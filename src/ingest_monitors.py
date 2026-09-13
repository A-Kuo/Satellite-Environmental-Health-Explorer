"""Builds the contextual air-monitor point layer from EPA AQS daily data --
replaces the earlier Wisconsin-DNR-specific ArcGIS layer (build_dnr_points in
src/spatial_join.py) with a state-agnostic source that works for every state
in src/states.py, Wisconsin included.

Needs NO new download: data/raw/aqs_daily_{42101,42401,42602,88101}_2022.zip
are national-scope files already cached on disk from the satellite
calibration workstream (src/ingest_ground_truth.py). This module just reads
them again and filters by a different state's FIPS code.

Output schema matches the original wi_dnr_points.parquet exactly (point_id,
name, point_type, latitude, longitude, pollutant_or_permit_type,
reporting_year, source_url) so app/components/map.py needs no schema
changes. Two real differences from the old WI DNR layer, both documented in
methodology.md: `point_type` is always "air_monitor" now (AQS has no
permitted-facility-equivalent point type), and `reporting_year` is the real
data year (2022) rather than a live-snapshot pull date.
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import pandas as pd

from src.states import get_state

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

YEAR = 2022

# AQS parameter code -> pollutant label. Same 4 pollutants already cached by
# src/ingest_ground_truth.py for the calibration workstream.
POLLUTANTS = {
    "42602": "NO2",
    "42401": "SO2",
    "42101": "CO",
    "88101": "PM2.5",
}

SOURCE_URL = f"https://aqs.epa.gov/aqsweb/airdata/daily_88101_{YEAR}.zip"


def _read_daily_zip(param: str) -> pd.DataFrame:
    zip_path = RAW_DIR / f"aqs_daily_{param}_{YEAR}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(
            f"{zip_path} not found -- run src/ingest_ground_truth.py first "
            "(it caches the national AQS daily files this module reads)."
        )
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as f:
            return pd.read_csv(
                f,
                low_memory=False,
                usecols=["State Code", "County Code", "Site Num", "Latitude", "Longitude"],
            )


def build_monitor_points(state) -> pd.DataFrame:
    rows_by_site: dict[str, dict] = {}

    for param, pollutant_name in POLLUTANTS.items():
        df = _read_daily_zip(param)
        state_df = df[df["State Code"].astype(str).str.zfill(2) == state.fips].copy()
        if state_df.empty:
            continue

        state_df["site_id"] = (
            state_df["State Code"].astype(str).str.zfill(2)
            + state_df["County Code"].astype(str).str.zfill(3)
            + state_df["Site Num"].astype(str).str.zfill(4)
        )
        for site_id, group in state_df.groupby("site_id"):
            if site_id not in rows_by_site:
                rows_by_site[site_id] = {
                    "point_id": site_id,
                    "name": f"AQS Site {site_id}",
                    "point_type": "air_monitor",
                    "latitude": group["Latitude"].iloc[0],
                    "longitude": group["Longitude"].iloc[0],
                    "pollutants": set(),
                    "reporting_year": YEAR,
                    "source_url": SOURCE_URL,
                    "state_abbr": state.abbr,
                }
            rows_by_site[site_id]["pollutants"].add(pollutant_name)

    rows = []
    for site in rows_by_site.values():
        site = dict(site)
        site["pollutant_or_permit_type"] = ", ".join(sorted(site.pop("pollutants")))
        rows.append(site)

    ordered_cols = [
        "point_id", "name", "point_type", "latitude", "longitude",
        "pollutant_or_permit_type", "reporting_year", "source_url", "state_abbr",
    ]
    return pd.DataFrame(rows)[ordered_cols] if rows else pd.DataFrame(columns=ordered_cols)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="WI", help="State abbreviation, e.g. WI, MN")
    args = parser.parse_args()
    state = get_state(args.state)

    out_path = PROCESSED_DIR / f"{state.abbr.lower()}_monitor_points.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = build_monitor_points(state)
    out.to_parquet(out_path, index=False)
    print(f"Wrote {len(out):,} rows -> {out_path}")


if __name__ == "__main__":
    main()
