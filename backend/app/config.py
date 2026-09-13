"""Application settings, loaded from environment / .env via pydantic-settings.

Secrets are NEVER hardcoded here. Copy .env.example to .env and fill it in.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- CAMARA / Nokia Network-as-Code ---
    nokia_nac_api_key: str = ""
    nokia_nac_base_url: str = ""

    # --- Agent LLM ---
    # Provider is configurable so a rate limit mid-pitch is a one-line .env change rather
    # than a crisis, and so we can measure which model is more SELECTIVE about which
    # signals it pulls — that selectivity is our "real agent, not a rules engine" claim.
    llm_provider: str = "groq"  # groq | gemini
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    agent_timeout_s: float = 12.0  # Groq slows under burst; 8s tripped the fallback

    # If the primary provider is rate-limited or down, try this one before giving up on
    # reasoning altogether. Measured 2026-09-12: Groq answers in ~7.5s and is genuinely
    # selective (3 of 7 signals); Gemini answers in ~25s and pulls everything. So Groq
    # leads on both speed and judgement, and Gemini exists to keep an agent in the loop
    # on the day Groq's free tier says no — a slow analyst beats no analyst.
    # Set to "" to disable the second attempt.
    llm_fallback_provider: str = "gemini"
    llm_fallback_timeout_s: float = 28.0

    # The model that talks to the customer on the phone. Deliberately NOT the same one
    # that scores the payment.
    #
    # The risk agent runs on Groq's gpt-oss-120b and is excellent there: it answers in
    # about 7 seconds and genuinely picks 3 of 7 signals. But it is a *reasoning* model,
    # and inside a real-time voice loop that turned out to be unusable. Two defects,
    # both documented by other people rather than guessed at by us:
    #
    #   - it returns silent empty completions with no error, which Vapi cannot speak.
    #     Observed on our own calls: the model billed 250 completion tokens while
    #     ElevenLabs synthesised 0 characters, and the call died with
    #     endedReason=silence-timed-out.
    #   - roughly 4 requests in 10 leak reasoning tokens into the spoken output, which
    #     is where "press 1 if you're worth" and "and as I was saying" came from.
    #
    # Groq currently offers no non-reasoning model we could swap to, so the voice leg
    # moves to Gemini, which is already part of this project's stack.
    voice_llm_provider: str = "google"
    voice_llm_model: str = "gemini-2.5-flash"

    # --- Voice ---
    vapi_api_key: str = ""
    vapi_phone_number_id: str = ""
    # The browser SDK authenticates with a separate, publishable key. It is meant to be
    # visible in page source; the private key above must never be.
    vapi_public_key: str = ""
    # "phone" dials out; "web" hands the same conversation to the browser. Web exists
    # because UAE carriers block VoIP termination, so no platform can ring a UAE mobile.
    voice_channel: str = "phone"
    elevenlabs_api_key: str = ""

    # Our own Twilio number, imported into the voice platform. Needed because no voice
    # platform's bundled number reaches the UAE: Vapi's free numbers are US national
    # only, Retell's managed numbers cover sixteen countries that do not include the
    # Emirates, and ElevenLabs does not issue numbers at all. Twilio publishes a rate
    # for UAE mobiles, so the carrier is the layer that can actually place the call.
    # Which browsers may call this API. Comma separated. The regex covers Vercel, where
    # every deployment gets its own hostname, so listing them is not possible.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_origin_regex: str = r"https://.*\.vercel\.app"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # --- Infra ---
    database_url: str = "postgresql+asyncpg://verifiedcall:verifiedcall@localhost:55432/verifiedcall"
    redis_url: str = "redis://localhost:56379/0"

    # --- Demo / test switches (see PROMPT 6 and PROMPT 9) ---
    demo_mode: bool = False
    """Force fallback CAMARA responses. Guaranteed-working path for a live pitch."""

    voice_mock: bool = True
    """Simulate Vapi call outcomes instead of placing (and paying for) real calls."""

    voice_mock_seconds: float = 4.0
    """How long a simulated call appears to take, so the dashboard visibly shows one in
    progress rather than flicking straight to the result."""

    # --- Behaviour ---
    camara_timeout_s: float = 3.0
    camara_max_retries: int = 2
    app_env: str = "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
