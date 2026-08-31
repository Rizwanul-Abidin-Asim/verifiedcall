"""Can Twilio reach this phone at all? Ask Twilio, before involving anyone else.

    uv run python scripts/twilio_reach_test.py +971504229551

A real call to a UAE handset has to clear three gates, and only the last one is ours:

    1. Twilio will connect calls to that country       <- this script
    2. This account is allowed to call that number     <- this script
    3. Vapi routes an imported number through Twilio   <- live_call_test.py

Testing them together means a failure tells you nothing about which gate closed. So
this script skips the AI layer entirely and places a plain Twilio call that speaks one
sentence. If the phone rings, gates 1 and 2 are open and anything that fails afterwards
belongs to the voice platform, not the carrier.

It costs about a cent. Twilio publishes a rate of roughly $0.30/min to UAE mobiles and
this call lasts a few seconds.
"""

import argparse
import asyncio
import re
import sys
from xml.sax.saxutils import escape

import httpx

from app.config import settings

TWILIO_BASE = "https://api.twilio.com/2010-04-01"

SPOKEN = ("This is a test call from the Verified Call project. "
          "If you can hear this, the phone network is working. Goodbye.")

# Twilio's own words for the failures worth explaining rather than dumping.
KNOWN = {
    "13227": "Geo Permissions are blocking this country. Turn on the United Arab "
             "Emirates under Voice, Settings, Geo Permissions, and enable the High "
             "Risk range too if it is listed separately.",
    "21215": "Geo Permissions are blocking this country. Turn on the United Arab "
             "Emirates under Voice, Settings, Geo Permissions.",
    "21210": "The number you are calling is not a Verified Caller ID on this trial "
             "account. Add it under Phone Numbers, Manage, Verified Caller IDs.",
    "21211": "Twilio rejected the destination number as invalid.",
    "21606": "The from number cannot place calls. Check it has the Voice capability.",
}

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m")


def fail(message: str) -> int:
    print(f"{RED}{message}{RESET}")
    return 1


async def main(to_number: str, timeout_s: int) -> int:
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    from_number = settings.twilio_phone_number

    missing = [name for name, value in (
        ("TWILIO_ACCOUNT_SID", sid),
        ("TWILIO_AUTH_TOKEN", token),
        ("TWILIO_PHONE_NUMBER", from_number),
    ) if not value]
    if missing:
        return fail("Missing from .env: " + ", ".join(missing))

    if not re.fullmatch(r"\+[1-9]\d{7,14}", to_number):
        return fail(f"{to_number!r} is not an E.164 number, e.g. +971501234567")

    auth = (sid, token)
    twiml = f"<Response><Say>{escape(SPOKEN)}</Say></Response>"

    print(f"{DIM}calling {to_number} from {from_number}{RESET}")
    print(f"{YELLOW}Your phone should ring. You do not have to answer; we only need "
          f"to know Twilio will place it.{RESET}\n")

    async with httpx.AsyncClient(timeout=30.0, auth=auth) as client:
        response = await client.post(
            f"{TWILIO_BASE}/Accounts/{sid}/Calls.json",
            data={"To": to_number, "From": from_number, "Twiml": twiml},
        )
        if not response.is_success:
            body = response.json() if response.headers.get(
                "content-type", "").startswith("application/json") else {}
            code = str(body.get("code", ""))
            print(f"{RED}Twilio refused to place the call.{RESET}")
            print(f"  status  : {response.status_code}")
            print(f"  code    : {code or '(none)'}")
            print(f"  message : {body.get('message') or response.text[:300]}")
            if code in KNOWN:
                print(f"\n{YELLOW}What this means:{RESET} {KNOWN[code]}")
            else:
                print(f"\n{DIM}Not a failure we have seen before. The message above is "
                      f"Twilio's own; treat it as the authority.{RESET}")
            return 1

        call = response.json()
        call_sid = call["sid"]
        print(f"  accepted, call {call_sid}")
        print(f"{DIM}watching until it completes...{RESET}")

        last = None
        for _ in range(max(1, timeout_s // 3)):
            await asyncio.sleep(3)
            poll = await client.get(f"{TWILIO_BASE}/Accounts/{sid}/Calls/{call_sid}.json")
            if not poll.is_success:
                continue
            state = poll.json()
            status = state.get("status")
            if status != last:
                last = status
                print(f"  {DIM}status: {status}{RESET}")
            if status in ("completed", "busy", "no-answer", "failed", "canceled"):
                break
        else:
            print(f"{YELLOW}Still ringing when we stopped watching. Twilio accepted "
                  f"the call, which is what this test needed to prove.{RESET}")
            return 0

    print()
    if last in ("completed", "no-answer", "busy"):
        print(f"{GREEN}Twilio can reach this number.{RESET} Final status: {last}.")
        if last == "no-answer":
            print(f"{DIM}Nobody picked up, which still proves the call was placed and "
                  f"the network connected it.{RESET}")
        print("\nGates 1 and 2 are open. Next: import the number into Vapi and run "
              "scripts/live_call_test.py.")
        return 0

    reason = state.get("annotation") or ""
    print(f"{RED}The call did not connect.{RESET} Final status: {last}. {reason}")
    print(f"{DIM}A 'failed' status here is usually Geo Permissions or an unverified "
          f"destination on a trial account.{RESET}")
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Check Twilio will place a call to a number, without any AI layer.")
    ap.add_argument("to_number", help="the phone to ring, E.164, e.g. +971504229551")
    ap.add_argument("--timeout", type=int, default=60, help="seconds to watch")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.to_number, args.timeout)))
