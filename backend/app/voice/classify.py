"""Turn what the customer said into an outcome.

The hard problem this works around: speech recognition for Gulf Arabic and Urdu is the
weakest component in the system, and we cannot fix that. So the design avoids depending
on it.

- We never need a transcript, only one of three states per question. A closed choice is
  far more robust than open transcription.
- A keypad press, when we get one, overrides the words entirely. It is exact and
  language-independent.
- Time to answer is read as evidence in its own right. A coached victim hesitates before
  denying they were told to keep the call secret, because they were told to lie and
  lying takes a moment. Timing works identically in every language and does not depend
  on the transcript being right at all.

Nothing here decides on its own that somebody is guilty. Where the signals conflict the
answer is INCONCLUSIVE, which means a human analyst looks at it.
"""

import logging
from enum import StrEnum

from pydantic import BaseModel, Field

from app.db.models import VoiceOutcome
from app.voice.scripts import AFFIRMATIVE, DTMF_NO, DTMF_YES, NEGATIVE, Language

log = logging.getLogger("voice.classify")

HESITATION_MS = 3500
"""Above this, an answer counts as hesitant.

Chosen rather than measured: we have no recordings of coerced customers to calibrate
against. It is a starting threshold and the eval set described in the README is what
would replace it with a real number."""


class Reply(StrEnum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


class Answer(BaseModel):
    question_key: str
    reply: Reply
    response_ms: int = Field(ge=0, default=0)
    heard: str | None = None
    keypad: str | None = None
    hesitant: bool = False

    @property
    def from_keypad(self) -> bool:
        return self.keypad in (DTMF_YES, DTMF_NO)


def interpret(question_key: str, language: Language, heard: str | None,
              keypad: str | None, response_ms: int) -> Answer:
    """One question's answer. Keypad wins over speech when both arrive."""
    reply = Reply.UNCLEAR

    if keypad == DTMF_YES:
        reply = Reply.YES
    elif keypad == DTMF_NO:
        reply = Reply.NO
    elif heard:
        spoken = heard.strip().lower()
        if any(word in spoken for word in AFFIRMATIVE[language]):
            reply = Reply.YES
        elif any(word in spoken for word in NEGATIVE[language]):
            reply = Reply.NO

    return Answer(
        question_key=question_key, reply=reply, response_ms=response_ms,
        heard=heard, keypad=keypad, hesitant=response_ms >= HESITATION_MS,
    )


class Assessment(BaseModel):
    outcome: VoiceOutcome
    rationale: str
    answers: dict[str, Answer]

    def as_json(self) -> dict:
        return {k: v.model_dump(mode="json") for k, v in self.answers.items()}


def assess(answers: list[Answer], *, answered: bool = True) -> Assessment:
    """Decide what the call told us."""
    by_key = {a.question_key: a for a in answers}

    if not answered or not answers:
        return Assessment(
            outcome=VoiceOutcome.NO_ANSWER,
            rationale="The customer did not answer, so the payment stays held for a "
                      "human analyst rather than being released on silence.",
            answers=by_key)

    asked_to_pay = by_key.get("asked_to_pay")
    secret = by_key.get("told_to_keep_secret")
    others = by_key.get("others_present")

    # A yes to either coercion question is the answer on its own.
    admitted = [a for a in (asked_to_pay, secret) if a and a.reply is Reply.YES]
    if admitted:
        which = " and ".join(a.question_key.replace("_", " ") for a in admitted)
        return Assessment(
            outcome=VoiceOutcome.SCAM_DETECTED,
            rationale=f"The customer confirmed {which}. That is someone else directing "
                      f"this payment, so it stays blocked.",
            answers=by_key)

    # A denial that took a long time is not the same as a quick denial.
    if secret and secret.reply is Reply.NO and secret.hesitant and not secret.from_keypad:
        return Assessment(
            outcome=VoiceOutcome.INCONCLUSIVE,
            rationale=f"The customer denied being told to keep the payment secret, but "
                      f"took {secret.response_ms}ms to answer. Scammers coach victims to "
                      f"deny exactly this, so the hesitation is treated as a signal and "
                      f"the payment goes to a human analyst.",
            answers=by_key)

    if any(a.reply is Reply.UNCLEAR for a in answers):
        return Assessment(
            outcome=VoiceOutcome.INCONCLUSIVE,
            rationale="At least one answer could not be understood. Rather than guess, "
                      "the payment goes to a human analyst.",
            answers=by_key)

    if others and others.reply is Reply.YES:
        return Assessment(
            outcome=VoiceOutcome.INCONCLUSIVE,
            rationale="The customer says somebody else is present. They denied being "
                      "instructed, but a person in the room may be why. A human analyst "
                      "should call back when they are alone.",
            answers=by_key)

    return Assessment(
        outcome=VoiceOutcome.CONFIRMED_LEGITIMATE,
        rationale="The customer denied being contacted, denied being told to keep the "
                  "payment quiet, and answered without hesitation. Releasing the payment.",
        answers=by_key)


RELEASES_PAYMENT = {VoiceOutcome.CONFIRMED_LEGITIMATE}
