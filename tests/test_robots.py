import urllib.robotparser
from typing import cast

import pytest

from research_swarm.agents.researcher import research_subquestion
from research_swarm.agents.runtime import Runtime
from research_swarm.llm import StructuredLLM
from research_swarm.models import SubQuestion
from research_swarm.mock_llm import MockLLM
from research_swarm.providers import fetch
from research_swarm.providers.base import SearchHit
from research_swarm.providers.fetch import PageFetcher


def _parser(disallowed_path: str) -> urllib.robotparser.RobotFileParser:
    policy = urllib.robotparser.RobotFileParser()
    policy.parse(["User-agent: *", f"Disallow: {disallowed_path}"])
    return policy


class SingleHitSearch:
    name = "exa"

    def __init__(self, hit: SearchHit):
        self.hit = hit

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        return [self.hit]

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_robots_policy_blocks_disallowed_url(settings, monkeypatch):
    origin = "https://robots-test.example"
    monkeypatch.setitem(fetch._ROBOTS_CACHE, origin, _parser("/private/"))
    reader = PageFetcher(settings)
    assert await reader._allowed_by_robots(origin + "/public/page") is True
    assert await reader._allowed_by_robots(origin + "/private/page") is False


@pytest.mark.asyncio
async def test_invalid_url_is_rejected_by_robots_check(settings):
    assert await PageFetcher(settings)._allowed_by_robots("file:///etc/passwd") is False


@pytest.mark.asyncio
async def test_cached_page_is_not_returned_if_robots_disallows_it(settings, monkeypatch):
    url = "https://robots-test.example/private/report"
    monkeypatch.setitem(fetch._ROBOTS_CACHE, "https://robots-test.example", _parser("/private/"))
    reader = PageFetcher(settings)
    reader._memory[url] = ("Private title", "Cached private contents")

    title, text, error = await reader.fetch(url)

    assert (title, text) == ("", "")
    assert error == "blocked by robots.txt (or robots policy unavailable)"


@pytest.mark.asyncio
async def test_provider_page_text_and_snippet_cannot_bypass_robots(settings, monkeypatch):
    url = "https://robots-test.example/private/provider-result"
    hit = SearchHit(
        url=url,
        title="Private provider result",
        snippet="disallowed provider snippet",
        content="disallowed provider full text",
    )
    fetcher = PageFetcher(settings)

    async def denied(candidate: str) -> bool:
        assert candidate == url
        return False

    monkeypatch.setattr(fetcher, "is_allowed_by_robots", denied)
    runtime = Runtime(
        settings=settings,
        llm=cast(StructuredLLM, MockLLM()),
        search=SingleHitSearch(hit),
        fetcher=fetcher,
    )
    sub_question = SubQuestion(
        id="q1", question="What does the restricted page say?", search_queries=["restricted page"]
    )

    sources, claims = await research_subquestion(runtime, sub_question, topic="robots policy")

    assert len(sources) == 1
    assert sources[0].content == ""
    assert sources[0].snippet == ""
    assert sources[0].fetched is False
    assert sources[0].error == "blocked by robots.txt (or robots policy unavailable)"
    assert claims == []


@pytest.mark.asyncio
async def test_provider_text_is_preserved_for_robots_allowed_url(settings, monkeypatch):
    url = "https://robots-test.example/public/provider-result"
    hit = SearchHit(url=url, content="Allowed full page text")
    fetcher = PageFetcher(settings)

    async def allowed(candidate: str) -> bool:
        assert candidate == url
        return True

    monkeypatch.setattr(fetcher, "is_allowed_by_robots", allowed)
    runtime = Runtime(
        settings=settings,
        llm=cast(StructuredLLM, MockLLM()),
        search=SingleHitSearch(hit),
        fetcher=fetcher,
    )
    sub_question = SubQuestion(
        id="q1", question="What is reported?", search_queries=["public report"]
    )

    sources, _claims = await research_subquestion(runtime, sub_question, topic="robots policy")

    assert sources[0].content == "Allowed full page text"
    assert sources[0].fetched is True
