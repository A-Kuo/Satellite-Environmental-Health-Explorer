"""Load step. The shared idempotent upsert is enough for most sources.

Override only if the source needs something the generic path cannot do, for
example loading boundaries into ``core.geographies`` (the foundation connectors).
"""

from __future__ import annotations

import uuid

import pandas as pd
import psycopg

from src.connectors.warehouse import upsert_indicator_values


def load(
    conn: psycopg.Connection,
    df: pd.DataFrame,
    indicator_ids: dict[str, int],
    run_id: uuid.UUID,
) -> int:
    """Upsert on the natural key; returns the number of rows inserted or changed."""
    return upsert_indicator_values(conn, df, indicator_ids, run_id)
