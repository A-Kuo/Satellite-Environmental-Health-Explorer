"""Unified legend panel for the screening map, rendered in Streamlit itself
rather than as floating branca color bars inside the Folium map. Replaces
the earlier design where each toggled layer added its own disconnected
color-ramp widget to the map corner -- this renders every active layer's
meaning in one place, always visible regardless of which Folium layers are
currently toggled.
"""
from __future__ import annotations

import streamlit as st

from app.components.map import FLAGGED_OUTLINE_COLOR, INDICATOR_COLORS, NO_DATA_COLOR, SVI_COLORS


def _gradient_css(colors: list[str]) -> str:
    return f"linear-gradient(to right, {', '.join(colors)})"


def _ramp_html(title: str, colors: list[str], low_label: str, high_label: str) -> str:
    return f"""
    <div style="margin-bottom:0.5rem;">
      <div style="font-size:0.8rem; font-weight:600; margin-bottom:2px;">{title}</div>
      <div style="height:10px; border-radius:3px; background:{_gradient_css(colors)};"></div>
      <div style="display:flex; justify-content:space-between; font-size:0.7rem; color:#666;">
        <span>{low_label}</span><span>{high_label}</span>
      </div>
    </div>
    """


def render_legend(indicator_label: str, show_svi_layer: bool, show_dnr_points: bool) -> None:
    st.markdown("**Map legend**")

    html_parts = [
        _ramp_html(
            f"{indicator_label} — relative concern",
            INDICATOR_COLORS,
            "Low concern",
            "High concern",
        )
    ]
    if show_svi_layer:
        html_parts.append(
            _ramp_html(
                "Social Vulnerability Index (contextual, national-relative)",
                SVI_COLORS,
                "Low SVI",
                "High SVI",
            )
        )

    swatch_row = (
        '<div style="display:flex; gap:1.25rem; align-items:center; font-size:0.75rem; '
        'margin-top:4px; flex-wrap:wrap;">'
        f'<span><span style="display:inline-block; width:12px; height:12px; '
        f'border:2px solid {FLAGGED_OUTLINE_COLOR}; border-radius:2px; '
        'vertical-align:middle;"></span> Flagged for review</span>'
        f'<span><span style="display:inline-block; width:12px; height:12px; '
        f'background:{NO_DATA_COLOR}; border-radius:2px; vertical-align:middle;"></span> No data</span>'
    )
    if show_dnr_points:
        swatch_row += (
            '<span><span style="display:inline-block; width:10px; height:10px; '
            'background:#ffcc00; border:1px solid #555555; border-radius:50%; '
            'vertical-align:middle;"></span> DNR point (contextual only)</span>'
        )
    swatch_row += "</div>"
    html_parts.append(swatch_row)

    st.markdown("\n".join(html_parts), unsafe_allow_html=True)
