"""Place one real call, to a phone you control, and watch it resolve.

    uv run python scripts/live_call_test.py +971500000000

This dials an actual phone and spends Vapi credits. Everything else in this repo can
be run for free; this cannot, which is why it is a separate script you have to ask for
by name rather than a flag on the smoke test.

It drives demo scenario 3, the one the pitch is built on: every network signal is bad,
but the device is exactly where the payment claims to be. That combination means the
customer is probably holding the phone while somebody talks them through the transfer,
so the payment is held and the customer is called.

The network signals still come from Nokia's sandbox number. Only the call goes to your
real phone. That seam is deliberate and the dashboard says so.

When it rings, answer it. You will be asked three questions. Say "no" to the first two
and then wait about five seconds before answering the third, and you should see
INCONCLUSIVE rather than a release: a denial delivered slowly is not a clean call.
"""

import argparse
import asyncio
import re
import sys

import httpx

# Scenario 3 from docs/camara-findings.md: bad signals, device where it should be.
SIGNAL_MSISDN = "+99999991004"

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m")


def fail(message: str) -> int:
    print(f"{RED}{message}{RESET}")
    return 1


async def main(url: str, msisdn: str, timeout_s: int) -> int:
    if not re.fullmatch(r"\+[1-9]\d{7,14}", msisdn):
        return fail(f"{msisdn!r} is not an E.164 number. It needs the country code and "
                    f"a leading +, for example +971501234567.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            health = await client.get(f"{url}/health")
        except httpx.HTTPError as exc:
            return fail(f"Could not reach the backend at {url}: {exc}\n"
                        f"Start it with: uv run uvicorn app.main:app --port 8000")
        if not health.is_success:
            return fail(f"{url}/health returned {health.status_code}")

        body = health.json()
        if body.get("voice_mock", True):
            return fail(
                "The backend is still in mock mode, so nothing would dial.\n"
                "Set VOICE_MOCK=false in .env and restart the backend.")

        print(f"{DIM}backend {url} is up and in live voice mode{RESET}")
        print(f"{YELLOW}This will ring {msisdn} and spend Vapi credits.{RESET}")
        print(f"{DIM}Signals come from the sandbox number {SIGNAL_MSISDN}.{RESET}\n")

        response = await client.post(f"{url}/transactions/evaluate", json={
            "amount": "42000.00",
            "currency": "AED",
            "merchant_name": "Direct transfer",
            "beneficiary_id": "live-call-test",
            "is_new_beneficiary": True,
            "customer_msisdn": msisdn,        # the phone that actually rings
            "signal_msisdn": SIGNAL_MSISDN,   # the phone the network is asked about
            "customer_locale": "en",
            "expected_city": "AE-DXB",
        })
        if not response.is_success:
            return fail(f"evaluate returned {response.status_code}: {response.text[:300]}")

        decision = response.json()
        txn_id = decision["transaction_id"]
        print(f"  decision : {decision['outcome']}  score {decision['risk_score']}")
        print(f"  txn      : {txn_id}")

        if decision["outcome"] != "intervene":
            return fail(f"Expected 'intervene' so a call would be placed, got "
                        f"{decision['outcome']!r}. Nothing was dialled.")

        print(f"\n{YELLOW}Your phone should ring shortly. Answer it.{RESET}")
        print(f"{DIM}Waiting up to {timeout_s}s for the call to resolve...{RESET}")

        last = None
        for _ in range(timeout_s // 3):
            await asyncio.sleep(3)
            voice = await client.get(f"{url}/voice/{txn_id}")
            if not voice.is_success:
                continue
            state = voice.json()
            if state["status"] != last:
                last = state["status"]
                print(f"  {DIM}status: {last}{RESET}")
            if state["status"] in ("completed", "failed"):
                break
        else:
            return fail("The call did not resolve in time. The payment stays held, "
                        "which is the safe state, but check the backend logs.")

        print()
        if state["status"] == "failed":
            print(f"{RED}The call failed.{RESET} {state.get('transcript')}")
            return 1

        colour = GREEN if state["outcome"] else RED
        print(f"  outcome    : {colour}{state['outcome']}{RESET}")
        print(f"  resolution : {state['resolution']}")
        print(f"  language   : {state['language']}   duration: {state['duration_s']}s")
        print(f"  simulated  : {state['is_mock']}")

        for key, answer in (state.get("answers") or {}).items():
            pause = f"{answer['response_ms']}ms"
            flag = f" {YELLOW}hesitated{RESET}" if answer.get("hesitant") else ""
            print(f"    {key:22} {answer['reply']:8} after {pause}{flag}")

        if state.get("transcript"):
            print(f"\n{DIM}transcript{RESET}")
            for line in state["transcript"].splitlines():
                print(f"    {DIM}{line}{RESET}")

        if not state.get("answers"):
            print(f"\n{YELLOW}No answers were extracted.{RESET} The payment stays held, "
                  f"which is correct, but the transcript above is worth reading: it is "
                  f"usually the transcriber, not the logic.")

        print(f"\n{GREEN}Live call completed.{RESET} "
              f"Open the dashboard and this transaction will be in the feed.")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Place one real call to a phone you control.")
    ap.add_argument("msisdn", help="your phone in E.164 format, e.g. +971501234567")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=int, default=180, help="seconds to wait")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.url.rstrip("/"), args.msisdn, args.timeout)))
