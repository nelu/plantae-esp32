import ntptime
import uasyncio as asyncio
import time
from domain.state import DeviceState

async def sync(host="pool.ntp.org", retries=3):
    ntptime.host = host
    for attempt in range(retries):
        try:
            ntptime.settime()
            # Verify the time was actually set (should be after 2020)
            # Unix timestamp for Jan 1, 2020 is 1577836800
            # Convert to MicroPython time: 1577836800 - 946684800 = 631152000
            unix_2020 = 1577836800
            micropython_2020 = unix_2020 - DeviceState.UNIX_EPOCH_OFFSET
            if time.time() > micropython_2020:
                return True
        except Exception as e:
            if attempt < retries - 1:  # Don't sleep on last attempt
                await asyncio.sleep(2)
    return False
