"""Command-line interface.

    research-swarm "the state of solid-state batteries in 2026" --out report.md
    research-swarm "topic" --mock            # no API keys needed at all
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from research_swarm.config import SEARCH_PROVIDERS, Settings
from research_swarm.report import render_markdown, write_report
from research_swarm.runner import run_research


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-swarm",
        description="Multi-agent deep research: plan, search, read, cross-check, synthesize.",
    )
    parser.add_argument("topic", help="The research topic or question.")
    parser.add_argument("-o", "--out", default=None, help="Write the Markdown report here.")
    parser.add_argument("--json", dest="json_path", default=None, help="Write the JSON report here.")
    parser.add_argument("--mock", action="store_true", help="Force offline mock LLM + search.")
    parser.add_argument("--provider", default=None, help="LLM provider: gemini|openai|anthropic|mock.")
    parser.add_argument("--search", default=None, choices=list(SEARCH_PROVIDERS), help="Search backend.")
    parser.add_argument("--model", default=None, help="Override the LLM model id.")
    parser.add_argument("--max-subquestions", type=int, default=None, help="Plan size (default 5).")
    parser.add_argument("--results-per-query", type=int, default=None, help="Results per search query.")
    parser.add_argument("--concurrency", type=int, default=None, help="Max concurrent calls.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Print only the report.")
    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    overrides: dict[str, object] = {}
    if args.provider:
        overrides["llm_provider"] = args.provider
    if args.search:
        overrides["search_provider"] = args.search
    if args.model:
        overrides["llm_model"] = args.model
    if args.max_subquestions is not None:
        overrides["max_subquestions"] = max(1, args.max_subquestions)
    if args.results_per_query is not None:
        overrides["results_per_query"] = max(1, args.results_per_query)
    if args.concurrency is not None:
        overrides["max_concurrency"] = max(1, args.concurrency)
    if args.mock:
        overrides["llm_provider"] = "mock"
        overrides["search_provider"] = "mock"
        overrides["llm_model"] = "mock-1"
    return settings.with_overrides(**overrides)


def _progress_printer(quiet: bool):
    def on_event(node: str, update: dict) -> None:
        if quiet:
            return
        for message in update.get("events", []) or []:
            print(f"  · {node}: {message}", file=sys.stderr)
        for error in update.get("errors", []) or []:
            print(f"  ! {error}", file=sys.stderr)

    return on_event


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = _settings_from_args(args)

    if not args.quiet:
        llm = settings.resolve_llm_provider()
        search = settings.resolve_search_provider()
        print(f"research-swarm → topic: {args.topic}", file=sys.stderr)
        print(f"  llm: {llm} ({settings.resolved_model(llm)})", file=sys.stderr)
        print(f"  search: {search}", file=sys.stderr)
        if llm == "mock" or search == "mock":
            print(
                "  note: mock mode active - set GEMINI_API_KEY (and optionally a search "
                "key) or see .env.example",
                file=sys.stderr,
            )

    try:
        report = asyncio.run(
            run_research(args.topic, settings, on_event=_progress_printer(args.quiet))
        )
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    written = write_report(report, markdown_path=args.out, json_path=args.json_path)
    if args.out or args.json_path:
        if not args.quiet:
            for path in written:
                print(f"  wrote {path}", file=sys.stderr)
    if not args.out and not args.json_path:
        print(render_markdown(report))

    stats = report.stats
    if not args.quiet:
        print(
            f"done in {stats.duration_seconds:.1f}s · {stats.sources_fetched} sources read · "
            f"{stats.claims} claims · {stats.contradictions} contradictions · "
            f"{stats.llm_calls} LLM calls",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
