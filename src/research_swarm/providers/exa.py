"""Exa search backend (https://docs.exa.ai) - semantic search built for agents."""

from __future__ import annotations

from research_swarm.config import Settings
from research_swarm.providers.base import SearchError, SearchHit
from research_swarm.providers.http import request

ENDPOINT = "https://api.exa.ai/search"


class ExaProvider:
    name = "exa"

    def __init__(self, settings: Settings, *, search_type: str = "auto"):
        if not settings.exa_api_key:
            raise SearchError("EXA_API_KEY is not set.")
        self._settings = settings
        self._api_key = settings.exa_api_key
        self._type = search_type

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        payload = {
            "query": query,
            "numResults": max_results,
            "type": self._type,
            "contents": {
                "text": {"maxCharacters": min(self._settings.max_content_chars, 4000)},
                "highlights": {"numSentences": 3},
            },
        }
        response = await request(
            "POST",
            ENDPOINT,
            settings=self._settings,
            headers={"x-api-key": self._api_key, "Content-Type": "application/json"},
            json=payload,
        )
        data = response.json()
        hits: list[SearchHit] = []
        for item in data.get("results", []) or []:
            url = item.get("url")
            if not url:
                continue
            highlights = item.get("highlights") or []
            hits.append(
                SearchHit(
                    url=url,
                    title=(item.get("title") or "").strip(),
                    snippet=" ".join(highlights).strip() or (item.get("text") or "")[:400],
                    published=item.get("publishedDate"),
                    score=item.get("score"),
                    content=(item.get("text") or "").strip(),
                )
            )
        return hits[:max_results]

    async def aclose(self) -> None:  # pragma: no cover - shared pool
        return None
