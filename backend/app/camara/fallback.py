"""Cached CAMARA responses for demo resilience.

Used when the live API errors, times out or rate-limits, and whenever DEMO_MODE is on.

Two rules, both non-negotiable:
1. Every result returned from here carries source="fallback" and a reason. The dashboard
   shows it. We never pass cached data off as live.
2. The cached values match the shapes in docs/camara-findings.md exactly, so the agent
   cannot tell the difference structurally — only by reading `source`.

Values are keyed by the sandbox demo numbers so a fallback still tells a coherent story
for whichever scenario is being demonstrated.
"""

from datetime import UTC, datetime, timedelta

from app.camara.models import (
    CallForwardingSignal,
    LocationSignal,
    LocationVerificationResult,
    RoamingSignal,
    SignalSource,
    SimSwapSignal,
)

# Sandbox convention: ...1000 is the "bad" device, ...1001 the clean one.
SWAPPED = "+99999991000"
CLEAN = "+99999991001"


def _recent(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def _sim_swap(phone_number: str) -> SimSwapSignal:
    swapped = phone_number == SWAPPED
    return SimSwapSignal(
        swapped=swapped,
        latest_sim_change=_recent(6) if swapped else None,
        raw={"swapped": swapped},
    )


def _call_forwarding(phone_number: str) -> CallForwardingSignal:
    active = phone_number == SWAPPED
    return CallForwardingSignal(
        active=active,
        forwarding_types=["unconditional"] if active else [],
        raw={"active": active},
    )


def _device_status(phone_number: str) -> RoamingSignal:
    roaming = phone_number == SWAPPED
    return RoamingSignal(
        roaming=roaming,
        country_code=36 if roaming else None,
        country_names=["HU"] if roaming else [],
        last_status_time=_recent(0),
        raw={"roaming": roaming, "countryCode": 36} if roaming else {"roaming": False},
    )


def _location(phone_number: str) -> LocationSignal:
    inside = phone_number == CLEAN
    result = LocationVerificationResult.TRUE if inside else LocationVerificationResult.FALSE
    return LocationSignal(
        verification_result=result,
        last_location_time=_recent(0),
        raw={"verificationResult": result.value},
    )


_BUILDERS = {
    "sim_swap": _sim_swap,
    "call_forwarding": _call_forwarding,
    "device_status": _device_status,
    "location_verification": _location,
}


def fallback_for(api_name: str, phone_number: str, reason: str):
    """Build a cached result, always flagged as a fallback."""
    try:
        builder = _BUILDERS[api_name]
    except KeyError:
        raise KeyError(
            f"No fallback defined for {api_name!r}. Add one — a signal with no fallback "
            f"can break a live demo."
        ) from None

    signal = builder(phone_number)
    signal.source = SignalSource.FALLBACK
    signal.fallback_reason = reason
    return signal
