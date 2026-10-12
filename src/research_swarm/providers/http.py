"""Shared async HTTP with bounded retries and a single connection pool."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from research_swarm.config import Settings

USER_AGENT = (
    "research-swarm/0.1 (+https://github.com/; multi-agent research assistant)"
)

_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
_client: httpx.AsyncClient | None = None


def get_client(settings: Settings) -> httpx.AsyncClient:
    """One pooled client per process; safe under asyncio concurrency."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en,*;q=0.5"},
        )
    return _client


async def aclose_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def request(
    method: str,
    url: str,
    *,
    settings: Settings,
    max_attempts: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP request, retrying transient failures with jittered backoff."""
    client = get_client(settings)
    last: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in _RETRY_STATUS and attempt < max_attempts:
                await asyncio.sleep(_backoff(attempt, response))
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last = exc
            if exc.response.status_code not in _RETRY_STATUS or attempt == max_attempts:
                raise
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last = exc
            if attempt == max_attempts:
                raise
        await asyncio.sleep(_backoff(attempt))

    raise httpx.HTTPError(f"request to {url} failed: {last}")


def _backoff(attempt: int, response: httpx.Response | None = None) -> float:
    retry_after = 0.0
    if response is not None:
        try:
            retry_after = float(response.headers.get("retry-after", "0") or 0)
        except ValueError:
            retry_after = 0.0
    return max(retry_after, min(8.0, (2 ** (attempt - 1)) + random.random()))
