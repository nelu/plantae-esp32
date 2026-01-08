import uasyncio as asyncio
import ujson as json

class HttpApi:
    def __init__(self, get_status, get_cfg, patch_cfg, schedule_reboot, pwm_out=None, flow_sensor=None):
        self.get_status = get_status
        self.get_cfg = get_cfg
        self.patch_cfg = patch_cfg
        self.schedule_reboot = schedule_reboot
        self.pwm_out = pwm_out
        self.flow_sensor = flow_sensor

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
            elif method == "POST" and path == "/pump":
                # Control pump PWM: POST /pump {"duty": 0.5, "duration_s": 10}
                try:
                    data = json.loads(body.decode() or "{}")
                    duty = float(data.get("duty", 0))
                    duration_s = data.get("duration_s", None)
                    
                    if self.pwm_out and 0 <= duty <= 1:
                        self.pwm_out.set(duty)
                        result = {"ok": True, "duty": duty}
                        if duration_s:
                            result["duration_s"] = duration_s
                            result["message"] = "Pump will run for %s seconds" % duration_s
                        await self._json(writer, result)
                    else:
                        await self._json(writer, {"error": "Invalid duty cycle (0-1)"}, 400)
                except (KeyError, ValueError):
                    await self._json(writer, {"error": "Invalid request"}, 400)
            elif method == "POST" and path == "/flow/reset":
                # Reset flow meter: POST /flow/reset
                try:
                    if hasattr(self, 'flow_sensor') and self.flow_sensor:
                        # Reset volume and pulse counters
                        self.flow_sensor._vol = 0.0
                        self.flow_sensor._total = 0
                        await self._json(writer, {"ok": True, "message": "Flow meter reset"})
                    else:
                        await self._json(writer, {"error": "Flow sensor not available"}, 400)
                except Exception as e:
                    await self._json(writer, {"error": str(e)}, 500)
            elif method == "POST" and path == "/flow/calibrate":
                # Calibrate flow meter: POST /flow/calibrate {"calibration": 450}
                try:
                    data = json.loads(body.decode() or "{}")
                    calibration = int(data.get("calibration", 0))
                    
                    # Update config via patch_cfg
                    self.patch_cfg({"flow": {"calibration": calibration}})
                    await self._json(writer, {"ok": True, "calibration": calibration})
                except (KeyError, ValueError) as e:
                    await self._json(writer, {"error": "Invalid calibration value"}, 400)
            elif method == "GET" and path == "/flow":
                # Get detailed flow information
                try:
                    status = self.get_status()
                    flow_data = status.get("flow", {})
                    config = self.get_cfg()
                    flow_config = config.get("flow", {})
                    
                    detailed_flow = {
                        "current": flow_data,
                        "config": flow_config,
                        "sensor_type": flow_config.get("type", "unknown"),
                        "calibration": flow_config.get("calibration", 0),
                        "pin": flow_config.get("pin", 0)
                    }
                    await self._json(writer, detailed_flow)
                except Exception as e:
                    await self._json(writer, {"error": str(e)}, 500)
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
