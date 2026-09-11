"""Web tools: keyless web search (DuckDuckGo) and page reading.

``web_search`` needs no API key. ``browser_open`` fetches readable text with
the stdlib and asks the UI (via the ``on_open`` callback) to show the page
in the embedded browser tab.
"""

from __future__ import annotations

import html as _html
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


# -- DuckDuckGo HTML parsing ---------------------------------------------
class _DDGParser(HTMLParser):
    """Extract (title, url, snippet) triples from DDG html results."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict] = []
        self._cur: dict | None = None
        self._in_title = False
        self._in_snippet = False
        self._snippet_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs = dict(attrs)
        cls = attrs.get("class", "")
        if tag == "a" and "result__a" in cls:
            self._cur = {"title": "", "url": _clean_ddg_url(attrs.get("href", "")), "snippet": ""}
            self._in_title = True
        elif tag in ("div", "a") and "result__snippet" in cls and self._cur is not None:
            self._in_snippet = True
            self._snippet_tag = tag

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        elif tag == getattr(self, "_snippet_tag", None) and self._in_snippet:
            self._in_snippet = False
            if self._cur and self._cur["url"]:
                self._cur["title"] = self._cur["title"].strip()
                self._cur["snippet"] = re.sub(r"\s+", " ", self._cur["snippet"]).strip()
                self.results.append(self._cur)
            self._cur = None

    def handle_data(self, data: str) -> None:
        if self._cur is None:
            return
        if self._in_title:
            self._cur["title"] += data
        elif self._in_snippet:
            self._cur["snippet"] += data


def _clean_ddg_url(href: str) -> str:
    """DDG wraps links as //duckduckgo.com/l/?uddg=<encoded>."""
    if "uddg=" in href:
        try:
            return urllib.parse.unquote(href.split("uddg=", 1)[1].split("&")[0])
        except Exception:
            pass
    if href.startswith("//"):
        return "https:" + href
    return href


def web_search(query: str, count: int = 6) -> str:
    """Search the web (DuckDuckGo, no API key). Returns top results."""
    query = (query or "").strip()
    if not query:
        return "Empty search query."
    results: list[dict] = []
    try:
        data = urllib.parse.urlencode({"q": query}).encode()
        req = urllib.request.Request(
            "https://html.duckduckgo.com/html/", data=data, headers=_UA
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            parser = _DDGParser()
            parser.feed(resp.read().decode("utf-8", errors="replace"))
            results = parser.results
    except Exception as exc:
        results = []
        err = f" (html endpoint failed: {exc})"
    else:
        err = ""
    if not results:
        # Fallback: DDG instant-answer API (sparse but keyless).
        try:
            url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
                {"q": query, "format": "json", "no_html": 1}
            )
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=_UA), timeout=15
            ) as resp:
                import json

                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            abstract = payload.get("AbstractText", "")
            if abstract:
                src = payload.get("AbstractURL", "")
                return f"1. {abstract} ({src})"
        except Exception:
            pass
        return f"No web results found for '{query}'.{err}"
    lines = []
    for i, r in enumerate(results[: max(1, count)], 1):
        lines.append(f"{i}. {r['title']}\n   {r['snippet']}\n   {r['url']}")
    return "\n".join(lines)


# -- readable page text ----------------------------------------------------
class _TextExtractor(HTMLParser):
    """Pull readable text out of HTML; skip scripts, styles, nav junk."""

    _KEEP = {"p", "h1", "h2", "h3", "h4", "li", "td", "th", "blockquote", "pre"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._keep = 0
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip += 1
        elif tag in self._KEEP:
            self._keep += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = max(0, self._skip - 1)
        elif tag in self._KEEP:
            self._keep = max(0, self._keep - 1)
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip or not self._keep:
            return
        text = _html.unescape(data).strip()
        if text:
            self._chunks.append(text + " ")

    def text(self, limit: int = 6000) -> str:
        raw = re.sub(r"[ \t]+", " ", "".join(self._chunks))
        raw = re.sub(r"\n\s*\n+", "\n\n", raw).strip()
        return raw[:limit]


def fetch_page_text(url: str, limit: int = 6000) -> str:
    """Download *url* and return readable text (stdlib only)."""
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype:
                return f"URL is not an HTML page (Content-Type: {ctype})."
            raw = resp.read(2_000_000).decode("utf-8", errors="replace")
    except Exception as exc:
        return f"Couldn't open {url}: {exc}"
    extractor = _TextExtractor()
    try:
        extractor.feed(raw)
    except Exception:
        pass
    text = extractor.text(limit)
    return text or "Page had no readable text."


def make_browser_open_tool(on_open) -> "Tool":
    """Build the ``browser_open`` tool.

    *on_open* is a callable(url) the UI supplies; it loads the URL in the
    embedded browser tab (called from the worker thread — the UI must hop
    to the main thread itself). Returns page text for the model either way.
    """
    from . import Tool

    def browser_open(url: str) -> str:
        url = (url or "").strip()
        if not url:
            return "Empty URL."
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = "https://" + url
        try:
            on_open(url)
            shown = "Opened in the app's browser tab."
        except Exception as exc:
            shown = f"Couldn't show in the embedded browser ({exc}); text below."
        return f"{shown}\n\nPage text:\n{fetch_page_text(url)}"

    return Tool(
        name="browser_open",
        description=(
            "Open a URL in the app's embedded browser tab AND get its readable "
            "text back. Use after web_search to actually read a promising result."
        ),
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full URL to open"}},
            "required": ["url"],
        },
        func=browser_open,
    )


WEB_SEARCH_TOOL_PARAMS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query"},
        "count": {
            "type": "integer",
            "description": "How many results (default 6)",
            "default": 6,
        },
    },
    "required": ["query"],
}
