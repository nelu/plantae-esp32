import uasyncio as asyncio
import ujson as json

class HttpApi:
    def __init__(self, get_status, get_cfg, patch_cfg, schedule_reboot):
        self.get_status = get_status
        self.get_cfg = get_cfg
        self.patch_cfg = patch_cfg
        self.schedule_reboot = schedule_reboot

    async def serve(self, host="0.0.0.0", port=80):
        return await asyncio.start_server(self._handle, host, port)

    async def _handle(self, reader, writer):
        try:
            req = await reader.readline()
            if not req:
                await writer.aclose(); return
            method, path, _ = req.decode().split()
            clen = 0
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                if line.lower().startswith(b"content-length:"):
                    clen = int(line.split(b":",1)[1].strip() or b"0")
            body = b""
            if clen:
                body = await reader.readexactly(clen)

            if method == "GET" and path == "/status":
                await self._json(writer, self.get_status())
            elif method == "GET" and path == "/config":
                await self._json(writer, self.get_cfg())
            elif method == "POST" and path == "/config":
                patch = json.loads(body.decode() or "{}")
                self.patch_cfg(patch)
                await self._json(writer, {"ok": True})
            elif method == "POST" and path == "/reboot":
                await self._json(writer, {"ok": True})
                await writer.aclose()
                self.schedule_reboot(1)
                return
            else:
                await self._text(writer, "Not found", 404)
        except Exception:
            try: await self._text(writer, "Bad request", 400)
            except Exception: pass
        try: await writer.aclose()
        except Exception: pass

    async def _json(self, writer, obj, code=200):
        data = json.dumps(obj)
        hdr = "HTTP/1.1 %d OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: %d\r\n\r\n" % (code, len(data))
        writer.write(hdr.encode() + data.encode())
        await writer.drain()

    async def _text(self, writer, text, code=200):
        hdr = "HTTP/1.1 %d OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n" % (code, len(text))
        writer.write(hdr.encode() + text.encode())
        await writer.drain()
