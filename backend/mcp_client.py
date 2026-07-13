"""Stdio JSON-RPC client for the EQL MCP server (everquest-legends-mcp).

The server is a Node process speaking MCP over stdio. We keep one process
alive, guard calls with a lock, and fail soft: helpers return None when the
server, Node, or the wiki is unavailable so callers can degrade gracefully.

Server setup (one-time):
    git clone https://github.com/Sergeantfirstclassvincetoxicumnegrum35/everquest-legends-mcp
    cd everquest-legends-mcp && npm install    # builds dist/ via prepare
Then point settings.mcp_server_dir at the clone (see .env).
"""
import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import settings

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPClient:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self._lock = asyncio.Lock()
        self._id = 0

    def _server_command(self) -> Optional[List[str]]:
        entry = Path(settings.mcp_server_dir) / "dist" / "index.js"
        if not entry.exists():
            return None
        return [settings.mcp_node_path, str(entry)]

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, obj: Dict[str, Any]) -> None:
        self.process.stdin.write(json.dumps(obj) + "\n")
        self.process.stdin.flush()

    async def _read_response(self, timeout: float = 30.0) -> Dict[str, Any]:
        line = await asyncio.wait_for(
            asyncio.to_thread(self.process.stdout.readline), timeout)
        if not line:
            raise RuntimeError("MCP server closed its stdout")
        return json.loads(line)

    async def _ensure_process(self) -> bool:
        if self.process and self.process.poll() is None:
            return True
        cmd = self._server_command()
        if not cmd:
            logger.warning("MCP server not found under %s (clone + npm install it)",
                           settings.mcp_server_dir)
            return False
        try:
            self.process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
            self._send({"jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
                        "params": {"protocolVersion": MCP_PROTOCOL_VERSION,
                                   "capabilities": {},
                                   "clientInfo": {"name": "eql-companion", "version": "0.2"}}})
            await self._read_response()
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            logger.info("MCP server started: %s", " ".join(cmd))
            return True
        except Exception as e:
            logger.warning("MCP server failed to start: %s", e)
            self._kill()
            return False

    async def call_tool(self, name: str, arguments: Dict[str, Any],
                        timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Call an MCP tool; returns its structuredContent or None on failure."""
        if not settings.mcp_enabled:
            return None
        async with self._lock:
            if not await self._ensure_process():
                return None
            try:
                req_id = self._next_id()
                self._send({"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                            "params": {"name": name, "arguments": arguments}})
                while True:  # skip any notifications interleaved by the server
                    resp = await self._read_response(timeout)
                    if resp.get("id") == req_id:
                        break
                if "error" in resp:
                    logger.warning("MCP tool %s error: %s", name, resp["error"])
                    return None
                result = resp.get("result", {})
                if result.get("isError"):
                    logger.warning("MCP tool %s returned isError", name)
                    return None
                return result.get("structuredContent") or result
            except Exception as e:
                logger.warning("MCP call %s failed: %s", name, e)
                self._kill()
                return None

    def _kill(self) -> None:
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass
        self.process = None

    async def close(self) -> None:
        self._kill()

    # ---- convenience wrappers ------------------------------------------
    async def wiki_page(self, title: str, max_characters: int = 40_000) -> Optional[dict]:
        sc = await self.call_tool(
            "eql_wiki_page", {"title": title, "maxCharacters": max_characters})
        page = (sc or {}).get("page")
        if page:
            return page
        # no MCP server (not cloned / Node missing / disabled): plain HTTP
        from backend.wiki_http import fetch_page_text
        return await fetch_page_text(title, max_characters)

    async def wiki_search(self, query: str, limit: int = 10) -> List[dict]:
        sc = await self.call_tool("eql_wiki_search", {"query": query, "limit": limit})
        if sc:
            return sc.get("results", [])
        from backend.wiki_http import search_pages
        return await search_pages(query, limit)

    async def wiki_category_pages(self, category: str, limit: int = 50) -> List[dict]:
        sc = await self.call_tool(
            "eql_wiki_category_pages", {"category": category, "limit": limit})
        if sc:
            return sc.get("pages", [])
        from backend.wiki_http import category_pages
        return await category_pages(category, limit)


_mcp_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client