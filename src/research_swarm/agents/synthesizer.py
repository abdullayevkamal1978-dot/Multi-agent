"""Synthesis agent - merges the swarm's output into a cited report body.

The three sub-tasks (findings, executive summary, open questions) do not depend
on each other, so they are fired concurrently.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from research_swarm.agents.runtime import Runtime, render_sources
from research_swarm.models import (
    Claim,
    Contradiction,
    Finding,
    FindingSet,
    OpenQuestions,
    Source,
)

FINDINGS_SYSTEM = """You are the SYNTHESIS agent in a multi-agent research system.

You receive verified claims and cross-checked contradictions. Produce the
findings section of the final report.

Rules:
- Answer the research question directly. No filler, no restating the question.
- Every finding MUST cite its source ids inline. Never cite a source that is
  not in the provided list.
- Where the contradiction analysis found a conflict, say so in the finding
  itself instead of silently picking a side.
- `confidence` must reflect evidence strength, not writing flair. Use low
  confidence for thin or single-source findings.
- 3-7 findings. Order by importance, not by the order claims arrived.
"""

SUMMARY_SYSTEM = """You are the SYNTHESIS agent writing the executive summary of a
research report.

Write 3-5 sentences of plain prose suitable for a busy decision-maker:
- Lead with the single most important conclusion.
- State the confidence level honestly, including what is still contested.
- Reference the key citations inline in square brackets, e.g. [S2].
- No bullet points, no headings, no preamble like "This report...".
"""

QUESTIONS_SYSTEM = """You are the SYNTHESIS agent identifying what is still unknown.

List the most decision-relevant open questions that the evidence could NOT
answer. Each must be specific and researchable, and must not merely restate an
already-answered question. 3-5 questions.
"""

FINDINGS_USER = """TOPIC: {topic}
SCOPE: {scope}

Claims:
{claims}

Contradictions found by the cross-check agent:
{contradictions}

Sources:
{sources}
"""

MAX_SOURCES = 20


@dataclass
class SynthesisResult:
    findings: list[Finding] = field(default_factory=list)
    executive_summary: str = ""
    open_questions: list[str] = field(default_factory=list)


async def synthesize(
    runtime: Runtime,
    *,
    topic: str,
    scope: str,
    claims: list[Claim],
    contradictions: list[Contradiction],
    sources: list[Source],
) -> SynthesisResult:
    """Produce findings, an executive summary and open questions concurrently."""
    claim_lines = "\n".join(
        f"- {c.statement} (sources: {', '.join(c.source_ids) or 'none'}; conf={c.confidence:.2f})"
        for c in claims
    ) or "- (no claims were extracted)"
    contradiction_lines = "\n".join(
        f"- {x.description} [{', '.join(x.source_ids) or 'no citation'}] "
        f"severity={x.severity}; resolution: {x.resolution or 'unresolved'}"
        for x in contradictions
    ) or "- (no contradictions were found)"
    source_block = render_sources(sources[:MAX_SOURCES], max_chars_per_source=1200)

    findings_prompt = FINDINGS_USER.format(
        topic=topic,
        scope=scope or "(not specified)",
        claims=claim_lines,
        contradictions=contradiction_lines,
        sources=source_block,
    )
    summary_prompt = (
        f"TOPIC: {topic}\n\nClaims:\n{claim_lines}\n\n"
        f"Contradictions:\n{contradiction_lines}\n\nSources:\n{source_block}"
    )
    questions_prompt = (
        f"TOPIC: {topic}\n\nAlready answered by these claims:\n{claim_lines}\n\n"
        f"Still contested:\n{contradiction_lines}"
    )

    finding_set, summary, open_questions = await asyncio.gather(
        runtime.structured(FindingSet, system=FINDINGS_SYSTEM, user=findings_prompt),
        runtime.text(system=SUMMARY_SYSTEM, user=summary_prompt, temperature=0.2),
        runtime.structured(
            OpenQuestions, system=QUESTIONS_SYSTEM, user=questions_prompt
        ),
    )

    known = {s.id for s in sources}
    findings = []
    for finding in finding_set.findings:
        finding.source_ids = [sid for sid in finding.source_ids if sid in known]
        findings.append(finding)

    return SynthesisResult(
        findings=findings,
        executive_summary=summary.strip(),
        open_questions=[q.strip() for q in open_questions.questions if q.strip()],
    )
