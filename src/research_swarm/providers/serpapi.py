"""SerpAPI backend (https://serpapi.com) - Google SERP results as JSON."""

from __future__ import annotations

from research_swarm.config import Settings
from research_swarm.providers.base import SearchError, SearchHit
from research_swarm.providers.http import request

ENDPOINT = "https://serpapi.com/search.json"


class SerpApiProvider:
    name = "serpapi"

    def __init__(self, settings: Settings, *, engine: str = "google"):
        if not settings.serpapi_api_key:
            raise SearchError("SERPAPI_API_KEY is not set.")
        self._settings = settings
        self._api_key = settings.serpapi_api_key
        self._engine = engine

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        response = await request(
            "GET",
            ENDPOINT,
            settings=self._settings,
            params={
                "engine": self._engine,
                "q": query,
                "num": max(10, max_results),
                "api_key": self._api_key,
            },
        )
        data = response.json()
        if data.get("error"):
            raise SearchError(f"SerpAPI error: {data['error']}")

        hits: list[SearchHit] = []
        for item in data.get("organic_results", []) or []:
            url = item.get("link")
            if not url:
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=(item.get("title") or "").strip(),
                    snippet=(item.get("snippet") or "").strip(),
                    published=item.get("date"),
                    score=float(item["position"]) if item.get("position") else None,
                )
            )
        return hits[:max_results]

    async def aclose(self) -> None:  # pragma: no cover - shared pool
        return None
