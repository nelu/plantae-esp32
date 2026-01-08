import time

import uasyncio as asyncio
from machine import I2C, Pin, reset

from adapters.config_manager import ConfigManager
from adapters.ntp import sync as ntp_sync
from adapters.wifi import Wifi
from app.device_id import get_device_id
from domain.state import DeviceState
from lib.logging import Logger


def configure_logging(cfg):
    from lib.logging import getLogger

    """Configure logging from config file"""
    from lib.logging import basicConfig, DEBUG, INFO, WARNING, ERROR, CRITICAL

    # Map string levels to constants
    level_map = {
        "DEBUG": DEBUG,
        "INFO": INFO,
        "WARNING": WARNING,
        "ERROR": ERROR,
        "CRITICAL": CRITICAL
    }

    # Get logging config with defaults
    log_cfg = cfg.get("logging", {})
    default_level = level_map.get(log_cfg.get("level", "WARNING"), WARNING)

    # Configure basic logging with timestamp format
    log_format = log_cfg.get("format", "%(asctime)s %(levelname)s:%(name)s:%(message)s")
    date_format = log_cfg.get("date_format", "%H:%M:%S")
    basicConfig(level=default_level, format=log_format, datefmt=date_format)

    # Set timezone offset for logging timestamps
    tz_offset_min = cfg.get("schedule", {}).get("tz_offset_min", 0)
    import lib.logging as logging_module
    logging_module._tz_offset_s = tz_offset_min * 60

    # Configure individual loggers
    loggers_cfg = log_cfg.get("loggers", {})
    for logger_name, level_str in loggers_cfg.items():
        level = level_map.get(level_str, default_level)
        if logger_name == "root":
            logger = getLogger()
        else:
            logger = getLogger(logger_name)
        logger.setLevel(level)

    # Test logging with time debugging
    LOG = getLogger()
    LOG.info("Logging configured from config file")

    # Debug time values
    import time
    current_time = time.time()
    try:
        lt = time.localtime(current_time)
        LOG.info("Current time: %d, localtime: %04d-%02d-%02d %02d:%02d:%02d" %
                 (current_time, lt[0], lt[1], lt[2], lt[3], lt[4], lt[5]))
    except Exception as e:
        LOG.info("Time debug failed: %s, raw time: %d" % (e, current_time))

    return LOG


LOG : Logger  # Will be set after config is loaded


class Supervisor:
    def __init__(self, config_path="config.json"):
        self.cfg_mgr = ConfigManager(config_path)
        self.cfg = self.cfg_mgr.load()

        # Configure logging from config file
        global LOG
        LOG = configure_logging(self.cfg)

        self.device_id = get_device_id(self.cfg)
        self.state = DeviceState(self.device_id)

        self.wifi = Wifi()
        self.pwm = None
        self.switchbank = None
        self.flow = None
        self.dosing_controller = None

        self._reboot_at = None
        self.wamp = None

    def schedule_reboot(self, t_s=1):
        if t_s < 1: t_s = 1
        self._reboot_at = time.ticks_add(time.ticks_ms(), int(t_s * 1000))
        if LOG:
            LOG.info("schedule_reboot: %s" % self._reboot_at)


    async def _maybe_reboot(self):
        if self._reboot_at and time.ticks_diff(time.ticks_ms(), self._reboot_at) >= 0:
            if LOG:
                LOG.info("reset() triggered")
            
            # Attempt consistent graceful shutdown
            if self.wamp:
                try:
                    # Send announce.offline before reboot
                    await self.wamp.publish_announce("announce.offline")
                except Exception as e:
                    if LOG: LOG.error("Failed to send offline announce: %s", e)

            # Give some time for logs and network buffers to flush
            await asyncio.sleep(2)
            #reset()

    def _local_time(self):
        """
        Returns:
          (local_minutes_since_midnight, local_seconds_in_minute)
        respecting schedule.tz_offset_min.
        """
        tz = int(self.cfg.get("schedule", {}).get("tz_offset_min", 0))
        t = time.time() + tz * 60
        lt = time.localtime(t)
        return (lt[3] * 60 + lt[4], lt[5])

    def _local_minutes(self):
        # Backward-compatible helper (kept in case other code calls it)
        m, _s = self._local_time()
        return m


    def _init_hw(self):
        from drivers.pca9685 import PCA9685

        from drivers.pwm_out import PwmOut
        from drivers.flowsensor import FlowSensor, flowtypes
        from domain.controllers import SwitchBank

        pwm_cfg = self.cfg["outputs"]["pwm"]
        self.pwm = PwmOut(pwm_cfg["pin"], pwm_cfg.get("freq", 20000), pwm_cfg.get("active_low", False))

        pca_cfg = self.cfg["outputs"]["pca9685"]
        if pca_cfg.get("enabled", True):
            i2c = I2C(int(pca_cfg.get("i2c_id", 0)),
                      scl=Pin(int(pca_cfg.get("scl", 22))),
                      sda=Pin(int(pca_cfg.get("sda", 21))),
                      freq=int(pca_cfg.get("freq", 400000)))
            pca = PCA9685(i2c, int(pca_cfg.get("addr", 64)))
            pca.set_pwm_freq(int(pca_cfg.get("pwm_freq", 1000)))
            self.switchbank = SwitchBank(pca, channels=int(pca_cfg.get("channels", 16)))

        fcfg = self.cfg["flow"]
        ppl = flowtypes.get(fcfg.get("type", "YFS401"))
        self.flow = FlowSensor(ppl, fcfg.get("pin", 14))
        self.flow.begin(pullup=bool(fcfg.get("pullup_external", True)))

        # Initialize dosing controller
        from domain.dosing import DosingController
        self.dosing_controller = DosingController(self.flow, self.pwm, self.cfg)

    async def task_wifi(self):
        consecutive_failures = 0
        while True:
            try:
                # Check if already connected before trying to reconnect
                if self.wifi.is_connected():
                    self.state.ip = self.wifi.ip()
                    consecutive_failures = 0
                    await asyncio.sleep(5)  # Check less frequently when connected
                    continue

                ok = await self.wifi.ensure(self.cfg["wifi"]["ssid"], self.cfg["wifi"]["password"])
                self.state.ip = self.wifi.ip()
                if not ok:
                    consecutive_failures += 1
                    self.state.last_error = "wifi"
                    if LOG and consecutive_failures % 10 == 1:  # Log every 10th failure to reduce spam
                        LOG.warning("WiFi connection failed (attempt %d)" % consecutive_failures)
                else:
                    consecutive_failures = 0

            except Exception as e:
                consecutive_failures += 1
                self.state.last_error = "wifi:%s" % e
                if LOG and consecutive_failures % 10 == 1:  # Log every 10th failure
                    LOG.exception("WiFi error (attempt %d):" % consecutive_failures, exc_info=e)

            # Exponential backoff for failed connections
            if consecutive_failures > 0:
                delay = min(2 ** min(consecutive_failures // 5, 4), 30)  # Max 30 seconds
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(2)

    async def task_ntp(self):
        every = int(self.cfg.get("ntp", {}).get("sync_every_s", 21600))
        host = self.cfg.get("ntp", {}).get("host", "pool.ntp.org")
        initial_sync = True

        while True:
            if self.wifi.is_connected():
                success = await ntp_sync(host)
                self.state.ntp_ok = bool(success)
                if success:
                    LOG.info("NTP: synced, time=%d" % time.time())
                    if initial_sync:
                        initial_sync = False
                        # After first successful sync, use normal interval
                        await asyncio.sleep(every)
                    else:
                        await asyncio.sleep(every)
                else:
                    LOG.error("NTP: sync failed")
                    # Retry more frequently if sync fails, especially on startup
                    retry_interval = 10 if initial_sync else 60
                    await asyncio.sleep(retry_interval)
            else:
                await asyncio.sleep(2)

    async def task_flow(self):
        interval_ms = int(self.cfg["flow"].get("read_interval_ms", 1000))
        next_ms = time.ticks_add(time.ticks_ms(), interval_ms)
        while True:
            now = time.ticks_ms()
            if time.ticks_diff(now, next_ms) >= 0:
                self.flow.read(calibration=int(self.cfg["flow"].get("calibration", 0)))
                self.state.flow_lps = self.flow.flow_lps
                self.state.flow_lpm = self.flow.flow_lpm
                self.state.volume_l = self.flow.volume_l
                self.state.pulses = self.flow.pulses_total
                next_ms = time.ticks_add(now, interval_ms)
            await asyncio.sleep_ms(20)

    async def task_pwm_schedule(self):
        from domain.scheduler import duty_from_schedule

        while True:
            # Skip schedule if button override is active or dosing is active
            if not getattr(self, '_pwm_btn_override', False) and not (self.dosing_controller and self.dosing_controller.is_dosing):
                sched = self.cfg.get("schedule", {}).get("pwm", [])
                mins, secs = self._local_time()
                duty = duty_from_schedule(sched, mins, secs)
                self.pwm.set(duty)
                self.state.pwm_duty = duty
            await asyncio.sleep(1)

    async def task_pwm_test_btn(self):
        btn_cfg = self.cfg.get("inputs", {}).get("pwm_test_btn", {})
        pin_num = btn_cfg.get("pin")
        if not pin_num:
            LOG.error("PWM test button ping not set")
            return  # No button configured

        active_low = btn_cfg.get("active_low", True)
        test_duty = btn_cfg.get("test_duty", 1.0)

        btn = Pin(pin_num, Pin.IN)
        self._pwm_btn_override = False
        last_state = btn.value()

        while True:
            state = btn.value()
            pressed = (state == 0) if active_low else (state == 1)

            if pressed and not self._pwm_btn_override:
                # Button just pressed - activate test mode
                self._pwm_btn_override = True
                self.pwm.set(test_duty)
                self.state.pwm_duty = test_duty
                # if LOG:
                #     LOG.debug("PWM test button pressed: duty=%.2f", test_duty)
            elif not pressed and self._pwm_btn_override:
                # Button released - return to schedule
                self._pwm_btn_override = False
                # if LOG:
                #     LOG.debug("PWM test button released")

            last_state = state
            await asyncio.sleep_ms(50)

    async def task_http(self):
        from adapters.http_api import HttpApi

        api = HttpApi(
            get_status=self.state.snapshot,
            get_cfg=lambda: self.cfg,
            patch_cfg=self._patch_cfg,
            schedule_reboot=self.schedule_reboot,
            pwm_out=self.pwm,
            flow_sensor=self.flow,
        )
        await api.serve(port=80)
        while True:
            await asyncio.sleep(3600)

    def _patch_cfg(self, patch):
        self.cfg = self.cfg_mgr.update(patch)
        self.cfg_mgr.save()

    async def task_wamp(self):
        if LOG: LOG.info("task_wamp: started")

        backoff = 1
        ntp_quiet_done = False

        while True:
            if not self.wifi.is_connected():
                await asyncio.sleep(2)
                continue

            # Wait for NTP sync before attempting WAMP connection
            if not self.state.ntp_ok:
                await asyncio.sleep(2)
                continue

            # One-time quiet period after first NTP success (helps ESP32 TLS)
            if not ntp_quiet_done:
                ntp_quiet_done = True
                await asyncio.sleep(3)

            try:
                from adapters.wamp_bridge import WampBridge

                self.wamp = WampBridge(self.cfg, self.state, self.switchbank, self.cfg_mgr, self.schedule_reboot, self.dosing_controller)
                if LOG: LOG.info("task_wamp: connecting...")

                import gc
                gc.collect()
                await asyncio.sleep_ms(0)

                await self.wamp.connect()
                backoff = 1

                while self.wamp and self.wamp.is_alive():
                    # Periodically publish status to keep connection active
                    try:
                        await self.wamp.publish_sense()
                        await self.wamp.publish_status()
                        pass
                    except Exception as e:
                        # if LOG: LOG.debug("Status publish failed: %s", e)
                        pass
                    await asyncio.sleep(1)  # Publish every 1 seconds

                # Connection loop ended; close cleanly before reconnecting
                if LOG: LOG.warning("WAMP connection lost, reconnecting...")
                try:
                    if self.wamp:
                        await self.wamp.close()
                except Exception:
                    pass

                # Memory cleanup after disconnect
                import gc
                gc.collect()

            except Exception as e:
                # Make sure we tear down the previous bridge/socket
                try:
                    if self.wamp:
                        await self.wamp.close()
                except Exception:
                    pass

                # Memory cleanup after error/disconnect
                import gc
                gc.collect()

                await asyncio.sleep(1)

                self.state.wamp_ok = False
                self.state.last_error = "wamp:%r" % (e,)
                if LOG:
                    LOG.error("WAMP connect failed: type=%s repr=%r" % (type(e), e))
                try:
                    import sys
                    sys.print_exception(e)
                except Exception:
                    pass

                self.wamp = None

                # If the underlying error was OSError(16), cool down a bit more
                eno = None
                try:
                    if isinstance(e, OSError) and e.args:
                        eno = e.args[0]
                except Exception:
                    pass

                if eno == 16:
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(backoff)

                backoff = 2 * backoff if backoff < 60 else 60

    async def task_dosing(self):
        """Update dosing controller regularly"""
        while True:
            if self.dosing_controller:
                mins, _secs = self._local_time()
                await self.dosing_controller.update(mins)
                # Update state with current dosing status
                self.state.dosing_status = self.dosing_controller.get_dose_status()
            await asyncio.sleep(0.5)  # Update twice per second for precision

    async def run(self):
        try:
            LOG.info("Hardware initialized successfully")

            asyncio.create_task(self.task_wifi())
            asyncio.create_task(self.task_ntp())
            # Wait for WiFi + NTP (required for TLS cert validation)

            asyncio.create_task(self.task_wamp())
            while not self.state.wamp_ok:
                await asyncio.sleep(0.2)

            self._init_hw()

            asyncio.create_task(self.task_http())
            asyncio.create_task(self.task_flow())
            asyncio.create_task(self.task_pwm_schedule())
            asyncio.create_task(self.task_pwm_test_btn())
            asyncio.create_task(self.task_dosing())

            LOG.info("All tasks started successfully")

            loop_count = 0
            while True:
                await self._maybe_reboot()

                # Log memory usage every 60 seconds to track potential leaks
                loop_count += 1
                if loop_count % 240 == 0:  # Every 60 seconds (240 * 0.25s)
                    import gc
                    gc.collect()  # Force garbage collection
                    free_mem = gc.mem_free()
                    if LOG:
                        LOG.info("Memory check: %d bytes free" % free_mem)
                    if free_mem < 10000:  # Less than 10KB free
                        if LOG:
                            LOG.error("Low memory warning: %d bytes" % free_mem)

                await asyncio.sleep(0.25)
        except Exception as e:
            if LOG:
                LOG.error("Critical error in supervisor: %s" % e)
            print("CRITICAL ERROR:", e)
            # Don't let the system crash silently
            import sys
            sys.print_exception(e)
            raise
