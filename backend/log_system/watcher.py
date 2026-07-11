"""Tail the active EQL log file and emit parsed events.

Polling tail (0.4s) rather than watchdog: single-file polling is cheap,
and unlike directory watchers it behaves identically on all Windows
filesystems and network drives. Reads in binary and tracks a byte
offset so partial lines and UTF-8 edge bytes never corrupt parsing.
"""
import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, Optional

from backend.log_system.parser import parse_line, extract_character_from_filename
from backend.log_system import events as ev

logger = logging.getLogger(__name__)

SEED_BYTES = 1024 * 1024  # how much history to replay on startup for initial state


def discover_log_file(log_dir: Path, character_name: Optional[str] = None) -> Optional[Path]:
    """Pick the log to watch: the named character's file, else most recent."""
    candidates = sorted(log_dir.glob("eqlog_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    if character_name:
        for p in candidates:
            name, _ = extract_character_from_filename(p)
            if name and name.lower() == character_name.lower():
                return p
    return candidates[0]


class LogWatcher:
    def __init__(
        self,
        path: Path,
        on_event: Callable[[ev.LogEvent, bool], Awaitable[None]],
        poll_interval: float = 0.4,
    ):
        self.path = path
        self.on_event = on_event  # (event, live) -> awaitable
        self.poll = poll_interval
        self.character_name, self.server = extract_character_from_filename(path)
        self._offset = 0
        self._pending = b""
        self._running = False

    async def seed(self) -> None:
        """Replay the tail of the file (no broadcasting) to build initial state."""
        try:
            size = self.path.stat().st_size
        except OSError:
            logger.warning(f"Log file not found yet: {self.path}")
            return
        start = max(0, size - SEED_BYTES)
        with open(self.path, "rb") as f:
            f.seek(start)
            data = f.read(size - start)
        lines = data.split(b"\n")
        if start > 0 and lines:
            lines = lines[1:]  # drop the partial first line
        for bline in lines:
            line = bline.decode("utf-8", errors="replace")
            event = parse_line(line, self.character_name)
            if event:
                await self.on_event(event, False)
        self._offset = size
        logger.info(f"Seeded from {self.path.name} ({size - start} bytes)")

    async def run(self) -> None:
        self._running = True
        logger.info(f"Watching {self.path}")
        while self._running:
            try:
                size = self.path.stat().st_size
            except OSError:
                await asyncio.sleep(2.0)
                continue

            if size < self._offset:  # rotated/truncated
                logger.info("Log truncated — restarting from top")
                self._offset = 0
                self._pending = b""

            if size > self._offset:
                with open(self.path, "rb") as f:
                    f.seek(self._offset)
                    chunk = f.read(size - self._offset)
                self._offset = size
                data = self._pending + chunk
                lines = data.split(b"\n")
                self._pending = lines.pop()  # last element is "" or a partial line
                for bline in lines:
                    line = bline.decode("utf-8", errors="replace")
                    event = parse_line(line, self.character_name)
                    if event:
                        try:
                            await self.on_event(event, True)
                        except Exception:
                            logger.exception("on_event handler failed")

            await asyncio.sleep(self.poll)

    def stop(self) -> None:
        self._running = False
