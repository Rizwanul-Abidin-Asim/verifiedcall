"""Deterministic risk scoring.

Why this exists as a separate module rather than being the LLM's job:

The hackathon rewards agentic orchestration, and the agent genuinely is agentic — it
chooses which network signals to pull. But this is a payments system. If a bank asks
"why 43?", the answer cannot be "the model produced that number". The same transaction
and the same signals must always yield the same score, and the weights must be readable
by a compliance officer. So the model orchestrates and explains; this file scores.

Every weight is in one dict, deliberately, so it can be reviewed at a glance.
"""

from typing import TYPE_CHECKING

from app.agent.schemas import ReasoningStep, TransactionContext

if TYPE_CHECKING:  # channels imports models, not scoring — kept one-way on purpose
    from app.agent.channels import ChannelAssessment
from app.camara.models import (
    CallForwardingSignal,
    DeviceSwapSignal,
    LocationSignal,
    LocationVerificationResult,
    ReachabilitySignal,
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
    # Refusing to share position is weak evidence and weighted like it. It removes a
    # check rather than proving anything, and plenty of careful people decline.
    "device_location_denied": 5,
    # --- network signals ---
    # Forwarding is scored by TYPE, not as one boolean. Unconditional forwarding sends
    # every call straight elsewhere and is the shape of an interception set up for this
    # purpose. Conditional forwarding only fires when the line is busy or unanswered,
    # which describes a great many ordinary people with voicemail, so it earns a fraction
    # of the weight rather than the same 30.
    "call_forwarding_unconditional": 30,
    "call_forwarding_conditional": 12,
    # Raised from 15. A swapped SIM is one of the strongest single fraud indicators there
    # is, and weighting it down because *our* scenario is APP fraud confused "less
    # decisive for coercion" with "weak evidence". It is still below unconditional
    # forwarding, because a swap says an identity was compromised at some point while
    # forwarding says a scam is running right now.
    "sim_swap_recent": 22,
    # Alone, a new handset is usually a new phone. Its weight lives in the pairing below.
    "device_swap_recent": 12,
    "sim_and_device_swap": 18,
    # Not a risk factor in the ordinary sense — it is the absence of a way to intervene.
    # Scored because being unreachable *at the moment of a high-value first-time payment*
    # is not a coincidence worth ignoring.
    "device_unreachable": 12,
    "roaming": 8,
    "roaming_with_new_beneficiary": 7,
    "location_false": 25,
    "location_partial": 10,
    "location_unknown": 5,
    # Deliberately zero, and it used to be -5. A device sitting exactly where the payment
    # claims is equally consistent with a normal payment, a customer being talked through
    # it by a fraudster, a customer under duress, and someone else holding the handset.
    # It tells us WHICH kind of trouble this could be — which is why choose_outcome()
    # leans on it hard — but it is not evidence that there is no trouble. See ADR-005.
    "location_true": 0,
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

    if ctx.device_location_denied:
        found.append((
            "Device would not share its location", WEIGHTS["device_location_denied"],
            "Without the handset's own position we cannot ask the network whether it "
            "agrees, so one of two independent checks is missing. Weighted lightly: "
            "declining to share a location is common and not itself suspicious.",
            "device_location_denied"))

    if ctx.local_hour in UNUSUAL_HOURS:
        found.append((
            f"Initiated at {ctx.local_hour:02d}:00 local", WEIGHTS["unusual_hour"],
            "Payments made in the small hours often mean the customer is being kept on "
            "the phone and pressured to act before they can check.", "unusual_hour"))

    return found


def _score_call_forwarding(signal: CallForwardingSignal) -> list[Finding]:
    """Weighted by the kind of forwarding, because the kinds mean different things.

    `active` on the unconditional endpoint is the authoritative boolean; the type list
    from /call-forwardings is informational and may be unavailable (501 on some
    operators), so unconditional is inferred from `active` rather than from the list.
    """
    types = [t for t in signal.forwarding_types if t != "inactive"]

    if not signal.active and not types:
        return [("No call forwarding active", 0,
                 "Calls reach the customer normally.", "call_forwarding_clean")]

    if signal.active:
        detail = f" (also: {', '.join(t for t in types if t != 'unconditional')})" \
            if len(types) > 1 else ""
        return [(
            f"UNCONDITIONAL call forwarding is active{detail}",
            WEIGHTS["call_forwarding_unconditional"],
            "Every incoming call is being sent elsewhere. The bank's own verification "
            "call would be answered by whoever set this up — so this is not only "
            "evidence of a scam in progress, it closes the channel we would normally "
            "use to stop it.", "call_forwarding_unconditional")]

    # Conditional only: calls divert when busy or unanswered. Suspicious in context,
    # unremarkable on its own — this is what voicemail looks like.
    return [(
        f"Conditional call forwarding is active ({', '.join(types)})",
        WEIGHTS["call_forwarding_conditional"],
        "Calls divert only when the line is busy or goes unanswered. That is ordinary "
        "voicemail behaviour for most people, so it is weighted well below unconditional "
        "forwarding — but it does mean a missed call could be picked up elsewhere.",
        "call_forwarding_conditional")]


def _score_sim_swap(signal: SimSwapSignal) -> list[Finding]:
    if not signal.swapped:
        return [("No recent SIM swap", 0,
                 "The SIM behind this number has not changed.", "sim_swap_clean")]
    when = (f" on {signal.latest_sim_change:%Y-%m-%d}"
            if signal.latest_sim_change else " recently")
    return [(
        f"SIM was swapped{when}", WEIGHTS["sim_swap_recent"],
        "A recent SIM change means one-time passcodes and verification texts may be "
        "arriving on somebody else's SIM. It does not decide between theft and coercion "
        "on its own — in a coerced payment the genuine customer is still the one "
        "authorising — but it is strong evidence that this number's identity has already "
        "been interfered with, and it closes SMS as a way to reach them.",
        "sim_swap_recent")]


def _score_device_swap(signal: DeviceSwapSignal) -> list[Finding]:
    if not signal.swapped:
        return [("Same handset as before", 0,
                 "The SIM has not moved into a different phone.", "device_swap_clean")]
    when = (f" on {signal.latest_device_change:%Y-%m-%d}"
            if signal.latest_device_change else " recently")
    return [(
        f"SIM moved into a different handset{when}", WEIGHTS["device_swap_recent"],
        "On its own this is usually somebody replacing a broken phone, so it is weighted "
        "lightly. It matters mainly because it means we cannot assume the banking app is "
        "still on the device the customer is holding.", "device_swap_recent")]


def score_combinations(signals: list[SignalResult]) -> list[Finding]:
    """Findings that only exist when two signals are read together.

    Kept separate from score_signal() because a combination is not a property of any one
    signal, and burying it inside whichever happened to be scored last would make the
    weights table unreadable.
    """
    found: list[Finding] = []

    sim = next((s for s in signals if isinstance(s, SimSwapSignal)), None)
    device = next((s for s in signals if isinstance(s, DeviceSwapSignal)), None)
    if sim is not None and device is not None and sim.swapped and device.swapped:
        found.append((
            "Both the SIM and the handset changed",
            WEIGHTS["sim_and_device_swap"],
            "Either alone is usually innocent — people replace lost SIMs and broken "
            "phones. Together they are the shape of somebody rebuilding this customer's "
            "identity on hardware they control, which is why the pair scores more than "
            "the sum of its parts.", "sim_and_device_swap"))

    reach = next((s for s in signals if isinstance(s, ReachabilitySignal)), None)
    if reach is not None and not reach.reachable:
        found.append((
            "The network cannot reach this device on any channel",
            WEIGHTS["device_unreachable"],
            "Not a risk factor so much as the loss of every way to check. A customer "
            "being unreachable by their bank at the exact moment of a high-value payment "
            "to a new payee is a coincidence worth pricing in.", "device_unreachable"))

    return found


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
        "The device is where the payment says it is. This does NOT make the payment "
        "safe: it is equally consistent with a normal transfer, with the customer being "
        "talked through it by a fraudster, with the customer acting under duress, and "
        "with somebody else holding their phone. What it rules out is the customer being "
        "somewhere else entirely — so it changes a decline into a conversation, and "
        "scores nothing by itself."),
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
    if isinstance(signal, DeviceSwapSignal):
        return _score_device_swap(signal)
    # Reachability and location retrieval carry no weight of their own. Reachability is
    # scored only in combination (see score_combinations) and otherwise drives channel
    # routing; retrieval exists to explain a decision, not to change it.
    return []


def customer_appears_absent(signals: list[SignalResult]) -> bool:
    """Do we have positive evidence the customer is NOT where the payment claims?"""
    return any(
        isinstance(s, LocationSignal)
        and s.verification_result is LocationVerificationResult.FALSE
        for s in signals
    )


def choose_outcome(
    score: int,
    signals: list[SignalResult],
    channels: "ChannelAssessment | None" = None,
) -> tuple[DecisionOutcome, str]:
    """Turn a score into an action. Returns (outcome, rationale).

    The rule that matters, and the product thesis in one line: **we do not decline a
    payment when the customer appears to be present and reachable — we phone them.**

    A silent decline on a legitimate payment is a real cost to a real customer, and it is
    also the wrong response to coercion: if someone is being talked into this, a thirty
    second call resolves it and a decline does not. Decline is reserved for the case where
    the evidence says the person transacting probably is not the customer at all.

    `channels` adds the second half of that sentence. "We phone them" assumed a phone we
    could reach; once the network can tell us that assumption is false, an intervention
    we cannot safely deliver is not an intervention. Optional so that callers which
    predate channel routing — and the tests — still work.
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

    if channels is not None and channels.no_safe_channel:
        closed = ", ".join(
            f"{v.channel.value} ({v.blocked_by})"
            for v in channels.verdicts if v.blocked_by)
        return DecisionOutcome.DECLINE, (
            f"Risk score {score} warrants checking with the customer, but there is no "
            f"way left to ask them: {closed}. Every remaining route to this person runs "
            "through whoever compromised it, so contacting them would confirm the scam "
            "in the bank's own voice rather than interrupt it. The payment is held and a "
            "human analyst is paged. Being unable to reach a customer at the exact "
            "moment of a high-risk payment is not a gap in the check — it is the "
            "clearest thing the network has told us.")

    if channels is not None and channels.preferred is not None:
        return DecisionOutcome.INTERVENE, (
            f"Risk score {score} warrants holding the payment, and the network says we "
            f"can still reach the customer over {channels.preferred.value}. "
            f"{channels.strategy}")

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

    # Combinations last, so the trace reads as "here is each fact, and here is what they
    # mean together" rather than interleaving the two.
    for observed, delta, rationale, _key in score_combinations(signals):
        running += delta
        steps.append(ReasoningStep(
            step=len(steps) + 1, kind="assessment", observed=observed,
            rationale=rationale, score_delta=delta, running_score=clamp(running)))

    return clamp(running), steps
