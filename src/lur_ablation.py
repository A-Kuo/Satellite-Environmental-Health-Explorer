"""Feature-family ablation: retrains HistGradientBoostingRegressor (the
candidate model; random forest is the robustness benchmark, not the subject
of this diagnostic) on the standard Jan-Sep/Oct-Dec split with one feature
family dropped at a time, so the R2 contribution of each family is directly
readable against the full-feature model.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT
from src.lur_model import PILOTS, prepare_features, temporal_split

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

METEOROLOGY_COLS = [
    "temperature_2m", "relative_humidity_pct", "wind_speed_ms", "wind_direction_deg",
    "total_precipitation", "boundary_layer_height",
]
LAND_USE_COLS = ["impervious_pct", "elevation_m", "dist_to_major_road_km"]
TIME_COLS = ["doy_sin", "doy_cos", "is_weekend", "is_heating_season"]
# satellite family is pilot-specific (own + cross pollutant columns), resolved in main()


def _base_name(col: str) -> str:
    return col[: -len("_missing")] if col.endswith("_missing") else col


def ablate(feature_cols: list[str], drop_base_names: set[str]) -> list[str]:
    return [c for c in feature_cols if _base_name(c) not in drop_base_names]


def fit_and_score(train, test, feature_cols) -> dict:
    x_train, y_train = train[feature_cols].to_numpy(), train["concentration"].to_numpy()
    x_test, y_test = test[feature_cols].to_numpy(), test["concentration"].to_numpy()
    model = HistGradientBoostingRegressor(max_depth=4, random_state=0)
    model.fit(x_train, y_train)
    preds = model.predict(x_test)
    return {
        "r2": r2_score(y_test, preds),
        "rmse": mean_squared_error(y_test, preds) ** 0.5,
        "mae": mean_absolute_error(y_test, preds),
        "n_features": len(feature_cols),
    }


def main() -> None:
    all_rows = []
    for city, pollutant in PILOTS:
        df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
        df = df.dropna(subset=["concentration", "temperature_2m"])
        train, test = temporal_split(df)

        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        satellite_col = f"satellite_{pollutant}"
        cross_col = f"cross_satellite_{other_pollutant}"

        train_feat, test_feat, feature_cols = prepare_features(train, test, satellite_col, cross_col)

        families = {
            "satellite": {satellite_col, cross_col},
            "meteorology": set(METEOROLOGY_COLS),
            "land_use": set(LAND_USE_COLS),
            "time": set(TIME_COLS),
        }

        full_result = fit_and_score(train_feat, test_feat, feature_cols)
        full_result.update({"city": city, "pollutant": pollutant, "ablated_family": "none (full model)"})
        all_rows.append(full_result)
        print(f"{city}/{pollutant} [full model]: R2={full_result['r2']:.3f} ({full_result['n_features']} features)")

        for family_name, drop_names in families.items():
            ablated_cols = ablate(feature_cols, drop_names)
            result = fit_and_score(train_feat, test_feat, ablated_cols)
            result.update({"city": city, "pollutant": pollutant, "ablated_family": family_name})
            result["r2_drop_from_full"] = full_result["r2"] - result["r2"]
            all_rows.append(result)
            print(
                f"{city}/{pollutant} [-{family_name}]: R2={result['r2']:.3f} "
                f"(drop {result['r2_drop_from_full']:+.3f}, {result['n_features']} features)"
            )

    ablation_df = pd.DataFrame(all_rows)
    out_path = PROCESSED_DIR / "lur_ablation.csv"
    ablation_df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
