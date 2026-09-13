"""CAMARA Device Swap — has the SIM moved into a different handset?

On its own this says little: people replace broken phones. Its value is entirely in the
pairing with SIM Swap, because the two together separate stories that look identical
from either signal alone:

    SIM changed, device same    -> usually a genuine replacement SIM
    SIM same, device changed    -> usually a genuine new phone
    both changed, close together -> the shape of an account takeover

Verified against the simulator 2026-09-12: ...1000 swapped=true, ...1001 swapped=false,
/retrieve-date returns latestDeviceChange. Note the path is v1, unlike SIM Swap's v0.
"""

from app.camara.base import CAMARA_PREFIX, CamaraError, camara_post, with_fallback
from app.camara.models import DeviceSwapSignal

PATH = f"{CAMARA_PREFIX}/device-swap/device-swap/v1"
DEFAULT_MAX_AGE_HOURS = 240


@with_fallback("device_swap")
async def check_device_swap(
    phone_number: str, max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> DeviceSwapSignal:
    """Check for a device change, and fetch its date when there was one.

    /check does not return the date — only /retrieve-date does. We only pay for the
    second call when the first says something happened, because the age of the change is
    what makes it interesting and it is irrelevant when nothing changed.
    """
    body, latency_ms = await camara_post(
        "device_swap", f"{PATH}/check",
        {"phoneNumber": phone_number, "maxAge": max_age_hours},
    )
    swapped = bool(body["swapped"])

    changed_at = None
    if swapped:
        try:
            date_body, date_latency = await camara_post(
                "device_swap", f"{PATH}/retrieve-date", {"phoneNumber": phone_number},
            )
            changed_at = date_body.get("latestDeviceChange")
            latency_ms += date_latency
        except CamaraError:
            # The swap itself is the signal; losing its date degrades the explanation,
            # not the decision. Better a vaguer sentence than no signal at all.
            pass

    return DeviceSwapSignal(
        swapped=swapped,
        latest_device_change=changed_at,
        latency_ms=latency_ms,
        raw=body,
    )
