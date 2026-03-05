from lib.file_store import merge, load_with_default, atomic_save


def get_device_id():
    import ubinascii
    import machine
    return ubinascii.hexlify(machine.unique_id()).decode()


def default_cfg():
    return {
        "tz_offset_min": 120,
        "wifi": {"ssid": "", "password": ""},
        "wamp": {
            "url": "wss://plantae.robits.org/ws",
            "realm": "none",
            "prefix": "",
            "auth_fail_retries": 3,
            "keepalive": {
                "ping_interval_s": 25,
                "idle_timeout_s": 180
            }
        },
        "inputs": {
            "pwm_test_btn": {
                "pin": 35,
                "active_low": False,
                "test_duty": 0.5
            }
        },
    }


def _validate(cfg):
    wamp = cfg.setdefault("wamp", {})
    try:
        auth_fail_retries = int(wamp.get("auth_fail_retries", 3))
    except Exception:
        auth_fail_retries = 3
    if auth_fail_retries < 1:
        auth_fail_retries = 1
    wamp["auth_fail_retries"] = auth_fail_retries

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
    def __init__(self, path="config.mpk"):
        self.path = path
        self.data = None
        self.device_id = get_device_id()

    def load(self):
        self.data = _validate(load_with_default(self.path, default_cfg))
        return self.data

    def update(self, patch: dict):
        if self.data is None:
            self.load()
        if isinstance(patch, dict):
            merge(self.data, patch)
            self.data = _validate(self.data)
        return self.data

    def save(self):
        atomic_save(self.path, self.data)


# Module-level singleton for shared config access
CFG = ConfigManager()
