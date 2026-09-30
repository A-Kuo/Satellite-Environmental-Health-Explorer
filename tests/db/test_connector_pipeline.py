"""The connector contract end to end: fetch, register, clean, validate, load, publish.

Runs the template connector in fixture mode against a real PostGIS database. It
proves the framework behaves: idempotent, all-or-nothing, loud on bad data, and
careful with credentials. It says nothing about any real data source.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
import pytest

from src.connectors import warehouse
from src.connectors._template import TemplateConnector
from src.connectors.base import FetchedPayload
from src.connectors.catalog import load_catalog
from src.connectors.env import ConfigurationError
from src.connectors.gates import GateFailure
from src.connectors.ingest_log import StatusError, register_payload, set_status
from src.connectors.lock import SourceBusy, source_lock
from src.connectors.raw_store import RawStore, sha256_file

pytestmark = pytest.mark.db

CANARY = "canary-not-a-real-credential"
VALUE_COLUMNS = ["value", "moe_or_ci_low", "moe_or_ci_high"]


def connector_for(
    tmp_path: Path, cls: type[TemplateConnector] = TemplateConnector, **kw: Any
) -> TemplateConnector:
    return cls(store=RawStore(tmp_path / "raw"), fixture_mode=True, **kw)


def rows(conn: psycopg.Connection, sql_text: str) -> list[tuple[Any, ...]]:
    return conn.execute(sql_text).fetchall()  # type: ignore[arg-type]


def value_rows(conn: psycopg.Connection) -> dict[str, tuple[Any, ...]]:
    result = conn.execute(
        "SELECT geoid, value, moe_or_ci_low, coverage_flag, ingest_run_id "
        "FROM core.indicator_values ORDER BY geoid"
    )
    return {r[0]: r[1:] for r in result.fetchall()}


def log_rows(conn: psycopg.Connection) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT status, is_fixture, row_count, geo_vintage, notes, url, params::text "
        "FROM core.ingest_log ORDER BY fetched_at, ingest_run_id"
    ).fetchall()


# --- the happy path -------------------------------------------------------------


def test_a_run_loads_cleaned_values_and_records_provenance(
    pg: psycopg.Connection, tmp_path: Path
) -> None:
    connector = connector_for(tmp_path)
    report = connector.run(pg)
    assert (report.rows_seen, report.rows_changed, len(report.run_ids)) == (7, 7, 1)

    loaded = value_rows(pg)
    assert len(loaded) == 7
    assert loaded["01001020100"][0] == 21.4  # leading zero repaired: matched an Alabama tract
    assert "55079000400" in loaded  # "55079000400.0" float artifact repaired
    # The -999 sentinel became a gap that says why, with its interval cleared too.
    assert loaded["55079000300"][:3] == (None, None, "no_data")
    assert {v[2] for k, v in loaded.items() if k != "55079000300"} == {"ok"}

    (status, is_fixture, row_count, vintage, notes, url, params) = log_rows(pg)[0]
    assert (status, is_fixture, row_count, vintage) == ("published", True, 7, 2020)
    assert "sentinels_to_null={'value': 1, 'moe_or_ci_low': 1, 'moe_or_ci_high': 1}" in notes
    assert "rows_changed=7" in notes
    assert url == "https://example.org/synthetic/tract_values.csv" and params == "{}"

    sha = pg.execute("SELECT sha256 FROM core.ingest_log").fetchone()
    stored = next((tmp_path / "raw" / "template_demo").glob("*.csv"))
    assert sha == (sha256_file(stored),)  # the log row matches the immutable raw file


def test_values_point_at_the_run_that_loaded_them(pg: psycopg.Connection, tmp_path: Path) -> None:
    report = connector_for(tmp_path).run(pg)
    assert {v[3] for v in value_rows(pg).values()} == {report.run_ids[0]}


# --- idempotency ----------------------------------------------------------------


def test_running_twice_changes_nothing_the_second_time(
    pg: psycopg.Connection, tmp_path: Path
) -> None:
    first = connector_for(tmp_path).run(pg)
    catalog_ids = rows(pg, "SELECT indicator_id FROM core.indicator_catalog")
    second = connector_for(tmp_path).run(pg)

    assert second.rows_seen == 7 and second.rows_changed == 0
    assert len(value_rows(pg)) == 7  # no duplicates
    assert {v[3] for v in value_rows(pg).values()} == {first.run_ids[0]}  # provenance untouched
    assert rows(pg, "SELECT indicator_id FROM core.indicator_catalog") == catalog_ids
    assert [r[0] for r in log_rows(pg)] == ["published", "published"]
    assert "rows_changed=0" in log_rows(pg)[1][4]


class Revised(TemplateConnector):
    """A later release in which one tract's value is corrected."""

    def clean(self, fetched: FetchedPayload) -> pd.DataFrame:
        df = super().clean(fetched)
        df.loc[df["geoid"] == "27053000100", "value"] = 11.9
        return df


def test_a_revised_value_updates_only_that_row(pg: psycopg.Connection, tmp_path: Path) -> None:
    first = connector_for(tmp_path).run(pg)
    second = connector_for(tmp_path, Revised).run(pg)
    assert second.rows_changed == 1
    loaded = value_rows(pg)
    assert loaded["27053000100"][0] == 11.9
    assert loaded["27053000100"][3] == second.run_ids[0]  # provenance follows the change
    assert {v[3] for k, v in loaded.items() if k != "27053000100"} == {first.run_ids[0]}


# --- loud, all-or-nothing failure ------------------------------------------------


class Broken(TemplateConnector):
    """Out-of-range value, an unknown geography, and a value outside its own interval."""

    def clean(self, fetched: FetchedPayload) -> pd.DataFrame:
        df = super().clean(fetched)
        df.loc[0, "value"] = 150.0
        stray = df.iloc[[1]].assign(geoid="99999999999")
        return pd.concat([df, stray], ignore_index=True)


def test_every_failed_gate_is_reported_at_once_and_nothing_is_loaded(
    pg: psycopg.Connection, tmp_path: Path
) -> None:
    with pytest.raises(GateFailure) as raised:
        connector_for(tmp_path, Broken).run(pg)
    message = str(raised.value)
    for gate in ("plausible_range", "state_prefix", "geographies_present", "value_within_interval"):
        assert gate in message

    assert value_rows(pg) == {}  # all or nothing
    (status, _, _, _, notes, _, _) = log_rows(pg)[0]
    assert status == "failed" and "GateFailure" in notes and "plausible_range" in notes


class Unreadable(TemplateConnector):
    def clean(self, fetched: FetchedPayload) -> pd.DataFrame:
        raise RuntimeError("the file is not the format we expected")


def test_a_payload_that_cannot_be_cleaned_still_leaves_a_failed_provenance_row(
    pg: psycopg.Connection, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError, match="not the format"):
        connector_for(tmp_path, Unreadable).run(pg)
    ((status, _, _, _, notes, _, _),) = log_rows(pg)
    assert status == "failed" and "not the format we expected" in notes
    assert list((tmp_path / "raw" / "template_demo").glob("*.csv"))  # raw bytes were kept


# --- coverage against the prior release -----------------------------------------


class Year2021(TemplateConnector):
    def clean(self, fetched: FetchedPayload) -> pd.DataFrame:
        df = super().clean(fetched)
        df["period_start"] = pd.Timestamp("2021-01-01")
        df["period_end"] = pd.Timestamp("2021-12-31")
        return df


class AlabamaSuppressed(TemplateConnector):
    """A release in which the source drops every Alabama tract."""

    def clean(self, fetched: FetchedPayload) -> pd.DataFrame:
        df = super().clean(fetched)
        alabama = df["geoid"].str.startswith("01")
        df.loc[alabama, VALUE_COLUMNS] = float("nan")
        df.loc[alabama, "coverage_flag"] = "suppressed"
        return df


def test_a_sharp_coverage_drop_fails_unless_an_override_is_recorded(
    pg: psycopg.Connection, tmp_path: Path
) -> None:
    connector_for(tmp_path, Year2021).run(pg)

    with pytest.raises(GateFailure, match=r"coverage_not_dropped.*state 01"):
        connector_for(tmp_path, AlabamaSuppressed).run(pg)
    assert rows(
        pg, "SELECT count(*) FROM core.indicator_values WHERE period_end = '2022-12-31'"
    ) == [(0,)]

    note = "source suppressed Alabama for 2022 (documented in its release notes)"
    connector_for(tmp_path, AlabamaSuppressed, coverage_override_note=note).run(pg)
    assert rows(
        pg, "SELECT count(*) FROM core.indicator_values WHERE period_end = '2022-12-31'"
    ) == [(7,)]
    overrides = [r for r in log_rows(pg) if r[4] and "overridden" in r[4]]
    assert overrides and note in overrides[0][4]  # the exception is in the provenance record


# --- safety guards --------------------------------------------------------------


def test_fixture_mode_is_refused_in_prod(
    pg: psycopg.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    with pytest.raises(ConfigurationError, match="never run against prod"):
        connector_for(tmp_path).run(pg)
    assert log_rows(pg) == [] and value_rows(pg) == {}


def test_only_one_worker_may_run_a_source_at_a_time(pipeline_db: str, tmp_path: Path) -> None:
    with psycopg.connect(pipeline_db) as holder, psycopg.connect(pipeline_db) as other:
        with source_lock(holder, "template_demo"):
            with pytest.raises(SourceBusy, match="template_demo"):
                connector_for(tmp_path).run(other)
            assert log_rows(other) == []  # the refused run wrote nothing
        connector_for(tmp_path).run(other)  # released: now it may run
        assert len(value_rows(other)) == 7


class LeakyRequest(TemplateConnector):
    """A source whose request carries an API key in both the URL and the parameters."""

    def fetch(self) -> list[FetchedPayload]:
        (fetched,) = super().fetch()
        return [
            FetchedPayload(
                payload=fetched.payload,
                url=f"{fetched.url}?get=x&key={CANARY}",
                params={"get": "x", "key": CANARY},
            )
        ]


class LeakyFailure(LeakyRequest):
    def clean(self, fetched: FetchedPayload) -> pd.DataFrame:
        raise RuntimeError(f"request failed: {fetched.url}")


def test_credentials_never_reach_the_ingest_log(pg: psycopg.Connection, tmp_path: Path) -> None:
    connector_for(tmp_path, LeakyRequest).run(pg)
    with pytest.raises(RuntimeError):
        connector_for(tmp_path, LeakyFailure).run(pg)

    log = log_rows(pg)
    assert len(log) == 2
    for row in log:
        assert CANARY not in " ".join(str(part) for part in row)
    assert "key=REDACTED" in log[0][5] and '"REDACTED"' in log[0][6]
    assert log[1][0] == "failed" and "key=REDACTED" in log[1][4]  # the error text is redacted too


# --- building blocks ------------------------------------------------------------


def test_run_status_only_moves_forward_and_failed_is_terminal(pg: psycopg.Connection) -> None:
    run_id = register_payload(
        pg, source="demo", url="https://example.org/x", params={}, payload=None, is_fixture=True
    )
    with pytest.raises(StatusError, match="cannot move from 'fetched' to 'validated'"):
        set_status(pg, run_id, "validated")
    set_status(pg, run_id, "cleaned", row_count=3, geo_vintage=2020)
    set_status(pg, run_id, "failed", notes="boom")
    with pytest.raises(StatusError, match="already failed"):
        set_status(pg, run_id, "validated")
    with pytest.raises(StatusError, match="unknown ingest run"):
        set_status(pg, uuid.uuid4(), "cleaned")


def test_notes_accumulate_across_statuses(pg: psycopg.Connection) -> None:
    run_id = register_payload(
        pg, source="demo", url="https://example.org/x", params={}, payload=None, is_fixture=True
    )
    set_status(pg, run_id, "cleaned", notes="first")
    set_status(pg, run_id, "validated")
    set_status(pg, run_id, "loaded", notes="second")
    assert pg.execute("SELECT notes FROM core.ingest_log").fetchone() == ("first; second",)


def test_catalog_upsert_is_stable_and_updates_in_place(pg: psycopg.Connection) -> None:
    (entry,) = load_catalog(TemplateConnector.catalog_path)
    first = warehouse.upsert_catalog(pg, [entry])
    again = warehouse.upsert_catalog(pg, [entry.model_copy(update={"notes": "edited"})])
    assert first == again  # the id is stable across updates
    assert pg.execute("SELECT count(*), max(notes) FROM core.indicator_catalog").fetchone() == (
        1,
        "edited",
    )


def test_loading_an_indicator_that_is_not_in_the_catalog_is_an_error(
    pg: psycopg.Connection,
) -> None:
    df = pd.DataFrame({"indicator_key": ["nope.missing"]})
    with pytest.raises(KeyError, match="missing from the catalog"):
        warehouse.upsert_indicator_values(pg, df, {}, uuid.uuid4())
