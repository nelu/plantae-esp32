import ujson as json
import os

DEFAULT = {
  "config_version": 1,
  "device": {"name": "", "id": ""},
  "wifi": {"ssid": "", "password": ""},
  "ntp": {"host": "pool.ntp.org", "sync_every_s": 21600},
  "time": {"last_mpy_s": 0},
  "wamp": {"url": "ws://10.0.0.1:8080/ws", "realm": "realm1", "prefix": "org.robits.plantae.", "legacy_by_ip": True, "keepalive": {"ping_interval_s": 20, "idle_timeout_s": 60}},
  "flow": {"type": "YFS401", "pin": 14, "calibration": 5880, "read_interval_ms": 1000, "pullup_external": True},
  "outputs": {
    "pwm": {"pin": 25, "freq": 20000, "active_low": False},
    "pca9685": {"enabled": True, "i2c_id": 0, "scl": 22, "sda": 21, "addr": 64, "freq": 400000, "channels": 16, "pwm_freq": 1000}
  },
  "schedule": {"tz_offset_min": 0, "pwm": []}
}

def _merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v

def _validate(cfg):
    flow = cfg.get("flow", {})
    flow["pin"] = int(flow.get("pin", 14))
    flow["calibration"] = int(flow.get("calibration", 0))
    flow["read_interval_ms"] = int(flow.get("read_interval_ms", 1000))
    flow["pullup_external"] = bool(flow.get("pullup_external", True))

    pwm = cfg.get("outputs", {}).get("pwm", {})
    pwm["pin"] = int(pwm.get("pin", 25))
    pwm["freq"] = int(pwm.get("freq", 20000))
    pwm["active_low"] = bool(pwm.get("active_low", False))

    ntp = cfg.get("ntp", {})
    ntp["sync_every_s"] = int(ntp.get("sync_every_s", 21600))
    return cfg

class ConfigManager:
    def __init__(self, path="config.json"):
        self.path = path
        self.cfg = None

    def load(self):
        cfg = {}
        _merge(cfg, DEFAULT)
        try:
            with open(self.path, "r") as f:
                user = json.load(f)
            if isinstance(user, dict):
                _merge(cfg, user)
        except Exception:
            pass
        self.cfg = _validate(cfg)
        return self.cfg

    def update(self, patch: dict):
        if self.cfg is None:
            self.load()
        if isinstance(patch, dict):
            _merge(self.cfg, patch)
            self.cfg = _validate(self.cfg)
        return self.cfg

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.cfg, f)
        try:
            os.remove(self.path)
        except Exception:
            pass
        os.rename(tmp, self.path)
