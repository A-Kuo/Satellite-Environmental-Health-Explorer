"""Cleans the raw EJScreen 2.3 tract CSV (national) into the per-state
environmental_indicator schema described in agent.md.

Note: EJScreen was removed from EPA's own website in Feb 2025 (see
methodology.md for the limitation this implies). This file was sourced from
the Harvard Dataverse mirror, doi:10.7910/DVN/RLR5AX. It is a NATIONAL file
covering every state -- extending PM2.5 to a new state needs no new
download, just a different STATE_FIPS filter.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.states import StateConfig, get_state

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = REPO_ROOT / "data" / "raw" / "ejscreen_2024_tract_statepct_national.csv"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

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


def clean_indicator(state: StateConfig, raw_path: Path = RAW_PATH) -> pd.DataFrame:
    usecols = ["ID", "STATE_NAME", "PM25"]
    df = pd.read_csv(raw_path, usecols=usecols, dtype={"ID": str})

    out = df[df["ID"].str.startswith(state.fips)].copy()
    out = out.rename(columns={"ID": "geoid", "PM25": "indicator_value"})
    out = out.drop(columns=["STATE_NAME"])

    out["indicator_name"] = INDICATOR_NAME
    out["indicator_year"] = INDICATOR_YEAR
    out["unit"] = UNIT
    out["data_coverage_flag"] = "modeled"
    out["aggregation_method"] = AGGREGATION_METHOD
    out["source_url"] = SOURCE_URL

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
    return out[ordered_cols]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="WI", help="State abbreviation, e.g. WI, MN")
    args = parser.parse_args()
    state = get_state(args.state)

    out_path = PROCESSED_DIR / f"{state.abbr.lower()}_pm25_2022.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = clean_indicator(state)
    out.to_parquet(out_path, index=False)
    print(f"Wrote {len(out):,} rows -> {out_path}")


if __name__ == "__main__":
    main()
