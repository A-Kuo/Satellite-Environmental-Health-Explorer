"""GEOID repair, sentinel handling and missing-value flags."""

from __future__ import annotations

import pandas as pd
import pytest

from src.connectors.fips import STATE_FIPS, is_known_state_fips
from src.connectors.normalize import flag_missing_values, normalize_geoid, replace_sentinels
from src.states import FIPS_TO_ABBR


@pytest.mark.parametrize(
    ("raw", "level", "expected"),
    [
        ("1001020100", "tract", "01001020100"),  # leading zero dropped by a spreadsheet
        ("1001", "county", "01001"),
        ("55079000100", "tract", "55079000100"),  # already correct
        ("1001.0", "county", "01001"),  # float artifact from a column with blanks
        ("55079000400.0", "tract", "55079000400"),
        (" 55 ", "state", "55"),  # stray whitespace
        ("5", "state", "05"),
        ("2706", "zcta", "02706"),
    ],
)
def test_geoids_are_zero_padded_strings(raw: str, level: str, expected: str) -> None:
    assert normalize_geoid(pd.Series([raw]), level).iloc[0] == expected


def test_integer_and_float_typed_columns_are_repaired() -> None:
    assert normalize_geoid(pd.Series([1001, 55079]), "county").tolist() == ["01001", "55079"]
    assert normalize_geoid(pd.Series([1001.0, 55079.0]), "county").tolist() == ["01001", "55079"]


def test_missing_geoids_stay_missing() -> None:
    result = normalize_geoid(pd.Series(["1001", None, pd.NA]), "county")
    assert result.iloc[0] == "01001"
    assert result.iloc[1:].isna().all()


def test_a_wrong_length_geoid_is_left_for_the_gate_to_reject() -> None:
    assert normalize_geoid(pd.Series(["550790001001"]), "tract").iloc[0] == "550790001001"


def test_unknown_level_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown geography level"):
        normalize_geoid(pd.Series(["1"]), "block_group")


def test_sentinels_become_nan_and_are_counted_per_column() -> None:
    df = pd.DataFrame({"value": [1.0, -999.0, 3.0, -999.0], "low": [0.5, -999.0, 2.5, 3.5]})
    cleaned, counts = replace_sentinels(df, ["value", "low"], (-999,))
    assert counts == {"value": 2, "low": 1}
    assert cleaned["value"].isna().tolist() == [False, True, False, True]
    assert cleaned["low"].isna().tolist() == [False, True, False, False]


def test_only_declared_sentinels_are_replaced_and_input_is_not_mutated() -> None:
    df = pd.DataFrame({"value": [-1.0, -999.0, -5.0]})
    cleaned, counts = replace_sentinels(df, ["value"], (-999,))
    assert cleaned["value"].tolist()[0] == -1.0  # a legitimate negative survives
    assert cleaned["value"].tolist()[2] == -5.0
    assert counts == {"value": 1}
    assert df["value"].tolist() == [-1.0, -999.0, -5.0]  # original untouched


def test_sentinel_replacement_requires_numbers() -> None:
    with pytest.raises(TypeError, match="must be numeric"):
        replace_sentinels(pd.DataFrame({"value": ["-999", "1"]}), ["value"], (-999,))


def test_a_missing_value_says_why() -> None:
    df = pd.DataFrame(
        {"value": [1.0, float("nan"), float("nan")], "coverage_flag": ["ok", "ok", "suppressed"]}
    )
    flagged = flag_missing_values(df)
    assert flagged["coverage_flag"].tolist() == ["ok", "no_data", "suppressed"]  # keeps a reason


def test_state_registry_covers_states_dc_and_territories() -> None:
    assert len(STATE_FIPS) == 56
    assert sum(1 for s in STATE_FIPS.values() if s.is_territory) == 5
    assert STATE_FIPS["11"].abbr == "DC"
    assert is_known_state_fips("72") and not is_known_state_fips("99")


def test_registry_agrees_with_the_frozen_baseline_states() -> None:
    """The baseline registers 7 states; the national registry must not disagree."""
    for fips, abbr in FIPS_TO_ABBR.items():
        assert STATE_FIPS[fips].abbr == abbr
