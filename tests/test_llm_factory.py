"""LLM factory: provider selection, missing keys, Gemini kwargs wiring."""

import pytest

from research_swarm.config import Settings
from research_swarm.llm import LLMError, LangChainLLM, MockLLM, build_llm


def test_mock_provider_yields_mock_llm():
    assert isinstance(build_llm(Settings(llm_provider="mock")), MockLLM)


def test_missing_key_raises_a_helpful_error():
    settings = Settings(llm_provider="openai", openai_api_key="")
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        build_llm(settings)


def test_unknown_provider_is_rejected():
    with pytest.raises(LLMError, match="Unknown LLM provider"):
        LangChainLLM("not-a-provider", "m", "k")


def test_gemini_client_accepts_a_thinking_budget():
    """Construction only - no network call is made."""
    llm = LangChainLLM("gemini", "gemini-3.8-flash", "fake-key", thinking_budget=0)
    assert llm.name == "gemini"
    assert llm.model == "gemini-3.8-flash"
    assert llm.call_count == 0


def test_temperature_helper_falls_back_to_constructor_default():
    llm = LangChainLLM("gemini", "m", "k", temperature=0.3)
    assert llm._temperature_for(None) == 0.3
    assert llm._temperature_for(0.9) == 0.9


def test_mock_llm_counts_calls():
    llm = MockLLM()
    assert llm.call_count == 0


def test_thinking_budget_is_read_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", "0")
    assert Settings.from_env(env_file=None).gemini_thinking_budget == 0
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", "")
    assert Settings.from_env(env_file=None).gemini_thinking_budget is None
    monkeypatch.delenv("GEMINI_THINKING_BUDGET")
    assert Settings.from_env(env_file=None).gemini_thinking_budget is None
