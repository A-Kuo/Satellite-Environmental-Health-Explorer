"""No composite "risk", "priority", "harm" or "inequality" score, anywhere.

The explorer is a descriptive screening tool: signals are never blended into one
score. This fails the build if a forbidden name appears as an identifier in the
national-rebuild schema or catalog files. The list lives in one place,
``src/connectors/forbidden.py``; the catalog model, the load gate and migration
001's CHECK all enforce it, and this test keeps them in step. The API-field check
is added when the API ships. (The Wisconsin baseline has its own, narrower guard in
src/validate.py.)
"""

from __future__ import annotations

import re
from pathlib import Path

from src.connectors.forbidden import FORBIDDEN_NAMES, find_forbidden, forbidden_columns

REPO = Path(__file__).resolve().parent.parent
SCANNED_GLOBS = (
    "db/migrations/*.sql",
    "db/ops/*.sql",
    "src/connectors/**/*.toml",
    "src/connectors/**/*.sql",
)


def scanned_files() -> list[Path]:
    return sorted({p for pattern in SCANNED_GLOBS for p in REPO.glob(pattern)})


def test_no_forbidden_names_in_schema_or_catalog_files() -> None:
    files = scanned_files()
    assert files, "expected to scan at least the migrations"
    hits = {
        str(p.relative_to(REPO)): found
        for p in files
        if (found := find_forbidden(p.read_text(encoding="utf-8")))
    }
    assert not hits, f"forbidden composite-score names found: {hits}"


def test_the_detector_catches_every_forbidden_name() -> None:
    """Negative control: a scan that can never fail proves nothing."""
    for name in FORBIDDEN_NAMES:
        assert find_forbidden(f"CREATE TABLE t (id int, {name} real);") == [name]
        assert find_forbidden(f'column = "{name.upper()}"') == [name]
        assert find_forbidden(f"composite.{name}") == [name]
        assert find_forbidden(f"my_{name}_v2") == [name]  # embedded in a longer identifier
    assert find_forbidden("CREATE TABLE t (id int, concern_percentile real);") == []
    assert find_forbidden("microrisk_scoreboard") == []


def test_column_check_finds_forbidden_columns() -> None:
    assert forbidden_columns(["geoid", "value", "Risk_Score", "concern_percentile"]) == [
        "Risk_Score"
    ]


def test_the_database_check_covers_the_same_names() -> None:
    """The catalog CHECK in migration 001 must not drift from FORBIDDEN_NAMES."""
    migration = (REPO / "db/migrations/001_core_schema.sql").read_text(encoding="utf-8")
    match = re.search(r"indicator_key !~ '([^']+)'", migration)
    assert match, "catalog_no_composite_ck not found in 001"
    check = re.compile(match.group(1))
    for name in FORBIDDEN_NAMES:
        assert check.search(f"composite.{name}"), f"DB check would allow {name}"
