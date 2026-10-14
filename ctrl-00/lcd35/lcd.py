"""Userspace driver for the 3.5in 480x320 SPI TFT (ILI9486, 16-bit register width) on SPI3."""
import os, sys, time
import spidev
import numpy as np

W, H = 480, 320
GPIO_DC, GPIO_RST = 354, 119          # header pins 18 (PL2) and 22 (PD23)

def _gpio(n, val=None):
    base = f"/sys/class/gpio/gpio{n}"
    if not os.path.isdir(base):
        with open("/sys/class/gpio/export", "w") as f: f.write(str(n))
        time.sleep(0.05)
        with open(base + "/direction", "w") as f: f.write("out")
    if val is not None:
        with open(base + "/value", "w") as f: f.write("1" if val else "0")

class LCD:
    def __init__(self, hz=16_000_000, init="mhs"):
        self.spi = spidev.SpiDev(); self.spi.open(3, 0)
        self.spi.mode = 0; self.spi.max_speed_hz = hz
        _gpio(GPIO_DC, 1); _gpio(GPIO_RST, 1)
        self.reset(); self.init(init)

    def reset(self):
        _gpio(GPIO_RST, 1); time.sleep(0.05)
        _gpio(GPIO_RST, 0); time.sleep(0.1)
        _gpio(GPIO_RST, 1); time.sleep(0.15)

    def cmd(self, c, *data):
        _gpio(GPIO_DC, 0); self.spi.writebytes2(bytes([0, c]))
        if data:
            _gpio(GPIO_DC, 1)
            self.spi.writebytes2(bytes(b for d in data for b in (0, d)))

    def init(self, kind):
        c = self.cmd
        if kind == "mhs":
            c(0xF1, 0x36, 0x04, 0x00, 0x3C, 0x0F, 0x8F)
            c(0xF2, 0x18, 0xA3, 0x12, 0x02, 0xB2, 0x12, 0xFF, 0x10, 0x00)
            c(0xF8, 0x21, 0x04); c(0xF9, 0x00, 0x08)
            c(0x36, 0x08); c(0xB4, 0x00); c(0xC1, 0x41)
            c(0xC5, 0x00, 0x91, 0x80, 0x00)
        else:
            c(0xB0, 0x00); c(0x11); time.sleep(0.25)
            c(0xC2, 0x44); c(0xC5, 0x00, 0x00, 0x00, 0x00)
        c(0xE0, 0x0F, 0x1F, 0x1C, 0x0C, 0x0F, 0x08, 0x48, 0x98, 0x37, 0x0A, 0x13, 0x04, 0x11, 0x0D, 0x00)
        c(0xE1, 0x0F, 0x32, 0x2E, 0x0B, 0x0D, 0x05, 0x47, 0x75, 0x37, 0x06, 0x10, 0x03, 0x24, 0x20, 0x00)
        c(0x3A, 0x55); c(0x11); time.sleep(0.15)
        c(0x36, 0x28); time.sleep(0.1); c(0x29)

    def show(self, img):
        """img: PIL RGB image, 480x320."""
        a = np.asarray(img.convert("RGB"), dtype=np.uint16)
        rgb565 = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
        self.show_raw(rgb565.astype(">u2").tobytes())

    def rotate(self, flipped):
        """Landscape orientation: normal, or turned 180 degrees (MADCTL with both mirror bits set)."""
        self.cmd(0x36, 0xE8 if flipped else 0x28)

    brightness = 1.0     # software dimming: the backlight is not switchable, so the picture itself is darkened

    def show_raw(self, buf):
        """buf: one full frame as big-endian RGB565 bytes (W*H*2)."""
        if self.brightness < 0.995:
            k = int(max(0.05, self.brightness) * 256)
            a = np.frombuffer(buf, dtype=">u2").astype(np.uint32)
            a = ((((a >> 11) * k) >> 8) << 11) | (((((a >> 5) & 63) * k) >> 8) << 5) | (((a & 31) * k) >> 8)
            buf = a.astype(">u2").tobytes()
        self.cmd(0x2A, 0, 0, (W - 1) >> 8, (W - 1) & 0xFF)
        self.cmd(0x2B, 0, 0, (H - 1) >> 8, (H - 1) & 0xFF)
        self.cmd(0x2C)
        _gpio(GPIO_DC, 1)
        self.spi.writebytes2(buf)

if __name__ == "__main__":
    from PIL import Image, ImageDraw, ImageFont
    kind = sys.argv[1] if len(sys.argv) > 1 else "mhs"
    lcd = LCD(init=kind)
    img = Image.new("RGB", (W, H), "black"); d = ImageDraw.Draw(img)
    for i, col in enumerate(("red", "green", "blue", "white")):
        d.rectangle([i * 120, 0, i * 120 + 119, 159], fill=col)
    try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
    except OSError: font = ImageFont.load_default()
    d.text((20, 190), "CTRL-00 Orange Pi", fill="white", font=font)
    d.text((20, 240), f"teste LCD ({kind})", fill="yellow", font=font)
    t = time.time(); lcd.show(img); print(f"frame enviado em {time.time()-t:.2f}s, init={kind}")
