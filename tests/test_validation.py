from src.validate import (
    check_indicator_year_present,
    check_no_negative_pm25,
    check_no_risk_score_column,
    check_screening_flag_logic,
    check_valid_svi_range,
)


def test_valid_svi_range(svi_df):
    check_valid_svi_range(svi_df)


def test_indicator_year_present(indicator_df):
    check_indicator_year_present(indicator_df)


def test_no_negative_pm25(indicator_df):
    check_no_negative_pm25(indicator_df)


def test_screening_flag_logic(screening_df):
    check_screening_flag_logic(screening_df)


def test_no_risk_score_column(screening_df):
    check_no_risk_score_column(screening_df)
