"""Indicator catalog entries, declared per connector in ``catalog.toml``.

The model mirrors the CHECK constraints on ``core.indicator_catalog`` so an
invalid entry fails at load time with a readable message instead of at INSERT.
A test keeps the allowed-value lists here and in migration 001 in step.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from src.connectors.forbidden import find_forbidden

Domain = Literal["health", "environment", "economic", "education", "food", "policy"]
Direction = Literal["higher_is_concern", "higher_is_protective", "neutral"]
EstimateType = Literal["observed", "survey", "model_based", "derived"]
GeoLevel = Literal["state", "county", "tract", "zcta"]
Cadence = Literal["monthly", "quarterly", "annual", "biennial", "irregular", "one_time"]

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    indicator_key: str
    domain: Domain
    name: NonBlank
    description: NonBlank
    unit: NonBlank
    direction: Direction
    estimate_type: EstimateType
    native_geo_level: GeoLevel
    native_geo_vintage: Annotated[int, Field(ge=1990, le=2100)]
    refresh_cadence: Cadence
    source_name: NonBlank
    source_url: Annotated[str, StringConstraints(pattern=r"^https?://\S+$")]
    license: NonBlank
    notes: str | None = None
    plausible_min: float | None = None
    plausible_max: float | None = None

    @field_validator("indicator_key")
    @classmethod
    def _key_is_well_formed_and_not_a_composite(cls, value: str) -> str:
        if not _KEY.match(value):
            raise ValueError("must look like 'source.measure_name' (lower-case, dots, underscores)")
        if find_forbidden(value):
            raise ValueError("a composite score cannot be registered as an indicator")
        return value

    @model_validator(mode="after")
    def _range_is_ordered(self) -> CatalogEntry:
        low, high = self.plausible_min, self.plausible_max
        if low is not None and high is not None and low > high:
            raise ValueError("plausible_min must not exceed plausible_max")
        return self


class CatalogError(ValueError):
    """The catalog file is malformed or contains duplicate keys."""


def load_catalog(path: Path) -> list[CatalogEntry]:
    """Read ``[[indicator]]`` tables from a TOML file."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    tables = data.get("indicator")
    if not isinstance(tables, list) or not tables:
        raise CatalogError(f"{path.name}: expected at least one [[indicator]] table")
    entries = [CatalogEntry(**table) for table in tables]
    keys = [e.indicator_key for e in entries]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise CatalogError(f"{path.name}: duplicate indicator keys {duplicates}")
    return entries


def by_key(entries: list[CatalogEntry]) -> dict[str, CatalogEntry]:
    return {e.indicator_key: e for e in entries}
