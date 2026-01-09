# Lightweight Logging Shim for Memory Optimization
import sys

DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40
CRITICAL = 50

def basicConfig(**kwargs):
    pass

def getLogger(name="root"):
    return Logger(name)

class Logger:
    def __init__(self, name):
        self.name = name
        self.level = INFO

    def setLevel(self, level):
        self.level = level

    def debug(self, msg, *args):
        if self.level <= DEBUG:
            print("D:%s:" % self.name, msg % args if args else msg)

    def info(self, msg, *args):
        if self.level <= INFO:
            print("I:%s:" % self.name, msg % args if args else msg)

    def warning(self, msg, *args):
        if self.level <= WARNING:
            print("W:%s:" % self.name, msg % args if args else msg)

    def error(self, msg, *args):
        if self.level <= ERROR:
            print("E:%s:" % self.name, msg % args if args else msg)

    def critical(self, msg, *args):
        if self.level <= CRITICAL:
            print("C:%s:" % self.name, msg % args if args else msg)

    def exception(self, msg, *args, **kwargs):
        print("X:%s:" % self.name, msg % args if args else msg)
        exc = kwargs.get("exc_info")
        if exc:
            if isinstance(exc, Exception):
                sys.print_exception(exc)
            else:
                print(exc)
