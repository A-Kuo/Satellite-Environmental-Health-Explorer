"""Credentials must never reach the ingest log, whatever shape they arrive in."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from src.connectors.ingest_log import failure_note, redact_params, redact_text, redact_url

CANARY = "canary-not-a-real-credential"


def test_credential_params_are_masked_and_the_rest_is_kept() -> None:
    params = {
        "get": "B01001_001E",
        "key": CANARY,
        "api_key": CANARY,
        "$$app_token": CANARY,
        "X-Auth": CANARY,
        "nested": {"client_secret": CANARY, "year": 2022},
    }
    redacted = redact_params(params)
    assert CANARY not in str(redacted)
    assert redacted["get"] == "B01001_001E" and redacted["nested"]["year"] == 2022
    assert redacted["key"] == "REDACTED"


def test_input_params_are_not_mutated() -> None:
    params = {"key": CANARY}
    redact_params(params)
    assert params == {"key": CANARY}


def test_query_string_credentials_are_masked_in_urls() -> None:
    url = f"https://api.census.gov/data/2022/acs/acs5?get=B01001_001E&for=tract:*&key={CANARY}"
    redacted = redact_url(url)
    assert CANARY not in redacted
    query = parse_qs(urlsplit(redacted).query)
    assert query["key"] == ["REDACTED"]
    assert query["get"] == ["B01001_001E"] and query["for"] == ["tract:*"]


def test_userinfo_in_a_url_is_masked() -> None:
    redacted = redact_url(f"https://someone:{CANARY}@example.org/path?x=1")
    assert CANARY not in redacted and "someone" not in redacted
    assert redacted.startswith("https://REDACTED@example.org/path")


def test_a_url_without_credentials_is_unchanged_in_meaning() -> None:
    url = "https://example.org/data/file.csv"
    assert redact_url(url) == url


def test_credentials_inside_error_text_are_masked() -> None:
    text = f"Client error '403' for url 'https://x.example/api?year=2022&token={CANARY}&y=1'"
    redacted = redact_text(text)
    assert CANARY not in redacted and "year=2022" in redacted and "token=REDACTED" in redacted


def test_ordinary_text_is_left_alone() -> None:
    text = "value outside range for tract 55079000100: 150.0 > 100.0"
    assert redact_text(text) == text


def test_failure_notes_are_redacted_and_bounded() -> None:
    note = failure_note(RuntimeError(f"request failed: https://x.example?key={CANARY}"))
    assert note.startswith("RuntimeError:") and CANARY not in note
    assert len(failure_note(ValueError("x" * 5000))) == 500


@pytest.mark.parametrize(
    "name", ["key", "Key", "API_KEY", "access_token", "password", "Authorization"]
)
def test_common_credential_names_are_recognized(name: str) -> None:
    assert redact_params({name: CANARY})[name] == "REDACTED"
