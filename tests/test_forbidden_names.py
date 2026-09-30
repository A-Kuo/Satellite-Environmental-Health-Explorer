"""No composite "risk", "priority", "harm" or "inequality" score, anywhere.

The explorer is a descriptive screening tool: signals are never blended into one
score. This fails the build if a forbidden name appears as an identifier in the
national-rebuild schema or catalog files. The API-field check is added when the
API ships. (The Wisconsin baseline has its own, narrower guard in src/validate.py.)
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FORBIDDEN = ("risk_score", "priority_score", "harm_score", "inequality_score")
SCANNED_GLOBS = (
    "db/migrations/*.sql",
    "db/ops/*.sql",
    "src/connectors/**/*.toml",
    "src/connectors/**/*.sql",
)
NAME_PATTERN = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.IGNORECASE)


def find_forbidden(text: str) -> list[str]:
    return sorted({m.group(1).lower() for m in NAME_PATTERN.finditer(text)})


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
    for name in FORBIDDEN:
        assert find_forbidden(f"CREATE TABLE t (id int, {name} real);") == [name]
        assert find_forbidden(f'column = "{name.upper()}"') == [name]
    assert find_forbidden("CREATE TABLE t (id int, concern_percentile real);") == []


def test_the_database_check_covers_the_same_names() -> None:
    """The catalog CHECK in migration 001 must not drift from FORBIDDEN."""
    migration = (REPO / "db/migrations/001_core_schema.sql").read_text(encoding="utf-8")
    match = re.search(r"indicator_key !~ '([^']+)'", migration)
    assert match, "catalog_no_composite_ck not found in 001"
    check = re.compile(match.group(1))
    for name in FORBIDDEN:
        assert check.search(f"composite.{name}"), f"DB check would allow {name}"
