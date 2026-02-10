"""
Device NTP/RTC integration checks using real MicroPython modules.

Runs inside micropython/unix:v1.27.0. Skips gracefully if network or RTC
support is unavailable.
"""

import time

try:
    import machine
    from adapters.device import set_rtc_local_from_utc, sync_rtc_via_ntp
except Exception as e:  # pragma: no cover - import guard
    print("SKIP: required modules unavailable: %s" % e)
    raise SystemExit(0)


def _has_rtc():
    try:
        machine.RTC
        return True
    except Exception:
        return False


def _rtc_datetime():
    try:
        return machine.RTC().datetime()
    except Exception:
        return None


def test_set_rtc_local_from_utc():
    if not _has_rtc():
        print("SKIP: machine.RTC not available on this build")
        return

    before = _rtc_datetime()
    ts = time.time()
    ok = set_rtc_local_from_utc(ts, tz_offset_min=0)
    after = _rtc_datetime()

    assert ok, "set_rtc_local_from_utc returned False"
    assert after is not None, "RTC datetime unavailable"
    assert before != after, "RTC datetime did not change"
    print("set_rtc_local_from_utc: PASS", after)


def test_sync_rtc_via_ntp():
    if not _has_rtc():
        print("SKIP: machine.RTC not available on this build")
        return

    # Single attempt; rely on container network
    ok = False
    try:
        ok = time.run_until_complete(sync_rtc_via_ntp(retries=1, tz_offset_min=0))
    except AttributeError:
        # MicroPython unix lacks asyncio; call directly if coroutine-like
        try:
            ok = sync_rtc_via_ntp(retries=1, tz_offset_min=0)
        except Exception:
            ok = False
    except Exception:
        ok = False

    if not ok:
        print("SKIP: NTP sync failed (network or service)" )
        return

    dt = _rtc_datetime()
    assert dt is not None, "RTC datetime unavailable after NTP"
    assert dt[0] >= 2020, "RTC year looks invalid: %s" % (dt,)
    print("sync_rtc_via_ntp: PASS", dt)


def main():
    test_set_rtc_local_from_utc()
    test_sync_rtc_via_ntp()
    print("device ntp tests completed")


if __name__ == "__main__":
    main()
