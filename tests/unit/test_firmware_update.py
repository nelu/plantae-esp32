import importlib
import os
import sys
import types
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class _Logger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def _install_common_stubs():
    logging_mod = types.ModuleType("logging")
    logging_mod.LOG = _Logger()

    class _Pin:
        IN = 0
        OUT = 1

        def __init__(self, *args, **kwargs):
            self._value = 0

        def value(self, *args):
            if args:
                self._value = args[0]
            return self._value

    class _PWM:
        def __init__(self, *args, **kwargs):
            pass

        def deinit(self):
            pass

        def freq(self, *args, **kwargs):
            pass

        def duty_u16(self, *args, **kwargs):
            pass

    machine_mod = types.ModuleType("machine")
    machine_mod.unique_id = lambda: b"abc123"
    machine_mod.Pin = _Pin
    machine_mod.PWM = _PWM

    ubinascii_mod = types.ModuleType("ubinascii")
    ubinascii_mod.hexlify = lambda b: b

    uasyncio_mod = types.ModuleType("uasyncio")
    uasyncio_mod.create_task = lambda _coro: None

    file_store_mod = types.ModuleType("lib.file_store")
    file_store_mod.merge = lambda dst, patch: dst.update(patch) or dst
    file_store_mod.load_with_default = lambda _path, default_fn: default_fn()
    file_store_mod.atomic_save = lambda _path, _data: True

    sys.modules["logging"] = logging_mod
    sys.modules["machine"] = machine_mod
    sys.modules["ubinascii"] = ubinascii_mod
    sys.modules["uasyncio"] = uasyncio_mod
    sys.modules["lib.file_store"] = file_store_mod


class _DummyAlerts:
    def __init__(self):
        self.data = {}

    def set_alert(self, kind, message, ts=None, persist=True):
        self.data[kind] = {"message": message}
        return True

    def clear_alert(self, kind, persist=True):
        if kind in self.data:
            del self.data[kind]
            return True
        return False


class _DummyState:
    def __init__(self):
        self.alerts = _DummyAlerts()
        self.pwm_duty = 0.0


class FirmwareUpdateTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(sys.modules)
        _install_common_stubs()

    def tearDown(self):
        sys.modules.clear()
        sys.modules.update(self._saved)

    def _load_cfg(self, ota_ready):
        ota_pkg = types.ModuleType("ota")
        ota_status = types.ModuleType("ota.status")
        ota_status.ready = lambda: ota_ready
        ota_pkg.status = ota_status
        sys.modules["ota"] = ota_pkg
        sys.modules["ota.status"] = ota_status

        import adapters.config_manager as config_manager

        return importlib.reload(config_manager)

    def test_config_manager_exposes_ota_capability(self):
        cfg_mod = self._load_cfg(True)
        self.assertTrue(cfg_mod.CFG.ota_capable)

    def test_update_firmware_uses_release_json_and_reboots(self):
        cfg_mod = self._load_cfg(True)

        called = {"url": None}

        def _from_json(url, **kwargs):
            called["url"] = url

        ota_update_mod = types.ModuleType("ota.update")
        ota_update_mod.from_json = _from_json
        sys.modules["ota.update"] = ota_update_mod
        sys.modules["ota"].update = ota_update_mod

        import domain.device_service as device_service

        device_service = importlib.reload(device_service)
        reboots = []

        svc = device_service.DeviceService(_DummyState(), lambda t: reboots.append(t), stats_mgr=None)
        result = svc.update_firmware("v1.2.3")

        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("version"), "v1.2.3")
        self.assertEqual(
            called["url"],
            "https://github.com/nelu/plantae-firmware/releases/download/v1.2.3/esp32-ota.json",
        )
        self.assertEqual(reboots, [2])
        self.assertTrue(cfg_mod.CFG.ota_capable)

    def test_update_firmware_rejected_when_not_ota_capable(self):
        cfg_mod = self._load_cfg(False)

        import domain.device_service as device_service

        device_service = importlib.reload(device_service)
        reboots = []

        svc = device_service.DeviceService(_DummyState(), lambda t: reboots.append(t), stats_mgr=None)
        result = svc.update_firmware("v1.2.3")

        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "ota_not_supported")
        self.assertEqual(reboots, [])
        self.assertFalse(cfg_mod.CFG.ota_capable)

    def test_supervisor_confirms_firmware_boot(self):
        self._load_cfg(True)

        called = {"cancel": False}

        def _cancel():
            called["cancel"] = True

        ota_rollback_mod = types.ModuleType("ota.rollback")
        ota_rollback_mod.cancel = _cancel
        sys.modules["ota.rollback"] = ota_rollback_mod
        sys.modules["ota"].rollback = ota_rollback_mod

        import app.supervisor as supervisor

        supervisor = importlib.reload(supervisor)
        supervisor.Supervisor.confirm_firmware_boot()

        self.assertTrue(called["cancel"])


if __name__ == "__main__":
    unittest.main()
