import uasyncio as asyncio

from domain.state import DeviceState
from logging import LOG
import time

class DosingController:
    def __init__(self, flow_sensor, output_controller, config, state=None, stats=None, alerts_mgr=None, activity_update=None):
        self.flow_sensor = flow_sensor
        self.output_controller = output_controller
        self.config = config
        self.state = state
        self.stats = stats
        self.is_dosing = False
        self.dose_start_volume = 0.0
        self.target_quantity = 0.0
        self.dose_start_time = 0
        self.timeout_s = 60  # 5 minute timeout for safety
        self.tz_offset_min = int(self.config.get("schedule", {}).get("tz_offset_min", 0))
        self.last_auto_dose_day = -1  # Track daily auto-dosing (local day)
        self.activity_update = activity_update
        if self.stats:
            try:
                ts = int(self.stats.data.get("last_dose_ts", 0) or 0)
                ts_local_day = self._ts_to_local_day(ts) if ts > 0 else -1
                self.last_auto_dose_day = ts_local_day
            except Exception:
                self.last_auto_dose_day = -1
        
    def _parse_time(self, time_str):
        """Parse HH:MM format to minutes since midnight"""
        h, m = time_str.split(":")
        return int(h) * 60 + int(m)

    def _local_wday(self):
        """Return local weekday index (Mon=0..Sun=6) using tz offset"""
        t = self._unix_now() + self.tz_offset_min * 60
        lt = time.localtime(t)
        return int(lt[6])

    def _current_local_day(self):
        """Day number since epoch in local time (tz adjusted)"""
        return int((self._unix_now() + self.tz_offset_min * 60) // 86400)

    def _ts_to_local_day(self, ts):
        return int((int(ts) + self.tz_offset_min * 60) // 86400)

    @staticmethod
    def _unix_now():
        return int(time.time()) + DeviceState.UNIX_EPOCH_OFFSET
    
    async def start_dose(self, quantity_l, is_manual=False):
        """Start dosing a specific quantity in milliliters"""
        if self.is_dosing:
            LOG.warning("Dosing already in progress")
            return False
            
        dosing_cfg = self.config.get("schedule", {}).get("dosing", {})
        output_name = dosing_cfg.get("output", "pwm")
        output_duty = dosing_cfg.get("duty", 0.5)

        
        if output_name != "pwm":
            LOG.error("Only PWM output supported for dosing currently")
            return False
            
        self.is_dosing = True
        self._is_manual_dose = is_manual
        self.dose_start_volume = self.flow_sensor.volume_l
        self.target_quantity = float(quantity_l)
        self.dose_start_time = time.time()

        # Start the output at full duty
        self.output_controller.set(output_duty)
        if self.state:
            self.state.pwm_duty = output_duty

        self.notify_status()
        LOG.info("Started dosing %.3f L (start_volume=%.3f L) %s duty %.3f",
                 self.target_quantity, self.dose_start_volume, 
                 "(manual)" if is_manual else "(auto)", output_duty)
        return True
    
    def stop_dose(self):
        """Stop dosing immediately"""
        if not self.is_dosing:
            return False
            
        self.output_controller.set(0.0)
        self.is_dosing = False
        if self.state:
            self.state.pwm_duty = 0.0
        
        dosed_volume = self.flow_sensor.volume_l - self.dose_start_volume
        duration = time.time() - self.dose_start_time
        
        LOG.info("Stopped dosing: target=%.3f L, actual=%.3f L, duration=%.1f s", 
                 self.target_quantity, dosed_volume, duration)
        self.notify_status()

        return True
    
    def get_dose_status(self):
        """Get current dosing status"""
        if not self.is_dosing:
            return {
                "active": False,
                "target_l": 0.0,
                "dosed_l": 0.0,
                "remaining_l": 0.0,
                "duration_s": 0
            }
            
        dosed_volume = self.flow_sensor.volume_l - self.dose_start_volume
        remaining = max(0.0, self.target_quantity - dosed_volume)
        duration = time.time() - self.dose_start_time
        
        return {
            "active": True,
            "target_l": self.target_quantity,
            "dosed_l": dosed_volume,
            "remaining_l": remaining,
            "duration_s": duration
        }

    def notify_status(self):
        if not self.activity_update:
            return
        try:
            asyncio.create_task(self.activity_update())
            #asyncio.create_task(self.activity_update({'dosing': self.get_dose_status()}))
        except Exception as e:
            LOG.error("notify_activity failed: %s", e)

    async def update(self, local_minutes, wamp=None):
        """Update dosing state - call this regularly from main loop"""
        # Check for automatic dosing
        await self._check_auto_dose(local_minutes)
        
        if not self.is_dosing:
            return
            
        # Check timeout
        duration = time.time() - self.dose_start_time
        if duration > self.timeout_s:
            LOG.error("Dosing timeout after %.1f seconds", duration)
            self.state.alerts.set_alert("dosing", "timeout", ts=self.dose_start_time, persist=True)
            self.stop_dose()
            return
            
        # Check if target reached
        dosed_volume = self.flow_sensor.volume_l - self.dose_start_volume
        if dosed_volume >= self.target_quantity:
            LOG.info("Dosing complete: %.3f L in %.1f seconds", 
                     dosed_volume, duration)

            if not self._is_manual_dose and self.stats:
                self.stats.record_dose(time.time(), persist_immediately=True)
                self.last_auto_dose_day = self._current_local_day()
            self.stop_dose()
            return
            
    async def _check_auto_dose(self, local_minutes):
        """Check if we should start automatic dosing"""
        if self.is_dosing:  # Don't auto-dose if already dosing
            return
            
        dosing_cfg = self.config.get("schedule", {}).get("dosing", {})
        days = dosing_cfg.get("days") or []
        if not isinstance(days, list) or len(days) != 7:
            return

        current_day = self._current_local_day()
        if self.last_auto_dose_day >= 0 and current_day <= self.last_auto_dose_day:
            return

        day_idx = self._local_wday()
        start_str = days[day_idx]
        if not start_str:
            return

        try:
            start_min = self._parse_time(str(start_str))
        except Exception:
            LOG.error("Invalid dosing time for day %d: %s", day_idx, start_str)
            return

        if local_minutes >= start_min:
            quantity = float(dosing_cfg.get("quantity", 0) or 0)
            if quantity <= 0:
                return
            alert = self.state.alerts.get_alert("dosing")
            if alert:
                return
            success = await self.start_dose(quantity)
            if success:
                self.last_auto_dose_day = current_day
                LOG.info("Started automatic daily dose: %.3f L", quantity)
