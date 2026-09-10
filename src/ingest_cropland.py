"""Tract-level agricultural pressure indicators from the USDA NASS Cropland
Data Layer (CDL), via Google Earth Engine.

CDL's `cropland` band is the standard annual crop-type raster (30m,
CONUS-wide). This module reduces it per Wisconsin census tract into two
fertilizer/pesticide-loading proxies: row-crop share (corn/soybean, incl.
double-crop combinations) and pastureland share (grass/pasture, hay,
alfalfa -- Wisconsin's dairy-associated land cover). Class codes verified
directly against the image's own `cropland_class_values`/`cropland_class_names`
properties for the 2022 release (do not assume these are stable across years
without re-checking).

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
OUT_PATH = PROCESSED_DIR / "wi_cropland_2022.parquet"

CDL_COLLECTION = "USDA/NASS/CDL"
CDL_BAND = "cropland"
YEAR = 2022
SCALE_M = 30

SOURCE_URL = "https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php"

# CDL 2022 class codes (verified against the image's own cropland_class_names/
# cropland_class_values properties -- see notebooks/ or re-run the lookup
# below if CDL's class scheme ever changes):
#   1 Corn, 5 Soybeans, 12 Sweet Corn, 13 Pop or Orn Corn, 26 Dbl Crop
#   WinWht/Soybeans, 225/226/228/237/239/240/241/254 double-crop combinations
#   involving corn or soybeans.
ROW_CROP_CODES = [1, 5, 12, 13, 26, 225, 226, 228, 237, 239, 240, 241, 254]
#   176 Grass/Pasture, 37 Other Hay/Non Alfalfa, 36 Alfalfa (Wisconsin's
#   dominant dairy feed crop).
PASTURE_CODES = [176, 37, 36]

GROUP_MAP = {"row_crop": ROW_CROP_CODES, "pasture": PASTURE_CODES}

INDICATORS = [
    {
        "column": "row_crop_pct",
        "indicator_name": "Row-Crop Cultivation Share (Corn & Soybean)",
        "aggregation_method": (
            f"USDA NASS Cropland Data Layer {YEAR}, fraction of tract area "
            "classified as corn, soybean, or a double-crop combination "
            "involving either (CDL codes 1, 5, 12, 13, 26, 225, 226, 228, "
            "237, 239, 240, 241, 254), reduced per tract at native 30m "
            "resolution via a pixel-count histogram. A fertilizer/pesticide "
            "loading proxy, not a direct water-quality measurement."
        ),
    },
    {
        "column": "pasture_pct",
        "indicator_name": "Pastureland Share (Dairy-Associated)",
        "aggregation_method": (
            f"USDA NASS Cropland Data Layer {YEAR}, fraction of tract area "
            "classified as grass/pasture, other hay, or alfalfa (CDL codes "
            "176, 37, 36) -- Wisconsin's dominant dairy-associated land "
            "cover, reduced per tract at native 30m resolution via a "
            "pixel-count histogram. A manure/nutrient-runoff loading proxy, "
            "not a direct water-quality measurement."
        ),
    },
]


def extract_cropland_fractions(tracts: gpd.GeoDataFrame) -> pd.DataFrame:
    cdl_image = ee.Image(
        ee.ImageCollection(CDL_COLLECTION).filterDate(f"{YEAR}-01-01", f"{YEAR + 1}-01-01").first()
    )
    batches = build_polygon_fc(tracts, "geoid")
    return reduce_categorical_by_polygon(cdl_image, CDL_BAND, batches, "geoid", GROUP_MAP, SCALE_M)


def build_indicator_rows(fractions: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for spec in INDICATORS:
        df = fractions[["geoid", spec["column"]]].rename(columns={spec["column"]: "indicator_value"})
        df["indicator_name"] = spec["indicator_name"]
        df["indicator_year"] = YEAR
        df["unit"] = "fraction of tract area"
        df["data_coverage_flag"] = "modeled"
        df["aggregation_method"] = spec["aggregation_method"]
        df["source_url"] = SOURCE_URL
        frames.append(df)

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
    return pd.concat(frames, ignore_index=True)[ordered_cols]


def main() -> None:
    authenticate()
    tracts = gpd.read_parquet(TRACTS_PATH)
    print(f"Extracting CDL {YEAR} cropland fractions for {len(tracts):,} tracts...")
    fractions = extract_cropland_fractions(tracts)
    out = build_indicator_rows(fractions)
    out.to_parquet(OUT_PATH, index=False)
    print(f"  -> {OUT_PATH} ({len(out):,} rows, {out['indicator_name'].nunique()} indicators)")


if __name__ == "__main__":
    main()
