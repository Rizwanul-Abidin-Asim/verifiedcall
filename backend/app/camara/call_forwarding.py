"""CAMARA Call Forwarding Signal — are this number's calls being redirected?

This replaced Number Verification in our core four (which returns 401 server-side; see
scripts/spikes/probe_number_verification.py for the evidence).

Fraud signal, and our strongest: SIM Swap tells you an identity was compromised at some
point in the past. Unconditional call forwarding active *during* a payment means calls
are being intercepted right now — a scam in progress, which is the whole thesis.
"""

from app.camara.base import CAMARA_PREFIX, CamaraError, camara_post, with_fallback
from app.camara.models import CallForwardingSignal

BASE = f"{CAMARA_PREFIX}/call-forwarding-signal/call-forwarding-signal/v0.3"


@with_fallback("call_forwarding")
async def check_call_forwarding(phone_number: str) -> CallForwardingSignal:
    """Check unconditional call forwarding, then enrich with the full type list.

    The `/call-forwardings` variant is documented as possibly returning 501 (it exceeds
    the CFS API's core scope), so a failure there must not lose the primary answer.
    """
    body, latency_ms = await camara_post(
        "call_forwarding", f"{BASE}/unconditional-call-forwardings",
        {"phoneNumber": phone_number},
    )
    signal = CallForwardingSignal(
        active=bool(body["active"]), latency_ms=latency_ms, raw=body,
    )

    try:
        types, extra_ms = await camara_post(
            "call_forwarding", f"{BASE}/call-forwardings", {"phoneNumber": phone_number},
        )
    except CamaraError:
        return signal  # 501 or similar — the unconditional answer still stands

    signal.forwarding_types = list(types)
    signal.latency_ms += extra_ms
    signal.raw = {"unconditional": body, "types": types}
    return signal
