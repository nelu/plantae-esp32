import time

import uasyncio as asyncio

from logging import LOG
from adapters.config_manager import ConfigManager
from adapters.wifi import Wifi
from app.provision import ProvisionWifi



def _maybe_factory_reset_button(hold_time_s=5, wait_window_s=5):
    hold_ms = int(hold_time_s * 1000)
    window_ms = int(max(hold_time_s, wait_window_s or 0) * 1000)

    try:
        from machine import Pin
    except Exception as e:
        if LOG: LOG.error("factory_reset: init failed: %s", e)
        time.sleep_ms(window_ms)
        return False

    btn_cfg = (ConfigManager.default().get("inputs") or {}).get("pwm_test_btn", {})
    pin_num = btn_cfg.get("pin")
    if pin_num is None:
        time.sleep_ms(window_ms)
        return False

    try:
        btn = Pin(pin_num, Pin.IN)
    except Exception as e:
        if LOG: LOG.error("factory_reset: cannot init pin %s: %s", pin_num, e)
        time.sleep_ms(window_ms)
        return False

    active_low = btn_cfg.get("active_low", True)
    required_state = 0 if active_low else 1

    pressed_start = None
    deadline = time.ticks_add(time.ticks_ms(), window_ms)

    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        now = time.ticks_ms()
        if btn.value() == required_state:
            if pressed_start is None:
                pressed_start = now
                LOG.warning("factory_reset: pressed")

            if time.ticks_diff(now, pressed_start) >= hold_ms:
                try:
                    import os

                    os.remove("config.mpk")
                    os.remove("stats.mpk")

                    LOG.warning("factory_reset: config.mpk removed; provisioning")
                    return True
                except Exception as e:
                    LOG.error("factory_reset: failed to remove config.mpk: %s", e)
                    return False
        else:
            pressed_start = None
        time.sleep_ms(50)

    return False


def _init_boot():
    LOG.info('_init_boot')

    _maybe_factory_reset_button(hold_time_s=4, wait_window_s=5)

    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.load()

    wifi_cfg = cfg.get("wifi") or {}
    ssid = (wifi_cfg.get("ssid") or "").strip()
    pwd = wifi_cfg.get("password")
    is_provisioning = not ssid

    LOG.info("boot: starting network, provisioning=%s", is_provisioning)

    wifi = ProvisionWifi() if is_provisioning else Wifi()

    if is_provisioning:
        try:
            wifi.start_ap(cfg_mgr.device_id)
        except Exception as e:
            LOG.error("boot: start_ap failed: %s", e)
    else:
        try:
            asyncio.run(wifi.ensure(ssid, pwd))
        except Exception as e:
            LOG.error("boot: wifi ensure failed: %s", e)

    return {
        "cfg_mgr": cfg_mgr,
        "wifi": wifi,
        "is_provisioning": is_provisioning,
    }

if __name__ == "__main__":
    _init_boot()
