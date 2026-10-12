"""Web UI layer: update mapping, settings, and a real end-to-end SSE stream."""

from __future__ import annotations

import json

import asyncio

import pytest

from research_swarm import server
from research_swarm.config import Settings
from research_swarm.models import (
    Claim,
    Contradiction,
    Finding,
    ResearchPlan,
    ResearchReport,
    Source,
    SubQuestion,
)


def asyncio_run(coro):
    return asyncio.run(coro)


def _frames(raw: str) -> list[tuple[str, dict]]:
    out = []
    for block in raw.split("\n\n"):
        event = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event is not None:
            out.append((event, data))
    return out


def test_summarize_update_maps_planner():
    plan = ResearchPlan(
        topic="t",
        sub_questions=[SubQuestion(id="q1", question="?", search_queries=["a"])],
    )
    events = server.summarize_update("planner", {"plan": plan})
    assert [e for e, _ in events] == ["plan"]
    assert events[0][1]["sub_questions"][0]["id"] == "q1"


def test_summarize_update_researcher_emits_branch_with_counts():
    src = Source(id="S1", url="https://example.com")
    claim = Claim(id="c1", statement="s", source_ids=["S1"])
    events = server.summarize_update("researcher", {"sources": [src], "claims": [claim]})
    assert [e for e, _ in events] == ["branch"]
    payload = events[0][1]
    assert payload["sources"][0]["id"] == "S1"
    assert payload["claims"][0]["statement"] == "s"


def test_summarize_update_skips_empty_researcher():
    assert server.summarize_update("researcher", {"sources": [], "claims": []}) == []


def test_summarize_update_crosscheck_and_synthesizer():
    con = Contradiction(id="x1", topic="t", description="d")
    ev = server.summarize_update("crosscheck", {"contradictions": [con]})
    assert ev[0][0] == "contradictions" and ev[0][1][0]["id"] == "x1"

    ev = server.summarize_update(
        "synthesizer",
        {
            "findings": [Finding(heading="h", detail="d")],
            "executive_summary": "sum",
            "open_questions": ["q?"],
        },
    )
    assert ev[0][0] == "findings"
    assert ev[0][1]["executive_summary"] == "sum"
    assert ev[0][1]["open_questions"] == ["q?"]


def test_summarize_update_surfaces_errors_from_any_node():
    events = server.summarize_update("planner", {"errors": ["planner: boom"]})
    assert ("warning", {"message": "planner: boom"}) in events


def test_settings_from_query_mock_forces_mock_providers():
    s = server.settings_from_query(mock=True, max_subquestions=None, concurrency=None)
    assert s.resolve_llm_provider() == "mock"
    assert s.resolve_search_provider() == "mock"


def test_settings_from_query_clamps_out_of_range_values():
    assert server.settings_from_query(
        mock=False, max_subquestions=99, concurrency=99
    ).max_subquestions == 8
    assert server.settings_from_query(
        mock=False, max_subquestions=None, concurrency=99
    ).max_concurrency == 12
    assert server.settings_from_query(
        mock=False, max_subquestions=3, concurrency=3
    ).max_concurrency == 3


def test_settings_from_query_leaves_falsy_bounds_alone():
    """0/None mean "no override" - the dataclass defaults must survive."""
    base = Settings.from_env()
    got = server.settings_from_query(mock=False, max_subquestions=0, concurrency=None)
    assert got.max_subquestions == base.max_subquestions
    assert got.max_concurrency == base.max_concurrency


def test_app_exposes_expected_routes():
    paths = {r.path for r in server.app.routes}
    assert {"/", "/api/health", "/api/research"} <= paths


def test_health_reports_providers_without_secrets():
    import httpx

    async def _get(path: str):
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.get(path)

    response = asyncio_run(_get("/api/health"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    # Only booleans about key presence - the values themselves never appear.
    assert isinstance(payload["has_llm_key"], bool)
    assert isinstance(payload["has_search_key"], bool)
    assert set(payload) == {
        "ok",
        "llm_provider",
        "search_provider",
        "has_llm_key",
        "has_search_key",
    }
    assert "api_key=" not in json.dumps(payload).lower()

    page = asyncio_run(_get("/"))
    assert page.status_code == 200
    assert "research-swarm" in page.text


@pytest.mark.asyncio
async def test_end_to_end_stream_in_mock_mode():
    """The whole point of the layer: real graph updates reach the client."""
    settings = server.settings_from_query(
        mock=True, max_subquestions=2, concurrency=4
    )
    raw = ""
    async for frame in server._events("solid-state batteries", settings):
        raw += frame

    events = _frames(raw)
    names = [e for e, _ in events]

    assert names[0] == "start"
    assert "plan" in names
    assert "branch" in names
    assert "contradictions" in names
    assert "findings" in names
    assert names[-1] == "report"

    # Provider info reaches the UI so the banner can explain the run.
    assert events[0][1]["providers"]["llm"] == "mock"

    report = dict(events)["report"]
    assert report["topic"] == "solid-state batteries"
    assert isinstance(report["sources"], list)
    assert report["stats"]["llm_provider"] == "mock"

    # Branch progress is what drives the counter in the UI.
    branch = next(d for e, d in events if e == "branch")
    assert branch["branches_total"] >= 1
    assert branch["branches_done"] >= 1


@pytest.mark.asyncio
async def test_stream_emits_heartbeat_while_pipeline_is_idle(monkeypatch):
    """Idle HTTP/1.1 connections get dropped; a comment frame keeps it open."""

    async def slow_run(topic, settings, *, on_event=None):
        await asyncio.sleep(0.4)
        return ResearchReport(topic=topic, executive_summary="done")

    monkeypatch.setattr(server, "run_research", slow_run)
    monkeypatch.setattr(server, "HEARTBEAT_SECONDS", 0.05)

    settings = Settings(llm_provider="mock", search_provider="mock")
    raw = ""
    async for frame in server._events("a topic long enough", settings):
        raw += frame

    assert raw.count(": ping") >= 2
    # Comments must not be parsed as events by EventSource.
    assert "event: ping" not in raw


@pytest.mark.asyncio
async def test_heartbeat_does_not_duplicate_or_reorder_events(monkeypatch):
    async def instant(topic, settings, *, on_event=None):
        if on_event:
            on_event("planner", {"errors": ["planner: boom"]})
        return ResearchReport(topic=topic, executive_summary="done")

    monkeypatch.setattr(server, "run_research", instant)
    monkeypatch.setattr(server, "HEARTBEAT_SECONDS", 30)

    settings = Settings(llm_provider="mock", search_provider="mock")
    frames = []
    async for frame in server._events("a topic long enough", settings):
        frames.append(frame)

    events = [f.split("\n", 1)[0] for f in frames]
    assert events == ["event: start", "event: warning", "event: report"]
    assert ": ping" not in "".join(frames)
