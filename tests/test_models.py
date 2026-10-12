import pytest
from pydantic import ValidationError

from research_swarm.models import (
    Claim,
    Contradiction,
    ResearchReport,
    RunStats,
    Source,
    SubQuestion,
)


def test_sub_question_falls_back_to_question_when_no_queries():
    sub = SubQuestion(id="q1", question="What changed in 2026?", search_queries=[])
    assert sub.search_queries == ["What changed in 2026?"]


def test_sub_question_strips_blank_queries():
    sub = SubQuestion(id="q1", question="Q?", search_queries=["  real query  ", "", "   "])
    assert sub.search_queries == ["real query"]


def test_source_as_context_prefers_content_and_truncates():
    source = Source(id="S1", url="https://e.com/a", title="T", snippet="snip", content="x" * 500)
    rendered = source.as_context(max_chars=50)
    assert "[S1] T" in rendered and "https://e.com/a" in rendered
    assert "x" * 50 in rendered and "x" * 51 not in rendered


def test_source_as_context_falls_back_to_snippet():
    source = Source(id="S2", url="https://e.com/b", title="T", snippet="only snippet")
    assert "only snippet" in source.as_context(max_chars=100)


def test_report_source_index_and_defaults():
    report = ResearchReport(topic="t", executive_summary="s")
    assert isinstance(report.stats, RunStats)
    assert report.source_index() == {}
    report.sources.append(Source(id="S1", url="https://e.com"))
    assert set(report.source_index()) == {"S1"}


def test_confidence_must_be_within_range():
    with pytest.raises(ValidationError):
        Claim(id="c1", statement="s", confidence=1.5)
    with pytest.raises(ValidationError):
        Claim(id="c1", statement="s", confidence=-0.1)


def test_contradiction_severity_is_constrained():
    with pytest.raises(ValidationError):
        Contradiction(id="x1", topic="t", description="d", severity="catastrophic")
