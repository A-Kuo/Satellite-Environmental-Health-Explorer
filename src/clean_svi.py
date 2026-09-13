"""Cleans the raw CDC/ATSDR SVI 2022 per-state tract CSV into the
social_vulnerability schema described in agent.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.states import StateConfig, get_state

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

SVI_YEAR = 2022

COLUMN_MAP = {
    "RPL_THEMES": "overall_svi_percentile",
    "RPL_THEME1": "socioeconomic_theme_percentile",
    "RPL_THEME2": "household_characteristics_percentile",
    "RPL_THEME3": "minority_language_percentile",
    "RPL_THEME4": "housing_transport_percentile",
}


def clean_svi(state: StateConfig, raw_path: Path) -> pd.DataFrame:
    df = pd.read_csv(raw_path, dtype={"FIPS": str})

    df["geoid"] = df["FIPS"].str.zfill(11)

    percentile_cols = list(COLUMN_MAP.keys())
    df[percentile_cols] = df[percentile_cols].replace(-999, np.nan).replace(-999.0, np.nan)

    out = df[["geoid", *percentile_cols]].rename(columns=COLUMN_MAP)
    out["svi_year"] = SVI_YEAR
    out["source_url"] = (
        f"https://svi.cdc.gov/Documents/Data/{SVI_YEAR}/csv/states/{state.svi_name()}.csv"
    )

    ordered_cols = [
        "geoid",
        "svi_year",
        "overall_svi_percentile",
        "socioeconomic_theme_percentile",
        "household_characteristics_percentile",
        "minority_language_percentile",
        "housing_transport_percentile",
        "source_url",
    ]
    return out[ordered_cols]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="WI", help="State abbreviation, e.g. WI, MN")
    args = parser.parse_args()
    state = get_state(args.state)

    raw_path = RAW_DIR / f"svi_2022_{state.abbr.lower()}.csv"
    out_path = PROCESSED_DIR / f"{state.abbr.lower()}_svi_2022.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = clean_svi(state, raw_path)
    out.to_parquet(out_path, index=False)
    print(f"Wrote {len(out):,} rows -> {out_path}")


if __name__ == "__main__":
    main()
