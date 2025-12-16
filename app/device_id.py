import ubinascii
import network

def get_device_id(cfg=None):
    if cfg and cfg.get("device", {}).get("id"):
        return cfg["device"]["id"]
    wlan = network.WLAN(network.STA_IF)
    mac = wlan.config("mac")
    return "esp32-" + ubinascii.hexlify(mac).decode()
