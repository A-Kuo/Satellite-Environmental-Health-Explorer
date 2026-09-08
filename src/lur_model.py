"""Fits and evaluates LUR (Land Use Regression) models per city/pollutant
pilot, judged against multiple baselines -- not just the training mean --
per the user's own bar: "if a model can't beat a month/season-aware baseline,
it isn't operationally useful yet."

Same temporal split as the statewide calibration model (train Jan-Sep 2022,
test Oct-Dec 2022), but now with a full weather/land-use/road predictor stack
instead of a single satellite feature, and non-linear models (random forest,
histogram gradient boosting) instead of linear regression.

Note on baselines: the user's writeup asked for a "month-specific mean"
baseline. With one year of data split chronologically (train Jan-Sep, test
Oct-Dec), train and test share **no calendar months at all**, so a literal
month-of-year mean can't be estimated from training data for any test month.
A **meteorological-season mean** is used instead, which the split does
partially support: Sep (train) estimates a Fall mean applied to Oct/Nov
(test); Jan-Feb (train) estimate a Winter mean applied to Dec (test). This is
noted here and in methodology.md rather than silently substituted.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
PLOTS_DIR = PROCESSED_DIR / "lur_plots"

PILOTS = [("madison", "pm25"), ("milwaukee", "no2")]
TRAIN_TEST_SPLIT_DATE = "2022-10-01"

BASE_FEATURES = [
    "temperature_2m",
    "relative_humidity_pct",
    "wind_speed_ms",
    "wind_direction_deg",
    "total_precipitation",
    "boundary_layer_height",
    "impervious_pct",
    "elevation_m",
    "dist_to_major_road_km",
    "doy_sin",
    "doy_cos",
]
BOOL_FEATURES = ["is_weekend", "is_heating_season"]

SEASON_MAP = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
              6: "summer", 7: "summer", 8: "summer", 9: "fall", 10: "fall", 11: "fall"}

DISCLAIMER = "Calibration check: LUR-predicted vs. ground monitor, not a health/risk estimate."


def temporal_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = df[df["date"] < TRAIN_TEST_SPLIT_DATE].copy()
    test = df[df["date"] >= TRAIN_TEST_SPLIT_DATE].copy()
    return train, test


def prepare_features(
    train: pd.DataFrame,
    test: pd.DataFrame,
    satellite_col: str,
    cross_col: str,
    drop_features: frozenset[str] = frozenset(),
    extra_features: tuple[str, ...] = (),
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Median-impute (fit on train only) any feature with missing values and
    add a companion `<col>_missing` flag, so tree models never see NaN and
    the fact that a satellite retrieval was missing is itself usable signal.

    `drop_features` removes named base features (e.g. `impervious_pct`, for
    the site-transfer ablation); `extra_features` adds named columns already
    present in `train`/`test` (e.g. multi-scale land-use columns merged in
    beforehand) through the same impute-and-flag treatment.
    """
    numeric_features = [satellite_col, cross_col, *BASE_FEATURES, *extra_features]
    numeric_features = [c for c in numeric_features if c not in drop_features]
    train = train.copy()
    test = test.copy()
    feature_cols = []

    for col in numeric_features:
        missing_flag = f"{col}_missing"
        train[missing_flag] = train[col].isna()
        test[missing_flag] = test[col].isna()
        median = train[col].median()
        train[col] = train[col].fillna(median)
        test[col] = test[col].fillna(median)
        feature_cols.extend([col, missing_flag])

    feature_cols.extend(BOOL_FEATURES)
    for col in BOOL_FEATURES:
        train[col] = train[col].astype(float)
        test[col] = test[col].astype(float)

    return train, test, feature_cols


def compute_baselines(train: pd.DataFrame, test: pd.DataFrame) -> list[dict]:
    rows = []
    y_train = train["concentration"]
    y_test = test["concentration"]

    global_mean = y_train.mean()
    rows.append(("baseline_global_mean", pd.Series(global_mean, index=test.index)))

    season_means = train.assign(season=train["date"].dt.month.map(SEASON_MAP)).groupby("season")[
        "concentration"
    ].mean()
    test_season = test["date"].dt.month.map(SEASON_MAP)
    season_preds = test_season.map(season_means).fillna(global_mean)
    rows.append(("baseline_season_mean", season_preds))

    site_means = train.groupby("site_id")["concentration"].mean()
    site_preds = test["site_id"].map(site_means).fillna(global_mean)
    rows.append(("baseline_site_mean", site_preds))

    full_series = (
        pd.concat([train[["site_id", "date", "concentration"]], test[["site_id", "date", "concentration"]]])
        .sort_values(["site_id", "date"])
    )
    full_series["persistence"] = full_series.groupby("site_id")["concentration"].shift(1)
    persistence_lookup = full_series.set_index(["site_id", "date"])["persistence"]
    persistence_preds = test.set_index(["site_id", "date"]).index.map(persistence_lookup)
    persistence_preds = pd.Series(persistence_preds, index=test.index).fillna(global_mean)
    rows.append(("baseline_persistence", persistence_preds))

    return [{"method": name, "preds": preds, "y_test": y_test} for name, preds in rows]


def fit_models(train, test, feature_cols) -> list[dict]:
    x_train, y_train = train[feature_cols].to_numpy(), train["concentration"].to_numpy()
    x_test, y_test = test[feature_cols].to_numpy(), test["concentration"].to_numpy()

    models = {
        "model_random_forest": RandomForestRegressor(n_estimators=300, max_depth=8, random_state=0),
        "model_hist_gradient_boosting": HistGradientBoostingRegressor(max_depth=4, random_state=0),
    }
    results = []
    for name, model in models.items():
        model.fit(x_train, y_train)
        preds = pd.Series(model.predict(x_test), index=test.index)
        results.append({"method": name, "preds": preds, "y_test": test["concentration"]})
    return results


def score(entry: dict) -> dict:
    y_test, preds = entry["y_test"], entry["preds"]
    return {
        "method": entry["method"],
        "r2": r2_score(y_test, preds),
        "rmse": mean_squared_error(y_test, preds) ** 0.5,
        "mae": mean_absolute_error(y_test, preds),
    }


def plot_predicted_vs_actual(city, pollutant, best_entry, r2) -> None:
    y_test, preds = best_entry["y_test"], best_entry["preds"]
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_test, preds, alpha=0.5, s=14)
    lims = [min(y_test.min(), preds.min()), max(y_test.max(), preds.max())]
    ax.plot(lims, lims, "k--", linewidth=1, label="1:1")
    ax.set_xlabel(f"Ground-monitor {pollutant.upper()} (test set)")
    ax.set_ylabel(f"LUR-predicted ({best_entry['method']})")
    ax.set_title(f"{city.title()} {pollutant.upper()} LUR: predicted vs. actual (test R²={r2:.2f})")
    ax.legend()
    ax.annotate(DISCLAIMER, xy=(0.01, 0.01), xycoords="figure fraction", fontsize=7, color="dimgray")
    fig.tight_layout()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOTS_DIR / f"{city}_{pollutant}_predicted_vs_actual.png", dpi=150)
    plt.close(fig)


def main() -> None:
    all_rows = []
    for city, pollutant in PILOTS:
        df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
        df = df.dropna(subset=["concentration", "temperature_2m"])  # weather coverage should be near-complete

        train, test = temporal_split(df)
        if len(train) < 10 or len(test) < 10:
            print(f"{city}/{pollutant}: insufficient data (train={len(train)}, test={len(test)}), skipping")
            continue

        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        satellite_col = f"satellite_{pollutant}"
        cross_col = f"cross_satellite_{other_pollutant}"

        baseline_entries = compute_baselines(train, test)
        train_feat, test_feat, feature_cols = prepare_features(train, test, satellite_col, cross_col)
        model_entries = fit_models(train_feat, test_feat, feature_cols)

        entries = baseline_entries + model_entries
        scored = [score(e) for e in entries]
        for row in scored:
            row["city"] = city
            row["pollutant"] = pollutant
            row["n_train"] = len(train)
            row["n_test"] = len(test)
            row["train_start"], row["train_end"] = train["date"].min(), train["date"].max()
            row["test_start"], row["test_end"] = test["date"].min(), test["date"].max()
        all_rows.extend(scored)

        for row in scored:
            print(f"{city}/{pollutant} [{row['method']}]: R2={row['r2']:.3f} RMSE={row['rmse']:.3f} MAE={row['mae']:.3f}")

        best = max(entries, key=lambda e: r2_score(e["y_test"], e["preds"]))
        best_r2 = r2_score(best["y_test"], best["preds"])
        plot_predicted_vs_actual(city, pollutant, best, best_r2)

    metrics_df = pd.DataFrame(all_rows)
    out_path = PROCESSED_DIR / "lur_model_metrics.csv"
    metrics_df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
