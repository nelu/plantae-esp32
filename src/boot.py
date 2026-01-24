import time

import uasyncio as asyncio

from lib.logging import LOG
from adapters.config_manager import ConfigManager, DEFAULT
from adapters.wifi import Wifi
from app.device_id import get_device_id
from app.provision import ProvisionWifi


_BOOT_CTX = None


def _maybe_factory_reset_button(config_path="config.json", hold_time_s=5, wait_window_s=5):
    hold_ms = int(hold_time_s * 1000)
    window_ms = int(max(hold_time_s, wait_window_s or 0) * 1000)

    try:
        from machine import Pin
    except Exception as e:
        if LOG: LOG.error("factory_reset: init failed: %s", e)
        time.sleep_ms(window_ms)
        return False

    btn_cfg = (DEFAULT.get("inputs") or {}).get("pwm_test_btn", {})
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

                    os.remove(config_path)
                    os.remove("stats.json")

                    LOG.warning("factory_reset: %s removed; provisioning", config_path)
                    return True
                except Exception as e:
                    LOG.error("factory_reset: failed to remove %s: %s", config_path, e)
                    return False
        else:
            pressed_start = None
        time.sleep_ms(50)

    return False


def _init_boot():
    cfg_mgr = ConfigManager("config.json")

    _maybe_factory_reset_button("config.json", hold_time_s=4, wait_window_s=5)

    cfg = cfg_mgr.load()

    device_id = get_device_id(cfg)

    wifi_cfg = cfg.get("wifi") or {}
    ssid = (wifi_cfg.get("ssid") or "").strip()
    pwd = wifi_cfg.get("password")
    is_provisioning = not ssid

    if LOG: LOG.info("boot: starting network, provisioning=%s", is_provisioning)

    wifi = ProvisionWifi() if is_provisioning else Wifi()

    if is_provisioning:
        ap_name = device_id
        try:
            wifi.start_ap(ap_name)
            try:
                wifi.sta.active(False)
            except Exception:
                pass
        except Exception as e:
            if LOG: LOG.error("boot: start_ap failed: %s", e)
    else:
        try:
            asyncio.run(wifi.ensure(ssid, pwd))
        except Exception as e:
            if LOG: LOG.error("boot: wifi ensure failed: %s", e)

    return {
        "cfg_mgr": cfg_mgr,
        "cfg": cfg,
        "wifi": wifi,
        "device_id": device_id,
        "is_provisioning": is_provisioning,
    }


def get_boot_context():
    global _BOOT_CTX
    if _BOOT_CTX is None:
        _BOOT_CTX = _init_boot()
    return _BOOT_CTX

if __name__ == "__main__":
    _BOOT_CTX = _init_boot()
