#!/usr/bin/env python3
"""
Unit tests for DosingController class
"""

import unittest
import time
import sys
import os

# Provide a stub machine.unique_id if the platform lacks it (e.g., unix port).
try:
    import machine as _machine  # type: ignore
    if hasattr(_machine, "unique_id"):
        machine = _machine
    else:
        raise ImportError
except Exception:
    class _MachineStub:
        pass
    machine = _MachineStub()
    machine.unique_id = lambda: b"\x00\x01\x02\x03\x04\x05"
    sys.modules["machine"] = machine

try:
    import asyncio
except ImportError:  # MicroPython fallback
    try:
        import uasyncio as asyncio
    except ImportError:
        class _AsyncioStub:
            @staticmethod
            def run(coro):
                try:
                    return coro.send(None)
                except StopIteration as e:
                    return getattr(e, "value", None)

            @staticmethod
            def create_task(coro):
                # Execute immediately for test purposes
                try:
                    coro.send(None)
                except StopIteration:
                    pass
                return coro

            @staticmethod
            def new_event_loop():
                class _Loop:
                    def run_until_complete(self, c):
                        return _AsyncioStub.run(c)
                    def close(self):
                        pass
                return _Loop()

            @staticmethod
            def set_event_loop(loop):
                return None

        asyncio = _AsyncioStub()

if "uasyncio" not in sys.modules:
    sys.modules["uasyncio"] = asyncio

# Ensure project modules are importable in MicroPython container
try:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
except AttributeError:
    ROOT = "/app"

for p in (
    ROOT,
    ROOT + "/src",
    ROOT + "/src/lib",
):
    if p not in sys.path:
        sys.path.append(p)

# Force use of project logging module so LOG/Logger are available
try:
    import lib.logging as _proj_logging
    sys.modules["logging"] = _proj_logging
except Exception:
    pass

# Provide a lightweight umsgpack stub if missing (used only for persistence helpers)
try:
    import umsgpack  # type: ignore
except ImportError:  # pragma: no cover - environment guard
    try:
        import ujson as _json
    except ImportError:  # pragma: no cover
        import json as _json

    class _UMsgpackStub:
        pass

    _stub = _UMsgpackStub()
    _stub.load = lambda f: _json.load(f)
    _stub.dump = lambda obj, f: _json.dump(obj, f)
    sys.modules["umsgpack"] = _stub


class MockFlowSensor:
    def __init__(self):
        self.volume_l = 0.0
        self.flow_lpm = 0.0
        
    def reset_volume(self):
        self.volume_l = 0.0


class MockPwmOut:
    def __init__(self):
        self.duty = 0.0
        
    def set(self, duty):
        self.duty = duty


class TestDosingController(unittest.TestCase):
    def setUp(self):
        self.flow_sensor = MockFlowSensor()
        self.pwm_out = MockPwmOut()
        self.cfg = {
            "schedule": {
                "dosing": {
                    "days": ["17:00"] * 7,
                    "output": "pwm",
                    "duty": 0.5,
                    "quantity": 0.25
                }
            }
        }

        # Import here to avoid MicroPython import issues
        try:
            from src.domain.dosing import DosingController
            from src.adapters.config_manager import CFG
            CFG.data = self.cfg
            self.controller = DosingController(self.flow_sensor, self.pwm_out)
            self.controller.config = self.cfg
        except ImportError:
            self.skipTest("DosingController not available (MicroPython only)")
    
    def test_initial_state(self):
        """Test initial controller state"""
        self.assertFalse(self.controller.is_dosing)
        self.assertEqual(self.controller.target_quantity, 0.0)
        self.assertEqual(self.controller.dose_start_volume, 0.0)
    
    async def test_start_dose_valid(self):
        """Test starting a valid dose"""
        result = await self.controller.start_dose(0.5)
        
        self.assertTrue(result)
        self.assertTrue(self.controller.is_dosing)
        self.assertEqual(self.controller.target_quantity, 0.5)
        self.assertEqual(self.pwm_out.duty, 0.5)
    
    async def test_start_dose_already_dosing(self):
        """Test starting dose when already dosing"""
        await self.controller.start_dose(0.5)
        result = await self.controller.start_dose(0.3)
        
        self.assertFalse(result)
        self.assertEqual(self.controller.target_quantity, 0.5)  # Should keep original
    
    def test_stop_dose(self):
        """Test stopping dose"""
        # Start dosing first
        asyncio.run(self.controller.start_dose(0.5))
        
        result = self.controller.stop_dose()
        
        self.assertTrue(result)
        self.assertFalse(self.controller.is_dosing)
        self.assertEqual(self.pwm_out.duty, 0.0)
    
    def test_stop_dose_not_active(self):
        """Test stopping dose when not active"""
        result = self.controller.stop_dose()
        
        self.assertFalse(result)

    def test_reset_last_auto_dose_day(self):
        self.controller.last_auto_dose_day = 7
        self.controller.reset_last_auto_dose_day()

        self.assertEqual(self.controller.last_auto_dose_day, -1)
    
    def test_get_dose_status_inactive(self):
        """Test getting status when inactive"""
        status = self.controller.get_dose_status()
        
        expected = {
            "active": False,
            "target_l": 0.0,
            "dosed_l": 0.0,
            "remaining_l": 0.0,
            "duration_s": 0
        }
        
        for key, value in expected.items():
            self.assertEqual(status[key], value)
    
    def test_get_dose_status_active(self):
        """Test getting status when active"""
        asyncio.run(self.controller.start_dose(0.5))
        self.flow_sensor.volume_l = 0.2
        
        status = self.controller.get_dose_status()
        
        self.assertTrue(status["active"])
        self.assertEqual(status["target_l"], 0.5)
        self.assertAlmostEqual(status["dosed_l"], 0.2)
        self.assertAlmostEqual(status["remaining_l"], 0.3)
        self.assertGreaterEqual(status["duration_s"], 0)

    def test_local_wday_is_monday_for_epoch_day_4(self):
        """Weekday calculation stays Monday with tz offset applied"""
        monday_ts = 4 * 86400  # 1970-01-05 00:00:00 UTC (Monday)
        import src.domain.dosing as dosing

        orig_time_mod = dosing.time

        class _TimeStub:
            pass

        _stub = _TimeStub()
        _stub.time = lambda: monday_ts
        _stub.localtime = lambda t=None: time.gmtime(t)
        try:
            dosing.time = _stub
            self.assertEqual(dosing.local_wday(), 0)
        finally:
            dosing.time = orig_time_mod

    async def test_update_triggers_auto_dose_for_today(self):
        """Auto dosing starts when today's slot is set and not yet dosed"""
        import src.domain.dosing as dosing
        orig_wday, orig_day = dosing.local_wday, dosing.current_local_day
        dosing.local_wday = lambda: 0
        dosing.current_local_day = lambda: 123
        try:
            await self.controller.update(17 * 60)
            self.assertTrue(self.controller.is_dosing)
            self.assertEqual(self.controller.last_auto_dose_day, 123)
        finally:
            dosing.local_wday = orig_wday
            dosing.current_local_day = orig_day

    async def test_update_skips_empty_day(self):
        from src.adapters.config_manager import CFG
        import src.domain.dosing as dosing
        CFG.data["schedule"]["dosing"]["days"][0] = ""
        orig_wday, orig_day = dosing.local_wday, dosing.current_local_day
        dosing.local_wday = lambda: 0
        dosing.current_local_day = lambda: 200
        try:
            await self.controller.update(17 * 60)
            self.assertFalse(self.controller.is_dosing)
        finally:
            dosing.local_wday = orig_wday
            dosing.current_local_day = orig_day

    async def test_update_skips_if_already_dosed_today(self):
        import src.domain.dosing as dosing
        orig_wday, orig_day = dosing.local_wday, dosing.current_local_day
        dosing.local_wday = lambda: 0
        dosing.current_local_day = lambda: 300
        self.controller.last_auto_dose_day = 300
        try:
            await self.controller.update(17 * 60)
            self.assertFalse(self.controller.is_dosing)
        finally:
            dosing.local_wday = orig_wday
            dosing.current_local_day = orig_day


def run_async_test(coro):
    """Helper to run async tests"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


if __name__ == '__main__':
    # Convert async test methods to sync for unittest
    test_case = TestDosingController()
    
    try:
        test_case.setUp()
        
        async_tests = [
            'test_start_dose_valid',
            'test_start_dose_already_dosing',
            'test_update_triggers_auto_dose_for_today',
            'test_update_skips_empty_day',
            'test_update_skips_if_already_dosed_today'
        ]
        
        for test_name in async_tests:
            test_method = getattr(test_case, test_name)
            setattr(test_case, test_name, lambda self, tm=test_method: run_async_test(tm()))
        
        unittest.main()
    except Exception as e:
        print(f"Skipping tests: {e}")
        print("DosingController tests require MicroPython environment")
