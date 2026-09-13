"""App-level defaults. The state shown is now driven by a real sidebar
selector (app/streamlit_app.py) backed by whichever states exist in
tract_screening_view.parquet -- this just picks which one is preselected.
"""
from __future__ import annotations

DEFAULT_STATE_ABBR = "WI"
