from research_swarm.config import Settings


def test_provider_autodetects_from_present_keys():
    settings = Settings(gemini_api_key="k", tavily_api_key="t")
    assert settings.resolve_llm_provider() == "gemini"
    assert settings.resolve_search_provider() == "tavily"


def test_explicit_provider_wins_over_autodetect():
    settings = Settings(llm_provider="mock", search_provider="mock", gemini_api_key="k")
    assert settings.resolve_llm_provider() == "mock"
    assert settings.resolve_search_provider() == "mock"


def test_falls_back_to_mock_with_no_keys():
    settings = Settings()
    assert settings.resolve_llm_provider() == "mock"
    assert settings.resolve_search_provider() == "mock"


def test_default_models_per_provider():
    assert Settings().resolved_model("gemini") == "gemini-3.8-flash"
    assert Settings(llm_model="custom").resolved_model("openai") == "custom"


def test_as_dict_never_leaks_secrets():
    settings = Settings(gemini_api_key="SECRET_VALUE", tavily_api_key="ALSO_SECRET")
    dumped = repr(settings.as_dict())
    assert "SECRET" not in dumped


def test_with_overrides_is_immutable_and_selective():
    settings = Settings(llm_provider="mock")
    updated = settings.with_overrides(llm_provider=None, max_subquestions=9)
    assert settings.max_subquestions == 5
    assert updated.max_subquestions == 9
    assert updated.llm_provider == "mock"
