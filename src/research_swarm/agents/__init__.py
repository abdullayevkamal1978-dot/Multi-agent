"""The four specialist agents that make up the research swarm."""

from research_swarm.agents.contradiction import find_contradictions
from research_swarm.agents.planner import plan_research
from research_swarm.agents.researcher import research_subquestion
from research_swarm.agents.synthesizer import synthesize

__all__ = [
    "find_contradictions",
    "plan_research",
    "research_subquestion",
    "synthesize",
]
