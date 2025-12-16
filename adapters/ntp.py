import ntptime
import uasyncio as asyncio
import time

async def sync(host="pool.ntp.org", retries=3):
    ntptime.host = host
    for attempt in range(retries):
        try:
            ntptime.settime()
            # Verify the time was actually set (should be after 2020)
            if time.time() > 1577836800:  # Jan 1, 2020 timestamp
                return True
        except Exception as e:
            if attempt < retries - 1:  # Don't sleep on last attempt
                await asyncio.sleep(2)
    return False
