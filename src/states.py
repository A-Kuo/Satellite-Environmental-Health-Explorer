"""State registry -- the single source of truth for "which states exist" in
this pipeline. Wisconsin is just another entry, not a hardcoded special
case. FIPS codes below are the standard, stable 2-digit ANSI state codes;
double-check against Census's own FIPS reference table before onboarding a
new state, purely as a transcription safety check. `svi_csv_name` exists
because CDC/ATSDR's per-state SVI filename spelling has varied across
release years -- verify the exact filename (e.g. spaces vs. underscores)
against a live request before assuming the pattern holds for a new state.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateConfig:
    abbr: str
    fips: str
    name: str
    svi_csv_name: str | None = None

    def svi_name(self) -> str:
        return self.svi_csv_name or self.name


STATES: dict[str, StateConfig] = {
    "WI": StateConfig("WI", "55", "Wisconsin"),
    "MN": StateConfig("MN", "27", "Minnesota"),
    "ND": StateConfig("ND", "38", "North Dakota"),
    "SD": StateConfig("SD", "46", "South Dakota"),
    "MI": StateConfig("MI", "26", "Michigan"),
    "IA": StateConfig("IA", "19", "Iowa"),
    "IL": StateConfig("IL", "17", "Illinois"),
}

DEFAULT_STATE = "WI"

FIPS_TO_ABBR: dict[str, str] = {s.fips: s.abbr for s in STATES.values()}


def get_state(abbr: str) -> StateConfig:
    try:
        return STATES[abbr.upper()]
    except KeyError:
        raise ValueError(
            f"Unknown state abbreviation {abbr!r}. Known: {sorted(STATES)}"
        ) from None
