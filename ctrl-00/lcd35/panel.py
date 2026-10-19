"""Touch panel for CTRL-00: room tiles and per-room controls backed by Home Assistant."""
import colorsys, json, math, os, threading, time, urllib.error, urllib.request
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from lcd import LCD, W, H
from status import Touch, to_screen, info
from settings import SettingsMixin
from controllers import ControllersMixin
from theme import *
import glass

BASE = os.path.dirname(os.path.abspath(__file__))
HA_URL = "http://127.0.0.1:8123"
ENV_FILE = "/opt/automacao/.env"
MEDIA = os.path.join(BASE, "media")
FRAME_BYTES = W * H * 2
INTRO_FPS = 10                           # must match make_media.py; timings and names live in config.json

ON_STATES = {"on", "cool", "heat", "auto", "dry", "fan_only", "heat_cool"}
MEDIA_OFF = {"off", "standby", "unavailable", "unknown"}
PENDING_S = 25                           # how long a tapped value is held while the appliance has not confirmed it


FORECAST_EVERY_S = 900
CONDITIONS = {
    "clear-night": "Noite limpa", "cloudy": "Nublado", "exceptional": "Excepcional", "fog": "Neblina", "hail": "Granizo",
    "lightning": "Raios", "lightning-rainy": "Tempestade", "partlycloudy": "Parc. nublado", "pouring": "Chuva forte",
    "rainy": "Chuva", "snowy": "Neve", "snowy-rainy": "Neve e chuva", "sunny": "Ensolarado", "windy": "Ventoso",
    "windy-variant": "Ventoso"}
WEEKDAYS = ("SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM")
CLOUD_C, MOON_C, BOLT_C = (190, 198, 214), (226, 230, 240), (255, 214, 64)


def draw_weather(d, cx, cy, s, cond, bg):
    """Small vector weather icon centred on (cx, cy), about s px wide."""
    def sun(x, y, r):
        for k in range(8):
            a = k * 0.7854; ca, sa = math.cos(a), math.sin(a)
            d.line([x + ca * r * 1.45, y + sa * r * 1.45, x + ca * r * 1.9, y + sa * r * 1.9], fill=AMBER, width=max(2, s // 16))
        d.ellipse([x - r, y - r, x + r, y + r], fill=AMBER)
    def cloud(x, y, w, fill=CLOUD_C):
        h = w * 0.5
        d.ellipse([x - w * .5, y - h * .1, x - w * .1, y + h * .5], fill=fill)
        d.ellipse([x - w * .3, y - h * .55, x + w * .15, y + h * .45], fill=fill)
        d.ellipse([x, y - h * .3, x + w * .5, y + h * .5], fill=fill)
        d.rectangle([x - w * .32, y + h * .1, x + w * .3, y + h * .5], fill=fill)
    def drops(x, y, n, color, snow=False):
        for k in range(n):
            px = x + (k - (n - 1) / 2) * s * .2
            if snow: d.ellipse([px - 2, y - 2, px + 2, y + 2], fill=color)
            else: d.line([px + 3, y - s * .07, px - 3, y + s * .09], fill=color, width=max(2, s // 16))
    if cond == "sunny":
        sun(cx, cy, s * .2)
    elif cond == "clear-night":
        r = s * .3
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=MOON_C)
        d.ellipse([cx - r * .4, cy - r * 1.15, cx + r * 1.35, cy + r * .6], fill=bg)
    elif cond == "partlycloudy":
        sun(cx - s * .15, cy - s * .15, s * .15); cloud(cx + s * .05, cy + s * .05, s * .7)
    elif cond in ("fog",):
        for k in range(3): d.line([cx - s * .35, cy - s * .15 + k * s * .17, cx + s * .35, cy - s * .15 + k * s * .17], fill=CLOUD_C, width=max(2, s // 12))
    elif cond in ("windy", "windy-variant"):
        for k in range(3): d.line([cx - s * .35 + k * s * .06, cy - s * .15 + k * s * .17, cx + s * .3 - k * s * .1, cy - s * .15 + k * s * .17], fill=CLOUD_C, width=max(2, s // 12))
    else:
        cloud(cx, cy - s * .08, s * .75)
        if cond in ("rainy", "pouring", "lightning-rainy", "hail", "snowy-rainy"):
            drops(cx, cy + s * .32, 4 if cond == "pouring" else 3, CYAN)
        if cond in ("snowy",): drops(cx, cy + s * .32, 3, TEXT, snow=True)
        if cond in ("lightning", "lightning-rainy"):
            x, y = cx, cy + s * .02
            d.polygon([(x + s * .06, y), (x - s * .1, y + s * .22), (x, y + s * .22), (x - s * .06, y + s * .42), (x + s * .12, y + s * .16), (x + s * .02, y + s * .16)], fill=BOLT_C)


class HomeAssistant:
    def __init__(self):
        self.states, self.error, self.token, self.changed = {}, "sem token", None, threading.Event()
        self.pending = {}                # (entity, field) -> (value shown, deadline)
        self.forecast = []
        threading.Thread(target=self._poll, daemon=True).start()
        threading.Thread(target=self._poll_forecast, daemon=True).start()

    def weather(self):
        """State of the weather entity (prefers weather.forecast_home), or None."""
        s = self.states.get("weather.forecast_home")
        return s or next((v for k, v in self.states.items() if k.startswith("weather.")), None)

    def _poll_forecast(self):
        while True:
            w, wait = self.weather(), 15
            if w and self.token:
                try:
                    r = self._request("/api/services/weather/get_forecasts?return_response",
                                      {"entity_id": w["entity_id"], "type": "daily"})
                    fc = r["service_response"][w["entity_id"]]["forecast"]
                    if fc != self.forecast: self.forecast = fc; self.changed.set()
                    wait = FORECAST_EVERY_S
                except Exception:
                    pass
            time.sleep(wait)

    def _load_token(self):
        try:
            for line in open(ENV_FILE):
                if line.startswith("HA_TOKEN="):
                    return line.split("=", 1)[1].strip() or None
        except OSError:
            pass
        return None

    def _request(self, path, data=None):
        req = urllib.request.Request(HA_URL + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read() or b"null")

    def _poll(self):
        while True:
            error = None
            self.token = self._load_token()
            if not self.token:
                error = "sem token"
            else:
                try:
                    new = {s["entity_id"]: s for s in self._request("/api/states")}
                    self._apply_pending(new)
                    if new != self.states: self.states = new; self.changed.set()
                except urllib.error.HTTPError as e:
                    error = "token recusado" if e.code == 401 else f"HA erro {e.code}"
                except Exception:
                    error = "HA offline"
            if error != self.error: self.error = error; self.changed.set()
            time.sleep(2 if not error else 5)

    def call(self, domain, service, **data):
        def run():
            try: self._request(f"/api/services/{domain}/{service}", data)
            except Exception: pass
        threading.Thread(target=run, daemon=True).start()

    def is_on(self, eid):
        s = self.states.get(eid)
        if s and eid.startswith("media_player."): return s["state"] not in MEDIA_OFF
        return bool(s) and s["state"] in ON_STATES

    def number(self, eid):
        s = self.states.get(eid)
        if not s: return None
        raw = s["attributes"].get("temperature") if eid.startswith("climate.") else s["state"]
        try: return float(raw)
        except (TypeError, ValueError): return None

    # A tap is shown at once, but cloud appliances take seconds to report the change back. Until they
    # do, every poll would bring the old value and the screen would flick back and forth. So the tapped
    # value is held as "pending": polls keep showing it until the real state agrees, or until it expires
    # and the real state wins (the command did not get through).
    def _expect(self, eid, key, value):
        self.pending[(eid, key)] = (value, time.time() + PENDING_S)

    @staticmethod
    def _state_on(eid, state):
        return state not in MEDIA_OFF if eid.startswith("media_player.") else state in ON_STATES

    def _apply_pending(self, states):
        now = time.time()
        for (eid, key), (value, deadline) in list(self.pending.items()):
            s = states.get(eid)
            if s is None or now > deadline:
                self.pending.pop((eid, key), None); continue
            if key == "state":
                if self._state_on(eid, s["state"]) == value: self.pending.pop((eid, key), None)
                else: s["state"] = "on" if value else "off"
                continue
            if key == "mode":
                if s["state"] == value: self.pending.pop((eid, key), None)
                else: s["state"] = value
                continue
            real = s["state"] if key == "value" else s["attributes"].get(key)
            try: same = abs(float(real) - float(value)) < 0.005
            except (TypeError, ValueError): same = real == value
            if same: self.pending.pop((eid, key), None)
            elif key == "value": s["state"] = str(value)
            else: s["attributes"][key] = value

    def toggle(self, eid):
        s = self.states.get(eid)
        if s:
            target = not self.is_on(eid)
            s["state"] = "on" if target else "off"
            self._expect(eid, "state", target)
        self.call("homeassistant", "toggle", entity_id=eid)

    def volume(self, eid):
        """(level 0..1 or None, muted) of a media player."""
        a = (self.states.get(eid) or {}).get("attributes", {})
        v = a.get("volume_level")
        return (float(v) if isinstance(v, (int, float)) else None), bool(a.get("is_volume_muted"))

    def set_volume(self, eid, level):
        level = round(min(1.0, max(0.0, level)), 2)
        s = self.states.get(eid)
        if s: s["attributes"]["volume_level"] = level; self._expect(eid, "volume_level", level)
        self.call("media_player", "volume_set", entity_id=eid, volume_level=level)

    def mute(self, eid, muted):
        s = self.states.get(eid)
        if s: s["attributes"]["is_volume_muted"] = muted; self._expect(eid, "is_volume_muted", muted)
        self.call("media_player", "volume_mute", entity_id=eid, is_volume_muted=muted)

    def light_caps(self, eid):
        """(dimmable, has colour, has white temperature) of a light entity."""
        modes = set((self.states.get(eid) or {}).get("attributes", {}).get("supported_color_modes") or ())
        color = bool(modes & {"hs", "rgb", "rgbw", "rgbww", "xy"})
        return bool(modes - {"onoff"}), color, "color_temp" in modes

    def brightness(self, eid):
        """Brightness in percent, or None while off or unknown."""
        b = (self.states.get(eid) or {}).get("attributes", {}).get("brightness")
        return round(b * 100 / 255) if isinstance(b, (int, float)) else None

    def set_brightness(self, eid, pct):
        pct = int(min(100, max(1, pct)))
        s = self.states.get(eid)
        if s:
            raw = round(pct * 255 / 100)
            s["state"] = "on"; s["attributes"]["brightness"] = raw
            self._expect(eid, "brightness", raw); self._expect(eid, "state", True)
        self.call("light", "turn_on", entity_id=eid, brightness_pct=pct)

    def set_color(self, eid, rgb=None, kelvin=None):
        s = self.states.get(eid)
        if s:
            s["state"] = "on"; self._expect(eid, "state", True)
            s["attributes"].update({"color_mode": "rgb", "rgb_color": list(rgb)} if rgb else {"color_mode": "color_temp", "color_temp_kelvin": kelvin})
        if rgb: self.call("light", "turn_on", entity_id=eid, rgb_color=list(rgb))
        else: self.call("light", "turn_on", entity_id=eid, color_temp_kelvin=kelvin)

    def climate_set(self, eid, field, value):
        """hvac mode, fan mode or swing mode of a climate entity, shown at once and held until confirmed."""
        s = self.states.get(eid)
        if field == "hvac_mode":
            if s: s["state"] = value; self._expect(eid, "mode", value)
            self.call("climate", "set_hvac_mode", entity_id=eid, hvac_mode=value)
        else:
            if s: s["attributes"][field] = value; self._expect(eid, field, value)
            self.call("climate", f"set_{field}", entity_id=eid, **{field: value})

    def set_number(self, eid, value):
        s = self.states.get(eid)
        if eid.startswith("climate."):
            if s: s["attributes"]["temperature"] = value; self._expect(eid, "temperature", value)
            self.call("climate", "set_temperature", entity_id=eid, temperature=value)
        else:
            if s: s["state"] = str(value); self._expect(eid, "value", value)
            self.call("input_number", "set_value", entity_id=eid, value=value)


class Panel(SettingsMixin, ControllersMixin):
    def __init__(self):
        self._settings_init()
        self._config_init()
        self._ctrl_init()
        self.rooms = json.load(open(os.path.join(BASE, "rooms.json"), encoding="utf-8"))
        self.ha, self.lcd, self.tp = HomeAssistant(), LCD(hz=32_000_000), Touch()
        self._apply_rotation()
        self.view, self.hits, self.last_touch = "start", [], time.time()
        self.drags, self.dragging, self.light_drag = [], None, None

    # ---- drawing helpers
    def _center(self, d, box, text, f, fill):
        l, t, r, b = d.textbbox((0, 0), text, font=f)
        d.text(((box[0] + box[2] - (r - l)) / 2 - l, (box[1] + box[3] - (b - t)) / 2 - t), text, font=f, fill=fill)

    def _fit(self, d, text, f, width):
        if d.textlength(text, font=f) <= width: return text
        while len(text) > 1 and d.textlength(text + "…", font=f) > width: text = text[:-1]
        return text + "…"

    def _header(self, d, title, back=False, to="home"):
        x = 10
        if back:
            d.rounded_rectangle([6, 5, 76, 39], 8, fill=TILE_HI); self._center(d, (6, 5, 76, 39), "‹", F_BTN, TEXT)
            self.hits.append(((0, 0, 90, 48), lambda: self._go(to))); x = 88
        d.text((x, 11), title, font=F_TITLE, fill=TEXT)
        clock = time.strftime("%H:%M")
        d.text((W - 10 - d.textlength(clock, font=F_CLOCK), 11), clock, font=F_CLOCK, fill=MUTED)
        if self.ha.error:
            msg = self.ha.error.upper(); w = d.textlength(msg, font=F_PILL)
            d.rounded_rectangle([W - 82 - w - 16, 12, W - 82, 34], 11, fill=RED); d.text((W - 82 - w - 8, 16), msg, font=F_PILL, fill=BG)

    def _pill(self, d, x, y, label, on, color):
        w = 44
        d.rounded_rectangle([x, y, x + w, y + 20], 10, fill=color if on else None, outline=None if on else TILE_HI, width=2)
        self._center(d, (x, y, x + w, y + 20), label, F_PILL, BG if on else MUTED)

    def _humidity(self, room):
        """Relative humidity of a room: its own sensor, or the one that sits next to its temperature sensor."""
        eid = room.get("humidity") or room.get("temperature", "").replace("_temperatura", "_umidade")
        return self.ha.number(eid) if eid.startswith("sensor.") and eid != room.get("temperature") else None

    def _under(self, d, x, y):
        """Colour behind a point of a tile: the flat tile colour, or what the glass shows there."""
        return d.sample(x, y) if hasattr(d, "sample") else TILE

    # ---- views
    def _start(self, d):
        self._header(d, self._fit(d, self.cfg["name"], F_TITLE, 300))
        w = self.ha.weather()
        a = w["attributes"] if w else {}
        today = self.ha.forecast[0] if self.ha.forecast else {}
        cond = w["state"] if w else None
        box = (8, 52, 236, 208)
        d.rounded_rectangle(box, 12, fill=TILE)
        if w and cond not in ("unavailable", "unknown"):
            draw_weather(d, 58, 96, 56, cond, self._under(d, 78, 82))
            t = a.get("temperature")
            d.text((104, 62), f"{t:.0f}°" if isinstance(t, (int, float)) else "--", font=F_HUGE, fill=TEXT)
            d.text((16, 132), self._fit(d, CONDITIONS.get(cond, cond), F_COND, 212), font=F_COND, fill=TEXT)
            if "temperature" in today and "templow" in today:
                d.text((16, 158), f"máx {today['temperature']:.0f}°   mín {today['templow']:.0f}°", font=F_SUB, fill=TEXT)
            extra = [f"umid {a['humidity']:.0f}%" if "humidity" in a else None,
                     f"vento {a['wind_speed']:.0f} km/h" if "wind_speed" in a else None]
            d.text((16, 180), "   ".join(e for e in extra if e), font=F_SUB, fill=MUTED)
        else:
            self._center(d, box, "sem dados do tempo", F_SUB, MUTED)
        rbox = (244, 52, 472, 208)
        d.rounded_rectangle(rbox, 12, fill=TILE_HI)
        luzes = sum(self.ha.is_on(r["light"]) for r in self.rooms)
        ares = sum(self.ha.is_on(r["climate"]) for r in self.rooms)
        self._center(d, (rbox[0], rbox[1] + 30, rbox[2], rbox[1] + 90), "Ambientes ›", F_BTN, TEXT)
        self._center(d, (rbox[0], rbox[1] + 92, rbox[2], rbox[1] + 118), f"{luzes} luz(es) · {ares} ar(es) ligado(s)", F_SUB, MUTED)
        self.hits.append((rbox, lambda: self._go("home")))
        days, gap = self.ha.forecast[1:6], 8
        tw = (W - gap * 6) // 5
        for i, day in enumerate(days):
            x, y = gap + i * (tw + gap), 216
            d.rounded_rectangle([x, y, x + tw, 312], 10, fill=TILE)
            try: wd = WEEKDAYS[time.strptime(day["datetime"][:10], "%Y-%m-%d").tm_wday]
            except (KeyError, ValueError): wd = "--"
            self._center(d, (x, y + 4, x + tw, y + 24), wd, F_NAME, MUTED)
            draw_weather(d, x + tw // 2, y + 46, 34, {"clear-night": "sunny"}.get(day.get("condition"), day.get("condition")), self._under(d, x + tw // 2, y + 46))
            hi, lo = day.get("temperature"), day.get("templow")
            self._center(d, (x, y + 62, x + tw, y + 80), f"{hi:.0f}° {lo:.0f}°" if hi is not None and lo is not None else "--", F_NAME, TEXT)
            if day.get("precipitation", 0) >= 0.5:
                self._center(d, (x, y + 78, x + tw, y + 94), f"{day['precipitation']:.0f} mm" if day["precipitation"] >= 10 else f"{day['precipitation']:.1f} mm", F_PILL, CYAN)

    def _home(self, d):
        self._header(d, "Ambientes", back=True, to="start")
        gap, top, cols = 8, 46, 4
        tw, th = (W - gap * (cols + 1)) // cols, (H - top - gap * 2) // 2
        cells = self.rooms + [None]
        for i, room in enumerate(cells[:8]):
            x, y = gap + (i % cols) * (tw + gap), top + (i // cols) * (th + gap)
            box = (x, y, x + tw, y + th)
            d.rounded_rectangle(box, 10, fill=TILE)
            if room is None:
                self._center(d, (x, y, x + tw, y + th - 20), "⚙", font(38), MUTED)
                self._center(d, (x, y + th - 36, x + tw, y + th - 10), "Sistema", F_NAME, MUTED)
                self.hits.append((box, lambda: self._go("system"))); continue
            d.text((x + 9, y + 8), self._fit(d, room["name"], F_NAME, tw - 16), font=F_NAME, fill=MUTED)
            t = self.ha.number(room.get("temperature", ""))
            hum = self._humidity(room)
            self._center(d, (x, y + 28, x + tw, y + 72) if hum is not None else (x, y + 30, x + tw, y + 78),
                         f"{t:.1f}°" if t is not None else "--", F_TEMP, TEXT if t is not None else TILE_HI)
            if hum is not None: self._center(d, (x, y + 72, x + tw, y + 94), f"{hum:.0f}% umid.", F_SUB, CYAN)
            self._pill(d, x + 8, y + th - 30, "LUZ", any(self.ha.is_on(e) for k in ("light", "light2", "light3") for e in self._ents(room.get(k))), AMBER)
            self._pill(d, x + tw - 52, y + th - 30, "AR", self.ha.is_on(room["climate"]), CYAN)
            self.hits.append((box, lambda i=i: self._go(("room", i))))

    def _room(self, d, idx):
        room = self.rooms[idx]
        self._header(d, self._fit(d, room["name"], F_TITLE, 240), back=True)
        self._button(d, (346, 5, 400, 39), "⚙", lambda: self._go(("room_cfg", idx)), f=F_ICON)
        tv = room.get("tv")
        tiles = [("LUZ 1" if room.get("light2") else "LUZ", room["light"], AMBER, ("LIGADA", "DESLIGADA"), None)]
        tiles += [(label, room[k], AMBER, ("LIGADA", "DESLIGADA"), None) for k, label in (("light2", "LUZ 2"), ("light3", "LED")) if room.get(k)]
        for k, (label, eid, color, words, action) in enumerate(tiles):
            if isinstance(eid, list):          # several lights under one button: it opens a menu with one control each
                tiles[k] = (label, eid, color, ("LIGADO ›", "DESLIGADO ›"), lambda label=label: self._go(("leds", (idx, label))))
            elif self.ha.light_caps(eid)[0]:   # dimmable: the tile opens intensity and colour
                tiles[k] = (label, eid, color, ("LIGADA ›", "DESLIGADA ›"), lambda eid=eid, label=label: self._go(("light", (idx, eid, label))))
        ar_open = (lambda: self._go(("ar", idx))) if room["climate"].startswith("climate.") else None
        tiles.append(("AR", room["climate"], CYAN, ("LIGADO ›", "DESLIGADO ›") if ar_open else ("LIGADO", "DESLIGADO"), ar_open))
        if tv: tiles.append(("TV", tv, GREEN, ("LIGADA ›", "DESLIGADA ›"), lambda: self._go(("tv", idx))))
        tw = (W - 8 * (len(tiles) + 1)) / len(tiles)
        cols = [(int(8 + k * (tw + 8)), int(8 + k * (tw + 8) + tw)) for k in range(len(tiles))]
        for (x0, x1), (label, eid, color, words, action) in zip(cols, tiles):
            box, on = (x0, 50, x1, 166), any(self.ha.is_on(e) for e in self._ents(eid))
            d.rounded_rectangle(box, 12, fill=color if on else TILE)
            self._center(d, (box[0], box[1] + 14, box[2], box[1] + 70), label, F_BTN if len(tiles) < 5 else F_KEY, BG if on else TEXT)
            self._center(d, (box[0], box[1] + 72, box[2], box[3] - 12), words[0] if on else words[1], F_SUB, BG if on else MUTED)
            self.hits.append((box, action or (lambda eid=eid: self.ha.toggle(eid))))
        sp, eid = self.ha.number(room["setpoint"]), room["setpoint"]
        lo, hi = room.get("min", 16), room.get("max", 30)
        for box, sign, step in (((8, 174, 128, 312), "−", -1), ((352, 174, 472, 312), "+", 1)):
            d.rounded_rectangle(box, 12, fill=TILE_HI); self._center(d, box, sign, F_HUGE, TEXT)
            self.hits.append((box, lambda step=step: sp is not None and self.ha.set_number(eid, min(hi, max(lo, sp + step)))))
        self._center(d, (136, 180, 344, 272), f"{sp:.0f}°" if sp is not None else "--", F_HUGE, TEXT)
        t = self.ha.number(room.get("temperature", ""))
        hum = self._humidity(room)
        caption = (f"ambiente {t:.1f}°" if t is not None else "temperatura do ar") + (f"  ·  {hum:.0f}% umid." if hum is not None else "")
        self._center(d, (130, 276, 350, 306), caption, F_SUB, MUTED)

    def _tv(self, d, idx):
        room = self.rooms[idx]; eid = room.get("tv", "")
        s = self.ha.states.get(eid)
        self._header(d, self._fit(d, s["attributes"].get("friendly_name", "TV") if s else "TV", F_TITLE, 290), back=True, to=("room", idx))
        on = self.ha.is_on(eid); level, muted = self.ha.volume(eid)
        box = (8, 50, 236, 166)
        d.rounded_rectangle(box, 12, fill=GREEN if on else TILE)
        self._center(d, (box[0], box[1] + 14, box[2], box[1] + 70), "TV", F_BTN, BG if on else TEXT)
        self._center(d, (box[0], box[1] + 72, box[2], box[3] - 12), "LIGADA" if on else "DESLIGADA", F_SUB, BG if on else MUTED)
        self.hits.append((box, lambda: self.ha.toggle(eid)))
        box = (244, 50, 472, 166)
        d.rounded_rectangle(box, 12, fill=AMBER if muted else TILE)
        self._center(d, (box[0], box[1] + 14, box[2], box[1] + 70), "MUDO", F_BTN, BG if muted else TEXT if on else MUTED)
        self._center(d, (box[0], box[1] + 72, box[2], box[3] - 12), "ATIVADO" if muted else "DESATIVADO", F_SUB, BG if muted else MUTED)
        if on: self.hits.append((box, lambda: self.ha.mute(eid, not muted)))
        for box, sign, step in (((8, 174, 128, 312), "−", -0.02), ((352, 174, 472, 312), "+", 0.02)):
            d.rounded_rectangle(box, 12, fill=TILE_HI); self._center(d, box, sign, F_HUGE, TEXT if level is not None else MUTED)
            if level is not None: self.hits.append((box, lambda step=step: self.ha.set_volume(eid, level + step)))
        self._center(d, (136, 180, 344, 272), f"{level * 100:.0f}" if level is not None else "--", F_HUGE, TEXT)
        self._center(d, (136, 276, 344, 306), "volume", F_SUB, MUTED)

    WHEEL_C, WHEEL_R = (124, 184), 112          # colour wheel: centre and radius on screen
    FADER = (256, 152, 472, 200)                 # brightness fader track

    @staticmethod
    def _wheel_image(r):
        """Hue around, saturation outwards (white at the centre), as an RGB image with its circular mask."""
        n = 2 * r + 1
        y, x = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
        hue = (np.degrees(np.arctan2(-y, x)) % 360) / 60.0
        sat = np.clip(np.hypot(x, y) / r, 0, 1)
        i, f = np.floor(hue).astype(int) % 6, hue - np.floor(hue)
        p_, q, t = 1 - sat, 1 - sat * f, 1 - sat * (1 - f)
        one = np.ones_like(sat)
        rgb = np.select([i[..., None] == k for k in range(6)],
                        [np.dstack(c) for c in ((one, t, p_), (q, one, p_), (p_, one, t), (p_, q, one), (t, p_, one), (one, p_, q))])
        img = Image.fromarray((rgb * 255).astype(np.uint8), "RGB")
        mask = Image.fromarray(((np.hypot(x, y) <= r) * 255).astype(np.uint8), "L")
        return img, mask

    def _wheel_pick(self, x, y):
        """Colour under a point of the wheel (clamped to the rim), and the point itself."""
        (cx, cy), r = self.WHEEL_C, self.WHEEL_R
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy)
        if dist > r: dx, dy, dist = dx * r / dist, dy * r / dist, r
        h = (math.degrees(math.atan2(-dy, dx)) % 360) / 360
        rgb = tuple(round(v * 255) for v in colorsys.hsv_to_rgb(h, dist / r, 1))
        return rgb, (cx + dx, cy + dy)

    def _wheel_point(self, rgb):
        h, s, _ = colorsys.rgb_to_hsv(*(v / 255 for v in rgb))
        (cx, cy), r = self.WHEEL_C, self.WHEEL_R
        a = math.radians(h * 360)
        return cx + math.cos(a) * s * r, cy - math.sin(a) * s * r

    # Labels for the climate screen; anything not listed is shown as the integration names it.
    AC_MODES = {"heat_cool": "AUTO", "auto": "AUTO", "cool": "FRIO", "dry": "SECO", "fan_only": "VENTIL.", "heat": "CALOR"}
    AC_FANS = {"auto": "AUTO", "low": "BAIXA", "medium": "MÉDIA", "middle": "MÉDIA", "high": "ALTA", "quiet": "SILENC.",
               "focus": "FOCO", "diffuse": "DIFUSO", "turbo": "TURBO", "max": "MÁX"}
    AC_SWING = {"off": "PARADA", "vertical": "VERTICAL", "horizontal": "HORIZ.", "both": "AMBAS", "on": "MOVENDO"}

    def _ar(self, d, idx):
        """Full air conditioner control: power, setpoint, mode, fan and louvres."""
        room = self.rooms[idx]; eid = room["climate"]
        s = self.ha.states.get(eid); a = s["attributes"] if s else {}
        self._header(d, self._fit(d, a.get("friendly_name", "Ar"), F_TITLE, 290), back=True, to=("room", idx))
        state = s["state"] if s else "unavailable"
        on = state not in ("off", "unavailable", "unknown")
        modes = [m for m in a.get("hvac_modes", []) if m != "off"] or ["cool"]
        last = getattr(self, "_ar_last", {}).get(eid)
        # power
        box = (8, 48, 128, 118)
        d.rounded_rectangle(box, 12, fill=CYAN if on else TILE)
        self._center(d, (box[0], box[1] + 6, box[2], box[1] + 40), "AR", F_BTN, BG if on else TEXT)
        self._center(d, (box[0], box[1] + 40, box[2], box[3] - 4), "LIGADO" if on else "DESLIGADO", F_SMALL, BG if on else MUTED)
        def power():
            if on: self._ar_last = {**getattr(self, "_ar_last", {}), eid: state}; self.ha.climate_set(eid, "hvac_mode", "off")
            else: self.ha.climate_set(eid, "hvac_mode", last if last in modes else ("cool" if "cool" in modes else modes[0]))
        self.hits.append((box, power))
        # setpoint
        sp = a.get("temperature"); lo, hi = a.get("min_temp", 16), a.get("max_temp", 30)
        step = a.get("target_temp_step") or 1
        for box, sign, k in (((136, 48, 216, 118), "−", -1), ((392, 48, 472, 118), "+", 1)):
            d.rounded_rectangle(box, 12, fill=TILE_HI); self._center(d, box, sign, F_HUGE, TEXT)
            self.hits.append((box, lambda k=k: sp is not None and self.ha.set_number(eid, min(hi, max(lo, sp + k * step)))))
        self._center(d, (220, 46, 388, 100), f"{sp:.0f}°" if isinstance(sp, (int, float)) else "--", F_HUGE, TEXT if on else MUTED)
        cur = a.get("current_temperature")
        self._center(d, (220, 98, 388, 120), f"ambiente {cur:.1f}°" if isinstance(cur, (int, float)) else "temperatura", F_SMALL, MUTED)
        # option rows: mode, fan, louvres
        rows = [("Modo", modes, state if on else None, self.AC_MODES, lambda v: self.ha.climate_set(eid, "hvac_mode", v)),
                ("Ventil.", a.get("fan_modes") or [], a.get("fan_mode"), self.AC_FANS, lambda v: self.ha.climate_set(eid, "fan_mode", v)),
                ("Aletas", a.get("swing_modes") or [], a.get("swing_mode"), self.AC_SWING, lambda v: self.ha.climate_set(eid, "swing_mode", v))]
        y = 128
        for label, opts, cur_v, names, act in rows:
            if not opts: continue
            d.text((10, y + 15), label, font=F_PILL, fill=ORANGE)
            n = len(opts); x0 = 74; bw = (W - 8 - x0 - 6 * (n - 1)) / n
            for k, o in enumerate(opts):
                bx = (int(x0 + k * (bw + 6)), y, int(x0 + k * (bw + 6) + bw), y + 50)
                sel = o == cur_v
                d.rounded_rectangle(bx, 10, fill=AMBER if sel else TILE)
                txt = names.get(o, o.replace("_", " ").upper())
                fnt = F_PILL if d.textlength(txt, font=F_PILL) <= bw - 8 else F_SMALL
                self._center(d, bx, self._fit(d, txt, fnt, bw - 6), fnt, BG if sel else (TEXT if on else MUTED))
                self.hits.append((bx, lambda o=o, act=act: act(o)))
            y += 62

    @staticmethod
    def _ents(v):
        """A room control holds one entity id or, for a menu of several, a list of them."""
        return [e for e in (v if isinstance(v, list) else [v]) if e]

    def _leds(self, d, arg):
        """One button, several lights: a tile per light, each opening its own colour and intensity screen."""
        idx, label = arg
        room = self.rooms[idx]
        self._header(d, f"{label}  ·  {room['name']}", back=True, to=("room", idx))
        ents = self._ents(room.get("light3"))
        n = max(1, len(ents))
        cw = (W - 8 * (n + 1)) / n
        for k, eid in enumerate(ents):
            x0 = int(8 + k * (cw + 8)); box = (x0, 52, int(x0 + cw), 312)
            s = self.ha.states.get(eid); a = s["attributes"] if s else {}
            on, pct = self.ha.is_on(eid), self.ha.brightness(eid)
            name = a.get("friendly_name", eid)
            rgb = a.get("rgb_color") if on and a.get("color_mode") not in ("color_temp", None) else None
            d.rounded_rectangle(box, 14, fill=AMBER if on else TILE)
            fg, sub = (BG, BG) if on else (TEXT, MUTED)
            self._center(d, (box[0] + 8, box[1] + 18, box[2] - 8, box[1] + 60), self._fit(d, name, F_BTN if n < 3 else F_KEY, cw - 24), F_BTN if n < 3 else F_KEY, fg)
            self._center(d, (box[0], box[1] + 64, box[2], box[1] + 96), "LIGADO" if on else "DESLIGADO", F_SUB, sub)
            self._center(d, (box[0], box[1] + 100, box[2], box[1] + 170), f"{pct}%" if on and pct is not None else "--", F_HUGE, fg)
            if rgb:      # current colour as a swatch under the tile
                d.rounded_rectangle((box[0] + 24, box[3] - 54, box[2] - 24, box[3] - 30), 10, fill=tuple(rgb))
            self._center(d, (box[0], box[3] - 26, box[2], box[3] - 4), "cor e intensidade ›", F_SMALL, sub)
            self.hits.append((box, lambda eid=eid, name=name: self._go(("light", (idx, eid, name, ("leds", (idx, label)))))))

    def _light(self, d, arg):
        idx, eid, label = arg[:3]
        back = arg[3] if len(arg) > 3 else ("room", idx)
        s = self.ha.states.get(eid)
        a = s["attributes"] if s else {}
        self._header(d, self._fit(d, a.get("friendly_name", label), F_TITLE, 290), back=True, to=back)
        on, pct = self.ha.is_on(eid), self.ha.brightness(eid)
        _, has_rgb, has_ct = self.ha.light_caps(eid)
        drag = getattr(self, "light_drag", None)      # value under the finger, shown before it is sent
        # on / off
        box = (256, 50, 472, 110)
        d.rounded_rectangle(box, 12, fill=AMBER if on else TILE)
        self._center(d, (box[0], box[1] + 4, box[2], box[1] + 36), label, F_KEY, BG if on else TEXT)
        self._center(d, (box[0], box[1] + 34, box[2], box[3] - 4), "LIGADO" if on else "DESLIGADO", F_SUB, BG if on else MUTED)
        self.hits.append((box, lambda: self.ha.toggle(eid)))
        # brightness fader
        shown = drag[1] if drag and drag[0] == "fader" else (pct if on else None)
        x0, y0, x1, y1 = self.FADER
        d.text((x0 + 2, y0 - 26), "Intensidade", font=F_SUB, fill=MUTED)
        txt = f"{shown}%" if shown is not None else "--"
        d.text((x1 - d.textlength(txt, font=F_NAME), y0 - 26), txt, font=F_NAME, fill=TEXT)
        d.rounded_rectangle(self.FADER, 24, fill=TILE)
        if shown:
            fx = x0 + (x1 - x0) * shown / 100
            if fx - x0 >= 40: d.rounded_rectangle((x0, y0, fx, y1), 24, fill=AMBER)
            d.ellipse((fx - 22, y0 + 2, fx + 22, y1 - 2), fill=TEXT)
        def fader_move(x, y):
            self.light_drag = ("fader", int(min(100, max(1, round((x - x0) * 100 / (x1 - x0))))))
        def fader_done():
            v = self.light_drag; self.light_drag = None
            if v: self.ha.set_brightness(eid, v[1])
        self.drags.append(((x0 - 10, y0 - 14, x1 + 10, y1 + 14), fader_move, fader_done))
        # white temperatures
        if has_ct:
            cur_k = a.get("color_temp_kelvin") if on and a.get("color_mode") == "color_temp" else None
            for box, k, name, tone in (((256, 232, 360, 300), 2700, "QUENTE", (255, 196, 120)), ((368, 232, 472, 300), 6500, "FRIA", (226, 236, 255))):
                if cur_k and abs(cur_k - k) < 400: d.rounded_rectangle((box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3), 14, fill=TEXT)
                d.rounded_rectangle(box, 12, fill=tone)
                self._center(d, box, name, F_PILL, BG)
                self.hits.append((box, lambda k=k: self.ha.set_color(eid, kelvin=k)))
        # colour wheel
        (cx, cy), r = self.WHEEL_C, self.WHEEL_R
        if has_rgb:
            if not hasattr(self, "_wheel"): self._wheel = self._wheel_image(r)
            self._canvas.paste(self._wheel[0], (cx - r, cy - r), self._wheel[1])
            if drag and drag[0] == "wheel": point = drag[2]
            elif on and a.get("color_mode") != "color_temp" and a.get("rgb_color"): point = self._wheel_point(a["rgb_color"])
            else: point = None
            if point:
                px, py = point
                d.ellipse((px - 13, py - 13, px + 13, py + 13), fill=BG)
                d.ellipse((px - 10, py - 10, px + 10, py + 10), fill=TEXT)
            def wheel_move(x, y):
                rgb, pt = self._wheel_pick(x, y); self.light_drag = ("wheel", rgb, pt)
            def wheel_done():
                v = self.light_drag; self.light_drag = None
                if v: self.ha.set_color(eid, rgb=v[1])
            self.drags.append(((cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8), wheel_move, wheel_done))
        else:
            self._center(d, (cx - r, cy - 20, cx + r, cy + 20), "sem cor", F_SUB, MUTED)

    def _system(self, d):
        self._header(d, "Sistema", back=True)
        i, y = info(), 56
        nets = [n for n in i["ips"] if not n.startswith(("docker", "br-", "veth"))]
        rows = [(n.split()[0], n.split()[1]) for n in nets[:2]] + [
            ("CPU", f"{i['temp']}   carga {i['load']}"), ("RAM", i["mem"]), ("Disco", i["disk"]), ("Raiz", i["root"]),
            ("HA", self.ha.error or f"online, {len(self.ha.states)} entidades")]
        for k, v in rows:
            d.text((12, y), k, font=F_LINE, fill=ORANGE); d.text((100, y), self._fit(d, v, F_LINE, 228), font=F_LINE, fill=TEXT); y += 36
        self._button(d, (336, 52, 472, 110), "Wi-Fi", self._open_wifi, f=font(19, True))
        self._button(d, (336, 118, 472, 176), "Bluetooth", self._open_bt, f=font(19, True))
        self._button(d, (336, 184, 472, 242), "Tela", lambda: (self.disp.__setitem__("page", 0), self._go("display")), f=font(19, True))
        self._button(d, (336, 250, 472, 308), "Controladores", lambda: (self.ctrl.__setitem__("page", 0), self._go("ctrls")), f=font(16, True))

    # ---- intro and screensaver (raw RGB565 frames built by make_media.py)
    def _play_intro(self):
        try:
            with open(os.path.join(MEDIA, "intro.rgb565"), "rb") as f:
                t0, k = time.time(), 0
                while True:
                    buf = f.read(FRAME_BYTES)
                    if len(buf) < FRAME_BYTES: break
                    self.lcd.show_raw(buf); k += 1
                    time.sleep(max(0, t0 + k / INTRO_FPS - time.time()))
            time.sleep(0.8)
        except OSError:
            pass

    def _load_saver(self):
        try:
            data = open(os.path.join(MEDIA, "saver.rgb565"), "rb").read()
            return [data[i:i + FRAME_BYTES] for i in range(0, len(data) - FRAME_BYTES + 1, FRAME_BYTES)]
        except OSError:
            return []

    # ---- loop
    def _go(self, view): self.view = view

    def render(self):
        if self.cfg.get("theme", "glass") == "glass": img = glass.canvas(); d = glass.GlassDraw(img)
        else: img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img)
        self.hits, self.drags, self._canvas = [], [], img
        v = self.view; name = v if isinstance(v, str) else v[0]
        simple = {"start": self._start, "home": self._home, "system": self._system, "wifi": self._wifi, "bt": self._bt,
                  "kbd": self._kbd, "confirm": self._confirm, "display": self._display, "calib": self._calib, "ctrls": self._ctrls}
        if name in simple: simple[name](d)
        else: {"room": self._room, "wifi_net": self._wifi_net, "bt_dev": self._bt_dev, "room_cfg": self._room_cfg, "pick": self._pick, "tv": self._tv, "light": self._light, "leds": self._leds, "ar": self._ar,
                   "ctrl": self._ctrl, "ctrl_room": self._ctrl_room_pick, "ctrl_ac": self._ctrl_ac_pick, "ctrl_som": self._ctrl_som}[name](d, v[1])
        self.lcd.show(img)

    def run(self):
        if self.cfg["intro"]: self._play_intro()
        saver, saver_k, saver_next = self._load_saver(), 0, 0
        self.last_touch = time.time()
        pressed, released, drawn_minute, dirty = False, 0, None, True
        while True:
            now = time.time()
            t = self.tp.read()
            level = self._brightness()
            if level != self.lcd.brightness: self.lcd.brightness, dirty = level, True
            if self.view == "saver" and not saver:
                self.view, dirty = "start", True
            if self.view == "saver":
                if t and not pressed:      # a new touch only wakes the panel, it must not press what is underneath
                    pressed, released, self.last_touch, self.view, dirty = True, 0, now, "start", True
                else:
                    released = 0 if t else released + 1
                    if released >= 2: pressed = False
                    if now >= saver_next:
                        self.lcd.show_raw(saver[saver_k % len(saver)]); saver_k += 1
                        saver_next = max(saver_next + 1 / self.cfg["saver_fps"], now)
                    time.sleep(0.01)
                    continue
            elif t:
                released = 0
                if not pressed:
                    pressed, self.last_touch = True, now
                    if self.view == "calib":
                        self._calib_touch(t); dirty = True
                    else:
                        x, y = to_screen(t)
                        for (l, tp_, r, b), move, done in self.drags:
                            if l <= x <= r and tp_ <= y <= b: self.dragging = (move, done); move(x, y); dirty = True; break
                        else:
                            for (l, tp_, r, b), action in self.hits:
                                if l <= x <= r and tp_ <= y <= b: action(); dirty = True; break
                elif self.dragging:          # finger held: follow it, send only on release
                    self.dragging[0](*to_screen(t)); dirty = True
            else:
                released += 1
                if released >= 2:
                    pressed = False
                    if self.dragging: self.dragging[1](); self.dragging, dirty = None, True
            idle = now - self.last_touch
            if self.view != "start" and not self.busy and idle > self.cfg["idle_s"]: self.view, dirty = "start", True
            if self.view == "start" and saver and self.cfg["saver_s"] and not pressed and idle > self.cfg["saver_s"]:
                self.view, saver_k, saver_next = "saver", 0, now
                continue
            if self.ha.changed.is_set(): self.ha.changed.clear(); dirty = True
            if self.redraw.is_set(): self.redraw.clear(); dirty = True
            if self._settings_tick(now): dirty = True
            minute = time.strftime("%H:%M")
            if minute != drawn_minute or (self.view == "system" and int(now) % 5 == 0 and now - getattr(self, "_sys", 0) > 1):
                dirty, drawn_minute, self._sys = True, minute, now
            if dirty: self.render(); dirty = False
            time.sleep(0.03)


if __name__ == "__main__":
    os.chdir(BASE); Panel().run()
