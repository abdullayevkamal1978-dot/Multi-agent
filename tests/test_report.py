import json

from research_swarm.models import (
    Claim,
    Contradiction,
    Finding,
    ResearchReport,
    RunStats,
    Source,
)
from research_swarm.report import render_json, render_markdown, write_report


def _report() -> ResearchReport:
    return ResearchReport(
        topic="Tidal energy",
        scope="Global, 2026",
        executive_summary="Tidal capacity is growing slowly [S1] but costs remain high [S2].",
        findings=[Finding(heading="Costs", detail="Costs fell 12%.", source_ids=["S1"], confidence=0.7)],
        contradictions=[
            Contradiction(
                id="x1",
                topic="Cost trend",
                description="Sources disagree on the cost trend.",
                positions=["S1: falling", "S2: flat"],
                source_ids=["S1", "S2"],
                severity="high",
                resolution="S2 uses older data.",
                confidence=0.6,
            )
        ],
        open_questions=["What is the levelised cost in 2026?"],
        sources=[
            Source(id="S2", url="https://b.example", title="Beta", published="2026-02-01"),
            Source(id="S1", url="https://a.example", title="Alpha", fetched=True),
        ],
        stats=RunStats(
            duration_seconds=1.5, sub_questions=3, queries=6, sources_found=2,
            sources_fetched=1, claims=4, contradictions=1, llm_calls=5,
            llm_provider="gemini", llm_model="gemini-2.5-flash", search_provider="exa",
        ),
    )


def test_markdown_has_all_sections_and_citations():
    md = render_markdown(_report())
    for heading in (
        "# Tidal energy",
        "## Executive summary",
        "## Key findings",
        "## Contradictions and disagreements",
        "## Open questions",
        "## Sources",
    ):
        assert heading in md, f"missing section: {heading}"
    assert "[S1]" in md and "[S2]" in md
    assert "*Sources:* [S1]" in md
    assert "severity: high" in md
    assert "S2 uses older data." in md
    assert "`gemini:gemini-2.5-flash`" in md
    assert "https://a.example" in md


def test_markdown_flags_sources_that_failed_to_load():
    report = _report()
    report.sources.append(Source(id="S3", url="https://c.example", error="Timeout: slow"))
    md = render_markdown(report)
    assert "not read" in md and "Timeout: slow" in md


def test_markdown_sorts_sources_numerically_not_lexically():
    report = _report()
    report.sources = [Source(id=f"S{i}", url=f"https://e/{i}") for i in (10, 2, 1)]
    md = render_markdown(report)
    assert md.index("[S1]") < md.index("[S2]") < md.index("[S10]")


def test_empty_report_renders_without_crashing():
    md = render_markdown(ResearchReport(topic="Nothing", executive_summary=""))
    assert "## Key findings" in md
    assert "No findings could be synthesized" in md
    assert "did not conflict" in md


def test_run_warnings_are_surfaced():
    report = _report()
    report.stats.errors = ["researcher[q2]: TimeoutError: boom"]
    assert "## Run warnings" in render_markdown(report)
    assert "researcher[q2]" in render_markdown(report)


def test_json_is_valid_and_round_trips():
    report = _report()
    payload = json.loads(render_json(report))
    assert payload["topic"] == "Tidal energy"
    assert payload["stats"]["llm_provider"] == "gemini"
    assert ResearchReport.model_validate(payload).topic == report.topic


def test_write_report_creates_parent_directories(tmp_path):
    paths = write_report(
        _report(), markdown_path=tmp_path / "deep" / "r.md", json_path=tmp_path / "deep" / "r.json"
    )
    assert len(paths) == 2
    assert all(p.exists() for p in paths)
    assert (tmp_path / "deep" / "r.md").read_text().startswith("# Tidal energy")


def test_write_report_is_a_noop_when_no_paths_given(tmp_path):
    assert write_report(_report()) == []
