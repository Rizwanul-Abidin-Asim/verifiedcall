"""CAMARA SIM Swap — has the SIM behind this number changed recently?

Fraud signal: a recent swap means OTPs and verification calls may be reaching someone
else. Strong indicator of account-takeover preparation.

Observed shapes: docs/camara-findings.md
"""

from app.camara.base import CAMARA_PREFIX, camara_post, with_fallback
from app.camara.models import SimSwapSignal

BASE = f"{CAMARA_PREFIX}/sim-swap/sim-swap/v0"
DEFAULT_MAX_AGE_HOURS = 240


@with_fallback("sim_swap")
async def check_sim_swap(phone_number: str, max_age_hours: int = DEFAULT_MAX_AGE_HOURS
                         ) -> SimSwapSignal:
    """Check whether a SIM swap occurred within the last `max_age_hours` (1–2400).

    NOTE the unit: hours here, but seconds in location_verification. Easy bug.
    """
    body, latency_ms = await camara_post(
        "sim_swap", f"{BASE}/check",
        {"phoneNumber": phone_number, "maxAge": max_age_hours},
    )
    return SimSwapSignal(swapped=bool(body["swapped"]), latency_ms=latency_ms, raw=body)


@with_fallback("sim_swap")
async def retrieve_sim_swap_date(phone_number: str) -> SimSwapSignal:
    """Fetch the timestamp of the last SIM change.

    `latestSimChange` may be null, which is ambiguous — never swapped, or no data. We
    treat null as "not swapped" and let the reasoning trace say so explicitly.
    """
    body, latency_ms = await camara_post(
        "sim_swap", f"{BASE}/retrieve-date", {"phoneNumber": phone_number},
    )
    changed_at = body.get("latestSimChange")
    return SimSwapSignal(
        swapped=changed_at is not None,
        latest_sim_change=changed_at,
        latency_ms=latency_ms,
        raw=body,
    )
