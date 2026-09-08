"""Sortable tract review table. Defaults to screening_flag == True rows
("high-high" review candidates) with an option to see every tract."""
from __future__ import annotations

import geopandas as gpd
import streamlit as st

TABLE_COLUMNS = [
    "geography_name",
    "county_name",
    "indicator_value",
    "indicator_percentile_wi",
    "overall_svi_percentile",
    "screening_flag",
    "screening_rationale",
    "data_coverage_flag",
]


def render_screening_table(gdf: gpd.GeoDataFrame) -> None:
    st.subheader("Tract review table")
    show_all = st.checkbox("Show all tracts (default: flagged only)", value=False)
    df = gdf if show_all else gdf[gdf["screening_flag"]]
    st.caption(f"{len(df)} of {len(gdf)} tracts shown.")

    st.dataframe(
        df[TABLE_COLUMNS].sort_values("indicator_percentile_wi", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "geography_name": st.column_config.TextColumn("Tract"),
            "county_name": st.column_config.TextColumn("County"),
            "indicator_value": st.column_config.NumberColumn("Indicator value", format="%.2f"),
            "indicator_percentile_wi": st.column_config.ProgressColumn(
                "Indicator %ile (WI)", min_value=0, max_value=1, format="%.2f"
            ),
            "overall_svi_percentile": st.column_config.ProgressColumn(
                "SVI %ile (national)", min_value=0, max_value=1, format="%.2f"
            ),
            "screening_flag": st.column_config.CheckboxColumn("Flagged"),
            "screening_rationale": st.column_config.TextColumn("Rationale", width="large"),
            "data_coverage_flag": st.column_config.TextColumn("Coverage"),
        },
    )
