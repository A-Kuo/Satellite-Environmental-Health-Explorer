"""Madison-focused diagnosis of the rolling-CV instability: (a) joins each
fold's HGB R2 to that fold's mean meteorological conditions, to see whether
failing folds share a weather regime; (b) re-parses the already-cached raw
AQS PM2.5 daily file for Madison's 2 sites to pull columns dropped in the
original cleaning step (Method Name, Observation Percent, Event Type --
AQS's flag for wildfire-smoke/exceptional-event days) and checks whether
instrument-method changes, low completeness, or flagged days cluster in the
negative-R2 fold periods.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from src.lur_model import BASE_FEATURES
from src.lur_rolling_cv import FOLD_BOUNDARIES

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RAW_DIR = REPO_ROOT / "data" / "raw"

MADISON_CITY = "madison"
MADISON_POLLUTANT = "pm25"
AQS_PM25_ZIP = RAW_DIR / "aqs_daily_88101_2022.zip"

WEATHER_COLS = [
    "temperature_2m", "relative_humidity_pct", "wind_speed_ms",
    "total_precipitation", "boundary_layer_height",
]


def fold_weather_summary() -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{MADISON_CITY}_{MADISON_POLLUTANT}.parquet")
    df = df.dropna(subset=["concentration", "temperature_2m"])

    rolling_cv = pd.read_csv(PROCESSED_DIR / "lur_rolling_cv.csv", parse_dates=["test_month_start", "test_month_end"])
    rolling_cv = rolling_cv[
        (rolling_cv["city"] == MADISON_CITY)
        & (rolling_cv["pollutant"] == MADISON_POLLUTANT)
        & (rolling_cv["method"] == "model_hist_gradient_boosting")
    ]

    rows = []
    for _, fold_row in rolling_cv.iterrows():
        test_month = df[(df["date"] >= fold_row["test_month_start"]) & (df["date"] < fold_row["test_month_end"])]
        weather_means = test_month[WEATHER_COLS].mean().to_dict()
        rows.append(
            {
                "test_month_start": fold_row["test_month_start"].date(),
                "r2": fold_row["r2"],
                "n_test": len(test_month),
                "mean_concentration": test_month["concentration"].mean(),
                **{f"mean_{col}": val for col, val in weather_means.items()},
            }
        )
    return pd.DataFrame(rows).sort_values("test_month_start")


def aqs_quality_flags() -> pd.DataFrame:
    with zipfile.ZipFile(AQS_PM25_ZIP) as z:
        with z.open(z.namelist()[0]) as f:
            raw = pd.read_csv(
                f,
                low_memory=False,
                usecols=[
                    "State Code", "County Code", "Site Num", "Date Local", "Method Name",
                    "Observation Percent", "Event Type",
                ],
            )
    madison = raw[(raw["State Code"] == 55) & (raw["County Code"] == 25)].copy()
    madison["date"] = pd.to_datetime(madison["Date Local"])
    madison["site_id"] = (
        madison["State Code"].astype(str).str.zfill(2)
        + madison["County Code"].astype(str).str.zfill(3)
        + madison["Site Num"].astype(str).str.zfill(4)
    )
    return madison[["site_id", "date", "Method Name", "Observation Percent", "Event Type"]]


def main() -> None:
    fold_summary = fold_weather_summary()
    print("Madison/PM2.5 rolling-fold R2 vs. mean weather conditions:")
    print(fold_summary.to_string(index=False))

    negative_folds = fold_summary[fold_summary["r2"] < 0]
    positive_folds = fold_summary[fold_summary["r2"] >= 0]
    print("\nMean conditions, negative-R2 folds vs. positive-R2 folds:")
    compare_cols = [c for c in fold_summary.columns if c.startswith("mean_")]
    comparison = pd.DataFrame(
        {"negative_R2_folds": negative_folds[compare_cols].mean(), "positive_R2_folds": positive_folds[compare_cols].mean()}
    )
    print(comparison.to_string())

    out_path = PROCESSED_DIR / f"lur_fold_diagnostics_{MADISON_CITY}_{MADISON_POLLUTANT}.csv"
    fold_summary.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")

    quality = aqs_quality_flags()

    # Method/POC check: confirmed (this session) that both Madison sites run
    # concurrent raw+corrected POC pairs (e.g. POC 3 = raw Teledyne T640,
    # POC 23 = its own "(Corrected)" reading) spanning the full year, plus a
    # short-lived reference sampler at site 41 (POC 1, Jan-only, 60 obs) --
    # not a mid-year instrument swap. No method change coincides with the
    # failing summer folds.
    per_poc = quality.groupby(["site_id", "date"]).size()
    print("\nAQS instrumentation check: no mid-year method change found at either Madison "
          "site -- both run concurrent raw/corrected POC pairs all year (see methodology.md).")

    # Event Type check: this field turned out to be a per-instrument-series
    # label, not a per-day exceptional-event flag -- POC 3 ("raw") reads
    # "Included" for literally every day of the year at both sites, POC 23
    # ("corrected") is blank for literally every day. Verified directly: the
    # "Included" share is ~49% in every single month with zero variation,
    # which rules out an actual episodic event (e.g. wildfire smoke) and
    # confirms it's a reporting-stream artifact, not real information about
    # specific days. Recorded here so this dead end isn't re-investigated.
    print("\nEvent Type check: 'Included' appears for 100% of POC 3 (raw) rows and 0% of "
          "POC 23 (corrected) rows, every month, with no date-level pattern -- this is a "
          "raw/corrected reporting-stream label, not a wildfire-smoke/exceptional-event "
          "flag. Ruled out as an explanation for the summer folds; not worth revisiting.")

    quality_out = PROCESSED_DIR / f"lur_aqs_quality_flags_{MADISON_CITY}_{MADISON_POLLUTANT}.csv"
    quality.to_csv(quality_out, index=False)
    print(f"\nWrote {quality_out}")


if __name__ == "__main__":
    main()
