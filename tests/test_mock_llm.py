"""The mock LLM must be a deterministic pure function of the prompt."""

from research_swarm.mock_llm import MockLLM
from research_swarm.models import (
    ClaimSet,
    ContradictionSet,
    FindingSet,
    OpenQuestions,
    ResearchPlan,
)

PROMPT = """TOPIC: quantum error correction

### SOURCE S1 | Alpha | https://a.example/1
The threshold was reached in 2026.

### SOURCE S2 | Beta | https://b.example/2
A different team disputes the threshold.
"""


async def test_plan_is_deterministic_and_respects_limit():
    llm = MockLLM()
    prompt = "TOPIC: quantum error correction\n\nProduce at most 3 sub-questions."
    first = await llm.structured(ResearchPlan, system="x", user=prompt)
    second = await llm.structured(ResearchPlan, system="x", user=prompt)
    assert first == second
    assert len(first.sub_questions) == 3
    assert all(s.search_queries for s in first.sub_questions)


async def test_claims_cite_only_sources_present_in_the_prompt():
    llm = MockLLM()
    result = await llm.structured(ClaimSet, system="x", user=PROMPT)
    cited = {sid for claim in result.claims for sid in claim.source_ids}
    assert cited == {"S1", "S2"}


async def test_contradiction_needs_at_least_two_sources():
    llm = MockLLM()
    single = "TOPIC: t\n\n### SOURCE S1 | A | https://a.example/1\n"
    empty = await llm.structured(ContradictionSet, system="x", user=single)
    assert empty.contradictions == []

    both = await llm.structured(ContradictionSet, system="x", user=PROMPT)
    assert len(both.contradictions) == 1
    assert set(both.contradictions[0].source_ids) == {"S1", "S2"}


async def test_findings_and_questions_are_produced():
    llm = MockLLM()
    findings = await llm.structured(FindingSet, system="x", user=PROMPT)
    assert findings.findings and all(f.source_ids for f in findings.findings)
    questions = await llm.structured(OpenQuestions, system="x", user=PROMPT)
    assert len(questions.questions) >= 3


async def test_text_records_the_topic_and_counts_calls():
    llm = MockLLM()
    before = llm.call_count
    text = await llm.text(system="x", user="TOPIC: tidal energy\n\nbody")
    assert "tidal energy" in text
    assert llm.call_count == before + 1
