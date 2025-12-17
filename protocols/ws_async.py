"""
ws_async: minimal RFC6455 WebSocket client for MicroPython (async, text frames).

Features:
- ws:// support
- optional wss:// support (best-effort; depends on your MicroPython build)
- keepalive ping loop (optional)

API:
- await ws.send(str)
- await ws.recv() -> str
- await ws.close()
"""
import uasyncio as asyncio
import ubinascii, urandom, time

def _b64(x: bytes) -> bytes:
    return ubinascii.b2a_base64(x).strip()

def _mask(data: bytes, key: bytes) -> bytes:
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ key[i & 3]
    return bytes(out)

class WebSocket:
    def __init__(self, reader, writer):
        self._r = reader
        self._w = writer
        self._closed = False
        self._last_rx_ms = time.ticks_ms()
        self._ka_task = None

    def start_keepalive(self, ping_interval_s=20, idle_timeout_s=60):
        """
        Sends a ping every ping_interval_s.
        If no frame is received for idle_timeout_s, the socket is closed.
        """
        if ping_interval_s <= 0:
            return
        if idle_timeout_s < ping_interval_s:
            idle_timeout_s = ping_interval_s * 3
        if self._ka_task is None:
            self._ka_task = asyncio.create_task(self._keepalive(ping_interval_s, idle_timeout_s))

    async def _keepalive(self, ping_interval_s, idle_timeout_s):
        while not self._closed:
            await asyncio.sleep(ping_interval_s)
            if self._closed:
                break
            # if we're idle too long, close to force reconnect
            now = time.ticks_ms()
            if time.ticks_diff(now, self._last_rx_ms) > int(idle_timeout_s * 1000):
                await self.close()
                break
            try:
                await self._send_control(0x9, b"")  # ping
            except Exception:
                await self.close()
                break

    async def send(self, text: str):
        if self._closed:
            return
        payload = text.encode()
        mask_key = bytes([urandom.getrandbits(8) for _ in range(4)])
        header = bytearray()
        header.append(0x81)  # FIN + text
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(n.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(n.to_bytes(8, "big"))
        header.extend(mask_key)
        self._w.write(header)
        self._w.write(_mask(payload, mask_key))
        await self._w.drain()

    async def recv(self) -> str:
        """
        Receive ONE complete text message (reassembles continuation frames).
        Returns "" only when the connection is closed.
        """
        if self._closed:
            return ""

        msg = None  # bytearray for current text message, or None if not in a text message

        while True:
            try:
                b1 = (await self._r.readexactly(1))[0]
                b2 = (await self._r.readexactly(1))[0]
            except OSError as e:
                if getattr(e, "errno", None) == 9:  # EBADF
                    self._closed = True
                    return ""
                raise

            fin = (b1 & 0x80) != 0
            opcode = b1 & 0x0F
            masked = (b2 & 0x80) != 0
            ln = b2 & 0x7F

            if ln == 126:
                ln = int.from_bytes(await self._r.readexactly(2), "big")
            elif ln == 127:
                ln = int.from_bytes(await self._r.readexactly(8), "big")

            mask_key = await self._r.readexactly(4) if masked else None
            payload = await self._r.readexactly(ln) if ln else b""
            if masked and mask_key:
                payload = _mask(payload, mask_key)

            self._last_rx_ms = time.ticks_ms()

            # Control frames (must not be fragmented per RFC6455)
            if opcode == 0x8:  # close
                self._closed = True
                return ""
            if opcode == 0x9:  # ping -> pong
                await self._send_control(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue

            # Data frames
            if opcode == 0x1:  # text (start of a new text message)
                msg = bytearray()
                if payload:
                    msg.extend(payload)
                if fin:
                    try:
                        return msg.decode()
                    except Exception:
                        # Protocol-wise it's "text", but payload not UTF-8; ignore and keep reading.
                        msg = None
                        continue
                continue

            if opcode == 0x0:  # continuation
                if msg is None:
                    # Continuation without a started message -> ignore (or could close).
                    continue
                if payload:
                    msg.extend(payload)
                if fin:
                    try:
                        return msg.decode()
                    except Exception:
                        msg = None
                        continue
                continue

            if opcode == 0x2:  # binary
                # WAMP over JSON should not send binary. Ignore it to be robust.
                continue

            # Unknown opcode -> ignore for robustness
            continue


    async def __recv(self) -> str:
        if self._closed:
            return ""
        while True:
            try:
                b1 = (await self._r.readexactly(1))[0]
                b2 = (await self._r.readexactly(1))[0]
            except OSError as e:
                # Handle connection closed
                if e.errno == 9:  # EBADF
                    self._closed = True
                    return ""
                raise
            opcode = b1 & 0x0F
            masked = (b2 & 0x80) != 0
            ln = b2 & 0x7F
            if ln == 126:
                ln = int.from_bytes(await self._r.readexactly(2), "big")
            elif ln == 127:
                ln = int.from_bytes(await self._r.readexactly(8), "big")
            mask_key = await self._r.readexactly(4) if masked else None
            payload = await self._r.readexactly(ln) if ln else b""
            if masked and mask_key:
                payload = _mask(payload, mask_key)

            self._last_rx_ms = time.ticks_ms()

            if opcode == 0x8:  # close
                self._closed = True
                return ""
            if opcode == 0x9:  # ping -> pong
                await self._send_control(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode in (0x1, 0x0):  # text/continuation
                try:
                    return payload.decode()
                except Exception:
                    return ""

    async def _send_control(self, opcode, payload=b""):
        if self._closed:
            return
        # client->server must be masked
        mask_key = bytes([urandom.getrandbits(8) for _ in range(4)])
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        header.append(0x80 | len(payload))
        header.extend(mask_key)
        self._w.write(header)
        self._w.write(_mask(payload, mask_key))
        await self._w.drain()

    async def close(self):
        if self._closed:
            return
        try:
            await self._send_control(0x8, b"")
        except Exception:
            pass
        self._closed = True
        try:
            await self._w.aclose()
        except Exception:
            pass

async def connect(url: str, headers=None, ping_interval_s=20, idle_timeout_s=60) -> WebSocket:
    """
    url: ws://host[:port]/path  or  wss://host[:port]/path (best-effort)
    """
    import gc

    is_tls = url.startswith("wss://")
    if not (url.startswith("ws://") or is_tls):
        raise ValueError("Only ws:// or wss:// supported")
    rest = url[6:] if is_tls else url[5:]
    hostport, _, path = rest.partition("/")
    host, _, port_s = hostport.partition(":")
    port = int(port_s) if port_s else (443 if is_tls else 80)
    path = "/" + path

    # Best-effort TLS: many MicroPython builds support `ssl=True` in open_connection.
    try:
        if is_tls:
            gc.collect()
            # print("free:", gc.mem_free())
            reader, writer = await asyncio.open_connection(host, port, ssl=True)
        else:
            reader, writer = await asyncio.open_connection(host, port)
    except TypeError:
        # ssl kw not supported -> no TLS available here
        if is_tls:
            raise ValueError("This MicroPython build does not support TLS open_connection; use ws:// or a TLS-capable build.")
        reader, writer = await asyncio.open_connection(host, port)

    key = _b64(bytes([urandom.getrandbits(8) for _ in range(16)])).decode()
    req = [
        "GET %s HTTP/1.1" % path,
        "Host: %s:%d" % (host, port),
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: %s" % key,
        "Sec-WebSocket-Version: 13",
        "Sec-WebSocket-Protocol: wamp.2.json",
    ]
    if headers:
        for k, v in headers.items():
            req.append("%s: %s" % (k, v))
    req += ["", ""]
    writer.write("\r\n".join(req).encode())
    await writer.drain()

    status = await reader.readline()
    if not status.startswith(b"HTTP/1.1 101"):
        raise OSError("WS handshake failed: %r" % status)
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break

    ws = WebSocket(reader, writer)
    ws.start_keepalive(ping_interval_s=ping_interval_s, idle_timeout_s=idle_timeout_s)
    return ws
