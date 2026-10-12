"""Streaming web UI for the research pipeline.

FastAPI serves one static HTML page and an SSE endpoint that mirrors the graph
as it runs. The pipeline itself is untouched: we reuse ``run_research`` and
bridge its synchronous ``on_event`` hook onto an ``asyncio.Queue``. No threads
are needed because the hook fires inside the same event loop that drains it.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator

from pydantic import BaseModel

from research_swarm.config import Settings
from research_swarm.runner import run_research

STATIC_DIR = Path(__file__).parent / "static"

# HTTP/1.1 clients and proxies close idle connections. The pipeline can be quiet
# for a long stretch (a single researcher branch), so emit an SSE comment to keep
# the stream open. Comments are ignored by EventSource. Tunable because some
# proxies need a tighter interval than others.
HEARTBEAT_SECONDS = float(os.getenv("RESEARCH_WEB_HEARTBEAT_SECONDS", "15") or 15)

# Node names are defined in graph.py; the UI maps them onto pipeline steps.
NODE_STEPS = {
    "planner": "plan",
    "researcher": "research",
    "crosscheck": "check",
    "synthesizer": "synth",
}


def _dump(value: Any) -> Any:
    """JSON-safe serialization for the models flowing through the graph."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, tuple):
        return [_dump(v) for v in value]
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    return value


def sse(event: str, data: Any) -> str:
    """One SSE frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def settings_from_query(
    *, mock: bool, max_subquestions: int | None, concurrency: int | None
) -> Settings:
    """Build run settings from query params, without ever exposing secrets."""
    base = Settings.from_env()
    overrides: dict[str, Any] = {}
    if mock:
        # Demo mode: runs the real graph with no API keys and no network.
        overrides["llm_provider"] = "mock"
        overrides["search_provider"] = "mock"
    if max_subquestions:
        overrides["max_subquestions"] = max(1, min(max_subquestions, 8))
    if concurrency:
        overrides["max_concurrency"] = max(1, min(concurrency, 12))
    return base.with_overrides(**overrides) if overrides else base


def summarize_update(node: str, update: dict[str, Any]) -> list[tuple[str, Any]]:
    """Turn one graph update into zero or more UI events.

    Each fan-out branch emits its own ``researcher`` update, so sources and
    claims stream in branch by branch instead of arriving in one lump at the end.
    """
    events: list[tuple[str, Any]] = []

    if node == "planner":
        plan = update.get("plan")
        if plan is not None:
            events.append(("plan", _dump(plan)))

    elif node == "researcher":
        sources = update.get("sources") or []
        claims = update.get("claims") or []
        if sources or claims:
            events.append(
                ("branch", {"sources": _dump(sources), "claims": _dump(claims)})
            )

    elif node == "crosscheck":
        contradictions = update.get("contradictions")
        if contradictions is not None:
            events.append(("contradictions", _dump(contradictions)))

    elif node == "synthesizer":
        findings = update.get("findings")
        if findings is not None:
            events.append(
                (
                    "findings",
                    {
                        "findings": _dump(findings),
                        "executive_summary": update.get("executive_summary", ""),
                        "open_questions": _dump(update.get("open_questions") or []),
                    },
                )
            )

    # Errors are channelled by every node, including a failed planner.
    for error in update.get("errors") or []:
        events.append(("warning", {"message": str(error)}))

    return events


async def _run_into_queue(topic: str, settings: Settings, queue: asyncio.Queue) -> None:
    """Run the pipeline, pushing every graph update onto ``queue``."""

    def on_event(node: str, update: dict[str, Any]) -> None:
        queue.put_nowait(("update", (node, update)))

    try:
        report = await run_research(topic, settings, on_event=on_event)
    except Exception as exc:  # noqa: BLE001 - surface it, never crash the stream
        queue.put_nowait(("failed", {"message": f"{type(exc).__name__}: {exc}"}))
    else:
        queue.put_nowait(("finished", _dump(report)))
    finally:
        queue.put_nowait(("end", None))


async def _events(topic: str, settings: Settings) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_run_into_queue(topic, settings, queue))

    plan_total = 0
    branches_done = 0

    try:
        yield sse(
            "start",
            {
                "topic": topic,
                "providers": {
                    "llm": settings.resolve_llm_provider(),
                    "search": settings.resolve_search_provider(),
                    "model": settings.resolved_model(),
                },
            },
        )

        while True:
            try:
                kind, payload = await asyncio.wait_for(
                    queue.get(), timeout=HEARTBEAT_SECONDS
                )
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue

            if kind == "end":
                break
            if kind == "failed":
                yield sse("failed", payload)
                continue
            if kind == "finished":
                yield sse("report", payload)
                continue

            node, update = payload
            if node == "researcher":
                branches_done += 1

            for event, data in summarize_update(node, update):
                if event == "plan":
                    plan_total = len(data.get("sub_questions") or [])
                elif event == "branch":
                    data["branches_done"] = branches_done
                    data["branches_total"] = plan_total
                yield sse(event, data)

    finally:
        if not task.done():
            task.cancel()


def create_app():
    """Application factory, importable by tests and by ``uvicorn``."""
    from fastapi import FastAPI, Query
    from fastapi.responses import FileResponse, StreamingResponse

    app = FastAPI(title="research-swarm")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        settings = Settings.from_env()
        llm = settings.resolve_llm_provider()
        search = settings.resolve_search_provider()
        return {
            "ok": True,
            "llm_provider": llm,
            "search_provider": search,
            "has_llm_key": bool(settings.key_for_llm(llm)),
            "has_search_key": bool(settings.key_for_search(search)),
        }

    @app.get("/api/research")
    async def research(
        topic: str = Query(..., min_length=3, max_length=300),
        mock: bool = Query(False),
        max_subquestions: int | None = Query(None, ge=1, le=8),
        concurrency: int | None = Query(None, ge=1, le=12),
    ) -> StreamingResponse:
        settings = settings_from_query(
            mock=mock, max_subquestions=max_subquestions, concurrency=concurrency
        )
        return StreamingResponse(
            _events(topic.strip(), settings),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.getenv("RESEARCH_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("RESEARCH_WEB_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
