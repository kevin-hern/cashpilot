from pydantic_settings import BaseSettings
from typing import List
import json


def _parse_cors(raw: str) -> List[str]:
    """Accept JSON array or comma-separated string — handles both .env style and
    plain Railway/Vercel environment variable panel values."""
    raw = raw.strip()
    if raw.startswith("["):
        return json.loads(raw)
    return [o.strip() for o in raw.split(",") if o.strip()]


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://cashpilot:cashpilot@localhost:5432/cashpilot"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Plaid
    PLAID_CLIENT_ID: str = ""
    PLAID_SECRET: str = ""
    PLAID_ENV: str = "sandbox"
    PLAID_WEBHOOK_URL: str = ""

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # AES-256 hex key for encrypting Plaid access tokens (64 hex chars = 32 bytes)
    ENCRYPTION_KEY: str = "0000000000000000000000000000000000000000000000000000000000000000"

    # CORS: "*" allows all origins. Supports comma-separated or JSON array.
    CORS_ORIGINS: str = "*"

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return _parse_cors(self.CORS_ORIGINS)

    # Approval settings
    INTENT_EXPIRY_HOURS: int = 48
    REAUTH_THRESHOLD_DOLLARS: float = 0.01

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
