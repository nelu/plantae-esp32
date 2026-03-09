import time
import gc

import uasyncio as asyncio
from logging import LOG

from ..adapters.config_manager import CFG
from datetime import local_minutes, local_time_tuple


def _log_mem(label):
    if not LOG:
        return
    try:
        free = gc.mem_free()
        alloc = gc.mem_alloc() if hasattr(gc, "mem_alloc") else None
        task_count = None
        try:
            if hasattr(asyncio, "all_tasks"):
                task_count = len(asyncio.all_tasks())
            elif hasattr(asyncio, "Task") and hasattr(asyncio.Task, "all_tasks"):
                task_count = len(asyncio.Task.all_tasks())
        except Exception:
            task_count = None
        LOG.info("%s free=%s alloc=%s tasks=%s", label, free, alloc, task_count)
    except Exception:
        pass


async def task_wifi_status(sup):
    """Update IP/signal without managing reconnects."""
    while True:
        try:
            if not sup.wifi:
                await asyncio.sleep(5)
                continue

            if sup.is_provisioning:
                if hasattr(sup.wifi, "ap_ip"):
                    new_ip = sup.wifi.ap_ip()
                    if sup.state.ip != new_ip:
                        sup.state.ip = new_ip
                        if LOG: LOG.info("AP IP: %s", sup.state.ip)
            else:
                if sup.wifi.is_connected():
                    new_ip = sup.wifi.ip()
                    if sup.state.ip != new_ip:
                        sup.state.ip = new_ip
                        if LOG: LOG.info("WiFi IP: %s", sup.state.ip)
                    try:
                        sup.state.signal = sup.wifi.get_rssi()
                    except Exception:
                        pass
                else:
                    sup.state.ip = "0.0.0.0"
        except Exception as e:
            if LOG: LOG.error("WiFi Status Error: %s", e)

        await asyncio.sleep(5)


async def task_reboot_watch(sup):
    while True:
        sup._maybe_reboot()
        await asyncio.sleep_ms(200)


async def task_ntp(sup):
    from adapters.device import sync_rtc_via_ntp
    ntp_cfg = CFG.data.get("ntp", {})
    #every = int(ntp_cfg.get("sync_every_s", 21600))
    every = 200

    host = ntp_cfg.get("host", "pool.ntp.org")
    initial_sync = True

    while True:
    #while not sup.state.ntp_ok:
        tz_offset = int(CFG.data.get("tz_offset_min", 0))

        if sup.wifi.is_connected():
            success = sync_rtc_via_ntp(host, retries=3, tz_offset_min=tz_offset)
            sup.state.ntp_ok = bool(success)
            if success:
                LOG.debug("NTP: synced")
                if initial_sync:
                    initial_sync = False
                    await asyncio.sleep(every)
                else:
                    await asyncio.sleep(every)
            else:
                LOG.debug("NTP: sync failed")
                retry_interval = 10 if initial_sync else 60
                await asyncio.sleep(retry_interval)
        else:
            await asyncio.sleep(5)


async def task_flow(sup):
    interval_ms = int(CFG.data["flow"].get("read_interval_ms", 1000))
    next_ms = time.ticks_add(time.ticks_ms(), interval_ms)
    while True:
        now = time.ticks_ms()
        if time.ticks_diff(now, next_ms) >= 0:
            flow = sup.service.flow
            flow.read(calibration=int(CFG.data["flow"].get("calibration", 0)))
            sup.state.flow_lps = flow.flow_lps
            sup.state.flow_lpm = flow.flow_lpm
            sup.state.volume_l = flow.volume_l
            sup.state.pulses = flow.pulses_total
            if sup.stats:
                sup.stats.accumulate_volume(sup.state.volume_l)
            next_ms = time.ticks_add(now, interval_ms)
        await asyncio.sleep_ms(20)


async def task_pwm_schedule(sup):
    from domain.scheduler import duty_from_schedule

    while True:
        if not sup.service.pwm_override and not (sup.service.dosing and sup.service.dosing.is_dosing):
            sched = CFG.data.get("schedule", {}).get("pwm", [])
            if sched:
                mins, secs = local_time_tuple()
                duty = duty_from_schedule(sched, mins, secs)
                sup.service.pwm.set(duty)
                sup.state.pwm_duty = duty
        await asyncio.sleep(1)


async def task_stats(sup):
    while True:
        if sup.stats:
            sup.stats.track_pwm_runtime(sup.state.pwm_duty)
            sup.stats.save_if_needed()
        await asyncio.sleep(1)


async def task_pwm_test_btn(sup):
    from machine import Pin

    btn_cfg = CFG.data.get("inputs", {}).get("pwm_test_btn", {})
    pin_num = btn_cfg.get("pin")
    if not pin_num:
        LOG.error("task_pwm_test_btn: button pin not set")
        return

    active_low = btn_cfg.get("active_low", True)
    test_duty = btn_cfg.get("test_duty", 1.0)

    btn = Pin(pin_num, Pin.IN)
    button_override_active = False

    while True:
        state = btn.value()
        pressed = (state == 0) if active_low else (state == 1)

        if pressed and not button_override_active:
            button_override_active = True
            sup.service.set_pwm_manual(test_duty, True, source="button")
        elif not pressed and button_override_active:
            button_override_active = False
            sup.service.set_pwm_manual(0, False, source="button")

        await asyncio.sleep_ms(50)


async def task_http(sup):
    if sup.http_server is None:
        if sup.is_provisioning:
            from app.provision import ProvisionHttp
            sup.http_api = ProvisionHttp(
                sup.service,
                sup.wifi
            )
        else:
            from adapters.http_api import HttpApi
            sup.http_api = HttpApi(sup.service)

        sup.http_server = await sup.http_api.serve(port=80)
        LOG.info("task_http: listening on :80")

    evt = asyncio.Event()
    await evt.wait()


async def task_wamp(sup):
    LOG.info("task_wamp: started")
    ntp_quiet_done = False
    fail_count = 0

    while not sup.has_reboot_scheduled():
        if not sup.wifi.is_connected():
            await asyncio.sleep(2)
            continue

        if not sup.state.ntp_ok:
            await asyncio.sleep(2)
            continue

        if not ntp_quiet_done:
            ntp_quiet_done = True
            await asyncio.sleep(3)

        try:
            _log_mem("task_wamp: pre-start")
            LOG.info("task_wamp: start run_forever. Signal: %d", sup.state.signal)
            gc.collect()
            await asyncio.sleep_ms(0)

            await sup.wamp.start(timeout_s=20)
            _log_mem("task_wamp: post-start")
            fail_count = 0

            while True:
                if sup.wamp._runner and sup.wamp._runner.done():
                    raise RuntimeError("wamp runner stopped")
                if sup.wamp.is_alive():
                    await sup.wamp.publish_status()
                await asyncio.sleep(1)
                gc.collect()

        except Exception as e:
            sup.state.wamp_ok = False
            sup.state.last_error = (e,)
            LOG.error("task_wamp: %r", e)
            _log_mem("task_wamp: failure")

            try:
                await sup.wamp.close()
            except Exception as e:
                LOG.error('task_wamp: wamp close error - %r', e)
            finally:
                gc.collect()
                await asyncio.sleep_ms(0)

            _log_mem("task_wamp: post-close")

            fail_count += 1
            if fail_count > 10:
                LOG.error("task_wamp: Too many failures (%d). Rebooting...", fail_count)
                sup.schedule_reboot()

            msg = str(e)
            eno = None
            if isinstance(e, OSError) and e.args:
                eno = e.args[0]

            if "send timeout" in msg:
                await asyncio.sleep(5)
            elif "MBEDTLS" in msg or "ALLOC_FAILED" in msg or eno == 12:
                LOG.error("task_wamp: Memory/SSL error. Aggressive GC and Cooldown.")
                gc.collect()
                await asyncio.sleep(10)
            elif eno == 16:
                gc.collect()
                await asyncio.sleep(4)
            else:
                await asyncio.sleep(2)
            gc.collect()


async def task_dosing(sup):
    """Update dosing controller regularly"""
    LOG.debug("task_dosing: started")
    while not sup.has_reboot_scheduled():
        if sup.service.dosing:
            mins = local_minutes()
            await sup.service.dosing.update(mins)
            sup.state.dosing_status = sup.service.dosing.get_dose_status()

        await asyncio.sleep(2)
