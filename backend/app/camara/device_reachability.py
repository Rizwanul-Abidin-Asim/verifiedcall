"""CAMARA Device Reachability Status — can we still reach this customer, and how?

Every other signal here answers "how risky is this payment?". This one answers a
different question: "if we decide to intervene, which door is still open?"

That matters because an intervention sent down a channel the attacker controls is worse
than no intervention at all — it confirms the scam for them ("see, that's the bank
approving it"). Verified against the simulator 2026-09-12:

    +99999991000  reachable, ["SMS"]
    +99999991001  reachable, ["DATA"]
    +99999991002  reachable, ["SMS","DATA"]
    +99999991003  reachable=false, connectivity absent
"""

from app.camara.base import camara_post, with_fallback
from app.camara.models import ReachabilitySignal

PATH = "/device-status/device-reachability-status/v1/retrieve"


@with_fallback("device_reachability")
async def check_reachability(phone_number: str) -> ReachabilitySignal:
    """Retrieve current reachability and the channels it is reachable on.

    `connectivity` is omitted from the response entirely when reachable is false, so
    default it rather than indexing into it.
    """
    body, latency_ms = await camara_post(
        "device_reachability", PATH, {"device": {"phoneNumber": phone_number}},
    )
    return ReachabilitySignal(
        reachable=bool(body["reachable"]),
        connectivity=list(body.get("connectivity") or []),
        last_status_time=body.get("lastStatusTime"),
        latency_ms=latency_ms,
        raw=body,
    )
