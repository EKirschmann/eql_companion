"""Compact always-on-top combat strip (click-through overlay).

Polls the companion backend (:8000) once per second and paints live DPS +
the current encounter over the game. While Scroll Lock is OFF the window is
CLICK-THROUGH — every click lands in the game; turn Scroll Lock ON to drag
it (double-click closes). Passive like the OCR calibrator: it reads the
HTTP API only and never touches the game process.

Run: python -m backend.overlay   (or the Overlay button in the web header)
"""
import ctypes
import json
import threading
import time
import tkinter as tk
import urllib.request

API = "http://localhost:8000/api/character"
POLL_SECONDS = 1.0
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
VK_SCROLL = 0x91

BG = "#12151a"
GOLD = "#c8aa6e"
BRIGHT = "#e7cd92"
MUTED = "#8b8577"
HEAL = "#1fb38c"
RED = "#d4574a"


class OverlayStrip:
    def __init__(self) -> None:
        self.snap = None
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.88)
        self.root.configure(bg=BG)
        self.root.geometry("+60+140")
        self._drag = None
        self._transparent = None

        self.dps = tk.Label(self.root, text="— DPS", fg=GOLD, bg=BG,
                            font=("Consolas", 18, "bold"))
        self.dps.pack(anchor="w", padx=12, pady=(8, 0))
        self.enc = tk.Label(self.root, text="no encounter", fg=BRIGHT, bg=BG,
                            font=("Consolas", 10))
        self.enc.pack(anchor="w", padx=12)
        self.group = tk.Label(self.root, text="", fg=MUTED, bg=BG,
                              font=("Consolas", 9), justify="left")
        self.group.pack(anchor="w", padx=12)
        self.hint = tk.Label(self.root, text="", fg=MUTED, bg=BG,
                             font=("Consolas", 7))
        self.hint.pack(anchor="w", padx=12, pady=(2, 6))

        for w in (self.root, self.dps, self.enc, self.group, self.hint):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<Double-Button-1>", lambda _e: self.root.destroy())

        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.root.after(300, self._render)

    # ---- window plumbing --------------------------------------------------
    def _drag_start(self, e) -> None:
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())

    def _drag_move(self, e) -> None:
        if self._drag:
            self.root.geometry(
                f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

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
        if enable:
            self.hint.configure(fg=MUTED,
                                text="click-through · Scroll Lock ON to move")
        else:
            self.hint.configure(fg=GOLD,
                                text="MOVABLE — drag me · double-click closes "
                                     "· Scroll Lock OFF resumes click-through")

    # ---- data -------------------------------------------------------------
    def _poll_loop(self) -> None:
        while True:
            try:
                with urllib.request.urlopen(API, timeout=2) as r:
                    self.snap = json.loads(r.read().decode("utf-8"))
            except Exception:
                self.snap = None
            time.sleep(POLL_SECONDS)

    # ---- paint ------------------------------------------------------------
    def _render(self) -> None:
        interactive = bool(ctypes.windll.user32.GetKeyState(VK_SCROLL) & 1)
        self._set_click_through(not interactive)
        s = self.snap
        if not s:
            self.dps.configure(text="companion offline", fg=RED)
            self.enc.configure(text="start the backend on :8000")
            self.group.configure(text="")
        else:
            self.dps.configure(text=f"{s.get('dps', 0):g} DPS",
                               fg=HEAL if s.get("in_combat") else GOLD)
            enc = s.get("encounter")
            if enc:
                foes = enc.get("foes") or []
                target = (f"{len(foes)} foes" if len(foes) > 1
                          else (enc.get("target") or "…"))
                self.enc.configure(
                    text=f"{target} · {enc.get('duration', 0):g}s · "
                         f"{enc.get('total_damage', 0):,} dmg")
                # group (4) / raid (8): ranked damage-meter rows
                allies = enc.get("allies") or []
                rows = [
                    f"{(a.get('name') or '?')[:14]:<14}{a.get('dps', 0):>8g}"
                    for a in allies[:8]
                ]
                self.group.configure(text=chr(10).join(rows))
            else:
                self.enc.configure(text="no encounter")
                self.group.configure(text="")
        self.root.after(500, self._render)


if __name__ == "__main__":
    OverlayStrip().root.mainloop()