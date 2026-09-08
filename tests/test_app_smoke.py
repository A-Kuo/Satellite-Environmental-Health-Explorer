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
    assert len(gdf) > 0

    dnr = load_dnr_points()
    assert {"latitude", "longitude"}.issubset(dnr.columns)


def test_map_component_builds_without_streamlit_runtime():
    from app.components.map import build_screening_map
    from app.data_loader import load_dnr_points, load_screening_view

    gdf = load_screening_view()
    dnr = load_dnr_points()
    m = build_screening_map(gdf, dnr, "PM2.5 Annual Concentration", show_svi_layer=True, show_dnr_points=True)
    assert m._repr_html_()


def test_scatter_component_builds():
    from app.components.scatter import build_scatter_figure
    from app.data_loader import load_screening_view

    fig = build_scatter_figure(load_screening_view(), "PM2.5 Annual Concentration")
    assert len(fig.data) > 0


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
