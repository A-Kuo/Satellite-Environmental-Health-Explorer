"""Interactive Streamlit screening application. Folium map, sortable
screening table, and methods/limitations drawer, built on the validated
Stage One indicator/SVI/monitor-point layers plus the tract-level
agricultural/wetland indicators added since. The non-promoted modeling
research renders inside the "Research Appendix" tab via
app/components/research_appendix.py -- a single-page app (Streamlit's
`pages/` multipage mechanism was dropped in favor of a header tab bar so
page navigation no longer competes with the sidebar's filter controls for
the same space).

The state selector is a real filter, not a placeholder: options come from
whichever states exist in tract_screening_view.parquet (src/states.py is the
source of truth for which states CAN be onboarded; this list is which ones
actually HAVE been). Percentiles are always state-relative (see
src/spatial_join.py), so selecting a state shows that state's own
self-contained screening view, the same way the county filter already
narrows within one state.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st
from streamlit_folium import st_folium

from app.components.legend import render_legend
from app.components.map import build_screening_map
from app.components.methods_drawer import render_methods_drawer
from app.components.research_appendix import render_research_appendix
from app.components.scatter import build_scatter_figure
from app.components.table import render_screening_table
from app.config import DEFAULT_STATE_ABBR
from app.data_loader import load_monitor_points, load_screening_view
from app.text_content import BASIS_MISMATCH_NOTE, DISCLAIMER_BANNER

st.set_page_config(page_title="Regional Environmental Health Explorer", layout="wide")

screening_gdf = load_screening_view()
monitor_df = load_monitor_points()

state_options = sorted(screening_gdf["state_abbr"].dropna().unique())
default_index = state_options.index(DEFAULT_STATE_ABBR) if DEFAULT_STATE_ABBR in state_options else 0
selected_state_abbr = st.sidebar.selectbox("State", state_options, index=default_index)

state_gdf = screening_gdf[screening_gdf["state_abbr"] == selected_state_abbr]
selected_state_name = state_gdf["state_name"].iloc[0]

st.title(f"{selected_state_name} Environmental Health Explorer")
st.caption(DISCLAIMER_BANNER)

tab_screening, tab_appendix = st.tabs(["Screening", "Research Appendix"])

with tab_screening:
    state_monitor_df = (
        monitor_df[monitor_df["state_abbr"] == selected_state_abbr]
        if "state_abbr" in monitor_df.columns
        else monitor_df
    )

    indicator_options = sorted(state_gdf["selected_indicator"].dropna().unique())
    selected_indicator = st.sidebar.selectbox("Environmental indicator", indicator_options)

    county_options = [f"All {selected_state_name}"] + sorted(state_gdf["county_name"].dropna().unique())
    selected_county = st.sidebar.selectbox("County", county_options)

    show_svi_layer = st.sidebar.checkbox("Show SVI as separate layer", value=False)
    show_monitor_points = st.sidebar.checkbox("Show air monitor points (contextual)", value=True)
    st.sidebar.caption(
        "Air monitor points (EPA AQS) are a contextual layer only — not joined to any tract."
    )

    filtered = state_gdf[state_gdf["selected_indicator"] == selected_indicator]
    bounds = None
    if selected_county != f"All {selected_state_name}":
        filtered = filtered[filtered["county_name"] == selected_county]
        if len(filtered):
            minx, miny, maxx, maxy = filtered.total_bounds
            bounds = [[miny, minx], [maxy, maxx]]

    col_map, col_scatter = st.columns([3, 2])
    with col_map:
        st.subheader("Screening map")
        fmap = build_screening_map(
            filtered, state_monitor_df, selected_indicator, selected_state_abbr,
            show_svi_layer, show_monitor_points, bounds=bounds,
        )
        st_folium(fmap, use_container_width=True, height=600, returned_objects=[])
        render_legend(selected_indicator, show_svi_layer, show_monitor_points)
        st.caption(BASIS_MISMATCH_NOTE)
    with col_scatter:
        st.subheader("Indicator vs. social vulnerability")
        st.plotly_chart(
            build_scatter_figure(filtered, selected_indicator, selected_state_name),
            use_container_width=True,
        )

    render_screening_table(filtered, selected_state_abbr)
    render_methods_drawer()

with tab_appendix:
    render_research_appendix()
