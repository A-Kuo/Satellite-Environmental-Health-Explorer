"""Cached data access for the Stage Two Streamlit app.

Streamlit re-executes each page (app/streamlit_app.py, app/pages/*.py) as its
own top-level script, so the repo root is not guaranteed to be on sys.path the
way pytest's rootdir-based invocation puts it there for src.*. This module
inserts the repo root once on import so `from src.validate import PROCESSED_DIR`
works regardless of which script imports data_loader first.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import geopandas as gpd
import pandas as pd
import streamlit as st

from src.validate import PROCESSED_DIR

LUR_PLOTS_DIR = PROCESSED_DIR / "lur_plots"
CALIBRATION_PLOTS_DIR = PROCESSED_DIR / "calibration_plots"


@st.cache_data(show_spinner="Loading screening data...")
def load_screening_view() -> gpd.GeoDataFrame:
    gdf = gpd.read_parquet(PROCESSED_DIR / "tract_screening_view.parquet")
    return gdf.to_crs(epsg=4326)


@st.cache_data(show_spinner=False)
def load_dnr_points() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / "wi_dnr_points.parquet")


@st.cache_data(show_spinner=False)
def load_lur_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(PROCESSED_DIR / name)


def lur_plot_path(name: str) -> Path:
    return LUR_PLOTS_DIR / name


def calibration_plot_path(name: str) -> Path:
    return CALIBRATION_PLOTS_DIR / name
