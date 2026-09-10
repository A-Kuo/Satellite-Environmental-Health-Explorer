from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


@pytest.fixture(scope="session")
def tracts_gdf():
    return gpd.read_parquet(PROCESSED_DIR / "wi_tracts_2022.parquet")


@pytest.fixture(scope="session")
def svi_df():
    return pd.read_parquet(PROCESSED_DIR / "wi_svi_2022.parquet")


@pytest.fixture(scope="session")
def indicator_df():
    return pd.read_parquet(PROCESSED_DIR / "wi_pm25_2022.parquet")


@pytest.fixture(scope="session")
def cropland_df():
    return pd.read_parquet(PROCESSED_DIR / "wi_cropland_2022.parquet")


@pytest.fixture(scope="session")
def wetlands_df():
    return pd.read_parquet(PROCESSED_DIR / "wi_wetlands_2022.parquet")


@pytest.fixture(scope="session")
def exposure_gdf(tracts_gdf, indicator_df):
    return tracts_gdf.merge(indicator_df, on="geoid", how="left")


@pytest.fixture(scope="session")
def screening_df():
    return gpd.read_parquet(PROCESSED_DIR / "tract_screening_view.parquet")
