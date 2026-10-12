"""Shared fixtures. Every test runs fully offline - no API keys, no network."""

from __future__ import annotations

import pytest

from research_swarm.config import Settings


def mock_settings(tmp_path=None, **overrides) -> Settings:
    """Settings forced into offline mock mode."""
    base = dict(
        llm_provider="mock",
        llm_model="mock-1",
        search_provider="mock",
        max_subquestions=overrides.pop("max_subquestions", 4),
        results_per_query=overrides.pop("results_per_query", 3),
        max_concurrency=overrides.pop("max_concurrency", 5),
        max_content_chars=4000,
        request_timeout=5.0,
        cache_dir=str(tmp_path / "cache") if tmp_path is not None else ".cache-test",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings(tmp_path):
    return mock_settings(tmp_path)
