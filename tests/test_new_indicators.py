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
