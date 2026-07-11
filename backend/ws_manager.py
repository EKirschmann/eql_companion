"""WebSocket connection manager — broadcasts log events and state to clients."""
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)
        logger.info(f"WS client connected ({len(self.connections)} total)")

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)
        logger.info(f"WS client disconnected ({len(self.connections)} total)")

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self.connections:
            return
        payload = json.dumps(message, default=str)
        dead: list[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = WSManager()
