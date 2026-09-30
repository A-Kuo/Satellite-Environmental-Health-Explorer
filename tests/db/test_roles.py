"""Least-privilege access model (migration 002).

Privileges are checked two ways: by catalog lookup (has_*_privilege) and by
actually running statements as each group role, since the second is what a
compromised or misconfigured client would do.
"""

from __future__ import annotations

import psycopg
import pytest
from dbtools import add_geography, add_indicator, add_run, add_value, rejected
from psycopg import sql

pytestmark = pytest.mark.db

GROUPS = ("ingest_writer", "api_reader", "analyst_readonly")
SCHEMAS = ("raw", "core", "marts", "research")
CORE_TABLES = (
    "core.geographies",
    "core.indicator_catalog",
    "core.indicator_values",
    "core.indicator_percentiles",
    "core.ingest_log",
)

# (role, schema, may it USAGE the schema?)
SCHEMA_ACCESS = [
    ("api_reader", "marts", True),
    ("api_reader", "core", False),
    ("api_reader", "raw", False),
    ("api_reader", "research", False),
    ("analyst_readonly", "core", True),
    ("analyst_readonly", "marts", True),
    ("analyst_readonly", "research", True),
    ("analyst_readonly", "raw", False),
    ("ingest_writer", "raw", True),
    ("ingest_writer", "core", True),
    ("ingest_writer", "research", False),
    ("ingest_writer", "marts", False),
]


def has_schema(conn: psycopg.Connection, role: str, schema: str, privilege: str = "USAGE") -> bool:
    row = conn.execute("SELECT has_schema_privilege(%s, %s, %s)", (role, schema, privilege))
    result = row.fetchone()
    assert result is not None
    return bool(result[0])


def has_table(conn: psycopg.Connection, role: str, table: str, privilege: str) -> bool:
    row = conn.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, privilege))
    result = row.fetchone()
    assert result is not None
    return bool(result[0])


def test_group_roles_exist_and_cannot_log_in(conn: psycopg.Connection) -> None:
    rows = dict(
        conn.execute(
            "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)", (list(GROUPS),)
        ).fetchall()
    )
    assert rows == dict.fromkeys(GROUPS, False)


@pytest.mark.parametrize(("role", "schema", "allowed"), SCHEMA_ACCESS)
def test_schema_access_matrix(
    conn: psycopg.Connection, role: str, schema: str, allowed: bool
) -> None:
    assert has_schema(conn, role, schema) is allowed


def test_a_role_with_no_grants_reaches_nothing(conn: psycopg.Connection) -> None:
    """Nothing is granted to PUBLIC, so an arbitrary role sees no schema."""
    conn.execute("CREATE ROLE nobody_test NOLOGIN")
    for schema in (*SCHEMAS, "public"):
        assert has_schema(conn, "nobody_test", schema) is False, schema
    assert has_schema(conn, "nobody_test", "public", "CREATE") is False


@pytest.mark.parametrize("table", CORE_TABLES)
def test_core_table_privileges(conn: psycopg.Connection, table: str) -> None:
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert has_table(conn, "ingest_writer", table, privilege), privilege
    assert has_table(conn, "analyst_readonly", table, "SELECT")
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert not has_table(conn, "analyst_readonly", table, privilege), privilege
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert not has_table(conn, "api_reader", table, privilege), privilege


def test_raw_tables_are_insert_only_for_the_ingest_role(conn: psycopg.Connection) -> None:
    """Default privileges: a raw table created later is immutable to ingestion."""
    conn.execute("CREATE TABLE raw.demo_payload (id int)")
    assert has_table(conn, "ingest_writer", "raw.demo_payload", "SELECT")
    assert has_table(conn, "ingest_writer", "raw.demo_payload", "INSERT")
    assert not has_table(conn, "ingest_writer", "raw.demo_payload", "UPDATE")
    assert not has_table(conn, "ingest_writer", "raw.demo_payload", "DELETE")
    assert not has_table(conn, "api_reader", "raw.demo_payload", "SELECT")
    assert not has_table(conn, "analyst_readonly", "raw.demo_payload", "SELECT")


def test_new_marts_objects_are_readable_by_api_and_analyst_only(
    conn: psycopg.Connection,
) -> None:
    conn.execute("CREATE VIEW marts.demo_view AS SELECT 1 AS x")
    conn.execute("CREATE MATERIALIZED VIEW marts.demo_mv AS SELECT 1 AS x")
    for relation in ("marts.demo_view", "marts.demo_mv"):
        assert has_table(conn, "api_reader", relation, "SELECT")
        assert has_table(conn, "analyst_readonly", relation, "SELECT")
        assert not has_table(conn, "ingest_writer", relation, "SELECT")
        assert not has_table(conn, "api_reader", relation, "INSERT")


def test_research_is_readable_by_the_analyst_role_only(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE research.demo (id int)")
    assert has_table(conn, "analyst_readonly", "research.demo", "SELECT")
    assert not has_table(conn, "analyst_readonly", "research.demo", "INSERT")
    assert not has_table(conn, "api_reader", "research.demo", "SELECT")
    assert not has_table(conn, "ingest_writer", "research.demo", "SELECT")


# ---------------------------------------------------------------------------
# Behavior: run real statements as each role
# ---------------------------------------------------------------------------


def test_api_reader_cannot_read_core_raw_or_research(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE raw.demo_payload (id int)")
    conn.execute("CREATE TABLE research.demo (id int)")
    conn.execute("SET LOCAL ROLE api_reader")
    relations = (
        "core.indicator_values",
        "core.geographies",
        "raw.demo_payload",
        "research.demo",
    )
    for relation in relations:
        query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(*relation.split(".")))
        with rejected(conn, psycopg.errors.InsufficientPrivilege):
            conn.execute(query)


def test_api_reader_can_read_marts(conn: psycopg.Connection) -> None:
    conn.execute("CREATE VIEW marts.demo_view AS SELECT 1 AS x")
    conn.execute("SET LOCAL ROLE api_reader")
    assert conn.execute("SELECT x FROM marts.demo_view").fetchone() == (1,)


def test_analyst_readonly_reads_but_never_writes(conn: psycopg.Connection) -> None:
    add_geography(conn, "55", "state")
    indicator_id = add_indicator(conn)
    run_id = add_run(conn)
    conn.execute("SET LOCAL ROLE analyst_readonly")
    assert conn.execute("SELECT count(*) FROM core.geographies").fetchone() == (1,)
    with rejected(conn, psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM core.geographies")
    with rejected(conn, psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE core.indicator_catalog SET name = 'renamed'")
    with rejected(conn, psycopg.errors.InsufficientPrivilege):
        add_value(conn, "55", indicator_id, run_id)


def test_ingest_writer_can_load_core_but_not_edit_raw(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE raw.demo_payload (id int)")
    conn.execute("SET LOCAL ROLE ingest_writer")
    add_geography(conn, "55", "state")
    indicator_id = add_indicator(conn)
    add_value(conn, "55", indicator_id, add_run(conn))
    conn.execute("INSERT INTO raw.demo_payload VALUES (1)")
    with rejected(conn, psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE raw.demo_payload SET id = 2")
    with rejected(conn, psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM raw.demo_payload")
    with rejected(conn, psycopg.errors.InsufficientPrivilege):
        conn.execute("CREATE TABLE core.ingest_created (id int)")
