#!/usr/bin/env python3
"""
Unit tests for DosingController class
"""

import unittest
import time
import sys
import os
import importlib.util
import binascii
import types

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

if "micropython" not in sys.modules:
    micropython = types.SimpleNamespace(const=lambda value: value)
    sys.modules["micropython"] = micropython

if "ubinascii" not in sys.modules:
    ubinascii = types.SimpleNamespace(hexlify=binascii.hexlify)
    sys.modules["ubinascii"] = ubinascii

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
        sys.path.insert(0, p)

_project_datetime = os.path.join(ROOT, "src", "datetime.py")
if os.path.exists(_project_datetime):
    try:
        _spec = importlib.util.spec_from_file_location("datetime", _project_datetime)
        _datetime_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_datetime_mod)
        sys.modules["datetime"] = _datetime_mod
    except Exception:
        pass

# Force use of project logging module so LOG/Logger are available
_project_logging = os.path.join(ROOT, "src", "logging.py")
if os.path.exists(_project_logging):
    try:
        _spec = importlib.util.spec_from_file_location("logging", _project_logging)
        _proj_logging = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_proj_logging)
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


class MockAlerts:
    def __init__(self):
        self._alerts = {}

    def get_alert(self, kind):
        return self._alerts.get(kind)


class MockState:
    def __init__(self):
        self.alerts = MockAlerts()
        self.pwm_duty = 0.0


class TestDosingController(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.flow_sensor = MockFlowSensor()
        self.pwm_out = MockPwmOut()
        self.state = MockState()
        self.alert_calls = []
        self.cfg = {
            "schedule": {
                "dosing": {
                    "days": ["17:00"] * 7,
                    "output": "pwm",
                    "duty": 0.5,
                    "quantity": 0.25,
                    "min_progress_ml": 10,
                }
            }
        }

        # Import here to avoid MicroPython import issues
        try:
            from src.plantae.domain.dosing import DosingController
            from src.plantae.adapters.config_manager import CFG
            CFG.data = self.cfg
            self.controller = DosingController(
                self.flow_sensor,
                self.pwm_out,
                state=self.state,
                alert_set=self._alert_set,
            )
            self.controller.config = self.cfg
        except ImportError:
            self.skipTest("DosingController not available (MicroPython only)")

    def _alert_set(self, kind, message, ts=None):
        self.alert_calls.append({"kind": kind, "message": message, "ts": ts})
    
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
        import datetime as plantae_datetime

        orig_time = plantae_datetime.time

        class _TimeStub:
            @staticmethod
            def time():
                return monday_ts

            @staticmethod
            def localtime(t=None):
                return time.gmtime(monday_ts if t is None else t)

        try:
            plantae_datetime.time = _TimeStub()
            self.assertEqual(plantae_datetime.local_wday(), 0)
        finally:
            plantae_datetime.time = orig_time

    async def test_update_triggers_auto_dose_for_today(self):
        """Auto dosing starts when today's slot is set and not yet dosed"""
        import src.plantae.domain.dosing as dosing
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
        from src.plantae.adapters.config_manager import CFG
        import src.plantae.domain.dosing as dosing
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
        import src.plantae.domain.dosing as dosing
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

    async def test_update_times_out_when_progress_below_threshold(self):
        import src.plantae.domain.dosing as dosing

        original_unix_now = dosing.unix_now
        now = 100
        dosing.unix_now = lambda: now
        try:
            await self.controller.start_dose(3.0)
            self.flow_sensor.volume_l = 0.009
            now = 161

            await self.controller.update(0)

            self.assertFalse(self.controller.is_dosing)
            self.assertEqual(self.pwm_out.duty, 0.0)
            self.assertEqual(len(self.alert_calls), 1)
            self.assertEqual(self.alert_calls[0]["kind"], "dosing")
            self.assertEqual(self.alert_calls[0]["message"], "timeout")
        finally:
            dosing.unix_now = original_unix_now

    async def test_update_keeps_running_with_sufficient_progress(self):
        import src.plantae.domain.dosing as dosing

        original_unix_now = dosing.unix_now
        now = 100
        dosing.unix_now = lambda: now
        try:
            await self.controller.start_dose(3.0)

            self.flow_sensor.volume_l = 0.011
            now = 130
            await self.controller.update(0)

            self.flow_sensor.volume_l = 0.022
            now = 191
            await self.controller.update(0)

            self.assertTrue(self.controller.is_dosing)
            self.assertEqual(self.pwm_out.duty, 0.5)
            self.assertEqual(self.alert_calls, [])
        finally:
            dosing.unix_now = original_unix_now

    async def test_update_small_progress_does_not_reset_timeout(self):
        import src.plantae.domain.dosing as dosing

        original_unix_now = dosing.unix_now
        now = 100
        dosing.unix_now = lambda: now
        try:
            await self.controller.start_dose(3.0)

            self.flow_sensor.volume_l = 0.001
            now = 130
            await self.controller.update(0)

            now = 161
            await self.controller.update(0)

            self.assertFalse(self.controller.is_dosing)
            self.assertEqual(len(self.alert_calls), 1)
        finally:
            dosing.unix_now = original_unix_now


def run_async_test(coro):
    """Helper to run async tests"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


if __name__ == '__main__':
    try:
        unittest.main()
    except Exception as e:
        print(f"Skipping tests: {e}")
        print("DosingController tests require MicroPython environment")
