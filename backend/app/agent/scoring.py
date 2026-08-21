"""Deterministic risk scoring.

Why this exists as a separate module rather than being the LLM's job:

The hackathon rewards agentic orchestration, and the agent genuinely is agentic — it
chooses which network signals to pull. But this is a payments system. If a bank asks
"why 43?", the answer cannot be "the model produced that number". The same transaction
and the same signals must always yield the same score, and the weights must be readable
by a compliance officer. So the model orchestrates and explains; this file scores.

Every weight is in one dict, deliberately, so it can be reviewed at a glance.
"""

from app.agent.schemas import ReasoningStep, TransactionContext
from app.camara.models import (
    CallForwardingSignal,
    LocationSignal,
    LocationVerificationResult,
    RoamingSignal,
    SignalResult,
    SimSwapSignal,
)
from app.db.models import DecisionOutcome

WEIGHTS = {
    # --- transaction context ---
    "new_beneficiary": 15,
    "amount_over_5k": 10,
    "amount_over_10k": 15,
    "amount_over_25k": 20,
    "unusual_hour": 5,
    # --- network signals ---
    # Call forwarding outranks SIM swap for APP fraud. A swapped SIM says an identity was
    # compromised at some point; forwarding says the customer's calls are being
    # intercepted RIGHT NOW, which is what a scam in progress looks like.
    "call_forwarding_active": 30,
    "sim_swap_recent": 15,
    "roaming": 8,
    "roaming_with_new_beneficiary": 7,
    "location_false": 25,
    "location_partial": 10,
    "location_unknown": 5,
    "location_true": -5,  # corroborating evidence should be allowed to reduce risk
}

APPROVE_BELOW = 30
DECLINE_AT_OR_ABOVE = 70
UNUSUAL_HOURS = range(0, 6)  # 00:00-05:59 local

Finding = tuple[str, int, str, str]  # observed, delta, rationale, weight key


def score_context(ctx: TransactionContext) -> list[Finding]:
    """Every context factor that applies, before any network signal is pulled."""
    found: list[Finding] = []

    if ctx.is_new_beneficiary:
        found.append((
            "First-time beneficiary", WEIGHTS["new_beneficiary"],
            "Money sent to an account never paid before is the single most common shape "
            "of an authorised push payment scam.", "new_beneficiary"))

    amount = float(ctx.amount)
    for threshold, key in ((25_000, "amount_over_25k"), (10_000, "amount_over_10k"),
                           (5_000, "amount_over_5k")):
        if amount > threshold:
            found.append((
                f"Amount {ctx.amount} {ctx.currency} is above {threshold:,}",
                WEIGHTS[key],
                "Large transfers are where APP fraud losses concentrate.", key))
            break

    if ctx.local_hour in UNUSUAL_HOURS:
        found.append((
            f"Initiated at {ctx.local_hour:02d}:00 local", WEIGHTS["unusual_hour"],
            "Payments made in the small hours often mean the customer is being kept on "
            "the phone and pressured to act before they can check.", "unusual_hour"))

    return found


def _score_call_forwarding(signal: CallForwardingSignal) -> list[Finding]:
    if not signal.active:
        return [("No call forwarding active", 0,
                 "Calls reach the customer normally.", "call_forwarding_clean")]
    types = ", ".join(t for t in signal.forwarding_types if t != "inactive")
    detail = f" ({types})" if types else ""
    return [(
        f"Unconditional call forwarding is ACTIVE{detail}",
        WEIGHTS["call_forwarding_active"],
        "The customer's incoming calls are being redirected. A bank calling to verify "
        "would not reach them — this is what an in-progress scam looks like, not merely "
        "a past compromise.", "call_forwarding_active")]


def _score_sim_swap(signal: SimSwapSignal) -> list[Finding]:
    if not signal.swapped:
        return [("No recent SIM swap", 0,
                 "The SIM behind this number has not changed.", "sim_swap_clean")]
    when = (f" on {signal.latest_sim_change:%Y-%m-%d}"
            if signal.latest_sim_change else " recently")
    return [(
        f"SIM was swapped{when}", WEIGHTS["sim_swap_recent"],
        "A recent SIM change means one-time passcodes may reach someone else. Weaker "
        "evidence here than usual, because in APP fraud the genuine customer is the one "
        "authorising the payment.", "sim_swap_recent")]


def _score_roaming(signal: RoamingSignal, ctx: TransactionContext) -> list[Finding]:
    if not signal.roaming:
        return [("Device on its home network", 0,
                 "No roaming risk factor.", "roaming_clean")]
    where = ", ".join(signal.country_names) or str(signal.country_code or "abroad")
    found: list[Finding] = [(
        f"Device is roaming in {where}", WEIGHTS["roaming"],
        "A customer abroad is harder to reach and easier to pressure.", "roaming")]
    if ctx.is_new_beneficiary:
        found.append((
            "Roaming AND paying a first-time beneficiary",
            WEIGHTS["roaming_with_new_beneficiary"],
            "This combination is the classic APP fraud pattern — travelling, isolated, "
            "and sending money somewhere new.", "roaming_with_new_beneficiary"))
    return found


_LOCATION_RATIONALE = {
    LocationVerificationResult.FALSE: (
        "location_false",
        "The network does not place the device where this payment claims to originate. "
        "That points away from a customer being coerced and towards someone else "
        "operating the account."),
    LocationVerificationResult.PARTIAL: (
        "location_partial",
        "The network can only partially place the device in the expected area."),
    LocationVerificationResult.UNKNOWN: (
        "location_unknown",
        "The network cannot locate the device, so this check adds no assurance."),
    LocationVerificationResult.TRUE: (
        "location_true",
        "The device is where the payment says it is. The genuine customer appears to be "
        "present and holding their own phone."),
}


def _score_location(signal: LocationSignal) -> list[Finding]:
    key, rationale = _LOCATION_RATIONALE[signal.verification_result]
    rate = f" (match rate {signal.match_rate}%)" if signal.match_rate is not None else ""
    return [(f"Location check returned {signal.verification_result.value}{rate}",
             WEIGHTS[key], rationale, key)]


def score_signal(signal: SignalResult, ctx: TransactionContext) -> list[Finding]:
    if isinstance(signal, CallForwardingSignal):
        return _score_call_forwarding(signal)
    if isinstance(signal, SimSwapSignal):
        return _score_sim_swap(signal)
    if isinstance(signal, RoamingSignal):
        return _score_roaming(signal, ctx)
    if isinstance(signal, LocationSignal):
        return _score_location(signal)
    return []


def customer_appears_absent(signals: list[SignalResult]) -> bool:
    """Do we have positive evidence the customer is NOT where the payment claims?"""
    return any(
        isinstance(s, LocationSignal)
        and s.verification_result is LocationVerificationResult.FALSE
        for s in signals
    )


def choose_outcome(score: int, signals: list[SignalResult]) -> tuple[DecisionOutcome, str]:
    """Turn a score into an action. Returns (outcome, rationale).

    The rule that matters, and the product thesis in one line: **we do not decline a
    payment when the customer appears to be present and reachable — we phone them.**

    A silent decline on a legitimate payment is a real cost to a real customer, and it is
    also the wrong response to coercion: if someone is being talked into this, a thirty
    second call resolves it and a decline does not. Decline is reserved for the case where
    the evidence says the person transacting probably is not the customer at all.
    """
    if score < APPROVE_BELOW:
        return DecisionOutcome.APPROVE, (
            f"Risk score {score} is below the {APPROVE_BELOW} threshold; nothing in the "
            "signals justifies delaying this payment.")

    if score >= DECLINE_AT_OR_ABOVE and customer_appears_absent(signals):
        return DecisionOutcome.DECLINE, (
            f"Risk score {score} is at or above {DECLINE_AT_OR_ABOVE}, and the network "
            "does not place the device where this payment originates. That reads as "
            "account takeover rather than a customer under pressure, so calling the "
            "registered number would not reach the person transacting.")

    return DecisionOutcome.INTERVENE, (
        f"Risk score {score} warrants holding the payment, but the customer appears to be "
        "present and reachable. Declining silently would be the wrong response to "
        "coercion — we call them before the money moves.")


def build_trace(ctx: TransactionContext,
                signals: list[SignalResult]) -> tuple[int, list[ReasoningStep]]:
    """Assemble the running narrative and the final score together."""
    steps: list[ReasoningStep] = []
    running = 0

    def clamp(value: int) -> int:
        return max(0, min(100, value))

    for observed, delta, rationale, _key in score_context(ctx):
        running += delta
        steps.append(ReasoningStep(
            step=len(steps) + 1, kind="context", observed=observed, rationale=rationale,
            score_delta=delta, running_score=clamp(running)))

    for signal in signals:
        for observed, delta, rationale, _key in score_signal(signal, ctx):
            running += delta
            steps.append(ReasoningStep(
                step=len(steps) + 1, kind="signal", signal=signal.api_name,
                observed=observed, rationale=rationale, score_delta=delta,
                running_score=clamp(running), source=str(signal.source),
                latency_ms=round(signal.latency_ms, 1)))

    return clamp(running), steps
