"""Offline search backend.

Returns deterministic, clearly-labelled synthetic results so the full graph -
search, read, cross-check, synthesize - can run with no key and no network.
"""

from __future__ import annotations

import re

from research_swarm.config import Settings
from research_swarm.providers.base import SearchHit

_ANGLES = [
    ("Overview", "review"),
    ("Analysis", "analysis"),
    ("Critique", "critique"),
    ("Data", "data"),
    ("Forecast", "forecast"),
]


def slugify(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-") or "topic"


class MockSearchProvider:
    name = "mock"

    def __init__(self, settings: Settings | None = None):
        self._settings = settings

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        slug = slugify(query)
        hits: list[SearchHit] = []
        for label, path in _ANGLES[: max(1, min(max_results, len(_ANGLES)))]:
            hits.append(
                SearchHit(
                    url=f"https://mock.example/{slug}/{path}",
                    title=f"{query.strip()[:70]} - {label}",
                    snippet=(
                        f"A {label.lower()} of {query.strip()} based on published sources. "
                        "(offline mock result)"
                    ),
                    published="2026-01-01",
                    score=round(1.0 - 0.1 * len(hits), 2),
                )
            )
        return hits

    async def aclose(self) -> None:  # pragma: no cover
        return None
