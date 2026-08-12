"""CAMARA Device Status (roaming) — is the device on a foreign network, and where?

Fraud signal: roaming plus a first-time beneficiary is a classic APP fraud pattern —
the victim is travelling, less able to verify, and under time pressure.
"""

from app.camara.base import camara_post, with_fallback
from app.camara.models import RoamingSignal

PATH = "/device-status/device-roaming-status/v1/retrieve"


@with_fallback("device_status")
async def check_device_status(phone_number: str) -> RoamingSignal:
    """Retrieve current roaming status.

    countryCode/countryName are absent when the device is on its home network.
    countryName is a list because one MCC can cover several countries.
    """
    body, latency_ms = await camara_post(
        "device_status", PATH, {"device": {"phoneNumber": phone_number}},
    )
    return RoamingSignal(
        roaming=bool(body["roaming"]),
        country_code=body.get("countryCode"),
        country_names=list(body.get("countryName") or []),
        last_status_time=body.get("lastStatusTime"),
        latency_ms=latency_ms,
        raw=body,
    )
