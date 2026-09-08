"""Extracts the Land Use Regression (LUR) predictor stack -- static land-use/
terrain/road features plus dynamic daily weather -- for a city's monitor
sites, via Google Earth Engine (weather, land cover, elevation) and
OpenStreetMap (major-road distance).

The OSM road query goes straight to the Overpass API with `requests` rather
than through `osmnx`'s graph-building machinery: `osmnx.graph_from_point`
repeatedly hit connect timeouts against both overpass-api.de and the Kumi
Systems mirror in this environment, while a plain `requests` POST of the same
query to overpass-api.de succeeded in ~20s. We only need road geometry for a
nearest-distance calculation, not a routable graph, so the simpler direct
query is both more reliable here and less code. The response is cached to
data/raw/ and fetched only once, per OSM's own usage guidance (see
OSM_HEADERS below).

Reuses the per-day extraction/retry machinery already worked out in
ingest_satellite.py rather than re-solving the same Earth Engine timeout and
rate-limit issues here.
"""
from __future__ import annotations

import glob
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import ee
import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import LineString, Point

from src.ingest import append_ingest_log, sha256_of
from src.ingest_satellite import (
    ENV_DIR,
    END_DATE,
    SATELLITE_PRODUCTS,
    START_DATE,
    _all_dates,
    _get_info_with_retry,
    extract_daily_values,
    extract_pm25_proxy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RAW_DIR = REPO_ROOT / "data" / "raw"

# Reusable across cities/pollutants. Milwaukee's buffer is large enough (70km)
# to cover all 3 of Wisconsin's actual NO2 monitors, which span the
# Milwaukee-Kenosha corridor rather than sitting tightly within city limits
# (verified this session: 6km, 12km, and 60km from a Milwaukee city-center point).
CITY_CONFIGS = {
    "madison": {"center": (43.0731, -89.4012), "buffer_m": 25000},
    "milwaukee": {"center": (43.0389, -87.9065), "buffer_m": 70000},
}

STATIC_BUFFER_M = 500  # local urban-form buffer for impervious %/elevation
ERA5_LAND_MEAN_BANDS = [
    "temperature_2m",
    "dewpoint_temperature_2m",
    "u_component_of_wind_10m",
    "v_component_of_wind_10m",
]
ERA5_LAND_SUM_BANDS = ["total_precipitation"]
ERA5_LAND_COLLECTION = "ECMWF/ERA5_LAND/HOURLY"
ERA5_BLH_COLLECTION = "ECMWF/ERA5/HOURLY"  # boundary_layer_height isn't in ERA5-Land
ERA5_BLH_BAND = "boundary_layer_height"
ERA5_SCALE_M = 9000

NLCD_ASSET = "USGS/NLCD_RELEASES/2021_REL/NLCD"
DEM_COLLECTION = "USGS/3DEP/10m_collection"  # USGS/3DEP/10m (singular) is deprecated

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# A truthful, stable, identifying User-Agent, per OSM's usage guidance --
# not another application's UA string. The contact address is the GitHub-
# provided noreply address already public in this repo's own commit history
# (`git config user.email`), not a personal inbox.
OSM_HEADERS = {
    "User-Agent": (
        "SatelliteEnvironmentalHealthExplorer/0.1 "
        "(https://github.com/A-Kuo/Satellite-Environmental-Health-Explorer; "
        "contact: 123901299+A-Kuo@users.noreply.github.com)"
    )
}

# OSM data (c) OpenStreetMap contributors, ODbL -- must be credited wherever
# the resulting distance-to-major-road feature is used or displayed.
OSM_ATTRIBUTION = "(c) OpenStreetMap contributors"


def authenticate() -> None:
    key_paths = glob.glob(str(ENV_DIR / "*.json"))
    if not key_paths:
        raise FileNotFoundError(f"No service-account JSON key found in {ENV_DIR}.")
    key_path = key_paths[0]
    with open(key_path) as f:
        key = json.load(f)
    creds = ee.ServiceAccountCredentials(key["client_email"], key_path)
    ee.Initialize(creds, project=key["project_id"])


def load_city_sites(city: str, pollutant: str) -> pd.DataFrame:
    """Ground-truth monitor sites for `pollutant`, restricted to those within
    the city's buffer (haversine distance from the city center)."""
    gt = pd.read_parquet(
        PROCESSED_DIR / f"ground_truth_{pollutant}.parquet", columns=["site_id", "latitude", "longitude"]
    ).drop_duplicates("site_id")

    center_lat, center_lon = CITY_CONFIGS[city]["center"]
    buffer_km = CITY_CONFIGS[city]["buffer_m"] / 1000

    def _haversine_km(lat, lon):
        from math import asin, cos, radians, sin, sqrt

        dlat, dlon = radians(lat - center_lat), radians(lon - center_lon)
        a = sin(dlat / 2) ** 2 + cos(radians(center_lat)) * cos(radians(lat)) * sin(dlon / 2) ** 2
        return 2 * 6371 * asin(sqrt(a))

    gt["dist_from_center_km"] = gt.apply(lambda r: _haversine_km(r.latitude, r.longitude), axis=1)
    return gt[gt["dist_from_center_km"] <= buffer_km].drop(columns="dist_from_center_km").reset_index(drop=True)


def _build_points_fc(sites: pd.DataFrame, buffer_m: int) -> ee.FeatureCollection:
    features = [
        ee.Feature(
            ee.Geometry.Point(row.longitude, row.latitude).buffer(buffer_m),
            {"site_id": row.site_id},
        )
        for row in sites.itertuples()
    ]
    return ee.FeatureCollection(features)


def _fetch_major_roads_geojson(city: str, max_retries: int = 4) -> list[LineString]:
    """Returns motorway/trunk/primary way geometries within the city's
    bounding box as shapely LineStrings, from a cached raw Overpass response
    if one already exists, or by querying Overpass once and caching it.

    OSM's usage guidance asks callers to identify themselves, cache results,
    avoid parallel/repeated querying, and back off before retrying after an
    error -- this does all four: a real UA (OSM_HEADERS), one cached fetch
    per city logged like every other raw source in ingest_log.csv, and a
    lengthened first retry wait.
    """
    cache_path = RAW_DIR / f"osm_major_roads_{city}.json"

    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        center_lat, center_lon = CITY_CONFIGS[city]["center"]
        buffer_deg = CITY_CONFIGS[city]["buffer_m"] / 111_000  # rough meters->degrees
        south, north = center_lat - buffer_deg, center_lat + buffer_deg
        west, east = center_lon - buffer_deg, center_lon + buffer_deg

        query = (
            f'[out:json][timeout:60];way({south},{west},{north},{east})'
            f'["highway"~"motorway|trunk|primary"];out geom;'
        )

        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = requests.post(OVERPASS_URL, data={"data": query}, headers=OSM_HEADERS, timeout=90)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as exc:
                last_exc = exc
                wait = 30 * (attempt + 1)  # pause before retrying, per OSM guidance
                print(f"    Overpass query failed ({exc}); retrying in {wait}s ...")
                time.sleep(wait)
        else:
            raise RuntimeError(f"Could not fetch OSM roads for {city} after {max_retries} attempts") from last_exc

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        append_ingest_log(
            [
                {
                    "filename": cache_path.name,
                    "source_url": OVERPASS_URL,
                    "description": (
                        f"OpenStreetMap major roads (motorway/trunk/primary) within the "
                        f"{city} pilot buffer, (c) OpenStreetMap contributors, ODbL"
                    ),
                    "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                    "sha256": sha256_of(cache_path),
                }
            ]
        )
        print(f"    Cached OSM roads -> {cache_path}")

    lines = []
    for element in data.get("elements", []):
        geom = element.get("geometry")
        if geom and len(geom) >= 2:
            lines.append(LineString([(pt["lon"], pt["lat"]) for pt in geom]))
    return lines


def compute_road_distances(sites: pd.DataFrame, city: str) -> pd.Series:
    """Distance in km from each site to the nearest OSM major road
    (motorway/trunk/primary) within the city buffer."""
    lines = _fetch_major_roads_geojson(city)
    if not lines:
        raise RuntimeError(f"Overpass returned zero major-road ways for {city}")

    roads_gdf = gpd.GeoDataFrame(geometry=lines, crs="EPSG:4326")
    # Project to a metric CRS (Wisconsin Transverse Mercator) for real distances.
    roads_union = roads_gdf.to_crs("EPSG:3070").geometry.union_all()

    points = gpd.GeoDataFrame(
        sites, geometry=[Point(lon, lat) for lat, lon in zip(sites.latitude, sites.longitude)], crs="EPSG:4326"
    ).to_crs("EPSG:3070")

    return points.geometry.distance(roads_union) / 1000.0


def extract_static_features(city: str, sites: pd.DataFrame) -> pd.DataFrame:
    points_fc = _build_points_fc(sites, STATIC_BUFFER_M)

    nlcd = ee.Image(ee.ImageCollection(NLCD_ASSET).first()).select("impervious").rename("impervious_pct")
    dem = ee.ImageCollection(DEM_COLLECTION).mosaic().select("elevation").rename("elevation_m")
    combined = nlcd.addBands(dem)

    reduced = combined.reduceRegions(collection=points_fc, reducer=ee.Reducer.mean(), scale=30)
    info = _get_info_with_retry(reduced)

    rows = [feature["properties"] for feature in info["features"]]
    static_df = pd.DataFrame(rows)[["site_id", "impervious_pct", "elevation_m"]]

    static_df["dist_to_major_road_km"] = compute_road_distances(sites, city).values
    return static_df


def _extract_era5_day(points_fc: ee.FeatureCollection, site_ids: list[str], date_str: str) -> list[dict]:
    d = ee.Date(date_str)

    land_day = ee.ImageCollection(ERA5_LAND_COLLECTION).filterDate(d, d.advance(1, "day"))
    blh_day = ee.ImageCollection(ERA5_BLH_COLLECTION).filterDate(d, d.advance(1, "day")).select(ERA5_BLH_BAND)

    if land_day.size().getInfo() == 0:
        return [
            {"site_id": sid, "date": date_str, **{b: None for b in ERA5_LAND_MEAN_BANDS + ERA5_LAND_SUM_BANDS + [ERA5_BLH_BAND]}}
            for sid in site_ids
        ]

    mean_img = land_day.select(ERA5_LAND_MEAN_BANDS).mean()
    sum_img = land_day.select(ERA5_LAND_SUM_BANDS).sum()
    combined = mean_img.addBands(sum_img)

    if blh_day.size().getInfo() > 0:
        combined = combined.addBands(blh_day.mean())

    reduced = combined.reduceRegions(collection=points_fc, reducer=ee.Reducer.mean(), scale=ERA5_SCALE_M)
    info = _get_info_with_retry(reduced)

    rows = []
    for feature in info["features"]:
        props = feature["properties"]
        row = {"site_id": props.get("site_id"), "date": date_str}
        for band in ERA5_LAND_MEAN_BANDS + ERA5_LAND_SUM_BANDS + [ERA5_BLH_BAND]:
            row[band] = props.get(band)
        rows.append(row)
    return rows


def extract_dynamic_features(sites: pd.DataFrame) -> pd.DataFrame:
    points_fc = _build_points_fc(sites, STATIC_BUFFER_M)
    site_ids = sites["site_id"].tolist()
    all_rows: list[dict] = []
    dates = _all_dates(START_DATE, END_DATE)
    for i, date_str in enumerate(dates):
        try:
            all_rows.extend(_extract_era5_day(points_fc, site_ids, date_str))
        except Exception as exc:
            print(f"    {date_str}: ERA5 extraction failed ({exc}); recording as no retrieval")
            all_rows.extend(
                {"site_id": sid, "date": date_str, **{b: None for b in ERA5_LAND_MEAN_BANDS + ERA5_LAND_SUM_BANDS + [ERA5_BLH_BAND]}}
                for sid in site_ids
            )
        if (i + 1) % 30 == 0:
            print(f"    ERA5: {i + 1}/{len(dates)} days done")
    return pd.DataFrame(all_rows)


# Each pilot's *other* pollutant satellite proxy, evaluated at the pilot's
# own monitor sites -- satellite_no2.parquet/satellite_pm25.parquet only
# cover each pollutant's own (different) statewide monitor locations, so the
# cross-predictor (e.g. TROPOMI NO2 as a feature for the Madison PM2.5 model)
# has to be extracted fresh at the pilot's site set.
CROSS_SATELLITE_POLLUTANT = {"pm25": "no2", "no2": "pm25"}


def extract_cross_satellite(target_pollutant: str, sites: pd.DataFrame) -> pd.DataFrame:
    other_pollutant = CROSS_SATELLITE_POLLUTANT[target_pollutant]
    points_fc = _build_points_fc(sites, 1000)

    if other_pollutant == "pm25":
        out = extract_pm25_proxy(points_fc)
    else:
        collection_id, band, scale = SATELLITE_PRODUCTS[other_pollutant]
        out = extract_daily_values(collection_id, band, points_fc, scale)

    out = out.rename(
        columns={"satellite_value": f"cross_satellite_{other_pollutant}", "retrieval_valid": f"cross_satellite_{other_pollutant}_valid"}
    ).drop(columns=["satellite_band"])
    return out


def main() -> None:
    authenticate()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    pilots = [("madison", "pm25"), ("milwaukee", "no2")]
    for city, pollutant in pilots:
        sites = load_city_sites(city, pollutant)
        print(f"{city}/{pollutant}: {len(sites)} monitor sites")

        static_path = PROCESSED_DIR / f"lur_static_{city}.parquet"
        if static_path.exists():
            print(f"  {static_path} already exists, skipping")
        else:
            extract_static_features(city, sites).to_parquet(static_path, index=False)
            print(f"  -> {static_path}")

        dynamic_path = PROCESSED_DIR / f"lur_dynamic_{city}.parquet"
        if dynamic_path.exists():
            print(f"  {dynamic_path} already exists, skipping")
        else:
            print(f"  Extracting ERA5 daily weather for {city} ...")
            dynamic_df = extract_dynamic_features(sites)
            dynamic_df.to_parquet(dynamic_path, index=False)
            coverage = dynamic_df["temperature_2m"].notna().mean() if len(dynamic_df) else float("nan")
            print(f"  -> {dynamic_path} ({len(dynamic_df):,} rows, {coverage:.1%} valid)")

        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        cross_path = PROCESSED_DIR / f"lur_cross_satellite_{city}.parquet"
        if cross_path.exists():
            print(f"  {cross_path} already exists, skipping")
        else:
            print(f"  Extracting cross-satellite ({other_pollutant}) predictor for {city} ...")
            cross_df = extract_cross_satellite(pollutant, sites)
            cross_df.to_parquet(cross_path, index=False)
            print(f"  -> {cross_path} ({len(cross_df):,} rows)")


if __name__ == "__main__":
    main()
