"""WAMP client for MicroPython using WebSocket transport."""
import gc
import time

import uasyncio as asyncio
from lib import umsgpack

from lib.async_websocket_client.ws import AsyncWebsocketClient
from lib.logging import LOG
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

    def __init__(self, url, realm, ping_interval_s=30, idle_timeout_s=60, sni_host=None):
        self.url = url
        self.realm = realm
        self.sni_host = sni_host
        idle_ms = int(idle_timeout_s * 1000) if idle_timeout_s else None
        self._ws = AsyncWebsocketClient(idle_timeout_ms=idle_ms)  # Vovaman client
        self._connected = False
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

    async def connect(self, handshake_max_attempts=5, handshake_retry_delay_ms=1000):
        self._connected = False
        self._connect_error = None

        # Force the heap to settle to find the largest contiguous block
        gc.collect()
        await asyncio.sleep_ms(100)
        # Connect using the full URL and WAMP subprotocol
        attempt = 0
        while True:
            attempt += 1
            gc.collect()
            await asyncio.sleep_ms(50)
            try:
                # Vovaman handles SSL internally if the URL starts with wss://
                await self._ws.handshake(self.url, headers=[(b"Sec-WebSocket-Protocol", b"wamp.2.msgpack")],
                                      sni_host=self.sni_host)
                self._connect_error = None
                break
            except Exception as e:
                self._connect_error = str(e)
                if handshake_max_attempts is not None and attempt >= handshake_max_attempts:
                    raise
                await asyncio.sleep_ms(handshake_retry_delay_ms)


        if self._recv_task:
            self._recv_task.cancel()
        self._recv_task = asyncio.create_task(self._recv_loop())

        gc.collect()
        details = {"roles": {"publisher": {}, "subscriber": {}, "caller": {}, "callee": {}}}
        await self._send_msg([C.HELLO, self.realm, details])

        # if self.ping_interval_s is not None or self.idle_timeout_s is not None:
        #     if self._keepalive_task:
        #         try:
        #             self._keepalive_task.cancel()
        #         except Exception:
        #             pass
        #     self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        if self._connect_error is not None:
            raise OSError(self._connect_error)

        return True

    def is_connected(self):
        # Vovaman uses .open to indicate the stream is active
        return self._connected

    def on_join(self, cb):
        self._on_join = cb

    async def publish(self, topic, args=None, kwargs=None, options=None):
        request_id = self._next_id()
        opts = options or {}

        msg = [C.PUBLISH, request_id, opts, topic]
        if args is not None or kwargs is not None:
            msg.append(args or [])
        if kwargs is not None:
            if len(msg) == 4:
                msg.append([])
            msg.append(kwargs)

        if opts.get("acknowledge"):
            waiter = _RPCWaiter()
            self._pending_publishes[request_id] = waiter
            try:
                await self._send_msg(msg)
            except Exception as e:
                # ensure waiter doesn't hang forever
                self._pending_publishes.pop(request_id, None)
                waiter.set_error(e if isinstance(e, Exception) else OSError(str(e)))
                raise
            return await waiter.wait()

        await self._send_msg(msg)

    async def subscribe(self, topic, callback, options=None):
        request_id = self._next_id()
        self._pending_subscribes[request_id] = (topic, callback)
        await self._send_msg([C.SUBSCRIBE, request_id, options or {}, topic])

    async def unsubscribe(self, topic):
        pass  # Not implemented to keep footprint small

    async def register(self, procedure, callback, options=None):
        request_id = self._next_id()
        self._pending_registers[request_id] = (procedure, callback)
        await self._send_msg([C.REGISTER, request_id, options or {}, procedure])

    async def call(self, procedure, *args):
        request_id = self._next_id()
        waiter = _RPCWaiter()
        self._pending_calls[request_id] = waiter

        msg = [C.CALL, request_id, {}, procedure]
        if args:
            msg.append(list(args))
        await self._send_msg(msg)
        return await waiter.wait()

    async def close(self):
        try:
            if self._connected:
                await self._send_msg([C.GOODBYE, {}, "wamp.close.normal"])
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
                gc.collect()

                while await self._ws.open():
                    LOG.debug("awaiting recv...")
                    text = await self._ws.recv()

                    if text is None:
                        open_state = await self._ws.open()
                        LOG.warning("_recv_loop: Connection closed (recv returned None) mem_free=%d open=%s", gc.mem_free(), open_state)
                        if not open_state:
                            raise OSError("recv returned None")
                        await asyncio.sleep_ms(50)
                        continue

                    try:
                        if isinstance(text, str):
                            text = text.encode()
                        msg = umsgpack.loads(text)
                        await self._handle_wamp_message(msg)
                    except Exception as e:
                        print("WAMP: decode/processing error (msgpack): %s" % (e))
                        continue

        except Exception as e:
            LOG.error("WAMP: _recv_loop exception: %s" % e)
            self._disconnect("WAMP: Recv loop stopped")
            await asyncio.sleep(1)
            raise

    async def _send_msg(self, msg):
        encoded = umsgpack.dumps(msg)
        sent = await self._ws.send(encoded)

    async def send_ping(self, data=b''):
        """Send a low-level WebSocket PING frame."""
        if self._ws and await self._ws.open():
            try:
                # Based on your ws.py: write_frame(self, opcode, data=b'')
                # OP_PING is 0x09
                await self._ws.write_frame(0x09, data)
                if LOG: LOG.debug("WAMP: WebSocket PING sent len=%d", len(data) if data else 0)
            except Exception as e:
                print("WAMP: Failed to send PING: %s" % e)
                self._connected = False

    def start_keepalive(self):
        """Manually start the keepalive loop."""
        if self.ping_interval_s:
            # Cancel old task if it exists
            if hasattr(self, '_ping_task') and self._ping_task:
                self._ping_task.cancel()
            if LOG: LOG.info("WAMP: Keepalive starting (interval=%ss)", self.ping_interval_s)
            self._ping_task = asyncio.create_task(self._keepalive_loop())

    # inside AutobahnWS class (client.py)

    def _disconnect(self, reason="disconnected"):
        # set reason once
        if self._connect_error is None:
            self._connect_error = str(reason)

        self._connected = False

        exc = OSError(self._connect_error)

        # unblock anything awaiting RPC results / publish acks
        for waiter in self._pending_calls.values():
            try:
                waiter.set_error(exc)
            except Exception:
                pass
        self._pending_calls.clear()

        for waiter in self._pending_publishes.values():
            try:
                waiter.set_error(exc)
            except Exception:
                pass
        self._pending_publishes.clear()

        # these aren't awaited in your code, but clear to avoid leaks
        self._pending_subscribes.clear()
        self._pending_registers.clear()

    async def _keepalive_loop(self):
        LOG.info("WAMP: Keepalive loop started (interval: %ss)", self.ping_interval_s)
        ping_interval_ms = int(self.ping_interval_s * 1000)
        try:
            while self._connected:
                await asyncio.sleep(self.ping_interval_s)

                if not self._connected:
                    break

                if not await self._ws.open():
                    self._disconnect("keepalive detected closed socket")
                    break

                now = time.ticks_ms()
                last = getattr(self._ws, "last_activity_ms", now)
                idle_ms = time.ticks_diff(now, last)
                if idle_ms < ping_interval_ms:
                    if LOG: LOG.debug("WAMP: keepalive skipped, last activity %dms ago", idle_ms)
                    continue

                if LOG: LOG.debug("WAMP: keepalive ping mem_free=%d idle_ms=%d", gc.mem_free(), idle_ms)
                await self.send_ping()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._disconnect("keepalive error: %s" % e)
        finally:
            print("WAMP: Keepalive loop stopped")

    async def _handle_wamp_message(self, msg):
        if not isinstance(msg, list) or not msg:
            return
        code = msg[0]

        if code == C.WELCOME:
            self._connected = True
            if self._on_join:
                res = self._on_join(msg[1])
                if _is_awaitable(res):
                    asyncio.create_task(res)


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
                    await self._send_msg(err_msg)
                    return  # If result was None or a value, we just use it directly.

            resp = [C.YIELD, request_id, {}] if result is None else [C.YIELD, request_id, {}, [result]]
            await self._send_msg(resp)

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
            self._connect_error = "WAMP handshake aborted: %s" % reason
