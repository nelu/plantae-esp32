"""WAMP client for MicroPython using WebSocket transport."""
import time
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
import ujson as json
from .websocket import WebSocketClient
from . import constants as C


def _handle_callback_result(result):
    """
    Handle the result of calling a callback function.
    Returns True if the result was async and a task was created, False otherwise.
    
    In MicroPython, async functions return generators when called as regular functions.
    In regular Python, async functions return coroutines.
    """
    if hasattr(result, '__await__'):
        # Regular Python coroutine
        asyncio.create_task(result)
        return True
    elif hasattr(result, '__next__'):
        # MicroPython async function (returns generator)
        asyncio.create_task(result)
        return True
    else:
        # Regular function result
        return False


async def _handle_callback_result_await(result):
    """
    Handle the result of calling a callback function that needs to be awaited.
    Returns the final result after awaiting if necessary.
    
    In MicroPython, async functions return generators when called as regular functions.
    In regular Python, async functions return coroutines.
    """
    if hasattr(result, '__await__'):
        # Regular Python coroutine
        return await result
    elif hasattr(result, '__next__'):
        # MicroPython async function (returns generator)
        return await result
    else:
        # Regular function result
        return result


class _RPCWaiter:
    """Simple container to await a single RPC result."""

    def __init__(self):
        self._evt = asyncio.Event()
        self.result = None
        self.error = None

    async def wait(self):
        await self._evt.wait()
        if self.error is not None:
            raise self.error
        return self.result

    def set_result(self, value):
        self.result = value
        self._evt.set()

    def set_error(self, exc):
        self.error = exc
        self._evt.set()


class AutobahnWS:
    """WAMP client for MicroPython, transport: WebSocket (ws/wss)."""

    def __init__(self, host, port, realm, path="/", use_ssl=False, ping_interval_s=None, idle_timeout_s=None):
        self.host = host
        self.port = port
        self.realm = realm
        self.path = path or "/"
        self.use_ssl = use_ssl
        self.ping_interval_s = ping_interval_s
        self.idle_timeout_s = idle_timeout_s

        self._ws = WebSocketClient(host, port, self.path, use_ssl=use_ssl)
        self._connected = False
        self._session_id = None
        self._next_request_id = 1

        self._pending_subscribes = {}
        self._subscriptions = {}
        self._pending_registers = {}
        self._registrations = {}
        self._pending_calls = {}
        self._pending_publishes = {}

        self._recv_task = None
        self._keepalive_task = None
        self._on_join = None
        self._connect_error = None

    async def connect(self, timeout_s=10):
        self._connected = False
        self._session_id = None
        self._connect_error = None

        await self._ws.connect()

        details = {"roles": {"publisher": {}, "subscriber": {}, "caller": {}, "callee": {}}}
        await self._ws.send_text(json.dumps([C.HELLO, self.realm, details]))

        if self._recv_task:
            try:
                self._recv_task.cancel()
            except Exception:
                pass
        self._recv_task = asyncio.create_task(self._recv_loop())

        if self.ping_interval_s is not None or self.idle_timeout_s is not None:
            if self._keepalive_task:
                try:
                    self._keepalive_task.cancel()
                except Exception:
                    pass
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        t0 = time.ticks_ms()
        while self._session_id is None and self._connect_error is None:
            await asyncio.sleep_ms(50)
            if time.ticks_diff(time.ticks_ms(), t0) > int(timeout_s * 1000):
                raise OSError("WAMP connect timeout (no WELCOME)")

        if self._connect_error is not None:
            raise OSError(self._connect_error)

        return True

    def is_connected(self):
        return self._connected

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
            await self._ws.send_text(json.dumps(msg))
            return await waiter.wait()

        await self._ws.send_text(json.dumps(msg))

    async def subscribe(self, topic, callback, options=None):
        request_id = self._next_id()
        waiter = _RPCWaiter()
        self._pending_subscribes[request_id] = {"topic": topic, "callback": callback, "waiter": waiter}
        await self._ws.send_text(json.dumps([C.SUBSCRIBE, request_id, options or {}, topic]))
        try:
            return await asyncio.wait_for(waiter.wait(), 5.0)
        except asyncio.TimeoutError:
            self._pending_subscribes.pop(request_id, None)
            raise Exception("WAMP SUBSCRIBE timed out")

    async def unsubscribe(self, topic):
        pass  # Not implemented to keep footprint small

    async def register(self, procedure, callback, options=None):
        request_id = self._next_id()
        self._pending_registers[request_id] = (procedure, callback)
        await self._ws.send_text(json.dumps([C.REGISTER, request_id, options or {}, procedure]))

    async def call(self, procedure, *args):
        request_id = self._next_id()
        waiter = _RPCWaiter()
        self._pending_calls[request_id] = waiter

        msg = [C.CALL, request_id, {}, procedure]
        if args:
            msg.append(list(args))
        await self._ws.send_text(json.dumps(msg))
        return await waiter.wait()

    async def close(self):
        try:
            if self._connected:
                await self._ws.send_text(json.dumps([C.GOODBYE, {}, "wamp.close.normal"]))
        except Exception:
            pass

        self._connected = False
        if self._recv_task:
            self._recv_task.cancel()
            self._recv_task = None
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None

        await self._ws.close()

    def _next_id(self):
        rid = self._next_request_id
        self._next_request_id += 1
        if self._next_request_id > 0x7FFFFFFF:
            self._next_request_id = 1
        return rid

    async def _recv_loop(self):
        try:
            while True:
                if self._session_id is not None and not self._connected:
                    break
                try:
                    text = await self._ws.recv_text()
                except OSError as e:
                    self._connected = False
                    if not self._session_id:
                        self._connect_error = "WebSocket connection failed: %s" % str(e)
                    break
                except Exception as e:
                    self._connected = False
                    if not self._session_id:
                        self._connect_error = "WebSocket error: %s" % str(e)
                    break

                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except Exception:
                    continue

                await self._handle_wamp_message(msg)
        except asyncio.CancelledError:
            pass
        finally:
            self._connected = False

    async def _keepalive_loop(self):
        ping_ms = int(self.ping_interval_s * 1000) if self.ping_interval_s else 25000
        idle_ms = int(self.idle_timeout_s * 1000) if self.idle_timeout_s else 180000

        try:
            # Wait for connection to be established before starting keepalive
            while not self._connected and self._connect_error is None:
                await asyncio.sleep_ms(50)
            
            while self._connected:
                await asyncio.sleep_ms(ping_ms)
                if not self._connected:
                    break

                if self.idle_timeout_s and self._ws._last_activity_ms:
                    if time.ticks_diff(time.ticks_ms(), self._ws._last_activity_ms) > idle_ms:
                        self._connected = False
                        break

                try:
                    await self._ws.send_ping()
                except Exception:
                    self._connected = False
                    break
        except asyncio.CancelledError:
            pass
        finally:
            # Only close if we were connected and now disconnected (not during initial connect)
            if self._session_id and not self._connected:
                try:
                    await self._ws.close()
                except Exception:
                    pass



    async def _handle_wamp_message(self, msg):
        if not isinstance(msg, list) or not msg:
            return
        code = msg[0]
        
        # Import logging for error handling
        from lib.logging import getLogger
        wamp = getLogger("wamp")
        # wamp.debug("RX WAMP msg: code=%s len=%d msg=%s", code, len(msg), msg)

        if code == C.WELCOME:
            self._session_id = msg[1]
            self._connected = True
            if self._on_join:
                try:
                    # Call the function and check if we get a coroutine
                    result = self._on_join()
                    _handle_callback_result(result)
                except Exception as e:
                    wamp.error("on_join callback failed: %s", e)
                    pass

        elif code == C.SUBSCRIBED:
            req_id, sub_id = msg[1], msg[2]
            # wamp.debug("SUBSCRIBED: req_id=%s sub_id=%s", req_id, sub_id)
            info = self._pending_subscribes.pop(req_id, None)
            if info:
                # wamp.debug("Storing subscription: sub_id=%s topic=%s", sub_id, info.get("topic"))
                self._subscriptions[str(sub_id)] = info["callback"]
                if "waiter" in info:
                    info["waiter"].set_result(sub_id)
            else:
                wamp.warning("No pending subscription found for req_id: %s", req_id)

        elif code == C.EVENT:
            # wamp.debug("Processing EVENT message: %s", msg)
            if len(msg) < 3:
                wamp.error("Invalid EVENT message format: %s", msg)
                return
                
            sub_id = msg[1]
            pub_id = msg[2]  # Publication ID
            details = msg[3] if len(msg) > 3 and isinstance(msg[3], dict) else {}
            args = msg[4] if len(msg) > 4 and isinstance(msg[4], list) else []
            kwargs = msg[5] if len(msg) > 5 and isinstance(msg[5], dict) else {}
            
            # wamp.debug("EVENT: sub_id=%s pub_id=%s details=%s args=%s kwargs=%s", 
            #            sub_id, pub_id, details, args, kwargs)
            
            cb = self._subscriptions.get(str(sub_id))
            # wamp.debug("Found callback for sub_id %s: %s", sub_id, cb is not None)
            # wamp.debug("Available subscriptions: %s", list(self._subscriptions.keys()))
            
            if cb:
                try:
                    # wamp.debug("Calling subscription callback...")
                    # wamp.debug("Callback type: %s", type(cb))
                    # wamp.debug("Callback: %s", cb)
                    
                    # Call the function and handle async/sync results
                    result = cb(args, kwargs, details)
                    
                    if _handle_callback_result(result):
                        # wamp.debug("Async subscription callback started successfully")
                        pass
                    else:
                        # wamp.debug("Subscription callback completed successfully")
                        # wamp.debug("Callback result: %s", result)
                        pass
                        
                except Exception as e:
                    wamp.error("Subscription callback failed: %s", e)
                    import sys
                    sys.print_exception(e)
            else:
                wamp.warning("No callback found for subscription ID: %s", sub_id)

        elif code == C.REGISTERED:
            req_id, reg_id = msg[1], msg[2]
            info = self._pending_registers.pop(req_id, None)
            if info:
                self._registrations[str(reg_id)] = info[1]

        elif code == C.INVOCATION:
            request_id, reg_id = msg[1], msg[2]
            details = msg[3] if len(msg) > 3 and isinstance(msg[3], dict) else {}
            args = msg[4] if len(msg) > 4 and isinstance(msg[4], list) else []
            kwargs = msg[5] if len(msg) > 5 and isinstance(msg[5], dict) else {}

            cb = self._registrations.get(str(reg_id))
            result = None
            if cb:
                try:
                    # Call the function and handle async/sync results
                    result = cb(args, kwargs, details)
                    result = await _handle_callback_result_await(result)
                except Exception as exc:
                    err_msg = [C.ERROR, C.INVOCATION, request_id, {}, ["wamp.error.runtime_error"], {"message": str(exc)}]
                    await self._ws.send_text(json.dumps(err_msg))
                    return

            resp = [C.YIELD, request_id, {}] if result is None else [C.YIELD, request_id, {}, [result]]
            await self._ws.send_text(json.dumps(resp))

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
            elif req_type == C.SUBSCRIBE and req_id in self._pending_subscribes:
                self._pending_subscribes.pop(req_id)["waiter"].set_error(Exception("WAMP SUBSCRIBE error: %s" % error_uri))

        elif code == C.GOODBYE:
            self._connected = False

        elif code == C.ABORT:
            reason = msg[2] if len(msg) > 2 else "wamp.error.close_realm"
            self._connected = False
            if not self._session_id:
                self._connect_error = "WAMP handshake aborted: %s" % reason
