import socket
import asyncio as a
import binascii as b
import random as r
from collections import namedtuple
import re
import struct
import ssl
import gc
import sys
import time
from lib.logging import LOG

# Opcodes
OP_CONT = const(0x0)
OP_TEXT = const(0x1)
OP_BYTES = const(0x2)
OP_CLOSE = const(0x8)
OP_PING = const(0x9)
OP_PONG = const(0xa)

# Close codes
CLOSE_OK = const(1000)
CLOSE_GOING_AWAY = const(1001)
CLOSE_PROTOCOL_ERROR = const(1002)
CLOSE_DATA_NOT_SUPPORTED = const(1003)
CLOSE_BAD_DATA = const(1007)
CLOSE_POLICY_VIOLATION = const(1008)
CLOSE_TOO_BIG = const(1009)
CLOSE_MISSING_EXTN = const(1010)
CLOSE_BAD_CONDITION = const(1011)

URL_RE = re.compile(r'(wss|ws)://([A-Za-z0-9-\.]+)(?:\:([0-9]+))?(/.+)?')
URI = namedtuple('URI', ('protocol', 'hostname', 'port', 'path'))

class AsyncWebsocketClient:
    def __init__(self, ms_delay_for_read: int = 5, idle_timeout_ms: int | None = None):
        self._open = False
        self.delay_read = ms_delay_for_read
        self.idle_timeout_ms = idle_timeout_ms
        self._lock_for_open = a.Lock()
        self._lock_for_write = a.Lock()
        self.sock = None
        self.last_activity_ms = time.ticks_ms()

    async def open(self, new_val=None):
        await self._lock_for_open.acquire()
        try:
            if new_val is not None:
                if not new_val and self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
                    self.sock = None
                self._open = new_val
                if new_val:
                    self.last_activity_ms = time.ticks_ms()
            return self._open
        finally:
            self._lock_for_open.release()


    async def close(self, code=None):
        if code is not None:
            print("Connection is closed. Code: ", code)
        return await self.open(False)

    def urlparse(self, uri):
        """Parse ws or wss:// URLs"""
        match = URL_RE.match(uri)
        if match:
            protocol, host, port, path = match.group(1), match.group(2), match.group(3), match.group(4)

            if protocol not in ['ws', 'wss']:
                raise ValueError('Scheme {} is invalid'.format(protocol))

            if port is None:
                port = (80, 443)[protocol == 'wss']

            return URI(protocol, host, int(port), path)

    async def a_readline(self):
        line = None
        while line is None:
            line = self.sock.readline()
            await a.sleep_ms(self.delay_read)

        return line

    async def a_read(self, size: int | None = None):
        if size == 0:
            return b''
        chunks = []

        while True:
            b = self.sock.read(size) # type: ignore
            await a.sleep_ms(self.delay_read) # type: ignore

            # Continue reading if the socket returns None
            if b is None: continue

            # In some cases, the socket will return an empty bytes
            # after PING or PONG frames, we need to ignore them.
            if len(b) == 0: break

            chunks.append(b)
            size -= len(b) # type: ignore

            # After reading the first chunk, we can break if size is None or 0
            if size is None or size == 0: break

        # Join all the chunks and return them
        return b''.join(chunks)

    async def a_read_exactly(self, n: int):
        buf = bytearray(n)
        mv = memoryview(buf)
        got = 0
        waited_ms = 0

        while got < n:
            chunk = self.sock.read(n - got)  # type: ignore
            await a.sleep_ms(self.delay_read)
            waited_ms += self.delay_read

            if chunk is None:
                if self.idle_timeout_ms and waited_ms >= self.idle_timeout_ms:
                    if LOG: LOG.warning("a_read_exactly: timeout waiting for %d/%d bytes", got, n)
                    raise TimeoutError("socket timed out while reading")
                continue
            if chunk == b'':
                # Treat as closed socket / EOF
                if LOG: LOG.warning("a_read_exactly: EOF after %d/%d bytes", got, n)
                raise EOFError("socket closed while reading")

            mv[got:got + len(chunk)] = chunk
            got += len(chunk)
            waited_ms = 0

        self.last_activity_ms = time.ticks_ms()

        return bytes(buf)

    async def handshake(self, uri, headers=[], keyfile=None, certfile=None, cafile=None, cert_reqs=0, sni_host=None):

        if self.sock:
            await self.close()

        self.sock = socket.socket()
        self.uri = self.urlparse(uri)
        ai = socket.getaddrinfo(self.uri.hostname, self.uri.port) # type: ignore
        addr = ai[0][4]

        host = sni_host or self.uri.hostname

        self.sock.settimeout(30.0)
        self.sock.connect(addr)
        # self.sock.setblocking(False) - Keep blocking/timeout for handshake

        if self.uri.protocol == 'wss': # type: ignore
            cadata = None
            if not cafile is None:
                with open(cafile, 'rb') as f:
                    cadata = f.read()

            gc.collect()
            await a.sleep_ms(0)
            gc.collect()

            self.sock = ssl.wrap_socket(
                self.sock, server_side=False,
                key=keyfile, cert=certfile, # type: ignore
                cert_reqs=cert_reqs, # 0 - NONE, 1 - OPTIONAL, 2 - REQUIED
                cadata=cadata, # type: ignore
                server_hostname=host  # type: ignore
            )

        self.sock.setblocking(False)

        def send_header(header, *args):
            self.sock.write(header % args + '\r\n') # type: ignore

        # Sec-WebSocket-Key is 16 bytes of random base64 encoded
        key = b.b2a_base64(bytes(r.getrandbits(8)
                                        for _ in range(16)))[:-1]

        send_header(b'GET %s HTTP/1.1', self.uri.path or '/') # type: ignore
        send_header(b'Host: %s:%s', host, self.uri.port) # type: ignore
        send_header(b'Connection: Upgrade')
        send_header(b'Upgrade: websocket')
        send_header(b'Sec-WebSocket-Key: %s', key)
        send_header(b'Sec-WebSocket-Version: 13')
        send_header(b'Origin: http://{hostname}:{port}'.format( # type: ignore
            hostname=host, # type: ignore
            port=self.uri.port) # type: ignore
        )

        for key, value in headers:
            send_header(b'%s: %s', key, value)

        send_header(b'')

        line = await self.a_readline()
        header = (line)[:-2]
        if not header.startswith(b'HTTP/1.1 101 '):
            raise Exception(header)

        # We don't (currently) need these headers
        # FIXME: should we check the return key?
        while header:
            line = await self.a_readline()
            header = (line)[:-2]

        return await self.open(True)

    async def read_frame(self, max_size=None):
        # Frame header (must be exactly 2 bytes)
        byte1, byte2 = struct.unpack('!BB', await self.a_read_exactly(2))

        fin = bool(byte1 & 0x80)
        opcode = byte1 & 0x0f

        mask = bool(byte2 & (1 << 7))
        length = byte2 & 0x7f

        if length == 126:
            length, = struct.unpack('!H', await self.a_read_exactly(2))
        elif length == 127:
            length, = struct.unpack('!Q', await self.a_read_exactly(8))

        if max_size is not None and length > max_size:
            await self.close(code=CLOSE_TOO_BIG)
            return True, OP_CLOSE, None

        mask_bits = b""
        if mask:
            mask_bits = await self.a_read_exactly(4)

        try:
            data = await self.a_read_exactly(length)
        except MemoryError:
            await self.close(code=CLOSE_TOO_BIG)
            return True, OP_CLOSE, None

        if mask:
            data = bytes(b ^ mask_bits[i % 4] for i, b in enumerate(data))

        self.last_activity_ms = time.ticks_ms()
        # if LOG:
        #     try:
        #         LOG.debug("ws: frame fin=%s opcode=%s len=%d", fin, opcode, len(data) if data is not None else 0)
        #     except Exception:
        #         pass

        return fin, opcode, data

    # async def read_frame(self, max_size=None):
    #     # Frame header
    #     byte1, byte2 = struct.unpack('!BB', await self.a_read(2))
    #
    #     # Byte 1: FIN(1) _(1) _(1) _(1) OPCODE(4)
    #     fin = bool(byte1 & 0x80)
    #     opcode = byte1 & 0x0f
    #
    #     # Byte 2: MASK(1) LENGTH(7)
    #     mask = bool(byte2 & (1 << 7))
    #     length = byte2 & 0x7f
    #
    #     if length == 126:  # Magic number, length header is 2 bytes
    #         length, = struct.unpack('!H', await self.a_read(2))
    #     elif length == 127:  # Magic number, length header is 8 bytes
    #         length, = struct.unpack('!Q', await self.a_read(8))
    #
    #     if mask:  # Mask is 4 bytes
    #         mask_bits = await self.a_read(4)
    #
    #     try:
    #         data = await self.a_read(length)
    #     except MemoryError:
    #         # We can't receive this many bytes, close the socket
    #         await self.close(code=CLOSE_TOO_BIG)
    #         # await self._stream.drain()
    #         return True, OP_CLOSE, None
    #
    #     if mask:
    #         data = bytes(b ^ mask_bits[i % 4]
    #                      for i, b in enumerate(data))
    #
    #     return fin, opcode, data

    async def _awrite(self, data):
        if not data:
            return
        
        # In case we get a string (shouldn't happen with internal usage but safety first)
        if isinstance(data, str):
            data = data.encode('utf-8')
            
        mv = memoryview(data)
        total = len(data)
        written = 0
        
        while written < total:
            if not self.sock:
                raise OSError("Socket closed during write")
                
            try:
                n = self.sock.write(mv[written:])
                if n is None:
                    # Some ports return None for would-block
                    await a.sleep_ms(self.delay_read)
                    continue
                if n == 0:
                     # Should not happen on non-blocking unless closed or weird state
                     await a.sleep_ms(self.delay_read)
                     continue
                written += n
            except OSError as e:
                # errno 11 is EAGAIN
                if e.args[0] == 11:
                    await a.sleep_ms(self.delay_read)
                else:
                    raise

    async def write_frame(self, opcode, data=b''):
        await self._lock_for_write.acquire()
        try:
            fin = True
            mask = True  # messages sent by client are masked
    
            length = len(data)
            
            # Frame header
            # Byte 1: FIN(1) _(1) _(1) _(1) OPCODE(4)
            byte1 = 0x80 if fin else 0
            byte1 |= opcode
    
            # Byte 2: MASK(1) LENGTH(7)
            byte2 = 0x80 if mask else 0
            
            header = b''
    
            if length < 126:  # 126 is magic value to use 2-byte length header
                byte2 |= length
                header = struct.pack('!BB', byte1, byte2)
    
            elif length < (1 << 16):  # Length fits in 2-bytes
                byte2 |= 126  # Magic code
                header = struct.pack('!BBH', byte1, byte2, length)
    
            elif length < (1 << 64):
                byte2 |= 127  # Magic code
                header = struct.pack('!BBQ', byte1, byte2, length)
    
            else:
                raise ValueError()
            
            # Write header
            await self._awrite(header)
    
            if mask:  # Mask is 4 bytes
                mask_bits = struct.pack('!I', r.getrandbits(32))
                await self._awrite(mask_bits)
                
                # Apply mask to data
                # Optimization: for small data, this list comp is ok. 
                # For large data, we might want to chunk it? 
                # But 'data' is passed as bytes, so we have it all in RAM anyway.
                masked_data = bytes(b ^ mask_bits[i % 4] for i, b in enumerate(data))
                await self._awrite(masked_data)
            else:
                await self._awrite(data)
            self.last_activity_ms = time.ticks_ms()

        finally:
            self._lock_for_write.release()

    async def recv(self):
        while await self.open():
            try:
                fin, opcode, data = await self.read_frame()
            except EOFError as ex:
                # if LOG: LOG.warning("ws: EOF in recv: %s", ex)
                await self.open(False)
                return
            except TimeoutError as ex:
                # if LOG: LOG.warning("ws: Timeout in recv: %s", ex)
                await self.open(False)
                return
            except Exception as ex:
                # if LOG: LOG.error("ws: Exception in recv: %s", ex)
                try:
                    sys.print_exception(ex)
                except Exception:
                    pass
                await self.open(False)
                return

            if not fin:
                raise NotImplementedError()

            if opcode == OP_TEXT:
                return data.decode('utf-8')
            elif opcode == OP_BYTES:
                return data
            elif opcode == OP_CLOSE:
                close_code = None
                close_reason = ""
                try:
                    if data and len(data) >= 2:
                        close_code = struct.unpack('!H', data[:2])[0]
                        if len(data) > 2:
                            close_reason = data[2:].decode('utf-8', 'ignore')
                except Exception:
                    pass
                # if LOG: LOG.warning("ws: received CLOSE frame code=%s reason=%s", close_code, close_reason)
                await self.open(False)
                return
            elif opcode == OP_PONG:
                # if LOG: LOG.debug("ws: received PONG len=%d", len(data) if data else 0)
                self.last_activity_ms = time.ticks_ms()
                # Ignore this frame, keep waiting for a data frame
                continue
            elif opcode == OP_PING:
                try:
                    # if LOG: LOG.debug("ws: received PING len=%d", len(data) if data else 0)
                    self.last_activity_ms = time.ticks_ms()
                    # if LOG: LOG.debug("ws: sending PONG len=%d open=%s sock=%s", len(data) if data else 0, await self.open(), self.sock)
                    await self.write_frame(OP_PONG, data)
                    # if LOG: LOG.debug("ws: sent PONG len=%d", len(data) if data else 0)

                    # And then continue to wait for a data frame
                    continue
                except Exception as ex:
                    if LOG: LOG.error("ws: Error sending PONG: %s", ex)
                    try:
                        sys.print_exception(ex)
                    except Exception:
                        pass
                    # If sending the pong frame fails, close the connection
                    await self.open(False)
                    return
            elif opcode == OP_CONT:
                # This is a continuation of a previous frame
                raise NotImplementedError(opcode)
            else:
                raise ValueError(opcode)

    async def send(self, buf):
        if not await self.open():
            return
        if isinstance(buf, str):
            opcode = OP_TEXT
            buf = buf.encode('utf-8')
        elif isinstance(buf, bytes):
            opcode = OP_BYTES
        else:
            raise TypeError()
        await self.write_frame(opcode, buf)
