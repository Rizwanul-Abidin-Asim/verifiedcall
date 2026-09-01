"""Vapi's end-of-call report, and the voice status the checkout polls.

The webhook is deliberately forgiving about shape. Provider payloads change, and a
report we cannot parse must still leave the payment held rather than throw. What it will
not do is guess: an unparseable call becomes INCONCLUSIVE, which routes to a human.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Transaction, VoiceCall, VoiceChannel, VoiceStatus
from app.db.session import get_session
from app.voice.classify import Answer, Reply, assess
from app.voice.scripts import normalise_language, script_for, spoken_amount
from app.voice.vapi_client import answers_from_structured, response_gaps

log = logging.getLogger("voice.webhook")
router = APIRouter(tags=["voice"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _dig(payload: dict, *path: str, default: Any = None) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def parse_answers(payload: dict, language) -> list[Answer]:
    """Pull per-question answers out of an end-of-call report.

    The assistant's analysis plan produces a flat object keyed by question, so that is
    the happy path. The older list under structuredData.answers is still accepted, since
    a payload in flight during a deploy should not be dropped. Anything else yields
    nothing, and the caller treats that as inconclusive rather than as a clean call.
    """
    data = _dig(payload, "message", "analysis", "structuredData", default=None)
    if data is None:
        data = _dig(payload, "analysis", "structuredData", default=None)
    if isinstance(data, dict) and isinstance(data.get("answers"), list):
        data = data["answers"]

    messages = (_dig(payload, "message", "messages", default=None)
                or _dig(payload, "messages", default=None) or [])
    return answers_from_structured(data, language, response_gaps(messages))


@router.post("/voice/webhook")
async def voice_webhook(request: Request, session: SessionDep) -> dict:
    """End-of-call report. Always answers 200 so the provider does not retry forever."""
    from app.voice.service import resolve_call

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        log.warning("voice.webhook_unparseable_body")
        return {"received": True, "handled": False, "reason": "body was not json"}

    txn_id = (_dig(payload, "message", "call", "metadata", "transaction_id")
              or _dig(payload, "call", "metadata", "transaction_id")
              or _dig(payload, "metadata", "transaction_id"))
    if not txn_id:
        log.warning("voice.webhook_no_transaction_id")
        return {"received": True, "handled": False, "reason": "no transaction_id"}

    try:
        transaction_id = uuid.UUID(str(txn_id))
    except ValueError:
        log.warning("voice.webhook_bad_transaction_id %r", txn_id)
        return {"received": True, "handled": False, "reason": "transaction_id not a uuid"}

    txn = (await session.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )).scalar_one_or_none()
    if txn is None:
        log.warning("voice.webhook_unknown_transaction %s", transaction_id)
        return {"received": True, "handled": False, "reason": "unknown transaction"}

    language = normalise_language(txn.customer_locale)
    answers = parse_answers(payload, language)
    ended = str(_dig(payload, "message", "endedReason", default="")
                or _dig(payload, "endedReason", default="")).lower()
    answered = bool(answers) and "no-answer" not in ended and "voicemail" not in ended

    duration = int(_dig(payload, "message", "durationSeconds", default=0)
                   or _dig(payload, "durationSeconds", default=0) or 0)
    transcript = (_dig(payload, "message", "transcript")
                  or _dig(payload, "transcript"))

    assessment = assess(answers, answered=answered)
    await resolve_call(session, transaction_id, assessment, duration, transcript)
    await session.commit()

    log.info("voice.webhook_handled txn=%s outcome=%s answers=%d",
             transaction_id, assessment.outcome, len(answers))
    return {"received": True, "handled": True, "outcome": assessment.outcome.value}


@router.get("/voice/{transaction_id}")
async def voice_status(transaction_id: uuid.UUID, session: SessionDep) -> dict:
    """What the checkout polls while it says "we are calling you"."""
    from app.voice.service import resolution_for

    call = (await session.execute(
        select(VoiceCall).where(VoiceCall.transaction_id == transaction_id)
    )).scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=404, detail="No voice call for that transaction")

    return {
        "transaction_id": str(transaction_id),
        "status": call.status.value,
        "outcome": call.outcome.value if call.outcome else None,
        "resolution": resolution_for(call.outcome),
        "language": call.language,
        "is_mock": call.is_mock,
        "channel": call.channel.value,
        "duration_s": call.duration_s,
        "answers": call.answers,
        "transcript": call.transcript,
    }


__all__ = ["router", "parse_answers", "Reply"]


@router.get("/voice/{transaction_id}/web-session")
async def web_session(transaction_id: uuid.UUID, session: SessionDep) -> dict:
    """Everything the browser needs to run the call itself.

    The assistant is built here, not in the browser and not in Vapi's dashboard, so the
    interrogation script stays in version control next to the tests that exercise it.
    The page is handed a definition to play, not a script to compose.

    The key returned is the publishable one. It is designed to appear in page source;
    the private key never leaves this process.
    """
    from app.config import settings
    from app.voice.vapi_client import build_assistant

    call = (await session.execute(
        select(VoiceCall).where(VoiceCall.transaction_id == transaction_id)
    )).scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=404, detail="No voice call for that transaction")
    if call.status is VoiceStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="That call has already been answered")
    if call.channel is not VoiceChannel.WEB:
        raise HTTPException(status_code=409,
                            detail="That call is being placed over the phone network")
    if not settings.vapi_public_key:
        raise HTTPException(status_code=503, detail="VAPI_PUBLIC_KEY is not configured")

    txn = (await session.execute(
        select(Transaction).where(Transaction.id == transaction_id))).scalar_one()

    return {
        "transaction_id": str(transaction_id),
        "public_key": settings.vapi_public_key,
        "assistant": build_assistant(
            script_for(txn.customer_locale),
            amount=spoken_amount(txn.amount), currency=txn.currency,
            beneficiary=txn.merchant_name,
        ),
    }


@router.post("/voice/{transaction_id}/web-started")
async def web_started(transaction_id: uuid.UUID, body: dict, session: SessionDep) -> dict:
    """The browser reports the call it just started, and we take it from there.

    From this point a web call is indistinguishable from a phone call: the same polling,
    the same answer extraction, the same hesitation timing, the same resolution. Only
    how the audio reached the customer differed.
    """
    import asyncio

    from app.voice.service import run_live_intervention

    call_id = str(body.get("call_id") or "").strip()
    if not call_id:
        raise HTTPException(status_code=422, detail="call_id is required")

    call = (await session.execute(
        select(VoiceCall).where(VoiceCall.transaction_id == transaction_id)
    )).scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=404, detail="No voice call for that transaction")
    if call.status is VoiceStatus.COMPLETED:
        return {"accepted": False, "reason": "already resolved"}

    call.vapi_call_id = call_id
    call.status = VoiceStatus.IN_PROGRESS
    await session.commit()

    asyncio.create_task(run_live_intervention(transaction_id, call_id))
    log.info("voice.web_started txn=%s call=%s", transaction_id, call_id)
    return {"accepted": True, "transaction_id": str(transaction_id)}
