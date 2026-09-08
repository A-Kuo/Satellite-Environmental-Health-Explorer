"""Cleans the raw CDC/ATSDR SVI 2022 Wisconsin tract CSV into the
social_vulnerability schema described in agent.md.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = REPO_ROOT / "data" / "raw" / "svi_2022_wisconsin.csv"
OUT_PATH = REPO_ROOT / "data" / "processed" / "wi_svi_2022.parquet"

SVI_YEAR = 2022
SOURCE_URL = "https://svi.cdc.gov/Documents/Data/2022/csv/states/Wisconsin.csv"

COLUMN_MAP = {
    "RPL_THEMES": "overall_svi_percentile",
    "RPL_THEME1": "socioeconomic_theme_percentile",
    "RPL_THEME2": "household_characteristics_percentile",
    "RPL_THEME3": "minority_language_percentile",
    "RPL_THEME4": "housing_transport_percentile",
}


def clean_svi(raw_path: Path = RAW_PATH) -> pd.DataFrame:
    df = pd.read_csv(raw_path, dtype={"FIPS": str})

    df["geoid"] = df["FIPS"].str.zfill(11)

    percentile_cols = list(COLUMN_MAP.keys())
    df[percentile_cols] = df[percentile_cols].replace(-999, np.nan).replace(-999.0, np.nan)

    out = df[["geoid", *percentile_cols]].rename(columns=COLUMN_MAP)
    out["svi_year"] = SVI_YEAR
    out["source_url"] = SOURCE_URL

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
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = clean_svi()
    out.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(out):,} rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
