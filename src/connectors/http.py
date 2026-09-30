"""HTTP client for public data APIs.

Behavior every connector inherits (design spec section 5.4):

- A truthful, stable User-Agent naming the project and a contact. Never spoofed.
- A minimum interval between requests; one client per source, one worker per source.
- Retry with exponential backoff and full jitter on transient errors.
- A deliberate pause after 429 or 406, honoring ``Retry-After``, and never a
  tight retry loop.
- Conditional requests (ETag / Last-Modified) so an unchanged release is not
  downloaded again.
- API keys are attached as request parameters here and are never logged or stored
  (see ``ingest_log.redact_params``).
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any

import httpx

from src.connectors.env import ConfigurationError
from src.connectors.raw_store import FetchRecord, RawPayload, RawStore

PRODUCT = "SatelliteEnvHealthExplorer/0.1"
PROJECT_URL = "https://github.com/A-Kuo/Satellite-Environmental-Health-Explorer"
PAUSE_STATUSES = frozenset({429, 406})
RETRY_STATUSES = frozenset({500, 502, 503, 504})


class FetchError(RuntimeError):
    """A request failed for good: a non-retryable status, or retries ran out."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def build_user_agent(contact: str | None = None) -> str:
    """Identify the project and a way to reach its operator.

    Live requests need a real contact (``CONNECTOR_CONTACT``). Fixture mode never
    leaves the machine, so it may pass an explicit placeholder.
    """
    contact = contact or os.environ.get("CONNECTOR_CONTACT", "")
    if not contact.strip():
        raise ConfigurationError("CONNECTOR_CONTACT is not set")
    return f"{PRODUCT} (+{PROJECT_URL}; contact: {contact.strip()})"


def _retry_after_seconds(response: httpx.Response, now: datetime | None = None) -> float | None:
    """Parse ``Retry-After`` as seconds or an HTTP date; ``None`` if absent or invalid."""
    header = response.headers.get("Retry-After")
    if not header:
        return None
    header = header.strip()
    if header.isdigit():
        return float(header)
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


class SourceClient:
    """One client per source. Not thread-safe by design: one worker per source."""

    def __init__(
        self,
        source: str,
        *,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        min_interval_s: float = 1.0,
        max_retries: int = 5,
        base_delay_s: float = 1.0,
        max_delay_s: float = 60.0,
        pause_floor_s: float = 30.0,
        max_pause_s: float = 300.0,
        timeout_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.source = source
        self._min_interval = min_interval_s
        self._max_retries = max_retries
        self._base = base_delay_s
        self._max_delay = max_delay_s
        self._pause_floor = pause_floor_s
        self._max_pause = max_pause_s
        self._sleep = sleep
        self._clock = clock
        self._rng = rng or random.Random()  # noqa: S311 - backoff jitter, not cryptography
        self._last_request: float | None = None
        self._client = httpx.Client(
            transport=transport,
            headers={"User-Agent": user_agent},
            timeout=timeout_s,
            follow_redirects=True,
        )

    def __enter__(self) -> SourceClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- pacing -----------------------------------------------------------------

    def _space_requests(self) -> None:
        if self._last_request is not None:
            wait = self._min_interval - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)

    def _backoff(self, attempt: int) -> float:
        """Full jitter: uniform in [0, min(cap, base * 2**attempt)]."""
        return self._rng.uniform(0, min(self._max_delay, self._base * 2**attempt))

    def _delay_after(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None and response.status_code in PAUSE_STATUSES:
            asked = _retry_after_seconds(response)
            pause = self._pause_floor if asked is None else asked
            return min(max(pause, 0.0), self._max_pause)
        if response is not None:
            asked = _retry_after_seconds(response)
            if asked is not None:
                return min(asked, self._max_pause)
        return self._backoff(attempt)

    # -- requests ---------------------------------------------------------------

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """GET with pacing, retries and a pause on 429/406. 304 is returned as is."""
        last_status: int | None = None
        for attempt in range(self._max_retries + 1):
            self._space_requests()
            response: httpx.Response | None = None
            try:
                response = self._client.get(url, params=params, headers=headers)
            except httpx.TransportError:
                pass  # network hiccup: retry below
            finally:
                self._last_request = self._clock()

            if response is not None:
                last_status = response.status_code
                if response.is_success or response.status_code == 304:
                    return response
                retryable = response.status_code in PAUSE_STATUSES | RETRY_STATUSES
                if not retryable:
                    raise FetchError(
                        f"{self.source}: HTTP {response.status_code} (not retried)",
                        response.status_code,
                    )
            if attempt == self._max_retries:
                break
            self._sleep(self._delay_after(response, attempt))
        raise FetchError(
            f"{self.source}: gave up after {self._max_retries + 1} attempts "
            f"(last status: {last_status})",
            last_status,
        )

    def fetch_to_store(
        self,
        store: RawStore,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        suffix: str = ".bin",
        request_key: str,
    ) -> tuple[RawPayload, bool]:
        """Download into the raw store, skipping the body of an unchanged release.

        ``request_key`` identifies the request in the cache index and must NOT
        contain credentials. Returns ``(payload, from_cache)``.
        """
        record = store.get_record(self.source, request_key)
        conditional: dict[str, str] = {}
        if record is not None:
            if record.etag:
                conditional["If-None-Match"] = record.etag
            if record.last_modified:
                conditional["If-Modified-Since"] = record.last_modified

        response = self.get(url, params=params, headers=conditional)
        if response.status_code == 304 and record is not None:
            path = store.path_for(self.source, record.sha256, record.suffix)
            payload = RawPayload(self.source, path, record.sha256, path.stat().st_size)
            store.verify(payload)
            return payload, True

        payload = store.save(self.source, response.content, suffix)
        store.put_record(
            self.source,
            request_key,
            FetchRecord(
                sha256=payload.sha256,
                suffix=suffix,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            ),
        )
        return payload, False


def fixture_transport(
    routes: Mapping[str, bytes | str | Callable[[httpx.Request], httpx.Response]],
) -> httpx.MockTransport:
    """A transport that serves recorded responses and never touches the network.

    ``routes`` maps a URL substring to the body to return (or a handler). An
    unrouted URL raises, so fixture mode cannot silently go live.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, answer in routes.items():
            if fragment in str(request.url):
                if callable(answer):
                    return answer(request)
                body = answer.encode("utf-8") if isinstance(answer, str) else answer
                return httpx.Response(200, content=body)
        raise AssertionError(f"fixture mode: no recorded response for {request.url}")

    return httpx.MockTransport(handler)
