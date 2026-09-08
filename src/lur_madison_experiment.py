"""Pre-registered Madison PM2.5 experiment -- see methodology.md's
"Pre-registered Madison PM2.5 experiment" subsection for the two hypotheses,
feature proxies, and success criteria, written and committed BEFORE this
module was run.

Two new features, both reusing already-authenticated/already-queried Earth
Engine collections (no new data source):
  - `surface_solar_radiation_downwards` (ERA5-Land daily mean) -- proxy for
    photochemical secondary-aerosol formation.
  - `absorbing_aerosol_index` (Sentinel-5P TROPOMI UV Aerosol Index, from the
    same COPERNICUS/S5P/OFFL/L3_NO2 collection already queried for Madison's
    cross-satellite NO2 predictor) -- standard operational wildfire-smoke/
    dust proxy.

Re-runs the exact same rolling-origin CV and leave-one-site-out logic
already used everywhere else in this project (`lur_rolling_cv.run_fold`,
`lur_site_holdout.run_holdout`), with these two features added via the
existing `extra_features` parameter -- no new validation methodology.
"""
from __future__ import annotations

from pathlib import Path

import ee
import pandas as pd

from src.ingest_lur_features import CITY_CONFIGS, authenticate
from src.ingest_satellite import _all_dates, _get_info_with_retry, END_DATE, START_DATE
from src.lur_impervious_ablation import load_pilot_df
from src.lur_rolling_cv import FOLD_BOUNDARIES, run_fold
from src.lur_site_holdout import run_holdout

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

CITY = "madison"
POLLUTANT = "pm25"
NEW_FEATURES = ("surface_solar_radiation_downwards", "absorbing_aerosol_index")


def _build_points_fc(sites: pd.DataFrame, buffer_m: int) -> ee.FeatureCollection:
    return ee.FeatureCollection(
        [
            ee.Feature(
                ee.Geometry.Point(row.longitude, row.latitude).buffer(buffer_m),
                {"site_id": row.site_id},
            )
            for row in sites.itertuples()
        ]
    )


def extract_solar_radiation(sites: pd.DataFrame) -> pd.DataFrame:
    points_fc = _build_points_fc(sites, 500)
    ic = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY").select("surface_solar_radiation_downwards")
    rows = []
    for date_str in _all_dates(START_DATE, END_DATE):
        d = ee.Date(date_str)
        day_collection = ic.filterDate(d, d.advance(1, "day"))
        if day_collection.size().getInfo() == 0:
            for row in sites.itertuples():
                rows.append({"site_id": row.site_id, "date": date_str, "surface_solar_radiation_downwards": None})
            continue
        mean_img = day_collection.mean()
        reduced = mean_img.reduceRegions(collection=points_fc, reducer=ee.Reducer.mean(), scale=9000)
        info = _get_info_with_retry(reduced)
        for feature in info["features"]:
            props = feature["properties"]
            rows.append(
                {
                    "site_id": props.get("site_id"),
                    "date": date_str,
                    "surface_solar_radiation_downwards": props.get("mean"),
                }
            )
    return pd.DataFrame(rows)


def extract_aerosol_index(sites: pd.DataFrame) -> pd.DataFrame:
    points_fc = _build_points_fc(sites, 1000)
    ic = ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_NO2").select("absorbing_aerosol_index")
    rows = []
    for date_str in _all_dates(START_DATE, END_DATE):
        d = ee.Date(date_str)
        day_collection = ic.filterDate(d, d.advance(1, "day"))
        if day_collection.size().getInfo() == 0:
            for row in sites.itertuples():
                rows.append({"site_id": row.site_id, "date": date_str, "absorbing_aerosol_index": None})
            continue
        day_image = day_collection.mosaic()
        reduced = day_image.reduceRegions(collection=points_fc, reducer=ee.Reducer.mean(), scale=1113)
        info = _get_info_with_retry(reduced)
        for feature in info["features"]:
            props = feature["properties"]
            rows.append(
                {"site_id": props.get("site_id"), "date": date_str, "absorbing_aerosol_index": props.get("mean")}
            )
    return pd.DataFrame(rows)


def build_experiment_dataset() -> pd.DataFrame:
    df = load_pilot_df(CITY, POLLUTANT)
    sites = df.drop_duplicates("site_id")[["site_id", "latitude", "longitude"]]

    solar_path = PROCESSED_DIR / "lur_madison_solar_radiation.parquet"
    if solar_path.exists():
        solar_df = pd.read_parquet(solar_path)
    else:
        authenticate()
        solar_df = extract_solar_radiation(sites)
        solar_df.to_parquet(solar_path, index=False)

    aai_path = PROCESSED_DIR / "lur_madison_aerosol_index.parquet"
    if aai_path.exists():
        aai_df = pd.read_parquet(aai_path)
    else:
        authenticate()
        aai_df = extract_aerosol_index(sites)
        aai_df.to_parquet(aai_path, index=False)

    solar_df["date"] = pd.to_datetime(solar_df["date"])
    aai_df["date"] = pd.to_datetime(aai_df["date"])
    df = df.merge(solar_df, on=["site_id", "date"], how="left").merge(aai_df, on=["site_id", "date"], how="left")
    return df


def main() -> None:
    df = build_experiment_dataset()
    for feature in NEW_FEATURES:
        coverage = df[feature].notna().mean()
        print(f"{feature}: {coverage:.1%} coverage")

    satellite_col, cross_col = "satellite_pm25", "cross_satellite_no2"

    rolling_rows = []
    for train_end, test_end in FOLD_BOUNDARIES:
        scored = run_fold(df, train_end, test_end, satellite_col, cross_col, extra_features=NEW_FEATURES)
        for row in scored:
            row.update({"city": CITY, "pollutant": POLLUTANT})
        rolling_rows.extend(scored)

    holdout_rows = []
    for site in sorted(df["site_id"].unique()):
        scored = run_holdout(df, site, satellite_col, cross_col, extra_features=NEW_FEATURES)
        for row in scored:
            row.update({"city": CITY, "pollutant": POLLUTANT})
        holdout_rows.extend(scored)

    rolling_df = pd.DataFrame(rolling_rows)
    holdout_df = pd.DataFrame(holdout_rows)

    hgb_rolling = rolling_df[rolling_df["method"] == "model_hist_gradient_boosting"]
    hgb_baselines = rolling_df[rolling_df["method"].str.startswith("baseline_")]
    beats_all = []
    for fold in hgb_rolling["test_month_start"].unique():
        model_r2 = hgb_rolling[hgb_rolling["test_month_start"] == fold]["r2"].iloc[0]
        fold_baseline_r2 = hgb_baselines[hgb_baselines["test_month_start"] == fold]["r2"]
        beats_all.append(bool((model_r2 > fold_baseline_r2).all()))
    pct_folds_beating_baseline = sum(beats_all) / len(beats_all)
    median_rolling_r2 = hgb_rolling["r2"].median()

    hgb_holdout = holdout_df[holdout_df["method"] == "model_hist_gradient_boosting"]
    median_holdout_r2 = hgb_holdout["r2"].median()

    print(f"\nWith {NEW_FEATURES} added:")
    print(f"  Rolling median R2: {median_rolling_r2:.3f} (was 0.178 before)")
    print(f"  % folds beating all baselines: {pct_folds_beating_baseline:.1%} (was 37.5% before)")
    print(f"  Site-holdout median R2: {median_holdout_r2:.3f} (was 0.687 before)")

    promoted = pct_folds_beating_baseline >= 0.75 and median_rolling_r2 > 0.3
    print(f"\nPre-specified promotion criteria met: {promoted}")

    rolling_df.to_csv(PROCESSED_DIR / "lur_madison_experiment_rolling_cv.csv", index=False)
    holdout_df.to_csv(PROCESSED_DIR / "lur_madison_experiment_site_holdout.csv", index=False)

    summary = pd.DataFrame(
        [
            {
                "city": CITY,
                "pollutant": POLLUTANT,
                "features_added": ", ".join(NEW_FEATURES),
                "rolling_median_r2_before": 0.178,
                "rolling_median_r2_after": median_rolling_r2,
                "pct_folds_beating_baseline_before": 0.375,
                "pct_folds_beating_baseline_after": pct_folds_beating_baseline,
                "site_holdout_median_r2_before": 0.687,
                "site_holdout_median_r2_after": median_holdout_r2,
                "promoted": promoted,
            }
        ]
    )
    summary.to_csv(PROCESSED_DIR / "lur_madison_experiment_results.csv", index=False)
    print(f"\nWrote lur_madison_experiment_results.csv")


if __name__ == "__main__":
    main()
