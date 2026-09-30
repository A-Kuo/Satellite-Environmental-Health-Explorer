"""Cleaning helpers shared by every connector: GEOIDs, sentinel codes, flags."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

import pandas as pd

LEVEL_LENGTH: dict[str, int] = {"state": 2, "county": 5, "tract": 11, "zcta": 5}


def normalize_geoid(series: pd.Series, level: str) -> pd.Series:
    """Zero-padded string GEOIDs.

    Spreadsheets and integer-typed CSV columns drop leading zeros (Alabama county
    01001 becomes 1001) and a column with blanks turns into floats ("1001.0"). Both
    are repaired here. Missing values stay missing. A value that is still the wrong
    length afterwards is left as is, for the GEOID-format gate to reject.
    """
    if level not in LEVEL_LENGTH:
        raise ValueError(f"unknown geography level {level!r}")
    text = series.astype("string").str.strip()
    text = text.str.replace(r"^(\d+)\.0+$", r"\1", regex=True)
    return text.str.zfill(LEVEL_LENGTH[level])


def replace_sentinels(
    df: pd.DataFrame, columns: Sequence[str], sentinels: Collection[float]
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Convert missing-value codes (for example -999) to NaN and count them.

    Sentinels are declared per source, never guessed: a generic list would turn a
    legitimate negative value into a gap. Returns a copy and the count per column.
    """
    out = df.copy()
    counts: dict[str, int] = {}
    for column in columns:
        if not pd.api.types.is_numeric_dtype(out[column]):
            raise TypeError(f"{column} must be numeric before sentinels are replaced")
        mask = out[column].isin(list(sentinels))
        counts[column] = int(mask.sum())
        out.loc[mask, column] = float("nan")
    return out, counts


def flag_missing_values(df: pd.DataFrame, flag: str = "no_data") -> pd.DataFrame:
    """Mark rows with no value, so a missing value always says why."""
    out = df.copy()
    missing: Any = out["value"].isna() & (out["coverage_flag"] == "ok")
    out.loc[missing, "coverage_flag"] = flag
    return out
