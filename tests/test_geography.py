from src.validate import (
    check_crs,
    check_geoid_format,
    check_geoid_state_prefix,
    check_no_null_geometry,
    check_unique_geoid,
)


def test_unique_geoid(tracts_gdf):
    check_unique_geoid(tracts_gdf)


def test_no_null_geometry(tracts_gdf):
    check_no_null_geometry(tracts_gdf)


def test_geoid_format(tracts_gdf):
    check_geoid_format(tracts_gdf)


def test_geoid_state_prefix(tracts_gdf):
    check_geoid_state_prefix(tracts_gdf)


def test_crs(tracts_gdf):
    check_crs(tracts_gdf)
