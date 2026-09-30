"""One worker per source at a time (design spec section 5.4).

A Postgres session-level advisory lock keyed on the source name. A second run of
the same connector, from any machine, is refused instead of hammering a public API
in parallel. Requires a direct (non-pooled) connection.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

_NAMESPACE = 7_214_600  # fits int4; separates connector locks from the migration lock


class SourceBusy(RuntimeError):
    """Another worker already holds this source's lock."""


@contextmanager
def source_lock(conn: psycopg.Connection, source: str) -> Iterator[None]:
    key = (_NAMESPACE, f"connector:{source}")
    row = conn.execute("SELECT pg_try_advisory_lock(%s, hashtext(%s))", key).fetchone()
    if row is None or not row[0]:
        conn.rollback()
        raise SourceBusy(f"another worker is already running the {source!r} connector")
    conn.commit()
    try:
        yield
    finally:
        if conn.info.transaction_status == psycopg.pq.TransactionStatus.INERROR:
            conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s, hashtext(%s))", key)
        conn.commit()
