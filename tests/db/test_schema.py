"""Schema invariants enforced by the database itself (migration 001)."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from dbtools import (
    PERIOD,
    add_geography,
    add_indicator,
    add_run,
    add_value,
    geography_columns,
    insert,
    rejected,
    value_columns,
)

pytestmark = pytest.mark.db

SQUARE = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_extensions_schemas_and_tables_exist(conn: psycopg.Connection) -> None:
    extensions = {r[0] for r in conn.execute("SELECT extname FROM pg_extension")}
    assert {"postgis", "pg_trgm"} <= extensions

    schemas = {r[0] for r in conn.execute("SELECT nspname FROM pg_namespace")}
    assert {"raw", "core", "marts", "research"} <= schemas

    tables = {
        r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'core'")
    }
    assert tables == {
        "geographies",
        "indicator_catalog",
        "indicator_values",
        "indicator_percentiles",
        "ingest_log",
    }


def test_required_indexes_exist(conn: psycopg.Connection) -> None:
    definitions = " ".join(
        r[0] for r in conn.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = 'core'")
    )
    assert "USING gist (geom)" in definitions
    assert "USING gin (name gin_trgm_ops)" in definitions
    assert "(indicator_id, geo_vintage, period_end)" in definitions
    # The natural key leads with geoid, so it also serves geoid lookups.
    assert "(geoid, geo_vintage, indicator_id, period_start, period_end)" in definitions


def test_geometry_column_declares_one_srid(conn: psycopg.Connection) -> None:
    row = conn.execute(
        "SELECT srid, type FROM geometry_columns "
        "WHERE f_table_schema = 'core' AND f_table_name = 'geographies'"
    ).fetchone()
    assert row == (4269, "MULTIPOLYGON")


# ---------------------------------------------------------------------------
# core.geographies
# ---------------------------------------------------------------------------


def test_valid_geographies_at_every_level_are_accepted(conn: psycopg.Connection) -> None:
    add_geography(conn, "55", "state")
    add_geography(conn, "55079", "county")
    add_geography(conn, "55079000100", "tract")
    add_geography(conn, "53706", "zcta")


BAD_GEOGRAPHIES = [
    pytest.param(("5507900010", "tract"), {}, id="tract_geoid_too_short"),
    pytest.param(("5507", "county"), {}, id="county_geoid_too_short"),
    pytest.param(("5", "state"), {}, id="state_geoid_too_short"),
    pytest.param(("55079000100", "tract"), {"county_fips": "55080"}, id="tract_wrong_county"),
    pytest.param(("55079000100", "tract"), {"state_fips": "56"}, id="tract_wrong_state"),
    pytest.param(("55079", "county"), {"county_fips": "55080"}, id="county_fips_disagrees"),
    pytest.param(("55", "state"), {"county_fips": "55079"}, id="state_with_county"),
    pytest.param(("53706", "zcta"), {"state_fips": "53"}, id="zcta_with_state"),
    pytest.param(("5507900010a", "tract"), {}, id="non_numeric_geoid"),
]


@pytest.mark.parametrize(("key", "overrides"), BAD_GEOGRAPHIES)
def test_malformed_or_inconsistent_geographies_are_rejected(
    conn: psycopg.Connection, key: tuple[str, str], overrides: dict[str, Any]
) -> None:
    geoid, level = key
    columns = {**geography_columns(geoid, level), **overrides}
    with rejected(conn, psycopg.errors.CheckViolation):
        insert(conn, "core.geographies", **columns)


def test_unknown_level_and_implausible_vintage_are_rejected(conn: psycopg.Connection) -> None:
    with rejected(conn, psycopg.errors.CheckViolation):
        add_geography(conn, "55", "province")
    with rejected(conn, psycopg.errors.CheckViolation):
        add_geography(conn, "55", "state", vintage=1)


def test_same_geoid_in_two_vintages_is_two_geographies(conn: psycopg.Connection) -> None:
    add_geography(conn, "55079000100", "tract", vintage=2010)
    add_geography(conn, "55079000100", "tract", vintage=2020)
    with rejected(conn, psycopg.errors.UniqueViolation):
        add_geography(conn, "55079000100", "tract", vintage=2020)


INSERT_MULTIPOLYGON = (
    "INSERT INTO core.geographies (geoid, geo_level, geo_vintage, name, state_fips, geom) "
    "VALUES (%s, 'state', 2020, 'Test', %s, ST_Multi(ST_GeomFromText(%s, %s)))"
)
INSERT_RAW_GEOM = (
    "INSERT INTO core.geographies (geoid, geo_level, geo_vintage, name, state_fips, geom) "
    "VALUES (%s, 'state', 2020, 'Test', %s, ST_GeomFromText(%s, %s))"
)


def test_geometry_must_match_the_declared_srid_and_type(conn: psycopg.Connection) -> None:
    conn.execute(INSERT_MULTIPOLYGON, ("55", "55", SQUARE, 4269))  # declared SRID and type
    with rejected(conn, psycopg.Error):  # wrong SRID
        conn.execute(INSERT_MULTIPOLYGON, ("56", "56", SQUARE, 4326))
    with rejected(conn, psycopg.Error):  # a point is not a polygon
        conn.execute(INSERT_RAW_GEOM, ("57", "57", "POINT(0 0)", 4269))


def test_a_plain_polygon_is_promoted_to_a_multipolygon(conn: psycopg.Connection) -> None:
    """PostGIS promotes single to multi on insert, so loaders may pass either."""
    conn.execute(INSERT_RAW_GEOM, ("55", "55", SQUARE, 4269))
    row = conn.execute("SELECT GeometryType(geom) FROM core.geographies WHERE geoid = '55'")
    assert row.fetchone() == ("MULTIPOLYGON",)


# ---------------------------------------------------------------------------
# core.indicator_catalog
# ---------------------------------------------------------------------------


def test_valid_catalog_entry_gets_a_compact_integer_id(conn: psycopg.Connection) -> None:
    first = add_indicator(conn, indicator_key="places.a")
    second = add_indicator(conn, indicator_key="places.b")
    assert second == first + 1


BAD_CATALOG = [
    pytest.param({"plausible_min": 10, "plausible_max": 1}, id="min_above_max"),
    pytest.param({"license": "   "}, id="blank_license"),
    pytest.param({"source_url": "ftp://example.org/x"}, id="source_url_not_http"),
    pytest.param({"direction": "worst_first"}, id="unknown_direction"),
    pytest.param({"domain": "vibes"}, id="unknown_domain"),
    pytest.param({"estimate_type": "measured"}, id="unknown_estimate_type"),
    pytest.param({"refresh_cadence": "whenever"}, id="unknown_cadence"),
    pytest.param({"indicator_key": "Has Spaces"}, id="bad_key_format"),
    pytest.param({"indicator_key": "composite.risk_score"}, id="composite_risk_score"),
    pytest.param({"indicator_key": "composite.priority_score"}, id="composite_priority_score"),
    pytest.param({"indicator_key": "x.harm_score"}, id="composite_harm_score"),
    pytest.param({"indicator_key": "x.inequality_score"}, id="composite_inequality_score"),
]


@pytest.mark.parametrize("overrides", BAD_CATALOG)
def test_invalid_catalog_entries_are_rejected(
    conn: psycopg.Connection, overrides: dict[str, Any]
) -> None:
    with rejected(conn, psycopg.errors.CheckViolation):
        add_indicator(conn, **overrides)


def test_catalog_keys_are_unique(conn: psycopg.Connection) -> None:
    add_indicator(conn, indicator_key="places.a")
    with rejected(conn, psycopg.errors.UniqueViolation):
        add_indicator(conn, indicator_key="places.a")


# ---------------------------------------------------------------------------
# core.ingest_log
# ---------------------------------------------------------------------------


def test_ingest_log_defaults_and_status_lifecycle(conn: psycopg.Connection) -> None:
    run_id = add_run(conn, status="fetched")
    row = conn.execute(
        "SELECT params, is_fixture, sha256 FROM core.ingest_log WHERE ingest_run_id = %s",
        (run_id,),
    ).fetchone()
    assert row == ({}, False, None)
    for status in ("cleaned", "validated", "loaded", "published", "failed"):
        conn.execute(
            "UPDATE core.ingest_log SET status = %s WHERE ingest_run_id = %s", (status, run_id)
        )


BAD_RUNS = [
    pytest.param({"status": "done"}, id="unknown_status"),
    pytest.param({"sha256": "abc123"}, id="short_sha256"),
    pytest.param({"sha256": "G" * 64}, id="non_hex_sha256"),
    pytest.param({"row_count": -1}, id="negative_row_count"),
    pytest.param({"source": ""}, id="empty_source"),
]


@pytest.mark.parametrize("overrides", BAD_RUNS)
def test_invalid_ingest_log_rows_are_rejected(
    conn: psycopg.Connection, overrides: dict[str, Any]
) -> None:
    with rejected(conn, psycopg.errors.CheckViolation):
        add_run(conn, **overrides)


# ---------------------------------------------------------------------------
# core.indicator_values
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(conn: psycopg.Connection) -> dict[str, Any]:
    add_geography(conn, "55", "state")
    add_geography(conn, "55079000100", "tract")
    return {"indicator_id": add_indicator(conn), "run_id": add_run(conn)}


def test_a_value_loads_and_the_natural_key_blocks_duplicates(
    conn: psycopg.Connection, seeded: dict[str, Any]
) -> None:
    add_value(conn, "55079000100", seeded["indicator_id"], seeded["run_id"])
    with rejected(conn, psycopg.errors.UniqueViolation):
        add_value(conn, "55079000100", seeded["indicator_id"], seeded["run_id"], value=99)


def test_a_different_period_is_a_different_value(
    conn: psycopg.Connection, seeded: dict[str, Any]
) -> None:
    add_value(conn, "55079000100", seeded["indicator_id"], seeded["run_id"])
    add_value(
        conn,
        "55079000100",
        seeded["indicator_id"],
        seeded["run_id"],
        period_start="2023-01-01",
        period_end="2023-12-31",
    )


def test_a_value_needs_its_geography_vintage_to_exist(
    conn: psycopg.Connection, seeded: dict[str, Any]
) -> None:
    # Only the 2020 vintage of this tract is loaded.
    with rejected(conn, psycopg.errors.ForeignKeyViolation):
        add_value(conn, "55079000100", seeded["indicator_id"], seeded["run_id"], vintage=2010)


def test_a_value_needs_a_known_indicator_and_a_provenance_row(
    conn: psycopg.Connection, seeded: dict[str, Any]
) -> None:
    with rejected(conn, psycopg.errors.ForeignKeyViolation):
        add_value(conn, "55079000100", 32000, seeded["run_id"])
    with rejected(conn, psycopg.errors.ForeignKeyViolation):
        add_value(
            conn,
            "55079000100",
            seeded["indicator_id"],
            "00000000-0000-0000-0000-000000000000",
        )


BAD_VALUES = [
    pytest.param({"value": None}, id="ok_row_without_value"),
    pytest.param({"period_start": PERIOD[1], "period_end": PERIOD[0]}, id="period_reversed"),
    pytest.param({"moe_or_ci_low": 9, "moe_or_ci_high": 3}, id="interval_reversed"),
    pytest.param({"coverage_flag": "mostly"}, id="unknown_coverage_flag"),
]


@pytest.mark.parametrize("overrides", BAD_VALUES)
def test_invalid_values_are_rejected(
    conn: psycopg.Connection, seeded: dict[str, Any], overrides: dict[str, Any]
) -> None:
    with rejected(conn, psycopg.errors.CheckViolation):
        add_value(conn, "55079000100", seeded["indicator_id"], seeded["run_id"], **overrides)


def test_a_missing_value_is_allowed_when_it_says_why(
    conn: psycopg.Connection, seeded: dict[str, Any]
) -> None:
    add_value(
        conn,
        "55079000100",
        seeded["indicator_id"],
        seeded["run_id"],
        value=None,
        coverage_flag="suppressed",
    )


# ---------------------------------------------------------------------------
# core.indicator_percentiles
# ---------------------------------------------------------------------------


def percentile_columns(
    seeded: dict[str, Any], frame: str = "national", **overrides: Any
) -> dict[str, Any]:
    base = value_columns("55079000100", seeded["indicator_id"], seeded["run_id"])
    del base["value"]
    columns = {
        **base,
        "reference_frame": frame,
        "percentile": 0.8,
        "concern_percentile": 0.8,
        "n_in_frame": 84000,
    }
    return {**columns, **overrides}


def test_one_value_can_carry_a_percentile_in_each_frame(
    conn: psycopg.Connection, seeded: dict[str, Any]
) -> None:
    """The reason percentiles are a separate table: frames must not share a row."""
    add_value(conn, "55079000100", seeded["indicator_id"], seeded["run_id"])
    insert(conn, "core.indicator_percentiles", **percentile_columns(seeded, "national"))
    insert(conn, "core.indicator_percentiles", **percentile_columns(seeded, "state"))
    insert(
        conn,
        "core.indicator_percentiles",
        **percentile_columns(seeded, "peer_group", peer_group="rural_wi"),
    )
    count = conn.execute("SELECT count(*) FROM core.indicator_values").fetchone()
    assert count == (1,)  # the raw value is stored once


def test_a_percentile_needs_its_value_row(conn: psycopg.Connection, seeded: dict[str, Any]) -> None:
    with rejected(conn, psycopg.errors.ForeignKeyViolation):
        insert(conn, "core.indicator_percentiles", **percentile_columns(seeded))


BAD_PERCENTILES = [
    pytest.param({"frame": "peer_group"}, id="peer_group_frame_without_group"),
    pytest.param({"peer_group": "rural_wi"}, id="group_on_non_peer_frame"),
    pytest.param({"percentile": 1.2}, id="percentile_above_one"),
    pytest.param({"concern_percentile": -0.1}, id="concern_below_zero"),
    pytest.param({"n_in_frame": 0}, id="empty_frame"),
    pytest.param({"frame": "regional"}, id="unknown_frame"),
]


@pytest.mark.parametrize("overrides", BAD_PERCENTILES)
def test_invalid_percentiles_are_rejected(
    conn: psycopg.Connection, seeded: dict[str, Any], overrides: dict[str, Any]
) -> None:
    add_value(conn, "55079000100", seeded["indicator_id"], seeded["run_id"])
    fields = dict(overrides)  # do not mutate the shared parametrize value
    frame = fields.pop("frame", "national")
    with rejected(conn, psycopg.errors.CheckViolation):
        insert(conn, "core.indicator_percentiles", **percentile_columns(seeded, frame, **fields))


def test_neutral_indicators_may_have_no_concern_percentile(
    conn: psycopg.Connection, seeded: dict[str, Any]
) -> None:
    add_value(conn, "55079000100", seeded["indicator_id"], seeded["run_id"])
    insert(
        conn,
        "core.indicator_percentiles",
        **percentile_columns(seeded, concern_percentile=None),
    )
