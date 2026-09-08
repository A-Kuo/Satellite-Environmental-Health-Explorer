"""Computes descriptive statistics for the Stage One processed tables."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OUT_PATH = PROCESSED_DIR / "summary_statistics.csv"

NUMERIC_COLUMNS = {
    "wi_svi_2022.parquet": [
        "overall_svi_percentile",
        "socioeconomic_theme_percentile",
        "household_characteristics_percentile",
        "minority_language_percentile",
        "housing_transport_percentile",
    ],
    "wi_pm25_2022.parquet": ["indicator_value"],
    "tract_screening_view.parquet": ["indicator_value", "indicator_percentile_wi", "overall_svi_percentile"],
}


def describe_column(table: str, df: pd.DataFrame, column: str) -> dict:
    series = df[column]
    valid = series.dropna()
    return {
        "table": table,
        "column": column,
        "count": len(valid),
        "mean": valid.mean(),
        "median": valid.median(),
        "p25": valid.quantile(0.25),
        "p75": valid.quantile(0.75),
        "pct_missing": 1 - (len(valid) / len(series)) if len(series) else float("nan"),
    }


def main() -> None:
    rows = []
    for filename, columns in NUMERIC_COLUMNS.items():
        df = pd.read_parquet(PROCESSED_DIR / filename, columns=columns)
        for column in columns:
            rows.append(describe_column(filename, df, column))

    out = pd.DataFrame(rows)
    out.to_csv(OUT_PATH, index=False)
    print(out.to_string(index=False))
    print(f"\nWrote {len(out)} rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
