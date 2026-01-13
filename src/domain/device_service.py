from lib.logging import LOG


class DeviceService:
    __slots__ = (
        "state","config_mgr","_schedule_reboot",
        "flow","dosing","switches","pwm",
        "pwm_override","pwm_override_source",
    )
    def __init__(self, state, config_mgr, schedule_reboot, 
                 pwm_controller=None, flow_sensor=None, 
                 dosing_controller=None, switchbank=None):
        self.state = state
        self.config_mgr = config_mgr
        self._schedule_reboot = schedule_reboot
        self.flow = flow_sensor
        self.dosing = dosing_controller
        self.switches = switchbank
        self.pwm = None


        self.pwm_override = False
        self.pwm_override_source = None

    def get_status(self):
        return self.state.snapshot()

    def get_config(self):
        return self.config_mgr.cfg

    def patch_config(self, patch):
        self.config_mgr.update(patch)
        self.config_mgr.save()
        return True

    def reboot(self, timeout_s=1):
        self._schedule_reboot(timeout_s)
        return True

    def set_pwm_manual(self, duty, override=True, source="other"):
        """Set PWM duty manually with override flag. duty=0 releases override if override=False."""
        if duty == 0:
            override = False

        LOG.info("PWM: manual duty=%.2f override=%s source=%s (prev_source=%s)",
                 duty, override, source, self.pwm_override_source)

        self.pwm_override = override
        self.pwm_override_source = source if override else None

        if override:
            self.pwm.set(duty)
            self.state.pwm_duty = duty
        # If override is False, task_pwm_schedule will resume schedule on next tick

    async def start_dose(self, quantity, is_manual=True):
        if self.dosing:
            return await self.dosing.start_dose(quantity, is_manual=is_manual)
        return False

    def stop_dose(self):
        if self.dosing:
            return self.dosing.stop_dose()
        return False

    def get_dose_status(self):
        if self.dosing:
            return self.dosing.get_dose_status()
        return {}

    def reset_counters(self):
        self.state.volume_l = 0.0
        self.state.pulses = 0
        if self.flow:
            # Also reset internal sensor counters if exposed
            if hasattr(self.flow, "_vol"): self.flow._vol = 0.0
            if hasattr(self.flow, "_total"): self.flow._total = 0
        return True

    def set_switch(self, idx, on):
        if self.switches:
            ok = self.switches.set(idx, on)
            if ok:
                self.state.switches[:] = self.switches.values[:]
            return ok
        return False

    def set_all_switches(self, on):
        if self.switches:
            ok = self.switches.set_all(on)
            self.state.switches[:] = self.switches.values[:]
            return ok
        return False

