import time

import uasyncio as asyncio
from lib.logging import LOG


class Supervisor:
    def __init__(self, config_path="config.json"):
        from domain.state import DeviceState
        from adapters.config_manager import ConfigManager
        from app.device_id import get_device_id
        from domain.device_service import DeviceService

        self.cfg_mgr = ConfigManager(config_path)
        self.cfg = self.cfg_mgr.load()

        self.device_id = get_device_id(self.cfg)
        self.state = DeviceState(self.device_id)

        wifi_cfg = self.cfg.get("wifi") or {}
        ssid = (wifi_cfg.get("ssid") or "").strip()
        self.is_provisioning = not ssid

        if self.is_provisioning:
            from app.provision import ProvisionWifi
            self.wifi = ProvisionWifi()
        else:
            from adapters.wifi import Wifi
            self.wifi = Wifi()

        self.switchbank = None
        # self.flow = None
        # self.dosing_controller = None

        self._reboot_at = None
        self.wamp = None
        self.http_server = None
        self.http_api = None

        # Initialize centralized device service
        self.service = DeviceService(
            self.state,
            self.cfg_mgr,
            self.schedule_reboot
        )

        import gc
        gc.collect()

    async def _announce_reboot(self):
        if self.wamp:
            try:
                await self.wamp.publish_announce("announce.offline")
            except Exception as e:
                LOG.error("Failed to announce offline: %s", e)

    def schedule_reboot(self, t_s=1):
        if t_s < 1: t_s = 1
        LOG.info("Reboot scheduled in %ds", t_s)
        self._reboot_at = time.ticks_add(time.ticks_ms(), int(t_s * 1000))

        # Trigger offline announcement in background
        asyncio.create_task(self._announce_reboot())

    def _maybe_reboot(self):
        if self._reboot_at and time.ticks_diff(time.ticks_ms(), self._reboot_at) >= 0:
            from machine import reset
            reset()

    def _local_minutes(self):
        tz = int(self.cfg.get("schedule", {}).get("tz_offset_min", 0))
        t = time.time() + tz * 60
        lt = time.localtime(t)
        return lt[3] * 60 + lt[4]

    def _local_time(self):
        """Return (minutes_from_midnight, seconds)"""
        tz = int(self.cfg.get("schedule", {}).get("tz_offset_min", 0))
        t = time.time() + tz * 60
        lt = time.localtime(t)
        return (lt[3] * 60 + lt[4], lt[5])

    def _init_hw(self):
        # from drivers.pca9685 import PCA9685
        # from machine import I2C, Pin
        # from domain.controllers import SwitchBank

        from drivers.pwm_out import PwmOut
        from drivers.flowsensor.flowsensor import FlowSensor
        from drivers.flowsensor import types as flowtypes
        from domain.dosing import DosingController

        pwm_cfg = self.cfg["outputs"]["pwm"]

        # pca_cfg = self.cfg["outputs"]["pca9685"]
        # if pca_cfg.get("enabled", True):
        #     i2c = I2C(int(pca_cfg.get("i2c_id",0)),
        #               scl=Pin(int(pca_cfg.get("scl",22))),
        #               sda=Pin(int(pca_cfg.get("sda",21))),
        #               freq=int(pca_cfg.get("freq",400000)))
        #     pca = PCA9685(i2c, int(pca_cfg.get("addr",64)))
        #     pca.set_pwm_freq(int(pca_cfg.get("pwm_freq",1000)))
        #     self.switchbank = SwitchBank(pca, channels=int(pca_cfg.get("channels",16)))

        fcfg = self.cfg["flow"]
        ppl = getattr(flowtypes, fcfg.get("type", "YFS401"), flowtypes.YFS401)
        # self.flow = FlowSensor(ppl, fcfg.get("pin",14))
        # self.flow.begin(pullup=bool(fcfg.get("pullup_external", True)))
        self.service.pwm = PwmOut(pwm_cfg["pin"], pwm_cfg.get("freq", 1000), pwm_cfg.get("active_low", False))

        # Initialize dosing controller
        # self.dosing_controller =DosingController(self.service.flow, self.service.pwm, self.cfg)

        # Update service with initialized components
        self.service.flow = FlowSensor(ppl, fcfg.get("pin", 14))
        self.service.flow.begin(pullup=bool(fcfg.get("pullup_external", True)))
        # refactor this instantiation into service
        self.service.dosing = DosingController(self.service.flow, self.service.pwm, self.cfg)
        # self.service.switches = self.switchbank

    async def task_wifi(self):
        """Provisioning: start AP only. Normal: keep STA connected."""
        ap_started = False
        ap_name = self.device_id  # or whatever naming you use

        while True:
            try:
                if self.is_provisioning:
                    if not ap_started:
                        self.wifi.start_ap(ap_name)
                        try:
                            self.wifi.sta.active(False)
                        except Exception:
                            pass
                        ap_started = True

                    new_ip = self.wifi.ap_ip()
                    if self.state.ip != new_ip:
                        self.state.ip = new_ip
                        if LOG: LOG.info("AP IP: %s", self.state.ip)

                else:
                    # Station mode (your current logic, but safer .get())
                    wifi_cfg = self.cfg.get("wifi") or {}
                    ssid = wifi_cfg.get("ssid")
                    pwd = wifi_cfg.get("password")

                    if ssid and not self.wifi.is_connected():
                        LOG.warning("task_wifi disconnected, reconnecting...")
                        await self.wifi.ensure(ssid, pwd)

                    if self.wifi.is_connected():
                        new_ip = self.wifi.ip()
                        if self.state.ip != new_ip:
                            self.state.ip = new_ip
                            if LOG: LOG.info("WiFi IP: %s", self.state.ip)

            except Exception as e:
                if LOG: LOG.error("WiFi Monitor Error: %s", e)

            await asyncio.sleep(5)

    async def task_reboot_watch(self):
        while True:
            self._maybe_reboot()
            await asyncio.sleep_ms(200)

    async def task_ntp(self):
        from adapters.ntp import sync as ntp_sync

        every = int(self.cfg.get("ntp", {}).get("sync_every_s", 21600))
        host = self.cfg.get("ntp", {}).get("host", "pool.ntp.org")
        initial_sync = True

        while True:
            if self.wifi.is_connected():
                success = await ntp_sync(host)
                self.state.ntp_ok = bool(success)
                if success:
                    if LOG: LOG.debug("NTP: synced")
                    if initial_sync:
                        initial_sync = False
                        await asyncio.sleep(every)
                    else:
                        await asyncio.sleep(every)
                else:
                    if LOG: LOG.debug("NTP: sync failed")
                    retry_interval = 10 if initial_sync else 60
                    await asyncio.sleep(retry_interval)
            else:
                await asyncio.sleep(5)

    async def task_flow(self):
        interval_ms = int(self.cfg["flow"].get("read_interval_ms", 1000))
        next_ms = time.ticks_add(time.ticks_ms(), interval_ms)
        while True:
            now = time.ticks_ms()
            if time.ticks_diff(now, next_ms) >= 0:
                flow = self.service.flow
                flow.read(calibration=int(self.cfg["flow"].get("calibration", 0)))
                self.state.flow_lps = flow.flow_lps
                self.state.flow_lpm = flow.flow_lpm
                self.state.volume_l = flow.volume_l
                self.state.pulses = flow.pulses_total
                next_ms = time.ticks_add(now, interval_ms)
            await asyncio.sleep_ms(20)

    async def task_pwm_schedule(self):
        from domain.scheduler import duty_from_schedule

        while True:
            # Skip schedule if override is active or dosing is active
            if not self.service.pwm_override and not (self.service.dosing and self.service.dosing.is_dosing):
                sched = self.cfg.get("schedule", {}).get("pwm", [])
                # config disabled
                if sched:
                    mins, secs = self._local_time()
                    duty = duty_from_schedule(sched, mins, secs)
                    self.service.pwm.set(duty)
                    self.state.pwm_duty = duty
            await asyncio.sleep(1)

    async def task_pwm_test_btn(self):
        from machine import Pin

        btn_cfg = self.cfg.get("inputs", {}).get("pwm_test_btn", {})
        pin_num = btn_cfg.get("pin")
        if not pin_num:
            LOG.error("task_pwm_test_btn: button pin not set")
            return  # No button configured

        active_low = btn_cfg.get("active_low", True)
        test_duty = btn_cfg.get("test_duty", 1.0)

        btn = Pin(pin_num, Pin.IN)
        button_override_active = False

        while True:
            state = btn.value()
            pressed = (state == 0) if active_low else (state == 1)

            if pressed and not button_override_active:
                # Button just pressed - activate test mode
                button_override_active = True
                self.service.set_pwm_manual(test_duty, True, source="button")
            elif not pressed and button_override_active:
                # Button released - return to schedule
                button_override_active = False
                self.service.set_pwm_manual(0, False, source="button")

            await asyncio.sleep_ms(50)

    async def task_http(self):
        if self.http_server is None:
            if self.is_provisioning:
                from app.provision import ProvisionHttp
                self.http_api = ProvisionHttp(
                    self.service,
                    self.wifi
                )
            else:
                from adapters.http_api import HttpApi
                self.http_api = HttpApi(self.service)

            self.http_server = await self.http_api.serve(port=80)
            LOG.info("task_http: listening on :80")

        evt = asyncio.Event()
        await evt.wait()

    def _patch_cfg(self, patch):
        if self.cfg_mgr:
            self.cfg = self.cfg_mgr.update(patch)
            self.cfg_mgr.save()
        else:
            pass

    async def task_wamp(self):
        if LOG: LOG.info("task_wamp: started")
        import gc

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
                LOG.info("task_wamp: connect. Free: %d", gc.mem_free())
                gc.collect()
                self.wamp = WampBridge(self.cfg, self.state, self.service)
                #                self.wamp = WampBridge(self.cfg, self.state, None)

                gc.collect()
                await asyncio.sleep_ms(0)

                await self.wamp.connect()
                backoff = 1

                while self.wamp and self.wamp.is_alive():
                    # await self.wamp.publish_sense()
                    await self.wamp.publish_status()
                    await asyncio.sleep(1)

                # Connection loop ended; close cleanly before reconnecting
                try:
                    if self.wamp:
                        await self.wamp.close()
                except Exception:
                    pass
                finally:
                    gc.collect()
                    await asyncio.sleep_ms(0)


            except Exception as e:
                # Make sure we tear down the previous bridge/socket
                try:
                    if self.wamp:
                        await self.wamp.close()
                except Exception:
                    pass
                finally:
                    gc.collect()
                    await asyncio.sleep_ms(0)

                self.state.wamp_ok = False
                self.state.last_error = "wamp:%r" % (e,)
                LOG.error(self.state.last_error)
                gc.collect()
                self.wamp = None

                # If the underlying error was OSError(16), cool down a bit more
                eno = None
                try:
                    if isinstance(e, OSError) and e.args:
                        eno = e.args[0]
                except Exception:
                    pass
                finally:
                    gc.collect()

                msg = str(e)
                if "send timeout" in msg:
                    await asyncio.sleep(5)
                elif eno == 16:
                    gc.collect()
                    await asyncio.sleep(4)
                else:
                    await asyncio.sleep(backoff)
                gc.collect()

                backoff = 2 * backoff if backoff < 60 else 60

    async def task_dosing(self):
        """Update dosing controller regularly"""
        while True:
            if self.service.dosing:
                mins = self._local_minutes()
                await self.service.dosing.update(mins)
                # Update state with current dosing status
                self.state.dosing_status = self.service.dosing.get_dose_status()
            await asyncio.sleep(0.5)  # Update twice per second for precision

    async def run(self):
        try:
            LOG.info("supervisor: run")

            asyncio.create_task(self.task_reboot_watch())
            asyncio.create_task(self.task_wifi())

            if self.is_provisioning:
                LOG.info("Provisioning mode")
                asyncio.create_task(self.task_http())

                # just idle; provisioning endpoint will save config + reboot
                while True:
                    await asyncio.sleep(1)

            # dont run any task without wifi
            while not self.wifi.is_connected():
                await asyncio.sleep(2)

            # normal mode continues:
            asyncio.create_task(self.task_ntp())
            import gc
            gc.collect()

            asyncio.create_task(self.task_wamp())
            gc.collect()

            while not self.state.wamp_ok:
                await asyncio.sleep(1)

            gc.collect()

            self._init_hw()
            # gc.collect()
            # if self.wamp:
            #     self.wamp.service = self.service
            #     # Only after WAMP is connected, start other memory-intensive tasks
            gc.collect()
            asyncio.create_task(self.task_flow())
            asyncio.create_task(self.task_pwm_schedule())
            asyncio.create_task(self.task_pwm_test_btn())
            asyncio.create_task(self.task_dosing())
            gc.collect()

            LOG.info("supervisor: tasks started")

            loop_count = 0
            while True:
                # Log memory usage every 60 seconds to track potential leaks
                loop_count += 1
                if loop_count % 240 == 0:  # Every 60 seconds (240 * 0.25s)
                    import gc
                    gc.collect()  # Force garbage collection
                    free_mem = gc.mem_free()
                    LOG.info("Memcheck: %d bytes free" % free_mem)
                    if free_mem < 10000:  # Less than 10KB free
                        LOG.error("Low memory warning: %d bytes" % free_mem)

                await asyncio.sleep(0.25)
        except Exception as e:
            LOG.error("supervisor exc: %s" % e)
            # print("CRITICAL ERROR:", e)
            # Don't let the system crash silently
            import sys
            sys.print_exception(e)
            raise

def start():
    print("BOOT: Waiting 5s for network cleanup...")
    time.sleep(5)
    sup = Supervisor("config.json")
    asyncio.run(sup.run())