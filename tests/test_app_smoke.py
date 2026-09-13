"""Smoke tests for the Stage Two Streamlit app. These call component/loader
functions directly (no live Streamlit server needed - st.cache_data executes
fine on direct import) to catch import errors and basic contract breaks
without a browser.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_data_loader_imports_and_loads():
    from app.data_loader import load_monitor_points, load_screening_view

    gdf = load_screening_view()
    assert gdf.crs.to_epsg() == 4326
    assert "screening_flag" in gdf.columns
    assert "concern_percentile_wi" in gdf.columns
    assert "state_abbr" in gdf.columns
    assert len(gdf) > 0

    monitors = load_monitor_points()
    assert {"latitude", "longitude"}.issubset(monitors.columns)


def _pm25_only(gdf, state_abbr="WI"):
    return gdf[
        (gdf["selected_indicator"] == "PM2.5 Annual Concentration") & (gdf["state_abbr"] == state_abbr)
    ]


def test_map_component_builds_without_streamlit_runtime():
    from app.components.map import build_screening_map
    from app.data_loader import load_monitor_points, load_screening_view

    gdf = _pm25_only(load_screening_view())
    monitors = load_monitor_points()
    m = build_screening_map(
        gdf, monitors, "PM2.5 Annual Concentration", "WI",
        show_svi_layer=True, show_monitor_points=True,
    )
    assert m._repr_html_()


def test_map_component_builds_with_county_bounds():
    from app.components.map import build_screening_map
    from app.data_loader import load_monitor_points, load_screening_view

    gdf = _pm25_only(load_screening_view())
    county_gdf = gdf[gdf["county_name"] == gdf["county_name"].dropna().iloc[0]]
    minx, miny, maxx, maxy = county_gdf.total_bounds
    bounds = [[miny, minx], [maxy, maxx]]
    monitors = load_monitor_points()
    m = build_screening_map(
        county_gdf, monitors, "PM2.5 Annual Concentration", "WI",
        show_svi_layer=False, show_monitor_points=False, bounds=bounds,
    )
    assert m._repr_html_()


def test_scatter_component_builds():
    from app.components.scatter import build_scatter_figure
    from app.data_loader import load_screening_view

    fig = build_scatter_figure(_pm25_only(load_screening_view()), "PM2.5 Annual Concentration", "Wisconsin")
    assert len(fig.data) > 0


def test_legend_component_renders_without_streamlit_runtime():
    from app.components.legend import render_legend

    # st.markdown executes fine outside a live Streamlit server (no
    # ScriptRunContext needed for a pure render call); this just confirms it
    # doesn't raise for every show_svi_layer/show_monitor_points combination.
    render_legend("PM2.5 Annual Concentration", show_svi_layer=True, show_monitor_points=True)
    render_legend("Wetland & Surface Water Extent", show_svi_layer=False, show_monitor_points=False)


def test_research_appendix_renders_without_streamlit_runtime():
    from app.components.research_appendix import render_research_appendix

    # Exercises the full appendix (dataframes, tabs, images) in Streamlit's
    # bare-execution mode -- same "no live server needed" property the other
    # component tests rely on.
    render_research_appendix()


def test_methodology_boundary_language_present():
    """Canary against methodology.md drift for every boundary list rendered
    in the live app (methods drawer's WHAT_THIS_IS_NOT + PURPOSE_AND_BOUNDARY
    blockquote, and the research appendix's RESEARCH_APPENDIX_BOUNDARY) --
    not just the original four "what this is not" phrases."""
    methodology = (REPO_ROOT / "methodology.md").read_text(encoding="utf-8")
    for phrase in (
        # PURPOSE_AND_BOUNDARY blockquote (methods drawer)
        "descriptive screening tool",
        "rank community worthiness",
        # WHAT_THIS_IS_NOT (methods drawer)
        "Not an exposure model",
        "Not a health outcomes model",
        "Not causal",
        "Not a ranking of community worth or need",
        # RESEARCH_APPENDIX_BOUNDARY (research appendix "what this does not show")
        "A Milwaukee NO2 surface outside its 3 known monitor sites",
        "Madison PM2.5 predictions presented as reliable time-general estimates",
        "without recalibration",
        "Any satellite-layer description implying TROPOMI/MODIS materially",
        "A map combining either pilot's unvalidated predictions with SVI",
    ):
        assert phrase in methodology, (
            f"Expected phrase {phrase!r} in methodology.md — if this was "
            "intentionally reworded, update app/text_content.py to match."
        )
