"""The scorer must be exactly reproducible, and must produce the four demo outcomes.

No LLM is involved here by design — that is the whole point of splitting scoring out of
the agent. If these tests are green, the demo outcomes cannot drift because a model
happened to phrase something differently.
"""

from decimal import Decimal

import pytest

from app.agent.schemas import TransactionContext
from app.agent.scoring import (
    APPROVE_BELOW,
    DECLINE_AT_OR_ABOVE,
    build_trace,
    choose_outcome,
    customer_appears_absent,
)
from app.camara.models import (
    CallForwardingSignal,
    LocationSignal,
    LocationVerificationResult,
    RoamingSignal,
    SignalSource,
    SimSwapSignal,
)
from app.db.models import DecisionOutcome


def ctx(amount: str, new_payee: bool, hour: int = 14, msisdn: str = "+99999991000"):
    return TransactionContext(
        amount=Decimal(amount), merchant_name="Direct transfer",
        is_new_beneficiary=new_payee, local_hour=hour, signal_msisdn=msisdn)


def signals(*, swapped: bool, forwarding: bool, roaming: bool,
            location: LocationVerificationResult):
    """Build the four signals as the sandbox actually returns them together."""
    return [
        SimSwapSignal(swapped=swapped, raw={}),
        CallForwardingSignal(
            active=forwarding,
            forwarding_types=["unconditional"] if forwarding else ["inactive"], raw={}),
        RoamingSignal(roaming=roaming, country_code=36 if roaming else None,
                      country_names=["HU"] if roaming else [], raw={}),
        LocationSignal(verification_result=location, raw={}),
    ]


ALL_BAD = dict(swapped=True, forwarding=True, roaming=True)


def evaluate(context, sigs):
    score, trace = build_trace(context, sigs)
    outcome, rationale = choose_outcome(score, sigs)
    return score, outcome, trace, rationale


# ------------------------------------------------- the four demo scenarios


def test_scenario_1_clean_transaction_approves():
    score, outcome, trace, _ = evaluate(
        ctx("240.00", new_payee=False),
        signals(swapped=False, forwarding=False, roaming=False,
                location=LocationVerificationResult.TRUE))

    assert outcome is DecisionOutcome.APPROVE
    assert score < APPROVE_BELOW
    assert trace, "an approve still needs a visible rationale"


def test_scenario_2_device_elsewhere_declines():
    """Signals bad AND the device is not where the payment claims — reads as takeover."""
    score, outcome, _, rationale = evaluate(
        ctx("18500.00", new_payee=True),
        signals(**ALL_BAD, location=LocationVerificationResult.FALSE))

    assert outcome is DecisionOutcome.DECLINE
    assert score >= DECLINE_AT_OR_ABOVE
    assert "does not place the device" in rationale


def test_scenario_3_device_present_intervenes_not_declines():
    """The headline case. Signals are bad, the score is high, but the customer is
    demonstrably there — so we phone them rather than decline."""
    score, outcome, _, rationale = evaluate(
        ctx("42000.00", new_payee=True),
        signals(**ALL_BAD, location=LocationVerificationResult.TRUE))

    assert outcome is DecisionOutcome.INTERVENE
    assert score >= DECLINE_AT_OR_ABOVE, (
        "this scenario is meant to score high yet still not be declined — that contrast "
        "is the product thesis")
    assert "present and reachable" in rationale


def test_scenario_4_partial_location_intervenes():
    _, outcome, _, _ = evaluate(
        ctx("6300.00", new_payee=True),
        signals(**ALL_BAD, location=LocationVerificationResult.PARTIAL))
    assert outcome is DecisionOutcome.INTERVENE


def test_scenarios_2_and_3_differ_only_by_location():
    """Guards the demo narrative: if these two ever produce the same outcome, the
    'theft versus coercion' story on stage stops being true."""
    _, elsewhere, _, _ = evaluate(
        ctx("42000.00", new_payee=True),
        signals(**ALL_BAD, location=LocationVerificationResult.FALSE))
    _, present, _, _ = evaluate(
        ctx("42000.00", new_payee=True),
        signals(**ALL_BAD, location=LocationVerificationResult.TRUE))

    assert elsewhere is DecisionOutcome.DECLINE
    assert present is DecisionOutcome.INTERVENE


# ------------------------------------------------------------- properties


def test_scoring_is_reproducible():
    context = ctx("42000.00", new_payee=True)
    sigs = signals(**ALL_BAD, location=LocationVerificationResult.TRUE)
    first = build_trace(context, sigs)[0]
    for _ in range(5):
        assert build_trace(context, sigs)[0] == first


def test_score_never_leaves_0_100():
    everything = evaluate(ctx("999999.00", new_payee=True, hour=3),
                          signals(**ALL_BAD, location=LocationVerificationResult.FALSE))
    nothing = evaluate(ctx("1.00", new_payee=False),
                       signals(swapped=False, forwarding=False, roaming=False,
                               location=LocationVerificationResult.TRUE))
    assert 0 <= everything[0] <= 100
    assert 0 <= nothing[0] <= 100


def test_call_forwarding_outweighs_sim_swap():
    """Deliberate: forwarding means interception happening now, a swap means a past
    compromise. If this inverts, the APP-fraud thesis is no longer encoded in the score."""
    forwarding_only = build_trace(
        ctx("100.00", new_payee=False),
        [CallForwardingSignal(active=True, raw={})])[0]
    swap_only = build_trace(
        ctx("100.00", new_payee=False), [SimSwapSignal(swapped=True, raw={})])[0]
    assert forwarding_only > swap_only


def test_clean_location_reduces_the_score():
    with_check = build_trace(
        ctx("8000.00", new_payee=True),
        [LocationSignal(verification_result=LocationVerificationResult.TRUE, raw={})])[0]
    without_check = build_trace(ctx("8000.00", new_payee=True), [])[0]
    assert with_check < without_check


def test_absence_requires_positive_evidence():
    """No location check pulled must not be read as 'the customer is absent' — that would
    turn a missing signal into grounds for declining."""
    assert customer_appears_absent([]) is False
    assert customer_appears_absent(
        signals(**ALL_BAD, location=LocationVerificationResult.UNKNOWN)) is False
    assert customer_appears_absent(
        signals(**ALL_BAD, location=LocationVerificationResult.FALSE)) is True


def test_high_score_without_location_check_intervenes_rather_than_declines():
    score, outcome, _, _ = evaluate(
        ctx("42000.00", new_payee=True, hour=3),
        [SimSwapSignal(swapped=True, raw={}),
         CallForwardingSignal(active=True, raw={}),
         RoamingSignal(roaming=True, country_names=["HU"], raw={})])
    assert score >= DECLINE_AT_OR_ABOVE
    assert outcome is DecisionOutcome.INTERVENE


# ------------------------------------------------------- the trace itself


def test_trace_is_readable_and_arithmetic_holds():
    context = ctx("42000.00", new_payee=True)
    sigs = signals(**ALL_BAD, location=LocationVerificationResult.TRUE)
    score, trace = build_trace(context, sigs)

    assert [s.step for s in trace] == list(range(1, len(trace) + 1))
    assert trace[-1].running_score == score
    for step in trace:
        assert step.observed and step.rationale, "every step must be renderable"
        assert 0 <= step.running_score <= 100

    running = 0
    for step in trace:
        running += step.score_delta
        assert step.running_score == max(0, min(100, running))


def test_trace_records_signal_provenance():
    """A fallback must be visible in the narrative, not just in the database."""
    cached = SimSwapSignal(swapped=True, raw={}, source=SignalSource.FALLBACK,
                           fallback_reason="sim_swap: HTTP 500", latency_ms=1012.0)
    _, trace = build_trace(ctx("9000.00", new_payee=True), [cached])
    signal_steps = [s for s in trace if s.kind == "signal"]
    assert signal_steps[0].source == "fallback"
    assert signal_steps[0].latency_ms == 1012.0


@pytest.mark.parametrize("hour,expected_flag", [(3, True), (14, False), (23, False)])
def test_unusual_hour_only_counts_overnight(hour, expected_flag):
    score = build_trace(ctx("100.00", new_payee=False, hour=hour), [])[0]
    assert (score > 0) is expected_flag
