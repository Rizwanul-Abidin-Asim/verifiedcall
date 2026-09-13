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
    AnalystAction,
    _now,
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
    channel_assessment: dict | None = None,
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
        channel_assessment=channel_assessment,
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


async def record_analyst_review(
    session: AsyncSession,
    decision: Decision,
    action: AnalystAction,
    reason: str,
) -> Decision:
    """Record what a human did about a decision the agent had already made.

    Writes alongside `outcome`, never over it. The agent's verdict is evidence of what
    the system concluded, and a release is only meaningful next to the hold it reversed
    — collapsing the two into one field would leave a fraud team unable to audit its own
    overrides, which is the one dataset that tells them whether the agent is calibrated.

    A decision may be reviewed once. A second review is refused rather than silently
    replacing the first, because money has already moved on the strength of it.
    """
    if decision.analyst_action is not None:
        raise ValueError(
            f"Decision {decision.id} was already {decision.analyst_action.value} by an "
            f"analyst at {decision.analyst_reviewed_at:%Y-%m-%d %H:%M}"
        )

    reason = reason.strip()
    if not reason:
        raise ValueError("An analyst override must say why.")

    decision.analyst_action = action
    decision.analyst_reason = reason
    decision.analyst_reviewed_at = _now()
    await session.flush()

    # Logged at warning: an override is rare and is the thing worth finding in a log.
    log.warning("audit.analyst_override decision=%s agent_said=%s analyst_did=%s why=%s",
                decision.id, decision.outcome.value, action.value, reason)
    return decision
