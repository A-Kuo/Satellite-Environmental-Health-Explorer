from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


def _concat_glob(pattern: str, reader):
    paths = sorted(PROCESSED_DIR.glob(pattern))
    return pd.concat([reader(p) for p in paths], ignore_index=True)


@pytest.fixture(scope="session")
def tracts_gdf():
    return _concat_glob("*_tracts_2022.parquet", gpd.read_parquet)


@pytest.fixture(scope="session")
def svi_df():
    return _concat_glob("*_svi_2022.parquet", pd.read_parquet)


@pytest.fixture(scope="session")
def indicator_df():
    return _concat_glob("*_pm25_2022.parquet", pd.read_parquet)


@pytest.fixture(scope="session")
def cropland_df():
    return _concat_glob("*_cropland_2022.parquet", pd.read_parquet)


@pytest.fixture(scope="session")
def wetlands_df():
    return _concat_glob("*_wetlands_2022.parquet", pd.read_parquet)


@pytest.fixture(scope="session")
def monitor_points_df():
    return _concat_glob("*_monitor_points.parquet", pd.read_parquet)


@pytest.fixture(scope="session")
def exposure_gdf(tracts_gdf, indicator_df):
    return tracts_gdf.merge(indicator_df, on="geoid", how="left")


@pytest.fixture(scope="session")
def screening_df():
    return gpd.read_parquet(PROCESSED_DIR / "tract_screening_view.parquet")
