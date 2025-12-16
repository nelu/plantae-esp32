from machine import Pin, disable_irq, enable_irq
import time

class FlowSensor:
    def __init__(self, pulses_per_liter, pin):
        self._pin_num=int(pin)
        self._ppl=float(pulses_per_liter)
        self._pulse=0
        self._total=0
        self._lps=0.0
        self._vol=0.0
        self._t0=time.ticks_ms()
        self._pin=None

    def begin(self, pullup=True, trigger=Pin.IRQ_RISING):
        if pullup:
            self._pin=Pin(self._pin_num, Pin.IN)
        else:
            self._pin=Pin(self._pin_num, Pin.IN, Pin.PULL_UP)
        self._pin.irq(trigger=trigger, handler=self._isr)
        self._t0=time.ticks_ms()

    def _isr(self, _):
        self._pulse += 1

    def read(self, calibration=0):
        st=disable_irq()
        p=self._pulse
        self._pulse=0
        self._total += p
        enable_irq(st)

        denom=self._ppl + float(calibration)
        if denom <= 0:
            denom = 1.0
        now=time.ticks_ms()
        dt=time.ticks_diff(now, self._t0)
        if dt <= 0: dt = 1
        liters = p/denom
        self._vol += liters
        self._lps = liters/(dt/1000.0)
        self._t0 = now

    @property
    def pulses_total(self): return int(self._total)
    @property
    def flow_lps(self): return float(self._lps)
    @property
    def flow_lpm(self): return float(self._lps*60.0)
    @property
    def volume_l(self): return float(self._vol)
