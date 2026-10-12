"""research-swarm — a multi-agent deep-research system built on LangGraph."""

__version__ = "0.1.0"

from research_swarm.config import Settings
from research_swarm.models import (
    Claim,
    Contradiction,
    Finding,
    ResearchPlan,
    ResearchReport,
    RunStats,
    Source,
    SubQuestion,
)

from research_swarm.report import render_html, render_json, render_markdown, render_pdf  # noqa: E402
from research_swarm.runner import run_research  # noqa: E402

__all__ = [
    "__version__",
    "Settings",
    "render_json",
    "render_html",
    "render_pdf",
    "render_markdown",
    "run_research",
    "Claim",
    "Contradiction",
    "Finding",
    "ResearchPlan",
    "ResearchReport",
    "RunStats",
    "Source",
    "SubQuestion",
]
