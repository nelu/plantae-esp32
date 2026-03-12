import time
import gc

import uasyncio as asyncio
from ..adapters.config_manager import CFG
from . import tasks

from logging import LOG
# from logging import Logger, DEBUG
# LOG = Logger('root', DEBUG)

class Supervisor:
    def __init__(self):
        from ..domain.state import DeviceState
        from ..domain.device_service import DeviceService
        from ..adapters.wamp_bridge import WampBridge
        from ..domain.stats import StatsManager

        # CFG.load()

        self.stats = StatsManager()
        self.stats.load()

        # DeviceState owns alerts manager; use it directly
        self.state = DeviceState(CFG.device_id, stats_mgr=self.stats)

        self.is_provisioning = not ((CFG.data.get("wifi") or {}).get("ssid") or "").strip()
        # Initialize centralized device service
        self.service = DeviceService(
            self.state,
            self.schedule_reboot,
            stats_mgr=self.stats,
        )

        if self.is_provisioning:
            self.service.indicator.blink(freq_hz=3)

            from .provision import ProvisionWifi
            self.wifi = ProvisionWifi()
        else:
            from ..adapters.wifi import Wifi
            self.wifi = Wifi()

        self.switchbank = None
        # self.flow = None
        # self.dosing_controller = None

        self._reboot_at = None
        # self.wamp = None
        self.http_server = None
        self.http_api = None

        self.wamp = WampBridge(self.service)

        gc.collect()



    async def _announce_reboot(self):
        if self.wamp:
            try:
                await self.wamp.publish_announce("announce.offline")
                await self.wamp.close()
            except Exception as e:
                LOG.error("Failed to announce offline: %s", e)



    def has_reboot_scheduled(self):
        return self._reboot_at

    def schedule_reboot(self, t_s=1):
        if t_s < 1: t_s = 1
        LOG.info("Reboot scheduled in %ds", t_s)
        self._reboot_at = time.ticks_add(time.ticks_ms(), int(t_s * 1000))

        # Trigger offline announcement in background
        asyncio.create_task(self._announce_reboot())

    def _maybe_reboot(self):
        if self._reboot_at and time.ticks_diff(time.ticks_ms(), self._reboot_at) >= 0:
            try:
                self.service.shutdown_outputs()
            except Exception as e:
                LOG.error("shutdown before reset failed: %s", e)
            from machine import reset
            reset()

    async def run(self):
        import gc

        try:
            LOG.info("supervisor: run")

            asyncio.create_task(tasks.task_reboot_watch(self))
            asyncio.create_task(tasks.task_wifi_status(self))

            if self.is_provisioning:
                from .provision import dns_hijack_server
                LOG.info("run: Provisioning mode")

                asyncio.create_task(dns_hijack_server(ap_ip=self.wifi.ap_ip()))
                asyncio.create_task(tasks.task_http(self))
                # self.confirm_firmware_boot()

                # just idle; provisioning endpoint will save config + reboot
                while True:
                    await asyncio.sleep(1)

            # dont run any task without wifi
            # while not self.wifi or not self.wifi.is_connected():
            #     await asyncio.sleep(2)

            # normal mode continues:
            asyncio.create_task(tasks.task_ntp(self))
            #
            # while not self.state.ntp_ok:
            #     await asyncio.sleep(2)
            #     continue

            self.service.init_hardware(CFG.data, wamp_bridge=self.wamp)
            asyncio.create_task(tasks.task_stats(self))

            if CFG.data['wamp']['realm'] != "none":
                asyncio.create_task(tasks.task_flow(self))
                asyncio.create_task(tasks.task_pwm_schedule(self))
                asyncio.create_task(tasks.task_pwm_test_btn(self))
                asyncio.create_task(tasks.task_dosing(self))
            else:
                pass
                # asyncio.create_task(tasks.hardware_pairing_confirm(self))
            asyncio.create_task(tasks.task_wamp(self))

            # while not self.state.wamp_ok:
            #     await asyncio.sleep(1)
            #     gc.collect()



            # gc.collect()
            # if self.wamp:
            #     self.wamp.service = self.service
            #     # Only after WAMP is connected, start other memory-intensive tasks


            LOG.info("supervisor: tasks started")
            self.service.confirm_firmware_boot()

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
            
            LOG.error("Supervisor crashed. Rebooting in 10s...")
            await asyncio.sleep(10)
            from machine import reset
            reset()
