"""Tract-level wetland/surface-water resilience indicator from Google
Dynamic World (10m near-real-time land cover), via Google Earth Engine.

Dynamic World's `label` band is a per-pixel argmax over 9 classes (water,
trees, grass, flooded_vegetation, crops, shrub_and_scrub, built, bare,
snow_and_ice -- confirmed against the collection's own band list). This
module composites the growing season (Jun-Sep, when wetland/open-water
extent is most representative and least confused with snow/ice) via a
per-pixel mode across that window's images, then reduces it per Wisconsin
census tract into a wetland+surface-water area fraction.

A full-year mode composite was tried first and is computationally far more
expensive for no accuracy benefit at this resolution -- the growing-season
window cuts the image count roughly in half and keeps runtime for the full
1,542-tract pipeline in the ballpark of the existing LUR ingestion scripts'
run time (this is a slow, one-time-per-year ingestion script, not something
the app runs live).

Requires the same GEE service-account key as src/ingest_satellite.py
(.env/*.json, gitignored).
"""
from __future__ import annotations

from pathlib import Path

import ee
import geopandas as gpd
import pandas as pd

from src.gee_polygon_utils import build_polygon_fc, reduce_categorical_by_polygon
from src.ingest_satellite import authenticate

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
TRACTS_PATH = PROCESSED_DIR / "wi_tracts_2022.parquet"
OUT_PATH = PROCESSED_DIR / "wi_wetlands_2022.parquet"

DW_COLLECTION = "GOOGLE/DYNAMICWORLD/V1"
DW_BAND = "label"
YEAR = 2022
GROWING_SEASON_START = f"{YEAR}-06-01"
GROWING_SEASON_END = f"{YEAR}-09-01"
SCALE_M = 10

SOURCE_URL = "https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1"

# Dynamic World label band class codes (index order matches the collection's
# own probability-band order: water, trees, grass, flooded_vegetation,
# crops, shrub_and_scrub, built, bare, snow_and_ice -- confirmed directly
# against the collection's bandNames() at implementation time).
WATER_CLASS = 0
FLOODED_VEGETATION_CLASS = 3
GROUP_MAP = {"wetland_water": [WATER_CLASS, FLOODED_VEGETATION_CLASS]}

INDICATOR_NAME = "Wetland & Surface Water Extent"
AGGREGATION_METHOD = (
    f"Google Dynamic World V1, per-pixel most-common land-cover class across "
    f"the {YEAR} growing season ({GROWING_SEASON_START} to {GROWING_SEASON_END}), "
    "fraction of tract area classified water or flooded vegetation, reduced "
    "per tract at native 10m resolution via a pixel-count histogram. A "
    "wetland/surface-water-buffer proxy -- low values are the concerning "
    "direction for this indicator (little protective wetland buffer), the "
    "opposite of every other indicator in this pipeline. See "
    "src/spatial_join.py's LOW_IS_CONCERN_INDICATORS."
)


def extract_wetland_fraction(tracts: gpd.GeoDataFrame) -> pd.DataFrame:
    wi_bounds = ee.Geometry.Rectangle([-93.0, 42.4, -86.2, 47.1])
    dw = (
        ee.ImageCollection(DW_COLLECTION)
        .filterDate(GROWING_SEASON_START, GROWING_SEASON_END)
        .filterBounds(wi_bounds)
    )
    composite = dw.select(DW_BAND).mode()
    batches = build_polygon_fc(tracts, "geoid")
    return reduce_categorical_by_polygon(composite, DW_BAND, batches, "geoid", GROUP_MAP, SCALE_M)


def build_indicator_rows(fractions: pd.DataFrame) -> pd.DataFrame:
    out = fractions.rename(columns={"wetland_water_pct": "indicator_value"}).copy()
    out["indicator_name"] = INDICATOR_NAME
    out["indicator_year"] = YEAR
    out["unit"] = "fraction of tract area"
    out["data_coverage_flag"] = "modeled"
    out["aggregation_method"] = AGGREGATION_METHOD
    out["source_url"] = SOURCE_URL

    ordered_cols = [
        "geoid",
        "indicator_name",
        "indicator_year",
        "indicator_value",
        "unit",
        "data_coverage_flag",
        "aggregation_method",
        "source_url",
    ]
    return out[ordered_cols]


def main() -> None:
    authenticate()
    tracts = gpd.read_parquet(TRACTS_PATH)
    print(f"Extracting Dynamic World {YEAR} growing-season wetland/water fractions for {len(tracts):,} tracts...")
    fractions = extract_wetland_fraction(tracts)
    out = build_indicator_rows(fractions)
    out.to_parquet(OUT_PATH, index=False)
    print(f"  -> {OUT_PATH} ({len(out):,} rows)")


if __name__ == "__main__":
    main()
