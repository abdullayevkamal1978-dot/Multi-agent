"""Runtime configuration, resolved from environment variables / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

LLM_PROVIDERS = ("gemini", "openai", "anthropic", "mock")
SEARCH_PROVIDERS = ("exa", "tavily", "serpapi", "gemini", "mock")

_DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
    "mock": "mock-1",
}

_LLM_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

_SEARCH_KEY_ENV = {
    "exa": "EXA_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "serpapi": "SERPAPI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_optional_int(name: str) -> int | None:
    """None means 'leave the provider default alone'."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """All knobs for one research run."""

    llm_provider: str = "auto"
    llm_model: str = ""
    search_provider: str = "auto"

    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    exa_api_key: str = ""
    tavily_api_key: str = ""
    serpapi_api_key: str = ""

    gemini_thinking_budget: int | None = None

    max_subquestions: int = 5
    results_per_query: int = 5
    max_concurrency: int = 5
    max_content_chars: int = 6000
    request_timeout: float = 30.0
    cache_dir: str = ".cache"

    # ---- construction -----------------------------------------------------
    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] | None = ".env") -> "Settings":
        if load_dotenv is not None and env_file and Path(env_file).exists():
            load_dotenv(env_file, override=False)
        return cls(
            llm_provider=(os.getenv("LLM_PROVIDER") or "auto").strip().lower(),
            llm_model=(os.getenv("LLM_MODEL") or "").strip(),
            search_provider=(os.getenv("SEARCH_PROVIDER") or "auto").strip().lower(),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
            exa_api_key=os.getenv("EXA_API_KEY", "").strip(),
            tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
            serpapi_api_key=os.getenv("SERPAPI_API_KEY", "").strip(),
            gemini_thinking_budget=_env_optional_int("GEMINI_THINKING_BUDGET"),
            max_subquestions=_env_int("RESEARCH_MAX_SUBQUESTIONS", 5),
            results_per_query=_env_int("RESEARCH_RESULTS_PER_QUERY", 5),
            max_concurrency=_env_int("RESEARCH_MAX_CONCURRENCY", 5),
            max_content_chars=_env_int("RESEARCH_MAX_CONTENT_CHARS", 6000),
            request_timeout=_env_float("RESEARCH_TIMEOUT_SECONDS", 30.0),
            cache_dir=os.getenv("RESEARCH_CACHE_DIR", ".cache").strip() or ".cache",
        )

    # ---- provider resolution ---------------------------------------------
    def key_for_llm(self, provider: str) -> str:
        return {
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }.get(provider, "")

    def key_for_search(self, provider: str) -> str:
        return {
            "exa": self.exa_api_key,
            "tavily": self.tavily_api_key,
            "serpapi": self.serpapi_api_key,
            "gemini": self.gemini_api_key,
        }.get(provider, "")

    def resolve_llm_provider(self) -> str:
        """Explicit setting wins; otherwise first provider with a key; else mock."""
        if self.llm_provider and self.llm_provider != "auto":
            return self.llm_provider
        for provider in ("gemini", "openai", "anthropic"):
            if self.key_for_llm(provider):
                return provider
        return "mock"

    def resolve_search_provider(self) -> str:
        if self.search_provider and self.search_provider != "auto":
            return self.search_provider
        for provider in ("exa", "tavily", "serpapi"):
            if self.key_for_search(provider):
                return provider
        # Gemini grounding is a valid fallback, but only worth using when the
        # same key is present and the user asked for it (it is billed).
        return "mock"

    def resolved_model(self, provider: str | None = None) -> str:
        provider = provider or self.resolve_llm_provider()
        if self.llm_model:
            return self.llm_model
        env_name = f"{provider.upper()}_MODEL"
        return os.getenv(env_name, "").strip() or _DEFAULT_MODELS.get(provider, provider)

    def with_overrides(self, **kwargs) -> "Settings":
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean)

    def as_dict(self) -> dict[str, object]:
        """Safe to log: never includes secret values."""
        return {
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "search_provider": self.search_provider,
            "max_subquestions": self.max_subquestions,
            "results_per_query": self.results_per_query,
            "max_concurrency": self.max_concurrency,
            "max_content_chars": self.max_content_chars,
            "request_timeout": self.request_timeout,
        }
