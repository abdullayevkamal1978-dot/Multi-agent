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


def render_html(report: ResearchReport) -> str:
    """Render a self-contained, print-friendly HTML report."""
    import html

    esc = html.escape
    sections = [f"<h1>{esc(report.topic)}</h1>", f"<p class=meta>Generated {esc(report.generated_at)}</p>",
                f"<h2>Executive summary</h2><p>{esc(report.executive_summary or 'Not available.')}</p>", "<h2>Key findings</h2>"]
    for finding in report.findings:
        sections.append(f"<article><h3>{esc(finding.heading)}</h3><p>{esc(finding.detail)}</p><small>Sources: {esc(', '.join(finding.source_ids) or 'uncited')} · confidence {finding.confidence:.2f}</small></article>")
    sections.append("<h2>Contradictions and disagreements</h2>")
    for item in report.contradictions:
        sections.append(f"<article><h3>{esc(item.topic or 'Disagreement')} — {esc(item.severity)}</h3><p>{esc(item.description)}</p><p><strong>Resolution:</strong> {esc(item.resolution or 'Unresolved')}</p></article>")
    sections.append("<h2>Open questions</h2><ul>" + "".join(f"<li>{esc(q)}</li>" for q in report.open_questions) + "</ul><h2>Sources</h2><ul>")
    sections.extend(f'<li><a href="{esc(src.url, quote=True)}">{esc(src.title or src.url)}</a> [{esc(src.id)}]</li>' for src in report.sources)
    sections.append("</ul>")
    return "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>" + esc(report.topic) + "</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:900px;margin:3rem auto;padding:0 1.5rem;color:#172033}h1,h2{color:#173b63}article{border-left:3px solid #6c93bb;padding:.5rem 1rem;margin:1rem 0;background:#f5f8fb}.meta,small{color:#627084}@media print{body{margin:0;max-width:none}}</style></head><body>" + "\n".join(sections) + "</body></html>"


def render_pdf(report: ResearchReport) -> bytes:
    """Render a simple PDF. Requires the optional ``reportlab`` dependency."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        from xml.sax.saxutils import escape
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install the 'app' extra to export PDF (pip install -e '.[app]').") from exc
    from io import BytesIO
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, rightMargin=0.7*inch, leftMargin=0.7*inch)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(report.topic), styles["Title"]), Spacer(1, 12), Paragraph("Executive summary", styles["Heading2"]), Paragraph(escape(report.executive_summary or "Not available."), styles["BodyText"])]
    for title, body in [(f.heading, f.detail) for f in report.findings] + [(c.topic or "Disagreement", c.description + " Resolution: " + c.resolution) for c in report.contradictions]:
        story += [Paragraph(escape(title), styles["Heading2"]), Paragraph(escape(body), styles["BodyText"]), Spacer(1, 8)]
    story.append(Paragraph("Sources", styles["Heading2"]))
    for src in report.sources:
        story.append(Paragraph(f"[{escape(src.id)}] {escape(src.title or src.url)} — {escape(src.url)}", styles["BodyText"]))
    doc.build(story)
    return output.getvalue()
