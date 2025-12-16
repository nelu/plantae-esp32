from micropython import const
import io
import sys
import time

CRITICAL = const(50)
ERROR = const(40)
WARNING = const(30)
INFO = const(20)
DEBUG = const(10)
NOTSET = const(0)

_DEFAULT_LEVEL = const(WARNING)

_level_dict = {
    CRITICAL: "CRITICAL",
    ERROR: "ERROR",
    WARNING: "WARNING",
    INFO: "INFO",
    DEBUG: "DEBUG",
    NOTSET: "NOTSET",
}

_loggers = {}
_stream = sys.stderr
_default_fmt = "%(asctime)s %(levelname)s:%(name)s:%(message)s"
_default_datefmt = "%Y-%m-%d %H:%M:%S"
_tz_offset_s = 0  # Timezone offset in seconds, set by configure_logging


class LogRecord:
    def set(self, name, level, message):
        self.name = name
        self.levelno = level
        self.levelname = _level_dict[level]
        self.message = message
        self.ct = time.time()
        self.msecs = int((self.ct - int(self.ct)) * 1000)
        self.asctime = None


class Handler:
    def __init__(self, level=NOTSET):
        self.level = level
        self.formatter = None

    def close(self):
        pass

    def setLevel(self, level):
        self.level = level

    def setFormatter(self, formatter):
        self.formatter = formatter

    def format(self, record):
        return self.formatter.format(record)


class StreamHandler(Handler):
    def __init__(self, stream=None):
        super().__init__()
        self.stream = _stream if stream is None else stream
        self.terminator = "\n"

    def close(self):
        if hasattr(self.stream, "flush"):
            self.stream.flush()

    def emit(self, record):
        if record.levelno >= self.level:
            # Use print() for MicroPython compatibility instead of stream.write()
            print(self.format(record))


class FileHandler(StreamHandler):
    def __init__(self, filename, mode="a", encoding="UTF-8"):
        super().__init__(stream=open(filename, mode=mode, encoding=encoding))

    def close(self):
        super().close()
        self.stream.close()


class Formatter:
    def __init__(self, fmt=None, datefmt=None):
        self.fmt = _default_fmt if fmt is None else fmt
        self.datefmt = _default_datefmt if datefmt is None else datefmt

    def usesTime(self):
        return "asctime" in self.fmt

    def formatTime(self, datefmt, record):
        try:
            # In MicroPython, time.time() returns seconds since 2000-01-01
            # Apply timezone offset for proper local time display
            adjusted_time = record.ct + _tz_offset_s
            
            if hasattr(time, "strftime") and hasattr(time, "localtime"):
                lt = time.localtime(adjusted_time)
                return time.strftime(datefmt, lt)
        except Exception as e:
            pass
        
        # Fallback for MicroPython - simple time formatting with timezone
        try:
            adjusted_time = record.ct + _tz_offset_s
            lt = time.localtime(adjusted_time)
            # Format as HH:MM:SS
            return "%02d:%02d:%02d" % (lt[3], lt[4], lt[5])
        except Exception as e:
            pass
            
        # If localtime fails, try to use current time directly
        try:
            # Get fresh time and format it with timezone
            current_time = time.time() + _tz_offset_s
            lt = time.localtime(current_time)
            return "%02d:%02d:%02d" % (lt[3], lt[4], lt[5])
        except:
            pass
            
        # Ultimate fallback - use ticks for relative timing
        try:
            if hasattr(time, 'ticks_ms'):
                ms = time.ticks_ms()
                seconds = ms // 1000
                mins = seconds // 60
                hours = mins // 60
                return "%02d:%02d:%02d" % (hours % 24, mins % 60, seconds % 60)
        except:
            pass
            
        # Last resort - just show the raw timestamp
        return "%.1f" % (record.ct or 0)

    def format(self, record):
        if self.usesTime():
            record.asctime = self.formatTime(self.datefmt, record)
            # Ensure asctime is never None
            if record.asctime is None:
                record.asctime = "??:??:??"
        
        return self.fmt % {
            "name": record.name,
            "message": record.message,
            "msecs": record.msecs,
            "asctime": record.asctime or "",
            "levelname": record.levelname,
        }


class Logger:
    def __init__(self, name, level=NOTSET):
        self.name = name
        self.level = level
        self.handlers = []
        self.record = LogRecord()

    def setLevel(self, level):
        self.level = level

    def isEnabledFor(self, level):
        return level >= self.getEffectiveLevel()

    def getEffectiveLevel(self):
        return self.level or getLogger().level or _DEFAULT_LEVEL

    def log(self, level, msg, *args):
        if self.isEnabledFor(level):
            if args:
                if isinstance(args[0], dict):
                    args = args[0]
                msg = msg % args
            self.record.set(self.name, level, msg)
            handlers = self.handlers
            if not handlers:
                handlers = getLogger().handlers
            for h in handlers:
                h.emit(self.record)

    def debug(self, msg, *args):
        self.log(DEBUG, msg, *args)

    def info(self, msg, *args):
        self.log(INFO, msg, *args)

    def warning(self, msg, *args):
        self.log(WARNING, msg, *args)

    def error(self, msg, *args):
        self.log(ERROR, msg, *args)

    def critical(self, msg, *args):
        self.log(CRITICAL, msg, *args)

    def exception(self, msg, *args, exc_info=True):
        self.log(ERROR, msg, *args)
        tb = None
        if isinstance(exc_info, BaseException):
            tb = exc_info
        elif hasattr(sys, "exc_info"):
            tb = sys.exc_info()[1]
        if tb:
            buf = io.StringIO()
            sys.print_exception(tb, buf)
            self.log(ERROR, buf.getvalue())

    def addHandler(self, handler):
        self.handlers.append(handler)

    def hasHandlers(self):
        return len(self.handlers) > 0


def getLogger(name=None):
    if name is None:
        name = "root"
    if name not in _loggers:
        _loggers[name] = Logger(name)
        if name == "root":
            basicConfig()
    return _loggers[name]


def log(level, msg, *args):
    getLogger().log(level, msg, *args)


def debug(msg, *args):
    getLogger().debug(msg, *args)


def info(msg, *args):
    getLogger().info(msg, *args)


def warning(msg, *args):
    getLogger().warning(msg, *args)


def error(msg, *args):
    getLogger().error(msg, *args)


def critical(msg, *args):
    getLogger().critical(msg, *args)


def exception(msg, *args, exc_info=True):
    getLogger().exception(msg, *args, exc_info=exc_info)


def shutdown():
    for k, logger in _loggers.items():
        for h in logger.handlers:
            h.close()
        _loggers.pop(logger, None)


def addLevelName(level, name):
    _level_dict[level] = name


def basicConfig(
    filename=None,
    filemode="a",
    format=None,
    datefmt=None,
    level=WARNING,
    stream=None,
    encoding="UTF-8",
    force=False,
):
    if "root" not in _loggers:
        _loggers["root"] = Logger("root")

    logger = _loggers["root"]

    if force or not logger.handlers:
        for h in logger.handlers:
            h.close()
        logger.handlers = []

        if filename is None:
            handler = StreamHandler(stream)
        else:
            handler = FileHandler(filename, filemode, encoding)

        handler.setLevel(level)
        handler.setFormatter(Formatter(format, datefmt))

        logger.setLevel(level)
        logger.addHandler(handler)


if hasattr(sys, "atexit"):
    sys.atexit(shutdown)
