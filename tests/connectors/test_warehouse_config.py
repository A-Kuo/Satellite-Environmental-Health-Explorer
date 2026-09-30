"""Connection settings: refuse unsafe or missing configuration before any query."""

from __future__ import annotations

import pytest

from src.connectors.env import ConfigurationError, app_env, require_env
from src.connectors.warehouse import connect


def test_a_missing_connection_variable_is_named_but_never_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_INGEST", raising=False)
    with pytest.raises(ConfigurationError, match="DATABASE_URL_INGEST is not set"):
        connect()


def test_a_pooled_host_is_refused_because_connectors_use_advisory_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL_INGEST", "postgresql://u@ep-cool-123-pooler.aws.neon.tech/db")
    with pytest.raises(ConfigurationError, match="pooled host"):
        connect()


def test_require_env_and_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_SETTING", "value")
    assert require_env("SOME_SETTING") == "value"
    monkeypatch.setenv("SOME_SETTING", "")
    with pytest.raises(ConfigurationError):
        require_env("SOME_SETTING")

    monkeypatch.setenv("APP_ENV", "dev")
    assert app_env() == "dev"
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ConfigurationError, match="APP_ENV"):
        app_env()
