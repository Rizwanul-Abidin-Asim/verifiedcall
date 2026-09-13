"""Channel trust — which door can we still knock on?

Every other part of this system asks "how risky is this payment?". This module asks the
question that actually decides whether an intervention is worth attempting:

    If we reach out to this customer, is the attacker standing in the way?

It matters because an intervention delivered over a channel the attacker controls is
worse than no intervention at all. It does not just fail — it *helps them*. A scammer who
intercepts the bank's verification call gets to play the part of the bank ("yes, that's
us confirming, go ahead"), and the customer's last chance to be interrupted becomes the
thing that convinces them.

So before we contact anybody we work out, per channel, whether the network says that
channel is still ours. Three facts about three doors:

    voice     Call Forwarding Signal   are calls being diverted?
    sms       SIM Swap                 would texts land on a different SIM?
    app push  Device Swap + Device Reachability
                                       is there a data path, and is the app still on the
                                       handset we know?

This is deterministic, for the same reason scoring.py is: "we did not call the customer
because the network said their calls were being diverted" is a sentence a bank may have
to defend to a regulator, and it must come out the same way every time. The model's job
is to decide what to SAY once this module has decided where it can be said. See ADR-006.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from app.camara.models import (
    CallForwardingSignal,
    DeviceSwapSignal,
    ReachabilitySignal,
    SignalResult,
    SimSwapSignal,
)


class Channel(StrEnum):
    VOICE = "voice"
    SMS = "sms"
    APP_PUSH = "app_push"


class ChannelVerdict(BaseModel):
    """One door, and whether the network says it is still ours."""

    channel: Channel
    trusted: bool
    reason: str
    """Written for a fraud analyst, not a developer. Rendered on the dashboard."""
    blocked_by: str | None = None
    """The api_name of the signal that closed this channel, when one did."""
    evidence_missing: bool = False
    """True when we could not prove the channel safe because we never pulled the signal.

    Distinct from `trusted=False`. Unproven is not the same as compromised, and the
    dashboard says which is which rather than collapsing both into a red cross."""


class ChannelAssessment(BaseModel):
    """The full picture, and the routing decision that follows from it."""

    verdicts: list[ChannelVerdict]
    preferred: Channel | None = None
    """Where the intervention should go. None when every door is closed."""
    strategy: str = ""
    """Why that channel, in one sentence a judge can follow."""
    signals_used: list[str] = Field(default_factory=list)

    @computed_field  # must reach the dashboard, which renders the siege state from it
    @property
    def no_safe_channel(self) -> bool:
        """Every door we actually asked about is positively closed.

        Deliberately NOT "we did not find a trusted channel". Those are different
        statements and conflating them is dangerous: on a run where the agent pulled no
        channel-bearing signals at all, every verdict is `evidence_missing`, and reading
        that as a siege would let a skipped tool call decline a real customer's payment.

        So this requires a `blocked_by` on every channel — a named signal that closed it.
        Silence is not evidence. The same principle as customer_appears_absent() in
        scoring.py, which refuses to infer absence from a location check nobody ran.
        """
        return bool(self.verdicts) and all(v.blocked_by for v in self.verdicts)

    def trusted_channels(self) -> list[Channel]:
        return [v.channel for v in self.verdicts if v.trusted]

    def verdict_for(self, channel: Channel) -> ChannelVerdict | None:
        return next((v for v in self.verdicts if v.channel is channel), None)


NOT_VOUCHED = (
    "No route has been vouched for, because the checks that would prove a door is still "
    "the customer's were not needed for this payment. Unproven is not barred: had this "
    "payment been held, those checks would have run before anyone was contacted."
)
"""The wording when nothing was checked and nothing was barred, typically an approved
payment. It must never read like the siege verdict below."""

SILENT_SIEGE = (
    "No channel the network can vouch for is still open to this customer. We are not "
    "going to attempt contact: every remaining route runs through somebody we cannot "
    "identify, and using one would tell them the bank is watching while handing them "
    "the bank's own voice. The payment is held and a human fraud analyst is paged."
)
"""The verdict when every door is shut.

Worth stating plainly because it inverts the usual reading. Ordinarily "we could not
reach the customer" is a failure of the intervention. Here it is the single most
informative thing the network has told us: somebody has arranged, at the moment of a
high-risk payment, for this person to be unreachable by their bank. That does not happen
by accident."""


def _voice(
    forwarding: CallForwardingSignal | None, reachability: ReachabilitySignal | None,
) -> ChannelVerdict:
    """Voice is our best channel and the easiest one to poison.

    Best, because only a conversation catches coaching — a coerced customer taps "yes" on
    a screen exactly as fast as a free one does, but they answer questions differently
    when somebody is listening.

    Easiest to poison, because unconditional call forwarding is a single toggle and the
    diverted call is indistinguishable, from our side, from a successful one.
    """
    if forwarding is None:
        return ChannelVerdict(
            channel=Channel.VOICE, trusted=False, evidence_missing=True,
            reason="We never checked whether this customer's calls are being diverted, "
                   "so we cannot say a call would reach them rather than somebody else.")

    if forwarding.active:
        types = ", ".join(t for t in forwarding.forwarding_types if t != "inactive")
        return ChannelVerdict(
            channel=Channel.VOICE, trusted=False, blocked_by="call_forwarding",
            reason=f"Calls to this number are being diverted"
                   f"{f' ({types})' if types else ''}. Phoning to verify the payment "
                   f"would connect us to whoever set up the diversion, and let them "
                   f"confirm the transfer in the customer's place.")

    # Reachability reports SMS and DATA; it does not report circuit-switched voice. A
    # device the network cannot reach at all is unlikely to take a call either, but we
    # say "probably" rather than pretending to a certainty the API did not give us.
    if reachability is not None and not reachability.reachable:
        return ChannelVerdict(
            channel=Channel.VOICE, trusted=False, blocked_by="device_reachability",
            reason="Calls are not being diverted, but the network cannot reach this "
                   "device at all, so a call would probably not connect either.")

    return ChannelVerdict(
        channel=Channel.VOICE, trusted=True,
        reason="No diversion is active, so a call to this number reaches the customer's "
               "own handset.")


def _sms(
    sim_swap: SimSwapSignal | None, reachability: ReachabilitySignal | None,
) -> ChannelVerdict:
    """SMS is the channel we trust least even when it works.

    A swapped SIM receives the texts, which is the obvious failure. The less obvious one
    is that SMS survives coercion badly: "read me the code they just sent you" is the
    single most rehearsed line in this kind of fraud, and a code the customer can say out
    loud is a code the attacker can have. So SMS is a last resort here, and never carries
    anything that would be useful to repeat aloud.
    """
    if reachability is not None and not reachability.has_sms:
        detail = ("the network cannot reach this device at all"
                  if not reachability.reachable else
                  "the network reports no SMS path to this device right now")
        return ChannelVerdict(
            channel=Channel.SMS, trusted=False, blocked_by="device_reachability",
            reason=f"A text would not arrive: {detail}.")

    if sim_swap is None:
        return ChannelVerdict(
            channel=Channel.SMS, trusted=False, evidence_missing=True,
            reason="We never checked for a SIM swap, so we cannot say a text would "
                   "reach this customer's SIM rather than a replacement one.")

    if sim_swap.swapped:
        when = (f" on {sim_swap.latest_sim_change:%d %b}"
                if sim_swap.latest_sim_change else " recently")
        return ChannelVerdict(
            channel=Channel.SMS, trusted=False, blocked_by="sim_swap",
            reason=f"The SIM behind this number was replaced{when}. A text would be "
                   f"delivered to whoever holds the new SIM.")

    return ChannelVerdict(
        channel=Channel.SMS, trusted=True,
        reason="The SIM has not changed and the network reports an SMS path, so a text "
               "reaches the customer's own SIM.")


def _app_push(
    device_swap: DeviceSwapSignal | None, reachability: ReachabilitySignal | None,
) -> ChannelVerdict:
    """The in-app channel: quiet, and that is the point.

    A scammer keeping someone on the phone hears a bank call arrive and can talk over it.
    They do not hear a notification. When the voice line is compromised this is usually
    the only door left that the attacker is not standing in front of.

    Two things have to hold: a data path must exist, and the app has to still be on the
    handset we know about. CAMARA's proper answer to the second is Number Verification,
    which binds the number to the device over its mobile data connection — but that call
    needs a three-legged OIDC token the handset itself has to fetch, so a server cannot
    make it (docs/camara-findings.md). Device Swap is the available proxy: it does not
    prove the right phone is holding the session, but it does tell us when a different
    one started holding the SIM.
    """
    if reachability is None:
        return ChannelVerdict(
            channel=Channel.APP_PUSH, trusted=False, evidence_missing=True,
            reason="We never checked reachability, so we cannot say whether there is a "
                   "data path to the customer's app.")

    if not reachability.has_data:
        detail = ("the network cannot reach this device at all"
                  if not reachability.reachable else
                  "the network reports this device is reachable by text but has no data "
                  "connection")
        return ChannelVerdict(
            channel=Channel.APP_PUSH, trusted=False, blocked_by="device_reachability",
            reason=f"An in-app prompt would not arrive: {detail}.")

    if device_swap is not None and device_swap.swapped:
        when = (f" on {device_swap.latest_device_change:%d %b}"
                if device_swap.latest_device_change else " recently")
        return ChannelVerdict(
            channel=Channel.APP_PUSH, trusted=False, blocked_by="device_swap",
            reason=f"This SIM moved into a different handset{when}. We cannot assume the "
                   f"banking app is still on the phone the customer is holding.")

    unproven = " We have not confirmed the handset itself, only that it has not changed."
    return ChannelVerdict(
        channel=Channel.APP_PUSH, trusted=True,
        reason="There is a data path to the device and the handset behind this SIM has "
               "not changed, so an in-app prompt reaches the customer quietly — without "
               "anyone listening on the call hearing it arrive." + unproven)


# Order matters and encodes a judgement, so it is written down rather than implied.
#
# Voice first: it is the only channel that can tell a frightened customer from a free
# one, because it is the only one where the answers have texture. A tap is a tap.
#
# App push second: it cannot detect coercion the way a conversation can, so when we fall
# back to it we also change what we ask — see voice/scripts.py. Its advantage is silence.
#
# SMS last, and only to say "check your app", never to carry anything worth reading out.
_PREFERENCE = (Channel.VOICE, Channel.APP_PUSH, Channel.SMS)

_STRATEGY = {
    Channel.VOICE: "Calls are not being diverted, so we speak to the customer — a "
                   "conversation is the only channel that can tell a coerced answer "
                   "from a free one.",
    Channel.APP_PUSH: "The voice line cannot be trusted, so we move to the app instead. "
                      "It reaches the customer without the person on the phone hearing "
                      "it, and we ask differently because a tap cannot reveal coercion.",
    Channel.SMS: "Voice and the app are both unavailable, so a text is all that is "
                 "left. It carries no code and no amount — only a prompt to open the "
                 "app — because anything in it can be read aloud to the caller.",
}


def assess_channels(signals: list[SignalResult]) -> ChannelAssessment:
    """Decide where an intervention can safely be delivered.

    Takes whatever signals the agent chose to pull. Missing signals do not crash this —
    they produce `evidence_missing`, which reads as "unproven", not "compromised". That
    distinction is the whole reason this returns verdicts rather than booleans.
    """
    def find(api_name: str):
        return next((s for s in signals if s.api_name == api_name), None)

    forwarding = find("call_forwarding")
    sim_swap = find("sim_swap")
    device_swap = find("device_swap")
    reachability = find("device_reachability")

    verdicts = [
        _voice(forwarding, reachability),
        _app_push(device_swap, reachability),
        _sms(sim_swap, reachability),
    ]

    trusted = {v.channel for v in verdicts if v.trusted}
    preferred = next((c for c in _PREFERENCE if c in trusted), None)
    if preferred:
        strategy = _STRATEGY[preferred]
    elif all(v.blocked_by for v in verdicts):
        strategy = SILENT_SIEGE
    else:
        # Nothing vouched for, but nothing barred either: the checks were simply not
        # needed. Saying "every route is barred" here would present an unproven door as a
        # compromised one, the exact confusion channel trust exists to prevent.
        strategy = NOT_VOUCHED

    return ChannelAssessment(
        verdicts=verdicts,
        preferred=preferred,
        strategy=strategy,
        signals_used=[s.api_name for s in (forwarding, sim_swap, device_swap,
                                           reachability) if s is not None],
    )
