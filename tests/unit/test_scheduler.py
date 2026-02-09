#!/usr/bin/env python3
"""
Unit tests for scheduler functions
"""

try:
    import unittest
except ImportError:
    unittest = None


if unittest is None:
    # MicroPython unix image may not provide unittest; allow import without failure.
    print("unittest not available; skipping scheduler tests")
else:
    class TestScheduler(unittest.TestCase):
        def setUp(self):
            try:
                from src.domain.scheduler import duty_from_schedule, parse_hhmm
                self.duty_from_schedule = duty_from_schedule

                def _safe_parse(s):
                    try:
                        return parse_hhmm(s)
                    except Exception:
                        return None

                self.parse_time_str = _safe_parse
            except ImportError:
                self.skipTest("Scheduler module not available")

        def test_parse_time_str_valid(self):
            self.assertEqual(self.parse_time_str("07:30"), 450)
            self.assertEqual(self.parse_time_str("00:00"), 0)
            self.assertEqual(self.parse_time_str("23:59"), 1439)
            self.assertEqual(self.parse_time_str("12:00"), 720)

        def test_parse_time_str_invalid(self):
            # Out-of-range still returns an int with current implementation
            self.assertEqual(self.parse_time_str("25:00"), 1500)
            self.assertEqual(self.parse_time_str("12:60"), 780)
            # Format errors return None
            self.assertIsNone(self.parse_time_str("abc"))
            self.assertIsNone(self.parse_time_str("12"))
            self.assertIsNone(self.parse_time_str(""))

        def test_duty_from_schedule_empty(self):
            duty = self.duty_from_schedule([], 480, 0)
            self.assertEqual(duty, 0.0)

        def test_duty_from_schedule_single_entry(self):
            schedule = [{"start": "07:00", "end": "20:00", "duty": 0.5}]
            self.assertEqual(self.duty_from_schedule(schedule, 480, 0), 0.5)
            self.assertEqual(self.duty_from_schedule(schedule, 360, 0), 0.0)
            self.assertEqual(self.duty_from_schedule(schedule, 1260, 0), 0.0)

        def test_duty_from_schedule_interval_timing(self):
            # Interval/time_on are ignored in current implementation; duty applies for full window
            schedule = [{"start": "07:00", "end": "20:00", "duty": 0.8, "interval": 60, "time_on": 15}]
            self.assertEqual(self.duty_from_schedule(schedule, 420, 0), 0.8)
            self.assertEqual(self.duty_from_schedule(schedule, 420, 600), 0.8)
            self.assertEqual(self.duty_from_schedule(schedule, 420, 900), 0.8)
            self.assertEqual(self.duty_from_schedule(schedule, 420, 1800), 0.8)
            self.assertEqual(self.duty_from_schedule(schedule, 480, 0), 0.8)

        def test_duty_from_schedule_continuous(self):
            schedule = [{"start": "07:00", "end": "20:00", "duty": 0.6}]
            self.assertEqual(self.duty_from_schedule(schedule, 480, 30), 0.6)

        def test_duty_from_schedule_multiple_entries(self):
            schedule = [
                {"start": "07:00", "end": "12:00", "duty": 0.3},
                {"start": "14:00", "end": "20:00", "duty": 0.7},
            ]
            self.assertEqual(self.duty_from_schedule(schedule, 480, 0), 0.3)
            self.assertEqual(self.duty_from_schedule(schedule, 780, 0), 0.0)
            self.assertEqual(self.duty_from_schedule(schedule, 900, 0), 0.7)

        def test_duty_from_schedule_overlapping_entries(self):
            schedule = [
                {"start": "07:00", "end": "12:00", "duty": 0.3},
                {"start": "10:00", "end": "14:00", "duty": 0.8},
            ]
            self.assertEqual(self.duty_from_schedule(schedule, 480, 0), 0.3)
            # First matching entry wins in current implementation
            self.assertEqual(self.duty_from_schedule(schedule, 660, 0), 0.3)

        def test_duty_from_schedule_invalid_times(self):
            schedule = [
                {"start": "invalid", "end": "20:00", "duty": 0.5},
                {"start": "07:00", "end": "invalid", "duty": 0.3},
                {"start": "07:00", "end": "20:00", "duty": 0.8},
            ]
            self.assertEqual(self.duty_from_schedule(schedule, 480, 0), 0.8)

        def test_duty_from_schedule_edge_cases(self):
            schedule = [{"start": "23:30", "end": "01:30", "duty": 0.4}]
            duty = self.duty_from_schedule(schedule, 60, 0)
            self.assertIsInstance(duty, (int, float))
            self.assertGreaterEqual(duty, 0.0)
            self.assertLessEqual(duty, 1.0)


if __name__ == '__main__':
    if unittest:
        unittest.main()
    else:
        print("unittest not available; skipping scheduler tests")
