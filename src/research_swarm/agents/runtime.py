"""Shared runtime: injected dependencies + helpers used by every agent."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from research_swarm.config import Settings
from research_swarm.llm import StructuredLLM
from research_swarm.models import Source
from research_swarm.providers.base import SearchProvider
from research_swarm.providers.fetch import PageFetcher


@dataclass
class Runtime:
    """Everything an agent needs, injected once and shared across branches."""

    settings: Settings
    llm: StructuredLLM
    search: SearchProvider
    fetcher: PageFetcher

    llm_semaphore: asyncio.Semaphore = field(init=False)
    search_semaphore: asyncio.Semaphore = field(init=False)
    _id_lock: asyncio.Lock = field(init=False)
    _source_counter: int = field(init=False, default=0)
    _url_ids: dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        limit = max(1, self.settings.max_concurrency)
        self.llm_semaphore = asyncio.Semaphore(limit)
        self.search_semaphore = asyncio.Semaphore(limit)
        self._id_lock = asyncio.Lock()

    # ---- LLM -------------------------------------------------------------
    async def structured(self, schema, *, system: str, user: str, temperature: float = 0.0):
        """Call the LLM under a global concurrency cap."""
        async with self.llm_semaphore:
            return await self.llm.structured(
                schema, system=system, user=user, temperature=temperature
            )

    async def text(self, *, system: str, user: str, temperature: float = 0.0) -> str:
        async with self.llm_semaphore:
            return await self.llm.text(system=system, user=user, temperature=temperature)

    # ---- search ----------------------------------------------------------
    async def search_queries(self, queries: list[str], *, max_results: int) -> list:
        """Run several searches concurrently, isolating failures per query."""
        queries = [q for q in dict.fromkeys(q.strip() for q in queries if q and q.strip())]
        if not queries:
            return []

        async def _one(query: str):
            async with self.search_semaphore:
                try:
                    return await self.search.search(query, max_results=max_results)
                except Exception:  # noqa: BLE001 - one bad query must not fail the run
                    return []

        results = await asyncio.gather(*(_one(q) for q in queries))
        flat = [hit for hits in results for hit in hits]
        for hit in flat:
            hit.extra.setdefault("provider", self.search.name)
        return flat

    # ---- source ids ------------------------------------------------------
    async def citation_ids(self, urls: list[str]) -> list[str]:
        """Return a stable citation id per URL.

        The registry is keyed by normalised URL, so when two parallel branches
        independently discover the same page they get the *same* id instead of
        two duplicate entries in the final report. Callers may still hold two
        Source objects with that shared id; de-duplicate at fan-in with
        :func:`dedupe_by_id`.
        """
        if not urls:
            return []
        async with self._id_lock:
            ids: list[str] = []
            for url in urls:
                key = normalize_url(url)
                source_id = self._url_ids.get(key)
                if source_id is None:
                    self._source_counter += 1
                    source_id = f"S{self._source_counter}"
                    self._url_ids[key] = source_id
                ids.append(source_id)
            return ids


def render_sources(sources: list[Source], *, max_chars_per_source: int = 1800) -> str:
    """Render sources into the machine-readable block agents (and the mock) parse."""
    blocks = []
    for source in sources:
        body = (source.content or source.snippet or "").strip()[:max_chars_per_source]
        blocks.append(f"### SOURCE {source.id} | {source.title} | {source.url}\n{body}")
    return "\n\n".join(blocks)


def normalize_url(url: str) -> str:
    url = url.strip()
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix) :]
            break
    if url.startswith("www."):
        url = url[4:]
    return url.rstrip("/").lower()


def dedupe_hits(hits: list) -> list:
    """Collapse duplicate URLs, keeping the first (highest-ranked) occurrence."""
    seen: set[str] = set()
    unique = []
    for hit in hits:
        key = normalize_url(hit.url)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def dedupe_by_id(items: list) -> list:
    """Keep the first object per ``id``, preserving order (used at fan-in)."""
    seen: set[str] = set()
    unique = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)
    return unique
