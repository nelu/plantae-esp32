import ujson as json
import uasyncio as asyncio
import time
from .util import rid
from .errors import WampError, WampAbort, WampProtocolError, WampTimeout

# Import logging
from lib.logging import getLogger
LOG = getLogger("wamp")

# MicroPython-compatible coroutine check
def is_coroutine(obj):
    return hasattr(obj, '__await__') or str(type(obj)).find('generator') != -1

HELLO=1; WELCOME=2; ABORT=3; GOODBYE=6; ERROR=8
PUBLISH=16; PUBLISHED=17
SUBSCRIBE=32; SUBSCRIBED=33; EVENT=36
CALL=48; RESULT=50
REGISTER=64; REGISTERED=65; INVOCATION=68; YIELD=70

class WampConfig:
    def __init__(self, url, realm="realm1", roles=None, hello_details=None, call_timeout_s=10):
        self.url=url; self.realm=realm
        self.roles=roles or {"publisher":{}, "subscriber":{}, "caller":{}, "callee":{}}
        self.hello_details=hello_details or {}
        self.call_timeout_s=call_timeout_s

class WampClient:
    def __init__(self, ws, cfg: WampConfig):
        self.ws=ws; self.cfg=cfg; self.session_id=None
        self._pending={}; self._subs={}; self._regs={}
        self._alive=False

    async def open(self):
        details = {"roles": self.cfg.roles}
        hd = self.cfg.hello_details
        if hd:
            for k in hd:
                details[k] = hd[k]

        LOG.debug("Sending HELLO to realm: %s" % self.cfg.realm)
        await self._send([HELLO, self.cfg.realm, details])
        msg=await self._recv_msg()
        if msg[0]==WELCOME:
            LOG.info("Received WELCOME, session_id: %s" % msg[1])
            self.session_id=msg[1]; self._alive=True
            # Start the receive loop BEFORE returning
            asyncio.create_task(self._recv_loop())
            # Give the receive loop a moment to start
            await asyncio.sleep_ms(10)
        elif msg[0]==ABORT:
            LOG.error("Received ABORT: %s" % msg)
            raise WampAbort(msg[2], msg[1])
        else:
            LOG.error("Unexpected message: %s" % msg)
            raise WampProtocolError("Expected WELCOME/ABORT, got %r" % (msg,))

    async def close(self, reason="wamp.error.close_realm"):
        if not self._alive: return
        try: await self._send([GOODBYE, {}, reason])
        except: pass
        self._alive=False
        try: await self.ws.close()
        except: pass

    async def publish(self, topic, args=None, kwargs=None, acknowledge=False, options=None):
        req=rid()
        opts=options or {}
        if acknowledge: opts["acknowledge"]=True
        msg=[PUBLISH, req, opts, topic]
        if args is not None or kwargs is not None:
            msg.append(args or [])
        if kwargs is not None:
            if len(msg)==4: msg.append([])
            msg.append(kwargs)
        if acknowledge:
            fut=self._new_future(req)
            await self._send(msg)
            return await self._wait(fut)
        await self._send(msg); return None

    async def subscribe(self, topic, callback, options=None):
        req=rid(); fut=self._new_future(req)
        LOG.debug("Subscribing to topic: %s" % topic)
        await self._send([SUBSCRIBE, req, options or {}, topic])
        sub_id=await self._wait(fut)
        self._subs[sub_id]=callback
        LOG.debug("Subscribed to topic: %s with id: %s" % (topic, sub_id))
        return sub_id

    async def register(self, procedure, handler, options=None):
        req=rid(); fut=self._new_future(req)
        LOG.debug("Registering procedure: %s" % procedure)
        await self._send([REGISTER, req, options or {}, procedure])
        reg_id=await self._wait(fut)
        self._regs[reg_id]=handler
        LOG.debug("Registered procedure: %s with id: %s" % (procedure, reg_id))
        return reg_id

    async def call(self, procedure, args=None, kwargs=None, options=None, timeout_s=None):
        req=rid(); fut=self._new_future(req)
        msg=[CALL, req, options or {}, procedure]
        if args is not None or kwargs is not None:
            msg.append(args or [])
        if kwargs is not None:
            if len(msg)==4: msg.append([])
            msg.append(kwargs)
        await self._send(msg)
        return await self._wait(fut, timeout_s)

    async def _send(self, msg):
        await self.ws.send(json.dumps(msg))

    async def _recv_msg(self):
        raw=await self.ws.recv()
        if not raw:  # Empty string indicates connection closed
            return None
        try: return json.loads(raw)
        except: raise WampProtocolError("Bad JSON: %r" % raw)

    def _new_future(self, req_id):
        # Very simple future for MicroPython - just store the result
        result_holder = [None, None, False]  # [result, exception, done]
        self._pending[req_id] = result_holder
        return result_holder

    async def _wait(self, fut, timeout_s=None):
        t = timeout_s if timeout_s is not None else self.cfg.call_timeout_s
        start_time = time.ticks_ms()
        timeout_ms = int(t * 1000)
        
        while not fut[2]:  # while not done
            if time.ticks_diff(time.ticks_ms(), start_time) > timeout_ms:
                raise WampTimeout("Timeout")
            await asyncio.sleep_ms(10)
            
        if fut[1]:  # if exception
            raise fut[1]
        return fut[0]  # return result

    async def _recv_loop(self):
        while self._alive:
            try:
                msg=await self._recv_msg()
                if not msg:  # Empty message indicates connection closed
                    break
                mtype=msg[0]
            except OSError as e:
                # Handle connection closed or network errors
                LOG.debug("OSError in recv_loop: errno=%s" % getattr(e, 'errno', 'unknown'))
                if e.errno in (9, 104, 113):  # EBADF, ECONNRESET, EHOSTUNREACH
                    break
                raise
            except Exception as e:
                # Handle other errors (like WampProtocolError)
                LOG.debug("Exception in recv_loop: %s" % e)
                break
            if mtype==GOODBYE:
                self._alive=False; break
            if mtype==SUBSCRIBED:
                req_id, sub_id=msg[1], msg[2]
                fut=self._pending.pop(req_id, None)
                if fut: 
                    fut[0] = sub_id  # set result
                    fut[2] = True    # set done
            elif mtype==REGISTERED:
                req_id, reg_id=msg[1], msg[2]
                fut=self._pending.pop(req_id, None)
                if fut: 
                    fut[0] = reg_id  # set result
                    fut[2] = True    # set done
            elif mtype==EVENT:
                sub_id=msg[1]
                details=msg[3] if len(msg)>3 else {}
                args=msg[4] if len(msg)>4 else []
                kwargs=msg[5] if len(msg)>5 else {}
                cb=self._subs.get(sub_id)
                if cb:
                    r=cb(args, kwargs, details)
                    if is_coroutine(r): await r
            elif mtype==INVOCATION:
                inv_req, reg_id=msg[1], msg[2]
                details=msg[3] if len(msg)>3 else {}
                args=msg[4] if len(msg)>4 else []
                kwargs=msg[5] if len(msg)>5 else {}
                handler=self._regs.get(reg_id)
                if not handler:
                    await self._send([ERROR, INVOCATION, inv_req, {}, "wamp.error.no_such_procedure"])
                    continue
                try:
                    res=handler(args, kwargs, details)
                    if is_coroutine(res): res=await res
                    out_args, out_kwargs = [], {}
                    if res is None:
                        pass
                    elif isinstance(res, tuple) and len(res)==2 and isinstance(res[0], (list, tuple)) and isinstance(res[1], dict):
                        out_args=list(res[0]); out_kwargs=dict(res[1])
                    elif isinstance(res, (list, tuple)):
                        out_args=list(res)
                    else:
                        out_args=[res]
                    out=[YIELD, inv_req, {}]
                    if out_args or out_kwargs: out.append(out_args)
                    if out_kwargs:
                        if len(out)==3: out.append([])
                        out.append(out_kwargs)
                    await self._send(out)
                except Exception as e:
                    await self._send([ERROR, INVOCATION, inv_req, {}, "wamp.error.runtime_error", [str(e)], {}])
            elif mtype==RESULT:
                req_id=msg[1]
                details=msg[2] if len(msg)>2 else {}
                args=msg[3] if len(msg)>3 else []
                kwargs=msg[4] if len(msg)>4 else {}
                fut=self._pending.pop(req_id, None)
                if fut: 
                    fut[0] = (args, kwargs, details)  # set result
                    fut[2] = True                     # set done
            elif mtype==PUBLISHED:
                req_id, pub_id=msg[1], msg[2]
                fut=self._pending.pop(req_id, None)
                if fut: 
                    fut[0] = pub_id  # set result
                    fut[2] = True    # set done
            elif mtype==ERROR:
                req_id=msg[2]
                err_uri=msg[4] if len(msg)>4 else "wamp.error.unknown"
                args=msg[5] if len(msg)>5 else []
                fut=self._pending.pop(req_id, None)
                if fut: 
                    fut[1] = WampError("%s %s" % (err_uri, args[0] if args else ""))  # set exception
                    fut[2] = True                                                     # set done
