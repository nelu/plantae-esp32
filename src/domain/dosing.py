import time

from lib.logging import getLogger
LOG = getLogger("dosing")


class DosingController:
    def __init__(self, flow_sensor, output_controller, config):
        self.flow_sensor = flow_sensor
        self.output_controller = output_controller
        self.config = config
        self.is_dosing = False
        self.dose_start_volume = 0.0
        self.target_quantity = 0.0
        self.dose_start_time = 0
        self.timeout_s = 300  # 5 minute timeout for safety
        self.last_auto_dose_day = -1  # Track daily auto-dosing
        
    def _parse_time(self, time_str):
        """Parse HH:MM format to minutes since midnight"""
        h, m = time_str.split(":")
        return int(h) * 60 + int(m)
    
    def _is_dosing_time(self, local_minutes):
        """Check if current time is within dosing window"""
        dosing_cfg = self.config.get("schedule", {}).get("dosing", {})
        if not dosing_cfg:
            return False
            
        start_min = self._parse_time(dosing_cfg.get("start", "08:00"))
        end_min = self._parse_time(dosing_cfg.get("end", "20:10"))
        
        return start_min <= local_minutes < end_min
    
    async def start_dose(self, quantity_l, is_manual=False):
        """Start dosing a specific quantity in liters"""
        if self.is_dosing:
            LOG.warning("Dosing already in progress")
            return False
            
        dosing_cfg = self.config.get("schedule", {}).get("dosing", {})
        output_name = dosing_cfg.get("output", "pwm")
        
        if output_name != "pwm":
            LOG.error("Only PWM output supported for dosing currently")
            return False
            
        self.is_dosing = True
        self._is_manual_dose = is_manual
        self.dose_start_volume = self.flow_sensor.volume_l
        self.target_quantity = float(quantity_l)
        self.dose_start_time = time.time()
        
        # Start the output at full duty
        self.output_controller.set(1.0)
        
        LOG.info("Started dosing %.3f L (start_volume=%.3f L) %s", 
                 self.target_quantity, self.dose_start_volume, 
                 "(manual)" if is_manual else "(auto)")
        return True
    
    def stop_dose(self):
        """Stop dosing immediately"""
        if not self.is_dosing:
            return False
            
        self.output_controller.set(0.0)
        self.is_dosing = False
        
        dosed_volume = self.flow_sensor.volume_l - self.dose_start_volume
        duration = time.time() - self.dose_start_time
        
        LOG.info("Stopped dosing: target=%.3f L, actual=%.3f L, duration=%.1f s", 
                 self.target_quantity, dosed_volume, duration)
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
    
    async def update(self, local_minutes):
        """Update dosing state - call this regularly from main loop"""
        # Check for automatic dosing
        await self._check_auto_dose(local_minutes)
        
        if not self.is_dosing:
            return
            
        # Check timeout
        duration = time.time() - self.dose_start_time
        if duration > self.timeout_s:
            LOG.error("Dosing timeout after %.1f seconds", duration)
            self.stop_dose()
            return
            
        # Check if target reached
        dosed_volume = self.flow_sensor.volume_l - self.dose_start_volume
        if dosed_volume >= self.target_quantity:
            LOG.info("Dosing complete: %.3f L in %.1f seconds", 
                     dosed_volume, duration)
            self.stop_dose()
            return
            
        # Check if we're outside dosing window (safety)
        if not self._is_manual_dose and not self._is_dosing_time(local_minutes):
            LOG.warning("Stopping dosing - outside time window")
            self.stop_dose()
            return
    
    async def _check_auto_dose(self, local_minutes):
        """Check if we should start automatic dosing"""
        if self.is_dosing:  # Don't auto-dose if already dosing
            return
            
        dosing_cfg = self.config.get("schedule", {}).get("dosing", {})
        if not dosing_cfg or not dosing_cfg.get("quantity", 0):
            return
            
        # Only dose once per day
        current_day = int(time.time() // 86400)  # Days since epoch
        if self.last_auto_dose_day == current_day:
            return
            
        # Check if we're at the start of the dosing window
        start_min = self._parse_time(dosing_cfg.get("start", "08:00"))
        if abs(local_minutes - start_min) <= 1:  # Within 1 minute of start time
            quantity = float(dosing_cfg.get("quantity", 0))
            if quantity > 0:
                success = await self.start_dose(quantity)
                if success:
                    self.last_auto_dose_day = current_day
                    LOG.info("Started automatic daily dose: %.3f L", quantity)