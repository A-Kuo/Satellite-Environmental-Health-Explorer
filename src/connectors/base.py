"""The connector contract: every source runs the same six stages.

    fetch()     download or call the API; raw bytes are saved, immutable
    register()  write the core.ingest_log row (URL, params, SHA-256, size)
    clean()     normalize to the long-format value schema (gates.VALUE_COLUMNS)
    validate()  run the gates; fail loudly, listing every failure
    load()      idempotent upsert into core tables
    publish()   refresh marts (a hook; a no-op until a mart exists)

A concrete connector implements ``fetch``, ``clean`` and optionally
``validate_domain`` and ``publish``. Everything else (provenance, gates, the
upsert, status tracking, the single-worker lock, the fixture-mode guard) is
here, so a new source cannot skip a stage.
"""

from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
import psycopg

from src.connectors import gates, ingest_log, warehouse
from src.connectors.catalog import CatalogEntry, by_key, load_catalog
from src.connectors.env import ConfigurationError
from src.connectors.lock import source_lock
from src.connectors.raw_store import RawPayload, RawStore


@dataclass(frozen=True)
class FetchedPayload:
    """A saved raw payload and the request that produced it (credentials excluded)."""

    payload: RawPayload
    url: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunReport:
    source: str
    run_ids: tuple[uuid.UUID, ...]
    rows_seen: int
    rows_changed: int


class Connector(ABC):
    source: ClassVar[str]
    geo_level: ClassVar[str]
    catalog_path: ClassVar[Path]
    sentinels: ClassVar[tuple[float, ...]] = ()
    allow_multiple_periods: ClassVar[bool] = False

    def __init__(
        self,
        *,
        store: RawStore,
        fixture_mode: bool = False,
        coverage_override_note: str | None = None,
    ) -> None:
        self.store = store
        self.fixture_mode = fixture_mode
        self.coverage_override_note = coverage_override_note

    # -- stages a source implements ---------------------------------------------

    @abstractmethod
    def fetch(self) -> list[FetchedPayload]:
        """Download into the raw store. Must honor ``fixture_mode`` (no network)."""

    @abstractmethod
    def clean(self, fetched: FetchedPayload) -> pd.DataFrame:
        """Return a frame with exactly ``gates.VALUE_COLUMNS``."""

    def validate_domain(
        self, df: pd.DataFrame, catalog: dict[str, CatalogEntry]
    ) -> list[gates.GateResult]:
        """Source-specific gates, run after the shared ones."""
        return []

    def publish(self, conn: psycopg.Connection) -> None:  # noqa: B027 - optional hook
        """Refresh marts. A no-op until the first mart exists."""

    # -- shared stages ----------------------------------------------------------

    def register(self, conn: psycopg.Connection, fetched: FetchedPayload) -> uuid.UUID:
        """Write the provenance row. The vintage is filled in once the data is cleaned."""
        return ingest_log.register_payload(
            conn,
            source=self.source,
            url=fetched.url,
            params=fetched.params,
            payload=fetched.payload,
            is_fixture=self.fixture_mode,
        )

    def validate(
        self,
        conn: psycopg.Connection,
        df: pd.DataFrame,
        catalog: dict[str, CatalogEntry],
        indicator_ids: dict[str, int],
    ) -> list[gates.GateResult]:
        # Structural gates first: later gates assume the columns exist.
        results = gates.enforce(
            [
                gates.gate_not_empty(df),
                gates.gate_required_columns(df),
                gates.gate_no_forbidden_columns(df.columns),
            ]
        )
        vintages = {int(v) for v in pd.to_numeric(df["geo_vintage"]).dropna().unique()}
        known = warehouse.known_geography_pairs(conn, self.geo_level, vintages)
        results += [
            gates.gate_geoid_format(df, self.geo_level),
            gates.gate_state_prefix(df, self.geo_level),
            gates.gate_no_duplicates(df),
            gates.gate_vintage_recorded(df, {v for _, v in known}),
            gates.gate_geographies_present(df, known),
            gates.gate_plausible_range(df, catalog),
            gates.gate_sentinels_gone(df, self.sentinels),
            gates.gate_flags_consistent(df),
            gates.gate_periods(df, self.allow_multiple_periods),
            gates.gate_catalog_metadata(df, catalog),
            self._coverage_gate(conn, df, indicator_ids, vintages),
        ]
        results += self.validate_domain(df, catalog)
        return gates.enforce(results)

    def _coverage_gate(
        self,
        conn: psycopg.Connection,
        df: pd.DataFrame,
        indicator_ids: dict[str, int],
        vintages: set[int],
    ) -> gates.GateResult:
        if len(vintages) != 1:
            return gates.GateResult("coverage_not_dropped", True, "several vintages: not compared")
        (vintage,) = vintages
        universe = warehouse.geography_universe(conn, self.geo_level, vintage)
        current = gates.coverage_by_state(df, universe)
        ends = pd.to_datetime(df["period_end"]).groupby(df["indicator_key"]).min()
        prior = warehouse.prior_coverage(
            conn,
            indicator_ids,
            {str(k): v.date() for k, v in ends.items()},
            self.geo_level,
            vintage,
        )
        return gates.gate_coverage_not_dropped(
            current, prior, override_note=self.coverage_override_note
        )

    def load(
        self,
        conn: psycopg.Connection,
        df: pd.DataFrame,
        indicator_ids: dict[str, int],
        run_id: uuid.UUID,
    ) -> int:
        return warehouse.upsert_indicator_values(conn, df, indicator_ids, run_id)

    # -- orchestration ----------------------------------------------------------

    def run(self, conn: psycopg.Connection) -> RunReport:
        """Run every stage for every payload; on error mark the run failed and re-raise."""
        if self.fixture_mode and os.environ.get("APP_ENV") == "prod":
            raise ConfigurationError("fixture mode must never run against prod")

        entries = load_catalog(self.catalog_path)
        catalog = by_key(entries)
        run_ids: list[uuid.UUID] = []
        rows_seen = rows_changed = 0

        with source_lock(conn, self.source):
            indicator_ids = warehouse.upsert_catalog(conn, entries)
            conn.commit()

            for fetched in self.fetch():
                # Register first, so even a payload that cannot be cleaned leaves a
                # provenance row (marked failed) instead of vanishing.
                run_id = self.register(conn, fetched)
                conn.commit()
                run_ids.append(run_id)
                try:
                    df = self.clean(fetched)
                    counts = df.attrs.get("sentinel_counts")  # set by clean() when it nulls codes
                    ingest_log.set_status(
                        conn,
                        run_id,
                        "cleaned",
                        row_count=len(df),
                        geo_vintage=_single_vintage(df),
                        notes=f"sentinels_to_null={counts}" if counts else None,
                    )
                    conn.commit()
                    results = self.validate(conn, df, catalog, indicator_ids)
                    # A gate that passed only because of a documented override leaves
                    # that override in the provenance record.
                    overrides = [r.detail for r in results if r.detail.startswith("overridden")]
                    ingest_log.set_status(
                        conn, run_id, "validated", notes="; ".join(overrides) or None
                    )
                    conn.commit()
                    changed = self.load(conn, df, indicator_ids, run_id)
                    ingest_log.set_status(conn, run_id, "loaded", notes=f"rows_changed={changed}")
                    conn.commit()  # values and the 'loaded' status commit together
                except Exception as exc:
                    conn.rollback()
                    ingest_log.set_status(
                        conn, run_id, "failed", notes=ingest_log.failure_note(exc)
                    )
                    conn.commit()
                    raise
                rows_seen += len(df)
                rows_changed += changed

            self.publish(conn)
            for run_id in run_ids:
                ingest_log.set_status(conn, run_id, "published")
            conn.commit()

        return RunReport(self.source, tuple(run_ids), rows_seen, rows_changed)


def _single_vintage(df: pd.DataFrame) -> int | None:
    values = pd.to_numeric(df["geo_vintage"], errors="coerce").dropna().unique()
    return int(values[0]) if len(values) == 1 else None
