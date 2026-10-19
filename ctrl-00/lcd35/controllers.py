"""Controllers (ESP32 boards running ESPHome) on the panel: which room each one serves, the state of its
terminals, and basic checks. Everything goes through Home Assistant, where the boards already report."""
import time, unicodedata
from lcd import W
from theme import *

OFFLINE = ("unknown", "unavailable", None)


class ControllersMixin:
    """Views mixed into Panel. Uses the list, button, row and toast widgets of SettingsMixin."""

    def _ctrl_init(self):
        self.ctrl = dict(page=0)
        self.ctrl_pick = dict(page=0)

    # ---- data
    def _controllers(self):
        """ESPHome boards known to Home Assistant: every name that has an online flag and a Wi-Fi signal sensor."""
        s = self.ha.states
        names = [e[len("binary_sensor."):-len("_online")] for e in s if e.startswith("binary_sensor.") and e.endswith("_online")]
        return sorted(n for n in names if f"sensor.{n}_sinal_wi_fi" in s)

    def _ctrl_label(self, n): return n.replace("_", "-").upper()

    def _ctrl_room(self, n): return next((r for r in self.rooms if r.get("esp") == n), None)

    def _val(self, eid, default=None):
        s = self.ha.states.get(eid)
        return s["state"] if s and s["state"] not in OFFLINE else default

    def _ctrl_online(self, n): return self._val(f"binary_sensor.{n}_online") == "on"

    # ---- list
    def _ctrls(self, d):
        self._header(d, "Controladores", back=True, to="system")
        def row(box, n):
            room, on = self._ctrl_room(n), self._ctrl_online(n)
            d.text((box[0] + 12, box[1] + 6), self._fit(d, f"{self._ctrl_label(n)}  ·  {room['name'] if room else 'sem ambiente'}", F_LINE, 300), font=F_LINE, fill=TEXT)
            sig = self._val(f"sensor.{n}_sinal_wi_fi")
            d.text((box[0] + 12, box[1] + 31), (f"online  ·  sinal {float(sig):.0f} dBm" if sig else "online") if on else "sem comunicação",
                   font=F_SMALL, fill=GREEN if on else RED)
            d.ellipse([box[2] - 30, box[1] + 18, box[2] - 16, box[1] + 32], fill=GREEN if on else RED)
        self._list(d, self._controllers(), self.ctrl, row, lambda n: self._go(("ctrl", n)), None,
                   "nenhum controlador ESPHome no Home Assistant", top=48, rows=5)
        self._toast_draw(d)

    # ---- one controller: its terminals and checks
    def _ctrl(self, d, n):
        self._header(d, self._ctrl_label(n), back=True, to="ctrls")
        on, room = self._ctrl_online(n), self._ctrl_room(n)
        up = self._val(f"sensor.{n}_tempo_ligado")
        up = f"{float(up) / 3600:.1f} h" if up and float(up) >= 3600 else f"{float(up) / 60:.0f} min" if up else "--"
        sig = self._val(f"sensor.{n}_sinal_wi_fi")
        ac = self._val(f"select.{n}_padrao_do_ar")
        rows = [("Ambiente", room["name"] if room else "não definido")]
        if ac: rows.append(("Ar", f"padrão {ac}  ›"))
        rows += [
                ("Estado", f"online há {up}" if on else "sem comunicação"),
                ("Rede", f"{self._val(f'sensor.{n}_ip', '--')}  ·  {float(sig):.0f} dBm" if sig else "--")]
        count = self._val(f"sensor.{n}_ir_sinais_recebidos")
        if count is not None or f"button.{n}_testar_emissor_ir" in self.ha.states:
            rows.append(("Receptor IR", f"{float(count):.0f} recebidos  ·  último: {self._val(f'sensor.{n}_ir_ultimo_sinal', '--')}" if count and float(count) > 0 else "nenhum sinal ainda"))
        gas = self._val(f"sensor.{n}_gas_tensao_do_sensor")
        if gas is not None:
            alarm = self._val(f"binary_sensor.{n}_gas_acima_do_limite") == "on"
            rows.append(("Gás", f"{float(gas):.2f} V  ·  {'ACIMA DO LIMITE' if alarm else 'normal'}"))
        y = 50
        for k, v in rows[:6]:
            d.text((14, y), k, font=F_NAME, fill=ORANGE)
            d.text((130, y - 2), self._fit(d, v, F_SUB, 340), font=F_SUB, fill=TEXT)
            if k == "Ar": self.hits.append(((8, y - 8, 472, y + 24), lambda: (self.ctrl_pick.__setitem__("page", 0), self._go(("ctrl_ac", n)))))
            y += 32
        free = on and not self.busy
        f = font(16, True)
        self._button(d, (8, 250, 118, 310), "Identificar", lambda: self._ctrl_identify(n), f=f,
                     enabled=free and f"light.{n}_led_da_placa" in self.ha.states)
        self._button(d, (126, 250, 236, 310), "Testar IR", lambda: self._ctrl_test_ir(n), f=f,
                     enabled=free and f"button.{n}_testar_emissor_ir" in self.ha.states)
        self._button(d, (244, 250, 354, 310), "Som", lambda: self._go(("ctrl_som", n)), f=f,
                     enabled=on and f"button.{n}_testar_buzzer" in self.ha.states)
        self._button(d, (362, 250, 472, 310), "Ambiente", lambda: (self.ctrl_pick.__setitem__("page", 0), self._go(("ctrl_room", n))), f=f)
        self._toast_draw(d)

    def _ctrl_identify(self, n):
        """Blinks the board's own LED so the physical controller can be told apart from the others."""
        def work():
            eid = f"light.{n}_led_da_placa"
            for _ in range(6):
                self.ha._request("/api/services/light/turn_on", {"entity_id": eid, "rgb_color": [255, 255, 255], "brightness": 255}); time.sleep(0.35)
                self.ha._request("/api/services/light/turn_off", {"entity_id": eid}); time.sleep(0.35)
            self._say(f"{self._ctrl_label(n)} piscou o LED da placa")
        self._async(work, "Piscando o LED da placa…")

    def _ctrl_test_ir(self, n):
        """Fires the emitter and checks whether the board's own receiver saw it."""
        def count():
            try: return float(self.ha._request(f"/api/states/sensor.{n}_ir_sinais_recebidos")["state"])
            except Exception: return 0.0
        def work():
            before = count()
            self.ha._request("/api/services/button/press", {"entity_id": f"button.{n}_testar_emissor_ir"})
            for _ in range(8):
                time.sleep(0.5)
                if count() > before:
                    self._say("Emissor e receptor funcionando"); return
            self._say("Emitiu; o receptor não captou. Aponte o LED para ele", AMBER, 8)
        self._async(work, "Testando o infravermelho…")

    # Short original riff (RTTTL) for the buzzer test: fast, driving, about 4 s.
    TEST_TUNE = "hub:d=16,o=6,b=150:8e,g,a,8b,a,g,8e,d,e,8g,4a,p,8e,g,a,8b,d7,b,4a,8g,4e"

    def _ctrl_som(self, d, n):
        """Buzzer volume (stored on the board) and sound tests."""
        self._header(d, "Som  ·  " + self._ctrl_label(n), back=True, to=("ctrl", n))
        eid = f"number.{n}_volume_do_bipe"
        try: cur = int(float(self.ha.states[eid]["state"]))
        except (KeyError, ValueError): cur = None
        drag = getattr(self, "light_drag", None)
        shown = drag[1] if drag and drag[0] == "vol" else cur
        x0, y0, x1, y1 = 24, 120, 456, 176
        d.text((x0, 64), "Volume do bipe", font=F_NAME, fill=MUTED)
        txt = f"{shown}%" if shown is not None else "--"
        d.text((x1 - d.textlength(txt, font=F_TEMP), 54), txt, font=F_TEMP, fill=TEXT)
        d.rounded_rectangle((x0, y0, x1, y1), 28, fill=TILE)
        if shown is not None:
            fx = x0 + (x1 - x0) * shown / 100
            if fx - x0 >= 56: d.rounded_rectangle((x0, y0, fx, y1), 28, fill=AMBER)
            d.ellipse((fx - 26, y0 + 2, fx + 26, y1 - 2), fill=TEXT)
        def move(x, y):
            self.light_drag = ("vol", int(min(100, max(0, round((x - x0) * 20 / (x1 - x0)) * 5))))
        def done():
            v = self.light_drag; self.light_drag = None
            if not v: return
            s = self.ha.states.get(eid)
            if s: s["state"] = str(v[1])
            self.ha.call("number", "set_value", entity_id=eid, value=v[1])     # the board beeps at the new volume
        if cur is not None: self.drags.append(((x0 - 10, y0 - 16, x1 + 10, y1 + 16), move, done))
        f = font(18, True)
        self._button(d, (24, 220, 236, 296), "Bipe", lambda: self.ha.call("button", "press", entity_id=f"button.{n}_bipe"), f=f,
                     enabled=f"button.{n}_bipe" in self.ha.states)
        self._button(d, (244, 220, 456, 296), "Música de teste", lambda: self._ctrl_test_sound(n), f=f, enabled=not self.busy)
        if cur is None: self._center(d, (x0, y0, x1, y1), "volume indisponível (firmware antigo)", F_SUB, MUTED)
        self._toast_draw(d)

    def _ctrl_test_sound(self, n):
        """Plays a tune on the controller's buzzer (ESPHome action <name>_buzzer_tocar)."""
        def work():
            self.ha._request(f"/api/services/esphome/{n}_buzzer_tocar", {"melodia": self.TEST_TUNE})
            self._say(f"{self._ctrl_label(n)} tocou o teste de som")
        self._async(work, "Tocando…")

    # ---- which air conditioner remote standard the controller speaks
    AC_TESTED = {"Samsung", "Elgin"}      # standards confirmed on a real appliance of this installation

    @staticmethod
    def _ac_entity(n, option):
        """Climate entity of a standard: the ESP names each one "Ar <option>"."""
        slug = "".join(c for c in unicodedata.normalize("NFKD", option.lower()) if c.isalnum() or c == " ").strip().replace(" ", "_")
        return f"climate.{n}_ar_{slug}"

    def _ctrl_ac_pick(self, d, n):
        self._header(d, "Padrão do ar  ·  " + self._ctrl_label(n), back=True, to=("ctrl", n))
        sel = f"select.{n}_padrao_do_ar"
        s = self.ha.states.get(sel)
        items = list(s["attributes"].get("options", [])) if s else []
        def row(box, opt):
            cur = s and s["state"] == opt
            d.text((box[0] + 12, box[1] + 6), opt, font=F_LINE, fill=GREEN if cur else TEXT)
            ok = self._ac_entity(n, opt) in self.ha.states
            tag = "testado em aparelho" if opt in self.AC_TESTED else "pré-configurado"
            d.text((box[0] + 12, box[1] + 31), (f"em uso  ·  {tag}" if cur else tag) if ok else "não encontrado no Home Assistant",
                   font=F_SMALL, fill=GREEN if cur else (MUTED if ok else RED))
        def choose(opt):
            if s: s["state"] = opt
            self.ha.call("select", "select_option", entity_id=sel, option=opt)
            room = self._ctrl_room(n)
            if room:      # the room's air control and +/- follow the chosen standard
                room["climate"] = room["setpoint"] = self._ac_entity(n, opt); self._rooms_save()
            self._say(f"{self._ctrl_label(n)}: ar no padrão {opt}" + ("" if room else " (defina o ambiente para usar no painel)"))
            self._go(("ctrl", n))
        self._list(d, items, self.ctrl_pick, row, choose, None, "este controlador não tem seletor de ar", top=48, rows=5)
        self._toast_draw(d)

    # ---- which room a controller serves
    def _ctrl_room_pick(self, d, n):
        self._header(d, "Ambiente do " + self._ctrl_label(n), back=True, to=("ctrl", n))
        items = [("Nenhum", None)] + [(r["name"], i) for i, r in enumerate(self.rooms)]
        def row(box, it):
            cur = (it[1] is None and not self._ctrl_room(n)) or (it[1] is not None and self.rooms[it[1]].get("esp") == n)
            d.text((box[0] + 12, box[1] + 13), self._fit(d, it[0], F_LINE, 290), font=F_LINE, fill=GREEN if cur else TEXT)
            other = self.rooms[it[1]].get("esp") if it[1] is not None else None
            if other and other != n:
                tag = "já tem " + self._ctrl_label(other)
                d.text((box[2] - 14 - d.textlength(tag, font=F_SMALL), box[1] + 18), tag, font=F_SMALL, fill=MUTED)
        def choose(it):
            for r in self.rooms:
                if r.get("esp") == n: r.pop("esp")
            if it[1] is not None: self.rooms[it[1]]["esp"] = n
            self._rooms_save(); self._go(("ctrl", n))
        self._list(d, items, self.ctrl_pick, row, choose, None, "", top=48, rows=5)
