import time


DEFAULT_UNIX_EPOCH_OFFSET = 946684800


def _localtime():
    return time.localtime(time.time())


def parse_hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def local_minutes():
    lt = _localtime()
    return lt[3] * 60 + lt[4]


def local_time_tuple():
    lt = _localtime()
    return (lt[3] * 60 + lt[4], lt[5])


def local_wday():
    lt = _localtime()
    return (int(lt[6]) - 1) % 7


def ts_to_local_day(ts):
    return int(int(ts) // 86400)


def current_local_day():
    return ts_to_local_day(time.time())


def unix_now():
    return int(time.time()) + DEFAULT_UNIX_EPOCH_OFFSET
