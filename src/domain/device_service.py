from lib.logging import LOG


class DeviceService:
    __slots__ = (
        "state","config_mgr","_schedule_reboot",
        "flow","dosing","switches","pwm",
        "pwm_override","pwm_override_source","stats",
        "indicator",
    )
    def __init__(self, state, config_mgr, schedule_reboot, 
                 pwm_controller=None, flow_sensor=None, 
                  dosing_controller=None, switchbank=None,
                  stats_mgr=None):
        self.state = state
        self.config_mgr = config_mgr
        self._schedule_reboot = schedule_reboot
        self.flow = flow_sensor
        self.dosing = dosing_controller
        self.switches = switchbank
        self.pwm = None

        self.stats = stats_mgr


        self.pwm_override = False
        self.pwm_override_source = None
        self.indicator = self._Indicator(5)


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

    def shutdown_outputs(self):
        """Safely release active outputs before reboot/reset."""
        try:
            if self.dosing and getattr(self.dosing, "is_dosing", False):
                self.dosing.stop_dose()
        except Exception as e:
            LOG.error("shutdown_outputs: dosing stop failed: %s", e)

        self.pwm_override = False
        self.pwm_override_source = None

        pwm = self.pwm
        if pwm:
            try:
                pwm.set(0.0)
            except Exception as e:
                LOG.error("shutdown_outputs: pwm set failed: %s", e)
            try:
                pwm.release()
            except Exception as e:
                LOG.error("shutdown_outputs: pwm release failed: %s", e)

        try:
            self.state.pwm_duty = 0.0
        except Exception:
            pass

    def set_pwm_manual(self, duty, override=True, source="other"):
        """Set PWM duty manually with override flag. duty=0 releases override if override=False."""
        if duty == 0:
            override = False

        LOG.info("PWM: manual duty=%.2f override=%s source=%s (prev_source=%s)",
                 duty, override, source, self.pwm_override_source)

        self.pwm_override = override
        self.pwm_override_source = source if override else None

        pwm = self.pwm
        if not pwm:
            LOG.error("PWM: controller not initialized")
            return False

        # Always apply the requested duty so releases take effect immediately
        pwm.set(duty)
        self.state.pwm_duty = duty
        # If override is False, task_pwm_schedule will resume schedule on next tick


    def reset_counters(self):
        self.state.volume_l = 0.0
        self.state.pulses = 0
        if self.flow:
            # Also reset internal sensor counters if exposed
            if hasattr(self.flow, "_vol"): self.flow._vol = 0.0
            if hasattr(self.flow, "_total"): self.flow._total = 0
        return True

    def clear_alert(self, kind):
        return self.state.alerts.clear_alert(kind, persist=True)
         
    def set_alert(self, kind, message):
        return self.state.alerts.set_alert(kind, message, persist=True)

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

    # --- Indicator helper (built-in LED/buzzer) ---
    class _Indicator:
        __slots__ = ("_pin", "_pwm", "active_low", "_PWM")

        def __init__(self, pin=5):
            from machine import Pin, PWM

            self._PWM = PWM
            self.active_low = True  # LOLIN32 built-in LED is active low
            self._pin = Pin(int(pin), Pin.OUT)
            self._pwm = None
            self.off()

        def _clear_pwm(self):
            pwm = self._pwm
            if pwm:
                try:
                    pwm.deinit()
                except Exception:
                    pass
                self._pwm = None

        def on(self):
            self._clear_pwm()
            val = 0 if self.active_low else 1
            self._pin.value(val)

        def off(self):
            self._clear_pwm()
            val = 1 if self.active_low else 0
            self._pin.value(val)

        def blink(self, freq_hz=1, duty=0.5):
            pwm = self._pwm or self._PWM(self._pin)
            freq = int(freq_hz) if freq_hz and freq_hz > 0 else 1
            pwm.freq(freq)
            duty = 0.0 if duty is None else duty
            if duty < 0: duty = 0
            if duty > 1: duty = 1
            val = int(duty * 65535)
            if self.active_low:
                val = 65535 - val
            pwm.duty_u16(val)
            self._pwm = pwm

        def deinit(self):
            self._clear_pwm()
            try:
                self._pin.value(1 if self.active_low else 0)
            except Exception:
                pass
