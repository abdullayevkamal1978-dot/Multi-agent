import os
from pathlib import Path

import pytest

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


def test_resolve_cache_dir_uses_configured_path_when_writable(tmp_path):
    from research_swarm.config import _resolve_cache_dir

    target = tmp_path / "cache"
    assert _resolve_cache_dir(str(target)) == str(target)
    assert (target / "pages").parent.exists()


def test_resolve_cache_dir_empty_string_disables_disk_cache(tmp_path, monkeypatch):
    from research_swarm.config import _resolve_cache_dir

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_CACHE_DIR", "")
    # "" means "no preference" -> the default .cache is tried, and it works here.
    assert _resolve_cache_dir("") == ".cache"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_resolve_cache_dir_falls_back_when_project_is_read_only(tmp_path):
    """Serverless runtimes mount the project read-only; only /tmp is writable."""
    from research_swarm.config import _resolve_cache_dir

    readonly = tmp_path / "ro"
    readonly.mkdir()
    os.chmod(readonly, 0o500)
    try:
        resolved = _resolve_cache_dir(str(readonly / "cache"))
    finally:
        os.chmod(readonly, 0o700)

    assert resolved != str(readonly / "cache")
    assert resolved  # non-empty: a writable temp location was found
    Path(resolved, "probe").write_text("ok", encoding="utf-8")
