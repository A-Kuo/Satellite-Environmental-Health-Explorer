"""Extracts daily satellite-observed pollutant proxies at Wisconsin AQS
ground-monitor locations via Google Earth Engine.

Requires a GEE-enabled GCP project and a service-account JSON key placed at
`.env/*.json` (gitignored). See methodology.md for why raw Sentinel-5P/MODIS
data can't be pulled anonymously.
"""
from __future__ import annotations

import glob
import json
import time
from pathlib import Path

import ee
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
ENV_DIR = REPO_ROOT / ".env"

YEAR = 2022
START_DATE = f"{YEAR}-01-01"
END_DATE = f"{YEAR + 1}-01-01"
POINT_BUFFER_M = 1000  # 1 km buffer around each monitor point

# pollutant -> (Earth Engine ImageCollection id, band name, reduction scale in meters)
SATELLITE_PRODUCTS = {
    "no2": ("COPERNICUS/S5P/OFFL/L3_NO2", "tropospheric_NO2_column_number_density", 1113),
    "so2": ("COPERNICUS/S5P/OFFL/L3_SO2", "SO2_column_number_density", 1113),
    "co": ("COPERNICUS/S5P/OFFL/L3_CO", "CO_column_number_density", 1113),
    # MODIS/Terra+Aqua combined MAIAC daily AOD at 1 km resolution. The daily
    # global MOD08_D3/MYD08_D3 products used in earlier drafts of this pipeline
    # are no longer published to the Earth Engine public catalog (only their
    # monthly M3 successors remain) -- MCD19A2_GRANULES is the correct current
    # daily product, at the cost of needing its own QA-bitmask cloud masking
    # (see `_mcd19a2_qa_masked` below) instead of a pre-filtered band.
    "pm25": ("MODIS/061/MCD19A2_GRANULES", "Optical_Depth_055", 1000),
}


def authenticate() -> None:
    key_paths = glob.glob(str(ENV_DIR / "*.json"))
    if not key_paths:
        raise FileNotFoundError(
            f"No service-account JSON key found in {ENV_DIR}. "
            "Place the GEE service-account key there (gitignored) before running this module."
        )
    key_path = key_paths[0]
    with open(key_path) as f:
        key = json.load(f)

    creds = ee.ServiceAccountCredentials(key["client_email"], key_path)
    ee.Initialize(creds, project=key["project_id"])


def load_sites(pollutant: str) -> pd.DataFrame:
    ground_truth_path = PROCESSED_DIR / f"ground_truth_{pollutant}.parquet"
    gt = pd.read_parquet(ground_truth_path, columns=["site_id", "latitude", "longitude"])
    return gt.drop_duplicates("site_id").reset_index(drop=True)


def build_points_fc(sites: pd.DataFrame) -> ee.FeatureCollection:
    features = [
        ee.Feature(
            ee.Geometry.Point(row.longitude, row.latitude).buffer(POINT_BUFFER_M),
            {"site_id": row.site_id},
        )
        for row in sites.itertuples()
    ]
    return ee.FeatureCollection(features)


def _all_dates(start_date: str, end_date: str) -> list[str]:
    dates = pd.date_range(start_date, end_date, freq="D", inclusive="left")
    return [d.strftime("%Y-%m-%d") for d in dates]


def _get_info_with_retry(fc, max_retries: int = 6):
    for attempt in range(max_retries):
        try:
            return fc.getInfo()
        except ee.ee_exception.EEException as exc:
            if "Too many" in str(exc) or "rate" in str(exc).lower() or "429" in str(exc):
                wait = 2**attempt
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Exceeded max retries against Earth Engine")


def _null_rows(site_ids: list[str], band: str, date_str: str) -> list[dict]:
    return [
        {
            "site_id": site_id,
            "date": date_str,
            "satellite_value": None,
            "satellite_band": band,
            "retrieval_valid": False,
        }
        for site_id in site_ids
    ]


def _mcd19a2_qa_masked(band: str):
    """MCD19A2's AOD_QA bits 0-2 encode cloud/retrieval status; 1 = best quality.
    Masks out everything else and scales the raw AOD integer by its 0.001 factor."""

    def _fn(img: ee.Image) -> ee.Image:
        qa = img.select("AOD_QA").toInt()
        best_quality = qa.bitwiseAnd(7).eq(1)
        aod = img.select(band).multiply(0.001)
        return aod.updateMask(best_quality)

    return _fn


def _extract_day(
    ic: ee.ImageCollection,
    band: str,
    points_fc: ee.FeatureCollection,
    scale: int,
    date_str: str,
    day_reducer: str = "mosaic",
    preprocess=None,
) -> list[dict]:
    d = ee.Date(date_str)
    day_collection = ic.filterDate(d, d.advance(1, "day"))

    # On days with zero source images (no orbit passes / no granules), reducing
    # to a single image produces a bandless image and reduceRegions raises
    # rather than returning nulls -- check size first and short-circuit.
    if day_collection.size().getInfo() == 0:
        site_ids = points_fc.aggregate_array("site_id").getInfo()
        return _null_rows(site_ids, band, date_str)

    # `preprocess` (QA masking etc.) is applied *after* the date filter, on the
    # handful of images left for this one day -- mapping it over a whole
    # mission-length collection first (even bounds-filtered) is what caused
    # Earth Engine computation timeouts for granule products like MCD19A2.
    if preprocess:
        day_collection = day_collection.map(preprocess)

    # mosaic() takes the first unmasked pixel per location across the day's
    # images/granules; mean() averages all unmasked pixels instead -- used for
    # MCD19A2, which can have several QA-masked granule overpasses per day.
    day_image = day_collection.mosaic() if day_reducer == "mosaic" else day_collection.mean()
    reduced = day_image.reduceRegions(collection=points_fc, reducer=ee.Reducer.mean(), scale=scale)
    info = _get_info_with_retry(reduced)

    rows = []
    for feature in info["features"]:
        props = feature["properties"]
        rows.append(
            {
                "site_id": props.get("site_id"),
                "date": date_str,
                "satellite_value": props.get("mean"),
                "satellite_band": band,
                "retrieval_valid": props.get("mean") is not None,
            }
        )
    return rows


def extract_daily_values(
    collection_id: str,
    band: str,
    points_fc: ee.FeatureCollection,
    scale: int,
    preprocess=None,
    day_reducer: str = "mosaic",
) -> pd.DataFrame:
    """Pulls one day's site-level satellite values per Earth Engine request.

    A year's worth of days folded into a single mapped computation hits Earth
    Engine's interactive-compute complexity limit ("Too many concurrent
    aggregations") even at a single calendar month -- so this makes one small,
    cheap request per day instead (only a handful of WI monitor sites, so each
    request is fast) and lets `_get_info_with_retry` back off on rate limits.

    `preprocess`, if given, is applied per-day inside `_extract_day` (e.g. QA
    masking + scaling for MCD19A2) *after* that day's date filter, not mapped
    over the whole collection here -- granule products like MCD19A2 have many
    images worldwide per day, and mapping a custom function before filtering
    by date causes Earth Engine computation timeouts even when bounds-filtered.

    Always filters to Wisconsin's bounding box first, which is cheap (index-
    based) and keeps every subsequent step scoped to relevant imagery.
    """
    wi_bounds = points_fc.geometry().bounds().buffer(50000)
    base = ee.ImageCollection(collection_id).filterBounds(wi_bounds)
    ic = base if preprocess else base.select(band)
    all_rows: list[dict] = []
    dates = _all_dates(START_DATE, END_DATE)
    site_ids = points_fc.aggregate_array("site_id").getInfo()
    for i, date_str in enumerate(dates):
        try:
            all_rows.extend(
                _extract_day(ic, band, points_fc, scale, date_str, day_reducer, preprocess)
            )
        except Exception as exc:  # keep a bad day from losing the whole year's progress
            print(f"    {date_str}: extraction failed ({exc}); recording as no retrieval")
            all_rows.extend(_null_rows(site_ids, band, date_str))
        if (i + 1) % 30 == 0:
            print(f"    {collection_id}: {i + 1}/{len(dates)} days done")
    return pd.DataFrame(all_rows)


def extract_pm25_proxy(points_fc: ee.FeatureCollection) -> pd.DataFrame:
    """MCD19A2 MAIAC daily AOD, QA-masked to best-quality retrievals and
    averaged across the day's granules at each site."""
    collection_id, band, scale = SATELLITE_PRODUCTS["pm25"]
    return extract_daily_values(
        collection_id,
        band,
        points_fc,
        scale,
        preprocess=_mcd19a2_qa_masked(band),
        day_reducer="mean",
    )


def main() -> None:
    authenticate()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for pollutant, (collection_id, band, scale) in SATELLITE_PRODUCTS.items():
        print(f"Extracting satellite values for {pollutant} ({collection_id}) ...")
        sites = load_sites(pollutant)
        points_fc = build_points_fc(sites)

        if pollutant == "pm25":
            out = extract_pm25_proxy(points_fc)
        else:
            out = extract_daily_values(collection_id, band, points_fc, scale)

        out_path = PROCESSED_DIR / f"satellite_{pollutant}.parquet"
        out.to_parquet(out_path, index=False)
        coverage = out["retrieval_valid"].mean() if len(out) else float("nan")
        print(f"  -> {out_path} ({len(out):,} rows, {coverage:.1%} valid retrievals)")


if __name__ == "__main__":
    main()
