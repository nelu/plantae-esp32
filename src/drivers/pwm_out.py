from machine import PWM, Pin

class PwmOut:
    def __init__(self, pin, freq=20000, active_low=False):
        self.active_low=bool(active_low)
        self._pwm=PWM(Pin(int(pin), Pin.OUT), freq=int(freq))
        self.set(0.0)

    def set(self, duty01):
        if duty01 < 0: duty01 = 0
        if duty01 > 1: duty01 = 1
        v = int(duty01 * 65535)
        if self.active_low:
            v = 65535 - v
        self._pwm.duty_u16(v)
