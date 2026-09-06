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

    ...0  the customer admits they were told to make the payment   -> scam detected
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
from app.voice.scripts import SCRIPTS, SPEECH_LOCALE, Language, Script, script_for

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
    "0": [("others_present", Reply.YES, 1200),
          ("asked_to_pay", Reply.YES, 1800),
          ("told_to_keep_secret", Reply.YES, 2100)],
    "1": [("others_present", Reply.NO, 900),
          ("asked_to_pay", Reply.NO, 1100),
          ("told_to_keep_secret", Reply.NO, 1000)],
    "2": [("others_present", Reply.NO, 1000),
          ("asked_to_pay", Reply.NO, 1400),
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
    questions = "\n".join(f"{i}. {q.text}" for i, q in enumerate(script.questions, 1))
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
                            "releases a fraudulent one."
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
            "provider": "groq",
            "model": settings.groq_model,
            # The call skipped question 3 and said goodbye on its own. A deterministic
            # sample is the cheapest lever against a model improvising the sequence.
            "temperature": 0,
            "messages": [{
                "role": "system",
                "content": (
                    f"You are an automated bank security check. Speak only "
                    f"{script.language.value}.\n\n"
                    f"Ask these questions, in this exact order, one per turn:\n"
                    f"{questions}\n\n"
                    "Rules, in priority order.\n"
                    "1. Question 1 was already asked in your greeting. Your next turn "
                    "asks question 2. After the customer answers question 2, ask "
                    "question 3.\n"
                    "2. You may end the call ONLY after the customer has answered "
                    "question 3. Ending before question 3 is answered is a serious "
                    "error. Do not say goodbye, thank the customer, or summarise until "
                    "question 3 has an answer.\n"
                    "3. Accept a spoken yes or no, the typed word yes or no, or a "
                    "keypad press of 1 for yes and 2 for no.\n"
                    "4. If an answer is not a clear yes or no, repeat the same question "
                    "once, then move on.\n"
                    "5. Do not argue, reassure, explain fraud, or add anything beyond "
                    "the questions. One question per turn.\n"
                    "6. Once question 3 is answered, say exactly: \"Thank you. Please "
                    "stay on the line.\" Then end the call."
                ),
            }],
        },
        "voice": {"provider": "11labs", "voiceId": "burt"},
        "transcriber": {"provider": "deepgram", "model": "nova-2", "language": locale},
        "maxDurationSeconds": CALL_TIMEOUT_S,
        "endCallFunctionEnabled": True,
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
