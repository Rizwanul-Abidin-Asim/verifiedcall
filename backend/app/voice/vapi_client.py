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
from app.voice.classify import Answer, Assessment, Reply, assess, interpret
from app.voice.scripts import SPEECH_LOCALE, Language, Script, script_for

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
    return {
        "firstMessage": script.rendered_opening(amount, currency, beneficiary),
        "model": {
            "provider": "groq",
            "model": settings.groq_model,
            "messages": [{
                "role": "system",
                "content": (
                    f"You are an automated bank security check speaking "
                    f"{script.language.value}. Ask exactly these three questions, in "
                    f"order, and nothing else:\n{questions}\n\n"
                    "Accept a spoken yes or no, or a keypad press of 1 for yes and 2 for "
                    "no. Do not argue, do not reassure, do not explain the fraud. If the "
                    "customer answers anything other than yes or no, ask the same "
                    "question once more and then move on. When all three are answered, "
                    "end the call."
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


async def wait_for_mock_call() -> None:
    """A beat, so the dashboard visibly shows the call in progress before it resolves."""
    await asyncio.sleep(settings.voice_mock_seconds)


__all__ = ["Answer", "VoiceCallStarted", "place_call", "simulate_call", "wait_for_mock_call",
           "build_assistant"]
