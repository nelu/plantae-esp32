import uasyncio as asyncio
import time
from machine import I2C, Pin, reset

from adapters.wifi import Wifi
from adapters.ntp import sync as ntp_sync
from adapters.http_api import HttpApi
from adapters.config_manager import ConfigManager
from adapters.wamp_bridge import WampBridge
from lib.logging import Logger, DEBUG, getLogger, basicConfig

from domain.state import DeviceState
from domain.scheduler import duty_from_schedule
from domain.controllers import SwitchBank

from drivers.pca9685 import PCA9685
from drivers.pwm_out import PwmOut
from drivers.flowsensor.flowsensor import FlowSensor
from drivers.flowsensor import types as flowtypes

from app.device_id import get_device_id

def configure_logging(cfg):
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

LOG = None  # Will be set after config is loaded

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

        self._reboot_at = None
        self.wamp = None

    def schedule_reboot(self, t_s=1):
        if t_s < 1: t_s = 1
        self._reboot_at = time.ticks_add(time.ticks_ms(), int(t_s*1000))

    def _maybe_reboot(self):
        if self._reboot_at and time.ticks_diff(time.ticks_ms(), self._reboot_at) >= 0:
            reset()

    def _local_minutes(self):
        tz = int(self.cfg.get("schedule", {}).get("tz_offset_min", 0))
        t = time.time() + tz*60
        lt = time.localtime(t)
        return lt[3]*60 + lt[4]

    def _init_hw(self):
        pwm_cfg = self.cfg["outputs"]["pwm"]
        self.pwm = PwmOut(pwm_cfg["pin"], pwm_cfg.get("freq",20000), pwm_cfg.get("active_low",False))

        pca_cfg = self.cfg["outputs"]["pca9685"]
        if pca_cfg.get("enabled", True):
            i2c = I2C(int(pca_cfg.get("i2c_id",0)),
                      scl=Pin(int(pca_cfg.get("scl",22))),
                      sda=Pin(int(pca_cfg.get("sda",21))),
                      freq=int(pca_cfg.get("freq",400000)))
            pca = PCA9685(i2c, int(pca_cfg.get("addr",64)))
            pca.set_pwm_freq(int(pca_cfg.get("pwm_freq",1000)))
            self.switchbank = SwitchBank(pca, channels=int(pca_cfg.get("channels",16)))

        fcfg = self.cfg["flow"]
        ppl = getattr(flowtypes, fcfg.get("type","YFS401"), flowtypes.YFS401)
        self.flow = FlowSensor(ppl, fcfg.get("pin",14))
        self.flow.begin(pullup=bool(fcfg.get("pullup_external", True)))

    async def task_wifi(self):
        while True:
            try:
                ok = await self.wifi.ensure(self.cfg["wifi"]["ssid"], self.cfg["wifi"]["password"])
                self.state.ip = self.wifi.ip()
                if not ok:
                    self.state.last_error = "wifi"
            except Exception as e:
                self.state.last_error = "wifi:%s" % e
                if LOG: LOG.exception("wifi:", exc_info=e)
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
                    if LOG: LOG.debug("NTP: synced, time=%d" % time.time())
                    if initial_sync:
                        initial_sync = False
                        # After first successful sync, use normal interval
                        await asyncio.sleep(every)
                    else:
                        await asyncio.sleep(every)
                else:
                    if LOG: LOG.debug("NTP: sync failed")
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
                self.flow.read(calibration=int(self.cfg["flow"].get("calibration",0)))
                self.state.flow_lps = self.flow.flow_lps
                self.state.flow_lpm = self.flow.flow_lpm
                self.state.volume_l = self.flow.volume_l
                self.state.pulses = self.flow.pulses_total
                next_ms = time.ticks_add(now, interval_ms)
            await asyncio.sleep_ms(20)

    async def task_pwm_schedule(self):
        while True:
            sched = self.cfg.get("schedule", {}).get("pwm", [])
            duty = duty_from_schedule(sched, self._local_minutes())
            self.pwm.set(duty)
            self.state.pwm_duty = duty
            await asyncio.sleep(1)

    async def task_http(self):
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
        backoff = 1
        while True:
            if not self.wifi.is_connected():
                await asyncio.sleep(2)
                continue
            
            # Wait for NTP sync before attempting WAMP connection
            if not self.state.ntp_ok:
                await asyncio.sleep(2)
                continue
                
            try:
                self.wamp = WampBridge(self.cfg, self.state, self.switchbank, self.cfg_mgr, self.schedule_reboot)
                await self.wamp.connect()
                backoff = 1
                while self.wamp and self.wamp.client and self.wamp.client._alive:
                    await self.wamp.publish_sense()
                    await self.wamp.publish_status()
                    await asyncio.sleep(1)
            except Exception as e:
                self.state.wamp_ok = False
                self.state.last_error = "wamp:%s" % (e,)
                try:
                    if self.wamp:
                        await self.wamp.close()
                except Exception:
                    pass
                self.wamp = None
                await asyncio.sleep(backoff)
                backoff = 2*backoff if backoff < 60 else 60

    async def run(self):
        try:
            self._init_hw()
            LOG.info("Hardware initialized successfully")
            
            asyncio.create_task(self.task_wifi())
            asyncio.create_task(self.task_ntp())
            asyncio.create_task(self.task_http())
            asyncio.create_task(self.task_flow())
            asyncio.create_task(self.task_pwm_schedule())
            asyncio.create_task(self.task_wamp())
            
            LOG.info("All tasks started successfully")

            loop_count = 0
            while True:
                self._maybe_reboot()
                
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
