from pathlib import Path

import pandas as pd
import pytest

from src.lur_model import PILOTS
from src.validate import FORBIDDEN_COLUMNS

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


def _require_file(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path.name} not generated yet -- run the LUR diagnosis pipeline first")


@pytest.fixture(scope="session")
def rolling_cv_variants_df():
    path = PROCESSED_DIR / "lur_rolling_cv_variants.csv"
    _require_file(path)
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def site_holdout_variants_df():
    path = PROCESSED_DIR / "lur_site_holdout_variants.csv"
    _require_file(path)
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def mixed_effects_df():
    path = PROCESSED_DIR / "lur_mixed_effects.csv"
    _require_file(path)
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def quantile_coverage_df():
    path = PROCESSED_DIR / "lur_quantile_coverage.csv"
    _require_file(path)
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def persistence_comparison_df():
    path = PROCESSED_DIR / "lur_persistence_comparison.csv"
    _require_file(path)
    return pd.read_csv(path)


EXPECTED_VARIANTS = {"baseline_full", "no_impervious", "multiscale_land_use"}


def test_ablation_variants_present(rolling_cv_variants_df, site_holdout_variants_df):
    assert set(rolling_cv_variants_df["variant"]) == EXPECTED_VARIANTS
    assert set(site_holdout_variants_df["variant"]) == EXPECTED_VARIANTS


def test_mixed_effects_has_icc_for_every_pilot(mixed_effects_df):
    pilots_present = set(zip(mixed_effects_df["city"], mixed_effects_df["pollutant"]))
    assert pilots_present == set(PILOTS)
    assert mixed_effects_df["icc_between_site_share"].between(0, 1).all()


def test_quantile_coverage_has_nominal_and_empirical(quantile_coverage_df):
    assert (quantile_coverage_df["nominal_coverage"] == 0.8).all()
    assert quantile_coverage_df["overall_empirical_coverage"].between(0, 1).all()


def test_persistence_comparison_has_both_baselines(persistence_comparison_df):
    standard = persistence_comparison_df[persistence_comparison_df["window"] == "standard_split"]
    for city, pollutant in PILOTS:
        methods = set(standard[(standard["city"] == city) & (standard["pollutant"] == pollutant)]["method"])
        assert "baseline_persistence_1day" in methods
        assert "baseline_persistence_7day_trailing" in methods


def test_no_forbidden_column_names(
    rolling_cv_variants_df, site_holdout_variants_df, mixed_effects_df, quantile_coverage_df, persistence_comparison_df
):
    for df in (
        rolling_cv_variants_df, site_holdout_variants_df, mixed_effects_df, quantile_coverage_df, persistence_comparison_df,
    ):
        assert FORBIDDEN_COLUMNS.isdisjoint(df.columns)


@pytest.fixture(scope="session")
def madison_experiment_df():
    path = PROCESSED_DIR / "lur_madison_experiment_results.csv"
    _require_file(path)
    return pd.read_csv(path)


def test_madison_experiment_reports_before_and_after(madison_experiment_df):
    row = madison_experiment_df.iloc[0]
    assert row["city"] == "madison" and row["pollutant"] == "pm25"
    for col in (
        "rolling_median_r2_before", "rolling_median_r2_after",
        "pct_folds_beating_baseline_before", "pct_folds_beating_baseline_after",
        "site_holdout_median_r2_before", "site_holdout_median_r2_after",
    ):
        assert pd.notna(row[col])
    assert row["promoted"] in (True, False)


def test_madison_experiment_no_forbidden_column_names(madison_experiment_df):
    assert FORBIDDEN_COLUMNS.isdisjoint(madison_experiment_df.columns)
