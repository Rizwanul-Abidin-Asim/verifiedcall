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
