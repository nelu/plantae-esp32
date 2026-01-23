import time
import network
from adapters.wifi import Wifi
import uasyncio as asyncio
import ujson as json
import gc
import os

from adapters.http_api import HttpApi

class ProvisionWifi(Wifi):
    def __init__(self):
        super().__init__()
        self.ap = network.WLAN(network.AP_IF)
        self.ap.active(False)
        self._ap_ssid = None

    def ap_ip(self):
        return self.ap.ifconfig()[0] if self.ap.active() else "0.0.0.0"

    def ap_active(self):
        return self.ap.active()

    def start_ap(self, ssid, password=None):
        if self.ap.active() and self._ap_ssid == ssid:
            return

        # clean restart
        try:
            self.ap.active(False)
        except Exception:
            pass
        time.sleep_ms(300)

        # bring AP up first (ESP32 often requires this before config)
        self.ap.active(True)
        time.sleep_ms(300)

        # now configure SSID/auth
        if password:
            self.ap.config(essid=ssid, password=password, authmode=network.AUTH_WPA_WPA2_PSK)
        else:
            self.ap.config(essid=ssid, authmode=network.AUTH_OPEN)

        self._ap_ssid = ssid
        print("start_ap: AP ifconfig:", self.ap.ifconfig())

    def stop_ap(self):
        if self.ap.active():
            self.ap.active(False)
            self._ap_ssid = None

    async def test_credentials(self, ssid, password, timeout_s=20, dns_check=True):
        # Ensure STA is on for the test (task_wifi may have disabled it)
        try:
            self.sta.active(True)
        except Exception:
            pass

        try:
            self.sta.disconnect()
        except Exception:
            pass

        await asyncio.sleep_ms(200)

        ok = await self.ensure(ssid, password, timeout_s=timeout_s)

        res = {"connected": bool(ok), "status": int(self.sta.status()) if hasattr(self.sta, "status") else None,
            "ip": self.ip(), }

        if ok and dns_check:
            try:
                import socket
                socket.getaddrinfo("pool.ntp.org", 123)
                res["dns_ok"] = True
            except Exception:
                res["dns_ok"] = False

        return res





class ProvisionHttp(HttpApi):
    def __init__(self, service, wifi, html_path="/provision.html"):
        super().__init__(service)
        self.wifi = wifi
        self.html_path = html_path

    async def _handle(self, reader, writer):
        try:
            req = await reader.readline()
            if not req:
                return

            parts = req.decode().split()
            if len(parts) < 2:
                return

            method, path = parts[0], parts[1].split("?", 1)[0]

            clen = 0
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                if line.lower().startswith(b"content-length:"):
                    clen = int(line.split(b":", 1)[1].strip() or b"0")

            body = await reader.readexactly(clen) if clen else b""

            if method == "GET" and path == "/":
                await self._send_file(writer, self.html_path)
                return

            if method == "POST" and path == "/provisioning":
                try:
                    data = json.loads(body) if body else {}
                except Exception:
                    await self._json(writer, {"ok": False, "error": "bad json"})
                    return

                w = data.get("wifi")
                if not isinstance(w, dict):
                    w = data if isinstance(data, dict) else {}

                ssid = (w.get("ssid") or "").strip()
                pwd = (w.get("password") or "")

                if not ssid:
                    await self._json(writer, {"ok": False, "error": "missing ssid"})
                    return

                result = await self.wifi.test_credentials(ssid, pwd, timeout_s=20, dns_check=True)

                if result.get("connected"):
                    patch = data or {}
                    patch["wifi"] = {"ssid": ssid, "password": pwd}
                    self.service.patch_config(patch)
                    payload = {"ok": True, "saved": True, "rebooting": True}
                    payload.update(result)
                    await self._json(writer, payload)
                    await writer.drain()
                    self.service.reboot(3)
                    return

                # failed: revert STA so AP-only provisioning remains stable
                try:
                    self.wifi.sta.disconnect()
                    self.wifi.sta.active(False)
                except Exception:
                    pass

                payload = {"ok": False, "saved": False}
                payload.update(result)
                await self._json(writer, payload)
                return

            await self._text(writer, "Not found", 404)

        except Exception as e:
            print("ProvisionHttp error:", e)
            await self._text(writer, "Error", 400)
        finally:
            try:
                await writer.aclose()
            except Exception:
                pass
            gc.collect()

    async def _send_file(self, writer, filename):
        try:
            size = os.stat(filename)[6]
            # Content-Type is inferred as HTML to save logic/args
            hdr = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % size
            writer.write(hdr.encode())

            with open(filename, "rb") as f:
                # 256 or 512 is the sweet spot for ESP32 socket buffers
                buf = bytearray(256)
                mv = memoryview(buf)
                while True:
                    n = f.readinto(buf)
                    if not n:
                        break
                    writer.write(mv[:n])
                    await writer.drain()
        except OSError:
            await self._text(writer, "Not found", 404)
