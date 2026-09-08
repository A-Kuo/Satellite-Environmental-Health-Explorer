from src.validate import (
    check_crs_match,
    check_join_coverage,
    check_no_unexplained_missing_geometry,
)


def test_crs_match(tracts_gdf, exposure_gdf):
    check_crs_match(tracts_gdf, exposure_gdf)


def test_join_coverage(screening_df, tracts_gdf):
    check_join_coverage(screening_df, tracts_gdf)


def test_no_unexplained_missing_geometry(screening_df):
    check_no_unexplained_missing_geometry(screening_df)
