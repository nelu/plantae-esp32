import time, gc

from lib.file_store import PersistentManager
from adapters.datetime import DEFAULT_UNIX_EPOCH_OFFSET


class AlertManager(PersistentManager):
    def __init__(self, path="alerts.mpk", save_interval_s=60, initial=None):
        super().__init__(path, save_interval_s, initial=initial, default_factory=self.default)

    def default(self):
        return {}

    def set_alert(self, kind, message, ts=None, persist=True):
        ts_val = self._now_unix() if ts is None else self._normalize_ts(ts)
        alert = self.data.get(kind)
        if alert:
            alert["message"] = message
            alert["ts"] = ts_val
        else:
            self.data[kind] = {"message": message, "ts": ts_val}
        self._mark_dirty()
        if persist:
            self.save_if_needed(force=True)

    def clear_alert(self, kind, persist=True):
        if kind in self.data:
            del self.data[kind]
            self._mark_dirty()
            if persist:
                self.save_if_needed(force=True)
            return True
        return False

    def get_alert(self, kind):
        return self.data.get(kind)

    def all(self):
        return self.data


class DeviceState:

    def __init__(self, device_id, stats_mgr=None):
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

        self.stats_mgr = stats_mgr

        self.alerts = AlertManager()
        self.alerts.load()


    def uptime_s(self):
        return time.ticks_diff(time.ticks_ms(), self.boot_ms) // 1000

    def snapshot(self):
        gc.collect()

        return {
            "id": self.device_id,
            "ip": self.ip,
            "utc": time.time() + DEFAULT_UNIX_EPOCH_OFFSET,
            "uptime_s": self.uptime_s(),
            "heap": gc.mem_free(),
            "flow": {"lps": self.flow_lps, "lpm": self.flow_lpm, "vol_l": self.volume_l, "pulses": self.pulses},
            "out": {"switches": list(self.switches), "pwm": self.pwm_duty},
            "dosing": self.dosing_status,
            "health": {"signal": self.signal,
                       "ntp": self.ntp_ok, "wamp": self.wamp_ok, "err": self.last_error},
            "alerts": self.alerts.data,
            "stats": self.stats_mgr.data,
        }
