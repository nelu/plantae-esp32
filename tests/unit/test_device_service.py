import sys
import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.append(SRC)


class DummyState:
    def __init__(self):
        self.pwm_duty = 0


class DummyPwm:
    def __init__(self, pin, freq, active_low):
        self.pin = pin
        self.freq = freq
        self.active_low = active_low
        self.released = False

    def set(self, duty):
        self.last_set = duty

    def release(self):
        self.released = True


class DummyFlow:
    def __init__(self, ppl, pin):
        self.ppl = ppl
        self.pin = pin
        self.began = None

    def begin(self, pullup=True):
        self.began = pullup


class DummyDosing:
    def __init__(self, flow, pwm, state=None, stats=None, activity_update=None):
        self.flow = flow
        self.pwm = pwm
        self.state = state
        self.stats = stats
        self.activity_update = activity_update


class InitHardwareTests(unittest.TestCase):
    def setUp(self):
        self._modules = {}
        for name in (
            "drivers.pwm_out",
            "drivers.flowsensor",
            "domain.dosing",
            "machine",
            "neopixel",
            "uasyncio",
            "logging",
            "micropython",
            "domain.device_service",
        ):
            if name in sys.modules:
                self._modules[name] = sys.modules[name]

        class _Module:  # simple container
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class _Machine:
            class Pin:
                IN = 0
                OUT = 1
                def __init__(self, *args, **kwargs):
                    self.value_called = []
                def value(self, *args):
                    self.value_called.append(args)
                    return 0
            class PWM:
                def __init__(self, *args, **kwargs):
                    pass
                def deinit(self):
                    pass
                def freq(self, *args, **kwargs):
                    pass
                def duty_u16(self, *args, **kwargs):
                    pass

        class _NeoPixel:
            def __init__(self, pin, count):
                self.pin = pin
                self.count = count
                self.values = [(0, 0, 0)] * count
                self.write_count = 0

            def __setitem__(self, idx, value):
                self.values[idx] = tuple(value)

            def write(self):
                self.write_count += 1

        class _Task:
            def __init__(self, coro):
                self.coro = coro
                self.cancelled = False

            def cancel(self):
                self.cancelled = True
                try:
                    self.coro.close()
                except Exception:
                    pass

        class _Loop:
            def create_task(self, coro):
                return _Task(coro)

        class _UAsyncio:
            @staticmethod
            def get_event_loop():
                return _Loop()

            @staticmethod
            async def sleep_ms(_ms):
                return None

        class _Logger:
            def info(self, *args, **kwargs):
                pass
            def debug(self, *args, **kwargs):
                pass
            def warning(self, *args, **kwargs):
                pass
            def error(self, *args, **kwargs):
                pass

        class _MicroPython:
            @staticmethod
            def const(v):
                return v

        pwm_mod = _Module(PwmOut=DummyPwm)
        flow_mod = _Module(FlowSensor=DummyFlow, flowtypes={"YFS401": object()})
        dosing_mod = _Module(DosingController=DummyDosing)
        neopixel_mod = _Module(NeoPixel=_NeoPixel)
        logging_mod = _Module(LOG=_Logger())
        micropython_mod = _MicroPython()

        sys.modules["drivers.pwm_out"] = pwm_mod
        sys.modules["drivers.flowsensor"] = flow_mod
        sys.modules["domain.dosing"] = dosing_mod
        sys.modules["machine"] = _Machine()
        sys.modules["neopixel"] = neopixel_mod
        sys.modules["uasyncio"] = _UAsyncio
        sys.modules["logging"] = logging_mod
        sys.modules["micropython"] = micropython_mod

        from domain import device_service
        self.DeviceService = device_service.DeviceService

    def tearDown(self):
        # restore
        for name in (
            "drivers.pwm_out",
            "drivers.flowsensor",
            "domain.dosing",
            "machine",
            "neopixel",
            "uasyncio",
            "logging",
            "micropython",
            "domain.device_service",
        ):
            if name in self._modules:
                sys.modules[name] = self._modules[name]
            else:
                sys.modules.pop(name, None)

    def test_init_hardware_sets_components(self):
        cfg = {
            "outputs": {"pwm": {"pin": 12, "freq": 500, "active_low": True}},
            "flow": {"type": "YFS401", "pin": 34, "pullup_external": False},
        }

        svc = self.DeviceService(DummyState(), lambda t: None, stats_mgr=None)

        ok = svc.init_hardware(cfg, activity_update="cb")

        self.assertTrue(ok)
        self.assertIsInstance(svc.pwm, DummyPwm)
        self.assertEqual(svc.pwm.pin, 12)
        self.assertEqual(svc.pwm.freq, 500)
        self.assertTrue(svc.pwm.active_low)

        self.assertIsInstance(svc.flow, DummyFlow)
        self.assertEqual(svc.flow.pin, 34)
        self.assertFalse(svc.flow.began)

        self.assertIsInstance(svc.dosing, DummyDosing)
        self.assertEqual(svc.dosing.activity_update, "cb")
        self.assertIs(svc.dosing.flow, svc.flow)
        self.assertIs(svc.dosing.pwm, svc.pwm)

    def test_indicator_on_uses_green_pulse_in_rgb_mode(self):
        svc = self.DeviceService(DummyState(), lambda t: None, stats_mgr=None)
        ind = svc.indicator

        ind.on()

        self.assertTrue(ind._rgb)
        self.assertEqual(ind._anim_mode, "pulse")
        self.assertIsNotNone(ind._anim_task)
        ind.off()

    def test_indicator_blink_uses_rainbow_animation_in_rgb_mode(self):
        svc = self.DeviceService(DummyState(), lambda t: None, stats_mgr=None)
        ind = svc.indicator

        ind.blink(freq_hz=2, duty=0.4)

        self.assertEqual(ind._anim_mode, "rainbow_blink")
        self.assertEqual(ind._blink_freq, 2.0)
        self.assertEqual(ind._blink_duty, 0.4)
        ind.off()

    def test_indicator_off_stops_rgb_animation(self):
        svc = self.DeviceService(DummyState(), lambda t: None, stats_mgr=None)
        ind = svc.indicator

        ind.on()
        task = ind._anim_task
        ind.off()

        self.assertIsNone(ind._anim_task)
        self.assertEqual(ind._anim_mode, None)
        self.assertEqual(ind._np.values[0], (0, 0, 0))
        self.assertTrue(task.cancelled)

    def test_indicator_falls_back_to_mono_when_neopixel_missing(self):
        neopixel_mod = sys.modules.pop("neopixel", None)
        try:
            ind = self.DeviceService._Indicator(pin=5, rgb=True)
            self.assertFalse(ind._rgb)
            self.assertIsNone(ind._np)
        finally:
            if neopixel_mod is not None:
                sys.modules["neopixel"] = neopixel_mod


if __name__ == "__main__":
    unittest.main()
