def parse_hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)



def duty_from_schedule(schedule, local_minutes, local_seconds=None):
    """
    Determine PWM duty from a schedule list.

    Base behavior (no 'interval' in item):
      - If current time is within [start, end) (minute resolution), duty=duty.

    Interval behavior:
      - If item has 'interval' (seconds) and NO 'time_on':
          ON  for 'interval' seconds at duty
          OFF for 'interval' seconds at 0.0
        repeating (period = 2*interval).

      - If item has 'interval' (seconds) AND 'time_on' (seconds):
          period = interval
          ON for time_on seconds at duty, then OFF for the rest of the interval
        repeating.
        Example: interval=800, time_on=60 => ON 60s, OFF 740s, repeat.
    """
    duty = 0.0

    # local_seconds is optional for backward compatibility
    try:
        mins = int(local_minutes)
    except Exception:
        mins = 0

    try:
        secs = 0 if local_seconds is None else int(local_seconds)
    except Exception:
        secs = 0

    # normalize secs into 0..59 (best-effort)
    if secs < 0:
        secs = 0
    elif secs > 59:
        secs = secs % 60

    now_s = mins * 60 + secs

    for item in schedule or []:
        try:
            a_m = parse_hhmm(item["start"])
            b_m = parse_hhmm(item["end"])
            d = float(item.get("duty", 0.0))
        except Exception:
            continue

        # Minute-based window expressed in seconds
        start_s = a_m * 60
        end_s = b_m * 60

        if not (start_s <= now_s < end_s):
            continue

        interval = item.get("interval", None)

        # No interval => original behavior
        if interval is None:
            duty = d
            break

        # Interval present => pulsing behavior
        try:
            interval_s = int(interval)
        except Exception:
            interval_s = 0

        if interval_s <= 0:
            duty = d
            break

        time_on = item.get("time_on", None)

        # If time_on is provided, use interval as the full period
        if time_on is not None:
            try:
                on_s = int(time_on)
            except Exception:
                on_s = 0

            # clamp to sane range
            if on_s <= 0:
                duty = 0.0
            else:
                if on_s > interval_s:
                    on_s = interval_s
                pos = (now_s - start_s) % interval_s
                duty = d if pos < on_s else 0.0

            break

        # Back-compat: no time_on => ON interval_s, OFF interval_s (period 2*interval_s)
        pos = now_s - start_s  # seconds since window start
        period = interval_s * 2
        duty = d if (pos % period) < interval_s else 0.0
        break

    # clamp
    if duty < 0.0:
        duty = 0.0
    if duty > 1.0:
        duty = 1.0
    return duty