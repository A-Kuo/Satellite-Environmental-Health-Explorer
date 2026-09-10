"""Interactive Streamlit screening application. Folium map, sortable
screening table, and methods/limitations drawer, built on the validated
Stage One indicator/SVI/DNR layers plus the tract-level agricultural/wetland
indicators added since. The non-promoted modeling research renders inside
the "Research Appendix" tab via app/components/research_appendix.py -- a
single-page app (Streamlit's `pages/` multipage mechanism was dropped in
favor of a header tab bar so page navigation no longer competes with the
sidebar's filter controls for the same space).
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
from app.config import STATE_ABBR, STATE_NAME
from app.data_loader import load_dnr_points, load_screening_view
from app.text_content import BASIS_MISMATCH_NOTE, DISCLAIMER_BANNER

st.set_page_config(page_title=f"{STATE_ABBR} Environmental Health Explorer", layout="wide")

st.title(f"{STATE_NAME} Environmental Health Explorer")
st.caption(DISCLAIMER_BANNER)

tab_screening, tab_appendix = st.tabs(["Screening", "Research Appendix"])

with tab_screening:
    screening_gdf = load_screening_view()
    dnr_df = load_dnr_points()

    # Multi-state scaffolding (intentionally minimal, see README.md's
    # "Multi-state roadmap"): a visible placeholder, not a functional switch.
    st.sidebar.selectbox("State", [f"{STATE_NAME} (more states coming)"], disabled=True)

    indicator_options = sorted(screening_gdf["selected_indicator"].dropna().unique())
    selected_indicator = st.sidebar.selectbox("Environmental indicator", indicator_options)

    county_options = [f"All {STATE_NAME}"] + sorted(screening_gdf["county_name"].dropna().unique())
    selected_county = st.sidebar.selectbox("County", county_options)

    show_svi_layer = st.sidebar.checkbox("Show SVI as separate layer", value=False)
    show_dnr_points = st.sidebar.checkbox("Show DNR points (contextual)", value=True)
    st.sidebar.caption(
        "DNR points are a contextual layer only — not joined to any tract."
    )

    filtered = screening_gdf[screening_gdf["selected_indicator"] == selected_indicator]
    bounds = None
    if selected_county != f"All {STATE_NAME}":
        filtered = filtered[filtered["county_name"] == selected_county]
        if len(filtered):
            minx, miny, maxx, maxy = filtered.total_bounds
            bounds = [[miny, minx], [maxy, maxx]]

    col_map, col_scatter = st.columns([3, 2])
    with col_map:
        st.subheader("Screening map")
        fmap = build_screening_map(
            filtered, dnr_df, selected_indicator, show_svi_layer, show_dnr_points, bounds=bounds
        )
        st_folium(fmap, use_container_width=True, height=600, returned_objects=[])
        render_legend(selected_indicator, show_svi_layer, show_dnr_points)
        st.caption(BASIS_MISMATCH_NOTE)
    with col_scatter:
        st.subheader("Indicator vs. social vulnerability")
        st.plotly_chart(build_scatter_figure(filtered, selected_indicator), use_container_width=True)

    render_screening_table(filtered)
    render_methods_drawer()

with tab_appendix:
    render_research_appendix()
