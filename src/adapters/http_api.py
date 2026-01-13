import uasyncio as asyncio
import ujson as json
import gc


class HttpApi:
    def __init__(self, service):
        self.service = service

    async def serve(self, host="0.0.0.0", port=80):
        # Increased backlog helps with concurrent browser requests
        return await asyncio.start_server(self._handle, host, port, backlog=5)

    async def _handle(self, reader, writer):
        try:
            req = await reader.readline()
            if not req: return

            parts = req.decode().split()
            if len(parts) < 2: return
            method, path = parts[0], parts[1].split("?")[0]

            # Read headers to find Content-Length
            clen = 0
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""): break
                if line.lower().startswith(b"content-length:"):
                    clen = int(line.split(b":", 1)[1].strip() or b"0")

            body = await reader.readexactly(clen) if clen else b""
            handled  = True
            # Routing
            if method == "GET":
                if path == "/":
                    await self._text(writer, "Not found", 404)

                elif path == "/status":
                    await self._json(writer, self.service.get_status())

                elif path == "/config":
                    await self._json(writer, self.service.get_config())
                else:
                    handled = False

            elif method == "POST":
                if path == "/config":
                    self.service.patch_config(json.loads(body))
                    await self._json(writer, {"ok": True})
                elif path == "/reboot":
                    await self._json(writer, {"ok": True})
                    await writer.drain()
                    self.service.reboot(1)
                    return
                else:
                    handled = False

            if not handled:
                await self._text(writer, "Not found", 404)

        except Exception as e:
            print("Server Error:", e)  # Useful for debugging
            await self._text(writer, "Error", 400)
        finally:
            try:
                await writer.aclose()
            except Exception:
                pass            # CRITICAL: Force memory cleanup after every request
            gc.collect()

    async def _json(self, writer, obj):
        body = json.dumps(obj).encode()
        hdr = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(
            body)
        writer.write(hdr.encode())
        writer.write(body)
        await writer.drain()

    async def _text(self, writer, text, code):
        body = text.encode()
        hdr = "HTTP/1.1 %d OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % (code,
                                                                                                                 len(body))
        writer.write(hdr.encode())
        writer.write(body)
        await writer.drain()
