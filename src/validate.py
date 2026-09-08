"""Reusable validation assertions for the Stage One processed tables.

Shared by tests/ and runnable directly as a CLI, which also prints a
missingness-by-column summary for each table.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

FORBIDDEN_COLUMNS = {"risk_score", "priority_score", "harm_score"}
MIN_JOIN_COVERAGE = 0.90


# --- geography checks -------------------------------------------------------

def check_unique_geoid(tracts_gdf: gpd.GeoDataFrame) -> None:
    assert tracts_gdf["geoid"].is_unique, "Duplicate GEOIDs in tract geometry"


def check_no_null_geometry(tracts_gdf: gpd.GeoDataFrame) -> None:
    assert tracts_gdf["geometry"].notna().all(), "Null geometries present"


def check_geoid_format(tracts_gdf: gpd.GeoDataFrame) -> None:
    assert tracts_gdf["geoid"].str.match(r"^\d{11}$").all(), "GEOIDs not 11-digit strings"


def check_wisconsin_fips_prefix(tracts_gdf: gpd.GeoDataFrame) -> None:
    assert tracts_gdf["geoid"].str.startswith("55").all(), "Non-Wisconsin GEOIDs present"


def check_crs(tracts_gdf: gpd.GeoDataFrame) -> None:
    assert tracts_gdf.crs.to_epsg() in (4269, 4326), "Unexpected CRS"


# --- join checks -------------------------------------------------------------

def check_crs_match(tracts_gdf: gpd.GeoDataFrame, exposure_gdf: gpd.GeoDataFrame) -> None:
    assert tracts_gdf.crs == exposure_gdf.crs, "CRS mismatch before spatial join"


def check_join_coverage(screening_df: pd.DataFrame, tracts_gdf: gpd.GeoDataFrame) -> None:
    coverage = screening_df["indicator_value"].notna().mean()
    assert coverage >= MIN_JOIN_COVERAGE, f"Join coverage too low: {coverage:.1%}"


def check_no_unexplained_missing_geometry(screening_df: pd.DataFrame) -> None:
    mask = screening_df["indicator_value"].notna()
    assert screening_df.loc[mask, "geometry"].notna().all()


# --- value / logic checks -----------------------------------------------------

def check_valid_svi_range(svi_df: pd.DataFrame) -> None:
    valid = svi_df["overall_svi_percentile"].dropna()
    assert valid.between(0, 1).all(), "SVI percentile out of range"


def check_indicator_year_present(indicator_df: pd.DataFrame) -> None:
    assert indicator_df["indicator_year"].notna().all(), "Missing indicator year"


def check_no_negative_pm25(indicator_df: pd.DataFrame) -> None:
    assert (indicator_df["indicator_value"].dropna() >= 0).all(), "Negative PM2.5 values"


def check_screening_flag_logic(screening_df: pd.DataFrame) -> None:
    flagged = screening_df[screening_df["screening_flag"]]
    assert (flagged["indicator_percentile_wi"] >= 0.75).all()
    assert (flagged["overall_svi_percentile"] >= 0.75).all()


def check_no_risk_score_column(screening_df: pd.DataFrame) -> None:
    assert FORBIDDEN_COLUMNS.isdisjoint(screening_df.columns), "Forbidden column name found"


def missingness_summary(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    pct_missing = df.isna().mean().sort_values(ascending=False)
    return pd.DataFrame({"table": table_name, "column": pct_missing.index, "pct_missing": pct_missing.values})


def main() -> None:
    tracts = gpd.read_parquet(PROCESSED_DIR / "wi_tracts_2022.parquet")
    svi = pd.read_parquet(PROCESSED_DIR / "wi_svi_2022.parquet")
    indicator = pd.read_parquet(PROCESSED_DIR / "wi_pm25_2022.parquet")
    screening = gpd.read_parquet(PROCESSED_DIR / "tract_screening_view.parquet")

    check_unique_geoid(tracts)
    check_no_null_geometry(tracts)
    check_geoid_format(tracts)
    check_wisconsin_fips_prefix(tracts)
    check_crs(tracts)
    check_join_coverage(screening, tracts)
    check_no_unexplained_missing_geometry(screening)
    check_valid_svi_range(svi)
    check_indicator_year_present(indicator)
    check_no_negative_pm25(indicator)
    check_screening_flag_logic(screening)
    check_no_risk_score_column(screening)
    print("All validation checks passed.\n")

    summaries = pd.concat(
        [
            missingness_summary(tracts.drop(columns="geometry"), "wi_tracts_2022"),
            missingness_summary(svi, "wi_svi_2022"),
            missingness_summary(indicator, "wi_pm25_2022"),
            missingness_summary(screening.drop(columns="geometry"), "tract_screening_view"),
        ],
        ignore_index=True,
    )
    print(summaries.to_string(index=False))


if __name__ == "__main__":
    main()
