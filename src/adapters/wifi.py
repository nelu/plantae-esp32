import uasyncio as asyncio
import network
import time

class Wifi:
    def __init__(self):
        self.sta = network.WLAN(network.STA_IF)
        self.ap  = network.WLAN(network.AP_IF)
        self.sta.active(True)
        self.ap.active(False)
        self._last_connect_ms = 0
        self._ap_ssid = None

    def is_connected(self):
        return self.sta.isconnected()

    def ip(self):
        return self.sta.ifconfig()[0] if self.sta.isconnected() else "0.0.0.0"

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

    async def ensure(self, ssid, password, timeout_s=20):
        if self.sta.isconnected():
            return True
        if not ssid:
            return False

        # If already trying to connect, don't call connect() again.
        status = self.sta.status()
        # Common status values: STAT_CONNECTING=1, STAT_GOT_IP=3 (varies by port)
        if status == network.STAT_CONNECTING:
            for _ in range(int(timeout_s * 2)):
                if self.sta.isconnected():
                    return True
                await asyncio.sleep(0.5)
            return self.sta.isconnected()

        # Throttle connect attempts (avoid hammering driver)
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_connect_ms) < 5000:
            await asyncio.sleep(1)
            return self.sta.isconnected()
        self._last_connect_ms = now

        try:
            self.sta.connect(ssid, password)
        except OSError as oe:
            # Driver got upset: reset interface and try again next loop
            try:
                self.sta.active(False)
                await asyncio.sleep(1)
                self.sta.active(True)
            except Exception:
                pass
            return False

        # Wait for connection
        for _ in range(int(timeout_s * 2)):
            if self.sta.isconnected():
                return True
            await asyncio.sleep(0.5)

        return self.sta.isconnected()
