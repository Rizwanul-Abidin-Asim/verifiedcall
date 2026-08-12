"""Typed results for every CAMARA signal.

Field names mirror the shapes recorded in docs/camara-findings.md exactly. If you are
tempted to add a field, check that file first — if the shape isn't recorded there, stop.

These live in their own module (rather than beside each client) so that fallback.py can
build them without importing the clients, which would be circular.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SignalSource(StrEnum):
    LIVE = "live"
    FALLBACK = "fallback"


class SignalResult(BaseModel):
    """Common envelope. Every signal carries its provenance — this is a hackathon
    requirement, not a nicety: the dashboard must show fallbacks honestly."""

    api_name: str
    source: SignalSource = SignalSource.LIVE
    latency_ms: float = 0.0
    raw: dict | list = Field(default_factory=dict)
    fallback_reason: str | None = None

    @property
    def is_fallback(self) -> bool:
        return self.source is SignalSource.FALLBACK


class SimSwapSignal(SignalResult):
    """POST /passthrough/camara/v1/sim-swap/sim-swap/v0/check + /retrieve-date"""

    api_name: str = "sim_swap"
    swapped: bool
    latest_sim_change: datetime | None = None


class CallForwardingSignal(SignalResult):
    """POST .../call-forwarding-signal/v0.3/unconditional-call-forwardings

    Our highest-value signal: unconditional forwarding active at payment time means the
    customer's calls are being intercepted right now.
    """

    api_name: str = "call_forwarding"
    active: bool
    forwarding_types: list[str] = Field(default_factory=list)


class RoamingSignal(SignalResult):
    """POST /device-status/device-roaming-status/v1/retrieve

    countryCode is an MCC. countryName is a LIST — one MCC can map to several countries
    (340 -> BL, GF, GP, MF, MQ), so never assume a single element.
    """

    api_name: str = "device_status"
    roaming: bool
    country_code: int | None = None
    country_names: list[str] = Field(default_factory=list)
    last_status_time: datetime | None = None


class LocationVerificationResult(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class LocationSignal(SignalResult):
    """POST /location-verification/v1/verify

    Verifies against an area WE supply; it does not return a position. match_rate is
    present only on PARTIAL; last_location_time is omitted on UNKNOWN.
    """

    api_name: str = "location_verification"
    verification_result: LocationVerificationResult
    match_rate: int | None = None
    last_location_time: datetime | None = None
