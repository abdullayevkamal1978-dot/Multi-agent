"""Deterministic offline LLM.

Purpose
-------
Make the entire multi-agent graph runnable with **no API key and no network**:
CI runs the real graph, tests assert on real state transitions, and `--mock`
gives a full end-to-end demo. Output is a pure function of the prompt, so runs
are reproducible.
"""

from __future__ import annotations

import re
from typing import Callable

from pydantic import BaseModel

from research_swarm.models import (
    Claim,
    ClaimSet,
    Contradiction,
    ContradictionSet,
    Finding,
    FindingSet,
    OpenQuestions,
    ResearchPlan,
    SubQuestion,
)

# Agents embed machine-readable markers in their prompts; the mock parses them.
_TOPIC_RE = re.compile(r"^TOPIC:\s*(.+)$", re.MULTILINE)
_QUESTION_RE = re.compile(r"^QUESTION:\s*(.+)$", re.MULTILINE)
_SOURCE_RE = re.compile(r"^### SOURCE (\S+) \| (.*?) \| (\S+)$", re.MULTILINE)

_ANGLE_TEMPLATES = [
    ("Current state", "What is the current state of {topic} as of today?"),
    ("Key evidence", "What hard evidence and data exist about {topic}?"),
    ("Arguments for", "What are the strongest arguments in favour regarding {topic}?"),
    ("Arguments against", "What are the strongest criticisms and counter-arguments about {topic}?"),
    ("Outlook", "What do credible projections say about where {topic} is heading?"),
]


class MockLLM:
    """Implements :class:`research_swarm.llm.StructuredLLM` without a provider."""

    name = "mock"

    def __init__(self, model: str = "mock-1"):
        self.model = model
        self._calls = 0

    @property
    def call_count(self) -> int:
        return self._calls

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def _topic(prompt: str) -> str:
        match = _TOPIC_RE.search(prompt)
        if match:
            return match.group(1).strip()
        for line in prompt.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "[", "{", '"')):
                return line[:160]
        return "the research topic"

    @staticmethod
    def _question(prompt: str) -> str:
        match = _QUESTION_RE.search(prompt)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _sources(prompt: str) -> list[tuple[str, str, str]]:
        return [(m.group(1), m.group(2), m.group(3)) for m in _SOURCE_RE.finditer(prompt)]

    # ---- builders ---------------------------------------------------------
    def _plan(self, prompt: str) -> ResearchPlan:
        topic = self._topic(prompt)
        wanted = 5
        match = re.search(r"at most (\d+)", prompt)
        if match:
            wanted = max(1, min(int(match.group(1)), len(_ANGLE_TEMPLATES)))
        subs = []
        for i, (label, template) in enumerate(_ANGLE_TEMPLATES[:wanted], start=1):
            question = template.format(topic=topic)
            subs.append(
                SubQuestion(
                    id=f"q{i}",
                    question=question,
                    rationale=f"Covers the '{label.lower()}' angle needed for a balanced report.",
                    search_queries=[f"{topic} {label.lower()}", f"{topic} research 2026"],
                )
            )
        return ResearchPlan(
            topic=topic,
            scope=f"Balanced, evidence-backed overview of {topic}; mock-mode scope.",
            sub_questions=subs,
        )

    def _claims(self, prompt: str) -> ClaimSet:
        sources = self._sources(prompt)
        topic = self._topic(prompt) or self._question(prompt)
        claims: list[Claim] = []
        for i, (sid, title, _url) in enumerate(sources, start=1):
            claims.append(
                Claim(
                    id=f"c{i}",
                    statement=f"{title.strip() or sid} reports a distinct finding about {topic}.",
                    source_ids=[sid],
                    topic=topic[:60] or "general",
                    confidence=round(0.55 + 0.05 * (i % 4), 2),
                    quote=f"Excerpt from {title.strip() or sid}.",
                )
            )
        return ClaimSet(claims=claims)

    def _contradictions(self, prompt: str) -> ContradictionSet:
        sources = self._sources(prompt)
        ids = [s[0] for s in sources]
        if len(ids) < 2:
            return ContradictionSet(contradictions=[])
        topic = self._topic(prompt) or "the topic"
        return ContradictionSet(
            contradictions=[
                Contradiction(
                    id="x1",
                    topic=topic[:60],
                    description=(
                        f"Mock analysis: {ids[0]} and {ids[1]} frame {topic} with differing "
                        "emphasis; the effect size is not stated consistently."
                    ),
                    positions=[
                        f"{ids[0]}: presents the optimistic reading.",
                        f"{ids[1]}: presents a more cautious reading.",
                    ],
                    source_ids=ids[:2],
                    severity="low",
                    resolution=(
                        "Mock mode cannot judge credibility from real content; "
                        "treated as unresolved pending a live model."
                    ),
                    confidence=0.35,
                )
            ]
        )

    def _findings(self, prompt: str, question: str) -> FindingSet:
        sources = self._sources(prompt)
        ids = [s[0] for s in sources]
        topic = self._topic(prompt) or question or "the topic"
        if not ids:
            return FindingSet(
                findings=[
                    Finding(
                        heading=topic[:80],
                        detail="No sources were retrieved, so no evidence could be synthesized.",
                        source_ids=[],
                        confidence=0.0,
                    )
                ]
            )
        half = max(1, len(ids) // 2)
        return FindingSet(
            findings=[
                Finding(
                    heading=f"Evidence base for {topic}"[:120],
                    detail=(
                        "Mock synthesis over the retrieved sources indicates a convergent "
                        f"picture across {len(ids)} documents."
                    ),
                    source_ids=ids[:half],
                    confidence=0.6,
                ),
                Finding(
                    heading=f"Open debate around {topic}"[:120],
                    detail="Remaining disagreement is concentrated in the sources below.",
                    source_ids=ids[half:],
                    confidence=0.45,
                ),
            ]
        )

    def _open_questions(self, prompt: str) -> OpenQuestions:
        topic = self._topic(prompt)
        return OpenQuestions(
            questions=[
                f"What primary data would settle the disputed points about {topic}?",
                f"How does {topic} change across regions and time horizons?",
                f"Which stakeholders are least represented in the current sources on {topic}?",
            ]
        )

    def _registry(self, question: str) -> dict[str, Callable[[str], BaseModel]]:
        return {
            "ResearchPlan": self._plan,
            "ClaimSet": self._claims,
            "ContradictionSet": self._contradictions,
            "FindingSet": lambda prompt: self._findings(prompt, question),
            "OpenQuestions": self._open_questions,
        }

    # ---- StructuredLLM protocol ------------------------------------------
    async def structured(self, schema, *, system: str, user: str, temperature: float = 0.0):
        self._calls += 1
        builder = self._registry(self._question(user)).get(schema.__name__)
        if builder is None:
            return schema.model_construct()
        result = builder(user)
        if not isinstance(result, schema):
            raise TypeError(f"mock builder for {schema.__name__} returned {type(result).__name__}")
        return result

    async def text(self, *, system: str, user: str, temperature: float = 0.0) -> str:
        self._calls += 1
        topic = self._topic(user)
        return (
            f"Across the retrieved sources, {topic} shows a broadly consistent picture, "
            "though sample quality and framing vary. The strongest evidence supports the "
            "central findings below; the remainder of the disagreement is recorded as an "
            "open question rather than smoothed over. (Generated in offline mock mode - "
            "set an LLM API key for a real analysis.)"
        )
