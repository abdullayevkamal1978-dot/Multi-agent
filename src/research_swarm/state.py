"""LangGraph state schema.

The ``sources``/``claims``/``errors``/``events`` channels carry
``operator.add`` reducers, which is what makes the parallel fan-out safe:
every branch appends to the same list instead of overwriting it.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from research_swarm.models import (
    Claim,
    Contradiction,
    Finding,
    ResearchPlan,
    ResearchReport,
    Source,
    SubQuestion,
)


class ResearchState(TypedDict, total=False):
    topic: str
    plan: ResearchPlan

    # Written by the fan-out branches -> reduced with list concatenation.
    sub_question: SubQuestion
    sources: Annotated[list[Source], operator.add]
    claims: Annotated[list[Claim], operator.add]
    errors: Annotated[list[str], operator.add]
    events: Annotated[list[str], operator.add]

    # Written by the single-node stages.
    contradictions: list[Contradiction]
    findings: list[Finding]
    executive_summary: str
    open_questions: list[str]
    report: ResearchReport
