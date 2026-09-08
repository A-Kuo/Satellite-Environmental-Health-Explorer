"""Builds the geometries table, the DNR monitor points table, and the derived
tract_screening_view by joining SVI + the environmental indicator onto
Wisconsin census tract geometries.

agent.md's fixed repo structure has no dedicated "clean tracts" module, so
tract-geometry preparation (from the raw TIGER shapefile) lives here, as the
first step before the join itself.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

TIGER_ZIP = RAW_DIR / "tl_2022_55_tract.zip"
COUNTY_FIPS_TXT = RAW_DIR / "st55_wi_cou2020.txt"
DNR_GEOJSON = RAW_DIR / "wi_dnr_air_monitors_snapshot.geojson"

TRACTS_OUT = PROCESSED_DIR / "wi_tracts_2022.parquet"
SVI_PATH = PROCESSED_DIR / "wi_svi_2022.parquet"
INDICATOR_PATH = PROCESSED_DIR / "wi_pm25_2022.parquet"
DNR_POINTS_OUT = PROCESSED_DIR / "wi_dnr_points.parquet"
SCREENING_VIEW_OUT = PROCESSED_DIR / "tract_screening_view.parquet"

TARGET_CRS = "EPSG:4269"
SCREENING_PERCENTILE_THRESHOLD = 0.75

DNR_SOURCE_URL = (
    "https://dnrmaps.wi.gov/arcgis/rest/services/AM_WARP_MAP/AM_MONITORS_WTM_Int/MapServer/0"
)
POLLUTANT_FIELDS = [
    "O3", "PM2_5", "PM10", "PMCRS", "SO2", "NO2", "CO", "MET", "PBTSP",
    "METALS", "NOY", "PAH", "VOC", "NTN", "HG", "AMON", "UFP", "AETH", "AMNET", "MDN",
]


def build_tracts(tiger_zip: Path = TIGER_ZIP, county_fips_txt: Path = COUNTY_FIPS_TXT) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(tiger_zip)
    gdf = gdf.to_crs(TARGET_CRS)

    gdf["geoid"] = gdf["GEOID"].astype(str).str.zfill(11)
    gdf["county_fips"] = (gdf["STATEFP"].astype(str) + gdf["COUNTYFP"].astype(str)).str.zfill(5)

    county_names = pd.read_csv(county_fips_txt, sep="|", dtype=str)
    county_names["county_fips"] = (
        county_names["STATEFP"].str.zfill(2) + county_names["COUNTYFP"].str.zfill(3)
    )
    county_names = county_names.rename(columns={"COUNTYNAME": "county_name"})[
        ["county_fips", "county_name"]
    ]

    gdf = gdf.merge(county_names, on="county_fips", how="left")
    gdf["geography_name"] = gdf["NAMELSAD"] + ", " + gdf["county_name"] + ", Wisconsin"
    gdf["geography_type"] = "census_tract"

    return gdf[
        ["geoid", "geography_name", "geography_type", "geometry", "county_name", "county_fips"]
    ]


def build_dnr_points(dnr_geojson: Path = DNR_GEOJSON) -> pd.DataFrame:
    with open(dnr_geojson, encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for feature in data["features"]:
        props = feature["properties"]
        active_pollutants = [
            field.replace("PM2_5", "PM2.5")
            for field in POLLUTANT_FIELDS
            if str(props.get(field, "N/A")).upper() not in ("N/A", "NONE", "")
        ]
        rows.append(
            {
                "point_id": str(props["OBJECTID"]),
                "name": props.get("SITE"),
                "point_type": "air_monitor",
                "latitude": props.get("LATITUDE"),
                "longitude": props.get("LONGITUDE"),
                "pollutant_or_permit_type": ", ".join(active_pollutants) if active_pollutants else None,
                "reporting_year": date.today().year,
                "source_url": DNR_SOURCE_URL,
            }
        )
    return pd.DataFrame(rows)


def build_screening_view(
    tracts: gpd.GeoDataFrame, svi: pd.DataFrame, indicator: pd.DataFrame
) -> gpd.GeoDataFrame:
    assert tracts.crs is not None and tracts.crs.to_epsg() in (4269, 4326), "Unexpected tract CRS"

    merged = tracts.merge(indicator, on="geoid", how="left").merge(svi, on="geoid", how="left")

    merged["indicator_percentile_wi"] = merged["indicator_value"].rank(pct=True)

    merged["screening_flag"] = (
        (merged["indicator_percentile_wi"] >= SCREENING_PERCENTILE_THRESHOLD)
        & (merged["overall_svi_percentile"] >= SCREENING_PERCENTILE_THRESHOLD)
    ).fillna(False)

    merged["screening_rationale"] = merged["screening_flag"].map(
        {
            True: (
                "Selected because both the environmental indicator and SVI are at or "
                "above the Wisconsin 75th percentile. This is a screening flag for "
                "analyst review, not a health-risk estimate."
            ),
            False: (
                "Not flagged: the environmental indicator and/or SVI percentile for "
                "this tract falls below the Wisconsin 75th-percentile screening "
                "threshold."
            ),
        }
    )

    merged["selected_indicator"] = merged["indicator_name"]
    merged["last_updated"] = date.today().isoformat()

    out_cols = [
        "geoid",
        "geography_name",
        "county_name",
        "selected_indicator",
        "indicator_value",
        "indicator_percentile_wi",
        "overall_svi_percentile",
        "data_coverage_flag",
        "screening_flag",
        "screening_rationale",
        "last_updated",
        "geometry",
    ]
    return merged[out_cols]


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    tracts = build_tracts()
    tracts.to_parquet(TRACTS_OUT, index=False)
    print(f"Wrote {len(tracts):,} rows -> {TRACTS_OUT}")

    dnr_points = build_dnr_points()
    dnr_points.to_parquet(DNR_POINTS_OUT, index=False)
    print(f"Wrote {len(dnr_points):,} rows -> {DNR_POINTS_OUT}")

    svi = pd.read_parquet(SVI_PATH)
    indicator = pd.read_parquet(INDICATOR_PATH)
    screening_view = build_screening_view(tracts, svi, indicator)
    screening_view.to_parquet(SCREENING_VIEW_OUT, index=False)
    print(f"Wrote {len(screening_view):,} rows -> {SCREENING_VIEW_OUT}")


if __name__ == "__main__":
    main()
