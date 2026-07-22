"""Sectioned session overlay (always-on-top, click-through).

EQBuddy-style widget on our StoneGlass meter base: collapsible sections
- COMBAT   ranked class-colored damage bars (Damage|DPS, fight|last-5)
- SESSION  kills/deaths, XP + XP/hr, coin + coin/hr, crits/hit rate
- LOOT     recent drops + best observed drop-rate mobs
- PROGRESS level, hours-to-ding estimate, session/active clock
plus a COMPACT mode (header strip only) and adjustable opacity.

While Scroll Lock is OFF the window is CLICK-THROUGH — every click lands
in the game. Scroll Lock ON makes it interactive: drag to move, click
the title to switch Damage|DPS, the right header side to switch
fight|last-5, a section header to collapse/expand it, keys c=compact
+/-=opacity, double-click to close. Layout/position/opacity persist to
data/overlay_ui.json. Passive: reads the HTTP API only.

The overlay is a singleton (a second launch exits immediately) and
closes itself when the game exits.

Run: python -m backend.overlay   (or the Overlay button in the web header)
"""
import colorsys
import ctypes
import json
import threading
import time
import tkinter as tk
import urllib.request
from pathlib import Path

API_CHAR = "http://localhost:8000/api/character"
API_ENCS = "http://localhost:8000/api/encounters?limit=5"
STATE_FILE = Path("data") / "overlay_ui.json"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
VK_SCROLL = 0x91

BG = "#12151a"
HEADER_BG = "#1b1f26"
SEC_BG = "#171b21"
GOLD = "#c8aa6e"
BRIGHT = "#e7cd92"
INK = "#e6dEca"
MUTED = "#8b8577"
HEAL = "#1fb38c"
RED = "#d4574a"

W = 300
HEADER_H = 22
SEC_H = 15
ROW_H = 17
TROW_H = 14
HINT_H = 13

SECTIONS = ("combat", "timers", "session", "loot", "progress")
ALERT_BANNER_SECS = 6.0

# EQ class colors (first abbrev of the trio decides the bar color)
CLASS_COLORS = {
    "WAR": "#b5654a", "CLR": "#e8e0c0", "PAL": "#d8a8c8", "RNG": "#5fb55f",
    "SHD": "#7a5fb5", "DRU": "#c89a3e", "MNK": "#5fc4b0", "BRD": "#c45fb0",
    "ROG": "#c8c05f", "SHM": "#5f9fc4", "NEC": "#8fd45f", "WIZ": "#5f7fd4",
    "MAG": "#d47f5f", "ENC": "#b0a0e0", "BST": "#a08060", "BER": "#d45f5f",
}


def _class_color(classes, name):
    ab = (classes or "").split("/")[0].strip().upper()
    if ab in CLASS_COLORS:
        return CLASS_COLORS[ab]
    hue = (hash(name or "?") % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.40, 0.72)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _fmt(v):
    v = v or 0
    return f"{v / 1000:.1f}k" if v >= 10000 else f"{v:,.0f}"


def _fmt_coin(copper):
    """3267 copper -> '3p2g' (two largest denominations)."""
    c = int(copper or 0)
    parts = [(c // 1000, "p"), ((c % 1000) // 100, "g"),
             ((c % 100) // 10, "s"), (c % 10, "c")]
    out = [f"{n}{u}" for n, u in parts if n > 0][:2]
    return "".join(out) or "0c"


def _fight_rows(enc):
    """Contributor list for one encounter view; solo fights synthesize You."""
    allies = list(enc.get("allies") or [])
    if not allies and enc.get("total_damage"):
        allies = [{"name": "You", "damage": enc.get("total_damage", 0),
                   "dps": enc.get("dps", 0), "classes": None}]
    return allies


def compute_rows(snap, history, segment):
    """[(name, classes, damage, dps)] ranked by damage, plus fight label."""
    if segment == "current":
        enc = (snap or {}).get("encounter")
        if not enc:
            return [], "no encounter"
        rows = [(a.get("name") or "?", a.get("classes"),
                 a.get("damage", 0), a.get("dps", 0))
                for a in _fight_rows(enc)]
        foes = enc.get("foes") or []
        label = (f"{len(foes)} foes" if len(foes) > 1
                 else (enc.get("target") or "fight"))
        label = f"{label} · {enc.get('duration', 0):g}s"
    else:
        dmg, secs, cls = {}, {}, {}
        for enc in history or []:
            dur = enc.get("duration") or 0
            for a in _fight_rows(enc):
                n = a.get("name") or "?"
                dmg[n] = dmg.get(n, 0) + (a.get("damage") or 0)
                secs[n] = secs.get(n, 0) + dur
                cls.setdefault(n, a.get("classes"))
        rows = [(n, cls.get(n), d, round(d / secs[n], 1) if secs.get(n) else 0)
                for n, d in dmg.items()]
        label = f"last {len(history or [])} fights"
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows[:8], label


def timer_rows(snap):
    """TIMERS section: live countdowns, soonest first, red when short."""
    rows = []
    for t in ((snap or {}).get("timers") or [])[:6]:
        rem = t.get("remaining", 0)
        mins, secs = divmod(max(0, int(rem)), 60)
        clock = f"{mins}:{secs:02d}" if mins else f"{secs}s"
        color = RED if rem <= 5 else (GOLD if t.get("kind") == "raid" else INK)
        rows.append((t.get("name", "?")[:30], clock, color))
    return rows or [("no active timers", "", MUTED)]


def session_rows(snap):
    """SESSION section: [(left, right, color)]."""
    s = (snap or {}).get("session") or {}
    r = (snap or {}).get("rates") or {}

    def act(key):
        return (r.get(key) or {}).get("active_hr", 0)

    return [
        (f"kills {s.get('kills', 0)} · deaths {s.get('deaths', 0)}",
         f"{act('kills'):g}/hr", INK),
        (f"xp +{s.get('xp_percent', 0):g}%", f"{act('xp'):g}%/hr", INK),
        (f"coin {_fmt_coin(s.get('coin_copper', 0))}",
         f"{_fmt_coin(act('coin'))}/hr", INK),
        (f"crits {s.get('crits', 0)} · hit {s.get('hit_rate', 0):g}%",
         f"rune {_fmt(s.get('rune_absorbed', 0))}", MUTED),
    ]


def loot_rows(snap):
    """LOOT section: recent drops + best observed drop-rate mobs."""
    s = (snap or {}).get("session") or {}
    rows = [((" " + item)[:42], "", INK)
            for item in (s.get("loots") or [])[:4]]
    best = []
    for m in (snap or {}).get("mob_stats") or []:
        kills, drops = m.get("kills") or 0, m.get("loot_drops") or 0
        if kills > 0 and drops > 0:
            best.append((m.get("name") or "?", round(100 * drops / kills)))
    best.sort(key=lambda x: -x[1])
    for name, pct in best[:2]:
        rows.append((name[:28], f"{pct}% drops", MUTED))
    return rows or [("no loot yet", "", MUTED)]


def progress_rows(snap):
    """PROGRESS section: level, ding estimate, session clocks."""
    r = (snap or {}).get("rates") or {}
    lvl = (snap or {}).get("level")
    htl = r.get("hours_to_level")
    right = ""
    if htl:
        right = f"ding in ~{htl:g}h"
        if not r.get("hours_to_level_exact"):
            right += " (max)"
    return [
        (f"level {lvl if lvl is not None else '?'}", right, INK),
        (f"session {r.get('elapsed_hours', 0):g}h · "
         f"active {r.get('active_hours', 0):g}h", "", MUTED),
    ]


def section_summary(key, snap, history, segment):
    """One-liner shown on a COLLAPSED section header."""
    if key == "combat":
        return f"{(snap or {}).get('dps', 0):g} dps"
    if key == "session":
        s = (snap or {}).get("session") or {}
        r = (snap or {}).get("rates") or {}
        return (f"{s.get('kills', 0)}k · "
                f"{(r.get('xp') or {}).get('active_hr', 0):g}%/hr")
    if key == "timers":
        timers = (snap or {}).get("timers") or []
        if not timers:
            return "—"
        t = timers[0]
        return f"{t.get('name', '?')[:16]} {t.get('remaining', 0)}s"
    if key == "loot":
        loots = ((snap or {}).get("session") or {}).get("loots") or []
        return (loots[0][:22] if loots else "—")
    if key == "progress":
        r = (snap or {}).get("rates") or {}
        htl = r.get("hours_to_level")
        return f"~{htl:g}h to ding" if htl else "—"
    return ""

class OverlayMeter:
    def __init__(self) -> None:
        self.snap = None
        self.history = []
        st = self._load_state()
        self.mode = st.get("mode", "damage")          # damage | dps
        self.segment = st.get("segment", "current")   # current | last5
        self.compact = bool(st.get("compact", False))
        self.alpha = min(1.0, max(0.35, float(st.get("alpha", 0.90))))
        self.collapsed = {k: bool(st.get("collapsed", {}).get(k, False))
                          for k in SECTIONS}
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.alpha)
        self.root.configure(bg=BG)
        x, y = int(st.get("x", 60)), int(st.get("y", 140))
        self.root.geometry(f"{W}x{HEADER_H + ROW_H + HINT_H}+{x}+{y}")
        self._drag = None
        self._moved = False
        self._transparent = None
        self._sec_zones = []  # [(y0, y1, key)] rebuilt every render
        self._last_alert_id = 0
        self._alert_until = 0.0
        self._alert_text = ""

        self.canvas = tk.Canvas(self.root, width=W, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda _e: self.root.destroy())
        self.root.bind("<KeyPress>", self._key)

        threading.Thread(target=self._poll_char, daemon=True).start()
        threading.Thread(target=self._poll_encounters, daemon=True).start()
        threading.Thread(target=self._watch_game, daemon=True).start()
        self.root.after(300, self._render)

    # ---- persisted layout state -------------------------------------------
    def _load_state(self) -> dict:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps({
                "x": self.root.winfo_x(), "y": self.root.winfo_y(),
                "alpha": round(self.alpha, 2), "compact": self.compact,
                "collapsed": self.collapsed,
                "mode": self.mode, "segment": self.segment,
            }), encoding="utf-8")
        except Exception:
            pass

    # ---- interaction (only reachable while Scroll Lock is ON) -------------
    def _press(self, e) -> None:
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())
        self._moved = False
        try:
            self.root.focus_force()  # so c / +/- keys land here
        except Exception:
            pass

    def _motion(self, e) -> None:
        if self._drag:
            self._moved = True
            self.root.geometry(
                f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _release(self, e) -> None:
        if not self._moved:
            if e.y <= HEADER_H:
                if e.x < W // 2:
                    self.mode = "dps" if self.mode == "damage" else "damage"
                else:
                    self.segment = ("last5" if self.segment == "current"
                                    else "current")
            else:
                for y0, y1, key in self._sec_zones:
                    if y0 <= e.y <= y1:
                        self.collapsed[key] = not self.collapsed[key]
                        break
        self._drag = None
        self._save_state()

    def _key(self, e) -> None:
        ch = (e.char or "").lower()
        if ch == "c":
            self.compact = not self.compact
        elif ch in ("+", "="):
            self.alpha = min(1.0, self.alpha + 0.05)
            self.root.attributes("-alpha", self.alpha)
        elif ch in ("-", "_"):
            self.alpha = max(0.35, self.alpha - 0.05)
            self.root.attributes("-alpha", self.alpha)
        else:
            return
        self._save_state()

    def _set_click_through(self, enable: bool) -> None:
        if enable == self._transparent:
            return
        self._transparent = enable
        try:
            hwnd = (ctypes.windll.user32.GetParent(self.root.winfo_id())
                    or self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED
            if enable:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    # ---- data --------------------------------------------------------------
    def _poll_char(self) -> None:
        while True:
            try:
                with urllib.request.urlopen(API_CHAR, timeout=2) as r:
                    self.snap = json.loads(r.read().decode("utf-8"))
            except Exception:
                self.snap = None
            time.sleep(1.0)

    def _poll_encounters(self) -> None:
        while True:
            try:
                with urllib.request.urlopen(API_ENCS, timeout=3) as r:
                    d = json.loads(r.read().decode("utf-8"))
                self.history = d.get("encounters", d) if isinstance(d, dict) else d
            except Exception:
                pass
            time.sleep(5.0)

    def _watch_game(self) -> None:
        """Close the overlay when eqgame.exe exits (after it has been seen
        running at least once — launching the overlay first is fine)."""
        try:
            import psutil
        except ImportError:
            return
        seen = False
        while True:
            try:
                running = any((p.info.get("name") or "").lower() == "eqgame.exe"
                              for p in psutil.process_iter(["name"]))
            except Exception:
                running = seen  # scan hiccup: don't close on bad data
            if running:
                seen = True
            elif seen:
                self.root.after(0, self.root.destroy)
                return
            time.sleep(5)

    # ---- paint ---------------------------------------------------------
    def _sec_header(self, c, y, key, title, extra="") -> int:
        arrow = "v" if not self.collapsed[key] else ">"
        c.create_rectangle(0, y, W, y + SEC_H, fill=SEC_BG, width=0)
        c.create_text(6, y + SEC_H // 2, anchor="w", fill=GOLD,
                      font=("Consolas", 7, "bold"),
                      text=f"{arrow} {title}")
        summary = extra if not self.collapsed[key] else section_summary(
            key, self.snap, self.history, self.segment)
        if summary:
            c.create_text(W - 6, y + SEC_H // 2, anchor="e", fill=MUTED,
                          font=("Consolas", 7), text=summary[:34])
        self._sec_zones.append((y, y + SEC_H, key))
        return y + SEC_H

    def _text_rows(self, c, y, rows) -> int:
        for left, right, color in rows:
            c.create_text(8, y + TROW_H // 2, anchor="w", fill=color,
                          font=("Consolas", 8), text=left)
            if right:
                c.create_text(W - 6, y + TROW_H // 2, anchor="e", fill=color,
                              font=("Consolas", 8), text=right)
            y += TROW_H
        return y

    def _render(self) -> None:
        interactive = bool(ctypes.windll.user32.GetKeyState(VK_SCROLL) & 1)
        self._set_click_through(not interactive)
        c = self.canvas
        c.delete("all")
        self._sec_zones = []

        rows, label = compute_rows(self.snap, self.history, self.segment)
        s = (self.snap or {}).get("session") or {}
        r = (self.snap or {}).get("rates") or {}
        my_dps = (self.snap or {}).get("dps", 0)
        live = self.snap and self.snap.get("in_combat")

        # ---- header (always visible) ----
        y = HEADER_H
        c.create_rectangle(0, 0, W, HEADER_H, fill=HEADER_BG, width=0)
        if self.compact:
            xp_act = (r.get("xp") or {}).get("active_hr", 0)
            coin_act = (r.get("coin") or {}).get("active_hr", 0)
            header = (f"{my_dps:g}dps · {s.get('kills', 0)}k · "
                      f"{xp_act:g}%/hr · {_fmt_coin(coin_act)}/hr")
            c.create_text(6, HEADER_H // 2, anchor="w", fill=GOLD,
                          font=("Consolas", 9, "bold"), text=f"EQL {header}")
        else:
            mode_label = "Damage" if self.mode == "damage" else "DPS"
            c.create_text(8, HEADER_H // 2, anchor="w", fill=GOLD,
                          font=("Consolas", 9, "bold"),
                          text=f"{mode_label} · {label}"[:34])
            c.create_text(W - 8, HEADER_H // 2, anchor="e",
                          fill=HEAL if live else MUTED,
                          font=("Consolas", 9, "bold"), text=f"{my_dps:g}")

        # tracked-rule alert banner (+ chime once per alert)
        alerts = (self.snap or {}).get("alerts") or []
        if alerts:
            latest = alerts[-1]
            if latest.get("id", 0) > self._last_alert_id:
                self._last_alert_id = latest.get("id", 0)
                self._alert_until = time.time() + ALERT_BANNER_SECS
                self._alert_text = f"{latest.get('kind', '')}: {latest.get('text', '')}"
                if latest.get("sound"):
                    try:
                        import winsound
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    except Exception:
                        pass
        if time.time() < self._alert_until:
            c.create_rectangle(0, y, W, y + TROW_H, fill=GOLD, width=0)
            c.create_text(6, y + TROW_H // 2, anchor="w", fill=BG,
                          font=("Consolas", 8, "bold"),
                          text=self._alert_text[:44])
            y += TROW_H

        if not self.snap:
            c.create_text(8, y + TROW_H // 2, anchor="w", fill=RED,
                          font=("Consolas", 9),
                          text="companion offline (:8000)")
            y += TROW_H
        elif not self.compact:
            # ---- COMBAT ----
            y = self._sec_header(c, y, "combat", "COMBAT")
            if not self.collapsed["combat"]:
                if not rows:
                    c.create_text(8, y + TROW_H // 2, anchor="w", fill=MUTED,
                                  font=("Consolas", 9),
                                  text="waiting for combat…")
                    y += TROW_H
                total = sum(x[2] for x in rows) or 1
                top = rows[0][2] if rows else 1
                for i, (name, classes, dmg, dps) in enumerate(rows):
                    y0 = y + i * ROW_H
                    frac = (dmg / top) if top else 0
                    color = _class_color(classes, name)
                    c.create_rectangle(0, y0 + 1, max(2, int(W * frac)),
                                       y0 + ROW_H - 1, fill=color, width=0,
                                       stipple="gray50")
                    share = 100 * dmg / total
                    val = _fmt(dmg) if self.mode == "damage" else f"{dps:g}"
                    fg = BRIGHT if name == "You" else INK
                    c.create_text(6, y0 + ROW_H // 2, anchor="w", fill=fg,
                                  font=("Consolas", 9),
                                  text=f"{i + 1}. {name[:15]}")
                    c.create_text(W - 6, y0 + ROW_H // 2, anchor="e", fill=fg,
                                  font=("Consolas", 9),
                                  text=f"{val} ({share:.0f}%)")
                y += len(rows) * ROW_H
            # ---- TIMERS / SESSION / LOOT / PROGRESS ----
            y = self._sec_header(c, y, "timers", "TIMERS")
            if not self.collapsed["timers"]:
                y = self._text_rows(c, y, timer_rows(self.snap))
            y = self._sec_header(c, y, "session", "SESSION")
            if not self.collapsed["session"]:
                y = self._text_rows(c, y, session_rows(self.snap))
            y = self._sec_header(c, y, "loot", "LOOT")
            if not self.collapsed["loot"]:
                y = self._text_rows(c, y, loot_rows(self.snap))
            y = self._sec_header(c, y, "progress", "PROGRESS")
            if not self.collapsed["progress"]:
                y = self._text_rows(c, y, progress_rows(self.snap))

        hint_y = y + HINT_H // 2
        if interactive:
            c.create_text(6, hint_y, anchor="w", fill=GOLD,
                          font=("Consolas", 7),
                          text="MOVABLE · title=mode/segment · section=fold "
                               "· c=compact · ±=opacity · dbl-click closes")
        else:
            c.create_text(6, hint_y, anchor="w", fill=MUTED,
                          font=("Consolas", 7),
                          text="click-through · Scroll Lock ON to interact")
        height = y + HINT_H
        self.root.geometry(f"{W}x{height}")
        c.configure(height=height)
        self.root.after(500, self._render)


def _already_running() -> bool:
    """Named-mutex singleton: survives backend restarts losing the process
    handle (which used to allow a second overlay on the next toggle)."""
    ctypes.windll.kernel32.CreateMutexW(None, False, "EQLCompanionOverlayMutex")
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    if _already_running():
        raise SystemExit(0)
    OverlayMeter().root.mainloop()