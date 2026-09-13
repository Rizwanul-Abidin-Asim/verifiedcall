"""Demo personas, and an honest account of why they are shaped like this.

In production a customer is one MSISDN and every signal is looked up against it. Nothing
in this file exists in that world.

The Nokia simulator gives each sandbox number a fixed personality across every API, and
those personalities are effectively binary — measured 2026-09-12 across +99999991000 to
+99999991012:

    +99999991001   clean everything, reachable on DATA only
    +99999991000   forwarding + SIM swap + device swap + roaming, SMS only
    +99999991002   the same, but reachable on SMS and DATA
    +99999991003+  the same, and not reachable at all

Which means no single sandbox number can express the case our whole design turns on: a
customer whose *calls* are being diverted but whose *phone* is still their own, still
carrying the banking app. Every number with forwarding switched on also reports a swapped
handset. That combination is common in reality and absent from the simulator.

So a persona maps each API to whichever sandbox number simulates the answer that story
needs. Every call is still a live call to Nokia — nothing here is cached or invented, and
`source` stays `live`. What we are choosing is which simulated customer to ask, per
question, and the audit trail records the number each answer came from because
`record_signal_call` persists the request payload. The dashboard shows it.

Say this out loud in the demo rather than letting someone find it. The seam is real and
it is the simulator's, not ours.
"""

from pydantic import BaseModel, Field

# The sandbox numbers, named by the behaviour we rely on rather than by digits.
ALL_CLEAN = "+99999991001"        # no forwarding, no swaps, DATA path, location TRUE
ALL_COMPROMISED_SMS = "+99999991000"   # forwarding + both swaps + roaming, SMS only
ALL_COMPROMISED_BOTH = "+99999991002"  # as above, reachable on SMS and DATA
UNREACHABLE = "+99999991003"      # as above, and the network cannot reach it at all
AT_HOME_COMPROMISED = "+99999991004"   # compromised signals but location verifies TRUE


class Persona(BaseModel):
    """One demo customer: a story, and where each network answer is sourced from."""

    key: str
    title: str
    story: str
    """Shown on the dashboard so the scenario is legible without the runsheet."""
    default_msisdn: str
    sources: dict[str, str] = Field(default_factory=dict)
    """api_name -> sandbox MSISDN. Anything unlisted falls back to default_msisdn."""

    def msisdn_for(self, api_name: str) -> str:
        return self.sources.get(api_name, self.default_msisdn)

    @property
    def is_composed(self) -> bool:
        """True when this persona draws on more than one sandbox number.

        Drives the seam banner. A persona that is a single number needs no caveat."""
        return bool(set(self.sources.values()) - {self.default_msisdn})

    def seam_note(self) -> str | None:
        """The disclosure line, or None when there is nothing to disclose."""
        if not self.is_composed:
            return None
        per_api = ", ".join(f"{api} from {number}"
                            for api, number in sorted(self.sources.items()))
        return (
            "Simulator seam: no single Nokia sandbox number can express this "
            "combination, so each network answer below was fetched live from the "
            f"sandbox number that simulates it ({per_api}). Every call is real; the "
            "customer is not. In production this is one number."
        )


PERSONAS: dict[str, Persona] = {
    "routine": Persona(
        key="routine",
        title="A routine payment",
        story="Rent, to a landlord she has paid for two years. Nothing about this needs "
              "the network's opinion, and the agent should say so rather than checking "
              "anyway.",
        default_msisdn=ALL_CLEAN,
    ),
    "theft": Persona(
        key="theft",
        title="Somebody else is in the account",
        story="A large first-time transfer, and the network cannot place the handset "
              "anywhere near where the payment claims to come from. This is the case "
              "where declining is the right answer: calling the registered number would "
              "reach the customer, who is not the one spending the money.",
        default_msisdn=ALL_COMPROMISED_SMS,
    ),
    "coercion_voice_open": Persona(
        key="coercion_voice_open",
        title="Coached, and we can still call",
        story="Same amount, same first-time payee, 2am — but the phone is exactly where "
              "it should be and nothing is diverting her calls. That is what being "
              "talked into it looks like from the network's side, and it is the one "
              "case where a conversation beats a decline.",
        default_msisdn=ALL_CLEAN,
    ),
    "voice_compromised": Persona(
        key="voice_compromised",
        title="Her calls are being diverted",
        story="The scam is further along: her calls are forwarded and her SIM has been "
              "replaced, so phoning her reaches the fraudster and texting her reaches "
              "his SIM. Her handset has not changed and it still has a data path — so "
              "the app is the one door he is not standing in front of.",
        default_msisdn=ALL_COMPROMISED_SMS,
        sources={
            # Forwarding + SIM swap come from the compromised number: these are what
            # close the voice and SMS doors.
            "call_forwarding": ALL_COMPROMISED_SMS,
            "sim_swap": ALL_COMPROMISED_SMS,
            # The handset is still hers, and still has data. The simulator only offers
            # these answers on the clean numbers.
            "device_swap": ALL_CLEAN,
            "device_reachability": ALL_COMPROMISED_BOTH,
            # She is where she says she is — this is coercion, not theft.
            "location_verification": AT_HOME_COMPROMISED,
        },
    ),
    "silent_siege": Persona(
        key="silent_siege",
        title="Every door is shut",
        story="Calls diverted, SIM replaced, handset replaced, and the network cannot "
              "reach the device at all. We do not attempt contact — there is no route "
              "left that does not run through the attacker. Not being able to reach her "
              "is not a failure of the check. It is the finding.",
        default_msisdn=UNREACHABLE,
    ),
}


def get_persona(key: str | None) -> Persona | None:
    return PERSONAS.get(key) if key else None
