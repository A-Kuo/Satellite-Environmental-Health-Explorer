from pathlib import Path

import pandas as pd
import pytest

from src.validate import FORBIDDEN_COLUMNS

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
POLLUTANTS = ["no2", "so2", "co", "pm25"]


def _require_file(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path.name} not generated yet -- run the satellite calibration pipeline first")


@pytest.fixture(scope="session")
def metrics_df():
    path = PROCESSED_DIR / "calibration_model_metrics.csv"
    _require_file(path)
    return pd.read_csv(path, parse_dates=["train_start", "train_end", "test_start", "test_end"])


@pytest.fixture(scope="session")
def coverage_df():
    path = PROCESSED_DIR / "satellite_coverage_report.csv"
    _require_file(path)
    return pd.read_csv(path)


def test_every_pollutant_has_metrics(metrics_df):
    assert set(metrics_df["pollutant"]) == set(POLLUTANTS)


def test_metrics_are_not_null(metrics_df):
    assert metrics_df[["r2", "rmse", "mae"]].notna().all().all()


def test_train_test_dates_do_not_overlap(metrics_df):
    assert (metrics_df["train_end"] < metrics_df["test_start"]).all()


def test_coverage_percentages_in_range(coverage_df):
    assert coverage_df["coverage_pct"].between(0, 100).all()


def test_coverage_reported_for_every_pollutant(coverage_df):
    assert set(coverage_df["pollutant"]) == set(POLLUTANTS)


def test_no_forbidden_column_names(metrics_df, coverage_df):
    assert FORBIDDEN_COLUMNS.isdisjoint(metrics_df.columns)
    assert FORBIDDEN_COLUMNS.isdisjoint(coverage_df.columns)
