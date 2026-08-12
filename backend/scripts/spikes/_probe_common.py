"""Minimal shared plumbing for the Phase 1 spikes.

Deliberately tiny. The spikes are meant to stay independent and slightly duplicative
(see PROMPT 1) — this only holds the two things that would otherwise be copied wrong:
the header pair and the raw dump format.
"""

import json
import sys
import time

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402

RAPIDAPI_HOST = "network-as-code.nokia.rapidapi.com"


def headers() -> dict:
    return {
        "Content-Type": "application/json",
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": settings.nokia_nac_api_key,
    }


def probe(name: str, path: str, body: dict) -> None:
    """Make ONE real call and dump everything about it, unparsed."""
    url = settings.nokia_nac_base_url + path
    print("=" * 78)
    print(f"{name}\nPOST {url}\nrequest: {json.dumps(body)}")
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(url, headers=headers(), json=body)
    except Exception as exc:  # noqa: BLE001 — spikes must never swallow anything
        print(f"TRANSPORT ERROR after {(time.perf_counter() - started) * 1000:.0f}ms: {exc!r}")
        return
    latency_ms = (time.perf_counter() - started) * 1000
    print(f"status : {response.status_code}")
    print(f"latency: {latency_ms:.0f}ms")
    print(f"headers: {dict(response.headers)}")
    print(f"body   : {response.text}")


def phone_from_argv(default: str) -> str:
    return sys.argv[1] if len(sys.argv) > 1 else default
