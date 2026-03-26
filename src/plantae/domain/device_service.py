from logging import LOG
from ..version import INDICATOR_LED, INDICATOR_LED_RGB
import uasyncio as asyncio
from ..adapters.config_manager import CFG


class DeviceService:
    __slots__ = (
        "state","_schedule_reboot",
        "flow","dosing","switches","pwm",
        "pwm_override","pwm_override_source","stats",
        "indicator", "publish_alerts", "_ota_update_in_progress",
    )
    def __init__(self, state, schedule_reboot, 
                 pwm_controller=None, flow_sensor=None, 
                   dosing_controller=None, switchbank=None,
                   stats_mgr=None):
        self.state = state
        self._schedule_reboot = schedule_reboot
        self.flow = flow_sensor
        self.dosing = dosing_controller
        self.switches = switchbank
        self.pwm = None

        self.publish_alerts = None

        self.stats = stats_mgr


        self.pwm_override = False
        self.pwm_override_source = None
        self.indicator = self._Indicator(INDICATOR_LED, rgb=INDICATOR_LED_RGB)
        self._ota_update_in_progress = False


    def init_hardware(self, cfg_data,  wamp_bridge,):
        """Initialize PWM, flow sensor, and dosing controller."""
        from ..drivers.pwm_out import PwmOut
        from ..drivers.flowsensor import FlowSensor, flowtypes
        from .dosing import DosingController
        import machine

        pwm_cfg = cfg_data["outputs"]["pwm"]
        fcfg = cfg_data["flow"]

        ppl = flowtypes.get(fcfg.get("type", "YFS401"))
        self.pwm = PwmOut(pwm_cfg["pin"], pwm_cfg.get("freq", 1000), pwm_cfg.get("active_low", False))

        self.flow = FlowSensor(ppl, fcfg.get("pin", 34))
        #self.flow.begin(pullup=bool(fcfg.get("pullup_external", True)), trigger=machine.Pin.IRQ_RISING)
        self.flow.begin(pullup=bool(fcfg.get("pullup_external", True)))

        self.publish_alerts = wamp_bridge.publish_alerts

        self.dosing = DosingController(
            self.flow,
            self.pwm,
            state=self.state,
            stats=self.stats,
            activity_update=wamp_bridge.publish_status,
            alert_set=self.set_alert
        )
        return True


    def get_status(self):
        return self.state.snapshot()

    def get_config(self):
        return CFG.data

    def patch_config(self, patch):
        from ..adapters.config_manager import CFG
        CFG.update(patch)
        CFG.save()
        return True

    def reboot(self, timeout_s=1):
        self._schedule_reboot(timeout_s)
        return True

    async def _do_upgrade(self, fw_url):
        import ota.update
        try:
            ota.update.from_json(fw_url, verify=True, verbose=True, reboot=False)
            LOG.warning("OTA update ready, scheduling reboot")
            self.reboot(2)
        except Exception as e:
            LOG.error("OTA update failed: %s", e)
            self.set_alert("firmware", "update failed")
            return {"ok": False, "error": "update_failed", "reason": str(e)}
        finally:
            self._ota_update_in_progress = False

    def confirm_firmware_boot(self):
        if not CFG.ota_capable:
            return
        try:
            from ..adapters import device
            if not device.pending_rollback():
                return
            import ota.rollback

            ota.rollback.cancel()
            self.state.alerts.clear_alert("firmware")
            LOG.info("OTA: firmware boot confirmed")
        except Exception as e:
            LOG.error("OTA: firmware confirm failed: %s", e)

    def update_firmware(self, version):
        from ..adapters.config_manager import CFG

        # if not isinstance(version, str):
        #     return {"ok": False, "error": "invalid_version"}

        fw_url = version.strip()
        if not fw_url:
            return {"ok": False, "error": "invalid_version"}

        if not getattr(CFG, "ota_capable", False):
            LOG.warning("OTA update rejected: device is not OTA-capable")
            return {"ok": False, "error": "ota_not_supported"}

        if self._ota_update_in_progress:
            return {"ok": False, "error": "update_in_progress"}

        self._ota_update_in_progress = True


        import gc
        # import ota.update

        gc.collect()
        LOG.info("OTA update: firmware=%s", fw_url)
        asyncio.create_task(self._do_upgrade(fw_url))
        # ota.update.from_json(fw_url, verify=True, verbose=True, reboot=False)
        # self.reboot(2)
        return {"ok": True, "status": "updating", "version": fw_url}


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
        saved = self.state.alerts.clear_alert(kind, persist=True)
        asyncio.create_task(self.publish_alerts())
        return saved

    def set_alert(self, kind, message, ts=None):
        saved = self.state.alerts.set_alert(kind, message, ts=ts, persist=True)
        asyncio.create_task(self.publish_alerts())

        return saved

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
        __slots__ = (
            "_pin", "_pwm", "active_low", "_PWM",
            "_rgb", "_np", "_anim_task", "_anim_mode", "_blink_freq", "_blink_duty",
        )

        def __init__(self, pin=5, rgb=False):
            from machine import Pin, PWM

            self._PWM = PWM
            self._pin = Pin(int(pin), Pin.OUT)
            self._pwm = None
            self.active_low = True  # legacy mono indicator default

            self._rgb = bool(rgb)
            self._np = None
            self._anim_task = None
            self._anim_mode = None
            self._blink_freq = 1.0
            self._blink_duty = 0.5

            if self._rgb:
                try:
                    from neopixel import NeoPixel

                    self._np = NeoPixel(self._pin, 1)
                    self.active_low = False
                except Exception as e:
                    self._rgb = False
                    LOG.warning("indicator: rgb init failed on pin %s: %s", pin, e)

            self.off()

        def _clear_pwm(self):
            pwm = self._pwm
            if pwm:
                try:
                    pwm.deinit()
                except Exception:
                    pass
                self._pwm = None

        def _clear_animation(self):
            task = self._anim_task
            if task:
                try:
                    task.cancel()
                except Exception:
                    pass
            self._anim_task = None
            self._anim_mode = None

        def _write_rgb(self, r, g, b):
            if not self._np:
                return
            try:
                self._np[0] = (int(r), int(g), int(b))
                self._np.write()
            except Exception:
                pass

        @staticmethod
        def _wheel(pos):
            pos = int(pos) & 0xFF
            if pos < 85:
                return 255 - (pos * 3), pos * 3, 0
            if pos < 170:
                pos -= 85
                return 0, 255 - (pos * 3), pos * 3
            pos -= 170
            return pos * 3, 0, 255 - (pos * 3)

        @staticmethod
        async def _sleep_ms(asyncio, delay_ms):
            if hasattr(asyncio, "sleep_ms"):
                await asyncio.sleep_ms(delay_ms)
            else:
                await asyncio.sleep(delay_ms / 1000)

        async def _run_rgb_animation(self):
            try:
                import uasyncio as asyncio
            except Exception:
                import asyncio

            step_ms = 30
            phase_ms = 0
            hue = 0

            while True:
                mode = self._anim_mode

                if mode == "pulse":
                    period_ms = 3000
                    half = period_ms // 2
                    t = phase_ms % period_ms
                    if t < half:
                        level = (t * 255) // half
                    else:
                        level = ((period_ms - t) * 255) // half

                    min_g = 8
                    max_g = 96
                    green = min_g + ((max_g - min_g) * level) // 255
                    self._write_rgb(0, green, 0)

                elif mode == "rainbow_blink":
                    freq_hz = self._blink_freq if self._blink_freq > 0 else 1.0
                    period_ms = int(1000.0 / freq_hz)
                    if period_ms < step_ms:
                        period_ms = step_ms

                    duty = self._blink_duty
                    if duty < 0:
                        duty = 0
                    if duty > 1:
                        duty = 1

                    on_ms = int(period_ms * duty)
                    in_on_window = on_ms > 0 and (phase_ms % period_ms) < on_ms

                    if in_on_window:
                        r, g, b = self._wheel(hue)
                        self._write_rgb(r, g, b)
                    else:
                        self._write_rgb(0, 0, 0)

                    hue = (hue + 2) & 0xFF

                else:
                    return

                phase_ms += step_ms
                await self._sleep_ms(asyncio, step_ms)

        def _start_rgb_animation(self, mode, freq_hz=1, duty=0.5):
            if not self._rgb:
                return

            self._clear_pwm()
            self._clear_animation()
            self._anim_mode = mode

            try:
                self._blink_freq = float(freq_hz) if freq_hz is not None else 1.0
            except Exception:
                self._blink_freq = 1.0
            if self._blink_freq <= 0:
                self._blink_freq = 1.0

            self._blink_duty = 0.0 if duty is None else duty
            if self._blink_duty < 0:
                self._blink_duty = 0
            if self._blink_duty > 1:
                self._blink_duty = 1

            try:
                import uasyncio as asyncio
            except Exception:
                import asyncio

            try:
                self._anim_task = asyncio.get_event_loop().create_task(self._run_rgb_animation())
            except Exception:
                self._anim_task = None
                self._anim_mode = None

        def on(self):
            if self._rgb:
                self._start_rgb_animation("pulse")
                return

            self._clear_animation()
            self._clear_pwm()
            val = 0 if self.active_low else 1
            self._pin.value(val)

        def off(self):
            self._clear_animation()
            self._clear_pwm()
            if self._rgb:
                self._write_rgb(0, 0, 0)
                return

            val = 1 if self.active_low else 0
            self._pin.value(val)

        def blink(self, freq_hz=1, duty=0.5):
            if self._rgb:
                self._start_rgb_animation("rainbow_blink", freq_hz=freq_hz, duty=duty)
                return

            self._clear_animation()
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
            self._clear_animation()
            self._clear_pwm()
            if self._rgb:
                self._write_rgb(0, 0, 0)
                return

            try:
                self._pin.value(1 if self.active_low else 0)
            except Exception:
                pass
