"""Search-provider contract and factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from research_swarm.config import Settings


class SearchError(RuntimeError):
    """Raised when a search backend fails after retries."""


@dataclass
class SearchHit:
    """A raw search result, before it becomes a citable Source."""

    url: str
    title: str = ""
    snippet: str = ""
    published: str | None = None
    score: float | None = None
    content: str = ""
    extra: dict = field(default_factory=dict)


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]: ...

    async def aclose(self) -> None: ...


def build_search_provider(settings: Settings) -> SearchProvider:
    """Instantiate the configured search backend."""
    provider = settings.resolve_search_provider()

    if provider == "tavily":
        from research_swarm.providers.tavily import TavilyProvider

        return TavilyProvider(settings)
    if provider == "exa":
        from research_swarm.providers.exa import ExaProvider

        return ExaProvider(settings)
    if provider == "serpapi":
        from research_swarm.providers.serpapi import SerpApiProvider

        return SerpApiProvider(settings)
    if provider == "gemini":
        from research_swarm.providers.gemini_grounding import GeminiGroundingProvider

        return GeminiGroundingProvider(settings)
    if provider == "mock":
        from research_swarm.providers.mock import MockSearchProvider

        return MockSearchProvider(settings)

    raise SearchError(
        f"Unknown search provider {provider!r}. "
        "Choose one of: tavily, exa, serpapi, gemini, mock."
    )
