from src.validate import (
    check_crs,
    check_geoid_format,
    check_no_null_geometry,
    check_unique_geoid,
    check_wisconsin_fips_prefix,
)


def test_unique_geoid(tracts_gdf):
    check_unique_geoid(tracts_gdf)


def test_no_null_geometry(tracts_gdf):
    check_no_null_geometry(tracts_gdf)


def test_geoid_format(tracts_gdf):
    check_geoid_format(tracts_gdf)


def test_wisconsin_fips_prefix(tracts_gdf):
    check_wisconsin_fips_prefix(tracts_gdf)


def test_crs(tracts_gdf):
    check_crs(tracts_gdf)
