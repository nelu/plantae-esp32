def parse_hhmm(s):
    h, m = s.split(":")
    return int(h)*60 + int(m)

def duty_from_schedule(schedule, local_minutes):
    duty = 0.0
    for item in schedule or []:
        try:
            a = parse_hhmm(item["start"])
            b = parse_hhmm(item["end"])
            d = float(item.get("duty", 0.0))
        except Exception:
            continue
        if a <= local_minutes < b:
            duty = d
            break
    if duty < 0: duty = 0.0
    if duty > 1: duty = 1.0
    return duty
