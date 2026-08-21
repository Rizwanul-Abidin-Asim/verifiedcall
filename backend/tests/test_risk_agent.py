"""Agent behaviour, driven by a stub model so these run with no API key and no network.

The claims under test are the ones the submission rests on:
  - the agent is SELECTIVE about which signals it pulls (not a checklist)
  - every signal it pulls reaches the audit trail
  - it always returns a decision, even when the model is unreachable
  - a disagreement between model and scorer resolves to the more cautious outcome
"""

from decimal import Decimal

import pytest
import respx
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agent.risk_agent import evaluate, more_cautious
from app.agent.schemas import AgentMode, TransactionContext
from app.camara import base
from app.config import settings
from app.db.models import Base, DecisionOutcome, SignalCall, Transaction

BASE_URL = "https://nac.test"
CF = "/passthrough/camara/v1/call-forwarding-signal/call-forwarding-signal/v0.3"
SS = "/passthrough/camara/v1/sim-swap/sim-swap/v0"
ROAM = "/device-status/device-roaming-status/v1/retrieve"
LOC = "/location-verification/v1/verify"


@pytest.fixture(autouse=True)
async def _isolate(monkeypatch):
    monkeypatch.setattr(settings, "nokia_nac_base_url", BASE_URL)
    monkeypatch.setattr(settings, "nokia_nac_api_key", "test-key")
    monkeypatch.setattr(settings, "demo_mode", False)
    await base.close_client()
    yield
    await base.close_client()


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def txn(session):
    row = Transaction(
        amount=Decimal("42000.00"), currency="AED", merchant_name="Direct transfer",
        beneficiary_id="BEN-NEW-7731", is_new_beneficiary=True,
        customer_msisdn="+971500000000", signal_msisdn="+99999991004",
        customer_locale="ur")
    session.add(row)
    await session.flush()
    return row


def context(amount="42000.00", new_payee=True, msisdn="+99999991004"):
    return TransactionContext(
        amount=Decimal(amount), merchant_name="Direct transfer",
        is_new_beneficiary=new_payee, signal_msisdn=msisdn, local_hour=23)


def mock_sandbox(*, all_bad=True, location="TRUE"):
    """Wire the routes the way the sandbox actually responds."""
    respx.post(f"{BASE_URL}{CF}/unconditional-call-forwardings").respond(
        json={"active": all_bad})
    respx.post(f"{BASE_URL}{CF}/call-forwardings").respond(
        json=["unconditional"] if all_bad else ["inactive"])
    respx.post(f"{BASE_URL}{SS}/check").respond(json={"swapped": all_bad})
    respx.post(f"{BASE_URL}{ROAM}").respond(
        json={"roaming": all_bad, "countryCode": 36, "countryName": ["HU"]}
        if all_bad else {"roaming": False})
    respx.post(f"{BASE_URL}{LOC}").respond(json={"verificationResult": location})


def scripted_model(tool_names: list[str], outcome: str = "intervene") -> FunctionModel:
    """A model that calls exactly the named tools, then returns a fixed opinion."""

    async def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:  # first turn — request the tools
            if tool_names:
                return ModelResponse(
                    parts=[ToolCallPart(name, {}) for name in tool_names])
        output_tool = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(output_tool, {
            "recommended_outcome": outcome,
            "summary": "Large payment to a first-time payee with the line diverted.",
            "why_these_signals": f"Pulled {len(tool_names)} checks that could change "
                                 f"the outcome; skipped the rest to save latency.",
        })])

    return FunctionModel(behave)


def exploding_model() -> FunctionModel:
    async def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise RuntimeError("groq unavailable: 429 rate limited")

    return FunctionModel(behave)


# --------------------------------------------------------- the agentic claim


@respx.mock
async def test_agent_pulls_only_the_signals_it_asked_for(session, txn):
    """The core claim. If the agent always pulled all four, it would be a rules engine."""
    mock_sandbox()
    decision = await evaluate(
        session, txn.id, context(),
        model=scripted_model(["check_call_forwarding_tool", "verify_device_location_tool"]))

    assert decision.signals_pulled == ["call_forwarding", "location_verification"]
    assert "sim_swap" not in decision.signals_pulled
    assert "device_status" not in decision.signals_pulled


@respx.mock
async def test_agent_may_pull_nothing_on_a_trivial_payment(session, txn):
    """Deciding no check is needed is a legitimate answer, and the fast path."""
    mock_sandbox(all_bad=False)
    decision = await evaluate(
        session, txn.id, context(amount="12.00", new_payee=False),
        model=scripted_model([], outcome="approve"))

    assert decision.signals_pulled == []
    assert decision.outcome is DecisionOutcome.APPROVE
    assert decision.reasoning_trace, "an approve still needs a rationale"


@respx.mock
async def test_every_pulled_signal_reaches_the_audit_trail(session, txn):
    mock_sandbox()
    decision = await evaluate(
        session, txn.id, context(),
        model=scripted_model(["check_call_forwarding_tool", "check_sim_swap_tool"]))
    await session.commit()

    rows = (await session.execute(
        select(SignalCall).where(SignalCall.transaction_id == txn.id))).scalars().all()
    assert {r.api_name for r in rows} == set(decision.signals_pulled)
    assert all(r.request_payload for r in rows), "the request must be recorded too"


# ------------------------------------------------------- outcomes and safety


@respx.mock
async def test_device_present_intervenes_device_absent_declines(session, txn):
    """The demo narrative, end to end through the agent."""
    all_four = ["check_call_forwarding_tool", "check_sim_swap_tool",
                "check_device_roaming_tool", "verify_device_location_tool"]

    mock_sandbox(location="TRUE")
    present = await evaluate(session, txn.id, context(), model=scripted_model(all_four))
    assert present.outcome is DecisionOutcome.INTERVENE

    respx.clear()
    mock_sandbox(location="FALSE")
    absent = await evaluate(session, txn.id, context(), model=scripted_model(all_four))
    assert absent.outcome is DecisionOutcome.DECLINE


@respx.mock
async def test_disagreement_resolves_to_the_more_cautious_outcome(session, txn):
    mock_sandbox(location="TRUE")
    decision = await evaluate(
        session, txn.id, context(),
        model=scripted_model(["check_call_forwarding_tool"], outcome="approve"))

    # Scorer says intervene, model says approve — intervene must win, and be explained.
    assert decision.outcome is DecisionOutcome.INTERVENE
    assert decision.disagreement is not None
    assert "more cautious" in decision.disagreement


def test_more_cautious_ordering():
    assert more_cautious(DecisionOutcome.APPROVE, DecisionOutcome.DECLINE) is \
        DecisionOutcome.DECLINE
    assert more_cautious(DecisionOutcome.INTERVENE, DecisionOutcome.APPROVE) is \
        DecisionOutcome.INTERVENE
    assert more_cautious(DecisionOutcome.DECLINE, DecisionOutcome.INTERVENE) is \
        DecisionOutcome.DECLINE


@respx.mock
async def test_model_failure_falls_back_to_deterministic_pass(session, txn):
    """A live demo must never surface an error. If the model dies we pull everything."""
    mock_sandbox(location="TRUE")
    decision = await evaluate(session, txn.id, context(), model=exploding_model())

    assert decision.agent_mode is AgentMode.DETERMINISTIC_FALLBACK
    assert sorted(decision.signals_pulled) == [
        "call_forwarding", "device_status", "location_verification", "sim_swap"]
    assert decision.outcome is DecisionOutcome.INTERVENE
    assert decision.summary, "a decision without an explanation is not usable"


@respx.mock
async def test_camara_outage_still_produces_a_decision(session, txn):
    """Model up, network down: signals degrade to flagged fallbacks, decision survives."""
    respx.post(f"{BASE_URL}{CF}/unconditional-call-forwardings").respond(
        500, json={"detail": "Internal Server Error"})
    respx.post(f"{BASE_URL}{LOC}").respond(500, json={"detail": "Internal Server Error"})

    decision = await evaluate(
        session, txn.id, context(),
        model=scripted_model(["check_call_forwarding_tool", "verify_device_location_tool"]))

    assert decision.used_fallback is True
    assert decision.outcome in tuple(DecisionOutcome)
    fallback_steps = [s for s in decision.reasoning_trace if s.source == "fallback"]
    assert fallback_steps, "a cached signal must be visible in the narrative"


@respx.mock
async def test_total_failure_still_returns_a_decision(session, txn):
    """Model down AND network down. Worst case; still no exception to the caller."""
    for path in (f"{CF}/unconditional-call-forwardings", f"{SS}/check", ROAM, LOC):
        respx.post(f"{BASE_URL}{path}").respond(500, json={"detail": "down"})

    decision = await evaluate(session, txn.id, context(), model=exploding_model())
    assert decision.agent_mode is AgentMode.DETERMINISTIC_FALLBACK
    assert decision.used_fallback is True
    assert 0 <= decision.risk_score <= 100


# --------------------------------------------------------------- the trace


@respx.mock
async def test_trace_is_numbered_and_ends_with_the_assessment(session, txn):
    mock_sandbox()
    decision = await evaluate(
        session, txn.id, context(),
        model=scripted_model(["check_call_forwarding_tool"]))

    trace = decision.reasoning_trace
    assert [s.step for s in trace] == list(range(1, len(trace) + 1))
    assert trace[-1].kind == "assessment"
    assert str(decision.risk_score) in trace[-1].observed
    assert trace[0].rationale, "the agent must explain its choice of signals first"


@respx.mock
async def test_model_cannot_talk_us_into_a_false_decline(session, txn):
    """The model may escalate to a hold, but not to a decline, while the customer is
    demonstrably present. Refusing a payment the genuine customer is making does not
    protect them — it leaves them with a failed transfer and does nothing about the
    coercion. Decline is reserved for 'this is probably not the customer'."""
    mock_sandbox(location="TRUE")
    decision = await evaluate(
        session, txn.id, context(),
        model=scripted_model(["verify_device_location_tool"], outcome="decline"))

    assert decision.outcome is DecisionOutcome.INTERVENE
    assert "false decline" in decision.disagreement


@respx.mock
async def test_model_decline_is_honoured_when_the_customer_is_absent(session, txn):
    """The guard rail must not become a blanket ban on declining."""
    mock_sandbox(location="FALSE")
    decision = await evaluate(
        session, txn.id, context(),
        model=scripted_model(["check_call_forwarding_tool", "check_sim_swap_tool",
                              "check_device_roaming_tool", "verify_device_location_tool"],
                             outcome="decline"))
    assert decision.outcome is DecisionOutcome.DECLINE


@respx.mock
async def test_policy_pulls_the_location_check_before_declining(session, txn):
    """Selectivity has a floor. If the agent skipped the one check that can justify a
    decline, and the score is in the decline band, the policy engine pulls it rather than
    deciding on thinner evidence."""
    mock_sandbox(location="FALSE")
    decision = await evaluate(
        session, txn.id, context(),
        model=scripted_model(["check_call_forwarding_tool", "check_sim_swap_tool",
                              "check_device_roaming_tool"]))

    assert "location_verification" in decision.signals_pulled, (
        "the agent did not ask for it, but a decline cannot be justified without it")
    assert decision.outcome is DecisionOutcome.DECLINE
    assert "policy engine" in decision.reasoning_trace[0].rationale


@respx.mock
async def test_low_risk_never_triggers_the_extra_check(session, txn):
    """The mandatory check must not creep into the fast path."""
    mock_sandbox(all_bad=False)
    decision = await evaluate(
        session, txn.id, context(amount="50.00", new_payee=False),
        model=scripted_model(["check_call_forwarding_tool"], outcome="approve"))

    assert decision.signals_pulled == ["call_forwarding"]
    assert decision.outcome is DecisionOutcome.APPROVE
