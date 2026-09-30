"""Plain-SQL migration runner.

Applies ``db/migrations/NNN_name.sql`` in order, each file in its own
transaction, and records ``(version, name, sha256)`` in
``public.schema_migrations``. It speaks to any Postgres, so the same runner
serves the Neon dev project, the Neon prod project and a local PostGIS.

    python -m db.migrate --dry-run
    python -m db.migrate
    APP_ENV=prod python -m db.migrate --confirm-prod

Reads ``DATABASE_URL_MIGRATE`` (direct, non-pooled connection, owner role) from
the environment or from ``.env/.env``. The value is never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
# `.env/` is a directory (it also holds the GEE key), so the env file is `.env/.env`.
ENV_FILE = ROOT / ".env" / ".env"
ENV_VAR = "DATABASE_URL_MIGRATE"

_FILENAME_RE = re.compile(r"^(?P<version>\d{3,})_(?P<name>[a-z0-9_]+)\.sql$")
# Arbitrary constant: serializes concurrent runners against one database.
_ADVISORY_LOCK_KEY = 7_214_600_101

_CREATE_TRACKING_TABLE = """
    CREATE TABLE IF NOT EXISTS public.schema_migrations (
        version    text        PRIMARY KEY,
        name       text        NOT NULL,
        sha256     char(64)    NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now()
    )
"""


class MigrationError(RuntimeError):
    """A migration cannot be applied safely. Nothing further is run."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    sql: str
    sha256: str


@dataclass(frozen=True)
class Report:
    applied: tuple[str, ...]  # applied by this run
    pending: tuple[str, ...]  # would be applied (dry run)
    already_applied: tuple[str, ...]


def checksum(sql: str) -> str:
    """SHA-256 of the file text with line endings normalized.

    ``.gitattributes`` sets ``text=auto``, so a Windows checkout can turn LF into
    CRLF. Hashing the normalized text keeps one checksum per migration.
    """
    normalized = sql.replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Read and validate migration files, returned in version order."""
    migrations: dict[str, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME_RE.match(path.name)
        if match is None:
            raise MigrationError(f"{path.name}: expected a name like 001_short_name.sql")
        version = match["version"]
        if version in migrations:
            raise MigrationError(f"duplicate migration version {version}")
        sql = path.read_text(encoding="utf-8")
        migrations[version] = Migration(version, match["name"], sql, checksum(sql))
    return [migrations[v] for v in sorted(migrations, key=int)]


def describe_target(conninfo: str) -> str:
    """Host, database and user for logging. Never includes the password."""
    parts = conninfo_to_dict(conninfo)
    return (
        f"host={parts.get('host', '?')} dbname={parts.get('dbname', '?')} "
        f"user={parts.get('user', '?')}"
    )


def _assert_direct_connection(conninfo: str) -> None:
    host = str(conninfo_to_dict(conninfo).get("host") or "")
    if "-pooler" in host:
        raise MigrationError(
            "DATABASE_URL_MIGRATE points at a pooled host. Migrations need the direct "
            "(non-pooled) connection: they use session-level advisory locks."
        )


def _applied(conn: psycopg.Connection) -> dict[str, tuple[str, str]]:
    row = conn.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL").fetchone()
    if row is None or not row[0]:
        return {}
    rows = conn.execute("SELECT version, name, sha256 FROM public.schema_migrations").fetchall()
    return {version: (name, sha) for version, name, sha in rows}


def _plan(
    migrations: Sequence[Migration], applied: dict[str, tuple[str, str]]
) -> tuple[list[Migration], list[Migration]]:
    """Split into (already applied, pending); raise if history and files disagree."""
    on_disk = {m.version: m for m in migrations}
    for version in applied:
        if version not in on_disk:
            raise MigrationError(
                f"migration {version} is recorded as applied but its file is missing"
            )
    already: list[Migration] = []
    pending: list[Migration] = []
    for m in migrations:
        if m.version in applied:
            if applied[m.version][1] != m.sha256:
                raise MigrationError(
                    f"migration {m.version}_{m.name}.sql was modified after it was applied. "
                    "Add a new migration instead of editing an applied one."
                )
            already.append(m)
        else:
            pending.append(m)
    if applied and pending:
        newest_applied = max(applied, key=int)
        for m in pending:
            if int(m.version) < int(newest_applied):
                raise MigrationError(
                    f"migration {m.version} is older than the newest applied migration "
                    f"({newest_applied}); migrations must be applied in order"
                )
    return already, pending


def apply_migrations(
    conninfo: str,
    *,
    migrations_dir: Path = MIGRATIONS_DIR,
    dry_run: bool = False,
) -> Report:
    """Apply pending migrations (or, with ``dry_run``, only list them)."""
    _assert_direct_connection(conninfo)
    migrations = discover(migrations_dir)
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        try:
            already, pending = _plan(migrations, _applied(conn))
            if dry_run or not pending:
                return Report(
                    applied=(),
                    pending=tuple(m.version for m in pending),
                    already_applied=tuple(m.version for m in already),
                )
            conn.execute(_CREATE_TRACKING_TABLE)
            done: list[str] = []
            for m in pending:
                # File and bookkeeping row commit together or not at all.
                with conn.transaction():
                    conn.execute(m.sql)  # multi-statement file: no parameters, simple protocol
                    conn.execute(
                        "INSERT INTO public.schema_migrations (version, name, sha256) "
                        "VALUES (%s, %s, %s)",
                        (m.version, m.name, m.sha256),
                    )
                done.append(m.version)
            return Report(
                applied=tuple(done),
                pending=(),
                already_applied=tuple(m.version for m in already),
            )
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply pending SQL migrations.")
    parser.add_argument("--dry-run", action="store_true", help="list pending, change nothing")
    parser.add_argument(
        "--confirm-prod", action="store_true", help="required to apply when APP_ENV=prod"
    )
    parser.add_argument("--migrations-dir", type=Path, default=MIGRATIONS_DIR)
    args = parser.parse_args(argv)

    load_dotenv(ENV_FILE, override=False)

    env = os.environ.get("APP_ENV", "")
    if env not in {"dev", "prod"}:
        print("error: set APP_ENV to 'dev' or 'prod'", file=sys.stderr)
        return 2
    if env == "prod" and not (args.dry_run or args.confirm_prod):
        print("error: APP_ENV=prod requires --confirm-prod to apply", file=sys.stderr)
        return 2
    conninfo = os.environ.get(ENV_VAR, "")
    if not conninfo:
        print(f"error: {ENV_VAR} is not set", file=sys.stderr)
        return 2

    print(f"target: {describe_target(conninfo)} (APP_ENV={env})")
    try:
        report = apply_migrations(
            conninfo, migrations_dir=args.migrations_dir, dry_run=args.dry_run
        )
    except MigrationError as exc:
        print(f"migration error: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"database error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"pending: {', '.join(report.pending) or 'none'}")
    else:
        print(f"applied: {', '.join(report.applied) or 'none (up to date)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
