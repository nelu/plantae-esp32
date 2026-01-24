from machine import PWM, Pin

class PwmOut:
    def __init__(self, pin, freq=20000, active_low=False):
        self.active_low=bool(active_low)
        self._pwm=PWM(Pin(int(pin), Pin.OUT), freq=int(freq))
        self.set(0.0)

    def set(self, duty01):
        pwm = self._pwm
        if duty01 < 0: duty01 = 0
        if duty01 > 1: duty01 = 1
        v = int(duty01 * 65535)
        if self.active_low:
            v = 65535 - v
        pwm.duty_u16(v)

    def release(self):
        pwm = self._pwm
        if not pwm:
            return
        try:
            pwm.duty_u16(0)
        except Exception:
            pass
        try:
            pwm.deinit()
        except Exception:
            pass
        self._pwm = None
