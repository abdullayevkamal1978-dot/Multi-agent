"""Planner agent - decomposes a topic into independently researchable questions."""

from __future__ import annotations

from research_swarm.agents.runtime import Runtime
from research_swarm.models import ResearchPlan

SYSTEM = """You are the PLANNER agent in a multi-agent research system.

Your job: turn a broad topic into a small set of independently researchable
sub-questions that, taken together, produce a balanced and evidence-backed
report.

Rules:
- Decompose by *angle* (current state, hard evidence, strongest case for,
  strongest case against, credible outlook), not by vague subtopic.
- Each sub-question must be specific and answerable from public sources.
- Provide 2-4 distinct web-search queries per sub-question. Queries should be
  keyword-rich, not full sentences.
- Prefer 4-6 sub-questions. Do not pad.
- Never answer the question yourself. Plan only.
"""

USER_TEMPLATE = """TOPIC: {topic}

Produce at most {max_subquestions} sub-questions for this topic.
Make the plan balanced: include at least one angle that challenges the
mainstream view, so contradictions between sources can surface later.
"""


async def plan_research(runtime: Runtime, topic: str) -> ResearchPlan:
    """Return a typed research plan for ``topic``."""
    plan = await runtime.structured(
        ResearchPlan,
        system=SYSTEM,
        user=USER_TEMPLATE.format(
            topic=topic, max_subquestions=runtime.settings.max_subquestions
        ),
    )
    plan.topic = plan.topic or topic

    # Defensive normalisation: the LLM may over-produce or repeat ids.
    seen: set[str] = set()
    cleaned = []
    for index, sub in enumerate(plan.sub_questions, start=1):
        sub.id = sub.id.strip() or f"q{index}"
        if sub.id in seen:
            sub.id = f"q{index}"
        seen.add(sub.id)
        cleaned.append(sub)
    plan.sub_questions = cleaned[: runtime.settings.max_subquestions]
    if not plan.sub_questions:
        # Degenerate plan would stall the graph; fall back to researching the topic.
        from research_swarm.models import SubQuestion

        plan.sub_questions = [
            SubQuestion(
                id="q1",
                question=f"What is the current, evidence-backed state of {topic}?",
                rationale="Fallback sub-question generated because the planner returned none.",
                search_queries=[topic],
            )
        ]
    return plan
