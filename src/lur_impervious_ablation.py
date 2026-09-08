"""Re-runs rolling-origin CV and leave-one-site-out validation under two
feature-set variants, to test whether `impervious_pct` acting as a de facto
site identifier (confirmed by the step-like SHAP-by-site pattern in
lur_site_feature_diagnostics.py) is actually what's breaking Milwaukee/NO2's
spatial transfer:

  - `no_impervious`: impervious_pct dropped entirely.
  - `multiscale_land_use`: impervious_pct replaced by the multi-scale
    impervious/road-density/land-cover-mix features from
    lur_multiscale_features.py (spatially smoother, not a single point value).

Run for both pilots (Madison included for comparison, even though its
ablation/PDP results didn't show the same site-identity signature).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT
from src.lur_model import PILOTS
from src.lur_rolling_cv import FOLD_BOUNDARIES, run_fold
from src.lur_site_holdout import run_holdout

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

MULTISCALE_COLS = [
    "impervious_pct_100m", "impervious_pct_300m", "impervious_pct_500m", "impervious_pct_1000m",
    "landcover_pct_developed", "landcover_pct_forest", "landcover_pct_agriculture",
    "landcover_pct_water", "landcover_pct_other",
    "road_density_100m", "road_density_300m", "road_density_500m", "road_density_1000m",
]

VARIANTS = {
    "baseline_full": {"drop_features": frozenset(), "extra_features": ()},
    "no_impervious": {"drop_features": frozenset({"impervious_pct"}), "extra_features": ()},
    "multiscale_land_use": {
        "drop_features": frozenset({"impervious_pct"}),
        "extra_features": tuple(MULTISCALE_COLS),
    },
}


def load_pilot_df(city: str, pollutant: str) -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
    df = df.dropna(subset=["concentration", "temperature_2m"])

    multiscale_path = PROCESSED_DIR / f"lur_multiscale_features_{city}.parquet"
    if multiscale_path.exists():
        multiscale = pd.read_parquet(multiscale_path)
        df = df.merge(multiscale, on="site_id", how="left")
    return df


def main() -> None:
    rolling_rows = []
    holdout_rows = []

    for city, pollutant in PILOTS:
        df = load_pilot_df(city, pollutant)
        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        satellite_col = f"satellite_{pollutant}"
        cross_col = f"cross_satellite_{other_pollutant}"

        for variant_name, kwargs in VARIANTS.items():
            for train_end, test_end in FOLD_BOUNDARIES:
                scored = run_fold(df, train_end, test_end, satellite_col, cross_col, **kwargs)
                for row in scored:
                    row.update({"city": city, "pollutant": pollutant, "variant": variant_name})
                rolling_rows.extend(scored)

            for site in sorted(df["site_id"].unique()):
                scored = run_holdout(df, site, satellite_col, cross_col, **kwargs)
                for row in scored:
                    row.update({"city": city, "pollutant": pollutant, "variant": variant_name})
                holdout_rows.extend(scored)

        print(f"\n{city}/{pollutant}: median rolling-fold R2 and site-holdout R2 by variant (HGB)")
        rolling_df = pd.DataFrame([r for r in rolling_rows if r["city"] == city and r["pollutant"] == pollutant])
        holdout_df = pd.DataFrame([r for r in holdout_rows if r["city"] == city and r["pollutant"] == pollutant])
        hgb_rolling = rolling_df[rolling_df["method"] == "model_hist_gradient_boosting"]
        hgb_holdout = holdout_df[holdout_df["method"] == "model_hist_gradient_boosting"]
        for variant_name in VARIANTS:
            median_rolling = hgb_rolling[hgb_rolling["variant"] == variant_name]["r2"].median()
            median_holdout = hgb_holdout[hgb_holdout["variant"] == variant_name]["r2"].median()
            print(f"  {variant_name}: rolling median R2={median_rolling:.3f}, site-holdout median R2={median_holdout:.3f}")

    rolling_out = pd.DataFrame(rolling_rows)
    rolling_out.to_csv(PROCESSED_DIR / "lur_rolling_cv_variants.csv", index=False)
    holdout_out = pd.DataFrame(holdout_rows)
    holdout_out.to_csv(PROCESSED_DIR / "lur_site_holdout_variants.csv", index=False)
    print(f"\nWrote lur_rolling_cv_variants.csv and lur_site_holdout_variants.csv")


if __name__ == "__main__":
    main()
