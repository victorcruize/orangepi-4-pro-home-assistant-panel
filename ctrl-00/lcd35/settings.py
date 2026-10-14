"""Native settings screens for the CTRL-00 panel: Wi-Fi (NetworkManager) and Bluetooth (BlueZ), plus an on-screen keyboard."""
import json, os, re, subprocess, threading, time
import status
from lcd import W, H
from theme import *

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
CONFIG_DEFAULTS = dict(name="HUB", saver_s=60, idle_s=60, saver_fps=8, intro=True, cal=None, brightness=100, night=False, rotate=False, theme="glass")
THEME_CHOICES = [("glass", "vidro"), ("flat", "sólido")]
BRIGHT_CHOICES = [(100, "100%"), (80, "80%"), (60, "60%"), (40, "40%"), (25, "25%")]
NIGHT_HOURS, NIGHT_BRIGHTNESS = (22, 6), 20        # with night mode on: from 22h to 6h the panel drops to 20%
SAVER_CHOICES = [(30, "30 s"), (60, "1 min"), (120, "2 min"), (300, "5 min"), (600, "10 min"), (0, "nunca")]
IDLE_CHOICES = [(30, "30 s"), (60, "1 min"), (120, "2 min"), (300, "5 min")]
PULSE_CHOICES = [(5, "lento"), (8, "normal"), (12, "rápido")]
CAL_MARGIN = 40
CAL_TARGETS = [(CAL_MARGIN, CAL_MARGIN), (W - CAL_MARGIN, CAL_MARGIN), (W - CAL_MARGIN, H - CAL_MARGIN), (CAL_MARGIN, H - CAL_MARGIN)]
CAL_MAX_SHIFT_PX = 80          # a new calibration that moves a target further than this is treated as a mistake


def config_load():
    cfg = dict(CONFIG_DEFAULTS)
    try: cfg.update(json.load(open(CONFIG_PATH, encoding="utf-8")))
    except (OSError, ValueError): pass
    return cfg

KEYS = {"abc": ["qwertyuiop", "asdfghjkl", "zxcvbnm"], "ABC": ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"],
        "123": ["1234567890", "@#$%&*-_+", "!?.,:;/"], "#+=": ["()[]{}<>=~", "^|\\`'\"", ""]}


def run(args, timeout=20):
    """Runs a command without a shell. Returns (exit code, combined output)."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, str(e)


# ---- Wi-Fi (nmcli)
def _fields(line): return [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]

def wifi_radio(): return run(["nmcli", "radio", "wifi"])[1].strip() == "enabled"

def wifi_saved():
    out = run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"])[1]
    return {_fields(l)[0] for l in out.splitlines() if l.endswith(":802-11-wireless")}

def wifi_scan(rescan):
    out = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes" if rescan else "no"], 25)[1]
    nets = {}
    for line in out.splitlines():
        f = _fields(line)
        if len(f) < 4 or not f[1]: continue
        n = dict(ssid=f[1], active=f[0] == "*", signal=int(f[2] or 0), secure=f[3] not in ("", "--"))
        o = nets.get(n["ssid"])
        if not o or (n["active"] and not o["active"]) or (n["signal"] > o["signal"] and not o["active"]): nets[n["ssid"]] = n
    return sorted(nets.values(), key=lambda n: (not n["active"], -n["signal"]))

def wlan_ip():
    f = run(["ip", "-4", "-br", "a", "show", "wlan0"])[1].split()
    return f[2].split("/")[0] if len(f) > 2 else None

def wifi_error(out):
    o = out.lower()
    if "secrets were required" in o or "invalid" in o or "802-11-wireless-security" in o: return "Senha incorreta"
    if "no network with ssid" in o: return "Rede fora de alcance"
    if "timeout" in o: return "Tempo esgotado ao conectar"
    return "Falha ao conectar"


# ---- Bluetooth (bluetoothctl)
def bt_show():
    out = run(["bluetoothctl", "show"])[1]
    name = re.search(r"^\s*Alias: (.+)$", out, re.M)
    return dict(powered="Powered: yes" in out, name=name.group(1) if name else "")

def bt_devices():
    def listing(*flt):
        found = {}
        for l in run(["bluetoothctl", "devices", *flt])[1].splitlines():
            p = l.split(" ", 2)
            if len(p) >= 2 and p[0] == "Device": found[p[1]] = p[2] if len(p) > 2 else ""
        return found
    everything, paired, connected = listing(), listing("Paired"), listing("Connected")
    devs = []
    for mac, name in everything.items():
        named = bool(name) and name.replace("-", ":").upper() != mac
        if not named and mac not in paired: continue      # anonymous BLE beacons only clutter the list
        devs.append(dict(mac=mac, name=name if named else mac, paired=mac in paired, connected=mac in connected))
    return sorted(devs, key=lambda x: (not x["connected"], not x["paired"], x["name"].lower()))


class SettingsMixin:
    """Views mixed into Panel. Relies on Panel's _header, _center, _fit, _go, hits and view."""
    ROWS = 4

    def _settings_init(self):
        self.redraw, self.busy, self.toast = threading.Event(), False, None   # toast: (text, colour, expires | None)
        self.wifi = dict(nets=[], saved=set(), radio=True, page=0, loaded=False)
        self.bt = dict(devs=[], powered=True, name="", page=0, loaded=False)
        self.kbd = self.confirm = None
        self.pick = dict(page=0)

    def _settings_tick(self, now):
        if self.toast and self.toast[2] and now > self.toast[2]:
            self.toast = None; return True
        return False

    def _say(self, text, color=GREEN, secs=4):
        self.toast = (text, color, time.time() + secs); self.redraw.set()

    def _async(self, fn, busy_text=None):
        if self.busy: return
        self.busy = True
        if busy_text: self.toast = (busy_text, TILE_HI, None)
        def work():
            try: fn()
            except Exception as e: self._say(f"Erro: {e}", RED, 6)
            finally:
                if self.toast and self.toast[2] is None: self.toast = None
                self.busy = False; self.redraw.set()
        threading.Thread(target=work, daemon=True).start()

    # ---- shared widgets
    def _button(self, d, box, label, action, fill=TILE_HI, color=TEXT, f=F_NAME, enabled=True):
        d.rounded_rectangle(box, 10, fill=fill if enabled else TILE)
        self._center(d, box, label, f, color if enabled else MUTED)
        if enabled and action: self.hits.append((box, action))

    def _toast_draw(self, d):
        if not self.toast: return
        text, color, _ = self.toast
        d.rounded_rectangle([40, 270, W - 40, 312], 12, fill=color, outline=BG, width=3)
        self._center(d, (40, 270, W - 40, 312), self._fit(d, text, F_NAME, W - 110), F_NAME, TEXT if color == TILE_HI else BG)

    def _bars(self, d, x, y, pct, color):
        for k in range(4):
            h = 7 + k * 5
            d.rounded_rectangle([x + k * 9, y + 22 - h, x + k * 9 + 6, y + 22], 2, fill=color if pct >= (10, 35, 55, 75)[k] else TILE_HI)

    def _statusbar(self, d, text, sub, on, toggle):
        d.rounded_rectangle([8, 50, 472, 90], 10, fill=TILE)
        d.text((18, 54), self._fit(d, text, F_NAME, 330), font=F_NAME, fill=TEXT)
        d.text((18, 72), self._fit(d, sub, F_SMALL, 330), font=F_SMALL, fill=MUTED)
        box = (368, 56, 464, 84)
        d.rounded_rectangle(box, 14, fill=GREEN if on else TILE_HI)
        self._center(d, box, "LIGADO" if on else "DESLIGADO", F_PILL, BG if on else MUTED)
        self.hits.append(((352, 46, 480, 94), toggle))

    def _list(self, d, items, state, draw_row, on_tap, refresh, empty, top=96, rows=None):
        n = rows or self.ROWS
        rh, gap = (49, 4) if n == 5 else (50, 5)
        bottom = top + n * (rh + gap) - gap
        pages = max(1, -(-len(items) // n)); state["page"] = p = max(0, min(state["page"], pages - 1))
        for i, it in enumerate(items[p * n:(p + 1) * n]):
            box = (8, top + i * (rh + gap), 412, top + i * (rh + gap) + rh)
            d.rounded_rectangle(box, 10, fill=TILE); draw_row(box, it)
            self.hits.append((box, lambda it=it: on_tap(it)))
        if not items: self._center(d, (8, top, 412, bottom), empty, F_SUB, MUTED)
        third = (bottom - top - 2 * gap) // 3
        self._button(d, (420, top, 472, top + third), "▲", lambda: state.__setitem__("page", p - 1), f=F_LINE, enabled=p > 0)
        if refresh: self._button(d, (420, top + third + gap, 472, bottom - third - gap), "↻", refresh, f=F_ICON, enabled=not self.busy)
        else: self._center(d, (420, top + third, 472, bottom - third), f"{p + 1}/{pages}", F_SMALL, MUTED)
        self._button(d, (420, bottom - third, 472, bottom), "▼", lambda: state.__setitem__("page", p + 1), f=F_LINE, enabled=p < pages - 1)

    def _rows(self, d, rows, y=58):
        for k, v in rows:
            d.text((16, y), k, font=F_LINE, fill=ORANGE); d.text((150, y), self._fit(d, v, F_LINE, 310), font=F_LINE, fill=TEXT); y += 34

    # ---- confirmation
    def _ask(self, lines, yes_label, on_yes, back):
        self.confirm = dict(lines=lines, yes=yes_label, on_yes=on_yes, back=back); self._go("confirm")

    def _confirm(self, d):
        c = self.confirm
        self._header(d, "Confirmar", back=True, to=c["back"])
        y = 72
        for line in c["lines"]:
            self._center(d, (10, y, W - 10, y + 28), self._fit(d, line, F_LINE, W - 30), F_LINE, TEXT); y += 34
        self._button(d, (8, 212, 236, 302), "Cancelar", lambda: self._go(c["back"]), f=F_BTN)
        def yes(): self._go(c["back"]); c["on_yes"]()
        self._button(d, (244, 212, 472, 302), c["yes"], yes, fill=RED, color=BG, f=F_BTN)

    # ---- keyboard
    def _ask_text(self, title, on_ok, back, text=""):
        self.kbd = dict(title=title, text=text, mode="abc", on_ok=on_ok, back=back); self._go("kbd")

    def _kbd_type(self, ch):
        k = self.kbd; k["text"] += ch
        if k["mode"] == "ABC": k["mode"] = "abc"

    def _kbd(self, d):
        k = self.kbd; mode = k["mode"]; letters = mode in ("abc", "ABC")
        d.text((10, 5), self._fit(d, k["title"], F_NAME, W - 20), font=F_NAME, fill=MUTED)
        d.rounded_rectangle([8, 26, 472, 70], 8, fill=TILE, outline=CYAN, width=2)
        shown = k["text"] + "▏"
        while d.textlength(shown, font=F_LINE) > 440: shown = shown[1:]
        d.text((18, 36), shown, font=F_LINE, fill=TEXT)
        kw, kh, top = 48, 58, 78
        def key(box, label, action, fill=TILE, f=F_KEY, color=TEXT):
            d.rounded_rectangle([box[0] + 2, box[1] + 2, box[2] - 2, box[3] - 2], 7, fill=fill)
            self._center(d, box, label, f, color); self.hits.append((box, action))
        for r, chars in enumerate(KEYS[mode]):
            x0, y = (W - len(chars) * kw) // 2, top + r * kh
            for i, ch in enumerate(chars):
                key((x0 + i * kw, y, x0 + (i + 1) * kw, y + kh), ch, lambda ch=ch: self._kbd_type(ch))
        y = top + 2 * kh
        shift_to = {"abc": "ABC", "ABC": "abc", "123": "#+=", "#+=": "123"}[mode]
        key((0, y, 72, y + kh), "⇧" if letters else shift_to, lambda: k.__setitem__("mode", shift_to),
            CYAN if mode == "ABC" else TILE_HI, F_KEY if letters else F_NAME, BG if mode == "ABC" else TEXT)
        key((408, y, 480, y + kh), "⌫", lambda: k.__setitem__("text", k["text"][:-1]), TILE_HI)
        y = top + 3 * kh
        key((0, y, 72, y + kh), "123" if letters else "abc", lambda: k.__setitem__("mode", "123" if letters else "abc"), TILE_HI, F_NAME)
        key((72, y, 264, y + kh), "espaço", lambda: self._kbd_type(" "), TILE, F_SUB, MUTED)
        key((264, y, 372, y + kh), "Cancelar", lambda: self._go(k["back"]), TILE_HI, F_NAME)
        def ok(): self._go(k["back"]); k["on_ok"](k["text"])
        key((372, y, 480, y + kh), "OK", ok, GREEN, F_BTN, BG)

    # ---- display and system settings (persisted in config.json)
    def _config_init(self):
        self.cfg, self.disp, self.calib = config_load(), dict(page=0), None
        if self.cfg.get("cal"): status.CAL.update(self.cfg["cal"])

    def _config_save(self):
        with open(CONFIG_PATH + ".tmp", "w", encoding="utf-8") as f: json.dump(self.cfg, f, ensure_ascii=False, indent=1)
        os.replace(CONFIG_PATH + ".tmp", CONFIG_PATH)

    def _apply_rotation(self):
        flipped = bool(self.cfg.get("rotate"))
        status.ROTATED = flipped
        self.lcd.rotate(flipped)

    def _toggle_rotation(self):
        self.cfg["rotate"] = not self.cfg.get("rotate"); self._config_save(); self._apply_rotation()

    def _brightness(self):
        """Current picture brightness, 0..1, from the setting and the night mode."""
        level = self.cfg.get("brightness", 100)
        hour = time.localtime().tm_hour
        if self.cfg.get("night") and (hour >= NIGHT_HOURS[0] or hour < NIGHT_HOURS[1]): level = min(level, NIGHT_BRIGHTNESS)
        return level / 100

    def _cycle(self, key, choices):
        values = [v for v, _ in choices]; cur = self.cfg.get(key)
        self.cfg[key] = values[(values.index(cur) + 1) % len(values)] if cur in values else values[0]
        self._config_save()

    def _display(self, d):
        self._header(d, "Tela e sistema", back=True, to="system")
        cfg = self.cfg
        def label(key, choices): return dict(choices).get(cfg.get(key), str(cfg.get(key)))
        def rename(t):
            if t.strip(): cfg["name"] = t.strip(); self._config_save()
        def power(lines, yes, args): self._ask(lines, yes, lambda: subprocess.Popen(args), "display")
        items = [
            ("Luminosidade", label("brightness", BRIGHT_CHOICES), lambda: self._cycle("brightness", BRIGHT_CHOICES)),
            ("Aparência", label("theme", THEME_CHOICES), lambda: self._cycle("theme", THEME_CHOICES)),
            ("Modo noturno (22h às 6h)", "20%" if cfg.get("night") else "não", lambda: (cfg.__setitem__("night", not cfg.get("night")), self._config_save())),
            ("Girar tela 180°", "girada" if cfg.get("rotate") else "normal", self._toggle_rotation),
            ("Nome do painel", cfg["name"], lambda: self._ask_text("Nome do painel", rename, "display", cfg["name"])),
            ("Descanso de tela após", label("saver_s", SAVER_CHOICES), lambda: self._cycle("saver_s", SAVER_CHOICES)),
            ("Voltar ao início após", label("idle_s", IDLE_CHOICES), lambda: self._cycle("idle_s", IDLE_CHOICES)),
            ("Ritmo do pulso", label("saver_fps", PULSE_CHOICES), lambda: self._cycle("saver_fps", PULSE_CHOICES)),
            ("Abertura ao ligar", "sim" if cfg["intro"] else "não", lambda: (cfg.__setitem__("intro", not cfg["intro"]), self._config_save())),
            ("Ver descanso agora", "›", lambda: self._go("saver")),
            ("Calibrar toque", "›", self._calib_start),
            ("Reiniciar painel", "›", lambda: power(["Reiniciar o painel?", "A tela volta em alguns segundos."], "Reiniciar", ["systemctl", "restart", "lcd35-panel"])),
            ("Reiniciar placa", "›", lambda: power(["Reiniciar a placa?", "Home Assistant e automações", "ficam fora do ar por cerca de 1 minuto."], "Reiniciar", ["systemctl", "reboot"])),
            ("Desligar placa", "›", lambda: power(["Desligar a placa?", "Home Assistant e automações param.", "Para religar, tire e ponha a energia."], "Desligar", ["systemctl", "poweroff"])),
        ]
        def row(box, it):
            d.text((box[0] + 12, box[1] + 13), it[0], font=F_LINE, fill=TEXT)
            value = self._fit(d, it[1], F_LINE, 150)
            d.text((box[2] - 14 - d.textlength(value, font=F_LINE), box[1] + 13), value, font=F_LINE, fill=MUTED if it[1] == "›" else CYAN)
        self._list(d, items, self.disp, row, lambda it: it[2](), None, "", top=48, rows=5)
        self._toast_draw(d)

    def _calib_start(self):
        self.calib = dict(step=0, raw=[]); self._go("calib")

    def _calib(self, d):
        c = self.calib; x, y = CAL_TARGETS[c["step"]]
        self._center(d, (0, 112, W, 152), "Toque no centro da cruz", F_BTN, TEXT)
        self._center(d, (0, 158, W, 186), f"ponto {c['step'] + 1} de 4  ·  firme, com a unha ou uma caneta", F_SUB, MUTED)
        self._center(d, (0, 188, W, 212), "sem toque, cancela sozinho", F_SMALL, MUTED)
        d.line([x - 24, y, x + 24, y], fill=AMBER, width=3); d.line([x, y - 24, x, y + 24], fill=AMBER, width=3)
        d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=AMBER, width=2)

    def _calib_touch(self, first):
        samples = [first]
        for _ in range(8):
            time.sleep(0.02); s = self.tp.read()
            if s: samples.append(s)
        if len(samples) < 4: return                       # too light or too short: ask for the same point again
        c, mid = self.calib, len(samples) // 2
        c["raw"].append((sorted(s[0] for s in samples)[mid], sorted(s[1] for s in samples)[mid])); c["step"] += 1
        if c["step"] < 4: return
        # The fit is done in panel coordinates; with the picture turned 180 degrees the four crosses were shown
        # at the opposite physical corners, so the samples are put back in physical order first.
        tl, tr, br, bl = (c["raw"][2:] + c["raw"][:2]) if status.ROTATED else c["raw"]; m = CAL_MARGIN
        ry_left, ry_right = (tl[1] + bl[1]) / 2, (tr[1] + br[1]) / 2        # raw Y runs along screen X
        rx_top, rx_bottom = (tl[0] + tr[0]) / 2, (bl[0] + br[0]) / 2        # raw X runs along screen Y
        kx, ky = (ry_right - ry_left) / (W - 2 * m), (rx_bottom - rx_top) / (H - 2 * m)
        cal = dict(x0=round(ry_left - m * kx), x1=round(ry_left - m * kx + (W - 1) * kx),
                   y0=round(rx_top - m * ky), y1=round(rx_top - m * ky + (H - 1) * ky))
        old = dict(status.CAL)
        shift = max(max(abs(sx - tx), abs(sy - ty)) for (sx, sy), (tx, ty) in zip((status.to_screen(r) for r in c["raw"]), CAL_TARGETS))
        self._go("display")
        if abs(cal["x1"] - cal["x0"]) < 1500 or abs(cal["y1"] - cal["y0"]) < 1500 or shift > CAL_MAX_SHIFT_PX:
            status.CAL.update(old); self._say("Calibração descartada: toques fora das cruzes", RED, 7)
        else:
            status.CAL.update(cal); self.cfg["cal"] = cal; self._config_save(); self._say(f"Toque calibrado (ajuste de {shift:.0f} px)")

    # ---- room mapping (which Home Assistant entity each control of a room drives)
    OPTIONAL_FIELDS = ("light2", "tv")
    ROOM_FIELDS = (("name", "Nome", ()), ("light", "Luz", ("light.", "switch.", "input_boolean.")),
                   ("light2", "Luz 2", ("light.", "switch.", "input_boolean.")),
                   ("climate", "Ar", ("climate.", "input_boolean.")), ("temperature", "Temperatura", ("sensor.",)),
                   ("tv", "TV", ("media_player.",)))

    def _ent_label(self, eid):
        s = self.ha.states.get(eid)
        return s["attributes"].get("friendly_name", eid) if s else (f"{eid} (não existe)" if eid else "nenhum")

    def _rooms_save(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rooms.json")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write("[\n" + ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in self.rooms) + "\n]\n")
        os.replace(path + ".tmp", path)

    def _room_cfg(self, d, idx):
        room = self.rooms[idx]
        self._header(d, "Configurar ambiente", back=True, to=("room", idx))
        y = 46
        for key, label, domains in self.ROOM_FIELDS:
            box = (8, y, 472, y + 42)
            d.rounded_rectangle(box, 9, fill=TILE)
            d.text((18, y + 14), label, font=F_PILL, fill=ORANGE)
            d.text((120, y + 9), self._fit(d, room["name"] if key == "name" else self._ent_label(room.get(key, "")), F_LINE, 320), font=F_LINE, fill=TEXT)
            d.text((446, y + 3), "›", font=F_BTN, fill=MUTED)
            if key == "name":
                def rename(t, room=room):
                    if t.strip(): room["name"] = t.strip(); self._rooms_save()
                self.hits.append((box, lambda rename=rename: self._ask_text("Nome do ambiente", rename, ("room_cfg", idx), room["name"])))
            else:
                self.hits.append((box, lambda key=key: (self.pick.__setitem__("page", 0), self._go(("pick", (idx, key))))))
            y += 46

    def _pick_items(self, key):
        domains = dict((k, dm) for k, _, dm in self.ROOM_FIELDS)[key]
        items = []
        for eid, s in self.ha.states.items():
            if not eid.startswith(domains) or s["state"] == "unavailable": continue
            a = s["attributes"]
            if key == "temperature" and a.get("device_class") != "temperature": continue
            items.append((a.get("friendly_name", eid), eid))
        items.sort(key=lambda x: (domains.index(x[1].split(".")[0] + "."), x[0].lower()))
        return ([("Nenhum", "")] if key in self.OPTIONAL_FIELDS else []) + items

    def _pick(self, d, arg):
        idx, key = arg; room = self.rooms[idx]
        self._header(d, "Escolher " + dict((k, l) for k, l, _ in self.ROOM_FIELDS)[key].lower(), back=True, to=("room_cfg", idx))
        def row(box, it):
            cur = room.get(key) == it[1]
            d.text((box[0] + 12, box[1] + 6), self._fit(d, it[0], F_LINE, 380), font=F_LINE, fill=GREEN if cur else TEXT)
            d.text((box[0] + 12, box[1] + 31), self._fit(d, it[1] or "deixa este controle vazio", F_SMALL, 380), font=F_SMALL, fill=MUTED)
        def choose(it):
            eid = room[key] = it[1]
            if key == "climate":      # keep the +/- control and the temperature read-out pointing at the same appliance
                m = re.fullmatch(r"input_boolean\.ar_ambiente_(\d+)", eid)
                room["setpoint"] = eid if eid.startswith("climate.") else f"input_number.setpoint_ambiente_{m.group(1)}" if m else ""
                sensor = "sensor." + eid.split(".", 1)[1] + "_temperatura"
                if sensor in self.ha.states: room["temperature"] = sensor
                humidity = "sensor." + eid.split(".", 1)[1] + "_umidade"
                room["humidity"] = humidity if humidity in self.ha.states else ""
            self._rooms_save(); self._go(("room_cfg", idx))
        self._list(d, self._pick_items(key), self.pick, row, choose, None, "nenhuma entidade deste tipo no Home Assistant", top=48, rows=5)

    # ---- Wi-Fi
    def _wifi_load(self, rescan=True):
        radio = wifi_radio()
        self.wifi.update(radio=radio, saved=wifi_saved(), nets=wifi_scan(rescan) if radio else [], loaded=True)

    def _open_wifi(self):
        self._go("wifi"); self.wifi["page"] = 0
        def work(): self._wifi_load(False); self.redraw.set(); self._wifi_load(True)
        self._async(work, "Buscando redes…")

    def _wifi_toggle(self):
        if self.busy: return
        if self.wifi["radio"]:
            self._ask(["Desligar o Wi-Fi?", "Sem cabo de rede, o servidor fica", "fora da rede até religar por aqui."], "Desligar",
                      lambda: self._async(lambda: (run(["nmcli", "radio", "wifi", "off"]), self._wifi_load(False)), "Desligando Wi-Fi…"), "wifi")
        else:
            def on(): run(["nmcli", "radio", "wifi", "on"]); time.sleep(4); self._wifi_load(True)
            self._async(on, "Ligando Wi-Fi…")

    def _wifi(self, d):
        self._header(d, "Wi-Fi", back=True, to="system")
        w = self.wifi; cur = next((n for n in w["nets"] if n["active"]), None)
        self._statusbar(d, cur["ssid"] if cur else "Desconectado" if w["radio"] else "Wi-Fi desligado",
                        (wlan_ip() or "sem endereço IP") if w["radio"] else "rádio desligado", w["radio"], self._wifi_toggle)
        def row(box, n):
            x, y = box[0], box[1]
            d.text((x + 12, y + 6), self._fit(d, n["ssid"], F_LINE, 300), font=F_LINE, fill=TEXT)
            tag = "conectada" if n["active"] else "salva" if n["ssid"] in w["saved"] else "protegida" if n["secure"] else "aberta"
            d.text((x + 12, y + 31), tag, font=F_SMALL, fill=GREEN if n["active"] else MUTED)
            self._bars(d, box[2] - 50, y + 13, n["signal"], GREEN if n["active"] else TEXT)
        self._list(d, w["nets"], w, row, lambda n: self._go(("wifi_net", n["ssid"])),
                   lambda: self._async(lambda: self._wifi_load(True), "Buscando redes…"),
                   "nenhuma rede encontrada" if w["loaded"] and w["radio"] and not self.busy else "")
        self._toast_draw(d)

    def _wifi_net(self, d, ssid):
        self._header(d, self._fit(d, ssid, F_TITLE, 290), back=True, to="wifi")
        w = self.wifi; n = next((x for x in w["nets"] if x["ssid"] == ssid), None)
        saved, active = ssid in w["saved"], bool(n and n["active"])
        self._rows(d, [("Sinal", f"{n['signal']}%" if n else "fora de alcance"),
                       ("Segurança", ("protegida" if n["secure"] else "aberta") if n else "--"),
                       ("Estado", "conectada" if active else "salva" if saved else "nova")])
        self._button(d, (8, 176, 236, 262), "Conectada" if active else "Conectar", lambda: self._wifi_connect(ssid, n, saved),
                     fill=GREEN, color=BG, f=F_BTN, enabled=bool(n) and not active and not self.busy)
        self._button(d, (244, 176, 472, 262), "Esquecer", lambda: self._wifi_forget(ssid, active), f=F_BTN, enabled=saved and not self.busy)
        self._toast_draw(d)

    def _wifi_connect(self, ssid, n, saved):
        if n["secure"] and not saved:
            self._ask_text(f"Senha da rede {ssid}", lambda pw: self._wifi_do_connect(ssid, pw, saved), ("wifi_net", ssid))
        else:
            self._wifi_do_connect(ssid, None, saved)

    def _wifi_do_connect(self, ssid, pw, saved):
        prev = next((x["ssid"] for x in self.wifi["nets"] if x["active"]), None)
        def work():
            if saved: rc, out = run(["nmcli", "con", "up", "id", ssid], 45)
            else: rc, out = run(["nmcli", "dev", "wifi", "connect", ssid] + (["password", pw] if pw else []), 45)
            if rc == 0:
                self._say(f"Conectado a {ssid}")
            else:
                if not saved: run(["nmcli", "con", "delete", "id", ssid])      # do not keep a profile with a bad password
                if prev and prev != ssid: run(["nmcli", "con", "up", "id", prev], 45)
                self._say(wifi_error(out) + (": esqueça e conecte de novo" if saved and "Senha" in wifi_error(out) else ""), RED, 7)
            self._wifi_load(False)
        self._async(work, f"Conectando a {ssid}…")

    def _wifi_forget(self, ssid, active):
        lines = [f"Esquecer a rede {ssid}?"] + (["É a rede em uso: o servidor", "fica sem Wi-Fi até conectar outra."] if active else [])
        def work(): run(["nmcli", "con", "delete", "id", ssid]); self._wifi_load(False); self._say("Rede esquecida")
        self._ask(lines, "Esquecer", lambda: (self._go("wifi"), self._async(work, "Removendo…")), ("wifi_net", ssid))

    # ---- Bluetooth
    def _bt_load(self):
        s = bt_show()
        self.bt.update(powered=s["powered"], name=s["name"], devs=bt_devices() if s["powered"] else [], loaded=True)

    def _open_bt(self):
        self._go("bt"); self.bt["page"] = 0; self._async(self._bt_load)

    def _bt_scan(self):
        def work(): run(["bluetoothctl", "--timeout", "10", "scan", "on"], 15); self._bt_load()
        self._async(work, "Buscando dispositivos… 10 s")

    def _bt_toggle(self):
        if self.busy: return
        if self.bt["powered"]:
            self._ask(["Desligar o Bluetooth?", "O Home Assistant deixa de ver", "os dispositivos Bluetooth."], "Desligar",
                      lambda: self._async(lambda: (run(["bluetoothctl", "power", "off"]), self._bt_load()), "Desligando…"), "bt")
        else:
            self._async(lambda: (run(["bluetoothctl", "power", "on"]), time.sleep(1), self._bt_load()), "Ligando Bluetooth…")

    def _bt(self, d):
        self._header(d, "Bluetooth", back=True, to="system")
        b = self.bt
        sub = f"{sum(x['connected'] for x in b['devs'])} conectado(s) · {sum(x['paired'] for x in b['devs'])} pareado(s)"
        self._statusbar(d, b["name"] or "Bluetooth", sub if b["powered"] else "rádio desligado", b["powered"], self._bt_toggle)
        def row(box, x):
            d.text((box[0] + 12, box[1] + 6), self._fit(d, x["name"], F_LINE, 370), font=F_LINE, fill=TEXT)
            tag = "conectado" if x["connected"] else "pareado" if x["paired"] else "disponível"
            d.text((box[0] + 12, box[1] + 31), tag, font=F_SMALL, fill=GREEN if x["connected"] else CYAN if x["paired"] else MUTED)
        self._list(d, b["devs"], b, row, lambda x: self._go(("bt_dev", x["mac"])), self._bt_scan,
                   "toque em ↻ para buscar dispositivos" if b["loaded"] and b["powered"] and not self.busy else "")
        self._toast_draw(d)

    def _bt_dev(self, d, mac):
        x = next((v for v in self.bt["devs"] if v["mac"] == mac), None)
        self._header(d, self._fit(d, x["name"] if x else mac, F_TITLE, 290), back=True, to="bt")
        if not x:
            self._center(d, (8, 60, 472, 200), "dispositivo não está mais disponível", F_SUB, MUTED); self._toast_draw(d); return
        self._rows(d, [("Endereço", mac), ("Estado", "conectado" if x["connected"] else "pareado" if x["paired"] else "não pareado")])
        left, right, free = (8, 176, 236, 262), (244, 176, 472, 262), not self.busy
        if not x["paired"]:
            self._button(d, left, "Parear", lambda: self._bt_do(mac, "pair"), fill=GREEN, color=BG, f=F_BTN, enabled=free)
        elif x["connected"]:
            self._button(d, left, "Desconectar", lambda: self._bt_do(mac, "disconnect"), f=F_BTN, enabled=free)
        else:
            self._button(d, left, "Conectar", lambda: self._bt_do(mac, "connect"), fill=GREEN, color=BG, f=F_BTN, enabled=free)
        if x["paired"]:
            self._button(d, right, "Remover", lambda: self._ask([f"Remover {x['name']}?", "O pareamento será apagado."], "Remover",
                                                               lambda: self._bt_do(mac, "remove"), ("bt_dev", mac)), f=F_BTN, enabled=free)
        self._toast_draw(d)

    def _bt_do(self, mac, what):
        def work():
            if what == "pair":
                out = run(["bluetoothctl", "--agent", "NoInputNoOutput", "--timeout", "30", "pair", mac], 35)[1]
                if "Pairing successful" in out or "AlreadyExists" in out:
                    run(["bluetoothctl", "trust", mac]); run(["bluetoothctl", "--timeout", "12", "connect", mac], 16)
                    self._say("Pareado")
                else:
                    self._say("Falha ao parear: ponha o dispositivo em modo de pareamento", RED, 7)
            elif what == "connect":
                out = run(["bluetoothctl", "--timeout", "15", "connect", mac], 20)[1]
                self._say("Conectado") if "Connection successful" in out else self._say("Não foi possível conectar", RED, 6)
            elif what == "disconnect":
                run(["bluetoothctl", "disconnect", mac], 12); self._say("Desconectado")
            else:
                run(["bluetoothctl", "remove", mac], 12); self._say("Dispositivo removido"); self._go("bt")
            self._bt_load()
        self._async(work, {"pair": "Pareando…", "connect": "Conectando…", "disconnect": "Desconectando…", "remove": "Removendo…"}[what])
