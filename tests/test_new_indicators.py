from src.validate import (
    check_fraction_range,
    check_indicator_year_present,
    check_no_risk_score_column,
)


def test_cropland_fraction_range(cropland_df):
    check_fraction_range(cropland_df)


def test_cropland_indicator_year_present(cropland_df):
    check_indicator_year_present(cropland_df)


def test_cropland_two_indicators_present(cropland_df):
    assert set(cropland_df["indicator_name"].unique()) == {
        "Row-Crop Cultivation Share (Corn & Soybean)",
        "Pastureland Share (Dairy-Associated)",
    }


def test_wetlands_fraction_range(wetlands_df):
    check_fraction_range(wetlands_df)


def test_wetlands_indicator_year_present(wetlands_df):
    check_indicator_year_present(wetlands_df)


def test_no_risk_score_column_cropland(cropland_df):
    check_no_risk_score_column(cropland_df)


def test_no_risk_score_column_wetlands(wetlands_df):
    check_no_risk_score_column(wetlands_df)


def test_screening_view_has_multiple_indicators(screening_df):
    """Regression guard: confirms the long-format expansion in
    build_screening_view actually happened, not just that it doesn't crash."""
    assert screening_df["selected_indicator"].nunique() > 1


def test_screening_view_has_concern_percentile(screening_df):
    assert "concern_percentile_wi" in screening_df.columns
    valid = screening_df["concern_percentile_wi"].dropna()
    assert valid.between(0, 1).all()


def test_screening_view_has_multiple_states(screening_df):
    """Regression guard: confirms the multi-state combine step in
    src/spatial_join.py::combine_screening_view actually onboarded more than
    just Wisconsin."""
    assert "state_abbr" in screening_df.columns
    assert screening_df["state_abbr"].nunique() > 1


def test_percentiles_are_state_relative(screening_df):
    """Each state's indicator_percentile_wi must span its own [0, 1] range --
    percentiles are never pooled across states (src/spatial_join.py's
    groupby(["state_abbr", "indicator_name"])."""
    for (state, indicator), group in screening_df.groupby(["state_abbr", "selected_indicator"]):
        valid = group["indicator_percentile_wi"].dropna()
        if len(valid):
            assert valid.max() > 0.9, f"{state}/{indicator}: percentile doesn't reach near 1.0"
