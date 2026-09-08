"""Interactive Plotly scatter: indicator value vs. overall SVI percentile,
colored by screening_flag. Mirrors src/map_layers.py's static scatter_pm25_vs_svi.png
but generalized to whichever indicator is currently selected.
"""
from __future__ import annotations

import geopandas as gpd
import plotly.express as px
import plotly.graph_objects as go

SCREENING_COLOR_MAP = {"Flagged for review": "#bd0026", "Not flagged": "#a6bddb"}


def build_scatter_figure(gdf: gpd.GeoDataFrame, indicator_label: str = "Indicator value") -> go.Figure:
    df = gdf.dropna(subset=["indicator_value", "overall_svi_percentile"]).copy()
    df["Screening status"] = df["screening_flag"].map(
        {True: "Flagged for review", False: "Not flagged"}
    )

    fig = px.scatter(
        df,
        x="indicator_value",
        y="overall_svi_percentile",
        color="Screening status",
        color_discrete_map=SCREENING_COLOR_MAP,
        hover_name="geography_name",
        hover_data={
            "county_name": True,
            "indicator_percentile_wi": ":.2f",
            "overall_svi_percentile": ":.2f",
            "indicator_value": ":.2f",
            "Screening status": False,
        },
        labels={
            "indicator_value": f"{indicator_label} (raw value)",
            "overall_svi_percentile": "Overall SVI percentile (national-relative)",
        },
        title=f"{indicator_label} vs. Social Vulnerability (Wisconsin census tracts)",
    )
    fig.update_layout(legend_title_text="")
    return fig
