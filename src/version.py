# Build version - update before each release
VERSION = "0.0.0"
BUILD_DATE = "2026-03-10"
INDICATOR_LED = 5
INDICATOR_LED_RGB = False

try:
    import os

    uname = getattr(os, "uname", None)
    if uname and "ESP32S3" in getattr(uname(), "machine", ""):
        INDICATOR_LED = 48
        INDICATOR_LED_RGB = True
except Exception:
    pass