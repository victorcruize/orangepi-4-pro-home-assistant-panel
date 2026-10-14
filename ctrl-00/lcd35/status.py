"""Status screen for the 3.5in SPI TFT: system info plus raw touch read-out (XPT2046 on SPI3 CS1)."""
import os, signal, socket, subprocess, sys, time, json
import spidev
from PIL import Image, ImageDraw, ImageFont
from lcd import LCD, W, H

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf"
f_big, f_med, f_small = (ImageFont.truetype(FONT % "-Bold", 30), ImageFont.truetype(FONT % "", 22),
                         ImageFont.truetype(FONT % "", 16))
TOUCH_LOG = "/run/lcd35-touch.log"
LOGO_SRC = "/usr/share/pixmaps/orangepi/orangepi.png"

def load_logo(size=40):
    """Orange Pi logo with its white background made transparent."""
    try:
        im = Image.open(LOGO_SRC).convert("RGBA").resize((size, size), Image.LANCZOS)
        px = [(r, g, b, max(0, min(255, (255 - min(r, g, b)) * 4))) for r, g, b, _ in im.getdata()]
        im.putdata(px)
        return im
    except Exception:
        return None

LOGO = load_logo()

def splash():
    """Full-screen boot splash: big logo on a white card."""
    img = Image.new("RGB", (W, H), (10, 12, 18)); d = ImageDraw.Draw(img)
    size, pad = 176, 14
    x, y = (W - size - 2 * pad) // 2, 14
    d.rounded_rectangle([x, y, x + size + 2 * pad, y + size + 2 * pad], radius=28, fill="white")
    try:
        big = Image.open(LOGO_SRC).convert("RGB").resize((size, size), Image.LANCZOS)
        img.paste(big, (x + pad, y + pad))
    except Exception:
        pass
    t = "HUB"; w = d.textlength(t, font=f_big)
    d.text(((W - w) / 2, H - 62), t, fill=(255, 106, 0), font=f_big)
    t = "Orange Pi"; w = d.textlength(t, font=f_small)
    d.text(((W - w) / 2, H - 26), t, fill=(150, 160, 175), font=f_small)
    return img

def sh(cmd):
    try: return subprocess.check_output(cmd, shell=True, text=True, timeout=3).strip()
    except Exception: return "?"

class Touch:
    def __init__(self):
        self.spi = spidev.SpiDev(); self.spi.open(3, 1)
        self.spi.mode = 0; self.spi.max_speed_hz = 1_000_000
    def _rd(self, c):
        r = self.spi.xfer2([c, 0, 0]); return ((r[1] << 8) | r[2]) >> 3
    def read(self):
        """Returns (raw_x, raw_y, z) or None when not pressed."""
        z = self._rd(0xB0)
        if z < 80: return None
        xs, ys = [], []
        for _ in range(5):
            xs.append(self._rd(0xD0)); ys.append(self._rd(0x90))
        self._rd(0x80)
        xs.sort(); ys.sort()
        return xs[2], ys[2], z

# Calibration measured on 2026-10-12 from corner presses: raw Y runs along screen X (inverted), raw X along screen Y.
CAL = dict(x0=3725, x1=333, y0=476, y1=3604)

ROTATED = False      # True when the picture is turned 180 degrees: touch coordinates turn with it

def to_screen(t):
    sx = (t[1] - CAL["x0"]) / (CAL["x1"] - CAL["x0"]) * (W - 1)
    sy = (t[0] - CAL["y0"]) / (CAL["y1"] - CAL["y0"]) * (H - 1)
    sx, sy = int(min(max(sx, 0), W - 1)), int(min(max(sy, 0), H - 1))
    return (W - 1 - sx, H - 1 - sy) if ROTATED else (sx, sy)

def info():
    ips = sh("ip -4 -br a | awk '$1!=\"lo\" && $3!=\"\" {print $1\" \"$3}'").splitlines()
    temp = sh("cat /sys/class/thermal/thermal_zone0/temp")
    mem = sh("free -m | awk '/Mem:/ {printf \"%d/%d MB\", $3, $2}'")
    disk = sh("df -h / | awk 'NR==2 {print $3\"/\"$2\" (\"$5\")\"}'")
    root = sh("findmnt -no SOURCE /")
    return dict(ips=ips, temp=(f"{int(temp)/1000:.0f} C" if temp.isdigit() else "?"), mem=mem, disk=disk,
                load=open("/proc/loadavg").read().split()[0], root=root)

def render(i, touch):
    img = Image.new("RGB", (W, H), (10, 12, 18)); d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 46], fill=(255, 106, 0))
    tx = 12
    if LOGO:
        img.paste(LOGO, (8, 3), LOGO); tx = 56
    d.text((tx, 6), "HUB", fill="black", font=f_big)
    d.text((W - 150, 12), time.strftime("%H:%M:%S"), fill="black", font=f_med)
    y = 58
    for line in i["ips"][:3]:
        d.text((12, y), line, fill="white", font=f_med); y += 30
    y += 6
    for k, v in (("CPU", f"{i['temp']}   carga {i['load']}"), ("RAM", i["mem"]), ("Disco", f"{i['disk']}  {i['root']}")):
        d.text((12, y), k, fill=(255, 160, 60), font=f_med); d.text((95, y), v, fill="white", font=f_med); y += 30
    if touch:
        sx, sy = to_screen(touch)
        d.line([sx - 14, sy, sx + 14, sy], fill=(0, 255, 120), width=3)
        d.line([sx, sy - 14, sx, sy + 14], fill=(0, 255, 120), width=3)
        msg = f"toque: tela=({sx},{sy})  bruto=({touch[0]},{touch[1]})"
    else:
        msg = "toque: -"
    d.text((12, H - 26), msg, fill=(120, 200, 255), font=f_small)
    return img

def shutdown(lcd):
    """Blank the panel and put the controller to sleep (SIGTERM = service stop / system shutdown)."""
    try:
        lcd.show(Image.new("RGB", (W, H), "black"))
        lcd.cmd(0x28); lcd.cmd(0x10)   # display off, sleep in
    except Exception:
        pass
    sys.exit(0)

def main():
    lcd = LCD(hz=32_000_000); tp = Touch()
    signal.signal(signal.SIGTERM, lambda *_: shutdown(lcd))
    signal.signal(signal.SIGINT, lambda *_: shutdown(lcd))
    lcd.show(splash()); time.sleep(2.5)
    last_info, i, last_touch, last_draw = 0, None, None, 0
    while True:
        now = time.time()
        t = tp.read()
        if t:
            last_touch = t
            with open(TOUCH_LOG, "a") as f: f.write(json.dumps(dict(t=round(now, 2), x=t[0], y=t[1], z=t[2])) + "\n")
        if now - last_info > 5 or i is None: i, last_info = info(), now
        if t or now - last_draw >= 1:
            lcd.show(render(i, last_touch)); last_draw = now
        time.sleep(0.05)

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__))); main()
