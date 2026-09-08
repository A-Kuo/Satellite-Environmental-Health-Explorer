"""Two checks in one module, both about whether a point forecast overstates
what the model actually knows:

1. A season-aware persistence baseline (7-day trailing per-site mean, causal
   -- only past data) compared against the existing single-previous-day
   persistence baseline, on both the standard split and the rolling folds.
2. Quantile regression (HistGradientBoostingRegressor, 10th/50th/90th
   percentiles) on the standard split, reporting empirical interval coverage
   -- if the model is only conditionally useful in some regimes, this shows
   up as coverage well off the nominal 80%, and can be broken out by season.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT
from src.lur_model import PILOTS, SEASON_MAP, prepare_features, temporal_split
from src.lur_rolling_cv import FOLD_BOUNDARIES

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

TRAILING_WINDOW_DAYS = 7


def trailing_mean_persistence(df: pd.DataFrame) -> pd.Series:
    """Causal 7-day trailing per-site mean: only uses observations strictly
    before each date, so it's usable as a same-day prediction with no
    look-ahead."""
    df = df.sort_values(["site_id", "date"])
    trailing = (
        df.groupby("site_id")["concentration"]
        .apply(lambda s: s.shift(1).rolling(TRAILING_WINDOW_DAYS, min_periods=1).mean())
    )
    return trailing.reset_index(level=0, drop=True).reindex(df.index)


def score(y_test, preds, method) -> dict:
    return {
        "method": method,
        "r2": r2_score(y_test, preds),
        "rmse": mean_squared_error(y_test, preds) ** 0.5,
        "mae": mean_absolute_error(y_test, preds),
    }


def compare_persistence_baselines(city: str, pollutant: str) -> list[dict]:
    df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
    df = df.dropna(subset=["concentration", "temperature_2m"])
    df["trailing_7day"] = trailing_mean_persistence(df)

    rows = []

    def _score_window(train, test, label):
        y_test = test["concentration"]
        single_day = (
            pd.concat([train[["site_id", "date", "concentration"]], test[["site_id", "date", "concentration"]]])
            .sort_values(["site_id", "date"])
        )
        single_day["persistence_1day"] = single_day.groupby("site_id")["concentration"].shift(1)
        lookup = single_day.set_index(["site_id", "date"])["persistence_1day"]
        preds_1day = pd.Series(test.set_index(["site_id", "date"]).index.map(lookup), index=test.index)
        preds_1day = preds_1day.fillna(train["concentration"].mean())

        preds_7day = test["trailing_7day"].fillna(train["concentration"].mean())

        row_1day = score(y_test, preds_1day, "baseline_persistence_1day")
        row_7day = score(y_test, preds_7day, "baseline_persistence_7day_trailing")
        row_1day["window"] = row_7day["window"] = label
        return [row_1day, row_7day]

    train, test = temporal_split(df)
    rows.extend(_score_window(train, test, "standard_split"))

    for train_end, test_end in FOLD_BOUNDARIES:
        fold_train = df[df["date"] < train_end]
        fold_test = df[(df["date"] >= train_end) & (df["date"] < test_end)]
        if len(fold_train) < 10 or len(fold_test) < 5:
            continue
        rows.extend(_score_window(fold_train, fold_test, f"fold_test_{train_end}"))

    for row in rows:
        row["city"] = city
        row["pollutant"] = pollutant
    return rows


def quantile_coverage(city: str, pollutant: str) -> dict:
    df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
    df = df.dropna(subset=["concentration", "temperature_2m"])
    train, test = temporal_split(df)

    other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
    satellite_col = f"satellite_{pollutant}"
    cross_col = f"cross_satellite_{other_pollutant}"
    train_feat, test_feat, feature_cols = prepare_features(train, test, satellite_col, cross_col)
    x_train, y_train = train_feat[feature_cols].to_numpy(), train_feat["concentration"].to_numpy()
    x_test = test_feat[feature_cols].to_numpy()

    preds = {}
    for q in (0.1, 0.5, 0.9):
        model = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=4, random_state=0)
        model.fit(x_train, y_train)
        preds[q] = model.predict(x_test)

    y_test = test_feat["concentration"].to_numpy()
    inside = (y_test >= preds[0.1]) & (y_test <= preds[0.9])
    test_feat = test_feat.copy()
    test_feat["inside_interval"] = inside
    test_feat["season"] = test_feat["date"].dt.month.map(SEASON_MAP)

    overall_coverage = inside.mean()
    by_season = test_feat.groupby("season")["inside_interval"].mean()

    return {
        "city": city,
        "pollutant": pollutant,
        "nominal_coverage": 0.8,
        "overall_empirical_coverage": overall_coverage,
        **{f"coverage_{season}": val for season, val in by_season.items()},
    }


def main() -> None:
    persistence_rows = []
    coverage_rows = []
    for city, pollutant in PILOTS:
        persistence_rows.extend(compare_persistence_baselines(city, pollutant))
        coverage = quantile_coverage(city, pollutant)
        coverage_rows.append(coverage)
        print(f"{city}/{pollutant}: quantile [10,90] coverage = {coverage['overall_empirical_coverage']:.1%} (nominal 80%)")
        for k, v in coverage.items():
            if k.startswith("coverage_"):
                print(f"    {k}: {v:.1%}")

    persistence_df = pd.DataFrame(persistence_rows)
    persistence_out = PROCESSED_DIR / "lur_persistence_comparison.csv"
    persistence_df.to_csv(persistence_out, index=False)
    print(f"\nWrote {persistence_out}")

    print("\nStandard-split persistence comparison:")
    print(
        persistence_df[persistence_df["window"] == "standard_split"][
            ["city", "pollutant", "method", "r2", "rmse", "mae"]
        ].to_string(index=False)
    )

    coverage_df = pd.DataFrame(coverage_rows)
    coverage_out = PROCESSED_DIR / "lur_quantile_coverage.csv"
    coverage_df.to_csv(coverage_out, index=False)
    print(f"\nWrote {coverage_out}")


if __name__ == "__main__":
    main()
