#!/usr/bin/env python3
"""
Unit tests for WampBridge class
"""

import unittest
from unittest.mock import Mock, AsyncMock, patch
import asyncio
import time


class MockState:
    def __init__(self):
        self.device_id = "test-device"
        self.ip = "192.168.1.100"
        self.wamp_ok = False
        self.dosing_status = {}
        self.last_error = None

    def snapshot(self):
        return {
            "device_id": self.device_id,
            "ip": self.ip,
            "wamp_ok": self.wamp_ok,
            "dosing_status": self.dosing_status,
        }


class MockIndicator:
    def __init__(self):
        self.blink = Mock()
        self.on = Mock()


class MockService:
    def __init__(self, state=None):
        self.indicator = MockIndicator()
        self.dosing = Mock()
        self.dosing.start_dose = AsyncMock(return_value=True)
        self.dosing.stop_dose = Mock(return_value=True)
        self.dosing.get_dose_status = Mock(return_value={"active": False})
        self.dosing.last_auto_dose_day = None
        self.dosing.reset_last_auto_dose_day = Mock(side_effect=lambda: setattr(self.dosing, "last_auto_dose_day", -1))
        self.stats = Mock()
        self.alerts = Mock()
        self.alerts.data = {}
        self.alerts.all = Mock(return_value=self.alerts.data)
        self._config_patches = []

        self.state = state

        self.set_all_switches = Mock(return_value=True)
        self.set_switch = Mock(return_value=True)
        self.patch_config = Mock(side_effect=self._record_patch)
        self.clear_alert = Mock()
        self.set_alert = Mock()
        self.set_pwm_manual = Mock()
        self.get_status = Mock(return_value={"ok": True})
        self.reset_counters = Mock(return_value=True)
        self.reboot = Mock(return_value=True)

    def _record_patch(self, patch):
        self._config_patches.append(patch)
        return True


class TestWampBridge(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "wamp": {
                "prefix": "org.robits.plantae.",
                "url": "ws://example",
                "realm": "realm1",
                "keepalive": {},
                "legacy_by_ip": True,
            }
        }
        self.state = MockState()
        self.service = MockService(self.state)

        with patch('src.adapters.wamp_bridge.AutobahnWS'):
            from src.adapters.wamp_bridge import WampBridge
            self.bridge = WampBridge(self.cfg, self.service)

        # Provide a client mock for publish calls used in tests
        self.bridge.client = Mock()
        self.bridge.client.publish = AsyncMock()

    def test_pfx(self):
        self.assertEqual(self.bridge._pfx(), "org.robits.plantae.")

    def test_topic(self):
        self.assertEqual(self.bridge._topic("test"), "org.robits.plantae.test")

    def test_addr_suffixes(self):
        suffixes = self.bridge._addr_suffixes()
        self.assertIn("test-device", suffixes)
        self.assertEqual(len(suffixes), len(set(suffixes)))

    def test_addr_topic(self):
        topic = self.bridge._device_topic("status", "test-device")
        self.assertEqual(topic, "org.robits.plantae.status.test-device")

    async def test_on_master(self):
        await self.bridge.on_master([], {"time": time.time()}, {})
        self.bridge.client.publish.assert_called_once()

    async def test_rpc_control_all_switches(self):
        result = await self.bridge.rpc_control([], {"all": True}, {})
        self.assertTrue(result)
        self.service.set_all_switches.assert_called_once_with(True)

    async def test_rpc_control_single_switch(self):
        self.service.set_switch.return_value = True
        # publish_switch is awaited inside rpc_control
        self.bridge.publish_switch = AsyncMock()

        result = await self.bridge.rpc_control([], {"switch": (2, True)}, {})

        self.assertTrue(result)
        self.service.set_switch.assert_called_once_with(2, True)
        self.bridge.publish_switch.assert_awaited_once_with(2, True)

    async def test_rpc_control_patch_config(self):
        patch_cfg = {"flow": {"calibration": 100}}
        result = await self.bridge.rpc_control([], {"patch_cfg": patch_cfg}, {})
        self.assertTrue(result)
        self.assertIn(patch_cfg, self.service._config_patches)

    async def test_rpc_calibrate(self):
        result = await self.bridge.rpc_calibrate([], {"type": "flow", "calibration": 150}, {})
        self.assertTrue(result)
        self.assertIn({"flow": {"calibration": 150}}, self.service._config_patches)

    async def test_rpc_dose_start(self):
        result = await self.bridge.rpc_dose([], {"action": "start", "quantity": 0.5}, {})
        self.assertEqual(result["status"], "started")
        self.service.dosing.start_dose.assert_awaited_once_with(0.5)

    async def test_rpc_dose_invalid_quantity(self):
        result = await self.bridge.rpc_dose([], {"action": "start", "quantity": 0}, {})
        self.assertEqual(result["error"], "invalid_quantity")

    async def test_rpc_dose_stop(self):
        self.service.dosing.stop_dose.return_value = True
        result = await self.bridge.rpc_dose([], {"action": "stop"}, {})
        self.assertEqual(result["status"], "stopped")

    async def test_rpc_dose_status(self):
        expected_status = {"active": False, "quantity": 0.0}
        self.service.dosing.get_dose_status.return_value = expected_status
        result = await self.bridge.rpc_dose([], {"action": "status"}, {})
        self.assertEqual(result, expected_status)

    async def test_rpc_dose_set_schedule_valid_days(self):
        days = ["10:00"] * 7
        result = await self.bridge.rpc_dose([], {"action": "set_schedule", "dosing": {"days": days, "quantity": 0.2}}, {})
        self.assertEqual(result.get("status"), "updated")
        self.assertIn({"schedule": {"dosing": {"days": days, "quantity": 0.2}}}, self.service._config_patches)

    async def test_rpc_dose_set_schedule_invalid_days_length(self):
        result = await self.bridge.rpc_dose([], {"action": "set_schedule", "dosing": {"days": ["10:00"]}}, {})
        self.assertEqual(result.get("error"), "invalid_field")

    async def test_rpc_dose_set_schedule_resets_last_auto_day(self):
        days = ["08:00"] * 7
        self.service.dosing.last_auto_dose_day = 123

        result = await self.bridge.rpc_dose([], {"action": "set_schedule", "dosing": {"days": days}}, {})

        self.assertEqual(result.get("status"), "updated")
        self.service.dosing.reset_last_auto_dose_day.assert_called_once()
        self.assertEqual(self.service.dosing.last_auto_dose_day, -1)

    async def test_rpc_dose_set_schedule_invalid_time(self):
        days = ["10:00"] * 7
        days[2] = "1000"
        result = await self.bridge.rpc_dose([], {"action": "set_schedule", "dosing": {"days": days}}, {})
        self.assertEqual(result.get("error"), "invalid_time")

    async def test_rpc_dose_set_schedule_missing_days(self):
        result = await self.bridge.rpc_dose([], {"action": "set_schedule", "dosing": {}}, {})
        self.assertEqual(result.get("error"), "missing_field")

    async def test_rpc_status(self):
        result = await self.bridge.rpc_status([], {}, {})
        self.assertEqual(result, {"ok": True})

    async def test_rpc_reset(self):
        result = await self.bridge.rpc_reset([], {}, {})
        self.assertTrue(result)
        self.service.reset_counters.assert_called_once()

    async def test_rpc_reboot(self):
        result = await self.bridge.rpc_reboot([], {"timeout": 5}, {})
        self.assertTrue(result)
        self.service.reboot.assert_called_once_with(5)


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
    test_case = TestWampBridge()
    test_case.setUp()
    
    async_tests = [
        'test_on_master',
        'test_rpc_control_all_switches',
        'test_rpc_control_single_switch',
        'test_rpc_control_patch_config',
        'test_rpc_calibrate',
        'test_rpc_dose_start',
        'test_rpc_dose_invalid_quantity',
        'test_rpc_dose_stop',
        'test_rpc_dose_status',
        'test_rpc_dose_set_schedule_valid_days',
        'test_rpc_dose_set_schedule_invalid_days_length',
        'test_rpc_dose_set_schedule_invalid_time',
        'test_rpc_dose_set_schedule_missing_days',
        'test_rpc_status',
        'test_rpc_reset',
        'test_rpc_reboot'
    ]
    
    for test_name in async_tests:
        test_method = getattr(test_case, test_name)
        setattr(test_case, test_name, lambda self, tm=test_method: run_async_test(tm()))
    
    unittest.main()
