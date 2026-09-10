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
    from app.data_loader import load_dnr_points, load_screening_view

    gdf = load_screening_view()
    assert gdf.crs.to_epsg() == 4326
    assert "screening_flag" in gdf.columns
    assert "concern_percentile_wi" in gdf.columns
    assert len(gdf) > 0

    dnr = load_dnr_points()
    assert {"latitude", "longitude"}.issubset(dnr.columns)


def _pm25_only(gdf):
    return gdf[gdf["selected_indicator"] == "PM2.5 Annual Concentration"]


def test_map_component_builds_without_streamlit_runtime():
    from app.components.map import build_screening_map
    from app.data_loader import load_dnr_points, load_screening_view

    gdf = _pm25_only(load_screening_view())
    dnr = load_dnr_points()
    m = build_screening_map(gdf, dnr, "PM2.5 Annual Concentration", show_svi_layer=True, show_dnr_points=True)
    assert m._repr_html_()


def test_map_component_builds_with_county_bounds():
    from app.components.map import build_screening_map
    from app.data_loader import load_dnr_points, load_screening_view

    gdf = _pm25_only(load_screening_view())
    county_gdf = gdf[gdf["county_name"] == gdf["county_name"].dropna().iloc[0]]
    minx, miny, maxx, maxy = county_gdf.total_bounds
    bounds = [[miny, minx], [maxy, maxx]]
    dnr = load_dnr_points()
    m = build_screening_map(
        county_gdf, dnr, "PM2.5 Annual Concentration", show_svi_layer=False,
        show_dnr_points=False, bounds=bounds,
    )
    assert m._repr_html_()


def test_scatter_component_builds():
    from app.components.scatter import build_scatter_figure
    from app.data_loader import load_screening_view

    fig = build_scatter_figure(_pm25_only(load_screening_view()), "PM2.5 Annual Concentration")
    assert len(fig.data) > 0


def test_legend_component_renders_without_streamlit_runtime():
    from app.components.legend import render_legend

    # st.markdown executes fine outside a live Streamlit server (no
    # ScriptRunContext needed for a pure render call); this just confirms it
    # doesn't raise for every show_svi_layer/show_dnr_points combination.
    render_legend("PM2.5 Annual Concentration", show_svi_layer=True, show_dnr_points=True)
    render_legend("Wetland & Surface Water Extent", show_svi_layer=False, show_dnr_points=False)


def test_research_appendix_renders_without_streamlit_runtime():
    from app.components.research_appendix import render_research_appendix

    # Exercises the full appendix (dataframes, tabs, images) in Streamlit's
    # bare-execution mode -- same "no live server needed" property the other
    # component tests rely on.
    render_research_appendix()


def test_methodology_boundary_language_present():
    methodology = (REPO_ROOT / "methodology.md").read_text(encoding="utf-8")
    for phrase in (
        "descriptive screening tool",
        "Not an exposure model",
        "Not a health outcomes model",
        "Not causal",
    ):
        assert phrase in methodology, (
            f"Expected phrase {phrase!r} in methodology.md — if this was "
            "intentionally reworded, update app/text_content.py to match."
        )
