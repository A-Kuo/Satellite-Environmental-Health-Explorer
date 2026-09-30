"""Helpers for inserting valid rows and probing constraints in DB tests."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg import sql

PERIOD = ("2022-01-01", "2022-12-31")


@contextmanager
def rejected(conn: psycopg.Connection, error: type[psycopg.Error]) -> Iterator[None]:
    """Expect ``error``. The savepoint rolls back so the outer transaction stays usable."""
    status = conn.info.transaction_status
    assert status == psycopg.pq.TransactionStatus.INTRANS, (
        "rejected() needs an open outer transaction, or it would commit instead of roll back"
    )
    with pytest.raises(error), conn.transaction():
        yield


CATALOG_DEFAULTS: dict[str, Any] = {
    "indicator_key": "test.indicator",
    "domain": "health",
    "name": "Test indicator",
    "description": "A synthetic indicator used only in tests.",
    "unit": "percent",
    "direction": "higher_is_concern",
    "estimate_type": "model_based",
    "native_geo_level": "tract",
    "native_geo_vintage": 2020,
    "refresh_cadence": "annual",
    "source_name": "Synthetic",
    "source_url": "https://example.org/source",
    "license": "Public domain (synthetic)",
    "plausible_min": 0,
    "plausible_max": 100,
}


def insert(
    conn: psycopg.Connection, table: str, returning: str | None = None, **columns: Any
) -> Any:
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(*table.split(".")),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.SQL(", ").join([sql.Placeholder()] * len(columns)),
    )
    if returning:
        query = query + sql.SQL(" RETURNING {}").format(sql.Identifier(returning))
    cur = conn.execute(query, list(columns.values()))
    if returning:
        row = cur.fetchone()
        assert row is not None
        return row[0]
    return None


def geography_columns(geoid: str, level: str, vintage: int = 2020) -> dict[str, Any]:
    """Columns for a geography whose FIPS fields agree with its GEOID."""
    return {
        "geoid": geoid,
        "geo_level": level,
        "geo_vintage": vintage,
        "name": f"Test {level} {geoid}",
        "state_fips": None if level == "zcta" else geoid[:2],
        "county_fips": {"county": geoid, "tract": geoid[:5]}.get(level),
    }


def add_geography(
    conn: psycopg.Connection, geoid: str, level: str, vintage: int = 2020, **overrides: Any
) -> None:
    insert(conn, "core.geographies", **{**geography_columns(geoid, level, vintage), **overrides})


def add_run(conn: psycopg.Connection, **overrides: Any) -> uuid.UUID:
    columns: dict[str, Any] = {
        "source": "test",
        "url": "https://example.org/payload.csv",
        "status": "loaded",
    }
    run_id = insert(conn, "core.ingest_log", "ingest_run_id", **{**columns, **overrides})
    assert isinstance(run_id, uuid.UUID)
    return run_id


def add_indicator(conn: psycopg.Connection, **overrides: Any) -> int:
    indicator_id = insert(
        conn, "core.indicator_catalog", "indicator_id", **{**CATALOG_DEFAULTS, **overrides}
    )
    assert isinstance(indicator_id, int)
    return indicator_id


def value_columns(
    geoid: str, indicator_id: int, run_id: uuid.UUID, vintage: int = 2020, **overrides: Any
) -> dict[str, Any]:
    columns: dict[str, Any] = {
        "geoid": geoid,
        "geo_vintage": vintage,
        "indicator_id": indicator_id,
        "period_start": PERIOD[0],
        "period_end": PERIOD[1],
        "value": 12.5,
        "ingest_run_id": run_id,
    }
    return {**columns, **overrides}


def add_value(
    conn: psycopg.Connection,
    geoid: str,
    indicator_id: int,
    run_id: uuid.UUID,
    vintage: int = 2020,
    **overrides: Any,
) -> None:
    insert(
        conn,
        "core.indicator_values",
        **value_columns(geoid, indicator_id, run_id, vintage, **overrides),
    )
