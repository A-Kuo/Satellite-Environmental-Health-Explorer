"""Stage Two: interactive Streamlit screening application. Folium map, sortable
screening table, and methods/limitations drawer, built only on the validated
Stage One indicator/SVI/DNR layers. The non-promoted modeling research lives
separately in app/pages/1_Research_Appendix.py and is never composed here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st
from streamlit_folium import st_folium

from app.components.map import build_screening_map
from app.components.methods_drawer import render_methods_drawer
from app.components.scatter import build_scatter_figure
from app.components.table import render_screening_table
from app.data_loader import load_dnr_points, load_screening_view
from app.text_content import BASIS_MISMATCH_NOTE, DISCLAIMER_BANNER

st.set_page_config(page_title="WI Environmental Health Explorer", layout="wide")

st.title("Wisconsin Environmental Health Explorer")
st.caption(DISCLAIMER_BANNER)

screening_gdf = load_screening_view()
dnr_df = load_dnr_points()

indicator_options = sorted(screening_gdf["selected_indicator"].dropna().unique())
selected_indicator = st.sidebar.selectbox("Environmental indicator", indicator_options)
show_svi_layer = st.sidebar.checkbox("Show SVI as separate layer", value=False)
show_dnr_points = st.sidebar.checkbox("Show DNR points (contextual)", value=True)
st.sidebar.caption(
    "DNR points are a contextual layer only — not joined to any tract."
)

filtered = screening_gdf[screening_gdf["selected_indicator"] == selected_indicator]

col_map, col_scatter = st.columns([3, 2])
with col_map:
    st.subheader("Screening map")
    fmap = build_screening_map(filtered, dnr_df, selected_indicator, show_svi_layer, show_dnr_points)
    st_folium(fmap, use_container_width=True, height=600, returned_objects=[])
    st.caption(BASIS_MISMATCH_NOTE)
with col_scatter:
    st.subheader("Indicator vs. social vulnerability")
    st.plotly_chart(build_scatter_figure(filtered, selected_indicator), use_container_width=True)

render_screening_table(filtered)
render_methods_drawer()
