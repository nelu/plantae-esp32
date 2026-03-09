import time
import network
from ..adapters.wifi import Wifi
from logging import LOG
import uasyncio as asyncio
import ujson as json
import gc
import os
import socket

from ..adapters.http_api import HttpApi

AP_DEVICE_IP="192.168.110.1"

def ip_to_bytes(ip):
    return bytes(map(int, ip.split(".")))


async def dns_hijack_server(listen_ip="0.0.0.0", ap_ip=AP_DEVICE_IP):
    import struct
    # UDP/53 DNS server
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((listen_ip, 53))
    s.setblocking(False)

    ap_ip_b = ip_to_bytes(ap_ip)

    while True:
        try:
            data, addr = s.recvfrom(512)
        except OSError:
            await asyncio.sleep_ms(10)
            continue

        if len(data) < 12:
            continue

        # DNS header
        tid = data[0:2]
        flags = data[2:4]
        qdcount = struct.unpack("!H", data[4:6])[0]
        if qdcount < 1:
            continue

        # Find end of QNAME (labels ending with 0x00)
        i = 12
        while i < len(data) and data[i] != 0:
            i += 1 + data[i]
        i += 1  # skip 0 byte

        if i + 4 > len(data):
            continue

        qtype, qclass = struct.unpack("!HH", data[i:i + 4])
        question = data[12:i + 4]  # QNAME + QTYPE + QCLASS

        # Build response header: QR=1, RD copied, RA=0, RCODE=0
        # 0x8180 is a common "standard query response, no error"
        resp_flags = b"\x81\x80"

        # If query is type A (1) and class IN (1), include an A answer
        if qtype == 1 and qclass == 1:
            ancount = 1
            header = tid + resp_flags + struct.pack("!HHHH", 1, ancount, 0, 0)

            # Answer: NAME as pointer to question name at 0x0c -> 0xC00C
            answer = b"\xC0\x0C"  # NAME (pointer)
            answer += struct.pack("!HHI", 1, 1, 30)  # TYPE=A, CLASS=IN, TTL=30
            answer += struct.pack("!H", 4)  # RDLENGTH
            answer += ap_ip_b  # RDATA (your AP IP)

            resp = header + question + answer
        else:
            # No answers for other types (AAAA, etc.)
            header = tid + resp_flags + struct.pack("!HHHH", 1, 0, 0, 0)
            resp = header + question

        try:
            s.sendto(resp, addr)
        except OSError:
            LOG.warning('dns_hijack_server: Failed to responde with %s', ap_ip)
            pass


class ProvisionWifi(Wifi):
    def __init__(self):
        super().__init__()
        self.ap = network.WLAN(network.AP_IF)
        # self.ap.active(False)
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
        except Exception as e:
            LOG.error("start_ap: AP reset failed: %s", e)
            pass
        time.sleep_ms(500)

        # bring AP up first (ESP32 often requires this before config)
        self.ap.active(True)
        time.sleep_ms(500)

        # now configure SSID/auth
        if password:
            self.ap.config(essid=ssid, password=password, authmode=network.AUTH_WPA_WPA2_PSK)
        else:
            self.ap.config(essid=ssid, authmode=network.AUTH_OPEN)

        self._ap_ssid = ssid
        self.ap.ifconfig((AP_DEVICE_IP,'255.255.255.0',AP_DEVICE_IP,AP_DEVICE_IP))

        LOG.info("start_ap: %s - ifconfig %s", ssid, (self.ap.ifconfig(),))

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
