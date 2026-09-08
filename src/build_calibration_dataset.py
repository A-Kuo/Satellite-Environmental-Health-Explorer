"""Joins ground-truth AQS concentrations with satellite proxies per pollutant
and reports how much of the theoretically possible site-day coverage the
satellite retrieval actually delivered.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

POLLUTANTS = ["no2", "so2", "co", "pm25"]


def build_calibration_dataset(pollutant: str) -> tuple[pd.DataFrame, dict]:
    ground_truth = pd.read_parquet(PROCESSED_DIR / f"ground_truth_{pollutant}.parquet")
    ground_truth["date"] = pd.to_datetime(ground_truth["date"])

    satellite = pd.read_parquet(PROCESSED_DIR / f"satellite_{pollutant}.parquet")
    satellite["date"] = pd.to_datetime(satellite["date"])

    merged = ground_truth.merge(satellite, on=["site_id", "date"], how="left")

    n_possible = len(merged)
    n_valid = int(merged["retrieval_valid"].fillna(False).sum())
    coverage_pct = 100 * n_valid / n_possible if n_possible else float("nan")

    calibration_dataset = merged[merged["retrieval_valid"].fillna(False)].copy()
    calibration_dataset = calibration_dataset.drop(columns=["retrieval_valid"])

    coverage_row = {
        "pollutant": pollutant,
        "n_ground_truth_site_days": n_possible,
        "n_valid_satellite_retrievals": n_valid,
        "coverage_pct": coverage_pct,
    }
    return calibration_dataset, coverage_row


def main() -> None:
    coverage_rows = []
    for pollutant in POLLUTANTS:
        dataset, coverage_row = build_calibration_dataset(pollutant)
        out_path = PROCESSED_DIR / f"calibration_dataset_{pollutant}.parquet"
        dataset.to_parquet(out_path, index=False)
        coverage_rows.append(coverage_row)
        print(
            f"{pollutant}: {coverage_row['n_valid_satellite_retrievals']:,} / "
            f"{coverage_row['n_ground_truth_site_days']:,} site-days "
            f"({coverage_row['coverage_pct']:.1f}% coverage) -> {out_path}"
        )

    coverage_report = pd.DataFrame(coverage_rows)
    coverage_path = PROCESSED_DIR / "satellite_coverage_report.csv"
    coverage_report.to_csv(coverage_path, index=False)
    print(f"\nWrote coverage report -> {coverage_path}")


if __name__ == "__main__":
    main()
