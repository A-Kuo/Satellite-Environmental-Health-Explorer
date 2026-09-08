"""Rolling-origin temporal validation for the LUR pilots: proves the single
Jan-Sep/Oct-Dec split result wasn't a lucky split, by re-scoring across 8
expanding-window folds (train through April/test May, ... train through
Nov/test Dec).

Each fold is scored against per-fold baselines (global mean, persistence)
computed from that fold's own training data only -- not the full-year
baselines in lur_model.py -- so no fold ever sees test-period information.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT
from src.lur_model import PILOTS, prepare_features

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# (train-through month, test month), Apr-Nov train cutoffs -> May-Dec test months.
FOLD_BOUNDARIES = [
    ("2022-05-01", "2022-06-01"),
    ("2022-06-01", "2022-07-01"),
    ("2022-07-01", "2022-08-01"),
    ("2022-08-01", "2022-09-01"),
    ("2022-09-01", "2022-10-01"),
    ("2022-10-01", "2022-11-01"),
    ("2022-11-01", "2022-12-01"),
    ("2022-12-01", "2023-01-01"),
]

MODELS = {
    "model_random_forest": lambda: RandomForestRegressor(n_estimators=300, max_depth=8, random_state=0),
    "model_hist_gradient_boosting": lambda: HistGradientBoostingRegressor(max_depth=4, random_state=0),
}


def fold_baselines(train: pd.DataFrame, test: pd.DataFrame) -> list[dict]:
    y_train, y_test = train["concentration"], test["concentration"]
    global_mean = y_train.mean()

    full_series = (
        pd.concat([train[["site_id", "date", "concentration"]], test[["site_id", "date", "concentration"]]])
        .sort_values(["site_id", "date"])
    )
    full_series["persistence"] = full_series.groupby("site_id")["concentration"].shift(1)
    persistence_lookup = full_series.set_index(["site_id", "date"])["persistence"]
    persistence_preds = pd.Series(
        test.set_index(["site_id", "date"]).index.map(persistence_lookup), index=test.index
    ).fillna(global_mean)

    return [
        {"method": "baseline_global_mean", "preds": pd.Series(global_mean, index=test.index), "y_test": y_test},
        {"method": "baseline_persistence", "preds": persistence_preds, "y_test": y_test},
    ]


def score(entry: dict) -> dict:
    y_test, preds = entry["y_test"], entry["preds"]
    return {
        "method": entry["method"],
        "r2": r2_score(y_test, preds),
        "rmse": mean_squared_error(y_test, preds) ** 0.5,
        "mae": mean_absolute_error(y_test, preds),
    }


def run_fold(
    df: pd.DataFrame,
    train_end: str,
    test_end: str,
    satellite_col: str,
    cross_col: str,
    drop_features: frozenset[str] = frozenset(),
    extra_features: tuple[str, ...] = (),
) -> list[dict]:
    train = df[df["date"] < train_end].copy()
    test = df[(df["date"] >= train_end) & (df["date"] < test_end)].copy()
    if len(train) < 10 or len(test) < 5:
        return []

    entries = fold_baselines(train, test)

    train_feat, test_feat, feature_cols = prepare_features(
        train, test, satellite_col, cross_col, drop_features=drop_features, extra_features=extra_features
    )
    x_train, y_train = train_feat[feature_cols].to_numpy(), train_feat["concentration"].to_numpy()
    x_test = test_feat[feature_cols].to_numpy()
    for name, make_model in MODELS.items():
        model = make_model()
        model.fit(x_train, y_train)
        preds = pd.Series(model.predict(x_test), index=test_feat.index)
        entries.append({"method": name, "preds": preds, "y_test": test_feat["concentration"]})

    scored = [score(e) for e in entries]
    for row in scored:
        row["train_end"] = train_end
        row["test_month_start"] = train_end
        row["test_month_end"] = test_end
        row["n_train"] = len(train)
        row["n_test"] = len(test)
    return scored


def evaluate_promotion(rolling_df: pd.DataFrame, site_holdout_df: pd.DataFrame | None = None) -> dict:
    """Mechanically checks the user's promotion criteria that can be computed
    from these two tables; importance-plausibility stays a human judgment
    call reported elsewhere, not scored here."""
    verdict = {}
    for (city, pollutant), group in rolling_df.groupby(["city", "pollutant"]):
        model_rows = group[group["method"] == "model_hist_gradient_boosting"]
        baseline_rows = group[group["method"].str.startswith("baseline_")]

        beats_baseline_per_fold = []
        for fold in model_rows["test_month_start"].unique():
            model_r2 = model_rows[model_rows["test_month_start"] == fold]["r2"].iloc[0]
            fold_baselines_r2 = baseline_rows[baseline_rows["test_month_start"] == fold]["r2"]
            beats_baseline_per_fold.append(bool((model_r2 > fold_baselines_r2).all()))

        pct_folds_beating_baseline = sum(beats_baseline_per_fold) / len(beats_baseline_per_fold)
        median_r2 = model_rows["r2"].median()

        site_holdout_positive = None
        if site_holdout_df is not None:
            subset = site_holdout_df[
                (site_holdout_df["city"] == city)
                & (site_holdout_df["pollutant"] == pollutant)
                & (site_holdout_df["method"] == "model_hist_gradient_boosting")
            ]
            site_holdout_positive = bool((subset["r2"] > 0).all()) if len(subset) else None

        verdict[(city, pollutant)] = {
            "pct_folds_beating_all_baselines": pct_folds_beating_baseline,
            "median_fold_r2": median_r2,
            "site_holdout_all_positive": site_holdout_positive,
        }
    return verdict


def main() -> None:
    all_rows = []
    for city, pollutant in PILOTS:
        df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
        df = df.dropna(subset=["concentration", "temperature_2m"])

        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        satellite_col = f"satellite_{pollutant}"
        cross_col = f"cross_satellite_{other_pollutant}"

        for train_end, test_end in FOLD_BOUNDARIES:
            scored = run_fold(df, train_end, test_end, satellite_col, cross_col)
            for row in scored:
                row["city"] = city
                row["pollutant"] = pollutant
            all_rows.extend(scored)

    metrics_df = pd.DataFrame(all_rows)
    out_path = PROCESSED_DIR / "lur_rolling_cv.csv"
    metrics_df.to_csv(out_path, index=False)
    print(f"Wrote {out_path}")

    print("\nMedian fold R2 by pilot/method:")
    print(metrics_df.groupby(["city", "pollutant", "method"])["r2"].median().to_string())

    verdict = evaluate_promotion(metrics_df)
    print("\nPromotion-criteria summary (HGB, rolling folds only -- site holdout added separately):")
    for key, v in verdict.items():
        print(f"  {key}: {v}")


if __name__ == "__main__":
    main()
