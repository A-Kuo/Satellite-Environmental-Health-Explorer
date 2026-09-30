"""Parameterized fetch: download, save raw bytes, record the SHA-256."""

from __future__ import annotations

from src.connectors._template.client import build_client
from src.connectors.base import FetchedPayload
from src.connectors.raw_store import RawStore

URL = "https://example.org/synthetic/tract_values.csv"


def fetch(store: RawStore, *, fixture_mode: bool) -> list[FetchedPayload]:
    """Return one ``FetchedPayload`` per raw file. Keep credentials out of ``params``."""
    with build_client(fixture_mode=fixture_mode) as client:
        payload, _from_cache = client.fetch_to_store(store, URL, suffix=".csv", request_key=URL)
    return [FetchedPayload(payload=payload, url=URL, params={})]
