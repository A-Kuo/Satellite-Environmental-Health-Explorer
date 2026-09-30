"""Provenance: one ``core.ingest_log`` row per fetched payload.

Credentials never reach the log. Many public APIs (Census, Socrata) take the key
as a query parameter, so URLs, parameters and failure messages are all redacted
before they are stored.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.types.json import Jsonb

from src.connectors.raw_store import RawPayload

Status = Literal["fetched", "cleaned", "validated", "loaded", "published", "failed"]
_FORWARD: tuple[str, ...] = ("fetched", "cleaned", "validated", "loaded", "published")
_MASK = "REDACTED"
_SENSITIVE_NAME = re.compile(r"key|token|secret|passw|credential|auth", re.IGNORECASE)
_SENSITIVE_PAIR = re.compile(
    r"(?P<name>[\w-]*(?:key|token|secret|passw\w*|credential|auth)[\w-]*)=(?P<value>[^&\s\"']+)",
    re.IGNORECASE,
)
_MAX_NOTE = 500


class StatusError(RuntimeError):
    """An ingest run tried to move to a status it cannot reach from where it is."""


def redact_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """Copy of ``params`` with every credential-looking value masked."""
    out: dict[str, Any] = {}
    for name, value in params.items():
        if _SENSITIVE_NAME.search(str(name)):
            out[name] = _MASK
        elif isinstance(value, Mapping):
            out[name] = redact_params(value)
        else:
            out[name] = value
    return out


def redact_url(url: str) -> str:
    """Mask credential-looking query values and any ``user:password@`` part."""
    parts = urlsplit(url)
    query = [
        (name, _MASK if _SENSITIVE_NAME.search(name) else value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    host = parts.netloc.rsplit("@", 1)[-1]
    netloc = f"{_MASK}@{host}" if "@" in parts.netloc else host
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), parts.fragment))


def redact_text(text: str) -> str:
    """Mask ``name=value`` credentials inside free text such as an exception message."""
    return _SENSITIVE_PAIR.sub(lambda m: f"{m.group('name')}={_MASK}", text)


def failure_note(exc: BaseException) -> str:
    return redact_text(f"{type(exc).__name__}: {exc}")[:_MAX_NOTE]


def register_payload(
    conn: psycopg.Connection,
    *,
    source: str,
    url: str,
    params: Mapping[str, Any],
    payload: RawPayload | None,
    is_fixture: bool,
) -> uuid.UUID:
    """Record a fetched payload with status ``fetched`` and return its run id."""
    row = conn.execute(
        "INSERT INTO core.ingest_log (source, url, params, sha256, bytes, status, is_fixture) "
        "VALUES (%s, %s, %s, %s, %s, 'fetched', %s) RETURNING ingest_run_id",
        (
            source,
            redact_url(url),
            Jsonb(redact_params(params)),
            payload.sha256 if payload else None,
            payload.size if payload else None,
            is_fixture,
        ),
    ).fetchone()
    if row is None or not isinstance(row[0], uuid.UUID):
        raise RuntimeError("INSERT INTO core.ingest_log returned no run id")
    return row[0]


def set_status(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    status: Status,
    *,
    row_count: int | None = None,
    geo_vintage: int | None = None,
    notes: str | None = None,
) -> None:
    """Advance a run one step, or mark it failed. Failed is terminal."""
    row = conn.execute(
        "SELECT status FROM core.ingest_log WHERE ingest_run_id = %s FOR UPDATE", (run_id,)
    ).fetchone()
    if row is None:
        raise StatusError(f"unknown ingest run {run_id}")
    current = row[0]
    if current == "failed":
        raise StatusError(f"run {run_id} already failed")
    if status != "failed" and _FORWARD.index(status) != _FORWARD.index(current) + 1:
        raise StatusError(f"cannot move from {current!r} to {status!r}")
    conn.execute(
        "UPDATE core.ingest_log SET status = %s, updated_at = now(), "
        "row_count = COALESCE(%s, row_count), geo_vintage = COALESCE(%s, geo_vintage), "
        "notes = NULLIF(concat_ws('; ', notes, %s::text), '') WHERE ingest_run_id = %s",
        (status, row_count, geo_vintage, notes, run_id),
    )
