"""Cleans the raw EJScreen 2.3 tract CSV (national) into the Wisconsin-only
environmental_indicator schema described in agent.md.

Note: EJScreen was removed from EPA's own website in Feb 2025 (see
methodology.md for the limitation this implies). This file was sourced from
the Harvard Dataverse mirror, doi:10.7910/DVN/RLR5AX.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = REPO_ROOT / "data" / "raw" / "ejscreen_2024_tract_statepct_national.csv"
OUT_PATH = REPO_ROOT / "data" / "processed" / "wi_pm25_2022.parquet"

INDICATOR_NAME = "PM2.5 Annual Concentration"
INDICATOR_YEAR = 2022
UNIT = "µg/m³"
SOURCE_URL = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/RLR5AX"
AGGREGATION_METHOD = (
    "EPA EJScreen 2.3 modeled annual-average PM2.5 surface, tract-level. "
    "Sourced via the Harvard Dataverse mirror of EJScreen (file "
    "EJScreen_2024_Tract_StatePct_with_AS_CNMI_GU_VI.csv) because EPA removed "
    "EJScreen from its own website in February 2025 and no official EPA "
    "endpoint is currently available."
)


def clean_indicator(raw_path: Path = RAW_PATH) -> pd.DataFrame:
    usecols = ["ID", "STATE_NAME", "PM25"]
    df = pd.read_csv(raw_path, usecols=usecols, dtype={"ID": str})

    wi = df[df["ID"].str.startswith("55")].copy()
    wi = wi.rename(columns={"ID": "geoid", "PM25": "indicator_value"})
    wi = wi.drop(columns=["STATE_NAME"])

    wi["indicator_name"] = INDICATOR_NAME
    wi["indicator_year"] = INDICATOR_YEAR
    wi["unit"] = UNIT
    wi["data_coverage_flag"] = "modeled"
    wi["aggregation_method"] = AGGREGATION_METHOD
    wi["source_url"] = SOURCE_URL

    ordered_cols = [
        "geoid",
        "indicator_name",
        "indicator_year",
        "indicator_value",
        "unit",
        "data_coverage_flag",
        "aggregation_method",
        "source_url",
    ]
    return wi[ordered_cols]


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = clean_indicator()
    out.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(out):,} rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
