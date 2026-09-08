"""Joins ground truth, the pollutant's own satellite proxy, the cross-
pollutant satellite predictor, and the LUR static/dynamic feature tables into
one modeling-ready panel per city/pollutant pilot, with the derived
meteorological and temporal features the raw ERA5 pull doesn't compute.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT, load_city_sites

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

PILOTS = [("madison", "pm25"), ("milwaukee", "no2")]

HEATING_SEASON_MONTHS = {10, 11, 12, 1, 2, 3, 4}  # Oct-Apr, Wisconsin


def _relative_humidity_pct(temp_k: pd.Series, dewpoint_k: pd.Series) -> pd.Series:
    """Magnus-Tetens approximation. Inputs in Kelvin, output 0-100."""
    t_c = temp_k - 273.15
    td_c = dewpoint_k - 273.15
    e_t = np.exp((17.625 * t_c) / (243.04 + t_c))
    e_td = np.exp((17.625 * td_c) / (243.04 + td_c))
    return 100 * e_td / e_t


def _wind_speed_direction(u: pd.Series, v: pd.Series) -> tuple[pd.Series, pd.Series]:
    speed = np.sqrt(u**2 + v**2)
    direction = (270 - np.degrees(np.arctan2(v, u))) % 360
    return speed, direction


def add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    doy = df["date"].dt.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    df["is_weekend"] = df["date"].dt.dayofweek.isin([5, 6])
    df["is_heating_season"] = df["date"].dt.month.isin(HEATING_SEASON_MONTHS)
    return df


def build_pilot_dataset(city: str, pollutant: str) -> pd.DataFrame:
    sites = load_city_sites(city, pollutant)
    site_ids = set(sites["site_id"])

    ground_truth = pd.read_parquet(PROCESSED_DIR / f"ground_truth_{pollutant}.parquet")
    ground_truth = ground_truth[ground_truth["site_id"].isin(site_ids)].copy()
    ground_truth["date"] = pd.to_datetime(ground_truth["date"])

    satellite = pd.read_parquet(PROCESSED_DIR / f"satellite_{pollutant}.parquet")
    satellite = satellite[satellite["site_id"].isin(site_ids)][["site_id", "date", "satellite_value", "retrieval_valid"]]
    satellite["date"] = pd.to_datetime(satellite["date"])
    satellite = satellite.rename(columns={"satellite_value": f"satellite_{pollutant}"})

    other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
    cross = pd.read_parquet(PROCESSED_DIR / f"lur_cross_satellite_{city}.parquet")
    cross["date"] = pd.to_datetime(cross["date"])

    dynamic = pd.read_parquet(PROCESSED_DIR / f"lur_dynamic_{city}.parquet")
    dynamic["date"] = pd.to_datetime(dynamic["date"])

    static = pd.read_parquet(PROCESSED_DIR / f"lur_static_{city}.parquet")

    df = ground_truth.merge(satellite, on=["site_id", "date"], how="left")
    df = df.merge(cross, on=["site_id", "date"], how="left")
    df = df.merge(dynamic, on=["site_id", "date"], how="left")
    df = df.merge(static, on="site_id", how="left")

    df["relative_humidity_pct"] = _relative_humidity_pct(df["temperature_2m"], df["dewpoint_temperature_2m"])
    df["wind_speed_ms"], df["wind_direction_deg"] = _wind_speed_direction(
        df["u_component_of_wind_10m"], df["v_component_of_wind_10m"]
    )
    df = add_temporal_features(df)

    df["retrieval_valid"] = df["retrieval_valid"].fillna(False)
    df[f"cross_satellite_{other_pollutant}_valid"] = df[f"cross_satellite_{other_pollutant}_valid"].fillna(False)

    return df


FEATURE_COLUMNS_TEMPLATE = [
    "temperature_2m",
    "relative_humidity_pct",
    "wind_speed_ms",
    "wind_direction_deg",
    "total_precipitation",
    "boundary_layer_height",
    "impervious_pct",
    "elevation_m",
    "dist_to_major_road_km",
    "doy_sin",
    "doy_cos",
    "is_weekend",
    "is_heating_season",
]


def main() -> None:
    for city, pollutant in PILOTS:
        df = build_pilot_dataset(city, pollutant)
        out_path = PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet"
        df.to_parquet(out_path, index=False)

        satellite_coverage = df["retrieval_valid"].mean()
        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        cross_coverage = df[f"cross_satellite_{other_pollutant}_valid"].mean()
        weather_coverage = df["temperature_2m"].notna().mean()
        print(
            f"{city}/{pollutant}: {len(df):,} site-days -> {out_path}\n"
            f"  own-satellite coverage {satellite_coverage:.1%}, "
            f"cross-satellite ({other_pollutant}) coverage {cross_coverage:.1%}, "
            f"weather coverage {weather_coverage:.1%}"
        )


if __name__ == "__main__":
    main()
