"""httpx helper: retries on 429 and 5xx with exponential backoff, honouring Retry-After."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from app.core.errors import ProviderError
from app.core.logging import get_logger

log = get_logger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    ra = resp.headers.get("Retry-After")
    if not ra:
        return None
    try:
        return max(0.0, float(ra))
    except ValueError:
        return None


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    sleep: Any = asyncio.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request; retry on 429/5xx/network errors; raise ProviderError when exhausted."""
    attempt = 0
    last_error: str = ""
    while True:
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            resp = None
        if resp is not None:
            if resp.status_code < 400:
                return resp
            if resp.status_code not in RETRY_STATUSES:
                raise ProviderError(
                    f"HTTP {resp.status_code} from {provider}: {resp.text[:200]}",
                    provider=provider,
                    retryable=False,
                    status=resp.status_code,
                )
            last_error = f"HTTP {resp.status_code}"
        if attempt >= max_retries:
            raise ProviderError(
                f"{provider} failed after {attempt + 1} attempts ({last_error})",
                provider=provider,
                retryable=True,
                status=resp.status_code if resp is not None else None,
            )
        delay = min(max_delay, base_delay * (2**attempt)) + random.uniform(0, 0.25)
        if resp is not None:
            ra = _retry_after_seconds(resp)
            if ra is not None:
                delay = min(max_delay, max(delay, ra))
        log.info(
            "%s retry %d/%d in %.1fs (%s)", provider, attempt + 1, max_retries, delay, last_error
        )
        await sleep(delay)
        attempt += 1
