from micropython import const
import time

# Constants save RAM by not creating actual integer objects in some contexts
DEBUG = const(10)
INFO = const(20)
WARNING = const(30)
ERROR = const(40)

_level_dict = {10: "DBG", 20: "INF", 30: "WRN", 40: "ERR"}

class Logger:
    def __init__(self, name, level=WARNING):
        self.name = name
        self.level = level

    def _log(self, level, msg, *args):
        if level >= self.level:
            # Format directly to save on object creation
            t = time.localtime()
            # Efficient timestamp formatting without strftime (which is often missing)
            ts = "%02d:%02d:%02d" % (t[3], t[4], t[5])
            if args:
                msg = msg % args
            print(f"{ts} [{_level_dict.get(level, '???')}][{self.name}] {msg}")

    def debug(self, m, *a): self._log(DEBUG, m, *a)
    def info(self, m, *a): self._log(INFO, m, *a)
    def warning(self, m, *a): self._log(WARNING, m, *a)
    def error(self, m, *a): self._log(ERROR, m, *a)


LOG = Logger("root", DEBUG)