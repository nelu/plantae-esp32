import os

import ujson as json

DEFAULT = {
    "wifi": {"ssid": "", "password": ""},
    "ntp": {"host": "pool.ntp.org", "sync_every_s": 21600},
    "wamp": {
        "url": "wss://plantae.robits.org/ws",
        "realm": "realm1",
        "prefix": "org.robits.plantae.",
        "keepalive": {
            "ping_interval_s": 25,
            "idle_timeout_s": 180
        }},
    "flow": {
        "type": "YFS401",
        "pin": 34,
        "calibration": 5880,
        "read_interval_ms": 1000,
        "pullup_external": True
    },
    "inputs": {
        "pwm_test_btn": {
            "pin": 35,
            "active_low": False,
            "test_duty": 0.5
        }
    },
    "outputs": {
        "pwm": {
            "pin": 2,
            "freq": 100,
            "active_low": False
        }
    },
    "schedule": {
    "tz_offset_min": 120,
    "pwm": [

    ],
    "dosing": {
      "start": "19:00",
      "end": "19:03",
      "output": "pwm",
      "duty": 0.5,
      "quantity": 0.15
    }
  }
}


def _merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict):
            # ensure we don't share dict objects from DEFAULT / patch
            if not isinstance(dst.get(k), dict):
                dst[k] = {}
            _merge(dst[k], v)
        elif isinstance(v, list):
            # avoid sharing lists (e.g. schedule.pwm)
            dst[k] = list(v)
        else:
            dst[k] = v


def _validate(cfg):
    flow = cfg.setdefault("flow", {})
    flow["pin"] = int(flow.get("pin", 14))
    flow["calibration"] = int(flow.get("calibration", 5880))
    flow["read_interval_ms"] = int(flow.get("read_interval_ms", 1000))
    flow["pullup_external"] = bool(flow.get("pullup_external", True))

    outputs = cfg.setdefault("outputs", {})
    pwm = outputs.setdefault("pwm", {})
    pwm["pin"] = int(pwm.get("pin", 2))
    pwm["freq"] = int(pwm.get("freq", 1000))
    pwm["active_low"] = bool(pwm.get("active_low", False))

    ntp = cfg.setdefault("ntp", {})
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
