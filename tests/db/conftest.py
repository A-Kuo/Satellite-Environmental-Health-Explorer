"""Fixtures for database tests.

They need a throwaway PostGIS server, given by TEST_DATABASE_URL (a libpq
connection string for a superuser, e.g. the CI service container or a local
cluster). Without it every test that requests these fixtures is skipped. It is
never a Neon URL: each test creates and drops its own database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import psycopg
import pytest
from dbtools import add_geography
from psycopg import sql
from psycopg.conninfo import make_conninfo

from db.migrate import apply_migrations


@pytest.fixture(scope="session")
def server_conninfo() -> str:
    conninfo = os.environ.get("TEST_DATABASE_URL")
    if not conninfo:
        pytest.skip("TEST_DATABASE_URL is not set; skipping database tests")
    return conninfo


def _create_database(server_conninfo: str) -> str:
    name = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(server_conninfo, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return name


def _drop_database(server_conninfo: str, name: str) -> None:
    with psycopg.connect(server_conninfo, autocommit=True) as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


@pytest.fixture
def empty_db(server_conninfo: str) -> Iterator[str]:
    """Connection string for a brand-new, empty database."""
    name = _create_database(server_conninfo)
    try:
        yield make_conninfo(server_conninfo, dbname=name)
    finally:
        _drop_database(server_conninfo, name)


@pytest.fixture(scope="module")
def migrated_db(server_conninfo: str) -> Iterator[str]:
    """A database with every migration applied, shared by a test module."""
    name = _create_database(server_conninfo)
    conninfo = make_conninfo(server_conninfo, dbname=name)
    try:
        apply_migrations(conninfo)
        yield conninfo
    finally:
        _drop_database(server_conninfo, name)


TEMPLATE_FIXTURES = Path(__file__).parents[2] / "src/connectors/_template/fixtures"


@pytest.fixture
def pipeline_db(server_conninfo: str) -> Iterator[str]:
    """A fresh, migrated database with the template's synthetic tracts committed.

    Connector runs commit, so each pipeline test gets its own database instead of
    the rolled-back connection the schema tests share.
    """
    name = _create_database(server_conninfo)
    conninfo = make_conninfo(server_conninfo, dbname=name)
    try:
        apply_migrations(conninfo)
        tracts = pd.read_csv(TEMPLATE_FIXTURES / "tract_geographies.csv", dtype=str)
        with psycopg.connect(conninfo) as seed:
            for geoid, tract_name in tracts.itertuples(index=False):
                add_geography(seed, geoid, "tract", name=tract_name)
        yield conninfo
    finally:
        _drop_database(server_conninfo, name)


@pytest.fixture
def pg(pipeline_db: str) -> Iterator[psycopg.Connection]:
    """A connection to the pipeline database (commits are real here)."""
    connection = psycopg.connect(pipeline_db)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def conn(migrated_db: str) -> Iterator[psycopg.Connection]:
    """A connection whose work is always rolled back, so tests stay independent."""
    connection = psycopg.connect(migrated_db)
    # Open the outer transaction now. psycopg's transaction() is a savepoint only
    # inside an open transaction; otherwise it is a real BEGIN/COMMIT, and a
    # regression that lets a bad row through would commit it into the module's
    # shared database and cascade into unrelated tests.
    connection.execute("SELECT 1")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()
