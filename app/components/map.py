"""Builds the Folium map for the screening page: an indicator choropleth
(always on), an optional SVI choropleth layer, and an optional air-monitor
contextual point layer. Layer visibility is controlled entirely by the
sidebar checkboxes in app/streamlit_app.py (which gate whether a layer is
added to the map at all) -- there is deliberately no second, competing
Folium LayerControl toggle. The legend for these layers is rendered
separately in Streamlit itself (app/components/legend.py), not as floating
branca color bars on the map, so it stays visible and readable regardless of
which layers are toggled.

The default map view (when no `bounds` override is given) is always derived
from `gdf.total_bounds()`, not a fixed state-specific center/zoom constant --
this is what lets a newly selected state's tracts be framed correctly with
no per-state map constant needed.
"""
from __future__ import annotations

import branca.colormap as bcm
import folium
import geopandas as gpd
import pandas as pd

INDICATOR_COLORS = ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"]
SVI_COLORS = ["#f7fbff", "#9ecae1", "#3182bd", "#08306b"]
NO_DATA_COLOR = "#cccccc"
FLAGGED_OUTLINE_COLOR = "#bd0026"  # matches scatter.py's SCREENING_COLOR_MAP red


def _percentile_style(cmap: bcm.LinearColormap, field: str, outline_flagged: bool = False):
    def style_function(feature: dict) -> dict:
        value = feature["properties"].get(field)
        fill = NO_DATA_COLOR if value is None else cmap(value)
        flagged = outline_flagged and feature["properties"].get("screening_flag")
        return {
            "fillColor": fill,
            "color": FLAGGED_OUTLINE_COLOR if flagged else "white",
            "weight": 2.5 if flagged else 0.3,
            "fillOpacity": 0.75,
        }

    return style_function


def build_screening_map(
    gdf: gpd.GeoDataFrame,
    monitor_df: pd.DataFrame,
    indicator_label: str,
    state_abbr: str,
    show_svi_layer: bool = False,
    show_monitor_points: bool = True,
    bounds: list[list[float]] | None = None,
) -> folium.Map:
    m = folium.Map(tiles="OpenStreetMap")
    if bounds:
        m.fit_bounds(bounds)
    elif len(gdf):
        minx, miny, maxx, maxy = gdf.total_bounds
        m.fit_bounds([[miny, minx], [maxy, maxx]])

    indicator_cmap = bcm.LinearColormap(colors=INDICATOR_COLORS, vmin=0, vmax=1)
    indicator_geojson = gdf[[
        "geoid", "geography_name", "county_name", "indicator_value",
        "indicator_percentile_wi", "concern_percentile_wi", "overall_svi_percentile",
        "screening_flag", "geometry",
    ]]
    folium.GeoJson(
        indicator_geojson,
        name=f"{indicator_label} (relative concern)",
        style_function=_percentile_style(indicator_cmap, "concern_percentile_wi", outline_flagged=True),
        highlight_function=lambda f: {"weight": 3, "color": "black"},
        tooltip=folium.GeoJsonTooltip(
            fields=[
                "geography_name", "county_name", "indicator_value",
                "indicator_percentile_wi", "concern_percentile_wi", "overall_svi_percentile",
                "screening_flag",
            ],
            aliases=[
                "Tract", "County", f"{indicator_label} value",
                f"Indicator percentile ({state_abbr}-relative)", "Relative concern (percentile)",
                "SVI percentile (national-relative)", "Flagged for review",
            ],
            localize=True,
        ),
    ).add_to(m)

    if show_svi_layer:
        svi_cmap = bcm.LinearColormap(colors=SVI_COLORS, vmin=0, vmax=1)
        svi_geojson = gdf[["geoid", "geography_name", "overall_svi_percentile", "geometry"]]
        folium.GeoJson(
            svi_geojson,
            name="SVI — contextual layer (national-relative)",
            style_function=_percentile_style(svi_cmap, "overall_svi_percentile"),
            tooltip=folium.GeoJsonTooltip(
                fields=["geography_name", "overall_svi_percentile"],
                aliases=["Tract", "SVI percentile (national-relative)"],
                localize=True,
            ),
        ).add_to(m)

    if show_monitor_points:
        monitor_layer = folium.FeatureGroup(
            name="Air monitor points (EPA AQS, contextual only — not joined to tracts)"
        )
        for _, row in monitor_df.iterrows():
            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                radius=5,
                color="#555555",
                weight=1,
                fill=True,
                fill_color="#ffcc00",
                fill_opacity=0.9,
                tooltip=(
                    f"{row['name']} ({row['point_type']}) — contextual only, "
                    f"not joined to any tract | {row['pollutant_or_permit_type']}"
                ),
            ).add_to(monitor_layer)
        monitor_layer.add_to(m)

    return m
