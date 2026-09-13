"""Builds the per-state geometries table and the derived multi-state
tract_screening_view by joining SVI + environmental indicators onto census
tract geometries.

agent.md's fixed repo structure has no dedicated "clean tracts" module, so
tract-geometry preparation (from the raw TIGER shapefile) lives here, as the
first step before the join itself. Contextual monitor points moved to
src/ingest_monitors.py (EPA AQS, state-agnostic) -- this module no longer
builds them.

Run `python -m src.spatial_join --state <ABBR>` per onboarded state: it
(re)builds that state's tracts file, then always rebuilds the combined
multi-state tract_screening_view.parquet from every state's tracts/SVI/
indicator files found on disk -- so each run leaves the combined view
current, not just that one state's slice.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.states import StateConfig, get_state

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

SCREENING_VIEW_OUT = PROCESSED_DIR / "tract_screening_view.parquet"

TARGET_CRS = "EPSG:4269"
SCREENING_PERCENTILE_THRESHOLD = 0.75

# Indicators where a LOW value is the concerning direction (e.g. wetlands are
# a protective buffer -- little wetland extent is the signal worth review,
# not a lot). Every indicator not listed here defaults to "high is concern"
# (true for PM2.5 and the agricultural-loading indicators: more of the thing
# means more concern). concern_percentile_wi normalizes both cases so that a
# high value always means "more concerning," regardless of the underlying
# indicator's own direction -- screening_flag and the map's choropleth color
# both key off concern_percentile_wi, never the raw indicator_percentile_wi.
LOW_IS_CONCERN_INDICATORS = {"Wetland & Surface Water Extent"}


def build_tracts(state: StateConfig) -> gpd.GeoDataFrame:
    tiger_zip = RAW_DIR / f"tl_2022_{state.fips}_tract.zip"
    county_fips_txt = RAW_DIR / f"st{state.fips}_{state.abbr.lower()}_cou2020.txt"

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
    gdf["geography_name"] = gdf["NAMELSAD"] + ", " + gdf["county_name"] + f", {state.name}"
    gdf["geography_type"] = "census_tract"
    gdf["state_abbr"] = state.abbr
    gdf["state_name"] = state.name

    return gdf[
        [
            "geoid", "geography_name", "geography_type", "geometry",
            "county_name", "county_fips", "state_abbr", "state_name",
        ]
    ]


def build_screening_view(
    tracts: gpd.GeoDataFrame, svi: pd.DataFrame, indicators: pd.DataFrame
) -> gpd.GeoDataFrame:
    """Builds the long-format screening view: one row per (state, geoid, indicator_name).

    `tracts` may span multiple states (each tagged with its own state_abbr
    from build_tracts()); `indicators` may stack more than one indicator's
    rows, all sharing the environmental_indicator schema. A plain merge on
    geoid expands both dimensions correctly into long format. Percentile is
    computed *within* each (state, indicator) group -- state-relative,
    always, per the project's decision to never pool percentiles across
    states (or across indicators).
    """
    assert tracts.crs is not None and tracts.crs.to_epsg() in (4269, 4326), "Unexpected tract CRS"

    merged = tracts.merge(indicators, on="geoid", how="left").merge(svi, on="geoid", how="left")

    merged["indicator_percentile_wi"] = merged.groupby(["state_abbr", "indicator_name"])[
        "indicator_value"
    ].rank(pct=True)

    # Normalizes indicator direction so a high value always means "more
    # concerning," regardless of whether the underlying indicator itself
    # trends that way (PM2.5, cropland, pasture) or the opposite way
    # (wetland extent -- see LOW_IS_CONCERN_INDICATORS above). screening_flag
    # and the map's choropleth color both key off this column, never the raw
    # indicator_percentile_wi.
    is_low_concern = merged["indicator_name"].isin(LOW_IS_CONCERN_INDICATORS)
    merged["concern_percentile_wi"] = merged["indicator_percentile_wi"].where(
        ~is_low_concern, 1 - merged["indicator_percentile_wi"]
    )

    merged["screening_flag"] = (
        (merged["concern_percentile_wi"] >= SCREENING_PERCENTILE_THRESHOLD)
        & (merged["overall_svi_percentile"] >= SCREENING_PERCENTILE_THRESHOLD)
    ).fillna(False)

    merged["screening_rationale"] = merged.apply(
        lambda row: (
            f"Selected because both the environmental indicator and SVI are at or "
            f"above the {row['state_name']} 75th percentile. This is a screening flag "
            "for analyst review, not a health-risk estimate."
            if row["screening_flag"]
            else (
                "Not flagged: the environmental indicator and/or SVI percentile for "
                f"this tract falls below the {row['state_name']} 75th-percentile "
                "screening threshold."
            )
        ),
        axis=1,
    )

    merged["selected_indicator"] = merged["indicator_name"]
    merged["last_updated"] = date.today().isoformat()

    out_cols = [
        "geoid",
        "state_abbr",
        "state_name",
        "geography_name",
        "county_name",
        "selected_indicator",
        "indicator_value",
        "indicator_percentile_wi",
        "concern_percentile_wi",
        "overall_svi_percentile",
        "data_coverage_flag",
        "screening_flag",
        "screening_rationale",
        "last_updated",
        "geometry",
    ]
    return merged[out_cols]


def combine_screening_view() -> gpd.GeoDataFrame:
    """Reads every onboarded state's tracts/SVI/indicator files present in
    data/processed/ and concatenates them into one multi-state screening
    view -- the file the app reads."""
    tract_paths = sorted(PROCESSED_DIR.glob("*_tracts_2022.parquet"))
    if not tract_paths:
        raise FileNotFoundError("No *_tracts_2022.parquet files found -- build at least one state first.")

    all_tracts = pd.concat([gpd.read_parquet(p) for p in tract_paths], ignore_index=True)
    all_tracts = gpd.GeoDataFrame(all_tracts, geometry="geometry", crs=gpd.read_parquet(tract_paths[0]).crs)

    svi_paths = sorted(PROCESSED_DIR.glob("*_svi_2022.parquet"))
    all_svi = pd.concat([pd.read_parquet(p) for p in svi_paths], ignore_index=True)

    indicator_paths = sorted(
        p for p in PROCESSED_DIR.glob("*.parquet")
        if p.name.endswith(("_pm25_2022.parquet", "_cropland_2022.parquet", "_wetlands_2022.parquet"))
    )
    all_indicators = pd.concat([pd.read_parquet(p) for p in indicator_paths], ignore_index=True)

    return build_screening_view(all_tracts, all_svi, all_indicators)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="WI", help="State abbreviation, e.g. WI, MN")
    args = parser.parse_args()
    state = get_state(args.state)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    tracts = build_tracts(state)
    tracts_out = PROCESSED_DIR / f"{state.abbr.lower()}_tracts_2022.parquet"
    tracts.to_parquet(tracts_out, index=False)
    print(f"Wrote {len(tracts):,} rows -> {tracts_out}")

    screening_view = combine_screening_view()
    screening_view.to_parquet(SCREENING_VIEW_OUT, index=False)
    n_states = screening_view["state_abbr"].nunique()
    n_indicators = screening_view["selected_indicator"].nunique()
    print(
        f"Wrote {len(screening_view):,} rows ({n_states} state(s), {n_indicators} indicators) "
        f"-> {SCREENING_VIEW_OUT}"
    )


if __name__ == "__main__":
    main()
