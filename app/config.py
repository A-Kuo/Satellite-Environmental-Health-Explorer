"""State-level constants for the app's UI copy. Multi-state scaffolding is
intentionally minimal (see README.md's "Multi-state roadmap") -- this file
lets the UI's Wisconsin-specific wording come from one place rather than
scattered literals, without implying a second state is actually supported
yet (the sidebar's state selector, in app/streamlit_app.py, stays a
disabled placeholder).
"""
from __future__ import annotations

STATE_NAME = "Wisconsin"
STATE_ABBR = "WI"
