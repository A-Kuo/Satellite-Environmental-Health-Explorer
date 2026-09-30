"""Validation gates: each one must pass good data and catch its own failure."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.connectors._template import TemplateConnector
from src.connectors.catalog import by_key, load_catalog
from src.connectors.gates import (
    VALUE_COLUMNS,
    GateFailure,
    GateResult,
    coverage_by_state,
    enforce,
    gate_catalog_metadata,
    gate_coverage_not_dropped,
    gate_crs,
    gate_flags_consistent,
    gate_geographies_present,
    gate_geoid_format,
    gate_no_duplicates,
    gate_no_forbidden_columns,
    gate_not_empty,
    gate_periods,
    gate_plausible_range,
    gate_required_columns,
    gate_sentinels_gone,
    gate_state_prefix,
    gate_vintage_recorded,
)

CATALOG = by_key(load_catalog(TemplateConnector.catalog_path))
KEY = "template_demo.rate"


def make_frame(
    geoids: tuple[str, ...] = ("55079000100", "55079000200"), **columns: Any
) -> pd.DataFrame:
    n = len(geoids)
    frame = pd.DataFrame(
        {
            "geoid": list(geoids),
            "geo_vintage": [2020] * n,
            "indicator_key": [KEY] * n,
            "period_start": pd.to_datetime(["2022-01-01"] * n),
            "period_end": pd.to_datetime(["2022-12-31"] * n),
            "value": [10.0 + i for i in range(n)],
            "moe_or_ci_low": [9.0 + i for i in range(n)],
            "moe_or_ci_high": [11.0 + i for i in range(n)],
            "coverage_flag": ["ok"] * n,
        }
    )
    for name, values in columns.items():
        frame[name] = values
    return frame


def test_a_clean_frame_passes_every_gate() -> None:
    df = make_frame()
    known = {("55079000100", 2020), ("55079000200", 2020)}
    results = [
        gate_not_empty(df),
        gate_required_columns(df),
        gate_no_forbidden_columns(df.columns),
        gate_geoid_format(df, "tract"),
        gate_state_prefix(df, "tract"),
        gate_no_duplicates(df),
        gate_vintage_recorded(df, {2020}),
        gate_geographies_present(df, known),
        gate_crs(4269),
        gate_plausible_range(df, CATALOG),
        gate_sentinels_gone(df, (-999,)),
        gate_flags_consistent(df),
        gate_periods(df),
        gate_catalog_metadata(df, CATALOG),
    ]
    assert all(r.passed for r in results), [r for r in results if not r.passed]
    assert enforce(results) == results


def test_the_frame_helper_matches_the_declared_columns() -> None:
    assert tuple(make_frame().columns) == VALUE_COLUMNS


# --- structure ----------------------------------------------------------------


def test_empty_frame_and_missing_columns_fail() -> None:
    assert not gate_not_empty(make_frame().iloc[0:0]).passed
    assert "value" in gate_required_columns(make_frame().drop(columns="value")).detail


def test_composite_score_columns_are_rejected() -> None:
    result = gate_no_forbidden_columns(["geoid", "value", "risk_score"])
    assert not result.passed and "risk_score" in result.detail
    assert gate_no_forbidden_columns(["geoid", "concern_percentile"]).passed


# --- identifiers --------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["5507900010", "55079000100.0", "5507900010a", "550790001001", " 55079000100"],
    ids=["short", "float_artifact", "letter", "too_long", "whitespace"],
)
def test_malformed_tract_geoids_fail(bad: str) -> None:
    assert not gate_geoid_format(make_frame(("55079000100", bad)), "tract").passed


def test_missing_geoid_fails() -> None:
    assert not gate_geoid_format(make_frame(("55079000100", None)), "tract").passed  # type: ignore[arg-type]


def test_geoid_widths_follow_the_level() -> None:
    assert gate_geoid_format(make_frame(("55", "27")), "state").passed
    assert gate_geoid_format(make_frame(("55079",)), "county").passed
    assert not gate_geoid_format(make_frame(("55079",)), "tract").passed


def test_unknown_state_prefix_fails_but_zcta_is_exempt() -> None:
    assert not gate_state_prefix(make_frame(("99079000100",)), "tract").passed
    assert gate_state_prefix(make_frame(("99079",)), "zcta").passed
    assert gate_state_prefix(make_frame(("72127000100",)), "tract").passed  # Puerto Rico


def test_duplicates_on_the_natural_key_fail_but_other_periods_do_not() -> None:
    dup = make_frame(("55079000100", "55079000100"))
    assert not gate_no_duplicates(dup).passed
    other = make_frame(
        ("55079000100", "55079000100"), period_end=pd.to_datetime(["2022-12-31", "2023-12-31"])
    )
    assert gate_no_duplicates(other).passed


def test_vintage_must_be_present_and_loaded() -> None:
    assert not gate_vintage_recorded(make_frame(geo_vintage=[2020, None]), {2020}).passed
    assert not gate_vintage_recorded(make_frame(geo_vintage=[2010, 2010]), {2020}).passed


def test_join_audit_reports_unmatched_geographies() -> None:
    known = {("55079000100", 2020)}
    result = gate_geographies_present(make_frame(), known)
    assert not result.passed and "55079000200" in result.detail
    # Same GEOID in another vintage is a different geography.
    assert not gate_geographies_present(make_frame(geo_vintage=[2010, 2010]), known).passed


def test_crs_must_be_known_and_match() -> None:
    assert gate_crs(4269).passed
    assert not gate_crs(None).passed
    assert not gate_crs(4326).passed
    assert gate_crs(4326, declared=4326).passed


# --- values -------------------------------------------------------------------


def test_values_outside_the_catalog_range_fail_and_gaps_are_ignored() -> None:
    assert not gate_plausible_range(make_frame(value=[10.0, 150.0]), CATALOG).passed
    assert not gate_plausible_range(make_frame(value=[10.0, -1.0]), CATALOG).passed
    assert gate_plausible_range(make_frame(value=[10.0, float("nan")]), CATALOG).passed


def test_an_indicator_missing_from_the_catalog_fails_both_gates() -> None:
    df = make_frame(indicator_key=["unknown.thing"] * 2)
    assert "not in catalog" in gate_plausible_range(df, CATALOG).detail
    assert not gate_catalog_metadata(df, CATALOG).passed


def test_a_catalog_entry_without_license_or_url_fails_the_gate() -> None:
    entry = CATALOG[KEY]
    for blank in ({"license": " "}, {"source_url": ""}):
        weakened = {KEY: entry.model_copy(update=blank)}  # model_copy skips validation
        assert not gate_catalog_metadata(make_frame(), weakened).passed


def test_surviving_sentinel_codes_fail() -> None:
    result = gate_sentinels_gone(make_frame(value=[10.0, -999.0]), (-999,))
    assert not result.passed and "value" in result.detail


def test_flags_must_be_known_and_ok_needs_a_value() -> None:
    assert not gate_flags_consistent(make_frame(coverage_flag=["ok", "mostly"])).passed
    assert not gate_flags_consistent(make_frame(value=[10.0, float("nan")])).passed
    ok = make_frame(value=[10.0, float("nan")], coverage_flag=["ok", "suppressed"])
    assert gate_flags_consistent(ok).passed


# --- time ---------------------------------------------------------------------


def test_missing_or_reversed_periods_fail() -> None:
    missing = make_frame(period_end=[pd.Timestamp("2022-12-31"), pd.NaT])
    assert not gate_periods(missing).passed
    reversed_ = make_frame(period_start=pd.to_datetime(["2023-01-01"] * 2))
    assert "before period_start" in gate_periods(reversed_).detail


def test_periods_and_vintages_are_never_silently_mixed() -> None:
    mixed_periods = make_frame(period_end=pd.to_datetime(["2022-12-31", "2023-12-31"]))
    assert "multiple periods" in gate_periods(mixed_periods).detail
    assert gate_periods(mixed_periods, allow_multiple_periods=True).passed
    mixed_vintages = make_frame(geo_vintage=[2010, 2020])
    assert "vintages mixed" in gate_periods(mixed_vintages).detail


# --- coverage -----------------------------------------------------------------

UNIVERSE = pd.DataFrame(
    {
        "geoid": ["55079000100", "55079000200", "55079000300", "55079000400", "01001020100"],
        "state_fips": ["55", "55", "55", "55", "01"],
    }
)


def test_coverage_counts_only_geographies_with_values() -> None:
    df = make_frame(("55079000100", "55079000200", "01001020100"), value=[1.0, float("nan"), 3.0])
    coverage = coverage_by_state(df, UNIVERSE)
    assert coverage[(KEY, "55")] == pytest.approx(1 / 4)  # one of four Wisconsin tracts
    assert coverage[(KEY, "01")] == pytest.approx(1.0)


def test_with_no_prior_release_the_coverage_gate_passes() -> None:
    assert gate_coverage_not_dropped({(KEY, "55"): 0.2}, None).passed
    assert gate_coverage_not_dropped({(KEY, "55"): 0.2}, {}).passed


def test_a_small_drop_or_an_improvement_passes() -> None:
    prior = {(KEY, "55"): 0.90, (KEY, "01"): 0.50}
    assert gate_coverage_not_dropped({(KEY, "55"): 0.82, (KEY, "01"): 0.95}, prior).passed


def test_a_sharp_drop_fails_and_names_the_state() -> None:
    result = gate_coverage_not_dropped({(KEY, "55"): 0.40}, {(KEY, "55"): 0.90})
    assert not result.passed
    assert "state 55" in result.detail and "90%" in result.detail and "40%" in result.detail


def test_a_state_that_vanished_counts_as_zero_coverage() -> None:
    assert not gate_coverage_not_dropped(
        {(KEY, "55"): 0.9}, {(KEY, "55"): 0.9, (KEY, "01"): 0.9}
    ).passed


def test_an_override_note_lets_a_drop_pass_and_is_visible() -> None:
    result = gate_coverage_not_dropped(
        {(KEY, "55"): 0.40}, {(KEY, "55"): 0.90}, override_note="source suppressed WI in 2023"
    )
    assert result.passed
    assert result.detail.startswith("overridden") and "source suppressed WI" in result.detail


def test_a_blank_override_note_does_not_count() -> None:
    assert not gate_coverage_not_dropped(
        {(KEY, "55"): 0.4}, {(KEY, "55"): 0.9}, override_note="  "
    ).passed


# --- enforce ------------------------------------------------------------------


def test_enforce_reports_every_failure_at_once() -> None:
    results = [
        GateResult("first", True),
        GateResult("second", False, "two things wrong"),
        GateResult("third", False, "another thing"),
    ]
    with pytest.raises(GateFailure) as raised:
        enforce(results)
    message = str(raised.value)
    assert "2 validation gate(s) failed" in message
    assert "second" in message and "third" in message and "first" not in message
    assert [f.name for f in raised.value.failures] == ["second", "third"]
