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
sys.modules.setdefault("lib.file_store", _FakeFileStore())

import app.tasks as tasks


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


class _DummyService:
    def __init__(self):
        self.pwm_override = False
        self.dosing = None
        self.pwm = _DummyPwm()
        self.manual = []

    def set_pwm_manual(self, duty, override, source=None):
        self.manual.append((duty, override, source))


class _DummyState:
    def __init__(self):
        self.ip = "0.0.0.0"
        self.signal = None
        self.pwm_duty = 0


class _DummySup:
    def __init__(self):
        self.state = _DummyState()
        self.service = _DummyService()
        self.wifi = _DummyWifi()
        self.is_provisioning = False
        self._maybe_calls = 0

    def _maybe_reboot(self):
        self._maybe_calls += 1


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


if __name__ == "__main__":
    unittest.main()
