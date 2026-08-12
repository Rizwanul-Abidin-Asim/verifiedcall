"""The audit trail.

STANDING RULE: every CAMARA call and every agent decision goes through here. No
exceptions, no direct writes that bypass it. The trail is a scored part of the
submission and a regulatory requirement for the real product, not a debug convenience.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.camara.models import SignalResult, SignalSource
from app.db.models import (
    Decision,
    DecisionOutcome,
    SignalCall,
    SignalSourceKind,
    Transaction,
)

log = logging.getLogger("audit")


async def record_signal_call(
    session: AsyncSession,
    transaction_id: uuid.UUID,
    signal: SignalResult,
    request_payload: dict | None = None,
) -> SignalCall:
    """Persist one CAMARA call exactly as it happened, fallbacks included.

    A fallback is recorded as a fallback. We never write cached data as if it were live.
    """
    record = SignalCall(
        transaction_id=transaction_id,
        api_name=signal.api_name,
        request_payload=request_payload or {},
        response_payload=signal.raw,
        source=(
            SignalSourceKind.FALLBACK
            if signal.source is SignalSource.FALLBACK
            else SignalSourceKind.LIVE
        ),
        fallback_reason=signal.fallback_reason,
        latency_ms=round(signal.latency_ms, 2),
    )
    session.add(record)
    await session.flush()
    log.info("audit.signal api=%s source=%s latency_ms=%.0f txn=%s",
             signal.api_name, signal.source, signal.latency_ms, transaction_id)
    return record


async def record_decision(
    session: AsyncSession,
    transaction_id: uuid.UUID,
    outcome: DecisionOutcome,
    risk_score: int,
    reasoning_trace: list[dict],
    total_latency_ms: float,
    used_fallback: bool = False,
) -> Decision:
    """Persist the agent's conclusion and the reasoning that produced it."""
    if not 0 <= risk_score <= 100:
        raise ValueError(f"risk_score must be 0-100, got {risk_score}")

    record = Decision(
        transaction_id=transaction_id,
        outcome=outcome,
        risk_score=risk_score,
        reasoning_trace=reasoning_trace,
        total_latency_ms=round(total_latency_ms, 2),
        used_fallback=used_fallback,
    )
    session.add(record)
    await session.flush()
    log.info("audit.decision outcome=%s score=%d fallback=%s latency_ms=%.0f txn=%s",
             outcome, risk_score, used_fallback, total_latency_ms, transaction_id)
    return record


async def record_transaction(session: AsyncSession, **fields) -> Transaction:
    """Persist an incoming transaction before any signal is pulled."""
    txn = Transaction(**fields)
    session.add(txn)
    await session.flush()
    log.info("audit.transaction id=%s amount=%s new_beneficiary=%s",
             txn.id, txn.amount, txn.is_new_beneficiary)
    return txn
