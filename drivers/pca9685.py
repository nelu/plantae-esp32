MODE1=0x00
PRESCALE=0xFE
LED0_ON_L=0x06

class PCA9685:
    def __init__(self, i2c, address=0x40):
        self.i2c=i2c
        self.addr=address
        self.reset()

    def reset(self):
        self.i2c.writeto_mem(self.addr, MODE1, b"\x00")

    def set_pwm_freq(self, freq_hz):
        prescale = int(round(25000000.0/(4096.0*freq_hz) - 1))
        if prescale < 3: prescale = 3
        old = self.i2c.readfrom_mem(self.addr, MODE1, 1)[0]
        sleep = (old & 0x7F) | 0x10
        self.i2c.writeto_mem(self.addr, MODE1, bytes([sleep]))
        self.i2c.writeto_mem(self.addr, PRESCALE, bytes([prescale]))
        self.i2c.writeto_mem(self.addr, MODE1, bytes([old]))
        self.i2c.writeto_mem(self.addr, MODE1, bytes([old | 0x80]))

    def set_pwm(self, channel, on, off):
        reg = LED0_ON_L + 4*int(channel)
        data = bytes([on & 0xFF, (on >> 8) & 0x0F, off & 0xFF, (off >> 8) & 0x0F])
        self.i2c.writeto_mem(self.addr, reg, data)
