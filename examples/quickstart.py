"""Runnable example: run the swarm and inspect the typed report.

    uv run python examples/quickstart.py "tidal energy economics"
    uv run python examples/quickstart.py "topic" --mock
"""

from __future__ import annotations

import asyncio
import sys

from research_swarm.config import Settings
from research_swarm.report import render_markdown
from research_swarm.runner import run_research


async def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--mock"]
    use_mock = "--mock" in sys.argv
    topic = args[0] if args else "grid-scale battery storage economics"

    settings = Settings.from_env()
    if use_mock:
        settings = settings.with_overrides(
            llm_provider="mock", search_provider="mock", llm_model="mock-1"
        )

    def progress(node: str, update: dict) -> None:
        for message in update.get("events", []) or []:
            print(f"  · {node}: {message}", file=sys.stderr)

    print(f"Researching: {topic}\n", file=sys.stderr)
    report = await run_research(topic, settings, on_event=progress)

    print(render_markdown(report))

    print("\n--- typed access ---", file=sys.stderr)
    print(f"findings       : {len(report.findings)}", file=sys.stderr)
    print(f"contradictions : {len(report.contradictions)}", file=sys.stderr)
    print(f"sources        : {len(report.sources)}", file=sys.stderr)
    for finding in report.findings:
        print(f"  - {finding.heading} (conf {finding.confidence})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
