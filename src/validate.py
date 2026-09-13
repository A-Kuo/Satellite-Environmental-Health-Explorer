"""Reusable validation assertions for the Stage One processed tables.

Shared by tests/ and runnable directly as a CLI, which also prints a
missingness-by-column summary for each table.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.states import STATES

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


def check_geoid_state_prefix(tracts_gdf: gpd.GeoDataFrame, valid_fips: set[str] | None = None) -> None:
    """Every GEOID's 2-digit state prefix must belong to an onboarded state
    (src/states.py), not one hardcoded value -- lets tracts from multiple
    states coexist in the same table."""
    valid_fips = valid_fips or {s.fips for s in STATES.values()}
    prefixes = tracts_gdf["geoid"].str[:2]
    assert prefixes.isin(valid_fips).all(), (
        f"GEOIDs with unrecognized state prefix present (expected one of {sorted(valid_fips)})"
    )


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


def check_fraction_range(indicator_df: pd.DataFrame) -> None:
    """For indicators expressed as a fraction of tract area (cropland,
    wetlands): values must fall in [0, 1]."""
    valid = indicator_df["indicator_value"].dropna()
    assert valid.between(0, 1).all(), "Fraction-of-area indicator value out of [0, 1] range"


def check_screening_flag_logic(screening_df: pd.DataFrame) -> None:
    """screening_flag is keyed off concern_percentile_wi (direction-normalized
    so a high value always means "more concerning"), not the raw
    indicator_percentile_wi -- see LOW_IS_CONCERN_INDICATORS in
    src/spatial_join.py. For a low-is-concern indicator (e.g. wetland
    extent), a flagged row legitimately has a LOW indicator_percentile_wi."""
    flagged = screening_df[screening_df["screening_flag"]]
    assert (flagged["concern_percentile_wi"] >= 0.75).all()
    assert (flagged["overall_svi_percentile"] >= 0.75).all()


def check_no_risk_score_column(screening_df: pd.DataFrame) -> None:
    assert FORBIDDEN_COLUMNS.isdisjoint(screening_df.columns), "Forbidden column name found"


def missingness_summary(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    pct_missing = df.isna().mean().sort_values(ascending=False)
    return pd.DataFrame({"table": table_name, "column": pct_missing.index, "pct_missing": pct_missing.values})


def main() -> None:
    # Concatenates whatever per-state files are actually present -- same
    # degrade-gracefully pattern used in src/spatial_join.py::main() -- so
    # this runs whether one state or several have been onboarded.
    tract_paths = sorted(PROCESSED_DIR.glob("*_tracts_2022.parquet"))
    svi_paths = sorted(PROCESSED_DIR.glob("*_svi_2022.parquet"))
    pm25_paths = sorted(PROCESSED_DIR.glob("*_pm25_2022.parquet"))

    tracts = pd.concat([gpd.read_parquet(p) for p in tract_paths], ignore_index=True)
    svi = pd.concat([pd.read_parquet(p) for p in svi_paths], ignore_index=True)
    indicator = pd.concat([pd.read_parquet(p) for p in pm25_paths], ignore_index=True)
    screening = gpd.read_parquet(PROCESSED_DIR / "tract_screening_view.parquet")

    check_unique_geoid(tracts)
    check_no_null_geometry(tracts)
    check_geoid_format(tracts)
    check_geoid_state_prefix(tracts)
    check_crs(tracts)
    check_join_coverage(screening, tracts)
    check_no_unexplained_missing_geometry(screening)
    check_valid_svi_range(svi)
    check_indicator_year_present(indicator)
    check_no_negative_pm25(indicator)
    check_screening_flag_logic(screening)
    check_no_risk_score_column(screening)
    print(f"All validation checks passed ({len(tract_paths)} state(s) onboarded).\n")

    summaries = pd.concat(
        [
            missingness_summary(tracts.drop(columns="geometry"), "tracts_2022"),
            missingness_summary(svi, "svi_2022"),
            missingness_summary(indicator, "pm25_2022"),
            missingness_summary(screening.drop(columns="geometry"), "tract_screening_view"),
        ],
        ignore_index=True,
    )
    print(summaries.to_string(index=False))


if __name__ == "__main__":
    main()
