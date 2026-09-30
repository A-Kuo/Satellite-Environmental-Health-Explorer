"""Normalize the raw file to the long-format value schema (``gates.VALUE_COLUMNS``)."""

from __future__ import annotations

import pandas as pd

from src.connectors.base import FetchedPayload
from src.connectors.gates import VALUE_COLUMNS
from src.connectors.normalize import flag_missing_values, normalize_geoid, replace_sentinels

INDICATOR_KEY = "template_demo.rate"
GEO_VINTAGE = 2020


def clean(fetched: FetchedPayload, *, level: str, sentinels: tuple[float, ...]) -> pd.DataFrame:
    # Read everything as text first: a numeric GEOID column loses its leading zeros.
    raw = pd.read_csv(fetched.payload.path, dtype=str)
    frame = pd.DataFrame(
        {
            "geoid": normalize_geoid(raw["GEOID"], level),
            "geo_vintage": GEO_VINTAGE,
            "indicator_key": INDICATOR_KEY,
            "period_start": pd.to_datetime(raw["YEAR"] + "-01-01"),
            "period_end": pd.to_datetime(raw["YEAR"] + "-12-31"),
            "value": pd.to_numeric(raw["RATE"]),
            "moe_or_ci_low": pd.to_numeric(raw["RATE_LOW"]),
            "moe_or_ci_high": pd.to_numeric(raw["RATE_HIGH"]),
            "coverage_flag": "ok",
        }
    )
    frame, counts = replace_sentinels(
        frame, ["value", "moe_or_ci_low", "moe_or_ci_high"], sentinels
    )
    frame = flag_missing_values(frame)[list(VALUE_COLUMNS)]
    frame.attrs["sentinel_counts"] = counts  # recorded in the ingest log
    return frame
