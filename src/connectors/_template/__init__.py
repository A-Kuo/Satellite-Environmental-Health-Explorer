"""Copyable connector skeleton, runnable end to end in fixture mode."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import ClassVar

import pandas as pd
import psycopg

from src.connectors._template import clean, fetch, load, validate
from src.connectors._template.client import SOURCE
from src.connectors.base import Connector, FetchedPayload
from src.connectors.catalog import CatalogEntry
from src.connectors.gates import GateResult


class TemplateConnector(Connector):
    source: ClassVar[str] = SOURCE
    geo_level: ClassVar[str] = "tract"
    catalog_path: ClassVar[Path] = Path(__file__).with_name("catalog.toml")
    sentinels: ClassVar[tuple[float, ...]] = (-999,)

    def fetch(self) -> list[FetchedPayload]:
        return fetch.fetch(self.store, fixture_mode=self.fixture_mode)

    def clean(self, fetched: FetchedPayload) -> pd.DataFrame:
        return clean.clean(fetched, level=self.geo_level, sentinels=self.sentinels)

    def validate_domain(
        self, df: pd.DataFrame, catalog: dict[str, CatalogEntry]
    ) -> list[GateResult]:
        return validate.domain_gates(df)

    def load(
        self,
        conn: psycopg.Connection,
        df: pd.DataFrame,
        indicator_ids: dict[str, int],
        run_id: uuid.UUID,
    ) -> int:
        return load.load(conn, df, indicator_ids, run_id)
