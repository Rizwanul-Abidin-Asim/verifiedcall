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
