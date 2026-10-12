"""Domain model for the research pipeline.

Every LLM call in this project returns one of these Pydantic models via
structured output, so downstream agents consume typed data instead of prose.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["low", "medium", "high"]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SubQuestion(BaseModel):
    """One independently researchable slice of the topic."""

    id: str = Field(description="Short stable id, e.g. 'q1'.")
    question: str = Field(description="A specific, answerable research question.")
    rationale: str = Field(default="", description="Why answering this matters.")
    search_queries: list[str] = Field(
        default_factory=list,
        description="2-4 web search queries that would surface evidence for this question.",
    )

    @field_validator("search_queries")
    @classmethod
    def _ensure_queries(cls, value: list[str], info) -> list[str]:
        value = [q.strip() for q in value if q and q.strip()]
        if value:
            return value
        question = info.data.get("question", "")
        return [question] if question else []


class ResearchPlan(BaseModel):
    """Output of the planner agent."""

    topic: str
    scope: str = Field(default="", description="What is in and out of scope for this run.")
    sub_questions: list[SubQuestion] = Field(default_factory=list)


class Source(BaseModel):
    """A single retrieved web document."""

    id: str = Field(description="Citation id used in the report, e.g. 'S3'.")
    url: str
    title: str = ""
    snippet: str = ""
    content: str = Field(default="", description="Extracted readable text, truncated.")
    published: str | None = None
    provider: str = Field(default="", description="Which search backend produced this result.")
    query: str = Field(default="", description="The query that surfaced this source.")
    score: float | None = None
    fetched: bool = False
    error: str | None = None

    def as_context(self, max_chars: int) -> str:
        body = self.content or self.snippet
        body = body[:max_chars]
        return f"[{self.id}] {self.title}\nURL: {self.url}\n{body}"


class Claim(BaseModel):
    """An atomic, checkable statement extracted from the sources."""

    id: str = Field(description="Short stable id, e.g. 'c1'.")
    statement: str
    source_ids: list[str] = Field(default_factory=list)
    topic: str = Field(default="", description="Cluster label, reused across sources.")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    quote: str = Field(default="", description="Supporting excerpt from the source, if any.")


class Contradiction(BaseModel):
    """A disagreement between sources, plus a judgement about who is right."""

    id: str = Field(description="Short stable id, e.g. 'x1'.")
    topic: str
    description: str = Field(description="What exactly the sources disagree about.")
    positions: list[str] = Field(
        default_factory=list,
        description="Each conflicting position with its source citations inline.",
    )
    source_ids: list[str] = Field(default_factory=list)
    severity: Severity = "medium"
    resolution: str = Field(
        default="",
        description="Which position the evidence favours, and why. Empty if genuinely unresolved.",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class Finding(BaseModel):
    """A synthesized, cited answer to a sub-question."""

    heading: str
    detail: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class RunStats(BaseModel):
    """Observability for one research run."""

    started_at: str = Field(default_factory=_utcnow_iso)
    finished_at: str | None = None
    duration_seconds: float | None = None
    sub_questions: int = 0
    queries: int = 0
    sources_found: int = 0
    sources_fetched: int = 0
    claims: int = 0
    contradictions: int = 0
    llm_calls: int = 0
    search_calls: int = 0
    errors: list[str] = Field(default_factory=list)
    llm_provider: str = ""
    llm_model: str = ""
    search_provider: str = ""


class ResearchReport(BaseModel):
    """The final artifact handed back to the user."""

    topic: str
    executive_summary: str
    scope: str = ""
    findings: list[Finding] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    stats: RunStats = Field(default_factory=RunStats)
    generated_at: str = Field(default_factory=_utcnow_iso)

    def source_index(self) -> dict[str, Source]:
        return {s.id: s for s in self.sources}


# ---------------------------------------------------------------------------
# Container schemas.
# Structured-output APIs model a *single* object more reliably than a bare
# list, so agents ask for these wrappers and unwrap them afterwards.
# ---------------------------------------------------------------------------
class ClaimSet(BaseModel):
    claims: list[Claim] = Field(default_factory=list)


class ContradictionSet(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)


class FindingSet(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


class OpenQuestions(BaseModel):
    questions: list[str] = Field(default_factory=list)
