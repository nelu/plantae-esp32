import uasyncio as asyncio
import network
import time

class Wifi:
    def __init__(self):
        self.sta = network.WLAN(network.STA_IF)
        self.sta.active(True)
        self._last_connect_ms = 0

    def is_connected(self):
        return self.sta.isconnected()

    def ip(self):
        return self.sta.ifconfig()[0] if self.sta.isconnected() else "0.0.0.0"

    def get_rssi(self):
        try:
            return self.sta.status('rssi')
        except Exception:
            return 0


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
                await asyncio.sleep(1)
            return self.sta.isconnected()

        # Throttle connect attempts (avoid hammering driver)
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_connect_ms) < 5000:
            await asyncio.sleep(2)
            return self.sta.isconnected()
        self._last_connect_ms = now

        try:
            self.sta.connect(ssid, password)
        except OSError as oe:
            # Driver got upset: reset interface and try again next loop
            try:
                self.sta.active(False)
                await asyncio.sleep(2)
                self.sta.active(True)
            except Exception:
                pass
            return False

        # Wait for connection
        for _ in range(int(timeout_s * 2)):
            if self.sta.isconnected():
                return True
            await asyncio.sleep(1)

        return self.sta.isconnected()

