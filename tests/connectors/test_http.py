"""HTTP client: identity, retries, pauses, pacing and conditional requests.

Nothing here touches the network: every request goes to an in-memory transport, and
sleeping is replaced by a recorder, so the tests are instant and deterministic.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from src.connectors.env import ConfigurationError
from src.connectors.http import (
    PRODUCT,
    PROJECT_URL,
    FetchError,
    SourceClient,
    _retry_after_seconds,
    build_user_agent,
    fixture_transport,
)
from src.connectors.raw_store import RawStore


class Script:
    """Serves a fixed sequence of responses and remembers what it was asked."""

    def __init__(self, *answers: httpx.Response | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def make_client(script: Script, **overrides: object) -> tuple[SourceClient, list[float]]:
    sleeps: list[float] = []
    settings: dict[str, object] = {
        "min_interval_s": 0,
        "max_retries": 4,
        "base_delay_s": 1.0,
        "max_delay_s": 60.0,
        "sleep": sleeps.append,
        "rng": random.Random(0),
    }
    client = SourceClient(
        "demo",
        user_agent="test-agent",
        transport=httpx.MockTransport(script),
        **{**settings, **overrides},  # type: ignore[arg-type]
    )
    return client, sleeps


def status(code: int, **headers: str) -> httpx.Response:
    return httpx.Response(code, headers=headers, content=b"body")


# --- identity ------------------------------------------------------------------


def test_the_user_agent_names_the_project_and_a_contact() -> None:
    agent = build_user_agent("ops@example.org")
    assert agent.startswith(PRODUCT) and PROJECT_URL in agent and "ops@example.org" in agent


def test_live_requests_need_a_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONNECTOR_CONTACT", raising=False)
    with pytest.raises(ConfigurationError, match="CONNECTOR_CONTACT"):
        build_user_agent()
    monkeypatch.setenv("CONNECTOR_CONTACT", "from-env@example.org")
    assert "from-env@example.org" in build_user_agent()


def test_every_request_carries_the_truthful_user_agent() -> None:
    script = Script(status(200))
    client, _ = make_client(script)
    client.get("https://example.org/data")
    assert script.requests[0].headers["User-Agent"] == "test-agent"


# --- retries -------------------------------------------------------------------


def test_transient_errors_are_retried_with_jittered_backoff() -> None:
    script = Script(status(503), status(503), status(200))
    client, sleeps = make_client(script)
    assert client.get("https://example.org/data").status_code == 200
    assert len(script.requests) == 3
    # Full jitter: the wait before attempt n is uniform in [0, base * 2**n].
    assert 0 <= sleeps[0] <= 1.0 and 0 <= sleeps[1] <= 2.0


def test_retries_stop_at_the_limit() -> None:
    script = Script(status(503))
    client, sleeps = make_client(script, max_retries=2)
    with pytest.raises(FetchError, match="gave up after 3 attempts") as raised:
        client.get("https://example.org/data")
    assert raised.value.status == 503
    assert len(script.requests) == 3 and len(sleeps) == 2


def test_backoff_is_capped() -> None:
    script = Script(status(503))
    client, sleeps = make_client(script, max_retries=8, base_delay_s=10.0, max_delay_s=15.0)
    with pytest.raises(FetchError):
        client.get("https://example.org/data")
    assert max(sleeps) <= 15.0


def test_a_network_error_is_retried() -> None:
    script = Script(httpx.ConnectError("boom"), status(200))
    client, sleeps = make_client(script)
    assert client.get("https://example.org/data").status_code == 200
    assert len(sleeps) == 1


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_client_errors_are_not_retried(code: int) -> None:
    script = Script(status(code))
    client, sleeps = make_client(script)
    with pytest.raises(FetchError, match="not retried") as raised:
        client.get("https://example.org/data")
    assert raised.value.status == code and len(script.requests) == 1 and sleeps == []


# --- pausing on 429 / 406 ------------------------------------------------------


def test_a_429_pauses_for_the_time_the_server_asks() -> None:
    script = Script(status(429, **{"Retry-After": "7"}), status(200))
    client, sleeps = make_client(script)
    client.get("https://example.org/data")
    assert sleeps == [7.0]


@pytest.mark.parametrize("code", [429, 406])
def test_without_a_hint_it_pauses_for_a_long_floor_not_a_short_backoff(code: int) -> None:
    script = Script(status(code), status(200))
    client, sleeps = make_client(script, pause_floor_s=30.0)
    client.get("https://example.org/data")
    assert sleeps == [30.0]


def test_an_absurd_retry_after_is_capped() -> None:
    script = Script(status(429, **{"Retry-After": "99999"}), status(200))
    client, sleeps = make_client(script, max_pause_s=300.0)
    client.get("https://example.org/data")
    assert sleeps == [300.0]


def test_retry_after_accepts_an_http_date() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    response = status(429, **{"Retry-After": "Thu, 01 Jan 2026 12:00:45 GMT"})
    assert _retry_after_seconds(response, now=now) == 45.0
    assert _retry_after_seconds(status(429, **{"Retry-After": "garbage"})) is None
    assert _retry_after_seconds(status(429)) is None


# --- pacing --------------------------------------------------------------------


def test_requests_are_spaced_by_the_minimum_interval() -> None:
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = SourceClient(
        "demo",
        user_agent="test-agent",
        transport=httpx.MockTransport(Script(status(200))),
        min_interval_s=2.0,
        sleep=sleep,
        clock=lambda: now[0],
    )
    client.get("https://example.org/a")
    now[0] += 0.5  # the caller did a little work in between
    client.get("https://example.org/b")
    assert sleeps == [pytest.approx(1.5)]


# --- raw store integration -----------------------------------------------------


def test_an_unchanged_release_is_not_downloaded_again(tmp_path: Path) -> None:
    body = b"a,b\n1,2\n"
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.headers))
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=body, headers={"ETag": '"v1"'})

    client = SourceClient(
        "demo", user_agent="ua", transport=httpx.MockTransport(handler), min_interval_s=0
    )
    store = RawStore(tmp_path)
    first, from_cache_first = client.fetch_to_store(
        store, "https://example.org/x.csv", suffix=".csv", request_key="x"
    )
    second, from_cache_second = client.fetch_to_store(
        store, "https://example.org/x.csv", suffix=".csv", request_key="x"
    )
    assert (from_cache_first, from_cache_second) == (False, True)
    assert first.path == second.path and first.sha256 == second.sha256
    assert "if-none-match" in calls[1] and "if-none-match" not in calls[0]


def test_a_changed_release_is_stored_alongside_the_old_one(tmp_path: Path) -> None:
    bodies = iter([b"release one", b"release two"])
    client = SourceClient(
        "demo",
        user_agent="ua",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=next(bodies))),
        min_interval_s=0,
    )
    store = RawStore(tmp_path)
    first, _ = client.fetch_to_store(store, "https://example.org/x", suffix=".bin", request_key="x")
    second, _ = client.fetch_to_store(
        store, "https://example.org/x", suffix=".bin", request_key="x"
    )
    assert first.path != second.path and first.path.exists() and second.path.exists()


def test_the_cache_index_never_contains_the_api_key(tmp_path: Path) -> None:
    canary = "canary-not-a-real-key"
    client = SourceClient(
        "demo",
        user_agent="ua",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")),
        min_interval_s=0,
    )
    store = RawStore(tmp_path)
    client.fetch_to_store(
        store,
        "https://example.org/data",
        params={"key": canary},
        suffix=".bin",
        request_key="https://example.org/data",  # the caller's key excludes credentials
    )
    index = (tmp_path / "demo" / "index.json").read_text()
    assert canary not in index


def test_fixture_mode_can_never_go_live() -> None:
    transport = fixture_transport({"known.csv": b"ok"})
    client = SourceClient("demo", user_agent="ua", transport=transport, min_interval_s=0)
    assert client.get("https://example.org/known.csv").content == b"ok"
    with pytest.raises(AssertionError, match="no recorded response"):
        client.get("https://example.org/unrecorded.csv")
