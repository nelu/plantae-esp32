"""WAMP client for MicroPython using WebSocket transport."""
import time
import uasyncio as asyncio
import ujson as json
from lib.async_websocket_client.ws import AsyncWebsocketClient
from . import constants as C


def _is_awaitable(obj):
    """Check if object is a generator/coroutine (MicroPython)."""
    return isinstance(obj, type((lambda: (yield))()))


class _RPCWaiter:
    __slots__ = ("_flag", "result", "error")

    def __init__(self):
        self._flag = asyncio.ThreadSafeFlag()
        self.result = None
        self.error = None

    async def wait(self):
        await self._flag.wait()
        if self.error is not None:
            raise self.error
        return self.result

    def set_result(self, value):
        self.result = value
        self._flag.set()

    def set_error(self, exc):
        self.error = exc
        self._flag.set()



class AutobahnWS:
    """WAMP client for MicroPython, transport: WebSocket (ws/wss)."""

    def __init__(self, url, realm, ping_interval_s=30,idle_timeout_s=60):
        self.url = url
        self.realm = realm
        self._ws = AsyncWebsocketClient()  # Vovaman client
        self._connected = False
        self._session_id = None
        self._next_request_id = 1
        self.ping_interval_s = ping_interval_s
        self.idle_timeout_s = idle_timeout_s

        self._pending_subscribes = {}
        self._subscriptions = {}
        self._pending_registers = {}
        self._registrations = {}
        self._pending_calls = {}
        self._pending_publishes = {}

        self._recv_task = None
        self._ping_task = None
        self._on_join = None
        self._connect_error = None

    async def connect(self, timeout_s=10):
        self._connected = False
        self._session_id = None
        self._connect_error = None

        import gc
        gc.collect()

        # Force the heap to settle to find the largest contiguous block
        import gc, time
        gc.collect()
        await asyncio.sleep_ms(100)
        gc.collect()
        # Connect using the full URL and WAMP subprotocol
        try:
            # Vovaman handles SSL internally if the URL starts with wss://
            await self._ws.handshake(self.url, headers=[(b"Sec-WebSocket-Protocol", b"wamp.2.json")])
        except Exception as e:
            self._connect_error = str(e)
            raise

        details = {"roles": {"publisher": {}, "subscriber": {}, "caller": {}, "callee": {}}}
        await self.send_text(json.dumps([C.HELLO, self.realm, details]))

        if self._recv_task:
            self._recv_task.cancel()
        self._recv_task = asyncio.create_task(self._recv_loop())


        # if self.ping_interval_s is not None or self.idle_timeout_s is not None:
        #     if self._keepalive_task:
        #         try:
        #             self._keepalive_task.cancel()
        #         except Exception:
        #             pass
        #     self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        t0 = time.ticks_ms()
        while self._session_id is None and self._connect_error is None:
            await asyncio.sleep_ms(50)
            if time.ticks_diff(time.ticks_ms(), t0) > int(timeout_s * 1000):
                raise OSError("WAMP connect timeout (no WELCOME)")

        if self._connect_error is not None:
            raise OSError(self._connect_error)

        if self.ping_interval_s:
            # Cancel old task if it exists
            if hasattr(self, '_ping_task') and self._ping_task:
                self._ping_task.cancel()
            self._ping_task = asyncio.create_task(self._keepalive_loop())

        return True

    def is_connected(self):
        # Vovaman uses .open to indicate the stream is active
        return bool(self._ws) and self._connected

    def on_join(self, cb):
        self._on_join = cb

    async def publish(self, topic, args=None, kwargs=None, acknowledge=False, options=None):
        request_id = self._next_id()
        opts = options or {}
        if acknowledge:
            opts["acknowledge"] = True
        msg = [C.PUBLISH, request_id, opts, topic]
        if args is not None or kwargs is not None:
            msg.append(args or [])
        if kwargs is not None:
            if len(msg) == 4:
                msg.append([])
            msg.append(kwargs)

        if acknowledge:
            waiter = _RPCWaiter()
            self._pending_publishes[request_id] = waiter
            await self.send_text(json.dumps(msg))
            return await waiter.wait()

        await self.send_text(json.dumps(msg))

    async def subscribe(self, topic, callback, options=None):
        request_id = self._next_id()
        self._pending_subscribes[request_id] = (topic, callback)
        await self.send_text(json.dumps([C.SUBSCRIBE, request_id, options or {}, topic]))

    async def unsubscribe(self, topic):
        pass  # Not implemented to keep footprint small

    async def register(self, procedure, callback, options=None):
        request_id = self._next_id()
        self._pending_registers[request_id] = (procedure, callback)
        await self.send_text(json.dumps([C.REGISTER, request_id, options or {}, procedure]))

    async def call(self, procedure, *args):
        request_id = self._next_id()
        waiter = _RPCWaiter()
        self._pending_calls[request_id] = waiter

        msg = [C.CALL, request_id, {}, procedure]
        if args:
            msg.append(list(args))
        await self.send_text(json.dumps(msg))
        return await waiter.wait()

    async def close(self):
        try:
            if self._connected:
                await self.send_text(json.dumps([C.GOODBYE, {}, "wamp.close.normal"]))
        except Exception:
            pass

        self._connected = False

        if self._ping_task:
            self._ping_task.cancel()
            self._ping_task = None
        if self._recv_task:
            self._recv_task.cancel()
            self._recv_task = None
        if self._ws:
            await self._ws.open(False)  # Close Vovaman client
        
        # Clear all state to free memory
        self._pending_subscribes.clear()
        self._subscriptions.clear()
        self._pending_registers.clear()
        self._registrations.clear()
        self._pending_calls.clear()
        self._pending_publishes.clear()

    def _next_id(self):
        rid = self._next_request_id
        self._next_request_id += 1
        if self._next_request_id > 0x7FFFFFFF:
            self._next_request_id = 1
        return rid

    async def _recv_loop(self):
        try:
            while True:
                # 1. Check connection state
                if not self._ws or not await self._ws.open():
                    break

                # 2. Vovaman's high-level recv()
                # returns string for text frames, bytes for binary
                text = await self._ws.recv()

                if text is None:
                    # LOG.info("WAMP: Connection closed (recv returned None)")
                    break

                try:
                    # Parse the JSON string into WAMP message
                    msg = json.loads(text)
                    await self._handle_wamp_message(msg)
                except Exception as e:
                    print("WAMP: JSON/Processing error: %s" % e)
                    # LOG.error("WAMP: JSON/Processing error: %s" % e)
                    continue

        except Exception as e:
            print("WAMP: Recv loop exception: %s" % e)
            #LOG.error("WAMP: Recv loop exception: %s" % e)
        finally:
            self._connected = False
            self._session_id = None
            #LOG.info("WAMP: Recv loop stopped")
            print("WAMP: Recv loop stopped")

    async def send_text(self, data):
        """Helper to send WAMP JSON strings"""
        if not self._ws or not await self._ws.open():
            return
        await self._ws.send(data)

    async def send_ping(self, data=b''):
        """Send a low-level WebSocket PING frame."""
        if self._ws and await self._ws.open():
            try:
                # Based on your ws.py: write_frame(self, opcode, data=b'')
                # OP_PING is 0x09
                self._ws.write_frame(0x09, data)
                # LOG.debug("WAMP: WebSocket PING sent")
            except Exception as e:
                print("WAMP: Failed to send PING: %s" % e)
                self._connected = False

    async def _keepalive_loop(self):
        """Background task to send periodic PING frames."""
        print("WAMP: Keepalive loop started (interval: %ss)" % self.ping_interval_s)
        try:
            while self._connected:
                await asyncio.sleep(self.ping_interval_s)

                if not self._connected:
                    break

                # Verify connection is still open before pinging
                if not await self._ws.open():
                    print("WAMP: Keepalive detected closed socket")
                    self._connected = False
                    break

                await self.send_ping()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print("WAMP: Keepalive loop error: %s" % e)
        finally:
            print("WAMP: Keepalive loop stopped")

    async def _handle_wamp_message(self, msg):
        if not isinstance(msg, list) or not msg:
            return
        code = msg[0]

        if code == C.WELCOME:
            self._session_id = msg[1]
            self._connected = True
            if self._on_join:
                try:
                    res = self._on_join()
                    if _is_awaitable(res):
                        asyncio.create_task(res)
                except Exception:
                    pass

        elif code == C.SUBSCRIBED:
            req_id, sub_id = msg[1], msg[2]
            info = self._pending_subscribes.pop(req_id, None)
            if info:
                self._subscriptions[str(sub_id)] = info[1]

        elif code == C.EVENT:
            if len(msg) < 3:
                # log error if possible, or just ignore invalid format
                return
            
            sub_id = msg[1]
            pub_id = msg[2]
            
            details = msg[3] if len(msg) > 3 and isinstance(msg[3], dict) else {}
            args = msg[4] if len(msg) > 4 and isinstance(msg[4], list) else []
            kwargs = msg[5] if len(msg) > 5 and isinstance(msg[5], dict) else {}
            cb = self._subscriptions.get(str(sub_id))
            if cb:
                try:
                    res = cb(args, kwargs, details)
                    if _is_awaitable(res):
                        asyncio.create_task(res)
                except Exception:
                    pass

        elif code == C.REGISTERED:
            if len(msg) < 3: return
            req_id, reg_id = msg[1], msg[2]
            info = self._pending_registers.pop(req_id, None)
            if info:
                self._registrations[str(reg_id)] = info[1]

        elif code == C.INVOCATION:
            if len(msg) < 3: return
            request_id, reg_id = msg[1], msg[2]
            details = msg[3] if len(msg) > 3 and isinstance(msg[3], dict) else {}
            args = msg[4] if len(msg) > 4 and isinstance(msg[4], list) else []
            kwargs = msg[5] if len(msg) > 5 and isinstance(msg[5], dict) else {}

            cb = self._registrations.get(str(reg_id))
            result = None
            if cb:
                try:
                    result = cb(args, kwargs, details)
                    if _is_awaitable(result):
                        result = await result
                except Exception as exc:
                    # Fix: 4th item is Error URI (string), 5th is Args (list)
                    err_msg = [C.ERROR, C.INVOCATION, request_id, {}, "wamp.error.runtime_error", [str(exc)]]
                    await self.send_text(json.dumps(err_msg))
                    return
                # If result was None or a value, we just use it directly.

            resp = [C.YIELD, request_id, {}] if result is None else [C.YIELD, request_id, {}, [result]]
            await self.send_text(json.dumps(resp))

        elif code == C.RESULT:
            req_id = msg[1]
            waiter = self._pending_calls.pop(req_id, None)
            if waiter:
                args = msg[3] if len(msg) >= 4 and isinstance(msg[3], list) else []
                waiter.set_result(args[0] if args else None)

        elif code == C.PUBLISHED:
            req_id = msg[1]
            waiter = self._pending_publishes.pop(req_id, None)
            if waiter:
                waiter.set_result(msg[2] if len(msg) > 2 else None)

        elif code == C.ERROR:
            if len(msg) >= 5:
                req_type, req_id, error_uri = msg[1], msg[2], msg[4]
            else:
                req_type, req_id, error_uri = None, None, "wamp.error"

            if req_type == C.CALL and req_id in self._pending_calls:
                self._pending_calls.pop(req_id).set_error(Exception("WAMP CALL error: %s" % error_uri))
            elif req_type == C.PUBLISH and req_id in self._pending_publishes:
                self._pending_publishes.pop(req_id).set_error(Exception("WAMP PUBLISH error: %s" % error_uri))

        elif code == C.GOODBYE:
            self._connected = False

        elif code == C.ABORT:
            reason = msg[2] if len(msg) > 2 else "wamp.error.close_realm"
            self._connected = False
            if not self._session_id:
                self._connect_error = "WAMP handshake aborted: %s" % reason
