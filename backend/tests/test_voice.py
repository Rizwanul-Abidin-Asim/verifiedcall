"""The voice layer: scripts, classification, and the end-to-end intervention.

Most of the risk here is in classify.py, because that is what turns a possibly-wrong
transcript into a decision about someone's money. The tests lean on the two things that
make it survivable: a keypad press beats the words, and hesitation is read as evidence.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base, Transaction, VoiceCall, VoiceOutcome, VoiceStatus
from app.voice.classify import HESITATION_MS, Reply, assess, interpret
from app.voice.scripts import (
    AFFIRMATIVE,
    NEGATIVE,
    SCRIPTS,
    Language,
    normalise_language,
    script_for,
)
from app.voice.service import resolution_for, resolve_call, start_intervention
from app.voice.vapi_client import build_assistant, simulate_call
from app.voice.webhooks import parse_answers

# ------------------------------------------------------------------- scripts


def test_every_language_has_the_same_three_questions():
    keys = {lang: [q.key for q in s.questions] for lang, s in SCRIPTS.items()}
    expected = ["others_present", "asked_to_pay", "told_to_keep_secret"]
    for lang, got in keys.items():
        assert got == expected, f"{lang} asks a different set of questions"


def test_the_two_coercion_questions_are_marked_in_every_language():
    for lang, s in SCRIPTS.items():
        flagged = {q.key for q in s.questions if q.scam_if_yes}
        assert flagged == {"asked_to_pay", "told_to_keep_secret"}, lang


def test_every_script_offers_the_keypad():
    """The keypad is what makes weak Arabic and Urdu speech recognition survivable, so
    every question in every language has to mention it."""
    # The opening deliberately does not carry it any more: it explained the keypad,
    # then question one explained it again, and the greeting ran twenty seconds.
    for lang, s in SCRIPTS.items():
        for q in s.questions:
            assert "1" in q.text and "2" in q.text, f"{lang}/{q.key} omits the keypad"


def test_opening_states_the_amount_and_who_it_goes_to():
    for lang, s in SCRIPTS.items():
        rendered = s.rendered_opening("42,000.00", "AED", "Direct transfer")
        assert "42,000.00" in rendered, lang
        assert "AED" in rendered, lang
        assert "Direct transfer" in rendered, lang
        assert "{" not in rendered, f"{lang} left an unfilled placeholder"


@pytest.mark.parametrize("locale,expected", [
    ("en", Language.EN), ("ar", Language.AR), ("hi", Language.HI), ("ur", Language.UR),
    ("ar-AE", Language.AR), ("en_GB", Language.EN), ("UR", Language.UR),
    (None, Language.EN), ("", Language.EN), ("fr", Language.EN), ("klingon", Language.EN),
])
def test_locale_mapping(locale, expected):
    assert normalise_language(locale) is expected
    assert script_for(locale).language is expected


def test_yes_and_no_words_do_not_overlap():
    for lang in Language:
        overlap = set(AFFIRMATIVE[lang]) & set(NEGATIVE[lang])
        assert not overlap, f"{lang} has words in both lists: {overlap}"


# -------------------------------------------------------------- interpreting


@pytest.mark.parametrize("lang", list(Language))
def test_spoken_yes_and_no_in_each_language(lang):
    yes = interpret("asked_to_pay", lang, heard=AFFIRMATIVE[lang][0], keypad=None,
                    response_ms=800)
    no = interpret("asked_to_pay", lang, heard=NEGATIVE[lang][0], keypad=None,
                   response_ms=800)
    assert yes.reply is Reply.YES
    assert no.reply is Reply.NO


def test_keypad_beats_a_wrong_transcript():
    """The whole point of offering the keypad: when speech recognition mishears, the
    digit is still exact."""
    a = interpret("asked_to_pay", Language.AR, heard="no", keypad="1", response_ms=900)
    assert a.reply is Reply.YES
    assert a.from_keypad


def test_unrecognised_speech_is_unclear_not_a_guess():
    a = interpret("asked_to_pay", Language.EN, heard="mmm well I suppose",
                  keypad=None, response_ms=900)
    assert a.reply is Reply.UNCLEAR


def test_hesitation_is_flagged_on_timing_alone():
    quick = interpret("told_to_keep_secret", Language.EN, "no", None, 900)
    slow = interpret("told_to_keep_secret", Language.EN, "no", None, HESITATION_MS + 1)
    assert quick.hesitant is False
    assert slow.hesitant is True
    assert slow.reply is Reply.NO, "hesitation must not change what they said"


# --------------------------------------------------------------- assessment


def answers(others="no", asked="no", secret="no", secret_ms=900, lang=Language.EN):
    words = {"yes": AFFIRMATIVE[lang][0], "no": NEGATIVE[lang][0]}
    return [
        interpret("others_present", lang, words[others], None, 900),
        interpret("asked_to_pay", lang, words[asked], None, 1000),
        interpret("told_to_keep_secret", lang, words[secret], None, secret_ms),
    ]


def test_clean_answers_release_the_payment():
    a = assess(answers())
    assert a.outcome is VoiceOutcome.CONFIRMED_LEGITIMATE
    assert resolution_for(a.outcome) == "released"


@pytest.mark.parametrize("field", ["asked", "secret"])
def test_admitting_either_coercion_question_blocks_the_payment(field):
    a = assess(answers(**{field: "yes"}))
    assert a.outcome is VoiceOutcome.SCAM_DETECTED
    assert resolution_for(a.outcome) == "blocked"


def test_hesitant_denial_goes_to_a_human_not_through():
    """The case the whole timing idea exists for: they say no, but slowly."""
    a = assess(answers(secret="no", secret_ms=HESITATION_MS + 1500))
    assert a.outcome is VoiceOutcome.INCONCLUSIVE
    assert resolution_for(a.outcome) == "held_for_analyst"
    assert "hesitat" in a.rationale.lower()


def test_a_hesitant_keypad_denial_is_trusted():
    """Timing means something for speech. Someone fumbling for a key is not evidence."""
    a = assess([
        interpret("others_present", Language.EN, None, "2", 900),
        interpret("asked_to_pay", Language.EN, None, "2", 1000),
        interpret("told_to_keep_secret", Language.EN, None, "2", HESITATION_MS + 3000),
    ])
    assert a.outcome is VoiceOutcome.CONFIRMED_LEGITIMATE


def test_someone_else_in_the_room_goes_to_a_human():
    a = assess(answers(others="yes"))
    assert a.outcome is VoiceOutcome.INCONCLUSIVE
    assert resolution_for(a.outcome) == "held_for_analyst"


def test_an_unclear_answer_is_never_treated_as_clean():
    a = assess([
        interpret("others_present", Language.EN, "no", None, 900),
        interpret("asked_to_pay", Language.EN, "erm", None, 1000),
        interpret("told_to_keep_secret", Language.EN, "no", None, 900),
    ])
    assert a.outcome is VoiceOutcome.INCONCLUSIVE


def test_no_answer_holds_the_payment():
    a = assess([], answered=False)
    assert a.outcome is VoiceOutcome.NO_ANSWER
    assert resolution_for(a.outcome) == "held_for_analyst"


def test_silence_never_releases_money():
    """The safe default when we do not know is not to let the money go."""
    for outcome in (VoiceOutcome.NO_ANSWER, VoiceOutcome.INCONCLUSIVE,
                    VoiceOutcome.SCAM_DETECTED):
        assert resolution_for(outcome) != "released"


# --------------------------------------------------------------- simulator


@pytest.mark.parametrize("suffix,expected", [
    ("0", VoiceOutcome.SCAM_DETECTED),
    ("1", VoiceOutcome.CONFIRMED_LEGITIMATE),
    ("2", VoiceOutcome.INCONCLUSIVE),
    ("9", VoiceOutcome.NO_ANSWER),
    ("7", VoiceOutcome.SCAM_DETECTED),
])
def test_simulator_is_deterministic_by_number(suffix, expected):
    assessment, duration = simulate_call(f"+97150000000{suffix}", Language.EN)
    assert assessment.outcome is expected
    assert duration > 0


@pytest.mark.parametrize("lang", list(Language))
def test_simulator_works_in_every_language(lang):
    assessment, _ = simulate_call("+971500000001", lang)
    assert assessment.outcome is VoiceOutcome.CONFIRMED_LEGITIMATE


def test_real_assistant_definition_carries_the_script():
    a = build_assistant(script_for("ar"), "42,000.00", "AED", "Direct transfer")
    assert "42,000.00" in a["firstMessage"]
    # Bare "ar", not "ar-AE". The transcriber only accepts regional variants for
    # English; see the note on SPEECH_LOCALE and the schema test in test_voice_live.py.
    assert a["transcriber"]["language"] == "ar"
    system = a["model"]["messages"][0]["content"]
    for q in script_for("ar").questions:
        assert q.text in system


# ------------------------------------------------------------------ webhook


def test_webhook_parses_a_well_formed_report():
    payload = {"message": {"analysis": {"structuredData": {"answers": [
        {"question_key": "others_present", "heard": "no", "response_ms": 800},
        {"question_key": "asked_to_pay", "heard": "yes", "response_ms": 1200},
        {"question_key": "told_to_keep_secret", "keypad": 1, "response_ms": 700},
    ]}}}}
    parsed = parse_answers(payload, Language.EN)
    assert len(parsed) == 3
    assert assess(parsed).outcome is VoiceOutcome.SCAM_DETECTED


@pytest.mark.parametrize("payload", [
    {}, {"message": {}}, {"message": {"analysis": {}}},
    {"message": {"analysis": {"structuredData": {"answers": "not a list"}}}},
    {"message": {"analysis": {"structuredData": {"answers": [{"no_key": 1}]}}}},
])
def test_a_report_we_cannot_read_never_looks_like_a_clean_call(payload):
    parsed = parse_answers(payload, Language.EN)
    assert parsed == []
    assert assess(parsed, answered=False).outcome is VoiceOutcome.NO_ANSWER


# ------------------------------------------------------- service integration


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
    await engine.dispose()


async def make_txn(session, msisdn="+971500000000", locale="ar"):
    txn = Transaction(
        amount=Decimal("42000.00"), currency="AED", merchant_name="Direct transfer",
        beneficiary_id="BEN-1", is_new_beneficiary=True,
        customer_msisdn=msisdn, signal_msisdn="+99999991004", customer_locale=locale)
    session.add(txn)
    await session.flush()
    return txn


async def test_intervention_creates_a_ringing_call(session, monkeypatch):
    monkeypatch.setattr(settings, "voice_mock", True)
    txn = await make_txn(session)
    call = await start_intervention(session, txn)

    assert call.status is VoiceStatus.RINGING
    assert call.is_mock is True
    assert call.language == "ar", "the call must be placed in the customer's language"
    assert call.outcome is None


async def test_intervention_is_not_placed_twice(session, monkeypatch):
    monkeypatch.setattr(settings, "voice_mock", True)
    txn = await make_txn(session)
    first = await start_intervention(session, txn)
    second = await start_intervention(session, txn)
    assert first.id == second.id

    rows = (await session.execute(
        select(VoiceCall).where(VoiceCall.transaction_id == txn.id))).scalars().all()
    assert len(rows) == 1


async def test_resolving_records_answers_and_outcome(session, monkeypatch):
    monkeypatch.setattr(settings, "voice_mock", True)
    txn = await make_txn(session, msisdn="+971500000000")
    await start_intervention(session, txn)

    assessment, duration = simulate_call(txn.customer_msisdn, Language.AR)
    call = await resolve_call(session, txn.id, assessment, duration)

    assert call.status is VoiceStatus.COMPLETED
    assert call.outcome is VoiceOutcome.SCAM_DETECTED
    assert set(call.answers) == {"others_present", "asked_to_pay", "told_to_keep_secret"}
    assert call.duration_s == duration
    assert call.transcript


async def test_resolving_an_unknown_transaction_is_survivable(session):
    assessment, duration = simulate_call("+971500000001", Language.EN)
    assert await resolve_call(session, uuid.uuid4(), assessment, duration) is None


async def test_a_failed_dial_leaves_the_payment_held(session, monkeypatch):
    """VOICE_MOCK off with no credentials is the realistic failure. It must record the
    failure rather than raise, because the payment is already held and stays held."""
    monkeypatch.setattr(settings, "voice_mock", False)
    monkeypatch.setattr(settings, "vapi_api_key", "")
    txn = await make_txn(session)

    call = await start_intervention(session, txn)
    assert call.status is VoiceStatus.FAILED
    assert call.outcome is None
    assert resolution_for(call.outcome) == "held_for_analyst"
