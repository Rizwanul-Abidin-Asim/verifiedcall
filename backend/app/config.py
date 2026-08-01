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
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # --- Voice ---
    vapi_api_key: str = ""
    vapi_phone_number_id: str = ""
    elevenlabs_api_key: str = ""

    # --- Infra ---
    database_url: str = "postgresql+asyncpg://verifiedcall:verifiedcall@localhost:5432/verifiedcall"
    redis_url: str = "redis://localhost:6379/0"

    # --- Demo / test switches (see PROMPT 6 and PROMPT 9) ---
    demo_mode: bool = False
    """Force fallback CAMARA responses. Guaranteed-working path for a live pitch."""

    voice_mock: bool = True
    """Simulate Vapi call outcomes instead of placing (and paying for) real calls."""

    # --- Behaviour ---
    camara_timeout_s: float = 3.0
    camara_max_retries: int = 2
    app_env: str = "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
