"""Direct-HTTP wiki access — the no-Node fallback for the MCP server.

The MCP server is the enhanced path (structured eql_builds_* data); when it
is absent (not cloned, Node missing, disabled), these fetch the same wiki
pages over plain HTTP and extract text in the same line-per-block shape the
MCP extractor produces, so every downstream parser keeps working. Adopters
get wiki-grounded counsel with nothing but Python installed.
"""
import asyncio
import json
import logging
import urllib.parse
import urllib.request
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

API = "https://eqlwiki.com/api.php"
_BLOCK_TAGS = {"p", "div", "table", "tr", "td", "th", "li", "ul", "ol",
               "h1", "h2", "h3", "h4", "h5", "h6", "br", "caption"}


class _TextExtract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [ln.strip() for ln in raw.splitlines()]
        out, blanks = [], 0
        for ln in lines:
            blanks = blanks + 1 if not ln else 0
            if blanks <= 1:
                out.append(ln)
        return "\n".join(out).strip()


def _ssl_ctx():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "eql-companion"})
    with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx()) as r:
        return json.loads(r.read().decode("utf-8"))


async def fetch_page_text(title: str, max_characters: int = 40_000):
    """MediaWiki rendered page -> {'title','text'} (None if missing)."""
    def work():
        d = _get({"action": "parse", "page": title, "format": "json",
                  "prop": "text", "redirects": 1})
        if "parse" not in d:
            return None
        html = d["parse"]["text"]["*"]
        p = _TextExtract()
        p.feed(html)
        return {"title": d["parse"].get("title", title),
                "text": p.text()[:max_characters], "source": "http"}
    try:
        return await asyncio.to_thread(work)
    except Exception as e:
        logger.warning("HTTP wiki page %r failed: %s", title, e)
        return None


async def fetch_page_html(title: str):
    """Raw rendered HTML of a page (None if missing). The acquisition
    sections (Drops From / Sold by / quests / crafting) exist ONLY in
    rendered HTML — the {{Itempage}} template emits them, so raw wikitext
    lacks them entirely (insight from DavisChappins/eql-tooltip, MIT)."""
    def work():
        d = _get({"action": "parse", "page": title, "format": "json",
                  "prop": "text", "redirects": 1})
        if "parse" not in d:
            return None
        return d["parse"]["text"]["*"]
    try:
        return await asyncio.to_thread(work)
    except Exception as e:
        logger.warning("HTTP wiki html %r failed: %s", title, e)
        return None


async def search_pages(query: str, limit: int = 10) -> list:
    def work():
        d = _get({"action": "query", "list": "search", "srsearch": query,
                  "srlimit": limit, "format": "json"})
        return [{"title": r["title"]}
                for r in d.get("query", {}).get("search", [])]
    try:
        return await asyncio.to_thread(work)
    except Exception as e:
        logger.warning("HTTP wiki search %r failed: %s", query, e)
        return []


async def category_pages(category: str, limit: int = 50) -> list:
    def work():
        cm = category if category.startswith("Category:") else "Category:" + category
        d = _get({"action": "query", "list": "categorymembers",
                  "cmtitle": cm, "cmlimit": limit, "format": "json"})
        return [{"title": r["title"]}
                for r in d.get("query", {}).get("categorymembers", [])]
    try:
        return await asyncio.to_thread(work)
    except Exception as e:
        logger.warning("HTTP wiki category %r failed: %s", category, e)
        return []
