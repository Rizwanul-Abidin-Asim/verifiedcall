"""Channel trust: which routes to the customer the network still vouches for.

The distinction these tests exist to protect is between a channel we know is closed and
one we never checked. Collapsing the two is the easy mistake, and it is the dangerous
one: it turns a tool call the agent chose to skip into grounds for refusing somebody's
payment.
"""

from app.agent.channels import NOT_VOUCHED, SILENT_SIEGE, Channel, assess_channels
from app.agent.scoring import choose_outcome
from app.camara.models import (
    CallForwardingSignal,
    DeviceSwapSignal,
    LocationSignal,
    LocationVerificationResult,
    ReachabilitySignal,
    SimSwapSignal,
)
from app.db.models import DecisionOutcome

REACHABLE_BOTH = ReachabilitySignal(reachable=True, connectivity=["SMS", "DATA"])
REACHABLE_SMS = ReachabilitySignal(reachable=True, connectivity=["SMS"])
UNREACHABLE = ReachabilitySignal(reachable=False, connectivity=[])
CLEAN_FORWARDING = CallForwardingSignal(active=False)
FORWARDED = CallForwardingSignal(active=True, forwarding_types=["unconditional"])
CLEAN_SIM = SimSwapSignal(swapped=False)
SWAPPED_SIM = SimSwapSignal(swapped=True)
CLEAN_DEVICE = DeviceSwapSignal(swapped=False)
SWAPPED_DEVICE = DeviceSwapSignal(swapped=True)


def verdict(assessment, channel):
    return assessment.verdict_for(channel)


# ------------------------------------------------- silence is not evidence


def test_no_signals_is_not_a_siege():
    """The regression that matters most.

    With nothing pulled every channel is unproven. If that read as "all doors shut", an
    agent deciding a small payment needed no network checks would have its customer's
    payment declined for being unreachable — on the strength of no evidence at all.
    """
    assessment = assess_channels([])
    assert assessment.no_safe_channel is False
    assert assessment.preferred is None
    assert all(v.evidence_missing for v in assessment.verdicts)
    assert all(v.blocked_by is None for v in assessment.verdicts)
    # The sentence shown on the fraud desk must not be the siege verdict either: an
    # approved payment's Reach tab once read "every route is barred, human paged".
    assert assessment.strategy != SILENT_SIEGE
    assert assessment.strategy == NOT_VOUCHED
    assert "barred" not in assessment.strategy.lower().replace("unproven is not barred", "")


def test_partially_checked_is_not_a_siege():
    """One closed door and two unchecked ones is not the same as three closed doors."""
    assessment = assess_channels([FORWARDED])
    assert verdict(assessment, Channel.VOICE).trusted is False
    assert assessment.no_safe_channel is False


def test_unproven_and_blocked_are_distinguishable():
    """The dashboard renders these differently, so they must not be one flag."""
    assessment = assess_channels([FORWARDED, REACHABLE_BOTH])
    voice = verdict(assessment, Channel.VOICE)
    sms = verdict(assessment, Channel.SMS)

    assert voice.blocked_by == "call_forwarding" and voice.evidence_missing is False
    assert sms.blocked_by is None and sms.evidence_missing is True


# ------------------------------------------------- each door, and what shuts it


def test_forwarding_shuts_the_voice_door():
    assessment = assess_channels([FORWARDED, CLEAN_SIM, CLEAN_DEVICE, REACHABLE_BOTH])
    assert verdict(assessment, Channel.VOICE).blocked_by == "call_forwarding"
    assert assessment.preferred is Channel.APP_PUSH


def test_sim_swap_shuts_the_sms_door():
    assessment = assess_channels([CLEAN_FORWARDING, SWAPPED_SIM, CLEAN_DEVICE,
                                  REACHABLE_BOTH])
    assert verdict(assessment, Channel.SMS).blocked_by == "sim_swap"
    assert verdict(assessment, Channel.VOICE).trusted is True


def test_device_swap_shuts_the_app_door():
    assessment = assess_channels([FORWARDED, CLEAN_SIM, SWAPPED_DEVICE, REACHABLE_BOTH])
    assert verdict(assessment, Channel.APP_PUSH).blocked_by == "device_swap"


def test_no_data_path_shuts_the_app_door():
    """Reachable by text is not reachable by app. The connectivity list is per-channel."""
    assessment = assess_channels([FORWARDED, CLEAN_SIM, CLEAN_DEVICE, REACHABLE_SMS])
    assert verdict(assessment, Channel.APP_PUSH).blocked_by == "device_reachability"
    assert verdict(assessment, Channel.SMS).trusted is True
    assert assessment.preferred is Channel.SMS


def test_unreachable_device_shuts_every_network_door():
    assessment = assess_channels([CLEAN_FORWARDING, CLEAN_SIM, CLEAN_DEVICE, UNREACHABLE])
    assert verdict(assessment, Channel.SMS).blocked_by == "device_reachability"
    assert verdict(assessment, Channel.APP_PUSH).blocked_by == "device_reachability"
    assert verdict(assessment, Channel.VOICE).blocked_by == "device_reachability"
    assert assessment.no_safe_channel is True


# ------------------------------------------------- preference order


def test_voice_wins_when_everything_is_open():
    """Only a conversation can tell a coerced answer from a free one, so it goes first."""
    assessment = assess_channels([CLEAN_FORWARDING, CLEAN_SIM, CLEAN_DEVICE,
                                  REACHABLE_BOTH])
    assert set(assessment.trusted_channels()) == {Channel.VOICE, Channel.APP_PUSH,
                                                  Channel.SMS}
    assert assessment.preferred is Channel.VOICE


def test_app_beats_sms_when_voice_is_gone():
    """SMS is last even when it works: 'read me the code' is the oldest line in this
    fraud, and anything a customer can say aloud the caller can have."""
    assessment = assess_channels([FORWARDED, CLEAN_SIM, CLEAN_DEVICE, REACHABLE_BOTH])
    assert Channel.SMS in assessment.trusted_channels()
    assert assessment.preferred is Channel.APP_PUSH


# ------------------------------------------------- what it does to the outcome


def test_siege_turns_a_hold_into_a_hold_plus_escalation():
    """We do not phone a line the attacker is holding just because the score said hold."""
    siege = assess_channels([FORWARDED, SWAPPED_SIM, SWAPPED_DEVICE, UNREACHABLE])
    assert siege.no_safe_channel is True

    outcome, rationale = choose_outcome(55, [FORWARDED, SWAPPED_SIM], siege)
    assert outcome is DecisionOutcome.DECLINE
    assert "human analyst is paged" in rationale


def test_unchecked_channels_still_allow_an_ordinary_intervention():
    """The counterpart to the siege test: absent evidence must not escalate anything."""
    outcome, _ = choose_outcome(55, [], assess_channels([]))
    assert outcome is DecisionOutcome.INTERVENE


def test_absent_customer_still_declines_regardless_of_channels():
    """Channel routing does not override the theft case. If the network cannot place the
    device where the payment came from, reaching the registered phone is beside the
    point — it is not the person spending the money."""
    absent = LocationSignal(verification_result=LocationVerificationResult.FALSE)
    open_channels = assess_channels([CLEAN_FORWARDING, CLEAN_SIM, CLEAN_DEVICE,
                                     REACHABLE_BOTH])
    outcome, _ = choose_outcome(85, [absent], open_channels)
    assert outcome is DecisionOutcome.DECLINE


def test_a_clean_payment_is_approved_without_asking_about_channels():
    """Below the flag threshold we have no reason to contact anybody, so a closed channel
    must not drag an ordinary payment into a hold."""
    siege = assess_channels([FORWARDED, SWAPPED_SIM, SWAPPED_DEVICE, UNREACHABLE])
    outcome, _ = choose_outcome(10, [], siege)
    assert outcome is DecisionOutcome.APPROVE
