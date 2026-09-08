from pathlib import Path

import pandas as pd
import pytest

from src.lur_model import PILOTS
from src.validate import FORBIDDEN_COLUMNS

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


def _require_file(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        pytest.skip(f"{path.name} not generated yet -- run the LUR validation pipeline first")
    return None


@pytest.fixture(scope="session")
def rolling_cv_df():
    path = PROCESSED_DIR / "lur_rolling_cv.csv"
    _require_file(path)
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def site_holdout_df():
    path = PROCESSED_DIR / "lur_site_holdout.csv"
    _require_file(path)
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def ablation_df():
    path = PROCESSED_DIR / "lur_ablation.csv"
    _require_file(path)
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def residual_summary_df():
    path = PROCESSED_DIR / "lur_residual_summary.csv"
    _require_file(path)
    return pd.read_csv(path)


def test_rolling_cv_has_eight_folds_per_pilot(rolling_cv_df):
    for city, pollutant in PILOTS:
        subset = rolling_cv_df[(rolling_cv_df["city"] == city) & (rolling_cv_df["pollutant"] == pollutant)]
        assert subset["test_month_start"].nunique() == 8, f"{city}/{pollutant}: expected 8 rolling folds"


def test_rolling_cv_no_null_metrics(rolling_cv_df):
    assert rolling_cv_df[["r2", "rmse", "mae"]].notna().all().all()


def test_site_holdout_covers_every_site(site_holdout_df):
    for city, pollutant in PILOTS:
        sites_in_dataset = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")["site_id"]
        sites_in_dataset = set(sites_in_dataset.astype(str).unique())
        sites_held_out = site_holdout_df[
            (site_holdout_df["city"] == city) & (site_holdout_df["pollutant"] == pollutant)
        ]["held_out_site"]
        sites_held_out = set(sites_held_out.astype(str).unique())
        assert sites_held_out == sites_in_dataset, f"{city}/{pollutant}: not every site was held out"


def test_ablation_includes_full_model_and_all_families(ablation_df):
    expected_families = {"none (full model)", "satellite", "meteorology", "land_use", "time"}
    for city, pollutant in PILOTS:
        subset = ablation_df[(ablation_df["city"] == city) & (ablation_df["pollutant"] == pollutant)]
        assert set(subset["ablated_family"]) == expected_families, f"{city}/{pollutant}: missing ablation rows"


def test_residual_summary_has_site_and_season_breakdowns(residual_summary_df):
    for city, pollutant in PILOTS:
        subset = residual_summary_df[
            (residual_summary_df["city"] == city) & (residual_summary_df["pollutant"] == pollutant)
        ]
        assert "site" in set(subset["group_type"]), f"{city}/{pollutant}: missing per-site residual breakdown"
        assert "season" in set(subset["group_type"]), f"{city}/{pollutant}: missing per-season residual breakdown"


def test_no_forbidden_column_names(rolling_cv_df, site_holdout_df, ablation_df, residual_summary_df):
    for df in (rolling_cv_df, site_holdout_df, ablation_df, residual_summary_df):
        assert FORBIDDEN_COLUMNS.isdisjoint(df.columns)
