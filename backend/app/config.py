"""Environment-based configuration. Nothing secret is hard-coded: production
refuses to start with the development defaults."""
from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-secret-change-me"
# A fixed, publicly known key used ONLY when ENVIRONMENT=development.
DEV_ENCRYPTION_KEY = "ZGV2LW9ubHktZW5jcnlwdGlvbi1rZXktMzItYnl0ZXM="


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Tallgrass Planner"
    environment: str = "development"  # development | staging | production
    database_url: str = "postgresql+psycopg://planner:planner@localhost:5432/planner"
    secret_key: str = DEV_SECRET
    encryption_key: str = DEV_ENCRYPTION_KEY  # Fernet key (32 url-safe base64 bytes)
    session_hours: int = 12
    cookie_secure: bool | None = None  # default: true outside development
    cors_origins: str = "http://localhost:3000"
    max_failed_logins: int = 8
    lockout_minutes: int = 15
    rate_limit_auth_per_minute: int = 20
    rate_limit_per_minute: int = 300
    max_monte_carlo_paths: int = 20000

    # AI assistant (OpenAI/OpenRouter-compatible chat-completions API). Empty = built-in demo helper.
    ai_base_url: str = "https://openrouter.ai/api/v1"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_dpa_confirmed: bool = False  # operator confirms a data-processing agreement is in place

    # Account aggregation (provider abstraction; "plaid" needs credentials).
    aggregation_provider: str = "none"  # none | plaid
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"

    @property
    def secure_cookies(self) -> bool:
        return (not self.is_dev) if self.cookie_secure is None else self.cookie_secure

    @property
    def ai_live(self) -> bool:
        return bool(self.ai_api_key and self.ai_model and self.ai_dpa_confirmed)

    @model_validator(mode="after")
    def _no_dev_secrets_in_production(self) -> Settings:
        if not self.is_dev and (self.secret_key == DEV_SECRET or self.encryption_key == DEV_ENCRYPTION_KEY):
            raise ValueError("SECRET_KEY and ENCRYPTION_KEY must be set outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
