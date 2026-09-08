"""Multi-scale land-use features for the Milwaukee site-transfer diagnosis:
impervious % and OSM road density at four buffer radii (100/300/500/1000 m),
plus a neighborhood land-cover mix (NLCD class proportions) at 500 m.

Motivation: `impervious_pct` in `lur_static_<city>.parquet` is a single-point
(500 m) value that turned out to be, by ablation, the single most important
Milwaukee/NO2 feature -- and also the prime suspect for why the model fails
leave-one-site-out (it may be acting as a site identifier rather than a
portable land-use relationship). Multi-scale, spatially smoother features
(road density instead of point imperviousness, several buffer radii instead
of one) are the standard LUR fix for that failure mode.

Road density is computed from the already-cached
`data/raw/osm_major_roads_<city>.json` (no new Overpass calls) via
`ingest_lur_features._fetch_major_roads_geojson`.
"""
from __future__ import annotations

from pathlib import Path

import ee
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.ingest_lur_features import (
    NLCD_ASSET,
    authenticate,
    _fetch_major_roads_geojson,
    _get_info_with_retry,
    load_city_sites,
)
from src.lur_model import PILOTS

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

BUFFER_RADII_M = [100, 300, 500, 1000]
LAND_COVER_BUFFER_M = 500

# NLCD class codes -> a coarser, more sample-efficient grouping for a 500 m
# buffer around a handful of monitor sites (see landcover_class_names in the
# NLCD asset metadata for the full class list).
LAND_COVER_GROUPS = {
    "developed": {21, 22, 23, 24},
    "forest": {41, 42, 43},
    "agriculture": {81, 82},
    "water": {11},
    "other": {12, 31, 52, 71, 90, 95},
}


def _build_points_fc(sites: pd.DataFrame, buffer_m: int) -> ee.FeatureCollection:
    features = [
        ee.Feature(
            ee.Geometry.Point(row.longitude, row.latitude).buffer(buffer_m),
            {"site_id": row.site_id},
        )
        for row in sites.itertuples()
    ]
    return ee.FeatureCollection(features)


def extract_multiscale_impervious(sites: pd.DataFrame) -> pd.DataFrame:
    nlcd = ee.Image(ee.ImageCollection(NLCD_ASSET).first()).select("impervious")
    rows = {row.site_id: {"site_id": row.site_id} for row in sites.itertuples()}

    for radius in BUFFER_RADII_M:
        points_fc = _build_points_fc(sites, radius)
        reduced = nlcd.reduceRegions(collection=points_fc, reducer=ee.Reducer.mean(), scale=30)
        info = _get_info_with_retry(reduced)
        for feature in info["features"]:
            props = feature["properties"]
            rows[props["site_id"]][f"impervious_pct_{radius}m"] = props.get("mean")

    return pd.DataFrame(rows.values())


def extract_land_cover_mix(sites: pd.DataFrame) -> pd.DataFrame:
    landcover = ee.Image(ee.ImageCollection(NLCD_ASSET).first()).select("landcover")
    points_fc = _build_points_fc(sites, LAND_COVER_BUFFER_M)
    reduced = landcover.reduceRegions(
        collection=points_fc, reducer=ee.Reducer.frequencyHistogram(), scale=30
    )
    info = _get_info_with_retry(reduced)

    rows = []
    for feature in info["features"]:
        props = feature["properties"]
        site_id = props["site_id"]
        histogram = props.get("histogram", {})
        total = sum(histogram.values()) or 1
        row = {"site_id": site_id}
        for group_name, codes in LAND_COVER_GROUPS.items():
            group_count = sum(count for code, count in histogram.items() if int(float(code)) in codes)
            row[f"landcover_pct_{group_name}"] = 100 * group_count / total
        rows.append(row)
    return pd.DataFrame(rows)


def extract_road_density(sites: pd.DataFrame, city: str) -> pd.DataFrame:
    """Total OSM major-road length (km) per km^2 within each buffer radius,
    from the already-cached city-wide road extract -- no new Overpass calls."""
    lines = _fetch_major_roads_geojson(city)
    roads_gdf = gpd.GeoDataFrame(geometry=lines, crs="EPSG:4326").to_crs("EPSG:3070")

    points = gpd.GeoDataFrame(
        sites, geometry=[Point(lon, lat) for lat, lon in zip(sites.latitude, sites.longitude)], crs="EPSG:4326"
    ).to_crs("EPSG:3070")

    rows = []
    for row in points.itertuples():
        result = {"site_id": row.site_id}
        for radius in BUFFER_RADII_M:
            buffer_geom = row.geometry.buffer(radius)
            clipped = roads_gdf.geometry.intersection(buffer_geom)
            total_length_km = clipped.length.sum() / 1000.0
            area_km2 = (3.14159265 * radius**2) / 1_000_000
            result[f"road_density_{radius}m"] = total_length_km / area_km2
        rows.append(result)
    return pd.DataFrame(rows)


def main() -> None:
    authenticate()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for city, pollutant in PILOTS:
        sites = load_city_sites(city, pollutant)
        print(f"{city}/{pollutant}: {len(sites)} sites")

        impervious_df = extract_multiscale_impervious(sites)
        land_cover_df = extract_land_cover_mix(sites)
        road_density_df = extract_road_density(sites, city)

        merged = impervious_df.merge(land_cover_df, on="site_id").merge(road_density_df, on="site_id")
        out_path = PROCESSED_DIR / f"lur_multiscale_features_{city}.parquet"
        merged.to_parquet(out_path, index=False)
        print(f"  -> {out_path}")
        print(merged.to_string(index=False))


if __name__ == "__main__":
    main()
