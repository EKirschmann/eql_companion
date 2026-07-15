"""Live position via screen OCR.

Reads the small on-screen region where the in-game map shows:
    X: -76
    Y: -3
    Z: 4
    Befallen

Loop: every ~1s, if eqgame.exe is running and OCR is enabled, grab the
configured screen rectangle (mss), upscale 3x (PIL), OCR it with RapidOCR
(ONNX PaddleOCR — the Windows built-in engine drops short lines like
"Z: 4"), parse X/Y/Z, and push the position into the tracker + WebSocket.
Passive screen reading only — never touches the game process.

Region + enabled flag live in data/ocr_config.json; the tkinter calibrator
(backend/ocr_overlay.py) writes the same file.
"""
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("data") / "ocr_config.json"
DEFAULT_CONFIG = {"left": 100, "top": 100, "width": 240, "height": 130, "enabled": False}
GAME_PROCESS = "eqgame.exe"

try:
    import mss  # noqa: F401
    import numpy as np
    import psutil
    from PIL import Image
    try:
        from rapidocr_onnxruntime import RapidOCR   # Python <= 3.12
        _OCR_V2 = False
    except ImportError:
        from rapidocr import RapidOCR               # successor pkg, 3.13+
        _OCR_V2 = True
    HAS_DEPS = True
    _IMPORT_ERROR = None
except ImportError as e:  # keep the app booting without OCR extras
    HAS_DEPS = False
    _IMPORT_ERROR = str(e)

_engine = None


def _get_engine():
    """RapidOCR loads its ONNX models on first use (~1s) — do it lazily."""
    global _engine
    if _engine is None:
        _engine = RapidOCR()
    return _engine

RE_X = re.compile(r"X\s*[:;.,]?\s*(-?\d+)", re.IGNORECASE)
RE_Y = re.compile(r"Y\s*[:;.,]?\s*(-?\d+)", re.IGNORECASE)
RE_Z = re.compile(r"Z\s*[:;.,]?\s*(-?\d+)", re.IGNORECASE)


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **cfg}
    except (OSError, ValueError):
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def parse_loc_text(text: str) -> Optional[dict]:
    """Extract x/y/z (+ trailing zone words) from OCR output."""
    mx, my, mz = RE_X.search(text), RE_Y.search(text), RE_Z.search(text)
    if not (mx and my and mz):
        return None
    remainder = RE_Z.sub("", RE_Y.sub("", RE_X.sub("", text)))
    zone_words = [w for w in re.findall(r"[A-Za-z'][A-Za-z']+", remainder)
                  if w.lower() not in ("x", "y", "z")]
    return {
        "x": float(mx.group(1)),
        "y": float(my.group(1)),
        "z": float(mz.group(1)),
        "zone_text": " ".join(zone_words) or None,
    }


def _capture_and_ocr(region: dict) -> str:
    """Capture the region and OCR it (runs in a worker thread — blocking CPU)."""
    import mss as _mss
    with _mss.mss() as sct:
        shot = sct.grab({"left": region["left"], "top": region["top"],
                         "width": region["width"], "height": region["height"]})
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    if _OCR_V2:
        out = _get_engine()(np.array(img))
        return "\n".join(list(getattr(out, "txts", None) or []))
    result, _elapsed = _get_engine()(np.array(img))
    return "\n".join(r[1] for r in (result or []))


async def ocr_region(region: dict) -> str:
    return await asyncio.to_thread(_capture_and_ocr, region)


class OcrWatcher:
    def __init__(self, tracker, ws_manager):
        self.tracker = tracker
        self.ws_manager = ws_manager
        self._running = False
        self._game_running = False
        self._game_checked = 0.0
        self.last_text: Optional[str] = None
        self.last_ok: Optional[str] = None
        self.error: Optional[str] = None

    def game_running(self) -> bool:
        """Is eqgame.exe alive? (cached 5s — process scans aren't free)"""
        if not HAS_DEPS:
            return False
        now = time.monotonic()
        if now - self._game_checked > 5.0:
            self._game_checked = now
            self._game_running = any(
                p.info["name"] and p.info["name"].lower() == GAME_PROCESS
                for p in psutil.process_iter(["name"]))
        return self._game_running

    def status(self) -> dict:
        cfg = load_config()
        return {
            "deps_ok": HAS_DEPS,
            "deps_error": _IMPORT_ERROR,
            "enabled": cfg["enabled"],
            "region": {k: cfg[k] for k in ("left", "top", "width", "height")},
            "game_running": self.game_running(),
            "last_text": self.last_text,
            "last_ok": self.last_ok,
            "position": self.tracker.position,
            "error": self.error,
        }

    async def run(self) -> None:
        if not HAS_DEPS:
            logger.warning(f"OCR disabled — missing deps: {_IMPORT_ERROR}")
            return
        self._running = True
        logger.info("OCR watcher started")
        while self._running:
            cfg = load_config()
            if not cfg["enabled"] or not self.game_running():
                await asyncio.sleep(2.0)
                continue
            try:
                text = await ocr_region(cfg)
                self.last_text = text.strip() or None
                parsed = parse_loc_text(text) if text else None
                if parsed:
                    self.error = None
                    self.last_ok = time.strftime("%H:%M:%S")
                    # The in-game map window labels the /loc NORTH-SOUTH value
                    # as "X:" and EAST-WEST as "Y:" (classic EQ axis confusion),
                    # so swap: window-X is our y, window-Y is our x. Verified
                    # against "The Broken Stair" landmark in Befallen.
                    self.tracker.position = {
                        "x": parsed["y"], "y": parsed["x"], "z": parsed["z"],
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                    await self.ws_manager.broadcast(
                        {"type": "state", "data": self.tracker.snapshot()})
            except Exception as e:
                self.error = str(e)[:200]
                logger.warning(f"OCR tick failed: {self.error}")
            await asyncio.sleep(1.0)

    def stop(self) -> None:
        self._running = False
