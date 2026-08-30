"""Orchestrating an intervention: place the call, resolve it, tell everyone.

The payment is already held by the gateway before any of this runs. Nothing here can
release money on its own; it records what the call found and the resolution follows from
that. A call that fails, times out, or cannot be understood leaves the payment held,
because the safe default when we do not know is not to let the money go.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Transaction, VoiceCall, VoiceOutcome, VoiceStatus
from app.db.session import get_sessionmaker
from app.services.events import broker
from app.voice.classify import RELEASES_PAYMENT, Assessment, assess
from app.voice.scripts import normalise_language
from app.voice.vapi_client import (
    answers_from_structured,
    duration_of,
    place_call,
    poll_call,
    response_gaps,
    simulate_call,
    transcript_of,
    wait_for_mock_call,
)

log = logging.getLogger("voice.service")


def resolution_for(outcome: VoiceOutcome | None) -> str:
    """What happens to the money. Only one outcome releases it."""
    if outcome in RELEASES_PAYMENT:
        return "released"
    if outcome is VoiceOutcome.SCAM_DETECTED:
        return "blocked"
    return "held_for_analyst"


async def _publish(txn: Transaction, call: VoiceCall, rationale: str | None = None) -> None:
    await broker.publish({
        "kind": "voice",
        "transaction_id": str(txn.id),
        "voice_call_id": str(call.id),
        "status": call.status.value,
        "outcome": call.outcome.value if call.outcome else None,
        "resolution": resolution_for(call.outcome),
        "language": call.language,
        "is_mock": call.is_mock,
        "duration_s": call.duration_s,
        "rationale": rationale,
    })


async def start_intervention(session: AsyncSession, txn: Transaction) -> VoiceCall:
    """Create the call record and dial. Returns with the call ringing, not finished."""
    existing = (await session.execute(
        select(VoiceCall).where(VoiceCall.transaction_id == txn.id)
    )).scalar_one_or_none()
    if existing is not None:
        log.info("voice.already_placed txn=%s", txn.id)
        return existing

    call = VoiceCall(transaction_id=txn.id, status=VoiceStatus.PENDING)
    session.add(call)
    await session.flush()

    try:
        started = await place_call(
            msisdn=txn.customer_msisdn, locale=txn.customer_locale,
            amount=f"{txn.amount:,.2f}", currency=txn.currency,
            beneficiary=txn.merchant_name, transaction_id=txn.id,
        )
    except Exception as exc:  # noqa: BLE001 - a failed dial must not lose the record
        log.error("voice.place_failed txn=%s %r", txn.id, exc)
        call.status = VoiceStatus.FAILED
        call.transcript = f"Could not place the call: {exc}"
        await session.flush()
        await _publish(txn, call, "The call could not be placed, so the payment stays held.")
        return call

    call.vapi_call_id = started.provider_call_id
    call.is_mock = started.is_mock
    call.language = started.language.value
    call.status = VoiceStatus.RINGING
    await session.flush()
    await _publish(txn, call, "Calling the customer now.")
    return call


async def resolve_call(session: AsyncSession, transaction_id: uuid.UUID,
                       assessment: Assessment, duration_s: int,
                       transcript: str | None = None) -> VoiceCall | None:
    """Record what the call found."""
    call = (await session.execute(
        select(VoiceCall).where(VoiceCall.transaction_id == transaction_id)
    )).scalar_one_or_none()
    if call is None:
        log.warning("voice.resolve_unknown txn=%s", transaction_id)
        return None

    # Polling and the webhook can both report the same call. Whichever lands first is
    # the record; the second is dropped rather than allowed to overwrite an outcome a
    # human may already have acted on.
    if call.status is VoiceStatus.COMPLETED:
        log.info("voice.already_resolved txn=%s outcome=%s", transaction_id, call.outcome)
        return call

    call.status = VoiceStatus.COMPLETED
    call.outcome = assessment.outcome
    call.answers = assessment.as_json()
    call.duration_s = duration_s
    call.transcript = transcript or assessment.rationale
    await session.flush()

    txn = (await session.execute(
        select(Transaction).where(Transaction.id == transaction_id))).scalar_one()
    log.info("voice.resolved txn=%s outcome=%s resolution=%s",
             transaction_id, assessment.outcome, resolution_for(assessment.outcome))
    await _publish(txn, call, assessment.rationale)
    return call


async def _mark_failed(transaction_id: uuid.UUID, reason: str) -> None:
    """Leave a visible failure rather than a spinner that never stops.

    The payment stays held either way, which is the safe state, but an operator has to
    be able to see that the call never completed.
    """
    try:
        async with get_sessionmaker()() as session:
            call = (await session.execute(
                select(VoiceCall).where(VoiceCall.transaction_id == transaction_id)
            )).scalar_one_or_none()
            if call is not None and call.status is not VoiceStatus.COMPLETED:
                call.status = VoiceStatus.FAILED
                call.transcript = reason
                await session.commit()
                log.info("voice.marked_failed txn=%s", transaction_id)
    except Exception as inner:  # noqa: BLE001
        log.error("voice.could_not_mark_failed txn=%s %r", transaction_id, inner)


async def run_live_intervention(transaction_id: uuid.UUID, call_id: str) -> None:
    """Background task for a real call: wait for it to end, then read what it found.

    We poll rather than wait for Vapi's webhook. A webhook needs this service to be
    publicly reachable, which on a laptop means running a tunnel; polling needs nothing
    and behaves identically. The webhook route still works for a deployed instance, and
    resolve_call ignores whichever report arrives second.
    """
    try:
        body = await poll_call(call_id)
        if body is None:
            await _mark_failed(
                transaction_id,
                "The call did not finish within the time we wait for it, so the payment "
                "stays held for a human analyst.")
            return

        async with get_sessionmaker()() as session:
            txn = (await session.execute(
                select(Transaction).where(Transaction.id == transaction_id)
            )).scalar_one_or_none()
            if txn is None:
                log.warning("voice.live_unknown_txn %s", transaction_id)
                return

            language = normalise_language(txn.customer_locale)
            structured = (body.get("analysis") or {}).get("structuredData")
            answers = answers_from_structured(
                structured, language, response_gaps(body.get("messages") or []))

            ended = str(body.get("endedReason") or "").lower()
            answered = (bool(answers)
                        and "no-answer" not in ended
                        and "voicemail" not in ended
                        and "customer-did-not-answer" not in ended)

            assessment = assess(answers, answered=answered)
            await resolve_call(session, transaction_id, assessment,
                               duration_of(body), transcript_of(body))
            await session.commit()
            log.info("voice.live_resolved txn=%s outcome=%s answers=%d reason=%s",
                     transaction_id, assessment.outcome, len(answers), ended)
    except Exception as exc:  # noqa: BLE001 - a failed call must not take the API down
        log.error("voice.live_failed txn=%s %r", transaction_id, exc)
        await _mark_failed(transaction_id, f"The call did not complete: {exc}")


async def run_mock_intervention(transaction_id: uuid.UUID) -> None:
    """Background task for a simulated call. Opens its own session on purpose.

    The request that triggered this has already returned and closed its session, so
    reusing it would be a use-after-free. Anything that goes wrong here is logged and
    swallowed: a failed simulation must never take the API down mid-demo.
    """
    try:
        await wait_for_mock_call()
        async with get_sessionmaker()() as session:
            txn = (await session.execute(
                select(Transaction).where(Transaction.id == transaction_id)
            )).scalar_one_or_none()
            if txn is None:
                log.warning("voice.mock_unknown_txn %s", transaction_id)
                return
            assessment, duration = simulate_call(
                txn.customer_msisdn, normalise_language(txn.customer_locale))
            await resolve_call(session, transaction_id, assessment, duration)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        # The payment stays held, which is the safe state, but an operator needs to see
        # that the call never completed rather than watching a spinner forever.
        log.error("voice.mock_failed txn=%s %r", transaction_id, exc)
        await _mark_failed(transaction_id, f"The call did not complete: {exc}")
