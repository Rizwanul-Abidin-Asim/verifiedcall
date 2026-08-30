"""POST /transactions/evaluate — the gateway webhook.

The payment is held by the caller while this runs, so the contract is: always answer,
answer quickly, and never surface an exception. app.agent.risk_agent.evaluate already
guarantees a decision even when the model or the network is down; this layer adds the
persistence and the live feed around it.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.risk_agent import evaluate
from app.agent.schemas import TransactionContext
from app.api.schemas import EvaluateRequest, EvaluateResponse
from app.config import settings
from app.db.models import DecisionOutcome
from app.db.session import get_session
from app.services.audit import record_decision, record_transaction
from app.services.events import broker
from app.voice.service import run_live_intervention, run_mock_intervention, start_intervention

SessionDep = Annotated[AsyncSession, Depends(get_session)]

log = logging.getLogger("api.transactions")
router = APIRouter(tags=["transactions"])

GULF_UTC_OFFSET = timedelta(hours=4)


def local_hour_now() -> int:
    """Gulf Standard Time. Used when the gateway does not tell us the customer's hour."""
    return (datetime.now(UTC) + GULF_UTC_OFFSET).hour


@router.post("/transactions/evaluate", response_model=EvaluateResponse)
async def evaluate_transaction(
    payload: EvaluateRequest,
    session: SessionDep,
) -> EvaluateResponse:
    signal_msisdn = payload.signal_msisdn or payload.customer_msisdn

    txn = await record_transaction(
        session,
        amount=payload.amount,
        currency=payload.currency,
        merchant_name=payload.merchant_name,
        beneficiary_id=payload.beneficiary_id,
        is_new_beneficiary=payload.is_new_beneficiary,
        customer_msisdn=payload.customer_msisdn,
        signal_msisdn=signal_msisdn,
        customer_locale=payload.customer_locale,
    )

    context = TransactionContext(
        amount=payload.amount,
        currency=payload.currency,
        merchant_name=payload.merchant_name,
        is_new_beneficiary=payload.is_new_beneficiary,
        customer_locale=payload.customer_locale,
        local_hour=payload.local_hour if payload.local_hour is not None else local_hour_now(),
        signal_msisdn=signal_msisdn,
    )

    decision = await evaluate(session, txn.id, context, expected_city=payload.expected_city)

    record = await record_decision(
        session,
        txn.id,
        decision.outcome,
        decision.risk_score,
        [step.model_dump(mode="json") for step in decision.reasoning_trace],
        decision.total_latency_ms,
        used_fallback=decision.used_fallback,
    )
    await session.commit()

    response = EvaluateResponse(
        decision_id=record.id,
        transaction_id=txn.id,
        outcome=decision.outcome,
        risk_score=decision.risk_score,
        summary=decision.summary,
        reasoning_trace=decision.reasoning_trace,
        signals_pulled=decision.signals_pulled,
        latency_ms=decision.total_latency_ms,
        used_fallback=decision.used_fallback,
        agent_mode=decision.agent_mode,
        disagreement=decision.disagreement,
        demo_seam=payload.customer_msisdn != signal_msisdn,
    )

    # After the commit and outside the decision path: a dead dashboard must not be able
    # to affect a payment.
    await broker.publish({
        "decision_id": str(record.id),
        "transaction_id": str(txn.id),
        "outcome": decision.outcome.value,
        "risk_score": decision.risk_score,
        "amount": str(payload.amount),
        "currency": payload.currency,
        "merchant_name": payload.merchant_name,
        "is_new_beneficiary": payload.is_new_beneficiary,
        "signals_pulled": decision.signals_pulled,
        "used_fallback": decision.used_fallback,
        "agent_mode": decision.agent_mode.value,
        "latency_ms": round(decision.total_latency_ms, 1),
        "summary": decision.summary,
        "decided_at": record.decided_at.isoformat(),
    })

    # A held payment gets a phone call. Placing it is deliberately after the response
    # object is built and the decision is committed: the customer's payment is already
    # held, so nothing about the call can change the decision we just recorded.
    if decision.outcome is DecisionOutcome.INTERVENE:
        try:
            call = await start_intervention(session, txn)
            await session.commit()
            # Fire and forget either way. The checkout polls /voice/{id} or watches
            # the stream; neither path can change the decision already recorded.
            if call.is_mock and settings.voice_mock:
                asyncio.create_task(run_mock_intervention(txn.id))
            elif call.vapi_call_id:
                asyncio.create_task(run_live_intervention(txn.id, call.vapi_call_id))
        except Exception as exc:  # noqa: BLE001 - the decision stands even if dialling fails
            log.error("api.intervention_failed txn=%s %r", txn.id, exc)

    log.info("api.decided txn=%s outcome=%s score=%d latency_ms=%.0f signals=%d",
             txn.id, decision.outcome, decision.risk_score,
             decision.total_latency_ms, len(decision.signals_pulled))
    return response
