"""Prove the fan-out is genuinely concurrent, not just logically branched.

Timing alone is a weak signal on a busy machine, so the primary assertion is
on *observed peak concurrency*; wall-clock is checked as a sanity bound.
"""

from __future__ import annotations

import asyncio
import time

from research_swarm.agents.runtime import Runtime
from research_swarm.config import Settings
from research_swarm.graph import build_graph
from research_swarm.mock_llm import MockLLM
from research_swarm.providers.fetch import PageFetcher
from research_swarm.providers.mock import MockSearchProvider

DELAY = 0.25


class InstrumentedSearch(MockSearchProvider):
    """Records how many searches overlap in time."""

    name = "instrumented"

    def __init__(self, settings):
        super().__init__(settings)
        self.in_flight = 0
        self.peak = 0
        self.calls = 0

    async def search(self, query, *, max_results=5):
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(DELAY)
            return await super().search(query, max_results=max_results)
        finally:
            self.in_flight -= 1


async def test_researcher_branches_run_concurrently(tmp_path):
    settings = Settings(
        llm_provider="mock",
        search_provider="mock",
        max_subquestions=4,
        results_per_query=2,
        max_concurrency=5,
        cache_dir=str(tmp_path / "cache"),
    )
    search = InstrumentedSearch(settings)
    runtime = Runtime(
        settings=settings, llm=MockLLM(), search=search, fetcher=PageFetcher(settings)
    )

    started = time.perf_counter()
    graph = build_graph(runtime)
    async for _ in graph.astream(
        {"topic": "concurrency probe", "sources": [], "claims": [], "errors": [], "events": []},
        stream_mode="updates",
    ):
        pass
    elapsed = time.perf_counter() - started

    sequential = search.calls * DELAY
    assert search.calls >= 4, f"expected a real fan-out, got {search.calls} searches"
    assert search.peak > 1, f"searches never overlapped (peak={search.peak})"
    assert search.peak >= 3, f"expected >=3 concurrent branches, peak was {search.peak}"
    assert elapsed < sequential * 0.6, (
        f"ran in {elapsed:.2f}s vs sequential {sequential:.2f}s - not parallel enough"
    )
