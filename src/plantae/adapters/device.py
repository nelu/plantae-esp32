import binascii
import struct
import time
import ntptime

from machine import RTC
from datetime import unix_now
from logging import LOG


def pending_rollback() -> bool:
    from ota.status import otadata_part, OTA_BLOCKS, OTA_CRC_INIT, OTA_SIZE, OTA_FMT

    if not otadata_part:
        return False
    try:
        for i in OTA_BLOCKS:
            otadata_part.readblocks(i, (b := bytearray(OTA_SIZE)))
            seq, _, state_num, crc = struct.unpack(OTA_FMT, b)
            if seq == 0xFFFFFFFF or state_num != 1:
                continue
            if binascii.crc32(struct.pack(b"<L", seq), OTA_CRC_INIT) == crc:
                return True
    except Exception:
        return False
    return False

def set_rtc_local_from_utc(ts_utc, tz_offset_min=0):
    """Set RTC to local time derived from UTC timestamp and tz offset."""
    try:
        local_ts = int(float(ts_utc) + int(tz_offset_min) * 60)
        dt = time.localtime(local_ts)
        # RTC expects (year, month, day, weekday, hours, minutes, seconds, subseconds)
        rtc_tuple = (dt[0], dt[1], dt[2], dt[6], dt[3], dt[4], dt[5], 0)
        RTC().datetime(rtc_tuple)
        return True
    except Exception as e:
        return False


def sync_rtc_via_ntp(host="pool.ntp.org", retries=3, tz_offset_min=0):
    ntptime.host = host
    for attempt in range(int(retries)):
        try:
            ntptime.settime()
            unix_2020 = 1577836800
            now_utc = unix_now()
            if now_utc > unix_2020:
                if set_rtc_local_from_utc(now_utc, tz_offset_min):
                    return True
        except Exception as e:
            LOG.error("NTP sync: %s",e)
            if attempt < int(retries) - 1:
                time.sleep(2)

    return False


