"""Google Search grounding through the Gemini API.

Lets a single Gemini key do double duty as both the LLM and the search layer.
Note: grounding with Google Search is **billed** ($14 / 1k queries after a
monthly free allowance) - see https://ai.google.dev/gemini-api/docs/pricing
"""

from __future__ import annotations

from research_swarm.config import Settings
from research_swarm.providers.base import SearchError, SearchHit


class GeminiGroundingProvider:
    name = "gemini"

    def __init__(self, settings: Settings, *, model: str | None = None):
        if not settings.gemini_api_key:
            raise SearchError("GEMINI_API_KEY is not set (required for Gemini grounding).")
        try:
            from google import genai  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise SearchError(
                "Gemini grounding needs the google-genai SDK: "
                "uv pip install langchain-google-genai"
            ) from exc
        self._settings = settings
        self._model = model or settings.resolved_model("gemini")

        from google import genai

        self._client = genai.Client(api_key=settings.gemini_api_key)

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        from google.genai import types

        prompt = (
            "Search the web and list the most authoritative, up-to-date sources about "
            f"the following research query. Be exhaustive about sourcing.\n\n{query}"
        )
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.0,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model, contents=prompt, config=config
            )
        except Exception as exc:  # noqa: BLE001
            raise SearchError(f"Gemini grounding failed: {exc}") from exc

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for candidate in getattr(response, "candidates", None) or []:
            metadata = getattr(candidate, "grounding_metadata", None)
            for chunk in getattr(metadata, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                uri = getattr(web, "uri", None)
                if not uri or uri in seen:
                    continue
                seen.add(uri)
                hits.append(SearchHit(url=uri, title=(getattr(web, "title", "") or "").strip()))
        return hits[:max_results]

    async def aclose(self) -> None:  # pragma: no cover
        return None
