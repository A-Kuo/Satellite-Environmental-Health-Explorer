"""Leave-one-monitor-site-out validation: trains on all but one site's
full-year data, predicts the held-out site's full year. Tests whether the
model generalizes to an unseen location, not just a monitor's own history.

Only global-mean and season-mean baselines apply here -- persistence and
site-mean baselines are undefined for a site with zero training history.

Caveat, stated plainly rather than glossed over: Madison has only 2 sites (1
holdout pair), Milwaukee 3 (3 pairs). This is enough to check the model isn't
purely memorizing one site's offset, not enough to claim broad spatial
generalization across either city.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT
from src.lur_model import PILOTS, SEASON_MAP, prepare_features

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

MODELS = {
    "model_random_forest": lambda: RandomForestRegressor(n_estimators=300, max_depth=8, random_state=0),
    "model_hist_gradient_boosting": lambda: HistGradientBoostingRegressor(max_depth=4, random_state=0),
}


def score(y_test, preds, method) -> dict:
    return {
        "method": method,
        "r2": r2_score(y_test, preds),
        "rmse": mean_squared_error(y_test, preds) ** 0.5,
        "mae": mean_absolute_error(y_test, preds),
    }


def run_holdout(
    df: pd.DataFrame,
    held_out_site: str,
    satellite_col: str,
    cross_col: str,
    drop_features: frozenset[str] = frozenset(),
    extra_features: tuple[str, ...] = (),
) -> list[dict]:
    train = df[df["site_id"] != held_out_site].copy()
    test = df[df["site_id"] == held_out_site].copy()
    if len(train) < 10 or len(test) < 5:
        return []

    rows = []
    global_mean = train["concentration"].mean()
    rows.append(score(test["concentration"], pd.Series(global_mean, index=test.index), "baseline_global_mean"))

    season_means = train.assign(season=train["date"].dt.month.map(SEASON_MAP)).groupby("season")[
        "concentration"
    ].mean()
    test_season = test["date"].dt.month.map(SEASON_MAP)
    season_preds = test_season.map(season_means).fillna(global_mean)
    rows.append(score(test["concentration"], season_preds, "baseline_season_mean"))

    train_feat, test_feat, feature_cols = prepare_features(
        train, test, satellite_col, cross_col, drop_features=drop_features, extra_features=extra_features
    )
    x_train, y_train = train_feat[feature_cols].to_numpy(), train_feat["concentration"].to_numpy()
    x_test = test_feat[feature_cols].to_numpy()
    for name, make_model in MODELS.items():
        model = make_model()
        model.fit(x_train, y_train)
        preds = model.predict(x_test)
        rows.append(score(test_feat["concentration"], preds, name))

    for row in rows:
        row["held_out_site"] = held_out_site
        row["n_train"] = len(train)
        row["n_test"] = len(test)
    return rows


def main() -> None:
    all_rows = []
    for city, pollutant in PILOTS:
        df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
        df = df.dropna(subset=["concentration", "temperature_2m"])

        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        satellite_col = f"satellite_{pollutant}"
        cross_col = f"cross_satellite_{other_pollutant}"

        sites = sorted(df["site_id"].unique())
        print(f"{city}/{pollutant}: {len(sites)} sites -> {len(sites)} holdout folds")
        for site in sites:
            rows = run_holdout(df, site, satellite_col, cross_col)
            for row in rows:
                row["city"] = city
                row["pollutant"] = pollutant
            all_rows.extend(rows)

    metrics_df = pd.DataFrame(all_rows)
    out_path = PROCESSED_DIR / "lur_site_holdout.csv"
    metrics_df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")
    print(metrics_df.pivot_table(index=["city", "pollutant", "held_out_site"], columns="method", values="r2").to_string())


if __name__ == "__main__":
    main()
