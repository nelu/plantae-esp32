"""Minimal WebSocket client for MicroPython ESP32 using raw sockets."""
import binascii
import struct
import time
import uasyncio as asyncio
import urandom
from lib.logging import getLogger

LOG = getLogger("ws")


class WebSocketClient:
    """WebSocket client with text frames and masking (client side)."""

    def __init__(self, host, port, path="/", use_ssl=False, subprotocol="wamp.2.json", server_hostname=None):
        self.host = host
        self.port = port
        self.path = path or "/"
        self.use_ssl = use_ssl
        self.subprotocol = subprotocol
        self.server_hostname = server_hostname
        self._sock = None
        self._closed = False
        self._last_activity_ms = None
        self._rxbuf = b""
        self._tx_lock = None

    def _lock(self):
        if self._tx_lock is None:
            self._tx_lock = asyncio.Lock()
        return self._tx_lock

    async def connect(self):
        import gc, socket
        from .constants import WS_GUID

        gc.collect()
        self._closed = False
        self._rxbuf = b""

        # Resolve IP if self.host is not already an IP (though Supervisor ensures it is)
        addr = socket.getaddrinfo(self.host, self.port)[0][-1]
        
        # Aggressive GC before allocation
        gc.collect()
        self._sock = socket.socket()
        # self._sock.settimeout(10)  # Safe default matching diagnose_ssl.py
        self._sock.connect(addr)

        if self.use_ssl:
            import ssl

            # Use provided SNI hostname, or fallback to connection host
            sni_host = self.server_hostname if self.server_hostname else self.host
            
            # define context
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.verify_mode = ssl.CERT_NONE

            # Defrag (DISABLED: might be counter-productive with high RAM)
            # self._defrag_heap()
            
            # Blocking handshake
            # self._sock.setblocking(True) 
            self._sock.settimeout(10) # 10s timeout (better than infinite hang)
            
            # Wrap WITH server_hostname (Essential for Cloudflare/VHosts)
            LOG.info("SSL: Wrapping socket (SNI: %s)...", sni_host)
            try:
                gc.collect()  # <--- add: right before wrap_socket
                self._sock = ctx.wrap_socket(self._sock, server_hostname=sni_host)
            except Exception as e:
                # OSErr 16 means we need more RAM/Compaction. 
                # Retrying without SNI is futile for Cloudflare.
                LOG.error("SSL: Handshake failed: %s", e)
                # hard close immediately so next attempt isn't poisoned
                self._force_close()
                gc.collect()
                raise
            
            # Restore timeout
            # self._sock.settimeout(10) # Removed: SSLSocket lacks this method on some ports
        
        # Use SNI host for HTTP Header too
        http_host = self.server_hostname if self.server_hostname else self.host

        # import os
        # key_b64 = binascii.b2a_base64(os.urandom(16)).strip().decode()

        # no os.urandom
        key_raw = bytearray(16)
        struct.pack_into("!I", key_raw, 0, urandom.getrandbits(32))
        struct.pack_into("!I", key_raw, 4, urandom.getrandbits(32))
        struct.pack_into("!I", key_raw, 8, urandom.getrandbits(32))
        struct.pack_into("!I", key_raw, 12, urandom.getrandbits(32))

        key_b64 = binascii.b2a_base64(key_raw).strip().decode()

        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: %s\r\n\r\n"
               ) % (self.path, http_host, self.port, key_b64, self.subprotocol)

        self._sock.setblocking(True)
        self._sock.write(req.encode())

        status = self._sock.readline()
        if not status or not status.startswith(b"HTTP/1.1 101"):
            raise OSError("WebSocket handshake failed: %r" % status)

        headers = {}
        while True:
            line = self._sock.readline()
            if not line or line == b"\r\n":
                break
            try:
                k, v = line.decode().split(":", 1)
                headers[k.strip().lower()] = v.strip()
            except Exception:
                pass

        self._sock.setblocking(False)
        import uhashlib

        expected = binascii.b2a_base64(uhashlib.sha1((key_b64 + WS_GUID).encode()).digest()).strip().decode()
        if headers.get("sec-websocket-accept", "") != expected:
            raise OSError("Bad Sec-WebSocket-Accept")
        if headers.get("sec-websocket-protocol", "") != self.subprotocol:
            raise OSError("Subprotocol rejected")

        if LOG:
            LOG.debug("WS: connected to %s:%d%s sock=%r", self.host, self.port, self.path, self._sock)
        self._last_activity_ms = time.ticks_ms()

    async def send_ping(self):
        if self._closed or not self._sock:
            return
        try:
            mask_key = urandom.getrandbits(32).to_bytes(4, "big")
            header = struct.pack("!BB", 0x89, 0x80)
            async with self._lock():     # <-- ADD
                await self._sock_send(header + mask_key)
            self._last_activity_ms = time.ticks_ms()
        except Exception:
            self._closed = True
            raise

    async def _sock_send(self, data, timeout_ms=30000, max_chunk=None):
        if not self._sock:
            raise OSError("Socket not connected")

        if max_chunk is None:
            max_chunk = 512 if self.use_ssl else 1460

        mv = memoryview(data)
        total, sent = len(data), 0
        t0 = time.ticks_ms()

        while sent < total:
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                self._force_close()
                raise OSError("Socket send timeout")

            try:
                end = sent + max_chunk
                n = self._sock.write(mv[sent:end])

                # Treat 0 differently for non-SSL (usually means closed)
                if n == 0 and not self.use_ssl:
                    self._force_close()
                    raise OSError("Socket closed during send")

                if not n:
                    await asyncio.sleep_ms(5)
                    continue

                sent += n

            except OSError as e:
                errno = e.args[0] if e.args else None
                if errno in (11, -11):
                    await asyncio.sleep_ms(5)
                    continue

                # Connection errors: close hard so reconnect is clean
                self._force_close()
                raise

            if sent < total:
                await asyncio.sleep_ms(1)


    async def _sock_recv(self, n, timeout_ms=30000):
        if not self._sock:
            raise OSError("Socket not connected")

        if len(self._rxbuf) >= n:
            result, self._rxbuf = self._rxbuf[:n], self._rxbuf[n:]
            return result

        buf = bytearray(self._rxbuf)
        self._rxbuf = b""
        t0 = time.ticks_ms()

        while len(buf) < n:
            if not self._sock:
                raise OSError("Socket closed during recv")

            try:
                chunk = self._sock.read(n - len(buf))
                if chunk is None:
                    pass
                elif chunk == b"":
                    # peer closed
                    self._force_close()
                    raise OSError("Socket closed by peer")
                else:
                    buf.extend(chunk)

            except OSError as e:
                if e.args and e.args[0] not in (11, -11):
                    self._force_close()
                    raise

            if len(buf) < n:
                if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                    self._force_close()
                    raise OSError("Socket recv timeout")
                await asyncio.sleep_ms(10)

        return bytes(buf)

    def _force_close(self):
        self._closed = True
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None

    async def send_pong(self, payload):
        mask = urandom.getrandbits(32).to_bytes(4, "big")
        plen = len(payload)
        hdr = struct.pack("!BB", 0x8A, 0x80 | plen) if plen < 126 else struct.pack("!BBH", 0x8A, 0x80 | 126, plen)
        masked = bytearray(plen)
        for i in range(plen):
            masked[i] = payload[i] ^ mask[i % 4]
        async with self._lock():         # <-- ADD
            await self._sock_send(hdr + mask + bytes(masked))

    async def send_text(self, data):
        payload = data.encode() if isinstance(data, str) else data
        length = len(payload)

        if length < 126:
            header = struct.pack("!BB", 0x81, 0x80 | length)
        elif length < (1 << 16):
            header = struct.pack("!BBH", 0x81, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, length)

        mask = urandom.getrandbits(32).to_bytes(4, "big")
        masked = bytearray(length)
        for i in range(length):
            masked[i] = payload[i] ^ mask[i % 4]

        async with self._lock():         # <-- ADD (covers the whole frame)
            await self._sock_send(header)
            await self._sock_send(mask)
            await self._sock_send(masked)  # keep as bytearray

        self._last_activity_ms = time.ticks_ms()

    async def recv_text(self):
        # Loop instead of recursion to avoid stack overflow on ping/pong
        while True:
            if self._closed or not self._sock:
                raise OSError("WebSocket not connected")

            try:
                hdr = await self._sock_recv(2)
            except Exception as e:
                self._closed = True
                raise OSError("WebSocket read failed: %s" % e)

            if len(hdr) < 2:
                self._closed = True
                raise OSError("WebSocket connection closed")

            opcode = hdr[0] & 0x0F
            is_masked = hdr[1] & 0x80
            length = hdr[1] & 0x7F

            try:
                if length == 126:
                    length = struct.unpack("!H", await self._sock_recv(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", await self._sock_recv(8))[0]

                mask = await self._sock_recv(4) if is_masked else None
                payload = await self._sock_recv(length)
            except Exception as e:
                self._closed = True
                raise OSError("WebSocket read failed: %s" % e)

            if mask:
                payload = bytearray(payload)
                for i in range(length):
                    payload[i] ^= mask[i % 4]

            self._last_activity_ms = time.ticks_ms()

            if opcode == 0x8:  # close
                self._closed = True
                raise OSError("WebSocket closed by peer")
            if opcode == 0x9:  # ping -> pong, continue loop
                await self.send_pong(payload)
                continue
            if opcode == 0xA:  # pong -> ignore, continue loop
                continue
            if opcode != 0x1:  # not text -> skip, continue loop
                continue

            return payload.decode()

    async def close(self):
        if self._closed:
            return
        self._closed = True
        if self._sock:
            try:
                mask_key = urandom.getrandbits(32).to_bytes(4, "big")
                async with self._lock():
                    await self._sock_send(b"\x88\x80" + mask_key)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
