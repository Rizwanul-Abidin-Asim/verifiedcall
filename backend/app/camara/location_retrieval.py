"""CAMARA Location Retrieval — where does the network actually place the handset?

Location Verification answers a yes/no question about an area we supply. This returns a
position. We use both, for different jobs:

    Verification -> the decision. "Is the device where the payment claims?"
    Retrieval    -> the explanation. "The network puts it in Budapest."

A fraud analyst can act on the second sentence. They cannot act on
`verificationResult: FALSE`, which is why our mentor pushed us toward retrieval.

Retrieval is the more privacy-invasive of the two — it discloses a position rather than
confirming one — so we only call it once a payment is already heading for a hold or a
decline, never on the approve path. Verified 2026-09-12: returns an area with a centre
and a radius in metres.
"""

from app.camara.base import camara_post, with_fallback
from app.camara.models import LocationRetrievalSignal

PATH = "/location-retrieval/v0/retrieve"
DEFAULT_MAX_AGE_S = 3600


@with_fallback("location_retrieval")
async def retrieve_location(
    phone_number: str, max_age_s: int = DEFAULT_MAX_AGE_S,
) -> LocationRetrievalSignal:
    """Retrieve the device's last known position.

    maxAge here is in SECONDS. SIM Swap and Device Swap take hours. The units genuinely
    differ between CAMARA APIs — see docs/camara-findings.md.
    """
    body, latency_ms = await camara_post(
        "location_retrieval", PATH,
        {"device": {"phoneNumber": phone_number}, "maxAge": max_age_s},
    )
    area = body.get("area") or {}
    centre = area.get("center") or {}
    return LocationRetrievalSignal(
        latitude=centre.get("latitude"),
        longitude=centre.get("longitude"),
        radius_m=area.get("radius"),
        last_location_time=body.get("lastLocationTime"),
        latency_ms=latency_ms,
        raw=body,
    )
