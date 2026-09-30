"""Environment access for connectors. Values are read, never printed or logged."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
# `.env/` is a directory (it also holds the GEE key), so the env file is `.env/.env`.
ENV_FILE = ROOT / ".env" / ".env"


class ConfigurationError(RuntimeError):
    """A required setting is missing or unsafe. The message names the variable only."""


def load_env(path: Path | None = None) -> None:
    """Load ``.env/.env`` if it exists. Real environment variables win."""
    load_dotenv(path or ENV_FILE, override=False)


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ConfigurationError(f"{name} is not set")
    return value


def app_env() -> str:
    """``dev`` or ``prod``; anything else is a configuration error."""
    value = os.environ.get("APP_ENV", "")
    if value not in {"dev", "prod"}:
        raise ConfigurationError("APP_ENV must be 'dev' or 'prod'")
    return value
