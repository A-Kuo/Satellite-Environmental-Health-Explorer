"""Database reads and writes shared by every connector."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import date

import pandas as pd
import psycopg
from psycopg.conninfo import conninfo_to_dict

from src.connectors.catalog import CatalogEntry
from src.connectors.env import ConfigurationError, require_env
from src.connectors.gates import Coverage

_CATALOG_COLUMNS: tuple[str, ...] = (
    "indicator_key",
    "domain",
    "name",
    "description",
    "unit",
    "direction",
    "estimate_type",
    "native_geo_level",
    "native_geo_vintage",
    "refresh_cadence",
    "source_name",
    "source_url",
    "license",
    "notes",
    "plausible_min",
    "plausible_max",
)


def connect(env_var: str = "DATABASE_URL_INGEST") -> psycopg.Connection:
    """Open a direct connection from an environment variable.

    Pooled hosts are refused: connectors rely on session-level advisory locks.
    """
    conninfo = require_env(env_var)
    host = str(conninfo_to_dict(conninfo).get("host") or "")
    if "-pooler" in host:
        raise ConfigurationError(f"{env_var} points at a pooled host; use the direct connection")
    return psycopg.connect(conninfo)


def upsert_catalog(conn: psycopg.Connection, entries: Sequence[CatalogEntry]) -> dict[str, int]:
    """Insert or update catalog entries; return ``indicator_key -> indicator_id``."""
    columns = ", ".join(_CATALOG_COLUMNS)
    placeholders = ", ".join(["%s"] * len(_CATALOG_COLUMNS))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _CATALOG_COLUMNS[1:])
    query = (
        f"INSERT INTO core.indicator_catalog ({columns}) VALUES ({placeholders}) "  # noqa: S608
        f"ON CONFLICT (indicator_key) DO UPDATE SET {updates} "
        "RETURNING indicator_key, indicator_id"
    )
    ids: dict[str, int] = {}
    for entry in entries:
        data = entry.model_dump()
        row = conn.execute(query, [data[c] for c in _CATALOG_COLUMNS]).fetchone()
        if row is None:
            raise RuntimeError(f"catalog upsert for {entry.indicator_key!r} returned no row")
        ids[row[0]] = row[1]
    return ids


def known_geography_pairs(
    conn: psycopg.Connection, level: str, vintages: Collection[int]
) -> set[tuple[str, int]]:
    rows = conn.execute(
        "SELECT geoid, geo_vintage FROM core.geographies "
        "WHERE geo_level = %s AND geo_vintage = ANY(%s)",
        (level, list(vintages)),
    ).fetchall()
    return {(geoid, int(vintage)) for geoid, vintage in rows}


def geography_universe(conn: psycopg.Connection, level: str, vintage: int) -> pd.DataFrame:
    """Every loaded geography of a level and vintage with a state, for coverage."""
    rows = conn.execute(
        "SELECT geoid, state_fips FROM core.geographies "
        "WHERE geo_level = %s AND geo_vintage = %s AND state_fips IS NOT NULL",
        (level, vintage),
    ).fetchall()
    return pd.DataFrame(rows, columns=["geoid", "state_fips"])


def prior_coverage(
    conn: psycopg.Connection,
    indicator_ids: Mapping[str, int],
    current_period_end: Mapping[str, date],
    level: str,
    vintage: int,
) -> Coverage:
    """Per-state coverage of the most recent earlier period of each indicator."""
    prior: dict[tuple[str, str], float] = {}
    for key, indicator_id in indicator_ids.items():
        if key not in current_period_end:
            continue
        rows = conn.execute(
            """
            WITH prev AS (
                SELECT max(period_end) AS pe FROM core.indicator_values
                WHERE indicator_id = %(ind)s AND geo_vintage = %(vin)s AND period_end < %(cur)s
            )
            SELECT g.state_fips, count(v.value)::float / count(*)
            FROM core.geographies g
            LEFT JOIN core.indicator_values v
                   ON v.geoid = g.geoid AND v.geo_vintage = g.geo_vintage
                  AND v.indicator_id = %(ind)s AND v.period_end = (SELECT pe FROM prev)
            WHERE g.geo_level = %(lvl)s AND g.geo_vintage = %(vin)s AND g.state_fips IS NOT NULL
              AND (SELECT pe FROM prev) IS NOT NULL
            GROUP BY g.state_fips
            """,
            {
                "ind": indicator_id,
                "vin": vintage,
                "cur": current_period_end[key],
                "lvl": level,
            },
        ).fetchall()
        for state, share in rows:
            prior[(key, str(state))] = float(share)
    return prior


def upsert_indicator_values(
    conn: psycopg.Connection,
    df: pd.DataFrame,
    indicator_ids: Mapping[str, int],
    run_id: uuid.UUID,
) -> int:
    """Idempotent load: stage with COPY, then upsert on the natural key.

    A row is written only when it is new or one of its value fields changed, so
    re-running a connector on an unchanged release changes nothing. Returns the
    number of rows inserted or updated. Provenance (``ingest_run_id``) therefore
    points at the payload that last changed the value.
    """
    unknown = sorted(set(df["indicator_key"]) - set(indicator_ids))
    if unknown:
        raise KeyError(f"indicators missing from the catalog: {unknown}")

    def numbers(column: str) -> list[float | None]:
        return [None if pd.isna(v) else float(v) for v in df[column].tolist()]

    columns = (
        df["geoid"].astype(str).tolist(),
        [int(v) for v in df["geo_vintage"].tolist()],
        [indicator_ids[k] for k in df["indicator_key"].tolist()],
        pd.to_datetime(df["period_start"]).dt.date.tolist(),
        pd.to_datetime(df["period_end"]).dt.date.tolist(),
        numbers("value"),
        numbers("moe_or_ci_low"),
        numbers("moe_or_ci_high"),
        df["coverage_flag"].astype(str).tolist(),
        [run_id] * len(df),
    )
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE _stage_values "
            "(LIKE core.indicator_values INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        with cur.copy(
            "COPY _stage_values (geoid, geo_vintage, indicator_id, period_start, period_end, "
            "value, moe_or_ci_low, moe_or_ci_high, coverage_flag, ingest_run_id) FROM STDIN"
        ) as copy:
            for row in zip(*columns, strict=True):
                copy.write_row(row)
        cur.execute(
            """
            INSERT INTO core.indicator_values AS t
                (geoid, geo_vintage, indicator_id, period_start, period_end,
                 value, moe_or_ci_low, moe_or_ci_high, coverage_flag, ingest_run_id)
            SELECT geoid, geo_vintage, indicator_id, period_start, period_end,
                   value, moe_or_ci_low, moe_or_ci_high, coverage_flag, ingest_run_id
            FROM _stage_values
            ON CONFLICT (geoid, geo_vintage, indicator_id, period_start, period_end)
            DO UPDATE SET value = EXCLUDED.value,
                          moe_or_ci_low = EXCLUDED.moe_or_ci_low,
                          moe_or_ci_high = EXCLUDED.moe_or_ci_high,
                          coverage_flag = EXCLUDED.coverage_flag,
                          ingest_run_id = EXCLUDED.ingest_run_id
            WHERE (t.value, t.moe_or_ci_low, t.moe_or_ci_high, t.coverage_flag)
                  IS DISTINCT FROM
                  (EXCLUDED.value, EXCLUDED.moe_or_ci_low, EXCLUDED.moe_or_ci_high,
                   EXCLUDED.coverage_flag)
            """
        )
        return cur.rowcount
