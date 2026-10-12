"""Tavily search backend (https://docs.tavily.com)."""

from __future__ import annotations

from research_swarm.config import Settings
from research_swarm.providers.base import SearchError, SearchHit
from research_swarm.providers.http import request

ENDPOINT = "https://api.tavily.com/search"


class TavilyProvider:
    name = "tavily"

    def __init__(self, settings: Settings, *, search_depth: str = "advanced"):
        if not settings.tavily_api_key:
            raise SearchError("TAVILY_API_KEY is not set.")
        self._settings = settings
        self._api_key = settings.tavily_api_key
        self._depth = search_depth

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        payload = {
            "query": query,
            "max_results": max_results,
            "search_depth": self._depth,
            "include_answer": False,
            "include_raw_content": False,
        }
        response = await request(
            "POST",
            ENDPOINT,
            settings=self._settings,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
        )
        data = response.json()
        hits: list[SearchHit] = []
        for item in data.get("results", []) or []:
            url = item.get("url")
            if not url:
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=(item.get("title") or "").strip(),
                    snippet=(item.get("content") or "").strip(),
                    score=item.get("score"),
                    published=item.get("published_date"),
                )
            )
        return hits[:max_results]

    async def aclose(self) -> None:  # pragma: no cover - shared pool
        return None
