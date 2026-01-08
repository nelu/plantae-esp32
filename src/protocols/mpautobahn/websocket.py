"""Minimal WebSocket client for MicroPython ESP32 using raw sockets."""
import binascii
import os
import socket
import struct
import time
import uasyncio as asyncio
try:
    import urandom
except ImportError:
    import random as urandom
from .constants import WS_GUID
from lib.logging import getLogger

LOG = getLogger("ws")


class WebSocketClient:
    """WebSocket client with text frames and masking (client side)."""

    def __init__(self, host, port, path="/", use_ssl=False, subprotocol="wamp.2.json"):
        self.host = host
        self.port = port
        self.path = path or "/"
        self.use_ssl = use_ssl
        self.subprotocol = subprotocol
        self._sock = None
        self._closed = False
        self._last_activity_ms = None
        self._rxbuf = b""

    async def connect(self):
        import uhashlib, gc
        from lib.memory_optimizer import MemoryOptimizer
        
        # Ultra-aggressive memory cleanup before SSL connection
        self._closed = False
        self._rxbuf = b""
        
        # Use the memory optimizer for SSL preparation
        await MemoryOptimizer.prepare_for_ssl()
        
        addr = socket.getaddrinfo(self.host, self.port)[0][-1]
        self._sock = socket.socket()
        self._sock.settimeout(10)  # 10s timeout for connect/SSL
        self._sock.connect(addr)

        if self.use_ssl:
            # Log memory info before SSL attempt
            mem_info = MemoryOptimizer.get_memory_info()
            if mem_info:
                LOG.debug("Memory before SSL: %s", mem_info)
            
            # Additional memory preparation specifically for SSL
            await MemoryOptimizer.force_defragment()
            
            import ssl
            # Create SSL context with minimal memory footprint
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.verify_mode = ssl.CERT_NONE
            
            try:
                self._sock = ctx.wrap_socket(self._sock, server_hostname=self.host)
                LOG.debug("SSL handshake successful")
            except OSError as e:
                # If SSL fails, clean up socket and re-raise
                try:
                    self._sock.close()
                except:
                    pass
                self._sock = None
                
                # Enhanced cleanup for OSError 16
                if e.args and e.args[0] == 16:
                    await MemoryOptimizer.extreme_cleanup()
                
                raise

        # Generate WebSocket key with smaller buffer
        key_bytes = bytearray(16)
        for i in range(16):
            try:
                key_bytes[i] = urandom.getrandbits(8)
            except AttributeError:
                # Fallback for systems without urandom.getrandbits
                key_bytes[i] = urandom.randint(0, 255)
        key_b64 = binascii.b2a_base64(bytes(key_bytes)).strip().decode()
        
        # Build request string efficiently
        req_parts = [
            "GET ", self.path, " HTTP/1.1\r\n",
            "Host: ", self.host, ":", str(self.port), "\r\n",
            "Upgrade: websocket\r\n",
            "Connection: Upgrade\r\n",
            "Sec-WebSocket-Key: ", key_b64, "\r\n",
            "Sec-WebSocket-Version: 13\r\n",
            "Sec-WebSocket-Protocol: ", self.subprotocol, "\r\n\r\n"
        ]
        req = "".join(req_parts)

        self._sock.setblocking(True)
        req_bytes = req.encode()
        self._sock.write(req_bytes)
        del req_bytes  # Free memory immediately

        # Read response with smaller buffer to reduce memory pressure
        status = self._sock.readline()
        if not status or not status.startswith(b"HTTP/1.1 101"):
            raise OSError("WebSocket handshake failed: %r" % status)

        headers = {}
        while True:
            line = self._sock.readline()
            if not line or line == b"\r\n":
                break
            try:
                line_str = line.decode()
                colon_pos = line_str.find(":")
                if colon_pos > 0:
                    k = line_str[:colon_pos].strip().lower()
                    v = line_str[colon_pos+1:].strip()
                    headers[k] = v
            except Exception:
                pass

        self._sock.setblocking(False)

        # Verify handshake with minimal memory usage
        expected_key = key_b64 + WS_GUID
        expected_hash = uhashlib.sha1(expected_key.encode()).digest()
        expected = binascii.b2a_base64(expected_hash).strip().decode()
        
        if headers.get("sec-websocket-accept", "") != expected:
            raise OSError("Bad Sec-WebSocket-Accept")
        if headers.get("sec-websocket-protocol", "") != self.subprotocol:
            raise OSError("Subprotocol rejected")

        # Final cleanup
        del headers, expected_key, expected_hash, expected
        gc.collect()

        # LOG.debug("WS: connected to %s:%d%s sock=%r", self.host, self.port, self.path, self._sock)
        self._last_activity_ms = time.ticks_ms()

    async def send_ping(self):
        if self._closed or not self._sock:
            return
        try:
            try:
                mask_key = urandom.getrandbits(32).to_bytes(4, "big")
            except AttributeError:
                # Fallback for systems without urandom.getrandbits
                mask_key = bytes([urandom.randint(0, 255) for _ in range(4)])
            header = struct.pack("!BB", 0x89, 0x80)
            await self._sock_send(header + mask_key)
            self._last_activity_ms = time.ticks_ms()
        except Exception:
            self._closed = True
            raise

    async def _sock_send(self, data):
        if not self._sock:
            raise OSError("Socket not connected")
        mv = memoryview(data)
        total, sent = len(data), 0
        t0 = time.ticks_ms()
        while sent < total:
            try:
                n = self._sock.write(mv[sent:])
                sent += n if n else 0
            except OSError as e:
                if e.args[0] in (11, -11):
                    await asyncio.sleep_ms(5)
                    if time.ticks_diff(time.ticks_ms(), t0) > 30000:
                        raise OSError("Socket send timeout")
                    continue
                raise
            if sent < total:
                await asyncio.sleep_ms(1)

    async def _sock_recv(self, n, timeout_ms=30000):
        if not self._sock:
            raise OSError("Socket not connected")
            
        if len(self._rxbuf) >= n:
            result, self._rxbuf = self._rxbuf[:n], self._rxbuf[n:]
            return result

        # Use smaller initial buffer to reduce memory pressure
        buf = bytearray(self._rxbuf)
        self._rxbuf = b""
        t0 = time.ticks_ms()

        while len(buf) < n:
            if not self._sock:
                raise OSError("Socket closed during recv")
            try:
                # Read in smaller chunks to reduce memory allocation pressure
                chunk_size = min(512, n - len(buf))  # Max 512 bytes per read
                chunk = self._sock.read(chunk_size)
                if chunk:
                    buf.extend(chunk)
            except OSError as e:
                if e.args[0] not in (11, -11):
                    raise

            if len(buf) < n:
                if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                    raise OSError("Socket recv timeout")
                await asyncio.sleep_ms(10)

        return bytes(buf)

    async def _send_pong(self, payload):
        try:
            mask = urandom.getrandbits(32).to_bytes(4, "big")
        except AttributeError:
            # Fallback for systems without urandom.getrandbits
            mask = bytes([urandom.randint(0, 255) for _ in range(4)])
        plen = len(payload)
        hdr = struct.pack("!BB", 0x8A, 0x80 | plen) if plen < 126 else struct.pack("!BBH", 0x8A, 0x80 | 126, plen)
        masked = bytearray(plen)
        for i in range(plen):
            masked[i] = payload[i] ^ mask[i % 4]
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

        try:
            mask = urandom.getrandbits(32).to_bytes(4, "big")
        except AttributeError:
            # Fallback for systems without urandom.getrandbits
            mask = bytes([urandom.randint(0, 255) for _ in range(4)])
        masked = bytearray(length)
        for i in range(length):
            masked[i] = payload[i] ^ mask[i % 4]

        await self._sock_send(header + mask + bytes(masked))
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
                await self._send_pong(payload)
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
                try:
                    mask_key = urandom.getrandbits(32).to_bytes(4, "big")
                except AttributeError:
                    # Fallback for systems without urandom.getrandbits
                    mask_key = bytes([urandom.randint(0, 255) for _ in range(4)])
                self._sock.write(b"\x88\x80" + mask_key)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
