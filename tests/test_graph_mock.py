"""End-to-end graph execution in offline mock mode."""

from research_swarm.runner import run_research


async def test_full_pipeline_produces_a_cited_report(settings):
    events: list[tuple[str, dict]] = []
    report = await run_research(
        "grid-scale energy storage economics", settings, on_event=lambda n, u: events.append((n, u))
    )

    # Structure
    assert report.topic == "grid-scale energy storage economics"
    assert report.executive_summary
    assert report.findings, "synthesis must produce findings"
    assert report.sources, "researchers must find sources"
    assert report.open_questions
    assert report.contradictions, "mock corpus is designed to conflict"

    # Every branch ran, and the fan-in happened after all of them.
    nodes = [name for name, _ in events]
    assert nodes[0] == "planner"
    assert nodes.count("researcher") >= 2, "expected parallel researcher branches"
    assert nodes[-2:] == ["crosscheck", "synthesizer"]


async def test_source_ids_are_unique_and_citations_resolve(settings):
    report = await run_research("perovskite solar cell stability", settings)

    ids = [s.id for s in report.sources]
    assert len(ids) == len(set(ids)), "duplicate citation ids in the report"

    known = set(ids)
    referenced = {sid for f in report.findings for sid in f.source_ids}
    referenced |= {sid for x in report.contradictions for sid in x.source_ids}
    assert referenced, "the report must cite sources"
    assert referenced <= known, f"citations point at unknown sources: {referenced - known}"


async def test_stats_are_populated(settings):
    report = await run_research("tidal energy", settings)
    stats = report.stats
    assert stats.sub_questions > 0
    assert stats.queries > 0
    assert stats.sources_found == len(report.sources)
    assert stats.sources_fetched > 0
    assert stats.claims > 0
    assert stats.llm_calls > 0
    assert stats.duration_seconds is not None and stats.duration_seconds >= 0
    assert stats.llm_provider == "mock"
    assert stats.search_provider == "mock"


async def test_missing_topic_is_rejected(settings):
    import pytest

    with pytest.raises(ValueError):
        await run_research("   ", settings)


async def test_empty_result_degrades_instead_of_crashing(settings):
    """A provider that returns nothing must still yield a valid report object."""
    from research_swarm.agents.runtime import Runtime
    from research_swarm.config import Settings
    from research_swarm.graph import build_graph
    from research_swarm.mock_llm import MockLLM
    from research_swarm.providers.fetch import PageFetcher

    class DeadSearch:
        name = "dead"

        async def search(self, query, *, max_results=5):
            return []

        async def aclose(self):
            return None

    cfg = Settings(
        llm_provider="mock", search_provider="mock", max_subquestions=2,
        results_per_query=2, cache_dir=str(settings.cache_dir),
    )
    runtime = Runtime(
        settings=cfg, llm=MockLLM(), search=DeadSearch(), fetcher=PageFetcher(cfg)
    )
    graph = build_graph(runtime)
    final: dict = {}
    async for chunk in graph.astream(
        {"topic": "nothing found", "sources": [], "claims": [], "errors": [], "events": []},
        stream_mode="updates",
    ):
        for _, update in chunk.items():
            if isinstance(update, dict):
                final.update(update)

    assert final["report"].contradictions == []
    assert final["report"].sources == []
    assert final["report"].executive_summary
