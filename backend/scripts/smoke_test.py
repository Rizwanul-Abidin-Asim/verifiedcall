"""End-to-end smoke test against a running server. Run this before pitching.

    uv run python scripts/smoke_test.py                     # default localhost:8000
    uv run python scripts/smoke_test.py --url http://host   # somewhere else

Exits non-zero and says exactly what broke. It checks the things that would actually
ruin a demo: the four scenarios still produce the right outcomes, the live feed
delivers, and the read endpoints return what the dashboard needs.
"""

import argparse
import asyncio
import json
import sys
import time

import httpx

CLEAN = "+99999991001"
ELSEWHERE = "+99999991000"
AT_HOME = "+99999991004"
PARTIAL = "+99999991003"
OUTAGE = "+99999990500"

SCENARIOS = [
    ("1  clean, known payee",        "240.00",   CLEAN,     False, 14, "approve"),
    ("2  bad signals, device away",  "18500.00", ELSEWHERE, True,  23, "decline"),
    ("3  bad signals, device here",  "42000.00", AT_HOME,   True,  23, "intervene"),
    ("4  partial location match",    "6300.00",  PARTIAL,   True,  23, "intervene"),
]

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
failures: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> bool:
    mark = f"{GREEN}pass{RESET}" if condition else f"{RED}FAIL{RESET}"
    print(f"  [{mark}] {label}" + (f"  {DIM}{detail}{RESET}" if detail else ""))
    if not condition:
        failures.append(label)
    return condition


def resolution_label(voice: dict) -> str:
    return voice.get("resolution", "?")


def body(amount, signal_msisdn, new_payee, hour, call_number="+971500000000"):
    return {
        "amount": amount, "currency": "AED", "merchant_name": "Direct transfer",
        "beneficiary_id": "BEN-SMOKE", "is_new_beneficiary": new_payee,
        "customer_msisdn": call_number, "signal_msisdn": signal_msisdn,
        "customer_locale": "en", "local_hour": hour,
    }


async def collect_stream(url: str, seen: list[dict], ready: asyncio.Event) -> None:
    """Listen on the SSE feed for the whole run."""
    try:
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream("GET", f"{url}/stream/decisions") as r:
                if r.status_code != 200:
                    ready.set()
                    return
                async for line in r.aiter_lines():
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        data = json.loads(raw)
                        if data.get("listening"):
                            ready.set()
                        elif "decision_id" in data:
                            seen.append(data)
    except Exception as exc:  # noqa: BLE001 - reported, never raised into the run
        print(f"  {YELLOW}stream ended: {exc!r}{RESET}")
        ready.set()


async def main(url: str) -> int:
    print(f"\nVerifiedCall smoke test against {url}\n" + "=" * 66)

    async with httpx.AsyncClient(timeout=60) as c:
        print("\nhealth")
        try:
            health = await c.get(f"{url}/health")
        except Exception as exc:  # noqa: BLE001
            print(f"  {RED}cannot reach the server: {exc!r}{RESET}")
            print("\n  start it with: uv run uvicorn app.main:app --port 8000\n")
            return 1
        check(health.status_code == 200, "GET /health returns 200")
        info = health.json()
        print(f"       demo_mode={info.get('demo_mode')} voice_mock={info.get('voice_mock')} "
              f"provider={info.get('llm_provider')}")
        check("key" not in json.dumps(info).lower(), "health leaks no credentials")

        seen: list[dict] = []
        ready = asyncio.Event()
        listener = asyncio.create_task(collect_stream(url, seen, ready))
        try:
            await asyncio.wait_for(ready.wait(), timeout=10)
            check(True, "SSE stream connected")
        except TimeoutError:
            check(False, "SSE stream connected", "no connect event within 10s")

        print("\nthe four demo scenarios")
        decision_ids = []
        for index, (label, amount, number, new_payee, hour, expected) in enumerate(SCENARIOS):
            if index:
                # A real demo has a human clicking between scenarios. Firing them
                # back to back only measures the LLM provider's burst rate limit.
                await asyncio.sleep(2.0)
            started = time.perf_counter()
            r = await c.post(f"{url}/transactions/evaluate",
                             json=body(amount, number, new_payee, hour))
            ms = (time.perf_counter() - started) * 1000
            if r.status_code != 200:
                check(False, label, f"HTTP {r.status_code} {r.text[:90]}")
                continue
            d = r.json()
            decision_ids.append(d["decision_id"])
            detail = (f"{d['outcome']:<9} score {d['risk_score']:>3}  "
                      f"{len(d['signals_pulled'])}/4 signals  {ms:>5.0f}ms  "
                      f"{'FALLBACK' if d['used_fallback'] else 'live'}  {d['agent_mode']}")
            check(d["outcome"] == expected, label, detail)
            check(bool(d["reasoning_trace"]), f"{label}: has a reasoning trace")

        print("\ndegraded path")
        r = await c.post(f"{url}/transactions/evaluate",
                         json=body("9000.00", OUTAGE, True, 23))
        if check(r.status_code == 200, "forced network outage still returns a decision",
                 f"HTTP {r.status_code}"):
            d = r.json()
            check(d["used_fallback"] is True, "outage decision is flagged as using cache",
                  f"outcome={d['outcome']}")
            decision_ids.append(d["decision_id"])

        print("\nread endpoints")
        listing = await c.get(f"{url}/decisions?limit=10")
        check(listing.status_code == 200, "GET /decisions returns 200")
        if listing.status_code == 200:
            page = listing.json()
            check(page["total"] >= len(decision_ids), "listing includes this run",
                  f"total={page['total']}")
        if decision_ids:
            det = await c.get(f"{url}/decisions/{decision_ids[0]}")
            check(det.status_code == 200, "GET /decisions/{id} returns 200")
            if det.status_code == 200:
                dd = det.json()
                check(bool(dd["reasoning_trace"]), "detail carries the reasoning trace")
                check("signal_calls" in dd, "detail carries the signal calls")
                check(all(s.get("source") in {"live", "fallback"} for s in dd["signal_calls"]),
                      "every signal is labelled live or fallback")
        missing = await c.get(f"{url}/decisions/00000000-0000-0000-0000-000000000000")
        check(missing.status_code == 404, "unknown decision id returns 404, not 500")

        print("\nvoice intervention")
        held_txn = None
        for did in decision_ids:
            detail = (await c.get(f"{url}/decisions/{did}")).json()
            if detail.get("outcome") == "intervene":
                held_txn = detail["transaction"]["id"]
                break

        if not check(held_txn is not None, "a held payment exists to call about"):
            pass
        else:
            resolved = None
            for _ in range(25):
                vr = await c.get(f"{url}/voice/{held_txn}")
                if vr.status_code == 200 and vr.json().get("status") == "completed":
                    resolved = vr.json()
                    break
                await asyncio.sleep(1.0)
            if check(resolved is not None, "the held payment triggered a call that resolved"):
                check(resolved["outcome"] in
                      {"scam_detected", "confirmed_legitimate", "no_answer", "inconclusive"},
                      "the call reached an outcome",
                      f"{resolved['outcome']} -> {resolution_label(resolved)}")
                check(resolved["is_mock"] is True,
                      "the call is labelled simulated, not passed off as real")
                check(bool(resolved["answers"]), "per-question answers were recorded")
                check(resolution_label(resolved) != "released"
                      or resolved["outcome"] == "confirmed_legitimate",
                      "money is only released on a clean call")

        print("\nlive feed")
        await asyncio.sleep(1.5)
        check(len(seen) >= len(decision_ids),
              "every decision reached the SSE stream",
              f"{len(seen)} received, {len(decision_ids)} expected")
        listener.cancel()

    print("\n" + "=" * 66)
    if failures:
        print(f"{RED}{len(failures)} check(s) failed:{RESET}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"{GREEN}all checks passed. safe to demo.{RESET}\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    sys.exit(asyncio.run(main(ap.parse_args().url.rstrip("/"))))
