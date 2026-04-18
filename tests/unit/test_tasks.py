import importlib.util
import os
import sys
import unittest


async def _noop_sleep(*args, **kwargs):
    return None


class _FakeAsyncioModule:
    pass


def _make_fake_asyncio():
    mod = _FakeAsyncioModule()
    mod.sleep = _noop_sleep
    mod.sleep_ms = _noop_sleep

    def run(coro):
        try:
            while True:
                coro.send(None)
        except StopIteration as e:
            return getattr(e, "value", None)
        except StopAsyncIteration:
            return None

    mod.run = run
    return mod


# Provide uasyncio stub before importing tasks
# Provide uasyncio stub before importing tasks
sys.modules.setdefault("uasyncio", _make_fake_asyncio())

if "micropython" not in sys.modules:
    class _FakeMicroPython:
        @staticmethod
        def const(value):
            return value

    sys.modules["micropython"] = _FakeMicroPython()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in (ROOT, os.path.join(ROOT, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_project_module(name, path):
    if not os.path.exists(path):
        return
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[name] = module
    except Exception:
        pass


_load_project_module("datetime", os.path.join(ROOT, "src", "datetime.py"))
_load_project_module("logging", os.path.join(ROOT, "src", "logging.py"))


# Stub config_manager dependencies used at import time
class _FakeUbinascii:
    @staticmethod
    def hexlify(b):
        return b


class _FakeMachine:
    @staticmethod
    def unique_id():
        return b"abc123"


class _FakeFileStore:
    @staticmethod
    def merge(dst, patch):
        try:
            dst.update(patch)
        except Exception:
            pass
        return dst

    @staticmethod
    def load_with_default(path, default_fn):
        return default_fn()

    @staticmethod
    def atomic_save(path, data):
        return True


sys.modules.setdefault("ubinascii", _FakeUbinascii())
sys.modules.setdefault("machine", _FakeMachine())
sys.modules.setdefault("file_store", _FakeFileStore())

from plantae.app import tasks


class _DummyWifi:
    def __init__(self, connected=True, ip="1.2.3.4", rssi=-42):
        self._connected = connected
        self._ip = ip
        self._rssi = rssi

    def is_connected(self):
        return self._connected

    def ip(self):
        return self._ip

    def get_rssi(self):
        return self._rssi


class _DummyPwm:
    def __init__(self):
        self.last_duty = None

    def set(self, duty):
        self.last_duty = duty


class _DummyFlow:
    def __init__(self):
        self.volume_l = 0.0


class _DummyAlerts:
    def __init__(self):
        self._alerts = {}

    def get_alert(self, kind):
        return self._alerts.get(kind)


class _DummyService:
    def __init__(self):
        self.pwm_override = False
        self.dosing = None
        self.pwm = _DummyPwm()
        self.flow = _DummyFlow()
        self.manual = []
        self.cleared_alerts = []

    def set_pwm_manual(self, duty, override, source=None):
        self.manual.append((duty, override, source))

    def clear_alert(self, kind):
        self.cleared_alerts.append(kind)
        return True


class _DummyDosing:
    def __init__(self, active=False):
        self.is_dosing = active
        self.start_calls = []
        self.stop_calls = 0

    async def start_dose(self, quantity, is_manual=False):
        self.start_calls.append((quantity, is_manual))
        self.is_dosing = True
        return True

    def stop_dose(self):
        self.stop_calls += 1
        self.is_dosing = False
        return True


class _DummyState:
    def __init__(self):
        self.ip = "0.0.0.0"
        self.signal = None
        self.pwm_duty = 0
        self.volume_l = 0.0
        self.alerts = _DummyAlerts()


class _DummySup:
    def __init__(self):
        self.state = _DummyState()
        self.service = _DummyService()
        self.wifi = _DummyWifi()
        self.is_provisioning = False
        self._maybe_calls = 0

    def _maybe_reboot(self):
        self._maybe_calls += 1


class _FakePin:
    IN = 0
    sequence = [1]
    index = 0

    def __init__(self, *args, **kwargs):
        pass

    def value(self):
        idx = self.index
        if idx >= len(self.sequence):
            idx = len(self.sequence) - 1
        return self.sequence[idx]


def _run_button_task(states, sup, step_ms=50, volumes=None):
    fake_machine = sys.modules["machine"]
    old_pin = getattr(fake_machine, "Pin", None)
    old_ticks_ms = getattr(tasks.time, "ticks_ms", None)
    old_ticks_diff = getattr(tasks.time, "ticks_diff", None)
    old_sleep_ms = getattr(tasks.asyncio, "sleep_ms", None)

    _FakePin.sequence = list(states)
    _FakePin.index = 0
    now = {"value": 0}

    if volumes:
        sup.service.flow.volume_l = volumes[0]
        sup.state.volume_l = volumes[0]

    async def step_sleep_ms(*args, **kwargs):
        now["value"] += step_ms
        _FakePin.index += 1
        if volumes and _FakePin.index < len(volumes):
            sup.service.flow.volume_l = volumes[_FakePin.index]
            sup.state.volume_l = volumes[_FakePin.index]
        if _FakePin.index >= len(_FakePin.sequence):
            raise StopAsyncIteration

    fake_machine.Pin = _FakePin
    tasks.time.ticks_ms = lambda: now["value"]
    tasks.time.ticks_diff = lambda a, b: a - b
    tasks.asyncio.sleep_ms = step_sleep_ms

    try:
        tasks.asyncio.run(tasks.task_pwm_test_btn(sup))
    finally:
        if old_pin is None:
            delattr(fake_machine, "Pin")
        else:
            fake_machine.Pin = old_pin

        if old_ticks_ms is None:
            delattr(tasks.time, "ticks_ms")
        else:
            tasks.time.ticks_ms = old_ticks_ms

        if old_ticks_diff is None:
            delattr(tasks.time, "ticks_diff")
        else:
            tasks.time.ticks_diff = old_ticks_diff

        if old_sleep_ms is not None:
            tasks.asyncio.sleep_ms = old_sleep_ms


def _run_once(coro):
    async def driver():
        try:
            await coro
        except StopAsyncIteration:
            return

    async def stopper(*args, **kwargs):
        raise StopAsyncIteration

    old_sleep = tasks.asyncio.sleep
    old_sleep_ms = getattr(tasks.asyncio, "sleep_ms", None)
    tasks.asyncio.sleep = stopper
    if old_sleep_ms is not None:
        tasks.asyncio.sleep_ms = stopper

    try:
        tasks.asyncio.run(driver())
    finally:
        tasks.asyncio.sleep = old_sleep
        if old_sleep_ms is not None:
            tasks.asyncio.sleep_ms = old_sleep_ms


class TasksTests(unittest.TestCase):
    def setUp(self):
        self._cfg_data = tasks.CFG.data
        tasks.CFG.data = {
            "inputs": {"pwm_test_btn": {"pin": 13, "active_low": True, "test_duty": 0.5}},
            "schedule": {"dosing": {"quantity": 0.25}},
        }

    def tearDown(self):
        tasks.CFG.data = self._cfg_data

    def test_task_wifi_status_updates_ip_and_signal(self):
        sup = _DummySup()
        _run_once(tasks.task_wifi_status(sup))

        self.assertEqual(sup.state.ip, "1.2.3.4")
        self.assertEqual(sup.state.signal, -42)

    def test_task_reboot_watch_calls_maybe_reboot(self):
        sup = _DummySup()
        _run_once(tasks.task_reboot_watch(sup))
        self.assertGreaterEqual(sup._maybe_calls, 1)

    def test_task_pwm_schedule_sets_duty_from_schedule(self):
        sup = _DummySup()
        tasks.CFG.data = {
            "schedule": {
                "pwm": [
                    {"start": "00:00", "end": "23:59", "duty": 0.5},
                ]
            },
            "flow": {},
        }

        _run_once(tasks.task_pwm_schedule(sup))
        self.assertAlmostEqual(sup.state.pwm_duty, 0.5)
        self.assertAlmostEqual(sup.service.pwm.last_duty, 0.5)

    def test_task_pwm_test_btn_short_press_toggles_manual_override(self):
        sup = _DummySup()

        _run_button_task([0, 1], sup)

        self.assertEqual(
            sup.service.manual,
            [(0.5, True, "button"), (0, False, "button")],
        )

    def test_task_pwm_test_btn_press_stops_active_dose(self):
        sup = _DummySup()
        sup.service.dosing = _DummyDosing(active=True)

        _run_button_task(([0] * 61) + [1], sup)

        self.assertEqual(sup.service.dosing.stop_calls, 1)
        self.assertEqual(sup.service.dosing.start_calls, [])
        self.assertEqual(sup.service.manual, [])

    def test_task_pwm_test_btn_long_press_starts_manual_dose(self):
        sup = _DummySup()
        sup.service.dosing = _DummyDosing(active=False)

        _run_button_task(([0] * 51) + [1], sup, step_ms=200)

        self.assertEqual(
            sup.service.manual,
            [(0.5, True, "button"), (0, False, "button")],
        )
        self.assertEqual(sup.service.dosing.start_calls, [(0.25, True)])
        self.assertEqual(sup.service.dosing.stop_calls, 0)

    def test_task_pwm_test_btn_long_press_fires_once_per_hold(self):
        sup = _DummySup()
        sup.service.dosing = _DummyDosing(active=False)

        _run_button_task(([0] * 80) + [1], sup, step_ms=200)

        self.assertEqual(sup.service.dosing.start_calls, [(0.25, True)])

    def test_task_pwm_test_btn_short_press_clears_timeout_after_recovery(self):
        sup = _DummySup()
        sup.state.alerts._alerts["dosing"] = {"message": "timeout", "ts": 123}

        _run_button_task([0, 0, 1], sup, volumes=[0.0, 0.02, 0.02])

        self.assertEqual(sup.service.cleared_alerts, ["dosing"])

    def test_task_pwm_test_btn_short_press_keeps_timeout_when_recovery_too_small(self):
        sup = _DummySup()
        sup.state.alerts._alerts["dosing"] = {"message": "timeout", "ts": 123}

        _run_button_task([0, 0, 1], sup, volumes=[0.0, 0.019, 0.019])

        self.assertEqual(sup.service.cleared_alerts, [])

    def test_task_pwm_test_btn_long_press_can_clear_timeout_and_start_dose(self):
        sup = _DummySup()
        sup.service.dosing = _DummyDosing(active=False)
        sup.state.alerts._alerts["dosing"] = {"message": "timeout", "ts": 123}

        volumes = [0.0] + ([0.02] * 51)
        _run_button_task(([0] * 51) + [1], sup, step_ms=200, volumes=volumes)

        self.assertEqual(sup.service.cleared_alerts, ["dosing"])
        self.assertEqual(sup.service.dosing.start_calls, [(0.25, True)])


if __name__ == "__main__":
    unittest.main()
