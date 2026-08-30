"""API behaviour, driven end to end with a scripted model and a mocked sandbox.

The four demo scenarios are asserted here, because those outcomes are what gets shown
on stage and they must not drift.
"""

import asyncio
import json

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.camara import base
from app.config import settings
from app.db.models import Base
from app.db.session import get_session
from app.main import app
from app.services.events import broker

BASE_URL = "https://nac.test"
CF = "/passthrough/camara/v1/call-forwarding-signal/call-forwarding-signal/v0.3"
SS = "/passthrough/camara/v1/sim-swap/sim-swap/v0"
ROAM = "/device-status/device-roaming-status/v1/retrieve"
LOC = "/location-verification/v1/verify"

CLEAN = "+99999991001"
ELSEWHERE = "+99999991000"
AT_HOME = "+99999991004"
PARTIAL = "+99999991003"


def sandbox(number_states: dict[str, dict]):
    """Route each sandbox number to the profile the real simulator returns for it."""
    def responder(field):
        def handler(request):
            body = json.loads(request.content)
            phone = body.get("phoneNumber") or body["device"]["phoneNumber"]
            return httpx.Response(200, json=number_states[phone][field])
        return handler

    respx.post(f"{BASE_URL}{CF}/unconditional-call-forwardings").mock(side_effect=responder("cf"))
    respx.post(f"{BASE_URL}{CF}/call-forwardings").mock(
        side_effect=lambda r: httpx.Response(200, json=["inactive"]))
    respx.post(f"{BASE_URL}{SS}/check").mock(side_effect=responder("ss"))
    respx.post(f"{BASE_URL}{ROAM}").mock(side_effect=responder("roam"))
    respx.post(f"{BASE_URL}{LOC}").mock(side_effect=responder("loc"))


BAD = {"cf": {"active": True}, "ss": {"swapped": True},
       "roam": {"roaming": True, "countryCode": 36, "countryName": ["HU"]}}
STATES = {
    CLEAN:     {"cf": {"active": False}, "ss": {"swapped": False},
                "roam": {"roaming": False}, "loc": {"verificationResult": "TRUE"}},
    ELSEWHERE: {**BAD, "loc": {"verificationResult": "FALSE"}},
    AT_HOME:   {**BAD, "loc": {"verificationResult": "TRUE"}},
    PARTIAL:   {**BAD, "loc": {"verificationResult": "PARTIAL", "matchRate": 74}},
}


RISKY_MARKERS = ("ACTIVE", "was swapped", "ROAMING", "NOT within", "partially within")


def all_four_model() -> FunctionModel:
    """Pulls every signal, then recommends based on what came back.

    An earlier version always said "intervene", which made the clean scenario fail: the
    policy guard rail correctly escalated an approve because the model disagreed. That
    was the test being wrong, not the code. A stub that ignores its own tool results is
    not a useful stand-in for an analyst.
    """
    TOOLS = ["check_call_forwarding_tool", "check_sim_swap_tool",
             "check_device_roaming_tool", "verify_device_location_tool"]

    async def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart(t, {}) for t in TOOLS])

        findings = " ".join(
            str(part.content)
            for message in messages
            for part in getattr(message, "parts", [])
            if isinstance(part, ToolReturnPart)
        )
        risky = any(marker in findings for marker in RISKY_MARKERS)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "recommended_outcome": "intervene" if risky else "approve",
            "summary": "Reviewed the network signals for this payment.",
            "why_these_signals": "Pulled the full set so the outcome depends on the data.",
        })])

    return FunctionModel(behave)


@pytest.fixture(autouse=True)
async def _env(monkeypatch):
    monkeypatch.setattr(settings, "nokia_nac_base_url", BASE_URL)
    monkeypatch.setattr(settings, "nokia_nac_api_key", "test-key")
    monkeypatch.setattr(settings, "demo_mode", False)
    await base.close_client()
    yield
    await base.close_client()


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = override

    # Inject the scripted model so no API key or network is needed.
    import app.agent.risk_agent as ra
    real_evaluate = ra.evaluate

    async def patched(session, txn_id, context, model=None, expected_city="AE-DXB"):
        return await real_evaluate(session, txn_id, context,
                                   model=all_four_model(), expected_city=expected_city)

    monkeypatch.setattr("app.api.routes.transactions.evaluate", patched)

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    app.dependency_overrides.clear()
    await engine.dispose()


def payload(amount, signal_msisdn, new_payee=True, hour=23):
    return {
        "amount": str(amount), "currency": "AED", "merchant_name": "Direct transfer",
        "beneficiary_id": "BEN-1", "is_new_beneficiary": new_payee,
        "customer_msisdn": "+971500000000", "signal_msisdn": signal_msisdn,
        "customer_locale": "en", "local_hour": hour,
    }


# ------------------------------------------------------- the four demo scenarios


@respx.mock
@pytest.mark.parametrize("label,amount,number,new_payee,hour,expected", [
    ("1 clean",            "240.00",   CLEAN,     False, 14, "approve"),
    ("2 device elsewhere", "18500.00", ELSEWHERE, True,  23, "decline"),
    ("3 device present",   "42000.00", AT_HOME,   True,  23, "intervene"),
    ("4 partial location", "6300.00",  PARTIAL,   True,  23, "intervene"),
])
async def test_demo_scenarios(client, label, amount, number, new_payee, hour, expected):
    sandbox(STATES)
    r = await client.post("/transactions/evaluate",
                          json=payload(amount, number, new_payee, hour))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == expected, f"{label}: got {body['outcome']} score {body['risk_score']}"
    assert body["reasoning_trace"], "every decision needs a visible rationale"
    assert body["decision_id"] and body["transaction_id"]


# ------------------------------------------------------------------ the contract


@respx.mock
async def test_demo_seam_is_reported(client):
    sandbox(STATES)
    r = await client.post("/transactions/evaluate", json=payload("100.00", CLEAN, False, 12))
    assert r.json()["demo_seam"] is True

    same = payload("100.00", CLEAN, False, 12)
    same["customer_msisdn"] = CLEAN
    r2 = await client.post("/transactions/evaluate", json=same)
    assert r2.json()["demo_seam"] is False


@respx.mock
async def test_signal_msisdn_defaults_to_the_customer(client):
    sandbox(STATES)
    body = payload("100.00", CLEAN, False, 12)
    body.pop("signal_msisdn")
    body["customer_msisdn"] = CLEAN
    r = await client.post("/transactions/evaluate", json=body)
    assert r.status_code == 200
    assert r.json()["demo_seam"] is False


@pytest.mark.parametrize("bad", [
    {"amount": "0"},
    {"amount": "-5"},
    {"customer_msisdn": "not-a-number"},
    {"customer_msisdn": "0501234567"},      # no country code
    {"merchant_name": ""},
    {"local_hour": 24},
])
async def test_bad_input_is_rejected_with_422(client, bad):
    body = payload("100.00", CLEAN, False, 12)
    body.update(bad)
    r = await client.post("/transactions/evaluate", json=body)
    assert r.status_code == 422


# ------------------------------------------------------------------- read side


@respx.mock
async def test_list_and_detail(client):
    sandbox(STATES)
    created = await client.post("/transactions/evaluate",
                                json=payload("42000.00", AT_HOME, True, 23))
    decision_id = created.json()["decision_id"]

    listing = await client.get("/decisions")
    assert listing.status_code == 200
    page = listing.json()
    assert page["total"] == 1
    row = page["items"][0]
    assert row["decision_id"] == decision_id
    assert row["signals_pulled"] == 4
    assert row["voice_outcome"] is None

    detail = await client.get(f"/decisions/{decision_id}")
    assert detail.status_code == 200
    d = detail.json()
    assert len(d["signal_calls"]) == 4
    assert {s["api_name"] for s in d["signal_calls"]} == {
        "call_forwarding", "sim_swap", "device_status", "location_verification"}
    assert all(s["source"] == "live" for s in d["signal_calls"])
    assert d["transaction"]["demo_seam"] is True
    assert d["reasoning_trace"][-1]["kind"] == "assessment"


async def test_unknown_decision_is_404(client):
    r = await client.get("/decisions/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


@respx.mock
async def test_pagination(client):
    sandbox(STATES)
    for _ in range(3):
        await client.post("/transactions/evaluate", json=payload("100.00", CLEAN, False, 12))
    page = (await client.get("/decisions?limit=2&offset=0")).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    page2 = (await client.get("/decisions?limit=2&offset=2")).json()
    assert len(page2["items"]) == 1


# ------------------------------------------------------------- fallback + stream


@respx.mock
async def test_camara_outage_still_returns_a_decision(client):
    for path in (f"{CF}/unconditional-call-forwardings", f"{SS}/check", ROAM, LOC):
        respx.post(f"{BASE_URL}{path}").mock(
            return_value=httpx.Response(500, json={"detail": "down"}))
    r = await client.post("/transactions/evaluate", json=payload("42000.00", AT_HOME, True, 23))
    assert r.status_code == 200
    body = r.json()
    assert body["used_fallback"] is True
    assert body["outcome"] in {"approve", "intervene", "decline"}

    detail = (await client.get(f"/decisions/{body['decision_id']}")).json()
    assert any(s["source"] == "fallback" for s in detail["signal_calls"])
    assert all(s["fallback_reason"] for s in detail["signal_calls"] if s["source"] == "fallback")


async def test_broker_drops_rather_than_blocking():
    """A dashboard that stops reading must never be able to stall a payment."""
    from app.services.events import QUEUE_DEPTH
    with broker.subscribe() as q:
        for i in range(QUEUE_DEPTH + 25):
            await asyncio.wait_for(broker.publish({"n": i}), timeout=1.0)
        assert q.qsize() == QUEUE_DEPTH


async def test_subscribers_are_released():
    before = broker.subscriber_count
    with broker.subscribe():
        assert broker.subscriber_count == before + 1
    assert broker.subscriber_count == before


class _Req:
    """Stands in for a Starlette Request in the stream tests."""

    def __init__(self, disconnected: bool = False):
        self._disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self._disconnected


async def test_stream_emits_connected_then_decisions():
    """Driven directly rather than over the ASGI test transport, which cannot hold a
    streaming response open while a second request runs. The endpoint itself is exercised
    against a real uvicorn server in scripts/smoke_test.py."""
    from app.api.routes.stream import decision_event_source

    gen = decision_event_source(_Req())
    first = await gen.__anext__()
    assert first["event"] == "connected"

    await broker.publish({"decision_id": "abc", "outcome": "intervene", "risk_score": 80})
    second = await gen.__anext__()
    assert second["event"] == "decision"
    assert json.loads(second["data"])["outcome"] == "intervene"
    await gen.aclose()


async def test_stream_stops_and_releases_on_disconnect():
    from app.api.routes.stream import decision_event_source

    before = broker.subscriber_count
    gen = decision_event_source(_Req(disconnected=True))
    assert (await gen.__anext__())["event"] == "connected"
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert broker.subscriber_count == before, "a closed stream must not leak a subscriber"


async def test_health_reports_switches(client):
    body = (await client.get("/health")).json()
    assert body["status"] == "ok"
    assert set(body) >= {"demo_mode", "voice_mock", "llm_provider"}
    assert "key" not in json.dumps(body).lower()


async def test_a_server_error_still_carries_cors_headers(client, monkeypatch):
    """Regression. The 500 was produced outside the CORS layer, so the browser reported a
    CORS failure and hid the real cause. Found by the checkout showing a CORS error when
    the database was down."""
    async def explode(*args, **kwargs):
        raise RuntimeError("database is gone")

    monkeypatch.setattr("app.api.routes.transactions.record_transaction", explode)
    r = await client.post("/transactions/evaluate",
                          json=payload("100.00", CLEAN, False, 12),
                          headers={"Origin": "http://127.0.0.1:3000"})

    assert r.status_code == 500
    assert r.json()["error"] == "internal_error"
    assert "database is gone" not in r.text, "internal detail must not reach the browser"
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000", (
        "without this header the browser shows a CORS error instead of the real one")


@respx.mock
async def test_metrics_are_computed_from_the_log_not_claimed(client):
    sandbox(STATES)
    await client.post("/transactions/evaluate", json=payload("240.00", CLEAN, False, 14))
    await client.post("/transactions/evaluate", json=payload("18500.00", ELSEWHERE, True, 23))

    m = (await client.get("/metrics")).json()
    assert m["decisions"]["total"] == 2
    assert m["decisions"]["by_outcome"]["approve"] >= 1
    assert m["camara"]["apis_integrated"] == 4
    assert m["camara"]["categories_spanned"] == 2
    assert m["voice"]["languages_supported"] == 4
    assert set(m["voice"]["languages"]) == {"ar", "en", "hi", "ur"}
    assert m["added_latency_ms"]["approve_path_median"] is not None
    assert m["camara"]["served_from_cache_pct"] == 0.0
    assert "key" not in json.dumps(m).lower()


@respx.mock
async def test_metrics_report_cache_use_honestly(client):
    for path in (f"{CF}/unconditional-call-forwardings", f"{SS}/check", ROAM, LOC):
        respx.post(f"{BASE_URL}{path}").respond(500, json={"detail": "down"})
    await client.post("/transactions/evaluate", json=payload("42000.00", AT_HOME, True, 23))

    m = (await client.get("/metrics")).json()
    assert m["camara"]["served_from_cache_pct"] == 100.0
    assert m["decisions"]["used_fallback"] == 1


@respx.mock
async def test_demo_mode_never_touches_the_network(client, monkeypatch):
    """The guaranteed-working path for a live pitch: cached data, no sandbox dependency,
    and still labelled as cached so nothing is misrepresented."""
    monkeypatch.setattr(settings, "demo_mode", True)
    route = respx.post(f"{BASE_URL}{SS}/check").respond(json={"swapped": False})

    r = await client.post("/transactions/evaluate", json=payload("42000.00", AT_HOME, True, 23))
    assert r.status_code == 200
    body = r.json()
    assert body["used_fallback"] is True
    assert route.call_count == 0, "DEMO_MODE must not reach the network at all"

    detail = (await client.get(f"/decisions/{body['decision_id']}")).json()
    assert all(s["source"] == "fallback" for s in detail["signal_calls"])
    assert all("DEMO_MODE" in (s["fallback_reason"] or "") for s in detail["signal_calls"])
