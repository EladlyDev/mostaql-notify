"""Secrets loaded from .env only (constitution IX). Never read tunables from here."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    database_url: str = "sqlite:///./data/mostaql.db"


@lru_cache
def get_secrets() -> Secrets:
    return Secrets()


def require_telegram(secrets: Secrets) -> None:
    """Fail loud at startup if Telegram credentials are missing."""
    missing = [k for k in ("telegram_bot_token", "telegram_chat_id") if not getattr(secrets, k)]
    if missing:
        raise RuntimeError(
            f"Missing required secrets in .env: {', '.join(missing)} (see .env.example)"
        )
