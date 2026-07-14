"""Details-style damage meter overlay (always-on-top, click-through).

Ranked, class-colored bars over the game — like the WoW Details! addon:
each contributor gets a bar proportional to the leader, with damage done,
DPS, and share of the group total. Two modes (Damage | DPS) and two
segments (this fight | last 5 fights).

While Scroll Lock is OFF the window is CLICK-THROUGH — every click lands in
the game. Scroll Lock ON makes it movable and interactive: click the title
to switch mode, the segment label to switch segment, drag to move,
double-click to close. Passive: reads the HTTP API only.

The overlay is a singleton (a second launch exits immediately) and closes
itself when the game exits — no orphan meters after you camp for the night.

Run: python -m backend.overlay   (or the Overlay button in the web header)
"""
import colorsys
import ctypes
import json
import threading
import time
import tkinter as tk
import urllib.request

API_CHAR = "http://localhost:8000/api/character"
API_ENCS = "http://localhost:8000/api/encounters?limit=5"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
VK_SCROLL = 0x91

BG = "#12151a"
HEADER_BG = "#1b1f26"
GOLD = "#c8aa6e"
BRIGHT = "#e7cd92"
INK = "#e6dEca"
MUTED = "#8b8577"
HEAL = "#1fb38c"
RED = "#d4574a"

W = 300
HEADER_H = 22
ROW_H = 17
HINT_H = 13

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


class OverlayMeter:
    def __init__(self) -> None:
        self.snap = None
        self.history = []
        self.mode = "damage"        # damage | dps
        self.segment = "current"    # current | last5
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.90)
        self.root.configure(bg=BG)
        self.root.geometry(f"{W}x{HEADER_H + ROW_H + HINT_H}+60+140")
        self._drag = None
        self._moved = False
        self._transparent = None

        self.canvas = tk.Canvas(self.root, width=W, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda _e: self.root.destroy())

        threading.Thread(target=self._poll_char, daemon=True).start()
        threading.Thread(target=self._poll_encounters, daemon=True).start()
        threading.Thread(target=self._watch_game, daemon=True).start()
        self.root.after(300, self._render)

    # ---- interaction (only reachable while Scroll Lock is ON) -------------
    def _press(self, e) -> None:
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())
        self._moved = False

    def _motion(self, e) -> None:
        if self._drag:
            self._moved = True
            self.root.geometry(
                f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _release(self, e) -> None:
        if not self._moved and e.y <= HEADER_H:
            if e.x < W // 2:
                self.mode = "dps" if self.mode == "damage" else "damage"
            else:
                self.segment = "last5" if self.segment == "current" else "current"
        self._drag = None

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
    def _render(self) -> None:
        interactive = bool(ctypes.windll.user32.GetKeyState(VK_SCROLL) & 1)
        self._set_click_through(not interactive)
        c = self.canvas
        c.delete("all")

        rows, label = compute_rows(self.snap, self.history, self.segment)
        n = max(1, len(rows))
        height = HEADER_H + n * ROW_H + HINT_H
        self.root.geometry(f"{W}x{height}")
        c.configure(height=height)

        # header
        c.create_rectangle(0, 0, W, HEADER_H, fill=HEADER_BG, width=0)
        mode_label = "Damage" if self.mode == "damage" else "DPS"
        live = self.snap and self.snap.get("in_combat")
        c.create_text(8, HEADER_H // 2, anchor="w", fill=GOLD,
                      font=("Consolas", 9, "bold"),
                      text=f"{mode_label} · {label}")
        my_dps = (self.snap or {}).get("dps", 0)
        c.create_text(W - 8, HEADER_H // 2, anchor="e",
                      fill=HEAL if live else MUTED,
                      font=("Consolas", 9, "bold"), text=f"{my_dps:g}")

        if not self.snap:
            c.create_text(8, HEADER_H + ROW_H // 2, anchor="w", fill=RED,
                          font=("Consolas", 9), text="companion offline (:8000)")
        elif not rows:
            c.create_text(8, HEADER_H + ROW_H // 2, anchor="w", fill=MUTED,
                          font=("Consolas", 9), text="waiting for combat…")

        total = sum(r[2] for r in rows) or 1
        top = rows[0][2] if rows else 1
        for i, (name, classes, dmg, dps) in enumerate(rows):
            y0 = HEADER_H + i * ROW_H
            frac = (dmg / top) if top else 0
            color = _class_color(classes, name)
            c.create_rectangle(0, y0 + 1, max(2, int(W * frac)), y0 + ROW_H - 1,
                               fill=color, width=0, stipple="gray50")
            share = 100 * dmg / total
            val = _fmt(dmg) if self.mode == "damage" else f"{dps:g}"
            fg = BRIGHT if name == "You" else INK
            c.create_text(6, y0 + ROW_H // 2, anchor="w", fill=fg,
                          font=("Consolas", 9),
                          text=f"{i + 1}. {name[:15]}")
            c.create_text(W - 6, y0 + ROW_H // 2, anchor="e", fill=fg,
                          font=("Consolas", 9),
                          text=f"{val} ({share:.0f}%)")

        hint_y = HEADER_H + n * ROW_H + HINT_H // 2
        if interactive:
            c.create_text(6, hint_y, anchor="w", fill=GOLD, font=("Consolas", 7),
                          text="MOVABLE · click title=mode · right side=segment "
                               "· dbl-click closes · ScrLk OFF=click-through")
        else:
            c.create_text(6, hint_y, anchor="w", fill=MUTED, font=("Consolas", 7),
                          text="click-through · Scroll Lock ON to move/switch")
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
