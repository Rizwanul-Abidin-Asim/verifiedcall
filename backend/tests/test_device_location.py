"""Where the handset says it is, and what we do with that.

The network location check used to be aimed at a hardcoded city centre, which compares
the operator against an assumption. Aiming it at the position the browser reported
compares two independent sources instead, and two are harder to fake than one.
"""

from decimal import Decimal

import pytest

from app.agent.schemas import TransactionContext
from app.agent.scoring import WEIGHTS, build_trace
from app.camara.location_verification import CITY_CENTRES


def context(**over) -> TransactionContext:
    base = dict(
        amount=Decimal("42000.00"), currency="AED", merchant_name="Direct transfer",
        is_new_beneficiary=True, customer_locale="en", local_hour=14,
        signal_msisdn="+99999991004",
    )
    base.update(over)
    return TransactionContext(**base)


def test_refusing_to_share_location_is_weak_evidence_not_an_accusation():
    """It removes a check. It does not prove anything, and is weighted like it."""
    denied = WEIGHTS["device_location_denied"]
    assert denied <= WEIGHTS["unusual_hour"], "refusing must not outweigh a late hour"
    assert denied < WEIGHTS["new_beneficiary"]
    assert denied < WEIGHTS["location_false"] / 4


def test_the_refusal_shows_up_in_the_score_and_the_trace():
    quiet, _ = build_trace(context(device_location_denied=False), [])
    refused, steps = build_trace(context(device_location_denied=True), [])

    assert refused == quiet + WEIGHTS["device_location_denied"]
    # The customer is told why, in the trace an analyst reads.
    assert any("would not share its location" in s.observed for s in steps)


def test_refusing_alone_cannot_hold_an_ordinary_payment():
    """A careful person who declines a location prompt must still be able to pay."""
    small = context(amount=Decimal("200.00"), is_new_beneficiary=False,
                    device_location_denied=True)
    score, _ = build_trace(small, [])
    from app.agent.scoring import APPROVE_BELOW
    assert score < APPROVE_BELOW


@pytest.mark.parametrize("city", list(CITY_CENTRES))
def test_the_fallback_centres_are_real_coordinates(city):
    lat, lon = CITY_CENTRES[city]
    assert -90 <= lat <= 90
    assert -180 <= lon <= 180


def test_every_caller_aims_at_the_device_when_it_reported_one():
    """Three places choose the centre, and only one of them knew about the device.

    A payment was checked against Dubai while the phone had reported Sharjah, because
    the agent tool was taught about device position and the deterministic fallback and
    the decline guard were not. They now share one function; this asserts nothing has
    gone back to reading the city table directly.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if path.name != "location_verification.py" and "CITY_CENTRES" in path.read_text(
            encoding="utf-8")
    ]
    assert offenders == [], f"these pick a centre without centre_for(): {offenders}"


def test_centre_for_prefers_the_device_and_falls_back_to_the_city():
    from app.camara.location_verification import CITY_CENTRES, centre_for

    assert centre_for(25.3463, 55.4209, "AE-DXB") == (25.3463, 55.4209)
    assert centre_for(None, None, "AE-DXB") == CITY_CENTRES["AE-DXB"]
    assert centre_for(None, None, "nonsense") == CITY_CENTRES["AE-DXB"]
    # Half a position is not a position.
    assert centre_for(25.3463, None, "AE-DXB") == CITY_CENTRES["AE-DXB"]
    assert centre_for(None, 55.4209, "AE-DXB") == CITY_CENTRES["AE-DXB"]
