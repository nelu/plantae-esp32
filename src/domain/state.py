import time, gc

UNIX_EPOCH_OFFSET = 946684800


class DeviceState:
    def __init__(self, device_id, stats=None):
        from version import VERSION, BUILD_DATE

        self.device_id = device_id
        self.boot_ms = time.ticks_ms()
        self.flow_lps = 0.0
        self.flow_lpm = 0.0
        self.volume_l = 0.0
        self.pulses = 0
        self.switches = [0] * 16
        self.pwm_duty = 0.0
        self.dosing_status = {"active": False, "target_l": 0.0, "dosed_l": 0.0, "remaining_l": 0.0, "duration_s": 0}
        self.ip = "0.0.0.0"
        self.ntp_ok = False
        self.wamp_ok = False
        self.signal = 0
        self.last_error = ""
        self.version = VERSION
        self.build = BUILD_DATE
        stats = stats or {}
        self.last_dose_ts = int(stats.get("last_dose_ts", 0) or 0)
        self.lifetime_volume_l = float(stats.get("lifetime_volume_l", 0.0) or 0.0)
        self.pwm_runtime_s = float(stats.get("pwm_runtime_s", 0.0) or 0.0)
        # Alerts dictionary - bind to stats if available or empty
        self.alerts = stats.get("alerts", {})

    def uptime_s(self):
        return time.ticks_diff(time.ticks_ms(), self.boot_ms) // 1000

    def snapshot(self):
        gc.collect()
        return {
            "id": self.device_id,
            "ip": self.ip,
            "utc": time.time() + UNIX_EPOCH_OFFSET,
            "uptime_s": self.uptime_s(),
            "heap": gc.mem_free(),
            "flow": {"lps": self.flow_lps, "lpm": self.flow_lpm, "vol_l": self.volume_l, "pulses": self.pulses},
            "out": {"switches": list(self.switches), "pwm": self.pwm_duty},
            "dosing": self.dosing_status,
            "health": {"signal": self.signal,
                       "ntp": self.ntp_ok, "wamp": self.wamp_ok, "err": self.last_error},
            "stats": {
                "last_dose_ts": self.last_dose_ts,
                "lifetime_volume_l": self.lifetime_volume_l,
                "pwm_runtime_s": self.pwm_runtime_s,
                "alerts": self.alerts,
            },
        }
