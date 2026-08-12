"""Phase 1 spike: which sandbox number produces which COMBINATION of signals?

The four demo scenarios need genuinely different signal profiles. If every "risky"
scenario uses the same MSISDN it produces identical signals, and "why did this one
decline but that one get a call?" has no good answer.

Run:  uv run python scripts/spikes/probe_signal_matrix.py
"""

import asyncio
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402

HEADERS = {
    "Content-Type": "application/json",
    "x-rapidapi-host": "network-as-code.nokia.rapidapi.com",
    "x-rapidapi-key": settings.nokia_nac_api_key,
}
CAMARA = "/passthrough/camara/v1"
AREA = {"areaType": "CIRCLE", "center": {"latitude": 50.735851, "longitude": 7.10066},
        "radius": 50000}

NUMBERS = [f"+9999999{n}" for n in (1000, 1001, 1002, 1003, 1004, 1005, 1111, 1112)]

CALLS = {
    "sim_swap": (f"{CAMARA}/sim-swap/sim-swap/v0/check",
                 lambda p: {"phoneNumber": p, "maxAge": 240}),
    "call_fwd": (f"{CAMARA}/call-forwarding-signal/call-forwarding-signal/v0.3"
                 "/unconditional-call-forwardings", lambda p: {"phoneNumber": p}),
    "roaming": ("/device-status/device-roaming-status/v1/retrieve",
                lambda p: {"device": {"phoneNumber": p}}),
    "location": ("/location-verification/v1/verify",
                 lambda p: {"device": {"phoneNumber": p}, "area": AREA}),
}


def summarise(api: str, status: int, body) -> str:
    if status != 200:
        return f"HTTP {status}"
    if api == "sim_swap":
        return "SWAPPED" if body.get("swapped") else "clean"
    if api == "call_fwd":
        return "FORWARDING" if body.get("active") else "clean"
    if api == "roaming":
        if not body.get("roaming"):
            return "home"
        return f"ROAMING {','.join(body.get('countryName') or []) or body.get('countryCode')}"
    if api == "location":
        result = body.get("verificationResult")
        rate = body.get("matchRate")
        return f"{result}{f' {rate}%' if rate is not None else ''}"
    return str(body)


async def probe_one(client: httpx.AsyncClient, api: str, phone: str) -> tuple[str, float]:
    path, build = CALLS[api]
    started = time.perf_counter()
    try:
        r = await client.post(path, headers=HEADERS, json=build(phone))
        elapsed = (time.perf_counter() - started) * 1000
        try:
            body = r.json()
        except Exception:
            body = {}
        return summarise(api, r.status_code, body), elapsed
    except Exception as exc:
        return f"ERR {type(exc).__name__}", (time.perf_counter() - started) * 1000


async def main() -> None:
    apis = list(CALLS)
    header = f"{'number':<16}" + "".join(f"{a:<20}" for a in apis)
    print(header)
    print("-" * len(header))

    async with httpx.AsyncClient(base_url=settings.nokia_nac_base_url,
                                 timeout=20.0) as client:
        for phone in NUMBERS:
            results = await asyncio.gather(*(probe_one(client, a, phone) for a in apis))
            row = f"{phone:<16}" + "".join(f"{r[0]:<20}" for r in results)
            print(row)


if __name__ == "__main__":
    asyncio.run(main())
