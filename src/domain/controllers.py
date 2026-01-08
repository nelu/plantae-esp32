class SwitchBank:
    def __init__(self, driver, channels=16):
        self.driver = driver
        self.channels = int(channels)
        self.values = [0]*self.channels

    def set(self, idx, on):
        idx=int(idx)
        on=1 if on else 0
        if idx < 0 or idx >= self.channels:
            return False
        if on:
            self.driver.set_pwm(idx, 4096, 0)
        else:
            self.driver.set_pwm(idx, 0, 4096)
        self.values[idx]=on
        return True

    def set_all(self, on):
        ok=True
        for i in range(self.channels):
            ok = self.set(i, on) and ok
        return ok
