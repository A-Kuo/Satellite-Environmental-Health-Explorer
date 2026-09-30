"""Catalog entries: validation, loading, and agreement with the database CHECKs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from src.connectors import catalog as catalog_module
from src.connectors._template import TemplateConnector
from src.connectors.catalog import CatalogEntry, CatalogError, by_key, load_catalog
from src.connectors.forbidden import FORBIDDEN_NAMES
from src.connectors.gates import COVERAGE_FLAGS
from src.connectors.ingest_log import Status
from src.connectors.normalize import LEVEL_LENGTH

MIGRATION_001 = (Path(__file__).parents[2] / "db/migrations/001_core_schema.sql").read_text()
VALID: dict[str, Any] = {
    "indicator_key": "demo.measure",
    "domain": "health",
    "name": "Demo",
    "description": "A demonstration indicator.",
    "unit": "percent",
    "direction": "higher_is_concern",
    "estimate_type": "model_based",
    "native_geo_level": "tract",
    "native_geo_vintage": 2020,
    "refresh_cadence": "annual",
    "source_name": "Demo source",
    "source_url": "https://example.org/data",
    "license": "Public domain",
    "plausible_min": 0,
    "plausible_max": 100,
}


def test_the_template_catalog_loads_and_is_complete() -> None:
    entries = load_catalog(TemplateConnector.catalog_path)
    assert [e.indicator_key for e in entries] == ["template_demo.rate"]
    entry = entries[0]
    assert entry.estimate_type == "model_based" and entry.license and entry.source_url


def test_a_valid_entry_is_accepted_and_frozen() -> None:
    entry = CatalogEntry(**VALID)
    with pytest.raises(ValidationError):
        entry.unit = "count"  # type: ignore[misc]


INVALID = [
    pytest.param({"plausible_min": 10, "plausible_max": 1}, id="min_above_max"),
    pytest.param({"license": "   "}, id="blank_license"),
    pytest.param({"source_url": "ftp://example.org/x"}, id="source_url_not_http"),
    pytest.param({"direction": "worst_first"}, id="unknown_direction"),
    pytest.param({"domain": "vibes"}, id="unknown_domain"),
    pytest.param({"estimate_type": "measured"}, id="unknown_estimate_type"),
    pytest.param({"refresh_cadence": "whenever"}, id="unknown_cadence"),
    pytest.param({"native_geo_level": "block"}, id="unknown_level"),
    pytest.param({"native_geo_vintage": 1}, id="implausible_vintage"),
    pytest.param({"indicator_key": "Has Spaces"}, id="bad_key_format"),
    pytest.param({"name": ""}, id="blank_name"),
    pytest.param({"surprise": "field"}, id="extra_field"),
]


@pytest.mark.parametrize("overrides", INVALID)
def test_invalid_entries_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CatalogEntry(**{**VALID, **overrides})


@pytest.mark.parametrize("name", FORBIDDEN_NAMES)
def test_a_composite_score_cannot_be_registered(name: str) -> None:
    with pytest.raises(ValidationError, match="composite score"):
        CatalogEntry(**{**VALID, "indicator_key": f"demo.{name}"})


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "catalog.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_catalog_file_needs_at_least_one_indicator(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match=r"at least one \[\[indicator\]\]"):
        load_catalog(write(tmp_path, "title = 'nothing here'\n"))


def test_duplicate_keys_in_one_file_are_rejected(tmp_path: Path) -> None:
    body = Path(TemplateConnector.catalog_path).read_text(encoding="utf-8")
    entry = body[body.index("[[indicator]]") :]
    with pytest.raises(CatalogError, match="duplicate indicator keys"):
        load_catalog(write(tmp_path, entry + "\n" + entry))


def test_by_key_indexes_entries() -> None:
    entries = load_catalog(TemplateConnector.catalog_path)
    assert set(by_key(entries)) == {"template_demo.rate"}


# --- drift: Python enums vs the database CHECK constraints ---------------------


def sql_values(constraint: str, column: str) -> set[str]:
    """The quoted values of ``<column> IN (...)`` inside a named CHECK in migration 001."""
    match = re.search(rf"CONSTRAINT {constraint} CHECK \(\s*{column} IN \(([^)]*)\)", MIGRATION_001)
    assert match, f"CHECK ({column} IN (...)) named {constraint} not found in migration 001"
    return set(re.findall(r"'([^']+)'", match.group(1)))


@pytest.mark.parametrize(
    ("constraint", "column", "literal"),
    [
        ("catalog_domain_ck", "domain", catalog_module.Domain),
        ("catalog_direction_ck", "direction", catalog_module.Direction),
        ("catalog_estimate_type_ck", "estimate_type", catalog_module.EstimateType),
        ("catalog_native_level_ck", "native_geo_level", catalog_module.GeoLevel),
        ("catalog_cadence_ck", "refresh_cadence", catalog_module.Cadence),
        ("geographies_level_ck", "geo_level", catalog_module.GeoLevel),
    ],
)
def test_python_enums_match_the_database_constraints(
    constraint: str, column: str, literal: Any
) -> None:
    assert sql_values(constraint, column) == set(get_args(literal))


def test_geography_levels_agree_with_the_geoid_width_table() -> None:
    assert set(LEVEL_LENGTH) == set(get_args(catalog_module.GeoLevel))


def test_coverage_flags_and_run_statuses_match_the_database() -> None:
    assert sql_values("indicator_values_coverage_ck", "coverage_flag") == set(COVERAGE_FLAGS)
    assert sql_values("ingest_log_status_ck", "status") == set(get_args(Status))
