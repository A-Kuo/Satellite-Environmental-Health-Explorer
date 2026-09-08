"""Renders the methods/limitations drawer attached to the screening page."""
from __future__ import annotations

import streamlit as st

from app.text_content import (
    DATA_SOURCES_TABLE,
    EJSCREEN_CAVEAT,
    MISSING_DATA_HANDLING,
    PERCENTILE_BASIS_MISMATCH,
    PURPOSE_AND_BOUNDARY,
    WHAT_THIS_IS_NOT,
)


def render_methods_drawer() -> None:
    with st.expander("Methods & limitations", expanded=False):
        st.markdown(PURPOSE_AND_BOUNDARY)

        st.markdown("**Data sources, years, and units**")
        st.table(DATA_SOURCES_TABLE)

        st.markdown("**EJScreen sourcing**")
        st.markdown(EJSCREEN_CAVEAT)

        st.markdown("**Percentile conventions**")
        st.markdown(PERCENTILE_BASIS_MISMATCH)

        st.markdown("**Missing-data handling**")
        st.markdown(MISSING_DATA_HANDLING)

        st.markdown("**What this is not**")
        for item in WHAT_THIS_IS_NOT:
            st.markdown(f"- {item}")
