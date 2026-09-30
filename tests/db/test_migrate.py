"""Migration runner: checksums, ordering guards, safety refusals, atomicity."""

from __future__ import annotations

import shutil
from pathlib import Path

import psycopg
import pytest

from db import migrate
from db.migrate import (
    MIGRATIONS_DIR,
    MigrationError,
    apply_migrations,
    checksum,
    describe_target,
    discover,
)

# ---------------------------------------------------------------------------
# No database needed
# ---------------------------------------------------------------------------


def test_checksum_ignores_line_endings_but_not_content() -> None:
    assert checksum("a\nb\n") == checksum("a\r\nb\r\n")
    assert checksum("a\nb\n") != checksum("a\nc\n")


def test_shipped_migrations_are_valid_and_ordered() -> None:
    found = discover(MIGRATIONS_DIR)
    assert [m.version for m in found][:2] == ["001", "002"]
    assert [m.version for m in found] == sorted(m.version for m in found)


def test_discover_sorts_numerically_and_rejects_bad_names(tmp_path: Path) -> None:
    for name in ("009_c.sql", "010_d.sql", "002_b.sql"):
        (tmp_path / name).write_text("SELECT 1;\n")
    assert [m.version for m in discover(tmp_path)] == ["002", "009", "010"]

    (tmp_path / "notes.sql").write_text("SELECT 1;\n")
    with pytest.raises(MigrationError, match="expected a name like"):
        discover(tmp_path)


def test_discover_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "001_a.sql").write_text("SELECT 1;\n")
    (tmp_path / "001_b.sql").write_text("SELECT 2;\n")
    with pytest.raises(MigrationError, match="duplicate migration version"):
        discover(tmp_path)


def test_describe_target_never_includes_the_password() -> None:
    canary = "canary-value-must-not-appear"  # synthetic marker, not a credential
    target = describe_target("postgresql://someone:" + canary + "@db.example.org/appdb")
    assert canary not in target
    assert "db.example.org" in target
    assert "appdb" in target


def test_pooled_host_is_refused_before_connecting() -> None:
    with pytest.raises(MigrationError, match="pooled"):
        apply_migrations("postgresql://u@ep-cool-123-pooler.us-east-1.aws.neon.tech/db")


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """No inherited settings and no developer .env/.env leaking into main()."""
    monkeypatch.setattr(migrate, "ENV_FILE", tmp_path / "absent.env")
    for var in ("APP_ENV", migrate.ENV_VAR):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_main_requires_app_env(isolated_env: pytest.MonkeyPatch) -> None:
    assert migrate.main([]) == 2


def test_main_requires_confirmation_to_apply_to_prod(
    isolated_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    isolated_env.setenv("APP_ENV", "prod")
    isolated_env.setenv(migrate.ENV_VAR, "host=localhost dbname=unused")
    assert migrate.main([]) == 2
    assert "--confirm-prod" in capsys.readouterr().err


def test_main_requires_the_connection_variable(
    isolated_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    isolated_env.setenv("APP_ENV", "dev")
    assert migrate.main([]) == 2
    assert migrate.ENV_VAR in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Needs a throwaway PostGIS server
# ---------------------------------------------------------------------------


def _copy_migrations(tmp_path: Path) -> Path:
    target = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, target)
    return target


def _applied_versions(conninfo: str) -> list[str]:
    with psycopg.connect(conninfo) as conn:
        rows = conn.execute("SELECT version FROM public.schema_migrations ORDER BY 1").fetchall()
    return [r[0] for r in rows]


@pytest.mark.db
def test_apply_from_empty_records_every_migration(empty_db: str) -> None:
    report = apply_migrations(empty_db)
    expected = tuple(m.version for m in discover(MIGRATIONS_DIR))
    assert report.applied == expected
    assert _applied_versions(empty_db) == list(expected)


@pytest.mark.db
def test_reapplying_is_a_noop(empty_db: str) -> None:
    apply_migrations(empty_db)
    again = apply_migrations(empty_db)
    assert again.applied == ()
    assert again.pending == ()
    assert len(again.already_applied) == len(discover(MIGRATIONS_DIR))


@pytest.mark.db
def test_dry_run_lists_pending_and_changes_nothing(empty_db: str) -> None:
    report = apply_migrations(empty_db, dry_run=True)
    assert report.applied == ()
    assert report.pending == tuple(m.version for m in discover(MIGRATIONS_DIR))
    with psycopg.connect(empty_db) as conn:
        row = conn.execute(
            "SELECT to_regclass('public.schema_migrations'), "
            "(SELECT count(*) FROM pg_namespace WHERE nspname = 'core')"
        ).fetchone()
    assert row == (None, 0)


@pytest.mark.db
def test_editing_an_applied_migration_is_detected(empty_db: str, tmp_path: Path) -> None:
    directory = _copy_migrations(tmp_path)
    apply_migrations(empty_db, migrations_dir=directory)
    first = next(directory.glob("001_*.sql"))
    first.write_text(first.read_text() + "\n-- edited after apply\n")
    with pytest.raises(MigrationError, match="modified after it was applied"):
        apply_migrations(empty_db, migrations_dir=directory)


@pytest.mark.db
def test_deleting_an_applied_migration_is_detected(empty_db: str, tmp_path: Path) -> None:
    directory = _copy_migrations(tmp_path)
    apply_migrations(empty_db, migrations_dir=directory)
    next(directory.glob("002_*.sql")).unlink()
    with pytest.raises(MigrationError, match="file is missing"):
        apply_migrations(empty_db, migrations_dir=directory)


@pytest.mark.db
def test_a_migration_older_than_the_newest_applied_is_refused(
    empty_db: str, tmp_path: Path
) -> None:
    directory = _copy_migrations(tmp_path)
    apply_migrations(empty_db, migrations_dir=directory)
    (directory / "000_late_addition.sql").write_text("SELECT 1;\n")
    with pytest.raises(MigrationError, match="in order"):
        apply_migrations(empty_db, migrations_dir=directory)


@pytest.mark.db
def test_a_failing_migration_rolls_back_and_is_not_recorded(empty_db: str, tmp_path: Path) -> None:
    (tmp_path / "001_ok.sql").write_text("CREATE TABLE public.t_ok (id int);\n")
    (tmp_path / "002_bad.sql").write_text(
        "CREATE TABLE public.t_partial (id int);\nSELECT 1 / 0;\n"
    )
    with pytest.raises(psycopg.errors.DivisionByZero):
        apply_migrations(empty_db, migrations_dir=tmp_path)

    assert _applied_versions(empty_db) == ["001"]
    with psycopg.connect(empty_db) as conn:
        row = conn.execute(
            "SELECT to_regclass('public.t_ok'), to_regclass('public.t_partial')"
        ).fetchone()
    assert row is not None
    assert row[0] is not None  # first migration committed
    assert row[1] is None  # failed migration left nothing behind
