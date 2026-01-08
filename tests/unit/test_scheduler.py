#!/usr/bin/env python3
"""
Unit tests for scheduler functions
"""

import unittest


class TestScheduler(unittest.TestCase):
    def setUp(self):
        try:
            from src.domain.scheduler import duty_from_schedule, parse_time_str
            self.duty_from_schedule = duty_from_schedule
            self.parse_time_str = parse_time_str
        except ImportError:
            self.skipTest("Scheduler module not available")
    
    def test_parse_time_str_valid(self):
        """Test parsing valid time strings"""
        self.assertEqual(self.parse_time_str("07:30"), 450)  # 7*60 + 30
        self.assertEqual(self.parse_time_str("00:00"), 0)
        self.assertEqual(self.parse_time_str("23:59"), 1439)  # 23*60 + 59
        self.assertEqual(self.parse_time_str("12:00"), 720)   # 12*60
    
    def test_parse_time_str_invalid(self):
        """Test parsing invalid time strings"""
        self.assertIsNone(self.parse_time_str("25:00"))  # Invalid hour
        self.assertIsNone(self.parse_time_str("12:60"))  # Invalid minute
        self.assertIsNone(self.parse_time_str("abc"))    # Invalid format
        self.assertIsNone(self.parse_time_str("12"))     # Missing colon
        self.assertIsNone(self.parse_time_str(""))       # Empty string
    
    def test_duty_from_schedule_empty(self):
        """Test duty calculation with empty schedule"""
        duty = self.duty_from_schedule([], 480, 0)  # 8:00 AM
        self.assertEqual(duty, 0.0)
    
    def test_duty_from_schedule_single_entry(self):
        """Test duty calculation with single schedule entry"""
        schedule = [{
            "start": "07:00",
            "end": "20:00", 
            "duty": 0.5
        }]
        
        # Within schedule
        duty = self.duty_from_schedule(schedule, 480, 0)  # 8:00 AM
        self.assertEqual(duty, 0.5)
        
        # Before schedule
        duty = self.duty_from_schedule(schedule, 360, 0)  # 6:00 AM
        self.assertEqual(duty, 0.0)
        
        # After schedule
        duty = self.duty_from_schedule(schedule, 1260, 0)  # 9:00 PM
        self.assertEqual(duty, 0.0)
    
    def test_duty_from_schedule_interval_timing(self):
        """Test duty calculation with interval timing"""
        schedule = [{
            "start": "07:00",
            "end": "20:00",
            "duty": 0.8,
            "interval": 60,    # 60 minutes
            "time_on": 15      # 15 minutes on
        }]
        
        # At start of interval (should be on)
        duty = self.duty_from_schedule(schedule, 420, 0)  # 7:00 AM, 0 seconds
        self.assertEqual(duty, 0.8)
        
        # Within on period
        duty = self.duty_from_schedule(schedule, 420, 600)  # 7:00 AM, 10 minutes
        self.assertEqual(duty, 0.8)
        
        # At end of on period
        duty = self.duty_from_schedule(schedule, 420, 900)  # 7:00 AM, 15 minutes
        self.assertEqual(duty, 0.0)
        
        # In off period
        duty = self.duty_from_schedule(schedule, 420, 1800)  # 7:00 AM, 30 minutes
        self.assertEqual(duty, 0.0)
        
        # Next interval start
        duty = self.duty_from_schedule(schedule, 480, 0)  # 8:00 AM, 0 seconds
        self.assertEqual(duty, 0.8)
    
    def test_duty_from_schedule_continuous(self):
        """Test duty calculation without intervals (continuous)"""
        schedule = [{
            "start": "07:00",
            "end": "20:00",
            "duty": 0.6
            # No interval/time_on = continuous
        }]
        
        duty = self.duty_from_schedule(schedule, 480, 30)  # 8:00:30 AM
        self.assertEqual(duty, 0.6)
    
    def test_duty_from_schedule_multiple_entries(self):
        """Test duty calculation with multiple schedule entries"""
        schedule = [
            {
                "start": "07:00",
                "end": "12:00",
                "duty": 0.3
            },
            {
                "start": "14:00", 
                "end": "20:00",
                "duty": 0.7
            }
        ]
        
        # First period
        duty = self.duty_from_schedule(schedule, 480, 0)  # 8:00 AM
        self.assertEqual(duty, 0.3)
        
        # Between periods
        duty = self.duty_from_schedule(schedule, 780, 0)  # 1:00 PM
        self.assertEqual(duty, 0.0)
        
        # Second period
        duty = self.duty_from_schedule(schedule, 900, 0)  # 3:00 PM
        self.assertEqual(duty, 0.7)
    
    def test_duty_from_schedule_overlapping_entries(self):
        """Test duty calculation with overlapping entries (last wins)"""
        schedule = [
            {
                "start": "07:00",
                "end": "12:00", 
                "duty": 0.3
            },
            {
                "start": "10:00",
                "end": "14:00",
                "duty": 0.8
            }
        ]
        
        # Before overlap
        duty = self.duty_from_schedule(schedule, 480, 0)  # 8:00 AM
        self.assertEqual(duty, 0.3)
        
        # In overlap (second entry should win)
        duty = self.duty_from_schedule(schedule, 660, 0)  # 11:00 AM
        self.assertEqual(duty, 0.8)
    
    def test_duty_from_schedule_invalid_times(self):
        """Test duty calculation with invalid time entries"""
        schedule = [
            {
                "start": "invalid",
                "end": "20:00",
                "duty": 0.5
            },
            {
                "start": "07:00",
                "end": "invalid", 
                "duty": 0.3
            },
            {
                "start": "07:00",
                "end": "20:00",
                "duty": 0.8
            }
        ]
        
        # Should only use the valid entry
        duty = self.duty_from_schedule(schedule, 480, 0)  # 8:00 AM
        self.assertEqual(duty, 0.8)
    
    def test_duty_from_schedule_edge_cases(self):
        """Test duty calculation edge cases"""
        schedule = [{
            "start": "23:30",
            "end": "01:30",  # Crosses midnight
            "duty": 0.4
        }]
        
        # This should be handled gracefully (start > end)
        # Implementation may vary - test that it doesn't crash
        duty = self.duty_from_schedule(schedule, 60, 0)  # 1:00 AM
        self.assertIsInstance(duty, (int, float))
        self.assertGreaterEqual(duty, 0.0)
        self.assertLessEqual(duty, 1.0)


if __name__ == '__main__':
    unittest.main()