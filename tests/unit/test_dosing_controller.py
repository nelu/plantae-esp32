#!/usr/bin/env python3
"""
Unit tests for DosingController class
"""

import unittest
from unittest.mock import Mock, AsyncMock
import asyncio


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
                    "output": "pwm",
                    "quantity": 0.25
                }
            }
        }
        
        # Import here to avoid MicroPython import issues
        try:
            from src.domain.dosing import DosingController
            self.controller = DosingController(self.flow_sensor, self.pwm_out, self.cfg)
        except ImportError:
            self.skipTest("DosingController not available (MicroPython only)")
    
    def test_initial_state(self):
        """Test initial controller state"""
        self.assertFalse(self.controller.is_dosing)
        self.assertEqual(self.controller.target_quantity, 0.0)
        self.assertEqual(self.controller.start_volume, 0.0)
    
    async def test_start_dose_valid(self):
        """Test starting a valid dose"""
        result = await self.controller.start_dose(0.5)
        
        self.assertTrue(result)
        self.assertTrue(self.controller.is_dosing)
        self.assertEqual(self.controller.target_quantity, 0.5)
        self.assertEqual(self.pwm_out.duty, 1.0)  # Should be at full power
    
    async def test_start_dose_invalid_quantity(self):
        """Test starting dose with invalid quantity"""
        result = await self.controller.start_dose(0.0)
        
        self.assertFalse(result)
        self.assertFalse(self.controller.is_dosing)
    
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
    
    async def test_update_dosing_complete(self):
        """Test update when dosing is complete"""
        await self.controller.start_dose(0.5)
        
        # Simulate reaching target volume
        self.flow_sensor.volume_l = 0.5
        
        await self.controller.update(480)  # 8:00 AM
        
        self.assertFalse(self.controller.is_dosing)
        self.assertEqual(self.pwm_out.duty, 0.0)
    
    async def test_update_dosing_in_progress(self):
        """Test update while dosing in progress"""
        await self.controller.start_dose(0.5)
        
        # Simulate partial progress
        self.flow_sensor.volume_l = 0.2
        
        await self.controller.update(480)  # 8:00 AM
        
        self.assertTrue(self.controller.is_dosing)
        self.assertEqual(self.pwm_out.duty, 1.0)
    
    def test_get_dose_status_inactive(self):
        """Test getting status when inactive"""
        status = self.controller.get_dose_status()
        
        expected = {
            "active": False,
            "target_quantity": 0.0,
            "current_volume": 0.0,
            "progress": 0.0,
            "start_time": None
        }
        
        for key, value in expected.items():
            self.assertEqual(status[key], value)
    
    def test_get_dose_status_active(self):
        """Test getting status when active"""
        asyncio.run(self.controller.start_dose(0.5))
        self.flow_sensor.volume_l = 0.2
        
        status = self.controller.get_dose_status()
        
        self.assertTrue(status["active"])
        self.assertEqual(status["target_quantity"], 0.5)
        self.assertEqual(status["current_volume"], 0.2)
        self.assertEqual(status["progress"], 0.4)  # 0.2 / 0.5
        self.assertIsNotNone(status["start_time"])
    
    def test_calculate_progress(self):
        """Test progress calculation"""
        # Test zero target
        progress = self.controller._calculate_progress(0.1, 0.0)
        self.assertEqual(progress, 0.0)
        
        # Test normal progress
        progress = self.controller._calculate_progress(0.2, 0.5)
        self.assertEqual(progress, 0.4)
        
        # Test complete
        progress = self.controller._calculate_progress(0.5, 0.5)
        self.assertEqual(progress, 1.0)
        
        # Test over-target
        progress = self.controller._calculate_progress(0.6, 0.5)
        self.assertEqual(progress, 1.0)


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
            'test_start_dose_invalid_quantity',
            'test_start_dose_already_dosing',
            'test_update_dosing_complete',
            'test_update_dosing_in_progress'
        ]
        
        for test_name in async_tests:
            test_method = getattr(test_case, test_name)
            setattr(test_case, test_name, lambda self, tm=test_method: run_async_test(tm()))
        
        unittest.main()
    except Exception as e:
        print(f"Skipping tests: {e}")
        print("DosingController tests require MicroPython environment")