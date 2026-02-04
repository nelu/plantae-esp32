import gc
import os
import time

try:
    import types

    _GenType = types.GeneratorType
except Exception:
    _GenType = ()
import ubinascii
import uasyncio as asyncio

import ssl  # type: ignore

from umsgpack import dumps as msgpack_dumps, loads as msgpack_loads  # type: ignore

try:
    # from logging import Logger, DEBUG  # type: ignore
    # LOG = Logger('wamp', DEBUG)
    from logging import LOG

except Exception:
    Logger = None
    LOG = None


def monotonic_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _parse_url(url):
    if url.startswith("wss://"):
        scheme = "wss"
        rest = url[6:]
        default_port = 443
    elif url.startswith("ws://"):
        scheme = "ws"
        rest = url[5:]
        default_port = 80
    else:
        raise ValueError("Unsupported URL scheme: %s" % url)

    if "/" in rest:
        hostport, path = rest.split("/", 1)
        path = "/" + path
    else:
        hostport = rest
        path = "/"

    if ":" in hostport:
        host, port_str = hostport.split(":", 1)
        port = int(port_str)
    else:
        host = hostport
        port = default_port
    return scheme, host, port, path


def _log(level, msg, *args):
    logger = LOG
    if not logger:
        return
    fn = getattr(logger, level, None)
    if not fn:
        return
    try:
        fn(msg, *args)
    except Exception:
        pass


class WebSocketClosed(Exception):
    pass


class MicropythonWampClient:
    def __init__(self, url, realm,
                 token=None, reconnect=4, max_payload=4096,
                 opcode_logging=False, mem_logging=False):
        self.url = url
        self.realm = realm
        self.token = token
        self.reconnect = reconnect
        self.max_payload = max_payload
        self.opcode_logging = bool(opcode_logging)
        self.mem_logging = bool(mem_logging)

        self.scheme, self.host, self.port, self.path = _parse_url(url)
        self.reader = None
        self.writer = None
        self.session_id = None
        self.connected = False
        self._closing = False
        self._closed_ws = False
        self._sent_goodbye = False
        self._cleanup_done = False
        self._req_id = 1
        self._last_pong_ms = monotonic_ms()

        self._send_lock = asyncio.Lock()
        self._conn_lock = asyncio.Lock()

        # Subscriptions and registrations
        self._desired_subs = []  # list of (topic, options, callback)
        self._pending_subs = {}  # req_id -> (topic, callback, event)
        self._subs_by_id = {}  # sub_id -> (topic, callback)

        self._desired_regs = []  # list of (proc, options, handler)
        self._pending_regs = {}  # req_id -> (proc, handler, event)
        self._regs_by_id = {}  # reg_id -> (proc, handler)

        self._pending_calls = {}  # req_id -> callback

        self._recv_task = None

        # TX buffers reused to reduce per-frame allocations
        self._tx_mask = bytearray(4)
        # Max header size: 2 (base) + 8 (len) + 4 (mask)
        self._tx_header = bytearray(14)

    def _next_req(self):
        self._req_id += 1
        if self._req_id > 0xFFFFFFFF:
            self._req_id = 1
        return self._req_id

    async def run_forever(self):
        while not self._closing:
            try:
                await self.connect()
                if self._recv_task:
                    try:
                        await self._recv_task
                    finally:
                        self._recv_task = None
            except Exception as exc:
                if not self._closing:
                    _log("error", "error: %s", exc)
            finally:
                try:
                    gc.collect()
                except Exception:
                    pass
            if self._closing:
                break
            await asyncio.sleep(self.reconnect)
            try:
                gc.collect()
            except Exception:
                pass

    async def connect(self):
        async with self._conn_lock:
            try:
                try:
                    gc.collect()
                except Exception:
                    pass
                self._cleanup_done = False
                self._closed_ws = False
                self._sent_goodbye = False
                self._recv_task = None
                await self._open_socket()
                await self._handshake()
                self.connected = True
                self._last_pong_ms = monotonic_ms()
                self.session_id = None
                self._recv_task = asyncio.create_task(self._receiver_loop())
                await self._send_hello()
            except Exception as exc:
                try:
                    await self._close_ws()
                except Exception:
                    pass
                self.connected = False
                self.session_id = None
                self._recv_task = None
                if self.mem_logging:
                    try:
                        free = gc.mem_free() if hasattr(gc, "mem_free") else None
                        _log("debug", "connect failed: %s free=%s", exc, free)
                    except Exception:
                        pass
                raise
            finally:
                try:
                    gc.collect()
                except Exception:
                    pass

    async def disconnect(self):
        await self.close()

    async def close(self):
        if self._closing:
            return
        self._closing = True
        try:
            if self.session_id is not None and not self._sent_goodbye:
                try:
                    await self._send_goodbye()
                except Exception:
                    pass
        finally:
            await self._close_ws()
            await self._cleanup()

    # Application-facing API -------------------------------------------------
    async def subscribe(self, topic, on_event, options=None):
        options = options or {}
        self._desired_subs.append((topic, options, on_event))
        return await self._send_subscribe(topic, options, on_event)

    async def register(self, proc, handler, options=None):
        options = options or {}
        self._desired_regs.append((proc, options, handler))
        return await self._send_register(proc, options, handler)

    async def publish(self, topic, args=None, kwargs=None, options=None):
        options = options or {}
        args = args or []
        kwargs = kwargs or {}
        req_id = self._next_req()
        msg = [16, req_id, options, topic, args, kwargs]
        return await self._send_wamp(msg)

    async def call(self, proc, args=None, kwargs=None, on_result=None, options=None):
        options = options or {}
        args = args or []
        kwargs = kwargs or {}
        req_id = self._next_req()
        if on_result:
            self._pending_calls[req_id] = on_result
        msg = [48, req_id, options, proc, args, kwargs]
        return await self._send_wamp(msg)

    async def _maybe_resolve(self, res):
        if res is None:
            return None
        if hasattr(res, "__await__"):
            return await res
        if _GenType and isinstance(res, _GenType) or (hasattr(res, "send") and hasattr(res, "throw")):
            try:
                while True:
                    res.send(None)
            except StopIteration as stop:
                return stop.value
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    _log("error", "handler non-exception: type=%s value=%r", type(exc), exc)
                    exc = Exception("non-exception raised: %r" % exc)
                _log("error", "handler generator error: %s", exc)
                return None
            return None
        return res

    # Internal connection management ----------------------------------------
    async def _open_socket(self):
        use_ssl = self.scheme == "wss"
        _log("info", "connecting to %s:%d", self.host, self.port)
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port, ssl=use_ssl)

    async def _handshake(self):
        key = ubinascii.b2a_base64(os.urandom(16)).strip()
        lines = [
            "GET %s HTTP/1.1" % self.path,
            "Host: %s:%d" % (self.host, self.port),
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Key: %s" % key.decode(),
            "Sec-WebSocket-Version: 13",
            "Sec-WebSocket-Protocol: wamp.2.msgpack",
            "\r\n",
        ]
        req = "\r\n".join(lines)
        self.writer.write(req.encode())
        await self.writer.drain()
        status = await self.reader.readline()
        if not status or b"101" not in status:
            raise WebSocketClosed("bad handshake status")
        while True:
            line = await self.reader.readline()
            if not line or line in (b"\r\n", b"\n"):
                break

    async def _receiver_loop(self):
        try:
            while not self._closing:
                opcode, data = await self._read_frame()
                if self.opcode_logging:
                    _log("debug", "recv opcode=0x%X len=%d", opcode, len(data))
                if opcode == 0x8:  # CLOSE
                    raise WebSocketClosed("close frame")
                if opcode == 0x9:  # PING from server
                    self._last_pong_ms = monotonic_ms()
                    if self.opcode_logging:
                        _log("debug", "recv PING len=%d", len(data))
                    try:
                        await self._send_pong(data)
                        if self.opcode_logging:
                            _log("debug", "sent PONG len=%d", len(data))
                    except Exception as exc:
                        _log("error", "pong send failed: %s", exc)
                        await self._close_ws()
                        return
                elif opcode == 0xA:  # PONG
                    self._last_pong_ms = monotonic_ms()
                    if self.opcode_logging:
                        _log("debug", "recv PONG len=%d", len(data))
                elif opcode == 0x2:  # binary
                    await self._handle_wamp(data)
                else:
                    if self.opcode_logging:
                        _log("debug", "ignored opcode %d", opcode)
        except WebSocketClosed:
            pass
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                _log("warning", "receiver cancelled")
            else:
                if not isinstance(exc, Exception):
                    _log("warning", "receiver non-exception ignored: type=%s value=%r", type(exc), exc)
                else:
                    if str(exc) == "exceptions must derive from BaseException":
                        _log("warning", "receiver non-base exception ignored")
                    else:
                        _log("error", "receiver error: %s", exc)
        finally:
            await self._cleanup()

    async def _send_hello(self):
        details = {
            "roles": {
                "publisher": {},
                "subscriber": {},
                "caller": {},
                "callee": {},
            }
        }
        if self.token:
            details["authmethods"] = ["ticket", "anonymous"]
            details["authid"] = self.token
        else:
            details["authmethods"] = ["anonymous"]
        msg = [1, self.realm, details]
        await self._send_wamp(msg)

    async def _post_welcome(self):
        await self._replay_subscriptions()
        await self._replay_registrations()

        try:
            cb = getattr(self, "on_session_join", None)
            if cb:
                cb(self.session_id)
        except Exception as exc:
            _log("warning", "on_session_join failed: %s", exc)

    async def _replay_subscriptions(self):
        for topic, options, cb in self._desired_subs:
            await self._send_subscribe(topic, options, cb)

    async def _replay_registrations(self):
        for proc, options, handler in self._desired_regs:
            await self._send_register(proc, options, handler)

    async def _send_subscribe(self, topic, options, callback):
        req_id = self._next_req()
        ev = asyncio.Event()
        self._pending_subs[req_id] = (topic, callback, ev)
        msg = [32, req_id, options, topic]
        await self._send_wamp(msg)

        await ev.wait()
        for sub_id, entry in self._subs_by_id.items():
            if entry[0] == topic:
                return sub_id
        return None

    async def _send_register(self, proc, options, handler):
        req_id = self._next_req()
        ev = asyncio.Event()
        self._pending_regs[req_id] = (proc, handler, ev)
        msg = [64, req_id, options, proc]
        await self._send_wamp(msg)
        await ev.wait()
        for reg_id, entry in self._regs_by_id.items():
            if entry[0] == proc:
                return reg_id
        return None

    async def _yield(self, req_id, kwargs=None):
        kw = kwargs if kwargs is not None else {}
        msg = [70, req_id, {}, [], kw]
        await self._send_wamp(msg)

    # WAMP message handling --------------------------------------------------
    async def _handle_wamp(self, payload):
        try:
            msg = msgpack_loads(payload)
        except Exception as exc:
            _log("warning", "decode failed: %s", exc)
            return
        if not isinstance(msg, list) or not msg:
            return
        msg_type = msg[0]
        try:
            if msg_type == 2:  # WELCOME
                self.session_id = msg[1]
                _log("info", "joined session %s", self.session_id)
                try:
                    asyncio.create_task(self._post_welcome())
                except Exception as exc:
                    _log("error", "post_welcome schedule failed: %s", exc)
            elif msg_type == 4:  # CHALLENGE
                await self._handle_challenge(msg)
            elif msg_type == 6:  # GOODBYE
                await self._handle_goodbye(msg)
            elif msg_type == 33:  # SUBSCRIBED
                req_id, sub_id = msg[1], msg[2]
                pending = self._pending_subs.pop(req_id, None)
                if pending:
                    topic, cb, ev = pending
                    self._subs_by_id[sub_id] = (topic, cb)
                    if ev:
                        ev.set()
                    _log("info", "subscribed %s", topic)
            elif msg_type == 36:  # EVENT
                await self._handle_event(msg)
            elif msg_type == 65:  # REGISTERED
                req_id, reg_id = msg[1], msg[2]
                pending = self._pending_regs.pop(req_id, None)
                if pending:
                    proc, handler, ev = pending
                    self._regs_by_id[reg_id] = (proc, handler)
                    if ev:
                        ev.set()
                    _log("info", "registered %s", proc)
            elif msg_type == 17:  # PUBLISHED (acknowledge)
                if self.opcode_logging:
                    req_id = msg[1] if len(msg) > 1 else None
                    pub_id = msg[2] if len(msg) > 2 else None
                    _log("debug", "recv PUBLISHED ack req=%s pub=%s", req_id, pub_id)
            elif msg_type == 68:  # INVOCATION
                await self._handle_invocation(msg)
            elif msg_type == 50:  # RESULT
                await self._handle_result(msg)
            elif msg_type == 3:  # ABORT
                reason = msg[2] if len(msg) > 2 else ""
                details = msg[1] if len(msg) > 1 else {}
                _log("error", "abort received reason=%s details=%s", reason, details)
                await self._close_ws()
            elif msg_type == 8:  # ERROR (subscribe/register/call/publish)
                if len(msg) < 5:
                    _log("warning", "malformed ERROR msg: %r", msg)
                    return
                req_type = msg[1]
                req_id = msg[2]
                error_uri = msg[4]
                if req_type == 32:  # SUBSCRIBE
                    pending = self._pending_subs.pop(req_id, None)
                    if pending:
                        _, _, ev = pending
                        if ev:
                            ev.set()
                elif req_type == 64:  # REGISTER
                    pending = self._pending_regs.pop(req_id, None)
                    if pending:
                        _, _, ev = pending
                        if ev:
                            ev.set()
                elif req_type == 48:  # CALL
                    self._pending_calls.pop(req_id, None)
                elif req_type == 16:  # PUBLISH with acknowledge
                    pass
                _log("warning", "error msg type=%s req=%s err=%s", req_type, req_id, error_uri)
            else:
                _log("debug", "unhandled msg type %s", msg_type)
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                _log("warning", "wamp handler cancelled")
                return
            if not isinstance(exc, Exception):
                _log("error", "wamp handler non-exception: type=%s value=%r", type(exc), exc)
                exc = Exception("non-exception raised: %r" % exc)
            _log("error", "wamp handler error: %s", exc)
            await self.disconnect()
        return

    async def _handle_challenge(self, msg):
        if not self.token:
            _log("warning", "challenge but no token")
            return
        req = [5, self.token, {}]
        await self._send_wamp(req)

    async def _handle_goodbye(self, msg):
        reason = msg[2] if len(msg) > 2 else ""
        _log("info", "goodbye received reason=%s", reason)
        if not self._sent_goodbye:
            try:
                await self._send_goodbye(reply=True)
            except Exception:
                pass
        self.session_id = None
        await self._close_ws()

    async def _handle_event(self, msg):
        sub_id = msg[1]
        entry = self._subs_by_id.get(sub_id)
        if not entry:
            return
        topic, cb = entry
        args = msg[4] if len(msg) > 4 else []
        kwargs = msg[5] if len(msg) > 5 else {}
        try:
            res = cb(args, kwargs)
            await self._maybe_resolve(res)
        except BaseException as exc:
            if not isinstance(exc, Exception):
                _log("warning", "event handler non-exception for %s: type=%s value=%r", topic, type(exc), exc)
                exc = Exception("non-exception raised: %r" % exc)
            _log("warning", "event handler error for %s: %s", topic, exc)

    async def _handle_invocation(self, msg):
        req_id = msg[1]
        reg_id = msg[2]
        entry = self._regs_by_id.get(reg_id)
        args = msg[4] if len(msg) > 4 else []
        kwargs = msg[5] if len(msg) > 5 else {}
        try:
            if entry:
                _, handler = entry
                result = await self._maybe_resolve(handler(args, kwargs))
            else:
                result = {"ok": True}
        except BaseException as exc:
            if not isinstance(exc, Exception):
                _log("warning", "invocation non-exception: type=%s value=%r", type(exc), exc)
                exc = Exception("non-exception raised: %r" % exc)
            result = {"error": str(exc)}
        await self._yield(req_id, kwargs=result if isinstance(result, dict) else {"result": result})

    async def _handle_result(self, msg):
        req_id = msg[1]
        cb = self._pending_calls.pop(req_id, None)
        if cb:
            args = msg[3] if len(msg) > 3 else []
            kwargs = msg[4] if len(msg) > 4 else {}
            try:
                res = cb(args, kwargs)
                await self._maybe_resolve(res)
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    _log("warning", "result callback non-exception: type=%s value=%r", type(exc), exc)
                    exc = Exception("non-exception raised: %r" % exc)
                _log("warning", "result callback error: %s", exc)

    # Framing ---------------------------------------------------------------
    async def _send_wamp(self, obj):
        payload = msgpack_dumps(obj)
        if len(payload) > self.max_payload:
            _log("warning", "payload too large (%d bytes)", len(payload))
            return False
        await self._send_frame(0x2, payload)
        return True

    async def _send_goodbye(self, reply=False):
        self._sent_goodbye = True
        details = {}
        reason = "wamp.close.goodbye_and_out" if reply else "wamp.close.system_shutdown"
        msg = [6, details, reason]
        await self._send_wamp(msg)

    async def _send_pong(self, data=b""):
        # Fast path pong; still uses send lock but logs if it fails.
        await self._send_frame(0xA, data)

    async def _send_frame(self, opcode, data):
        async with self._send_lock:
            if self.writer is None:
                raise WebSocketClosed("writer missing")

            body = data if isinstance(data, bytearray) else bytearray(data)
            length = len(body)

            # Prepare mask bytes once, stored in self._tx_mask
            mask_bytes = os.urandom(4)
            for i in range(4):
                self._tx_mask[i] = mask_bytes[i]

            # Build header in reusable buffer
            hdr = self._tx_header
            hdr[0] = 0x80 | (opcode & 0x0F)
            if length <= 125:
                hdr[1] = 0x80 | length
                hdr_len = 2
            elif length < 65536:
                hdr[1] = 0x80 | 126
                hdr[2] = (length >> 8) & 0xFF
                hdr[3] = length & 0xFF
                hdr_len = 4
            else:
                hdr[1] = 0x80 | 127
                idx = 2
                for shift in (56, 48, 40, 32, 24, 16, 8, 0):
                    hdr[idx] = (length >> shift) & 0xFF
                    idx += 1
                hdr_len = 10

            start = hdr_len
            for i in range(4):
                hdr[start + i] = self._tx_mask[i]
            hdr_len += 4

            # Mask payload in place
            for i in range(length):
                body[i] ^= self._tx_mask[i & 3]

            self.writer.write(hdr[:hdr_len])
            self.writer.write(body)
            await self.writer.drain()

    async def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = await self.reader.read(n - len(buf))
            if not chunk:
                raise WebSocketClosed("socket closed")
            buf += chunk
        return buf

    async def _read_frame(self):
        hdr = await self._read_exact(2)
        b1, b2 = hdr[0], hdr[1]
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        length = b2 & 0x7F
        if length == 126:
            ext = await self._read_exact(2)
            length = (ext[0] << 8) | ext[1]
        elif length == 127:
            ext = await self._read_exact(8)
            length = 0
            for byte in ext:
                length = (length << 8) | byte
        mask_key = await self._read_exact(4) if masked else None
        data = await self._read_exact(length) if length else b""
        if masked and mask_key:
            data = bytes([data[i] ^ mask_key[i & 3] for i in range(len(data))])
        return opcode, data

    async def _close_ws(self):
        if self._closed_ws:
            return
        self._closed_ws = True
        if self.writer:
            try:
                await self._send_frame(0x8, b"")
            except Exception:
                pass
            try:
                self.writer.close()
                if hasattr(self.writer, "wait_closed"):
                    await self.writer.wait_closed()
            except Exception:
                pass
        self.connected = False
        self.writer = None
        self.reader = None

    async def _cleanup(self):
        if self._cleanup_done:
            return
        self._cleanup_done = True
        try:
            cb = getattr(self, "on_session_lost", None)
            if cb:
                cb()
        except Exception as exc:
            _log("warning", "on_session_lost failed: %s", exc)
        self.connected = False
        self.session_id = None
        self._pending_subs.clear()
        self._pending_regs.clear()
        self._pending_calls.clear()
        self._subs_by_id.clear()
        self._regs_by_id.clear()
        if self._recv_task:
            try:
                if self._recv_task is not asyncio.current_task():
                    self._recv_task.cancel()
                    try:
                        await self._recv_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
            finally:
                self._recv_task = None
        if self.writer:
            try:
                self.writer.close()
            except Exception:
                pass
        self.writer = None
        self.reader = None
        try:
            gc.collect()
        except Exception:
            pass
