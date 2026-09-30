"""Validation gates: pure functions that inspect a cleaned frame and report.

A gate never mutates its input and never raises for bad data; it returns a
``GateResult``. ``enforce`` turns any failures into one loud ``GateFailure`` that
lists every failed gate at once, so a fix does not take one run per problem.

The frame under test is long format with the columns in ``VALUE_COLUMNS``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

import pandas as pd

from src.connectors.catalog import CatalogEntry
from src.connectors.fips import STATE_FIPS
from src.connectors.forbidden import forbidden_columns
from src.connectors.normalize import LEVEL_LENGTH

VALUE_COLUMNS: tuple[str, ...] = (
    "geoid",
    "geo_vintage",
    "indicator_key",
    "period_start",
    "period_end",
    "value",
    "moe_or_ci_low",
    "moe_or_ci_high",
    "coverage_flag",
)
NATURAL_KEY: tuple[str, ...] = (
    "geoid",
    "geo_vintage",
    "indicator_key",
    "period_start",
    "period_end",
)
COVERAGE_FLAGS = frozenset({"ok", "suppressed", "partial_coverage", "imputed", "no_data"})
DECLARED_SRID = 4269
_SAMPLE = 5


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str = ""


class GateFailure(Exception):
    """One or more validation gates failed; nothing was loaded."""

    def __init__(self, failures: list[GateResult]) -> None:
        self.failures = failures
        lines = [f"  - {r.name}: {r.detail}" for r in failures]
        super().__init__(f"{len(failures)} validation gate(s) failed:\n" + "\n".join(lines))


def _result(name: str, bad: pd.Series, what: str, frame: pd.DataFrame, column: str) -> GateResult:
    """Pass if no row is bad; otherwise report the count and a few examples."""
    count = int(bad.sum())
    if count == 0:
        return GateResult(name, True)
    sample = frame.loc[bad, column].astype(str).head(_SAMPLE).tolist()
    return GateResult(name, False, f"{count} row(s) {what}, e.g. {sample}")


def enforce(results: Iterable[GateResult]) -> list[GateResult]:
    """Return the results if all passed; otherwise raise ``GateFailure``."""
    collected = list(results)
    failures = [r for r in collected if not r.passed]
    if failures:
        raise GateFailure(failures)
    return collected


# --- structure ----------------------------------------------------------------


def gate_not_empty(df: pd.DataFrame) -> GateResult:
    return GateResult("not_empty", len(df) > 0, "" if len(df) else "no rows to load")


def gate_required_columns(df: pd.DataFrame) -> GateResult:
    missing = [c for c in VALUE_COLUMNS if c not in df.columns]
    return GateResult("required_columns", not missing, f"missing {missing}" if missing else "")


def gate_no_forbidden_columns(columns: Iterable[str]) -> GateResult:
    found = forbidden_columns(columns)
    return GateResult(
        "no_forbidden_columns", not found, f"composite-score column(s) {found}" if found else ""
    )


# --- identifiers --------------------------------------------------------------


def gate_geoid_format(df: pd.DataFrame, level: str) -> GateResult:
    """Zero-padded digit strings of the length the level requires."""
    width = LEVEL_LENGTH[level]
    ids = df["geoid"].astype("string")
    bad = ~ids.str.fullmatch(rf"[0-9]{{{width}}}").fillna(False).astype(bool)
    return _result("geoid_format", bad, f"are not {width}-digit {level} GEOIDs", df, "geoid")


def gate_state_prefix(df: pd.DataFrame, level: str) -> GateResult:
    """The state part of a GEOID must be a real state or territory FIPS code."""
    if level == "zcta":  # ZCTAs carry no state prefix
        return GateResult("state_prefix", True)
    prefix = df["geoid"].astype("string").str.slice(0, 2)
    bad = ~prefix.isin(list(STATE_FIPS)).fillna(False).astype(bool)
    return _result("state_prefix", bad, "have an unknown state FIPS prefix", df, "geoid")


def gate_no_duplicates(df: pd.DataFrame) -> GateResult:
    bad = df.duplicated(subset=list(NATURAL_KEY), keep=False)
    return _result("no_duplicates", bad, "repeat the natural key", df, "geoid")


def gate_vintage_recorded(df: pd.DataFrame, known_vintages: Collection[int]) -> GateResult:
    """Every row carries a geography vintage that exists in ``core.geographies``."""
    vintage = df["geo_vintage"]
    bad = vintage.isna() | ~vintage.isin(list(known_vintages))
    return _result("vintage_recorded", bad, "have a missing or unloaded vintage", df, "geo_vintage")


def gate_geographies_present(df: pd.DataFrame, known: Collection[tuple[str, int]]) -> GateResult:
    """Join audit: every (geoid, vintage) must exist before values are loaded."""
    pairs = pd.Series(list(zip(df["geoid"], df["geo_vintage"], strict=True)), index=df.index)
    bad = ~pairs.isin(set(known))
    return _result("geographies_present", bad, "match no loaded geography", df, "geoid")


def gate_crs(epsg: int | None, declared: int = DECLARED_SRID) -> GateResult:
    """CRS must be known and equal the declared storage SRID before any spatial step."""
    if epsg is None:
        return GateResult("crs_matches", False, "CRS is missing; refusing to guess")
    ok = epsg == declared
    return GateResult("crs_matches", ok, "" if ok else f"EPSG:{epsg} != declared EPSG:{declared}")


# --- values -------------------------------------------------------------------


def gate_plausible_range(df: pd.DataFrame, catalog: Mapping[str, CatalogEntry]) -> GateResult:
    problems: list[str] = []
    for key, group in df.groupby("indicator_key"):
        entry = catalog.get(str(key))
        if entry is None:
            problems.append(f"{key}: not in catalog")
            continue
        values = group["value"].dropna()
        below = int((values < entry.plausible_min).sum()) if entry.plausible_min is not None else 0
        above = int((values > entry.plausible_max).sum()) if entry.plausible_max is not None else 0
        if below or above:
            problems.append(
                f"{key}: {below} below {entry.plausible_min}, {above} above {entry.plausible_max}"
            )
    return GateResult("plausible_range", not problems, "; ".join(problems))


def gate_sentinels_gone(df: pd.DataFrame, sentinels: Collection[float]) -> GateResult:
    """No missing-value code may survive cleaning in a value column."""
    remaining: dict[str, int] = {}
    for column in ("value", "moe_or_ci_low", "moe_or_ci_high"):
        count = int(df[column].isin(list(sentinels)).sum())
        if count:
            remaining[column] = count
    return GateResult(
        "sentinels_gone", not remaining, f"sentinel codes remain: {remaining}" if remaining else ""
    )


def gate_flags_consistent(df: pd.DataFrame) -> GateResult:
    unknown = ~df["coverage_flag"].isin(list(COVERAGE_FLAGS))
    ok_without_value = (df["coverage_flag"] == "ok") & df["value"].isna()
    if int(unknown.sum()) or int(ok_without_value.sum()):
        return GateResult(
            "flags_consistent",
            False,
            f"{int(unknown.sum())} unknown flag(s); {int(ok_without_value.sum())} 'ok' row(s) "
            "without a value",
        )
    return GateResult("flags_consistent", True)


# --- time ---------------------------------------------------------------------


def gate_periods(df: pd.DataFrame, allow_multiple_periods: bool = False) -> GateResult:
    """Periods are present, ordered, and never silently mixed within one indicator."""
    start = pd.to_datetime(df["period_start"], errors="coerce")
    end = pd.to_datetime(df["period_end"], errors="coerce")
    missing = int((start.isna() | end.isna()).sum())
    reversed_ = int((end < start).sum())
    problems: list[str] = []
    if missing:
        problems.append(f"{missing} row(s) with a missing or unreadable period")
    if reversed_:
        problems.append(f"{reversed_} row(s) with period_end before period_start")
    if not allow_multiple_periods:
        spans = df.assign(_s=start, _e=end).groupby("indicator_key")[["_s", "_e"]].nunique()
        mixed = sorted(spans.index[(spans["_s"] > 1) | (spans["_e"] > 1)].astype(str))
        if mixed:
            problems.append(f"multiple periods mixed for {mixed}")
        vintages = df.groupby("indicator_key")["geo_vintage"].nunique()
        multi = sorted(vintages.index[vintages > 1].astype(str))
        if multi:
            problems.append(f"multiple geography vintages mixed for {multi}")
    return GateResult("periods", not problems, "; ".join(problems))


# --- catalog and coverage -----------------------------------------------------


def gate_catalog_metadata(df: pd.DataFrame, catalog: Mapping[str, CatalogEntry]) -> GateResult:
    """Every indicator has a catalog entry with a source URL and a license."""
    problems = []
    for key in sorted(df["indicator_key"].dropna().unique()):
        entry = catalog.get(str(key))
        if entry is None or not entry.source_url.strip() or not entry.license.strip():
            problems.append(str(key))
    return GateResult(
        "catalog_metadata",
        not problems,
        f"no complete catalog entry for {problems}" if problems else "",
    )


Coverage = Mapping[tuple[str, str], float]  # (indicator_key, state_fips) -> share with a value


def coverage_by_state(df: pd.DataFrame, universe: pd.DataFrame) -> dict[tuple[str, str], float]:
    """Share of each state's geographies that have a value, per indicator.

    ``universe`` has one row per expected geography with ``geoid`` and
    ``state_fips``. A geography absent from ``df`` counts as having no value.
    """
    result: dict[tuple[str, str], float] = {}
    totals = universe.groupby("state_fips")["geoid"].nunique()
    for key, group in df.groupby("indicator_key"):
        have = group.dropna(subset=["value"]).merge(universe, on="geoid", how="inner")
        counts = have.groupby("state_fips")["geoid"].nunique()
        for state, total in totals.items():
            result[(str(key), str(state))] = float(counts.get(state, 0)) / float(total)
    return result


def gate_coverage_not_dropped(
    current: Coverage,
    prior: Coverage | None,
    max_drop: float = 0.10,
    override_note: str | None = None,
) -> GateResult:
    """Fail when a state's coverage falls sharply against the prior release.

    ``max_drop`` is in absolute share (0.10 = ten percentage points). A state or
    indicator present in the prior release but absent now counts as zero. A
    non-blank ``override_note`` records a deliberate exception and lets it pass.
    """
    if not prior:
        return GateResult("coverage_not_dropped", True, "no prior release to compare")
    drops = {
        key: (before, current.get(key, 0.0))
        for key, before in prior.items()
        if before - current.get(key, 0.0) > max_drop
    }
    if not drops:
        return GateResult("coverage_not_dropped", True)
    detail = "; ".join(
        f"{k[0]} in state {k[1]}: {b:.0%} -> {a:.0%}"
        for k, (b, a) in sorted(drops.items())[:_SAMPLE]
    )
    if override_note and override_note.strip():
        return GateResult(
            "coverage_not_dropped", True, f"overridden ({override_note.strip()}): {detail}"
        )
    return GateResult(
        "coverage_not_dropped", False, f"coverage fell by more than {max_drop:.0%}: {detail}"
    )
