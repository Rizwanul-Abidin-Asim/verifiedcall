"""The real-call path: polling, reading the result, and refusing to guess.

Mock mode is scripted, so it can only ever confirm the code agrees with itself. This
file covers what happens against an actual provider payload, where the parts most
likely to go wrong are the ones we cannot rehearse: a transcript that does not line up
with the questions, a call that never ends, and two reports arriving for one call.

The shapes used here come from Vapi's published OpenAPI spec, not from guesswork.
"""

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import (
    Base,
    Transaction,
    VoiceCall,
    VoiceChannel,
    VoiceOutcome,
    VoiceStatus,
)
from app.voice.classify import Reply, assess
from app.voice.scripts import SCRIPTS, Language
from app.voice.service import resolve_call
from app.voice.vapi_client import (
    VAPI_BASE,
    answers_from_structured,
    build_assistant,
    duration_of,
    poll_call,
    response_gaps,
    transcript_of,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
    await engine.dispose()


def turn(role: str, message: str, start: float, duration_ms: int | None = None) -> dict:
    item = {"role": role, "message": message, "secondsFromStart": start}
    if duration_ms is not None:
        item["duration"] = duration_ms
    return item


# A call where the customer denies everything but stalls badly on the last question.
HESITANT_CALL = [
    turn("bot", "This is your bank about a payment of 8,000 AED.", 0.0, 4000),
    turn("bot", "Is there anyone else with you right now?", 4.0, 2500),
    turn("user", "no", 7.5),
    turn("bot", "Has anyone asked you to make this payment?", 8.5, 2500),
    turn("user", "no", 12.2),
    turn("bot", "Were you told not to discuss this with your bank?", 13.0, 2500),
    turn("user", "no", 21.0),
]


# ------------------------------------------------------------------- timing

async def test_gap_is_measured_from_when_the_question_finished():
    """Hesitation is the gap after the bot stops talking, not after it starts."""
    gaps = response_gaps(HESITANT_CALL)
    assert len(gaps) == 3
    assert gaps[0] == 1000        # 7.5 - (4.0 + 2.5)
    assert gaps[1] == 1200        # 12.2 - (8.5 + 2.5)
    assert gaps[2] == 5500        # 21.0 - (13.0 + 2.5)


async def test_consecutive_bot_turns_do_not_inflate_the_gap():
    """The opening runs straight into question one; only the last turn counts."""
    gaps = response_gaps([
        turn("bot", "opening", 0.0, 4000),
        turn("bot", "question", 4.0, 2000),
        turn("user", "no", 6.5),
    ])
    assert gaps == [500]


async def test_a_message_list_without_timing_yields_no_timing():
    """No timestamps means no hesitation claim. Silence beats a made-up number."""
    gaps = response_gaps([
        {"role": "bot", "message": "question"},
        {"role": "user", "message": "no"},
    ])
    assert gaps == []


async def test_junk_in_the_message_list_is_survived():
    assert response_gaps([None, "nonsense", 42, {"role": "user"}]) == []
    assert response_gaps([]) == []
    assert response_gaps(None) == []


# ------------------------------------------------------- reading the answers

async def test_flat_structured_data_becomes_answers_with_timing():
    answers = answers_from_structured(
        {"others_present": "no", "asked_to_pay": "no", "told_to_keep_secret": "no"},
        Language.EN, response_gaps(HESITANT_CALL))

    assert [a.reply for a in answers] == [Reply.NO, Reply.NO, Reply.NO]
    assert [a.question_key for a in answers] == [
        "others_present", "asked_to_pay", "told_to_keep_secret"]
    # Only the last one crosses the hesitation threshold, and it is the one that matters.
    assert [a.hesitant for a in answers] == [False, False, True]


async def test_a_denial_delivered_slowly_is_not_treated_as_a_clean_call():
    """The headline behaviour: denying while stalling routes to a human, not to release."""
    answers = answers_from_structured(
        {"others_present": "no", "asked_to_pay": "no", "told_to_keep_secret": "no"},
        Language.EN, response_gaps(HESITANT_CALL))
    assessment = assess(answers)
    assert assessment.outcome is not VoiceOutcome.CONFIRMED_LEGITIMATE


async def test_misaligned_timing_is_dropped_rather_than_guessed():
    """Fewer gaps than questions means we cannot say which pause belonged to which."""
    answers = answers_from_structured(
        {"others_present": "no", "asked_to_pay": "no", "told_to_keep_secret": "no"},
        Language.EN, [5500])
    assert all(a.response_ms == 0 for a in answers)
    assert not any(a.hesitant for a in answers)


async def test_a_reply_to_the_opening_does_not_shift_the_questions():
    """The customer says hello first. The three questions are still the last three."""
    chatty = [turn("bot", "This is your bank.", 0.0, 3000),
              turn("user", "hello?", 4.0)] + HESITANT_CALL[1:]
    answers = answers_from_structured(
        {"others_present": "no", "asked_to_pay": "no", "told_to_keep_secret": "no"},
        Language.EN, response_gaps(chatty))
    assert [a.hesitant for a in answers] == [False, False, True]


async def test_an_admission_is_read_as_an_admission():
    answers = answers_from_structured(
        {"others_present": "yes", "asked_to_pay": "yes", "told_to_keep_secret": "yes"},
        Language.EN, response_gaps(HESITANT_CALL))
    assert assess(answers).outcome is VoiceOutcome.SCAM_DETECTED


async def test_the_older_list_shape_still_parses():
    """A payload in flight during a deploy should not be silently dropped."""
    answers = answers_from_structured(
        [{"question_key": "asked_to_pay", "heard": "yes", "response_ms": 900}],
        Language.EN)
    assert len(answers) == 1
    assert answers[0].reply is Reply.YES


async def test_unparseable_extraction_yields_nothing():
    for junk in (None, "unclear", 42, [], {}):
        assert answers_from_structured(junk, Language.EN, []) == []


async def test_a_value_outside_the_enum_is_unclear_not_a_guess():
    answers = answers_from_structured(
        {"others_present": "maybe?"}, Language.EN, [])
    assert answers[0].reply is Reply.UNCLEAR


async def test_missing_questions_are_absent_rather_than_invented():
    answers = answers_from_structured({"asked_to_pay": "no"}, Language.EN, [])
    assert [a.question_key for a in answers] == ["asked_to_pay"]


async def test_arabic_questions_keep_their_own_order():
    answers = answers_from_structured(
        {"others_present": "no", "asked_to_pay": "yes", "told_to_keep_secret": "no"},
        Language.AR, [])
    assert [a.question_key for a in answers] == [
        "others_present", "asked_to_pay", "told_to_keep_secret"]
    assert assess(answers).outcome is VoiceOutcome.SCAM_DETECTED


# ------------------------------------------------------- transcript and length

async def test_transcript_prefers_the_provider_and_omits_system_turns():
    assert transcript_of({"transcript": "provided"}) == "provided"
    built = transcript_of({"messages": [
        {"role": "system", "message": "hidden"},
        turn("bot", "question", 0.0),
        turn("user", "no", 1.0),
    ]})
    assert "hidden" not in built
    assert built == "bot: question\nuser: no"
    assert transcript_of({}) is None


async def test_duration_comes_from_the_timestamps_and_survives_bad_ones():
    assert duration_of({"startedAt": "2026-08-30T10:00:00.000Z",
                        "endedAt": "2026-08-30T10:00:41.000Z"}) == 41
    assert duration_of({"startedAt": "not a date", "endedAt": "also not"}) == 0
    assert duration_of({}) == 0


# ------------------------------------------------------------------- polling

@respx.mock
async def test_polling_waits_for_the_call_to_end(monkeypatch):
    monkeypatch.setattr(settings, "vapi_api_key", "test-key")
    call_id = "call-123"
    replies = [
        httpx.Response(200, json={"id": call_id, "status": "ringing"}),
        httpx.Response(200, json={"id": call_id, "status": "in-progress"}),
        httpx.Response(200, json={"id": call_id, "status": "ended",
                                  "endedReason": "customer-ended-call"}),
    ]
    route = respx.get(f"{VAPI_BASE}/call/{call_id}").mock(side_effect=replies)

    body = await poll_call(call_id, timeout_s=30)
    assert body is not None
    assert body["status"] == "ended"
    assert route.call_count == 3


@respx.mock
async def test_polling_gives_up_rather_than_hanging_forever(monkeypatch):
    """A call that never ends must leave the payment held, not the task running."""
    monkeypatch.setattr(settings, "vapi_api_key", "test-key")
    respx.get(f"{VAPI_BASE}/call/stuck").mock(
        return_value=httpx.Response(200, json={"status": "in-progress"}))
    assert await poll_call("stuck", timeout_s=1) is None


@respx.mock
async def test_polling_survives_a_transport_error(monkeypatch):
    monkeypatch.setattr(settings, "vapi_api_key", "test-key")
    respx.get(f"{VAPI_BASE}/call/flaky").mock(side_effect=[
        httpx.ConnectError("dropped"),
        httpx.Response(500, text="upstream"),
        httpx.Response(200, json={"status": "ended"}),
    ])
    body = await poll_call("flaky", timeout_s=30)
    assert body is not None and body["status"] == "ended"


# ------------------------------------------------------------- idempotency

async def test_a_second_report_cannot_overwrite_a_resolved_call(session):
    """Polling and the webhook can both describe one call. The first wins."""
    txn = Transaction(
        customer_msisdn="+99999991004", signal_msisdn="+99999991004",
        customer_locale="en", amount=Decimal("8000.00"), currency="AED",
        merchant_name="Test Payee", beneficiary_id=f"payee-{uuid.uuid4().hex[:8]}",
        is_new_beneficiary=True,
    )
    session.add(txn)
    await session.flush()
    session.add(VoiceCall(transaction_id=txn.id, status=VoiceStatus.RINGING))
    await session.flush()

    scam = assess(answers_from_structured(
        {"others_present": "yes", "asked_to_pay": "yes", "told_to_keep_secret": "yes"},
        Language.EN, []))
    first = await resolve_call(session, txn.id, scam, 41, "first report")
    assert first.outcome is VoiceOutcome.SCAM_DETECTED

    clean = assess(answers_from_structured(
        {"others_present": "no", "asked_to_pay": "no", "told_to_keep_secret": "no"},
        Language.EN, []))
    second = await resolve_call(session, txn.id, clean, 41, "second report")

    # The blocked outcome stands. A late duplicate must not release held money.
    assert second.outcome is VoiceOutcome.SCAM_DETECTED
    assert second.transcript == "first report"


# --------------------------------------------- the assistant the provider accepts

# Pinned from the provider's published schema. A value outside these sets is rejected
# when the call is placed, which is the worst possible moment to find out.
DEEPGRAM_LANGUAGES = {
    "en", "en-AU", "en-CA", "en-GB", "en-IE", "en-IN", "en-NZ", "en-US",
    "ar", "hi", "hi-Latn", "ur",
}
ELEVENLABS_VOICES = {
    "burt", "marissa", "andrea", "sarah", "phillip", "steve", "joseph", "myra",
    "paula", "ryan", "drew", "paul", "mrb", "matilda", "mark",
}
GROQ_MODELS = {
    "openai/gpt-oss-20b", "openai/gpt-oss-120b", "deepseek-r1-distill-llama-70b",
    "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-8b-8192",
    "llama3-70b-8192", "gemma2-9b-it", "moonshotai/kimi-k2-instruct-0905",
    "meta-llama/llama-4-scout-17b-16e-instruct", "mistral-saba-24b",
    "compound-beta", "compound-beta-mini",
}


@pytest.mark.parametrize("language", list(Language))
async def test_every_language_builds_an_assistant_the_provider_accepts(language):
    """A locale the transcriber rejects fails the call, not the build. Catch it here.

    ar-AE, hi-IN and ur-PK all look reasonable and are all rejected.
    """
    assistant = build_assistant(SCRIPTS[language], "8,000.00", "AED", "Test Payee")

    assert assistant["transcriber"]["language"] in DEEPGRAM_LANGUAGES
    assert assistant["voice"]["voiceId"] in ELEVENLABS_VOICES
    assert assistant["model"]["model"] in GROQ_MODELS
    assert assistant["model"]["provider"] == "groq"


@pytest.mark.parametrize("language", list(Language))
async def test_the_extraction_schema_asks_for_exactly_our_questions(language):
    """What Vapi extracts has to match what answers_from_structured reads back."""
    assistant = build_assistant(SCRIPTS[language], "8,000.00", "AED", "Test Payee")
    schema = assistant["analysisPlan"]["structuredDataPlan"]["schema"]

    keys = [q.key for q in SCRIPTS[language].questions]
    assert list(schema["properties"]) == keys
    assert schema["required"] == keys
    for field in schema["properties"].values():
        assert field["enum"] == ["yes", "no", "unclear"]

    # The round trip: what the plan promises is what the parser understands.
    extracted = dict.fromkeys(keys, "no")
    assert [a.question_key for a in
            answers_from_structured(extracted, language, [])] == keys


# ------------------------------------------------- the browser channel

# A UAE mobile cannot be reached by any AI voice platform, because Etisalat and du are
# required to block VoIP-originated termination. The browser channel carries the same
# conversation with no carrier in the path. These tests cover the seam between the two,
# since everything after the call starts is the shared code above.

async def held_call(session, *, channel: VoiceChannel) -> Transaction:
    txn = Transaction(
        customer_msisdn="+971504229551", signal_msisdn="+99999991004",
        customer_locale="en", amount=Decimal("42000.00"), currency="AED",
        merchant_name="Direct transfer", beneficiary_id=f"p-{uuid.uuid4().hex[:8]}",
        is_new_beneficiary=True,
    )
    session.add(txn)
    await session.flush()
    session.add(VoiceCall(transaction_id=txn.id, status=VoiceStatus.RINGING,
                          channel=channel, language="en"))
    await session.flush()
    return txn


@asynccontextmanager
async def web_client(session):
    """The app, wired to this test's session."""
    from app.db.session import get_session
    from app.main import app

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


async def test_web_session_hands_the_browser_a_script_it_did_not_write(
        session, monkeypatch):
    """The assistant is built on the server so the script stays in version control."""
    monkeypatch.setattr(settings, "vapi_public_key", "pk-test")
    txn = await held_call(session, channel=VoiceChannel.WEB)
    async with web_client(session) as client:
        r = await client.get(f"/voice/{txn.id}/web-session")
        assert r.status_code == 200
        body = r.json()
        assert body["public_key"] == "pk-test"

        assistant = body["assistant"]
        schema = assistant["analysisPlan"]["structuredDataPlan"]["schema"]
        assert list(schema["properties"]) == [
            "others_present", "asked_to_pay", "told_to_keep_secret"]
        assert "42,000.00" in assistant["firstMessage"]


async def test_web_session_never_leaks_the_private_key(session, monkeypatch):
    """The publishable key goes to the page. The private key must not."""
    monkeypatch.setattr(settings, "vapi_public_key", "pk-test")
    monkeypatch.setattr(settings, "vapi_api_key", "SECRET-PRIVATE-KEY")
    txn = await held_call(session, channel=VoiceChannel.WEB)
    async with web_client(session) as client:
        r = await client.get(f"/voice/{txn.id}/web-session")
        assert "SECRET-PRIVATE-KEY" not in r.text


async def test_a_phone_call_is_not_offered_to_the_browser(session, monkeypatch):
    monkeypatch.setattr(settings, "vapi_public_key", "pk-test")
    txn = await held_call(session, channel=VoiceChannel.PHONE)
    async with web_client(session) as client:
        r = await client.get(f"/voice/{txn.id}/web-session")
        assert r.status_code == 409


async def test_web_session_refuses_without_a_public_key(session, monkeypatch):
    """Better a clear 503 than a page that fails silently in front of judges."""
    monkeypatch.setattr(settings, "vapi_public_key", "")
    txn = await held_call(session, channel=VoiceChannel.WEB)
    async with web_client(session) as client:
        r = await client.get(f"/voice/{txn.id}/web-session")
        assert r.status_code == 503


async def test_web_started_records_the_call_and_needs_an_id(session):
    txn = await held_call(session, channel=VoiceChannel.WEB)
    async with web_client(session) as client:
        blank = await client.post(f"/voice/{txn.id}/web-started", json={})
        assert blank.status_code == 422

        r = await client.post(f"/voice/{txn.id}/web-started",
                              json={"call_id": "web-call-abc"})
        assert r.status_code == 200
        assert r.json()["accepted"] is True

    call = (await session.execute(
        select(VoiceCall).where(VoiceCall.transaction_id == txn.id))).scalar_one()
    assert call.vapi_call_id == "web-call-abc"
    assert call.status is VoiceStatus.IN_PROGRESS


async def test_a_resolved_call_cannot_be_restarted_from_the_browser(session):
    """A stale tab must not reopen a decision someone may already have acted on."""
    txn = await held_call(session, channel=VoiceChannel.WEB)
    call = (await session.execute(
        select(VoiceCall).where(VoiceCall.transaction_id == txn.id))).scalar_one()
    call.status = VoiceStatus.COMPLETED
    call.outcome = VoiceOutcome.SCAM_DETECTED
    await session.flush()

    async with web_client(session) as client:
        r = await client.post(f"/voice/{txn.id}/web-started", json={"call_id": "late"})
        assert r.json()["accepted"] is False

    again = (await session.execute(
        select(VoiceCall).where(VoiceCall.transaction_id == txn.id))).scalar_one()
    assert again.outcome is VoiceOutcome.SCAM_DETECTED


async def test_the_web_channel_does_not_dial(session, monkeypatch):
    """In web mode nothing may reach the telephony API. That is the whole point."""
    from app.voice import service as voice_service

    monkeypatch.setattr(settings, "voice_channel", "web")
    monkeypatch.setattr(settings, "voice_mock", False)

    async def explode(**kwargs):
        raise AssertionError("start_intervention dialled a phone in web mode")

    monkeypatch.setattr(voice_service, "place_call", explode)

    txn = Transaction(
        customer_msisdn="+971504229551", signal_msisdn="+99999991004",
        customer_locale="ar", amount=Decimal("42000.00"), currency="AED",
        merchant_name="Direct transfer", beneficiary_id=f"p-{uuid.uuid4().hex[:8]}",
        is_new_beneficiary=True,
    )
    session.add(txn)
    await session.flush()

    call = await voice_service.start_intervention(session, txn)
    assert call.channel is VoiceChannel.WEB
    assert call.status is VoiceStatus.RINGING
    assert call.language == "ar"        # the locale still chooses the script
