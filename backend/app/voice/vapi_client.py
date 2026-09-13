"""Placing the call.

Two modes behind one function:

- VOICE_MOCK=true (the default) runs a simulator. No account, no credits, no phone
  rings, and the full path from decision to resolution still executes. This is how the
  flow is developed and tested.
- VOICE_MOCK=false places a real call through Vapi and waits for the end-of-call report
  to arrive at /voice/webhook.

The simulator picks its outcome from the last digit of the number being called, the same
convention Nokia's sandbox uses for network signals. Scripted, deterministic, and
obvious from the number itself, so a demo can show any outcome on purpose:

    ...0  the customer confirms every part of the scam story       -> scam detected
    ...1  the customer answers everything cleanly and quickly      -> legitimate
    ...2  the customer denies it, but hesitates on question three  -> inconclusive
    ...9  nobody picks up                                          -> no answer
    else  scam detected, since we only call when something is wrong
"""

import asyncio
import logging
import uuid

import httpx

from app.config import settings
from app.voice.classify import HESITATION_MS, Answer, Assessment, Reply, assess, interpret
from app.voice.scripts import (
    SCRIPTS,
    SPEECH_LOCALE,
    THANKS,
    Language,
    Script,
    script_for,
)

log = logging.getLogger("voice.client")

VAPI_BASE = "https://api.vapi.ai"
CALL_TIMEOUT_S = 120


class VoiceCallStarted:
    """What we know the moment a call is placed, before anyone answers."""

    def __init__(self, provider_call_id: str | None, is_mock: bool, language: Language):
        self.provider_call_id = provider_call_id
        self.is_mock = is_mock
        self.language = language


# ------------------------------------------------------------------ simulator

_MOCK_PLAN: dict[str, list[tuple[str, Reply, int]]] = {
    "0": [("account_at_risk", Reply.YES, 1200),
          ("details_given_by_other", Reply.YES, 1800),
          ("told_to_keep_secret", Reply.YES, 2100)],
    "1": [("account_at_risk", Reply.NO, 900),
          ("details_given_by_other", Reply.NO, 1100),
          ("told_to_keep_secret", Reply.NO, 1000)],
    "2": [("account_at_risk", Reply.NO, 1000),
          ("details_given_by_other", Reply.NO, 1400),
          ("told_to_keep_secret", Reply.NO, 5200)],   # the hesitation case
}

_SPOKEN = {
    (Language.EN, Reply.YES): "yes", (Language.EN, Reply.NO): "no",
    (Language.AR, Reply.YES): "نعم", (Language.AR, Reply.NO): "لا",
    (Language.HI, Reply.YES): "हाँ", (Language.HI, Reply.NO): "नहीं",
    (Language.UR, Reply.YES): "ہاں", (Language.UR, Reply.NO): "نہیں",
}


def simulate_call(msisdn: str, language: Language) -> tuple[Assessment, int]:
    """Run the script against a scripted customer. Returns (assessment, duration_s)."""
    last = msisdn[-1] if msisdn else ""
    if last == "9":
        return assess([], answered=False), 22

    plan = _MOCK_PLAN.get(last, _MOCK_PLAN["0"])
    answers = [
        interpret(key, language, heard=_SPOKEN[(language, reply)],
                  keypad=None, response_ms=ms)
        for key, reply, ms in plan
    ]
    duration = 18 + sum(ms for _, _, ms in plan) // 1000
    return assess(answers), duration


# ----------------------------------------------------------------- real calls

def build_assistant(script: Script, amount: str, currency: str, beneficiary: str) -> dict:
    """The Vapi assistant definition for one call.

    Kept here rather than configured in Vapi's dashboard so the script lives in version
    control next to the tests that exercise it.
    """
    locale = SPEECH_LOCALE[script.language]

    # The model is handed the exact lines it may say and asked which one comes next. It
    # is never asked to compose anything, because composing is where every failure came
    # from: told to "ask these questions in order", it paraphrased them, inserted "um"
    # and "as I was saying", mangled one into "press 1 if you're worth", and then put a
    # question it already had an answer to a second time.
    #
    # Ten behavioural rules had accumulated trying to police that, and each round of
    # them made the drift worse rather than better. They are gone. The constraint is
    # structural now: the whole reply has to be one of a handful of strings we wrote, so
    # there is nothing left to improvise. Question 1 is in firstMessage, so the model
    # only ever sends the later questions and the closing.
    scripted = [q.text for q in script.questions[1:]] + [THANKS[script.language]]
    lines = "\n".join(f"LINE {i}: {text}" for i, text in enumerate(scripted, 1))
    final = len(scripted)
    # Ask Vapi to extract the three answers for us. Shapes confirmed against their
    # OpenAPI spec: the result lands in call.analysis.structuredData.
    answer_schema = {
        "type": "object",
        "properties": {
            q.key: {
                "type": "string",
                "enum": ["yes", "no", "unclear"],
                "description": f"How the customer answered: {q.text}",
            }
            for q in script.questions
        },
        "required": [q.key for q in script.questions],
    }

    # The opening ends by asking the first question. On the first real call the
    # assistant introduced itself, then waited, and a model with nothing to reply to
    # stays quiet: the customer heard a statement, no question, and hung up after
    # thirty-three seconds of silence. Opening with a question makes the customer's
    # turn unambiguous and gives the model something to continue from.
    opening = script.rendered_opening(amount, currency, beneficiary)
    first_question = script.questions[0].text

    return {
        "firstMessage": f"{opening} {first_question}",
        "analysisPlan": {
            "structuredDataPlan": {
                "enabled": True,
                "schema": answer_schema,
                # {{schema}} and {{transcript}} are template variables the provider
                # fills in. Overriding these messages without them, which is what we did
                # at first, asks the extractor to read a transcript it was never given:
                # analysis.structuredData came back null on a real call where the
                # customer had answered every question, and the payment resolved as
                # "no answer". The wording below is ours; the two variables are not
                # optional.
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You extract how a customer answered a bank security check. "
                            "Return only JSON matching this schema:\n{{schema}}\n\n"
                            "Use exactly yes, no, or unclear for each question. Use "
                            "unclear when they did not answer, changed the subject, said "
                            "something that is not a yes or a no, or when the transcript "
                            "is too garbled to be sure. Never infer an answer they did "
                            "not give: a wrong yes blocks a real payment and a wrong no "
                            "releases a fraudulent one.\n\n"
                            "Read the whole sentence, not the first word. \"No one has "
                            "told me\" is a NO. \"No, they were found by me\" is a NO. "
                            "\"Yes, I was given the details\" is a YES.\n\n"
                            "Speech transcription writes \"no one\" as \"No. 1\" and "
                            "\"No one\" as \"No, 1\". A digit that appears inside a "
                            "sentence like that is part of the words, NOT a keypad "
                            "press — and reading that 1 as the keypad answer for yes "
                            "would invert the customer's answer. Only treat a digit as a "
                            "keypad press when it stands alone as the entire reply."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Transcript:\n\n{{transcript}}\n\n"
                            "The call ended because: {{endedReason}}"
                        ),
                    },
                ],
                # The default is 5 seconds. A call that ends while the model is still
                # thinking loses its answers entirely, and we would rather wait.
                "timeoutSeconds": 30,
            },
        },
        "model": {
            # See settings.voice_llm_provider for why this is not the risk agent's model.
            "provider": settings.voice_llm_provider,
            "model": settings.voice_llm_model,
            # How the assistant hangs up. This used to be `endCallFunctionEnabled: true`
            # at the top level, which Vapi has since removed from the API — so the flag
            # was being ignored and the assistant had no way to end anything. It
            # delivered its closing line and then sat on the call until the customer hung
            # up or the 120s cap expired, which is why completed calls were recording 58
            # and 70 seconds for three short questions.
            "tools": [{"type": "endCall"}],
            # The call skipped question 3 and said goodbye on its own. A deterministic
            # sample is the cheapest lever against a model improvising the sequence.
            "temperature": 0,
            "messages": [{
                "role": "system",
                "content": (
                    f"You are a bank's automated security check, speaking "
                    f"{script.language.value}. You are not having a conversation.\n\n"
                    f"Your reply is always exactly one of these lines, copied word for "
                    f"word:\n\n{lines}\n\n"
                    f"The customer has already been asked question 1 in the greeting. "
                    f"Send LINE 1 once they answer it. Send the next line once they "
                    f"answer the one before it. After LINE {final}, end the call.\n\n"
                    "Never send anything that is not one of those lines. Do not reword "
                    "them, shorten them, add to them, or say anything before or after "
                    "one. No greetings, no filler, no \"um\", no explaining, no "
                    "summarising, no asking whether they are still there.\n\n"
                    "Send a line a second time only if the customer's reply gave you no "
                    "idea which way they meant it, and then never a third time.\n\n"
                    "A reply counts as an answer whenever its meaning is clear: yes, "
                    "no, 1, 2, \"someone gave them to me\" (yes), \"I found it myself\" "
                    "(no), \"no one has told me\" (no). Never read the \"one\" in \"no "
                    "one\" as the digit 1."
                ),
            }],
        },
        # Every field here is set deliberately; the defaults were wrong for this call.
        #
        # model: Vapi defaults to eleven_turbo_v2, which is ENGLISH ONLY. We offer this
        # call in Arabic, Hindi and Urdu, so the default silently undermined the one
        # claim the voice layer exists to make. eleven_turbo_v2_5 is multilingual and
        # still low-latency.
        #
        # speed: the default read far too fast for this call. Range is 0.7-1.2 (Vapi's
        # schema). This is a bank ringing someone who is frightened, possibly in their
        # second language, with somebody else in the room — the delivery has to be
        # slower than a normal assistant, not faster.
        #
        # stability high, style at zero: we want the same flat, official delivery every
        # time. Expressiveness here would read as a person, and a person is exactly what
        # a scammer would send.
        "voice": {
            "provider": "11labs",
            "voiceId": "burt",
            "model": "eleven_turbo_v2_5",
            # 0.85 was too slow to listen to; 1.0 (the default) was too quick for
            # somebody frightened and possibly hearing this in a second language.
            "speed": 0.95,
            "stability": 0.7,
            "similarityBoost": 0.75,
            "style": 0,
        },
        "transcriber": {"provider": "deepgram", "model": "nova-2", "language": locale},
        # When the assistant may be cut off mid-sentence.
        #
        # Vapi's defaults are built for an assistant that chats, where "no", "wait" and
        # "actually" mean *stop talking*. This is a yes/no security questionnaire, and
        # in it "no" is an ANSWER. Left at the defaults, a customer answering "no"
        # silenced the question they were answering, and because numWords defaults to 0
        # the interruption ran off raw voice activity — so a breath, a cough, or the
        # other person in the room was enough to truncate a question. Observed live: the
        # third question was cut to "Has anyone asked you to keep this payment" and the
        # customer never heard what they were agreeing to.
        #
        # numWords=2 moves the decision from voice activity to actual transcribed words,
        # so the assistant finishes its sentence unless somebody genuinely talks over it.
        "stopSpeakingPlan": {
            "numWords": 2,
            "backoffSeconds": 1,
            # Empty on purpose, and the emptiness is the fix.
            #
            # Vapi treats these as backchannelling — noise a speaker makes while
            # listening, which should not count as a turn. Its default list contains
            # "yes", "yeah", "okay" and "right". In a questionnaire whose only valid
            # answers are yes and no, that means the answer is discarded: observed live,
            # the customer said "No", Vapi swallowed it as backchannel, the model saw
            # silence, asked "Hello?", and put the same question a third time.
            #
            # There is no such thing as a throwaway word on this call. Everything the
            # customer says is either the answer or evidence about the answer.
            "acknowledgementPhrases": [],
            # Only genuine "stop talking" phrases survive here. 'no', 'not', 'dont',
            # 'never' and 'but' were removed from Vapi's default list on purpose.
            "interruptionPhrases": [
                "stop", "shut up", "be quiet", "enough", "silence", "pause",
                "hold on", "wait a moment", "say that again", "repeat that",
            ],
        },
        # How long to wait before deciding the customer has finished speaking.
        #
        # Vapi waits 1.5s after a transcript that ends without punctuation, which is
        # sensible for open conversation and far too slow here: the answers are one word,
        # and a second and a half of dead air after "no" reads as the line having dropped.
        # Deepgram also often leaves a bare "no" unpunctuated, so that was the common
        # path, not the rare one.
        "startSpeakingPlan": {
            "waitSeconds": 0.4,
            "transcriptionEndpointingPlan": {
                "onPunctuationSeconds": 0.1,
                "onNoPunctuationSeconds": 0.9,
                # Kept at the default. Lowering it would cut "ninety thousand" in half,
                # and the amount is read back to the customer.
                "onNumberSeconds": 0.4,
            },
        },
        "maxDurationSeconds": CALL_TIMEOUT_S,
    }


async def place_call(
    *, msisdn: str, locale: str | None, amount: str, currency: str,
    beneficiary: str, transaction_id: uuid.UUID,
) -> VoiceCallStarted:
    """Ring the customer. In mock mode nothing dials and the call resolves immediately."""
    script = script_for(locale)

    if settings.voice_mock:
        log.info("voice.mock_call txn=%s to=%s lang=%s",
                 transaction_id, msisdn, script.language.value)
        return VoiceCallStarted(provider_call_id=None, is_mock=True,
                                language=script.language)

    if not settings.vapi_api_key or not settings.vapi_phone_number_id:
        raise RuntimeError(
            "VOICE_MOCK is false but VAPI_API_KEY or VAPI_PHONE_NUMBER_ID is missing")

    payload = {
        "phoneNumberId": settings.vapi_phone_number_id,
        "customer": {"number": msisdn},
        "assistant": build_assistant(script, amount, currency, beneficiary),
        "metadata": {"transaction_id": str(transaction_id)},
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{VAPI_BASE}/call",
            headers={"Authorization": f"Bearer {settings.vapi_api_key}"},
            json=payload,
        )
    if not response.is_success:
        raise RuntimeError(f"Vapi rejected the call: {response.status_code} "
                           f"{response.text[:200]}")

    call_id = response.json().get("id")
    log.info("voice.placed txn=%s call=%s lang=%s",
             transaction_id, call_id, script.language.value)
    return VoiceCallStarted(provider_call_id=call_id, is_mock=False,
                            language=script.language)


async def poll_call(call_id: str, *, timeout_s: int = 180) -> dict | None:
    """Wait for a real call to finish by polling, instead of waiting on a webhook.

    A webhook would need this machine to be publicly reachable, which during a demo
    means running a tunnel. Polling needs nothing, and Vapi exposes GET /call/{id} with
    a status enum that reaches "ended". The webhook route still works for anyone who
    does have a public URL; whichever arrives first resolves the call.
    """
    headers = {"Authorization": f"Bearer {settings.vapi_api_key}"}
    deadline = asyncio.get_running_loop().time() + timeout_s
    async with httpx.AsyncClient(timeout=20.0) as client:
        while asyncio.get_running_loop().time() < deadline:
            try:
                response = await client.get(f"{VAPI_BASE}/call/{call_id}", headers=headers)
            except httpx.HTTPError as exc:
                log.warning("voice.poll_error call=%s %r", call_id, exc)
                await asyncio.sleep(3)
                continue
            if response.is_success:
                body = response.json()
                status = body.get("status")
                if status in ("ended", "not-found"):
                    log.info("voice.poll_done call=%s status=%s reason=%s",
                             call_id, status, body.get("endedReason"))
                    return body
                log.info("voice.poll call=%s status=%s", call_id, status)
            else:
                log.warning("voice.poll_http call=%s %s", call_id, response.status_code)
            await asyncio.sleep(3)
    log.warning("voice.poll_timeout call=%s after %ds", call_id, timeout_s)
    return None


def response_gaps(messages: list) -> list[int]:
    """Milliseconds between the assistant finishing a turn and the customer starting.

    This is the hesitation signal, and it is the one part of the call that does not
    depend on the transcript being correct. Returned in order.

    If the message list cannot be aligned we return nothing rather than a guess, and
    hesitation simply does not fire. A wrong timing is worse than no timing.
    """
    def spoken_until(item: dict) -> float | None:
        """When a turn stopped, in seconds from the start of the call."""
        start = item.get("secondsFromStart")
        if start is None:
            return None
        # duration is milliseconds; time and endTime are epoch milliseconds. Either
        # gives the length of the turn, and we only ever need the length.
        length_ms = item.get("duration")
        if length_ms is None and item.get("endTime") is not None and item.get("time") is not None:
            length_ms = item["endTime"] - item["time"]
        return float(start) + (float(length_ms) / 1000 if length_ms is not None else 0.0)

    gaps: list[int] = []
    asked_at: float | None = None
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role in ("bot", "assistant"):
            asked_at = spoken_until(item)
        elif role == "user" and asked_at is not None:
            start = item.get("secondsFromStart")
            if start is not None:
                gaps.append(max(0, round((float(start) - asked_at) * 1000)))
            asked_at = None
    return gaps


def answers_from_structured(data, language: Language,
                            gaps: list[int] | None = None) -> list[Answer]:
    """Turn Vapi's extraction into our answer records.

    Two shapes are accepted. The flat {question_key: "yes"} is what our analysis plan
    asks for. The list of per-question objects is what an assistant tool call would
    publish, and is kept so an existing webhook payload still parses.

    Timing never comes from the model. It is measured from the transcript, because a
    model asked how long someone paused will happily invent a number.
    """
    if isinstance(data, list):
        answers: list[Answer] = []
        for item in data:
            if not isinstance(item, dict) or not item.get("question_key"):
                continue
            answers.append(interpret(
                question_key=str(item["question_key"]), language=language,
                heard=item.get("heard") or item.get("transcript"),
                keypad=str(item["keypad"]) if item.get("keypad") is not None else None,
                response_ms=int(item.get("response_ms") or 0),
            ))
        return answers

    if not isinstance(data, dict):
        return []

    questions = SCRIPTS[language].questions
    # The questions are the closing exchanges of the call, so the last N gaps are the
    # ones that belong to them; anything earlier is the customer replying to the
    # opening. If there are fewer gaps than questions we cannot say which is which,
    # so we record no timing rather than an alignment we are guessing at.
    usable = gaps and len(gaps) >= len(questions)
    aligned = gaps[-len(questions):] if usable else [0] * len(questions)

    answers = []
    for index, question in enumerate(questions):
        raw = data.get(question.key)
        if raw is None:
            continue
        try:
            reply = Reply(str(raw).strip().lower())
        except ValueError:
            reply = Reply.UNCLEAR
        ms = aligned[index]
        answers.append(Answer(question_key=question.key, reply=reply, response_ms=ms,
                              heard=str(raw), hesitant=ms >= HESITATION_MS))
    return answers


def transcript_of(body: dict) -> str | None:
    """A readable transcript, preferring the provider's own if it sent one."""
    existing = body.get("transcript")
    if isinstance(existing, str) and existing.strip():
        return existing
    lines = [
        f"{item.get('role')}: {item.get('message')}"
        for item in body.get("messages") or []
        if isinstance(item, dict) and item.get("role") != "system" and item.get("message")
    ]
    return "\n".join(lines) if lines else None


def duration_of(body: dict) -> int:
    """Call length in seconds, from the timestamps the provider returns."""
    started, ended = body.get("startedAt"), body.get("endedAt")
    if not started or not ended:
        return 0
    try:
        from datetime import datetime
        begin = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        finish = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
        return max(0, int((finish - begin).total_seconds()))
    except (ValueError, TypeError):
        return 0


async def wait_for_mock_call() -> None:
    """A beat, so the dashboard visibly shows the call in progress before it resolves."""
    await asyncio.sleep(settings.voice_mock_seconds)


__all__ = ["Answer", "VoiceCallStarted", "answers_from_structured", "build_assistant",
           "duration_of", "place_call", "poll_call", "response_gaps", "simulate_call",
           "transcript_of", "wait_for_mock_call"]
