from pathlib import Path

import pandas as pd
import pytest

from src.validate import FORBIDDEN_COLUMNS

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
PILOTS = [("madison", "pm25"), ("milwaukee", "no2")]
BASELINE_PREFIX = "baseline_"
MODEL_PREFIX = "model_"


def _require_file(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path.name} not generated yet -- run the LUR pipeline first")


@pytest.fixture(scope="session")
def metrics_df():
    path = PROCESSED_DIR / "lur_model_metrics.csv"
    _require_file(path)
    return pd.read_csv(path, parse_dates=["train_start", "train_end", "test_start", "test_end"])


def test_every_pilot_has_metrics(metrics_df):
    pilots_present = set(zip(metrics_df["city"], metrics_df["pollutant"]))
    assert pilots_present == set(PILOTS)


def test_metrics_are_not_null(metrics_df):
    assert metrics_df[["r2", "rmse", "mae"]].notna().all().all()


def test_train_test_dates_do_not_overlap(metrics_df):
    assert (metrics_df["train_end"] < metrics_df["test_start"]).all()


def test_baselines_and_models_both_present(metrics_df):
    """Guards against a future run silently dropping the baseline comparison
    -- a model's R2 is meaningless here without the baselines it must beat."""
    for city, pollutant in PILOTS:
        subset = metrics_df[(metrics_df["city"] == city) & (metrics_df["pollutant"] == pollutant)]
        methods = set(subset["method"])
        assert any(m.startswith(BASELINE_PREFIX) for m in methods), f"{city}/{pollutant}: no baseline rows"
        assert any(m.startswith(MODEL_PREFIX) for m in methods), f"{city}/{pollutant}: no model rows"


def test_no_forbidden_column_names(metrics_df):
    assert FORBIDDEN_COLUMNS.isdisjoint(metrics_df.columns)
