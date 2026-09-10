"""Polygon/region Earth Engine extraction helpers.

Every existing GEE pull in this repo (src/ingest_satellite.py,
src/ingest_lur_features.py, src/lur_multiscale_features.py) reduces over
point buffers around AQS monitor sites. Tract-level indicators need
reduction over tract *polygons* instead -- this module is that new piece,
reusing the categorical class-histogram idiom already proven in
src/lur_multiscale_features.py (ee.Reducer.frequencyHistogram() + a
{group_name: [class_codes]} lookup) and the retry/backoff pattern from
src/ingest_satellite.py.
"""
from __future__ import annotations

import time

import ee
import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

BATCH_SIZE = 500
# Simplifies tract boundaries before upload -- ~11m tolerance at WI's latitude,
# well within CDL/Dynamic World's own 30m/10m pixel resolution, so it doesn't
# meaningfully change area-fraction results but keeps the client-side payload
# (1,542 tract polygons) well under Earth Engine's request-size limits.
SIMPLIFY_TOLERANCE_DEG = 0.0001


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


def build_polygon_fc(gdf: gpd.GeoDataFrame, id_col: str) -> list[ee.FeatureCollection]:
    """Converts a GeoDataFrame's polygons into batched ee.FeatureCollections.

    Returns a list (not one big FeatureCollection) so callers can reduce each
    batch separately -- a defensive fallback against Earth Engine payload/
    timeout limits on a single very large client-side geometry upload.
    """
    wgs84 = gdf.to_crs(epsg=4326)
    wgs84 = wgs84.assign(geometry=wgs84.geometry.simplify(SIMPLIFY_TOLERANCE_DEG))

    batches = []
    rows = list(wgs84.itertuples())
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start : start + BATCH_SIZE]
        features = [
            ee.Feature(ee.Geometry(mapping(row.geometry)), {id_col: getattr(row, id_col)})
            for row in chunk
        ]
        batches.append(ee.FeatureCollection(features))
    return batches


def reduce_categorical_by_polygon(
    image: ee.Image,
    band: str,
    polygon_batches: list[ee.FeatureCollection],
    id_col: str,
    group_map: dict[str, list[int]],
    scale: int,
) -> pd.DataFrame:
    """Reduces a classified/categorical image over polygons via a pixel-count
    histogram per polygon, then converts counts to per-group area fractions.

    Mirrors the conversion already proven in
    src/lur_multiscale_features.py::extract_land_cover_mix, generalized from
    point buffers to arbitrary polygon batches.
    """
    classified = image.select(band)
    rows: list[dict] = []
    for batch in polygon_batches:
        reduced = classified.reduceRegions(
            collection=batch, reducer=ee.Reducer.frequencyHistogram(), scale=scale
        )
        info = _get_info_with_retry(reduced)
        for feature in info["features"]:
            props = feature["properties"]
            histogram = props.get("histogram", {}) or {}
            total = sum(histogram.values()) or 1
            row = {id_col: props.get(id_col)}
            for group_name, codes in group_map.items():
                group_count = sum(
                    count for code, count in histogram.items() if int(float(code)) in codes
                )
                row[f"{group_name}_pct"] = group_count / total
            rows.append(row)
    return pd.DataFrame(rows)
