"""Researcher agent - one per sub-question, all running in parallel.

Pipeline per branch:  search -> dedupe -> read pages -> extract claims.
"""

from __future__ import annotations

import asyncio

from research_swarm.agents.runtime import Runtime, dedupe_hits, render_sources
from research_swarm.models import Claim, ClaimSet, Source, SubQuestion

SYSTEM = """You are the RESEARCHER agent in a multi-agent research system.

You receive numbered source excerpts for exactly one sub-question. Extract the
factual claims that the sources actually support - not your own opinion.

Rules:
- One claim per distinct fact, number or position. Keep claims atomic.
- Every claim MUST cite the source ids that support it (e.g. ["S3"]). Never
  cite a source that does not contain the claim.
- Put a short verbatim excerpt from the source in `quote`.
- Reuse the same short `topic` label for claims about the same subject; the
  contradiction agent groups by that label later.
- `confidence` reflects evidence quality in the supplied sources only.
- If the sources contain nothing usable, return an empty list of claims.
"""

USER_TEMPLATE = """QUESTION: {question}

Sources for this question:

{sources}
"""

MAX_CLAIMS_PER_QUESTION = 8


async def research_subquestion(
    runtime: Runtime, sub_question: SubQuestion, *, topic: str
) -> tuple[list[Source], list[Claim]]:
    """Research one sub-question. Returns ``(sources, claims)``."""
    settings = runtime.settings

    hits = await runtime.search_queries(
        sub_question.search_queries, max_results=settings.results_per_query
    )
    hits = dedupe_hits(hits)[: settings.results_per_query]
    if not hits:
        return [], []

    # Same URL => same citation id, even across parallel branches.
    ids = await runtime.citation_ids([hit.url for hit in hits])
    sources = [
        Source(
            id=source_id,
            url=hit.url,
            title=(hit.title or hit.url).strip(),
            snippet=(hit.snippet or "").strip()[:1000],
            published=hit.published,
            provider=hit.extra.get("provider", runtime.search.name),
            query=hit.extra.get("query", ""),
            score=hit.score,
            content=(hit.content or "").strip()[: settings.max_content_chars],
        )
        for source_id, hit in zip(ids, hits)
    ]

    # Read the pages concurrently. Providers that already return full text skip this.
    await asyncio.gather(*(_read(runtime, source) for source in sources))
    usable = [s for s in sources if (s.content or s.snippet).strip()]
    if not usable:
        return sources, []

    context = render_sources(usable, max_chars_per_source=settings.max_content_chars)
    claim_set = await runtime.structured(
        ClaimSet,
        system=SYSTEM,
        user=USER_TEMPLATE.format(question=sub_question.question, sources=context),
    )
    claims = _normalize_claims(claim_set.claims, sub_question, usable)
    return sources, claims


async def _read(runtime: Runtime, source: Source) -> None:
    """Populate ``source.content`` in place; record failures instead of raising."""
    if source.content:
        if not await runtime.fetcher.is_allowed_by_robots(source.url):
            source.content = ""
            source.snippet = ""
            source.error = "blocked by robots.txt (or robots policy unavailable)"
            source.fetched = False
            return
        source.fetched = True
        return
    title, text, error = await runtime.fetcher.fetch(source.url)
    if error:
        source.error = error
        source.fetched = False
        if error.startswith("blocked by robots.txt"):
            source.content = ""
            source.snippet = ""
        return
    source.fetched = True
    if title and (not source.title or source.title == source.url):
        source.title = title
    source.content = text[: runtime.settings.max_content_chars]
    if text and not source.snippet:
        source.snippet = text[:400]


def _normalize_claims(
    raw_claims: list[Claim], sub_question: SubQuestion, sources: list[Source]
) -> list[Claim]:
    """Make claim ids unique across parallel branches and drop invented citations."""
    valid_ids = {s.id for s in sources}
    seen: set[str] = set()
    normalized: list[Claim] = []
    for index, claim in enumerate(raw_claims[:MAX_CLAIMS_PER_QUESTION], start=1):
        claim.id = f"c-{sub_question.id}-{index}"
        if claim.id in seen:
            continue
        seen.add(claim.id)
        claim.source_ids = [sid for sid in claim.source_ids if sid in valid_ids]
        if not claim.source_ids:
            # An uncited claim is unverifiable; keep the text but flag low trust.
            claim.confidence = min(claim.confidence, 0.2)
        claim.topic = (claim.topic or sub_question.question)[:80]
        normalized.append(claim)
    return normalized
