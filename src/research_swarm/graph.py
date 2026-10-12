"""LangGraph orchestration.

Topology
--------
                        ┌──────────────┐
        START ─────────▶│  planner     │
                        └──────┬───────┘
                               │  conditional edge fans out with Send()
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
      ┌────────────┐    ┌────────────┐    ┌────────────┐
      │ researcher │    │ researcher │ …  │ researcher │   (parallel)
      └──────┬─────┘    └──────┬─────┘    └──────┬─────┘
             └─────────────────┼─────────────────┘
                               ▼   implicit join: waits for every branch
                        ┌──────────────┐
                        │ cross-check  │  finds contradictions
                        └──────┬───────┘
                               ▼
                        ┌──────────────┐
                        │ synthesizer  │
                        └──────┬───────┘
                               ▼
                              END
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, START, StateGraph

try:  # LangGraph >= 0.2.20 keeps Send here
    from langgraph.types import Send
except ImportError:  # pragma: no cover - older layouts
    from langgraph.constants import Send  # type: ignore[attr-defined]

from research_swarm.agents.contradiction import find_contradictions
from research_swarm.agents.planner import plan_research
from research_swarm.agents.researcher import research_subquestion
from research_swarm.agents.runtime import Runtime, dedupe_by_id
from research_swarm.agents.synthesizer import synthesize
from research_swarm.models import ResearchReport, RunStats
from research_swarm.state import ResearchState


def build_graph(runtime: Runtime):
    """Compile the multi-agent graph for a given runtime."""

    async def planner_node(state: ResearchState) -> dict[str, Any]:
        started = time.perf_counter()
        topic = state["topic"]
        try:
            plan = await plan_research(runtime, topic)
        except Exception as exc:  # noqa: BLE001
            return {"errors": [f"planner: {type(exc).__name__}: {exc}"], "events": ["planner:FAILED"]}
        return {
            "plan": plan,
            "events": [
                f"planner:{len(plan.sub_questions)} sub-questions in "
                f"{time.perf_counter() - started:.2f}s"
            ],
        }

    async def researcher_node(state: ResearchState) -> dict[str, Any]:
        sub_question = state["sub_question"]
        started = time.perf_counter()
        try:
            sources, claims = await research_subquestion(
                runtime, sub_question, topic=state.get("topic", "")
            )
        except Exception as exc:  # noqa: BLE001 - one branch must not kill the run
            return {
                "sources": [],
                "claims": [],
                "errors": [f"researcher[{sub_question.id}]: {type(exc).__name__}: {exc}"],
                "events": [f"researcher[{sub_question.id}]:FAILED"],
            }
        return {
            "sources": sources,
            "claims": claims,
            "events": [
                f"researcher[{sub_question.id}]: {len(sources)} sources, "
                f"{len(claims)} claims in {time.perf_counter() - started:.2f}s"
            ],
        }

    async def crosscheck_node(state: ResearchState) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            contradictions = await find_contradictions(
                runtime,
                topic=state["topic"],
                claims=dedupe_by_id(state.get("claims", [])),
                sources=dedupe_by_id(state.get("sources", [])),
            )
        except Exception as exc:  # noqa: BLE001
            return {"contradictions": [], "errors": [f"cross-check: {type(exc).__name__}: {exc}"]}
        return {
            "contradictions": contradictions,
            "events": [
                f"cross-check: {len(contradictions)} contradictions in "
                f"{time.perf_counter() - started:.2f}s"
            ],
        }

    async def synthesizer_node(state: ResearchState) -> dict[str, Any]:
        started = time.perf_counter()
        topic = state["topic"]
        plan = state.get("plan")
        # Fan-in de-duplication: several branches may have found the same page.
        sources = dedupe_by_id(state.get("sources", []))
        claims = dedupe_by_id(state.get("claims", []))
        contradictions = dedupe_by_id(state.get("contradictions", []))
        errors = list(state.get("errors", []))

        try:
            result = await synthesize(
                runtime,
                topic=topic,
                scope=(plan.scope if plan else ""),
                claims=claims,
                contradictions=contradictions,
                sources=sources,
            )
        except Exception as exc:  # noqa: BLE001 - degrade to a partial report
            errors.append(f"synthesizer: {type(exc).__name__}: {exc}")
            source_block_ok = False
            report = ResearchReport(
                topic=topic,
                executive_summary=(
                    "Synthesis failed, so no executive summary could be produced. "
                    f"Collected sources are listed below. Errors: {errors}"
                ),
                scope=(plan.scope if plan else ""),
                findings=[],
                contradictions=contradictions,
                open_questions=[],
                sources=sources,
            )
            return {
                "report": report,
                "errors": errors,
                "events": ["synthesizer:FAILED"],
            }

        report = ResearchReport(
            topic=topic,
            executive_summary=result.executive_summary,
            scope=(plan.scope if plan else ""),
            findings=result.findings,
            contradictions=contradictions,
            open_questions=result.open_questions,
            sources=sources,
        )
        return {
            "report": report,
            "findings": result.findings,
            "executive_summary": result.executive_summary,
            "open_questions": result.open_questions,
            "events": [f"synthesizer: done in {time.perf_counter() - started:.2f}s"],
        }

    def fan_out(state: ResearchState) -> list[Send] | str:
        """Conditional edge: one parallel branch per sub-question.

        If planning failed there is nothing to fan out over, so route straight
        to synthesis - it degrades to a report that lists the collected errors.
        """
        plan = state.get("plan")
        if not plan or not plan.sub_questions:
            return "synthesizer"
        return [
            Send("researcher", {"topic": state["topic"], "sub_question": sub_question})
            for sub_question in plan.sub_questions
        ]

    builder = StateGraph(ResearchState)
    builder.add_node("planner", planner_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("crosscheck", crosscheck_node)
    builder.add_node("synthesizer", synthesizer_node)

    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", fan_out, ["researcher", "synthesizer"])
    builder.add_edge("researcher", "crosscheck")
    builder.add_edge("crosscheck", "synthesizer")
    builder.add_edge("synthesizer", END)

    return builder.compile()


def finalize_report(
    report: ResearchReport,
    *,
    llm_calls: int,
    sub_questions: int,
    queries: int,
    claims: int,
    started_at: float,
) -> ResearchReport:
    """Attach run statistics after the graph has finished."""
    from datetime import datetime, timezone

    report.stats.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report.stats.duration_seconds = round(time.perf_counter() - started_at, 3)
    report.stats.sub_questions = sub_questions
    report.stats.queries = queries
    report.stats.search_calls = queries
    report.stats.claims = claims
    report.stats.llm_calls = llm_calls
    report.stats.sources_found = len(report.sources)
    report.stats.sources_fetched = sum(1 for s in report.sources if s.fetched)
    report.stats.contradictions = len(report.contradictions)
    return report
