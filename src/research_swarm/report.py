"""Report rendering: Markdown for humans, JSON for machines."""

from __future__ import annotations

import json
from pathlib import Path

from research_swarm.models import ResearchReport

_SEVERITY_ICON = {"high": "!!!", "medium": "!!", "low": "!"}


def _citations(source_ids: list[str]) -> str:
    return ", ".join(f"[{sid}]" for sid in source_ids) if source_ids else "_(uncited)_"


def render_markdown(report: ResearchReport) -> str:
    """Render the report as a self-contained Markdown document."""
    stats = report.stats
    lines: list[str] = []

    lines.append(f"# {report.topic}")
    lines.append("")
    provenance = f"Generated {report.generated_at}"
    if stats.duration_seconds is not None:
        provenance += f" in {stats.duration_seconds:.1f}s"
    lines.append(f"*{provenance}*")
    lines.append("")
    lines.append(
        f"`{stats.llm_provider or '?'}:{stats.llm_model or '?'}` · "
        f"`search:{stats.search_provider or '?'}` · "
        f"{stats.sub_questions} sub-questions · {stats.queries} queries · "
        f"{stats.sources_fetched}/{stats.sources_found} sources read · "
        f"{stats.claims} claims · {stats.contradictions} contradictions"
    )
    lines.append("")

    if report.scope:
        lines.append(f"**Scope:** {report.scope}")
        lines.append("")

    lines.append("## Executive summary")
    lines.append("")
    lines.append(report.executive_summary or "_(not available)_")
    lines.append("")

    lines.append("## Key findings")
    lines.append("")
    if report.findings:
        for index, finding in enumerate(report.findings, start=1):
            lines.append(f"### {index}. {finding.heading}")
            lines.append("")
            lines.append(finding.detail)
            lines.append("")
            lines.append(f"*Sources:* {_citations(finding.source_ids)} · confidence {finding.confidence:.2f}")
            lines.append("")
    else:
        lines.append("_No findings could be synthesized from the retrieved evidence._")
        lines.append("")

    lines.append("## Contradictions and disagreements")
    lines.append("")
    if report.contradictions:
        for item in report.contradictions:
            flag = _SEVERITY_ICON.get(item.severity, "!")
            lines.append(f"### {flag} {item.topic or 'Disagreement'} — severity: {item.severity}")
            lines.append("")
            lines.append(item.description)
            lines.append("")
            for position in item.positions:
                lines.append(f"- {position}")
            if item.positions:
                lines.append("")
            lines.append(
                f"**Resolution:** {item.resolution or '_Unresolved on the available evidence._'}"
            )
            lines.append("")
            lines.append(
                f"*Sources:* {_citations(item.source_ids)} · confidence {item.confidence:.2f}"
            )
            lines.append("")
    else:
        lines.append(
            "_The retrieved sources did not conflict on the claims that were extracted._"
        )
        lines.append("")

    lines.append("## Open questions")
    lines.append("")
    if report.open_questions:
        for question in report.open_questions:
            lines.append(f"- {question}")
    else:
        lines.append("_None recorded._")
    lines.append("")

    lines.append("## Sources")
    lines.append("")
    if report.sources:
        for source in sorted(report.sources, key=lambda s: _source_sort_key(s.id)):
            title = source.title or source.url
            flags = []
            if not source.fetched:
                flags.append("not read")
            if source.error:
                flags.append(f"error: {source.error}")
            suffix = f" _({'; '.join(flags)})_" if flags else ""
            lines.append(f"- **[{source.id}]** [{title}]({source.url}){suffix}")
            if source.published:
                lines.append(f"  - published: {source.published}")
    else:
        lines.append("_No sources were retrieved._")
    lines.append("")

    if stats.errors:
        lines.append("## Run warnings")
        lines.append("")
        for error in stats.errors:
            lines.append(f"- `{error}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _source_sort_key(source_id: str) -> tuple[int, str]:
    digits = "".join(ch for ch in source_id if ch.isdigit())
    return (int(digits) if digits else 0, source_id)


def render_json(report: ResearchReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)


def write_report(
    report: ResearchReport, *, markdown_path: str | Path | None = None,
    json_path: str | Path | None = None,
) -> list[Path]:
    """Write whichever artifacts were requested; returns the paths written."""
    written: list[Path] = []
    if markdown_path:
        path = Path(markdown_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(report), encoding="utf-8")
        written.append(path)
    if json_path:
        path = Path(json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_json(report), encoding="utf-8")
        written.append(path)
    return written
