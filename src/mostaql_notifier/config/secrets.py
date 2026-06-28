"""Secrets loaded from .env only (constitution IX). Never read tunables from here."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    database_url: str = "sqlite:///./data/mostaql.db"

    # Dashboard (Feature 2). Auth gates every data/settings route; trivially disableable for
    # local-only use via dashboard_auth_enabled=false (constitution IX — local security).
    dashboard_auth_enabled: bool = True
    dashboard_password: str = ""
    dashboard_session_secret: str = ""
    frontend_origin: str = "http://localhost:3000"

    # Feature 3 — where uploaded attachment bytes live on disk. A deployment path (like
    # database_url), not a behaviour tunable, so it stays in env/secrets rather than the settings
    # table. Default sits inside the backed-up ./data volume, outside any public web path
    # (constitution IX/X). Files are streamed only via gated endpoints, never statically mounted.
    attachments_dir: str = "./data/attachments"


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


def require_dashboard(secrets: Secrets) -> None:
    """Fail loud at startup if the dashboard is auth-enabled but the password/secret are missing."""
    if not secrets.dashboard_auth_enabled:
        return
    missing = [
        k for k in ("dashboard_password", "dashboard_session_secret") if not getattr(secrets, k)
    ]
    if missing:
        raise RuntimeError(
            f"Missing required dashboard secrets in .env: {', '.join(missing)} "
            "(set DASHBOARD_AUTH_ENABLED=false to run with no login, or see .env.example)"
        )
