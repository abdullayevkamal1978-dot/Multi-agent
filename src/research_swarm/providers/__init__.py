"""Pluggable web-search backends, plus the async page reader."""

from research_swarm.providers.base import (
    SearchError,
    SearchHit,
    SearchProvider,
    build_search_provider,
)
from research_swarm.providers.fetch import PageFetcher, extract_text

__all__ = [
    "PageFetcher",
    "SearchError",
    "SearchHit",
    "SearchProvider",
    "build_search_provider",
    "extract_text",
]
