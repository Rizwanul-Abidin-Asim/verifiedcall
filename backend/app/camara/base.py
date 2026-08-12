"""Shared transport for every CAMARA call.

Auth is two headers — no OAuth for our four APIs. See docs/camara-findings.md.

Policy, deliberately narrow:
- 3s timeout (settings.camara_timeout_s)
- retry on 5xx and transport errors only, never on 4xx (a 400 will fail identically)
- any failure falls through to fallback.py rather than propagating
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("camara")

RAPIDAPI_HOST = "network-as-code.nokia.rapidapi.com"
CAMARA_PREFIX = "/passthrough/camara/v1"


class CamaraError(Exception):
    """A CAMARA call that did not produce a usable response."""

    def __init__(self, api_name: str, detail: str, status_code: int | None = None,
                 body: str | None = None):
        self.api_name = api_name
        self.status_code = status_code
        self.body = body
        super().__init__(f"{api_name}: {detail}")


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Lazily built shared client. Connection reuse matters here — a cold connection
    costs ~1.1s against Nokia versus ~250ms warm."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.nokia_nac_base_url,
            timeout=httpx.Timeout(settings.camara_timeout_s),
            headers={
                "Content-Type": "application/json",
                "x-rapidapi-host": RAPIDAPI_HOST,
                "x-rapidapi-key": settings.nokia_nac_api_key,
            },
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def camara_post(api_name: str, path: str, payload: dict) -> tuple[Any, float]:
    """POST to Nokia and return (parsed_json, latency_ms).

    Raises CamaraError on any non-2xx or transport failure, after retrying 5xx.
    """
    attempts = settings.camara_max_retries + 1
    started = time.perf_counter()
    last: CamaraError | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = await get_client().post(path, json=payload)
        except httpx.HTTPError as exc:
            last = CamaraError(api_name, f"transport error: {exc!r}")
            log.warning("camara.transport_error api=%s attempt=%d err=%r",
                        api_name, attempt, exc)
        else:
            latency_ms = (time.perf_counter() - started) * 1000
            if response.is_success:
                log.info("camara.ok api=%s status=%d latency_ms=%.0f",
                         api_name, response.status_code, latency_ms)
                return response.json(), latency_ms

            last = CamaraError(api_name, f"HTTP {response.status_code}",
                               response.status_code, response.text)
            log.warning("camara.http_error api=%s status=%d body=%s",
                        api_name, response.status_code, response.text[:300])
            # 4xx is deterministic — retrying just burns latency budget.
            if response.status_code < 500:
                raise last

        if attempt < attempts:
            await asyncio.sleep(0.1 * attempt)

    raise last or CamaraError(api_name, "exhausted retries")


def with_fallback(api_name: str) -> Callable:
    """Wrap a client so a failure degrades to a cached response instead of raising.

    DEMO_MODE short-circuits to fallback without touching the network — the
    guaranteed-working path for a live pitch.
    """

    def decorator(fn: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
        @wraps(fn)
        async def wrapper(phone_number: str, *args, **kwargs):
            from app.camara.fallback import fallback_for  # local: avoids a cycle

            if settings.demo_mode:
                log.info("camara.demo_mode api=%s phone=%s", api_name, phone_number)
                return fallback_for(api_name, phone_number, reason="DEMO_MODE enabled")

            started = time.perf_counter()
            try:
                return await fn(phone_number, *args, **kwargs)
            except CamaraError as exc:
                # The failed attempt cost real wall-clock time — retries included. Report
                # it, or the added-latency metric we show judges understates reality.
                elapsed_ms = (time.perf_counter() - started) * 1000
                log.warning("camara.fallback api=%s phone=%s wasted_ms=%.0f reason=%s",
                            api_name, phone_number, elapsed_ms, exc)
                signal = fallback_for(api_name, phone_number, reason=str(exc))
                signal.latency_ms = elapsed_ms
                return signal

        return wrapper

    return decorator
