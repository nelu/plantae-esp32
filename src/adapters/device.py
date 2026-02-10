import time
import ntptime

from machine import RTC
from lib.datetime import DEFAULT_UNIX_EPOCH_OFFSET

# NOTE: Tested with docker image micropython/unix:v1.27.0


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


async def sync_rtc_via_ntp(host="pool.ntp.org", retries=3, tz_offset_min=0):
    ntptime.host = host
    for attempt in range(int(retries)):
        try:
            ntptime.settime()
            unix_2020 = 1577836800
            micropython_2020 = unix_2020 - DEFAULT_UNIX_EPOCH_OFFSET
            now_utc = time.time()
            if now_utc > micropython_2020:
                ts_utc = now_utc
                if set_rtc_local_from_utc(ts_utc, tz_offset_min):
                    return True
        except Exception:
            if attempt < int(retries) - 1:
                import uasyncio as asyncio
                await asyncio.sleep(2)
    return False
