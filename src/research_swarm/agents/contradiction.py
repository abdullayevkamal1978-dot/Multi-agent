"""Contradiction agent - the system's cross-checking step.

This is the part a single-shot LLM summary cannot do: claims gathered from
different sources are compared against each other, disagreements are named
explicitly, and each one gets a judgement instead of being averaged away.
"""

from __future__ import annotations

from research_swarm.agents.runtime import Runtime, render_sources
from research_swarm.models import Claim, Contradiction, ContradictionSet, Source

SYSTEM = """You are the CONTRADICTION (cross-check) agent in a multi-agent research system.

You receive claims extracted independently by several researcher agents, plus
the sources they came from. Your only job is to find where the evidence
actually conflicts.

Rules:
- A contradiction is a *factual* conflict: different numbers, dates, causal
  claims, or opposite conclusions about the same thing. Tone and emphasis
  differences are NOT contradictions.
- Cite the claim ids and source ids involved in every contradiction.
- Never invent a conflict to look thorough. If the sources agree, return an
  empty list. An empty list is a correct and valuable answer.
- Severity: high = changes the practical conclusion; medium = changes the
  magnitude; low = detail-level disagreement.
- `resolution`: state which position the evidence favours and why (recency,
  sample size, primary vs secondary source). If it is genuinely unresolved,
  say so and say what would settle it. Do not pretend to resolve it.
"""

USER_TEMPLATE = """TOPIC: {topic}

Claims (id | topic | confidence | cited sources | statement):
{claims}

Sources:
{sources}

Find every genuine contradiction among these claims.
"""

MAX_SOURCES = 15
MAX_CLAIMS = 40


async def find_contradictions(
    runtime: Runtime,
    *,
    topic: str,
    claims: list[Claim],
    sources: list[Source],
) -> list[Contradiction]:
    """Return typed contradictions; empty when the evidence is consistent."""
    if len(claims) < 2 or len(sources) < 2:
        return []

    claim_lines = "\n".join(
        f"- {c.id} | {c.topic} | conf={c.confidence:.2f} | sources={c.source_ids or ['none']} | {c.statement}"
        for c in claims[:MAX_CLAIMS]
    )
    source_block = render_sources(sources[:MAX_SOURCES], max_chars_per_source=1200)

    result = await runtime.structured(
        ContradictionSet,
        system=SYSTEM,
        user=USER_TEMPLATE.format(topic=topic, claims=claim_lines, sources=source_block),
        temperature=0.1,
    )
    return _sanitize(result.contradictions, claims, sources)


def _sanitize(
    contradictions: list[Contradiction], claims: list[Claim], sources: list[Source]
) -> list[Contradiction]:
    """Drop citations to things that do not exist, and de-duplicate."""
    known_sources = {s.id for s in sources}
    known_claims = {c.id for c in claims}
    seen: set[str] = set()
    cleaned: list[Contradiction] = []

    for index, item in enumerate(contradictions, start=1):
        item.id = item.id.strip() or f"x{index}"
        if item.id in seen:
            item.id = f"x{index}"
        seen.add(item.id)
        item.source_ids = [sid for sid in item.source_ids if sid in known_sources]
        referenced = {sid for sid in item.source_ids}
        if not referenced:
            # Fall back to the citations of the claims it points at.
            for cid in item.source_ids:
                if cid in known_claims:
                    continue
            for claim in claims:
                if claim.id in known_claims and claim.id in item.description:
                    referenced.update(claim.source_ids)
            item.source_ids = sorted(referenced)
        cleaned.append(item)
    return cleaned
