"""Read side for the fraud-operations console."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    DecisionDetail,
    DecisionListItem,
    DecisionPage,
    SignalCallOut,
    TransactionOut,
    VoiceCallOut,
)
from app.db.models import Decision, Transaction
from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
LimitQ = Annotated[int, Query(ge=1, le=200)]
OffsetQ = Annotated[int, Query(ge=0)]

log = logging.getLogger("api.decisions")
router = APIRouter(tags=["decisions"])


def _transaction_out(txn: Transaction) -> TransactionOut:
    return TransactionOut(
        id=txn.id, amount=txn.amount, currency=txn.currency,
        merchant_name=txn.merchant_name, beneficiary_id=txn.beneficiary_id,
        is_new_beneficiary=txn.is_new_beneficiary,
        customer_msisdn=txn.customer_msisdn, signal_msisdn=txn.signal_msisdn,
        customer_locale=txn.customer_locale, created_at=txn.created_at,
        demo_seam=txn.is_demo_seam,
    )


@router.get("/decisions", response_model=DecisionPage)
async def list_decisions(
    session: SessionDep,
    limit: LimitQ = 25,
    offset: OffsetQ = 0,
) -> DecisionPage:
    total = await session.scalar(select(func.count()).select_from(Decision)) or 0

    rows = (await session.execute(
        select(Decision)
        .options(selectinload(Decision.transaction).selectinload(Transaction.signal_calls),
                 selectinload(Decision.transaction).selectinload(Transaction.voice_call))
        .order_by(Decision.decided_at.desc())
        .limit(limit).offset(offset)
    )).scalars().all()

    items = [
        DecisionListItem(
            decision_id=d.id,
            transaction_id=d.transaction_id,
            outcome=d.outcome,
            risk_score=d.risk_score,
            used_fallback=d.used_fallback,
            total_latency_ms=float(d.total_latency_ms),
            decided_at=d.decided_at,
            amount=d.transaction.amount,
            currency=d.transaction.currency,
            merchant_name=d.transaction.merchant_name,
            is_new_beneficiary=d.transaction.is_new_beneficiary,
            signals_pulled=len(d.transaction.signal_calls),
            voice_outcome=d.transaction.voice_call.outcome if d.transaction.voice_call else None,
        )
        for d in rows
    ]
    return DecisionPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/decisions/{decision_id}", response_model=DecisionDetail)
async def get_decision(
    decision_id: uuid.UUID,
    session: SessionDep,
) -> DecisionDetail:
    decision = (await session.execute(
        select(Decision)
        .where(Decision.id == decision_id)
        .options(selectinload(Decision.transaction).selectinload(Transaction.signal_calls),
                 selectinload(Decision.transaction).selectinload(Transaction.voice_call))
    )).scalar_one_or_none()

    if decision is None:
        raise HTTPException(status_code=404, detail=f"No decision with id {decision_id}")

    txn = decision.transaction
    voice = txn.voice_call

    return DecisionDetail(
        decision_id=decision.id,
        outcome=decision.outcome,
        risk_score=decision.risk_score,
        reasoning_trace=decision.reasoning_trace,
        total_latency_ms=float(decision.total_latency_ms),
        used_fallback=decision.used_fallback,
        decided_at=decision.decided_at,
        transaction=_transaction_out(txn),
        signal_calls=[
            SignalCallOut(
                id=sc.id, api_name=sc.api_name, source=str(sc.source),
                fallback_reason=sc.fallback_reason, latency_ms=float(sc.latency_ms),
                request_payload=sc.request_payload, response_payload=sc.response_payload,
                called_at=sc.called_at,
            )
            for sc in sorted(txn.signal_calls, key=lambda s: s.called_at)
        ],
        voice_call=None if voice is None else VoiceCallOut(
            id=voice.id, vapi_call_id=voice.vapi_call_id, language=voice.language,
            status=voice.status, outcome=voice.outcome, transcript=voice.transcript,
            answers=voice.answers, duration_s=voice.duration_s, is_mock=voice.is_mock,
            created_at=voice.created_at,
        ),
    )
