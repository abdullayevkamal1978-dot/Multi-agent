"""End-to-end entry point: build the runtime, run the graph, finalize the report."""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Callable

from research_swarm.agents.runtime import Runtime
from research_swarm.config import Settings
from research_swarm.graph import build_graph, finalize_report
from research_swarm.llm import build_llm
from research_swarm.models import ResearchReport, RunStats
from research_swarm.providers.base import build_search_provider
from research_swarm.providers.fetch import PageFetcher
from research_swarm.providers.http import aclose_client

EventHook = Callable[[str, dict[str, Any]], None]


def build_runtime(settings: Settings) -> Runtime:
    """Resolve providers from settings and wire them together."""
    llm = build_llm(settings)
    search = build_search_provider(settings)
    fetcher = PageFetcher(settings)
    return Runtime(settings=settings, llm=llm, search=search, fetcher=fetcher)


async def run_research(
    topic: str,
    settings: Settings | None = None,
    *,
    on_event: EventHook | None = None,
) -> ResearchReport:
    """Run the full multi-agent pipeline and return the finished report.

    ``on_event`` receives ``(node_name, update)`` for every graph update, which
    is what the CLI uses to stream progress.
    """
    settings = settings or Settings.from_env()
    if not topic or not topic.strip():
        raise ValueError("A research topic is required.")

    runtime = build_runtime(settings)
    graph = build_graph(runtime)
    started_at = time.perf_counter()

    initial: dict[str, Any] = {
        "topic": topic.strip(),
        "sources": [],
        "claims": [],
        "errors": [],
        "events": [],
    }

    final_state: dict[str, Any] = dict(initial)
    try:
        async for chunk in graph.astream(initial, stream_mode="updates"):
            for node_name, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                if on_event is not None:
                    on_event(node_name, update)
                _merge(final_state, update)
    finally:
        await _safe_close(runtime)
        await aclose_client()

    report = final_state.get("report")
    if report is None:
        report = ResearchReport(
            topic=topic,
            executive_summary=(
                "The pipeline produced no report. Errors: "
                + "; ".join(final_state.get("errors", []) or ["(none recorded)"])
            ),
            sources=final_state.get("sources", []),
        )

    plan = final_state.get("plan")
    queries = sum(len(q.search_queries) for q in plan.sub_questions) if plan else 0
    report.stats.errors = list(final_state.get("errors", []))
    report.stats.llm_provider = settings.resolve_llm_provider()
    report.stats.llm_model = settings.resolved_model()
    report.stats.search_provider = settings.resolve_search_provider()
    if not isinstance(report.stats, RunStats):
        report.stats = RunStats()

    return finalize_report(
        report,
        llm_calls=getattr(runtime.llm, "call_count", 0),
        sub_questions=len(plan.sub_questions) if plan else 0,
        queries=queries,
        claims=len(final_state.get("claims", [])),
        started_at=started_at,
    )


async def stream_research(
    topic: str, settings: Settings | None = None
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Async generator variant for callers that want to consume updates inline."""
    queue: list[tuple[str, dict[str, Any]]] = []

    def collect(node: str, update: dict[str, Any]) -> None:
        queue.append((node, update))

    report = await run_research(topic, settings, on_event=collect)
    for item in queue:
        yield item
    yield ("report", {"report": report})


def _merge(state: dict[str, Any], update: dict[str, Any]) -> None:
    """Mirror LangGraph's reducer semantics for the local state mirror."""
    for key, value in update.items():
        if key == "sources" and isinstance(value, list):
            existing = state.setdefault("sources", [])
            known = {s.id for s in existing}
            existing.extend(s for s in value if s.id not in known)
        elif key == "claims" and isinstance(value, list):
            existing = state.setdefault("claims", [])
            known = {c.id for c in existing}
            existing.extend(c for c in value if c.id not in known)
        elif key in ("errors", "events") and isinstance(value, list):
            state.setdefault(key, []).extend(value)
        else:
            state[key] = value


async def _safe_close(runtime: Runtime) -> None:
    closer = getattr(runtime.search, "aclose", None)
    if closer is not None:
        try:
            await closer()
        except Exception:  # noqa: BLE001
            pass
