"""The citation registry is the fix for duplicate sources across branches."""

from research_swarm.agents.runtime import Runtime, dedupe_by_id, normalize_url
from research_swarm.mock_llm import MockLLM
from research_swarm.models import Source
from research_swarm.providers.fetch import PageFetcher
from research_swarm.providers.mock import MockSearchProvider


def _runtime(settings):
    return Runtime(
        settings=settings,
        llm=MockLLM(),
        search=MockSearchProvider(settings),
        fetcher=PageFetcher(settings),
    )


def test_normalize_url_ignores_scheme_www_trailing_slash_case():
    variants = [
        "https://Example.com/a/b/",
        "http://example.com/a/b",
        "https://www.example.com/a/b",
    ]
    assert len({normalize_url(v) for v in variants}) == 1


async def test_same_url_gets_the_same_id_across_branches(settings):
    runtime = _runtime(settings)
    first = await runtime.citation_ids(["https://ex.com/a", "https://ex.com/b"])
    second = await runtime.citation_ids(["https://www.ex.com/a/", "https://ex.com/c"])

    assert first[0] == second[0], "the same page must reuse its citation id"
    assert second[1] not in first, "a new page must get a fresh id"
    assert len({*first, *second}) == 3


async def test_concurrent_id_allocation_never_collides(settings):
    import asyncio

    runtime = _runtime(settings)
    urls = [f"https://ex.com/page/{i}" for i in range(50)]

    async def allocate(url):
        return (await runtime.citation_ids([url]))[0]

    ids = await asyncio.gather(*(allocate(u) for u in urls))
    assert len(set(ids)) == 50


def test_dedupe_by_id_keeps_first_and_preserves_order():
    items = [
        Source(id="S1", url="https://a"),
        Source(id="S2", url="https://b"),
        Source(id="S1", url="https://a"),
    ]
    result = dedupe_by_id(items)
    assert [s.id for s in result] == ["S1", "S2"]
    assert result[0].url == "https://a"
