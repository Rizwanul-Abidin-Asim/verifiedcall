"""The audit trail must record what actually happened — including fallbacks, honestly."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.camara.models import SignalSource, SimSwapSignal
from app.db.models import (
    Base,
    DecisionOutcome,
    SignalCall,
    SignalSourceKind,
    Transaction,
)
from app.services.audit import record_decision, record_signal_call, record_transaction


@pytest.fixture
async def engine():
    # StaticPool keeps one connection, so a second session sees the same :memory: db.
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s


@pytest.fixture
async def txn(session):
    return await record_transaction(
        session,
        amount=Decimal("42000.00"), currency="AED",
        merchant_name="Direct transfer", beneficiary_id="BEN-NEW-7731",
        is_new_beneficiary=True,
        customer_msisdn="+971500000000", signal_msisdn="+99999991000",
        customer_locale="ur",
    )


async def test_live_signal_recorded_as_live(session, txn):
    signal = SimSwapSignal(swapped=True, latency_ms=294.0, raw={"swapped": True})
    record = await record_signal_call(
        session, txn.id, signal, request_payload={"phoneNumber": "+99999991000"})

    assert record.source is SignalSourceKind.LIVE
    assert record.response_payload == {"swapped": True}
    assert record.request_payload == {"phoneNumber": "+99999991000"}
    assert record.fallback_reason is None


async def test_fallback_is_never_recorded_as_live(session, txn):
    """The whole point of the flag: cached data must not masquerade as a live signal."""
    signal = SimSwapSignal(
        swapped=True, latency_ms=1012.0, raw={"swapped": True},
        source=SignalSource.FALLBACK, fallback_reason="sim_swap: HTTP 500",
    )
    record = await record_signal_call(session, txn.id, signal)

    assert record.source is SignalSourceKind.FALLBACK
    assert record.fallback_reason == "sim_swap: HTTP 500"
    assert float(record.latency_ms) > 0


async def test_decision_recorded_with_trace(session, txn):
    trace = [
        {"step": 1, "signal": "call_forwarding", "observed": "active=true",
         "effect": "+35", "note": "calls being intercepted right now"},
        {"step": 2, "signal": "device_status", "observed": "roaming in HU",
         "effect": "+20", "note": "roaming plus first-time beneficiary"},
    ]
    decision = await record_decision(
        session, txn.id, DecisionOutcome.INTERVENE, 78, trace, 541.0, used_fallback=False)

    assert decision.outcome is DecisionOutcome.INTERVENE
    assert decision.risk_score == 78
    assert decision.reasoning_trace[0]["signal"] == "call_forwarding"


@pytest.mark.parametrize("bad_score", [-1, 101, 250])
async def test_impossible_risk_score_rejected(session, txn, bad_score):
    with pytest.raises(ValueError, match="risk_score"):
        await record_decision(
            session, txn.id, DecisionOutcome.APPROVE, bad_score, [], 100.0)


async def test_signals_link_back_to_transaction(session, txn):
    for api in ("sim_swap", "call_forwarding"):
        signal = SimSwapSignal(swapped=False, raw={})
        signal.api_name = api
        await record_signal_call(session, txn.id, signal)
    await session.commit()

    rows = (await session.execute(
        select(SignalCall).where(SignalCall.transaction_id == txn.id))).scalars().all()
    assert {r.api_name for r in rows} == {"sim_swap", "call_forwarding"}


async def test_demo_seam_is_detectable(session, txn):
    """We must be able to show on the dashboard that signals and the called number
    are different, rather than quietly implying they are the same device."""
    assert txn.is_demo_seam is True

    same = await record_transaction(
        session, amount=Decimal("10.00"), currency="AED", merchant_name="X",
        beneficiary_id="B", is_new_beneficiary=False,
        customer_msisdn="+99999991001", signal_msisdn="+99999991001")
    assert same.is_demo_seam is False


async def test_records_are_visible_to_a_later_reader(engine, session, txn):
    """Write signals + decision, then read the transaction back through a NEW session.

    Guards the pattern the API actually uses (a session per request). Re-querying in the
    *same* session returns the identity-mapped instance with its relationships already
    loaded — which looks like the writes vanished. They haven't; the reader is stale.
    """
    signal = SimSwapSignal(swapped=True, latency_ms=294.0, raw={"swapped": True})
    await record_signal_call(session, txn.id, signal)
    await record_decision(
        session, txn.id, DecisionOutcome.INTERVENE, 82, [{"step": 1}], 541.0)
    await session.commit()

    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as reader:
        fresh = (await reader.execute(
            select(Transaction).where(Transaction.id == txn.id))).scalar_one()
        assert len(fresh.signal_calls) == 1
        assert fresh.decision is not None
        assert fresh.decision.risk_score == 82


async def test_unknown_transaction_id_is_rejected(session):
    """An orphan signal must not be storable. Requires SQLite FK enforcement, which
    app/db/__init__.py turns on so tests fail the way Postgres would."""
    signal = SimSwapSignal(swapped=False, raw={})
    with pytest.raises(IntegrityError):
        await record_signal_call(session, uuid.uuid4(), signal)
