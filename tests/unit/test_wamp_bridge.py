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
        self.last_error = None
        self.switches = [False] * 16
        self.volume_l = 0.0
        self.flow_lpm = 0.0
        self.pulses = 0
        self.pwm_duty = 0.0
        self.dosing_status = {}
    
    def snapshot(self):
        return {
            "device_id": self.device_id,
            "ip": self.ip,
            "wamp_ok": self.wamp_ok,
            "switches": self.switches.copy(),
            "volume_l": self.volume_l,
            "flow_lpm": self.flow_lpm,
            "pulses": self.pulses,
            "pwm_duty": self.pwm_duty,
            "dosing_status": self.dosing_status
        }


class MockConfigManager:
    def __init__(self):
        self.config = {}
    
    def update(self, patch):
        self.config.update(patch)
        return self.config
    
    def save(self):
        pass


class TestWampBridge(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "wamp": {
                "prefix": "org.robits.plantae.",
                "legacy_by_ip": True
            }
        }
        self.state = MockState()
        self.switchbank = Mock()
        self.config_mgr = MockConfigManager()
        self.schedule_reboot = Mock()
        self.dosing_controller = Mock()
        
        # Import here to avoid MicroPython import issues in tests
        with patch('src.adapters.wamp_bridge.AutobahnWS'):
            from src.adapters.wamp_bridge import WampBridge
            self.bridge = WampBridge(
                self.cfg, self.state, self.switchbank, 
                self.config_mgr, self.schedule_reboot, 
                self.dosing_controller
            )
    
    def test_pfx(self):
        """Test prefix generation"""
        self.assertEqual(self.bridge._pfx(), "org.robits.plantae.")
    
    def test_topic(self):
        """Test topic name generation"""
        self.assertEqual(self.bridge._topic("test"), "org.robits.plantae.test")
    
    def test_addr_suffixes(self):
        """Test address suffix generation"""
        suffixes = self.bridge._addr_suffixes()
        self.assertIn("test-device", suffixes)
        self.assertIn("192.168.1.100", suffixes)
        # Should not have duplicates
        self.assertEqual(len(suffixes), len(set(suffixes)))
    
    def test_addr_topic(self):
        """Test addressed topic generation"""
        topic = self.bridge._addr_topic("status", "test-device")
        self.assertEqual(topic, "org.robits.plantae.status.test-device")
    
    async def test_on_master(self):
        """Test master announcement handler"""
        self.bridge.client = Mock()
        self.bridge.client.publish = AsyncMock()
        
        await self.bridge.on_master([], {"time": time.time()}, {})
        
        # Should publish announce.online
        self.bridge.client.publish.assert_called_once()
        call_args = self.bridge.client.publish.call_args
        self.assertIn("announce.online", call_args[0][0])
    
    async def test_rpc_control_all_switches(self):
        """Test RPC control for all switches"""
        self.switchbank.set_all.return_value = True
        self.switchbank.values = [True] * 16
        
        result = await self.bridge.rpc_control([], {"all": True}, {})
        
        self.assertTrue(result)
        self.switchbank.set_all.assert_called_once_with(True)
        self.assertEqual(self.state.switches, [True] * 16)
    
    async def test_rpc_control_single_switch(self):
        """Test RPC control for single switch"""
        self.bridge.client = Mock()
        self.bridge.client.publish = AsyncMock()
        self.switchbank.set.return_value = True
        self.switchbank.values = [False] * 16
        self.switchbank.values[5] = True
        
        result = await self.bridge.rpc_control([], {"switch": [5, True]}, {})
        
        self.assertTrue(result)
        self.switchbank.set.assert_called_once_with(5, True)
        self.bridge.client.publish.assert_called_once()
    
    async def test_rpc_control_patch_config(self):
        """Test RPC control for config patching"""
        patch = {"flow": {"calibration": 100}}
        
        result = await self.bridge.rpc_control([], {"patch_cfg": patch}, {})
        
        self.assertTrue(result)
        self.assertEqual(self.config_mgr.config, patch)
    
    async def test_rpc_calibrate(self):
        """Test RPC calibration"""
        self.cfg["flow"] = {"calibration": 0}
        
        result = await self.bridge.rpc_calibrate([], {"type": "flow", "calibration": 150}, {})
        
        self.assertTrue(result)
        self.assertEqual(self.cfg["flow"]["calibration"], 150)
    
    async def test_rpc_dose_start(self):
        """Test RPC dosing start"""
        self.dosing_controller.start_dose = AsyncMock(return_value=True)
        
        result = await self.bridge.rpc_dose([], {"action": "start", "quantity": 0.5}, {})
        
        self.assertEqual(result["status"], "started")
        self.assertEqual(result["quantity"], 0.5)
        self.dosing_controller.start_dose.assert_called_once_with(0.5)
    
    async def test_rpc_dose_invalid_quantity(self):
        """Test RPC dosing with invalid quantity"""
        result = await self.bridge.rpc_dose([], {"action": "start", "quantity": 0}, {})
        
        self.assertEqual(result["error"], "invalid_quantity")
    
    async def test_rpc_dose_stop(self):
        """Test RPC dosing stop"""
        self.dosing_controller.stop_dose.return_value = True
        
        result = await self.bridge.rpc_dose([], {"action": "stop"}, {})
        
        self.assertEqual(result["status"], "stopped")
    
    async def test_rpc_dose_status(self):
        """Test RPC dosing status"""
        expected_status = {"active": False, "quantity": 0.0}
        self.dosing_controller.get_dose_status.return_value = expected_status
        
        result = await self.bridge.rpc_dose([], {"action": "status"}, {})
        
        self.assertEqual(result, expected_status)

    
    async def test_rpc_status(self):
        """Test RPC status"""
        result = await self.bridge.rpc_status([], {}, {})
        
        expected = self.state.snapshot()
        self.assertEqual(result, expected)
    
    async def test_rpc_reset(self):
        """Test RPC reset"""
        self.state.volume_l = 10.5
        self.state.pulses = 1000
        
        result = await self.bridge.rpc_reset([], {}, {})
        
        self.assertTrue(result)
        self.assertEqual(self.state.volume_l, 0.0)
        self.assertEqual(self.state.pulses, 0)
    
    async def test_rpc_reboot(self):
        """Test RPC reboot"""
        self.bridge.client = Mock()
        self.bridge.client.publish = AsyncMock()
        
        result = await self.bridge.rpc_reboot([], {"timeout": 5}, {})
        
        self.assertTrue(result)
        self.schedule_reboot.assert_called_once_with(5)


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
        'test_rpc_test_master',
        'test_rpc_status',
        'test_rpc_reset',
        'test_rpc_reboot'
    ]
    
    for test_name in async_tests:
        test_method = getattr(test_case, test_name)
        setattr(test_case, test_name, lambda self, tm=test_method: run_async_test(tm()))
    
    unittest.main()