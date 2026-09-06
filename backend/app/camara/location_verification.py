"""CAMARA Location Verification — is the device near where the transaction claims to be?

IMPORTANT: this API does not return a position. It answers a yes/no about an area *we*
supply. So the fraud signal is phrased as "is the device within R metres of the expected
city", with the radius chosen by us.
"""

from app.camara.base import camara_post, with_fallback
from app.camara.models import LocationSignal, LocationVerificationResult

PATH = "/location-verification/v1/verify"
DEFAULT_RADIUS_M = 50_000

# Expected transaction origins for the demo scenarios.
CITY_CENTRES = {
    "AE-DXB": (25.204849, 55.270783),
    "AE-AUH": (24.453884, 54.377342),
    "DE-BONN": (50.735851, 7.100660),  # the sandbox's own reference point
}


def centre_for(
    device_latitude: float | None,
    device_longitude: float | None,
    expected_city: str,
) -> tuple[float, float]:
    """Where to aim the check.

    The handset's own position when we have it, so the question becomes whether the
    network agrees with the phone. A city centre otherwise, which only compares the
    network against an assumption of ours.

    This lives in one function because three call sites decide it: the agent tool, the
    deterministic fallback, and the guard that insists on evidence before declining.
    The first was taught about device position and the other two were not, so a payment
    was checked against Dubai while the phone reported Sharjah. One place, or it drifts
    again.
    """
    if device_latitude is not None and device_longitude is not None:
        return device_latitude, device_longitude
    return CITY_CENTRES.get(expected_city, CITY_CENTRES["AE-DXB"])


@with_fallback("location_verification")
async def verify_location(
    phone_number: str,
    latitude: float,
    longitude: float,
    radius_m: int = DEFAULT_RADIUS_M,
) -> LocationSignal:
    """Verify the device sits within `radius_m` of the given centre.

    NOTE the unit: radius is metres, and this API's maxAge is seconds — sim_swap's
    maxAge is hours. Do not copy one into the other.
    """
    body, latency_ms = await camara_post(
        "location_verification", PATH,
        {
            "device": {"phoneNumber": phone_number},
            "area": {
                "areaType": "CIRCLE",
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": radius_m,
            },
        },
    )
    return LocationSignal(
        verification_result=LocationVerificationResult(body["verificationResult"]),
        match_rate=body.get("matchRate"),
        last_location_time=body.get("lastLocationTime"),
        latency_ms=latency_ms,
        raw=body,
    )
