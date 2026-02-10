import sys
import unittest


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

        pwm_mod = _Module(PwmOut=DummyPwm)
        flow_mod = _Module(FlowSensor=DummyFlow, flowtypes={"YFS401": object()})
        dosing_mod = _Module(DosingController=DummyDosing)

        sys.modules["drivers.pwm_out"] = pwm_mod
        sys.modules["drivers.flowsensor"] = flow_mod
        sys.modules["domain.dosing"] = dosing_mod
        sys.modules["machine"] = _Machine()

        from domain import device_service
        self.DeviceService = device_service.DeviceService

    def tearDown(self):
        # restore
        for name in (
            "drivers.pwm_out",
            "drivers.flowsensor",
            "domain.dosing",
            "machine",
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


if __name__ == "__main__":
    unittest.main()
