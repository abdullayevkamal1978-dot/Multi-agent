"""LLM layer.

Two implementations behind one tiny protocol:

* ``LangChainLLM`` - real provider (Gemini / OpenAI / Anthropic) reached through
  LangChain, using ``with_structured_output`` so every agent gets a Pydantic
  object back instead of prose.
* ``MockLLM`` - deterministic, offline, zero-key. It makes the whole graph
  runnable and testable without spending a cent, and gives the agents stable
  fixtures to assert against.

Keeping the protocol this small means the multi-agent graph never has to know
which backend it is talking to.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from research_swarm.config import Settings

TModel = TypeVar("TModel", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the underlying model call fails after retries."""


@runtime_checkable
class StructuredLLM(Protocol):
    """What an agent needs from a language model."""

    name: str
    model: str

    async def structured(
        self,
        schema: type[TModel],
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
    ) -> TModel: ...

    async def text(self, *, system: str, user: str, temperature: float = 0.0) -> str: ...

    @property
    def call_count(self) -> int: ...


class _BaseLLM:
    """Shared retry / bookkeeping."""

    name = "base"

    def __init__(self, model: str, *, max_attempts: int = 3, retry_delay: float = 1.5):
        self.model = model
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._calls = 0

    @property
    def call_count(self) -> int:
        return self._calls

    async def _with_retry(self, label: str, fn, *args, **kwargs):
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                self._calls += 1
                return await fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raised below
                last = exc
                if attempt == self._max_attempts:
                    break
                await asyncio.sleep(self._retry_delay * attempt)
        raise LLMError(f"{label} failed after {self._max_attempts} attempts: {last}") from last


class LangChainLLM(_BaseLLM):
    """Real provider via LangChain chat models."""

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        *,
        temperature: float = 0.0,
        thinking_budget: int | None = None,
    ):
        super().__init__(model)
        self.name = provider
        self._temperature = temperature
        self._client = self._build_client(provider, model, api_key, thinking_budget)

    def _temperature_for(self, temperature: float) -> float:
        return self._temperature if temperature is None else float(temperature)

    @staticmethod
    def _build_client(
        provider: str, model: str, api_key: str, thinking_budget: int | None = None
    ):
        if provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
            except ImportError as exc:  # pragma: no cover
                raise LLMError(
                    "Gemini selected but langchain-google-genai is missing. "
                    "Install it with: uv pip install 'research-swarm[google]'"
                ) from exc
            gemini_kwargs: dict = {
                "model": model,
                "google_api_key": api_key,
                "temperature": 0.0,
                "max_retries": 0,
            }
            if thinking_budget is not None:
                gemini_kwargs["thinking_budget"] = thinking_budget
            return ChatGoogleGenerativeAI(**gemini_kwargs)
        if provider == "openai":
            try:
                from langchain_openai import ChatOpenAI
            except ImportError as exc:  # pragma: no cover
                raise LLMError(
                    "OpenAI selected but langchain-openai is missing. "
                    "Install it with: uv pip install 'research-swarm[openai]'"
                ) from exc
            return ChatOpenAI(model=model, api_key=api_key, temperature=0.0, max_retries=0)
        if provider == "anthropic":
            try:
                from langchain_anthropic import ChatAnthropic
            except ImportError as exc:  # pragma: no cover
                raise LLMError(
                    "Anthropic selected but langchain-anthropic is missing. "
                    "Install it with: uv pip install 'research-swarm[anthropic]'"
                ) from exc
            return ChatAnthropic(model=model, api_key=api_key, temperature=0.0, max_retries=0)
        raise LLMError(f"Unknown LLM provider: {provider!r}")

    async def structured(
        self,
        schema: type[TModel],
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
    ) -> TModel:
        runnable = self._client.with_structured_output(schema)

        async def _invoke() -> TModel:
            messages = [("system", system), ("human", user)]
            # Per-call temperature travels as a bound model kwarg.
            bound = runnable.bind(temperature=self._temperature_for(temperature))
            result = await bound.ainvoke(messages)
            if isinstance(result, schema):
                return result
            return schema.model_validate(result)

        return await self._with_retry(f"{self.name}.structured", _invoke)

    async def text(self, *, system: str, user: str, temperature: float = 0.0) -> str:
        async def _invoke() -> str:
            bound = self._client.bind(temperature=self._temperature_for(temperature))
            msg = await bound.ainvoke([("system", system), ("human", user)])
            content = getattr(msg, "content", msg)
            if isinstance(content, list):  # multimodal-style blocks
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            return str(content)

        return await self._with_retry(f"{self.name}.text", _invoke)


# MockLLM lives in its own module to keep this file about the real backend.
from research_swarm.mock_llm import MockLLM  # noqa: E402


def build_llm(settings: Settings) -> StructuredLLM:
    """Pick a provider from settings and construct the LLM."""
    provider = settings.resolve_llm_provider()
    model = settings.resolved_model(provider)
    if provider == "mock":
        return MockLLM(model)
    api_key = settings.key_for_llm(provider)
    if not api_key:
        raise LLMError(
            f"Provider {provider!r} selected but no API key found. "
            f"Set {provider.upper()}_API_KEY, or run with --mock."
        )
    return LangChainLLM(
        provider, model, api_key, thinking_budget=settings.gemini_thinking_budget
    )


__all__ = [
    "LLMError",
    "LangChainLLM",
    "MockLLM",
    "StructuredLLM",
    "build_llm",
]
