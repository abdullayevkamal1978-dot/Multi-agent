"""Async page reader: fetch a URL and reduce it to readable text.

Deliberately dependency-light (no trafilatura/readability) so the project
installs fast; the extractor is a conservative HTML-to-text reducer that
drops script/style/nav noise and keeps block structure.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import urllib.robotparser
from urllib.parse import urlsplit, urlunsplit
from html.parser import HTMLParser
from pathlib import Path

from research_swarm.config import Settings
from research_swarm.providers.http import get_client, request

_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "canvas",
    "head",
    "nav",
    "footer",
    "header",
    "form",
    "iframe",
    "template",
    "aside",
}
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "section", "article", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "td", "th", "ul", "ol",
}
_WHITESPACE_RE = re.compile(r"[ \t\u00a0]+")
_BLANKS_RE = re.compile(r"\n{3,}")
_ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_ROBOTS_LOCK = asyncio.Lock()


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._chunks: list[str] = []
        self.title = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS and not self._skip_depth:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS and not self._skip_depth:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip_depth:
            return
        if data and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = _WHITESPACE_RE.sub(" ", raw)
        raw = "\n".join(line.strip() for line in raw.splitlines())
        return _BLANKS_RE.sub("\n\n", raw).strip()


def extract_text(html: str) -> tuple[str, str]:
    """Return ``(title, text)`` for an HTML document."""
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup is normal on the web
        pass
    title = _WHITESPACE_RE.sub(" ", parser.title).strip()
    if not title:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = _WHITESPACE_RE.sub(" ", match.group(1)).strip() if match else ""
    return title, parser.text()


class PageFetcher:
    """Fetches pages concurrently, with an on-disk cache."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrency))
        self._cache_dir = Path(settings.cache_dir) / "pages"
        self._memory: dict[str, tuple[str, str]] = {}

    # ---- caching ---------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self._cache_dir / f"{digest}.json"

    def _read_cache(self, url: str) -> tuple[str, str] | None:
        if url in self._memory:
            return self._memory[url]
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            value = (payload.get("title", ""), payload.get("text", ""))
            self._memory[url] = value
            return value
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, url: str, value: tuple[str, str]) -> None:
        self._memory[url] = value
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(url).write_text(
                json.dumps({"url": url, "title": value[0], "text": value[1]}),
                encoding="utf-8",
            )
        except OSError:
            pass

    async def _allowed_by_robots(self, url: str) -> bool:
        """Honor the origin's robots policy; fail closed when policy cannot be read."""
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return False
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        async with _ROBOTS_LOCK:
            if origin not in _ROBOTS_CACHE:
                robots_url = origin + "/robots.txt"
                try:
                    response = await request(
                        "GET", robots_url, settings=self._settings, max_attempts=1
                    )
                    parser = urllib.robotparser.RobotFileParser()
                    parser.set_url(robots_url)
                    parser.parse(response.text.splitlines())
                    _ROBOTS_CACHE[origin] = parser
                except Exception:
                    # A 404 means no policy; other failures are conservatively blocked.
                    # The shared request helper raises on 404, so explicitly distinguish it.
                    try:
                        response = await get_client(self._settings).get(robots_url)
                        if response.status_code == 404:
                            _ROBOTS_CACHE[origin] = None
                        elif response.is_success:
                            parser = urllib.robotparser.RobotFileParser()
                            parser.set_url(robots_url)
                            parser.parse(response.text.splitlines())
                            _ROBOTS_CACHE[origin] = parser
                        else:
                            return False
                    except Exception:
                        return False
            parser = _ROBOTS_CACHE[origin]
        return parser is None or parser.can_fetch("research-swarm", url)

    async def is_allowed_by_robots(self, url: str) -> bool:
        """Expose the same robots gate to providers that return page text."""
        if urlparse_host(url).endswith("mock.example"):
            return True
        return await self._allowed_by_robots(url)

    # ---- fetching --------------------------------------------------------
    async def fetch(self, url: str) -> tuple[str, str, str | None]:
        """Return ``(title, text, error)``. Errors never raise."""
        if urlparse_host(url).endswith("mock.example"):
            title, text = _synthetic_page(url)
            self._write_cache(url, (title, text))
            return title, text, None

        if not await self.is_allowed_by_robots(url):
            return "", "", "blocked by robots.txt (or robots policy unavailable)"

        cached = self._read_cache(url)
        if cached is not None:
            return cached[0], cached[1], None

        async with self._semaphore:
            try:
                response = await request("GET", url, settings=self._settings, max_attempts=2)
            except Exception as exc:  # noqa: BLE001 - report, don't crash the run
                return "", "", f"{type(exc).__name__}: {exc}"

        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type and content_type:
            return "", "", f"unsupported content-type: {content_type}"

        title, text = extract_text(response.text)
        text = text[: self._settings.max_content_chars * 4]
        self._write_cache(url, (title, text))
        return title, text, None


def urlparse_host(url: str) -> str:
    match = re.match(r"https?://([^/?#]+)", url, re.I)
    return match.group(1).lower() if match else ""


def _synthetic_page(url: str) -> tuple[str, str]:
    """Deterministic offline page body for mock.example URLs."""
    parts = [p for p in url.split("/") if p and p not in ("https:", "http:", "mock.example")]
    topic = parts[0].replace("-", " ") if parts else "the topic"
    angle = parts[1] if len(parts) > 1 else "overview"
    title = f"{topic.title()} - {angle.title()}"
    paragraphs = [
        f"This document examines {topic} from a {angle} perspective.",
        (
            f"Reported figures around {topic} vary by source and methodology, which is a "
            "common cause of apparent disagreement between publications."
        ),
        (
            "The evidence presented here is generated offline for demonstration purposes "
            "and must not be treated as a real finding."
        ),
    ]
    return title, "\n\n".join(paragraphs)
