# Data Dictionary — Stage One

Wisconsin Environmental Health Explorer. All tables are keyed by `geoid`, the
11-digit Census tract GEOID (state(2) + county(3) + tract(6)), zero-padded.

> This explorer is a descriptive screening tool. It does not estimate individual
> exposure, diagnose disease, establish causality, rank community worthiness, or
> replace environmental-health expertise and community input. Areas highlighted for
> review reflect the selected public indicators and analytic assumptions, not a
> definitive measure of risk or harm.

## `geographies` — `data/processed/wi_tracts_2022.parquet`

| Field | Type | Description |
|---|---|---|
| `geoid` | string | 11-digit Census tract GEOID |
| `geography_name` | string | e.g. "Census Tract 9400.02, Outagamie County, Wisconsin" |
| `geography_type` | string | always `"census_tract"` |
| `geometry` | geometry (Polygon) | CRS EPSG:4269 (NAD83) |
| `county_name` | string | e.g. "Outagamie County" |
| `county_fips` | string | 5-digit state(2)+county(3) |

- Source: Census Bureau TIGER/Line 2022, Wisconsin census tracts.
  `https://www2.census.gov/geo/tiger/TIGER2022/TRACT/tl_2022_55_tract.zip`
- County names: Census Bureau 2020 county FIPS reference,
  `https://www2.census.gov/geo/docs/reference/codes2020/cou/st55_wi_cou2020.txt`
- Rows: 1,542 Wisconsin census tracts. No missing values.

## `social_vulnerability` — `data/processed/wi_svi_2022.parquet`

| Field | Type | Description |
|---|---|---|
| `geoid` | string | 11-digit Census tract GEOID |
| `svi_year` | int | 2022 |
| `overall_svi_percentile` | float (0–1) | `RPL_THEMES`; NaN if source value was -999 |
| `socioeconomic_theme_percentile` | float (0–1) | `RPL_THEME1` |
| `household_characteristics_percentile` | float (0–1) | `RPL_THEME2` |
| `minority_language_percentile` | float (0–1) | `RPL_THEME3` |
| `housing_transport_percentile` | float (0–1) | `RPL_THEME4` |
| `source_url` | string | CDC/ATSDR SVI download URL |

- Source: CDC/ATSDR Social Vulnerability Index 2022, Wisconsin, census tract.
  `https://svi.cdc.gov/Documents/Data/2022/csv/states/Wisconsin.csv`
- Percentiles are **national-relative** as published by CDC/ATSDR (SVI does not
  publish a state-relative percentile); Stage One uses them as-is per `agent.md`'s
  schema. This differs from the environmental indicator's Wisconsin-relative
  percentile (see below) — a limitation documented in `methodology.md`.
- Missing-value convention: source sentinel `-999` is converted to `NaN`.
- Rows: 1,528 tracts (a small number of Wisconsin tracts — e.g. zero-population or
  water/parkland-only tracts — are not scored by SVI; ~1.2% missingness on the
  overall percentile in the final joined view).

## `environmental_indicator` — `data/processed/wi_pm25_2022.parquet`

| Field | Type | Description |
|---|---|---|
| `geoid` | string | 11-digit Census tract GEOID |
| `indicator_name` | string | `"PM2.5 Annual Concentration"` |
| `indicator_year` | int | 2022 |
| `indicator_value` | float | µg/m³, modeled annual average |
| `unit` | string | `"µg/m³"` |
| `data_coverage_flag` | string | `"modeled"` |
| `aggregation_method` | string | methodology + provenance note (see below) |
| `source_url` | string | Harvard Dataverse dataset landing page |

- Source: EPA EJScreen 2.3 tract-level PM2.5 (modeled annual-average surface).
  **EPA removed EJScreen from its own website in February 2025**, and no official
  EPA endpoint is available as of this writing. Sourced instead from the **Harvard
  Dataverse mirror** (`doi:10.7910/DVN/RLR5AX`, file
  `EJScreen_2024_Tract_StatePct_with_AS_CNMI_GU_VI.csv`), filtered to Wisconsin
  (`ID` prefix `"55"`). See `methodology.md` for the full limitation statement.
- This is a **modeled** estimate, not a ground-truth measurement for any specific
  tract — do not present it as directly measured concentration.
- Rows: 1,542 Wisconsin tracts. No missing values.

## `environmental_indicator` — `data/processed/wi_cropland_2022.parquet`

Same schema as `wi_pm25_2022.parquet` above. Two stacked indicators (3,084
rows total, 1,542 tracts × 2):

- `"Row-Crop Cultivation Share (Corn & Soybean)"` — fraction of tract area
  (0–1) classified corn, soybean, or a double-crop combination involving
  either, from the USDA NASS Cropland Data Layer (CDL) 2022, 30m resolution.
  A fertilizer/pesticide-loading proxy.
- `"Pastureland Share (Dairy-Associated)"` — fraction of tract area (0–1)
  classified grass/pasture, other hay, or alfalfa, from CDL 2022. A
  manure/nutrient-runoff loading proxy, specific to Wisconsin's dairy
  industry.

Source: `https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php`,
pulled via Google Earth Engine (`USDA/NASS/CDL`). Both are **high is
concern** indicators (more row-crop/pasture intensity = more loading
pressure) — see `concern_percentile_wi` on the screening view below.

## `environmental_indicator` — `data/processed/wi_wetlands_2022.parquet`

Same schema as `wi_pm25_2022.parquet` above. One indicator,
`"Wetland & Surface Water Extent"` — fraction of tract area (0–1) classified
water or flooded vegetation by Google Dynamic World V1, composited over the
2022 growing season (June–September, per-pixel mode), 10m resolution.

Source: `https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1`.
**This is a `low is concern` indicator** — wetlands are a protective buffer,
so a *low* value (little wetland/surface-water extent) is the direction
worth screening for, the opposite of every other indicator in this pipeline.
See `LOW_IS_CONCERN_INDICATORS` in `src/spatial_join.py` and
`concern_percentile_wi` below.

## `monitor_or_facility_points` — `data/processed/wi_dnr_points.parquet`

| Field | Type | Description |
|---|---|---|
| `point_id` | string | WI DNR `OBJECTID` |
| `name` | string | Monitoring site name |
| `point_type` | string | always `"air_monitor"` for Stage One |
| `latitude` | float | WGS84 (EPSG:4326) |
| `longitude` | float | WGS84 (EPSG:4326) |
| `pollutant_or_permit_type` | string | comma-separated list of pollutants actively monitored at the site (e.g. "O3, PM2.5") |
| `reporting_year` | int | year this snapshot of the live layer was pulled — **not** a specific reporting/compliance year for the site (see note below) |
| `source_url` | string | WI DNR ArcGIS REST service URL |

- Source: WI DNR Air Management Data Viewer, "All Monitors" layer.
  `https://dnrmaps.wi.gov/arcgis/rest/services/AM_WARP_MAP/AM_MONITORS_WTM_Int/MapServer/0`
- This is a **live, current-state** layer (active monitoring sites at time of
  download), not a historical annual dataset — `reporting_year` records only the
  snapshot date, and should not be read as "monitoring occurred in year X."
- Contextual point layer only. Do not imply that nearby tracts have measured
  concentrations equal to a monitor's readings.
- Rows: 40 active monitoring sites statewide.

## Derived Screening View — `data/processed/tract_screening_view.parquet`

| Field | Type | Description |
|---|---|---|
| `geoid` | string | 11-digit Census tract GEOID |
| `geography_name` | string | from `geographies` |
| `county_name` | string | from `geographies` |
| `selected_indicator` | string | one of `"PM2.5 Annual Concentration"`, `"Row-Crop Cultivation Share (Corn & Soybean)"`, `"Pastureland Share (Dairy-Associated)"`, `"Wetland & Surface Water Extent"` — the view is **long format**, one row per (tract, indicator) |
| `indicator_value` | float | from `environmental_indicator`, in that indicator's own unit |
| `indicator_percentile_wi` | float (0–1) | **Wisconsin-relative** percentile rank of `indicator_value`, computed via `pandas.rank(pct=True)` **within each indicator's own distribution** (`groupby("indicator_name")`), not across mixed indicators |
| `concern_percentile_wi` | float (0–1) | `indicator_percentile_wi`, direction-normalized so a **high value always means "more concerning"** — equal to `indicator_percentile_wi` for most indicators, or `1 - indicator_percentile_wi` for indicators in `LOW_IS_CONCERN_INDICATORS` (currently only wetland/surface-water extent). `screening_flag` and the app's map/scatter coloring use this column, never the raw `indicator_percentile_wi` |
| `overall_svi_percentile` | float (0–1) | from `social_vulnerability`, national-relative as published |
| `data_coverage_flag` | string | from `environmental_indicator` |
| `screening_flag` | bool | `True` only if both `concern_percentile_wi` and `overall_svi_percentile` are ≥ 0.75 |
| `screening_rationale` | string | plain-language explanation of the flag, always framed as "for analyst review," never as a risk/harm determination |
| `last_updated` | string | ISO date the view was built |
| `geometry` | geometry (Polygon) | from `geographies`, EPSG:4269 |

No column in this table (or any other) is named `risk_score`, `priority_score`, or
`harm_score` — enforced by `tests/test_validation.py::test_no_risk_score_column`.

- Rows: 1,542 tracts × 4 indicators = 6,168 (long format, one row per
  tract-indicator pair). The originally-documented 89-tract PM2.5 flag count
  (~5.8% of tracts, under the ≥75th-percentile-on-both-axes rule) still holds
  for the PM2.5 subset; other indicators flag independently within their own
  distribution.

## `data/metadata/ingest_log.csv`

One row per raw file downloaded by `src/ingest.py` and `src/ingest_ground_truth.py`:
`filename`, `source_url`, `description`, `downloaded_at_utc`, `sha256`.

---

# Satellite Calibration Model tables

See `methodology.md`'s "Satellite Calibration Model" section for the full method,
why the split is temporal rather than spatial, and the resolution/coverage caveats.
These tables are keyed by AQS `site_id` + `date`, **not** by tract `geoid` — they
never touch SVI and do not feed the Stage One screening view.

## `ground_truth_<pollutant>` — `data/processed/ground_truth_{no2,so2,co,pm25}.parquet`

| Field | Type | Description |
|---|---|---|
| `site_id` | string | AQS site id: state(2)+county(3)+site(4) |
| `date` | date | calendar day, 2022 |
| `pollutant` | string | `"NO2"` / `"SO2"` / `"CO"` / `"PM2.5"` |
| `latitude`, `longitude` | float | monitor location, WGS84 |
| `concentration` | float | daily arithmetic mean, averaged across POC/instrument if more than one at a site |
| `unit` | string | as published by AQS (ppb, ppm, or µg/m³ depending on pollutant) |

- Source: EPA AQS pre-generated daily files, `https://aqs.epa.gov/aqsweb/airdata/daily_<param>_2022.zip`, no authentication required.
- WI monitor counts (2022): NO2 = 3, SO2 = 7, CO = 3, PM2.5 = 20.

## `satellite_<pollutant>` — `data/processed/satellite_{no2,so2,co,pm25}.parquet`

| Field | Type | Description |
|---|---|---|
| `site_id` | string | matches `ground_truth_<pollutant>.site_id` |
| `date` | date | calendar day, 2022 |
| `satellite_value` | float | mean pixel value in a 1 km buffer around the site (band units vary by product; PM2.5's is a Terra/Aqua MODIS AOD mean) |
| `satellite_band` | string | source band name |
| `retrieval_valid` | bool | `False` on days with no cloud-free satellite retrieval (kept as explicit rows, not dropped, so coverage is auditable) |

- Source: Google Earth Engine (`COPERNICUS/S5P/OFFL/L3_NO2`/`L3_SO2`/`L3_CO`;
  `MODIS/061/MOD08_D3` + `MYD08_D3`), via a project service-account credential.

## `calibration_dataset_<pollutant>` — `data/processed/calibration_dataset_{no2,so2,co,pm25}.parquet`

Inner join of the two tables above, restricted to `retrieval_valid == True`:
`site_id`, `date`, `pollutant`, `latitude`, `longitude`, `concentration`, `unit`,
`satellite_value`, `satellite_band`. One row per site-day usable for modeling.

## `data/processed/satellite_coverage_report.csv`

| Field | Type | Description |
|---|---|---|
| `pollutant` | string | |
| `n_ground_truth_site_days` | int | total AQS site-days available |
| `n_valid_satellite_retrievals` | int | how many of those had a usable satellite value |
| `coverage_pct` | float (0–100) | the honest denominator behind the model's training data |

## `data/processed/calibration_model_metrics.csv`

One row per pollutant × model (`linear_regression`, `random_forest`):
`pollutant`, `model`, `n_train`, `n_test`, `train_start`, `train_end`,
`test_start`, `test_end`, `r2`, `rmse`, `mae`. `train_end` is always before
`test_start` (enforced by `tests/test_calibration.py`) — the split is temporal,
Jan 1–Sep 30, 2022 train vs. Oct 1–Dec 31, 2022 test.

## `data/processed/calibration_plots/<pollutant>_predicted_vs_actual.png`

Scatter of test-set ground-truth concentration vs. the better-performing
model's prediction, with a 1:1 reference line, for each pollutant.

No column in any calibration table is named `risk_score`, `priority_score`, or
`harm_score` — enforced by `tests/test_calibration.py::test_no_forbidden_column_names`.

---

# LUR Pilot tables

See `methodology.md`'s "LUR Pilot: Madison PM2.5, Milwaukee NO2" section for the
full method, the city/pollutant rationale (including the Madison-has-no-NO2-
monitor finding), and the results. Two pilots: `madison`/`pm25` and
`milwaukee`/`no2`. Distance-to-major-road data is **© OpenStreetMap
contributors** (ODbL) — credit required wherever it's shown.

## `lur_static_<city>` — `data/processed/lur_static_{madison,milwaukee}.parquet`

| Field | Type | Description |
|---|---|---|
| `site_id` | string | matches the pilot's `ground_truth_<pollutant>.site_id` |
| `impervious_pct` | float | NLCD 2021 impervious surface %, 500 m buffer mean |
| `elevation_m` | float | USGS 3DEP 10 m elevation, 500 m buffer mean |
| `dist_to_major_road_km` | float | distance to nearest OSM motorway/trunk/primary way |

Derived from `data/raw/osm_major_roads_<city>.json` — the raw Overpass API
response for that city's bounding box, fetched once and cached (logged in
`ingest_log.csv` like every other raw source) rather than re-queried on every
run. **© OpenStreetMap contributors, ODbL** — this attribution is required
wherever `dist_to_major_road_km` or any map built from this cache is shown.

## `lur_dynamic_<city>` — `data/processed/lur_dynamic_{madison,milwaukee}.parquet`

| Field | Type | Description |
|---|---|---|
| `site_id`, `date` | string, date | |
| `temperature_2m`, `dewpoint_temperature_2m` | float (K) | ERA5-Land, daily mean |
| `u_component_of_wind_10m`, `v_component_of_wind_10m` | float (m/s) | ERA5-Land, daily mean |
| `total_precipitation` | float (m) | ERA5-Land, daily **sum** (not mean — an accumulated field) |
| `boundary_layer_height` | float (m) | ERA5 (not ERA5-Land), daily mean |

## `lur_cross_satellite_<city>` — `data/processed/lur_cross_satellite_{madison,milwaukee}.parquet`

The *other* pollutant's satellite proxy, evaluated fresh at this pilot's own
sites (e.g. TROPOMI NO2 at Madison's PM2.5 monitors): `site_id`, `date`,
`cross_satellite_<pollutant>`, `cross_satellite_<pollutant>_valid`.

## `lur_dataset_<city>_<pollutant>` — `data/processed/lur_dataset_{madison_pm25,milwaukee_no2}.parquet`

One row per monitor site-day: ground truth (`concentration`), the pilot's own
`satellite_<pollutant>`, `cross_satellite_<other>`, all `lur_dynamic_<city>`
and `lur_static_<city>` fields joined in, plus derived features
`relative_humidity_pct`, `wind_speed_ms`, `wind_direction_deg`, `doy_sin`,
`doy_cos`, `is_weekend`, `is_heating_season`.

## `data/processed/lur_model_metrics.csv`

One row per pilot × method (5 baselines + 2 models — `baseline_global_mean`,
`baseline_season_mean`, `baseline_site_mean`, `baseline_persistence`,
`model_random_forest`, `model_hist_gradient_boosting`): `city`, `pollutant`,
`method`, `r2`, `rmse`, `mae`, `n_train`, `n_test`, `train_start`, `train_end`,
`test_start`, `test_end`. Both baseline and model rows are always present
(`tests/test_lur.py::test_baselines_and_models_both_present`) so a model's R²
is never read without the baselines it has to beat.

## `data/processed/lur_plots/<city>_<pollutant>_predicted_vs_actual.png`

Test-set ground truth vs. the better-performing model's prediction, with a
1:1 reference line, per pilot.

No column in any LUR table is named `risk_score`, `priority_score`, or
`harm_score` — enforced by `tests/test_lur.py::test_no_forbidden_column_names`.

---

# LUR Validation & Diagnostics tables

See `methodology.md`'s "Validation & Diagnostics" subsection for the full
results and the promotion-decision verdict. All read the already-built
`lur_dataset_<city>_<pollutant>.parquet` tables — no new ingestion.

## `data/processed/lur_rolling_cv.csv`

Rolling-origin temporal validation: one row per pilot × fold (8 folds, May
through Dec 2022 as the test month, expanding training window) × method
(`baseline_global_mean`, `baseline_persistence`, `model_random_forest`,
`model_hist_gradient_boosting` — computed fresh per fold from that fold's own
training data, not the full-year baselines in `lur_model_metrics.csv`):
`city`, `pollutant`, `method`, `r2`, `rmse`, `mae`, `train_end`,
`test_month_start`, `test_month_end`, `n_train`, `n_test`.

## `data/processed/lur_site_holdout.csv`

Leave-one-monitor-site-out validation: one row per pilot × held-out site ×
method (`baseline_global_mean`, `baseline_season_mean`,
`model_random_forest`, `model_hist_gradient_boosting` — persistence and
site-mean baselines are undefined here since the held-out site has zero
training history): `city`, `pollutant`, `held_out_site`, `method`, `r2`,
`rmse`, `mae`, `n_train`, `n_test`.

## `data/processed/lur_ablation.csv`

Feature-family ablation (HGB only): one row per pilot × `ablated_family`
(`"none (full model)"`, `satellite`, `meteorology`, `land_use`, `time`):
`city`, `pollutant`, `ablated_family`, `r2`, `rmse`, `mae`, `n_features`,
`r2_drop_from_full` (full-model R² minus this row's R² — null for the
full-model row itself).

## `data/processed/lur_feature_importance.csv`

Permutation importance (30 repeats, scored on the held-out Oct–Dec test set):
`city`, `pollutant`, `feature`, `perm_importance_mean`, `perm_importance_std`.
Paired with `data/processed/lur_plots/<city>_<pollutant>_shap_summary.png`
(SHAP beeswarm) for a directional read (which way each feature pushes the
prediction), not just magnitude.

## `data/processed/lur_residual_summary.csv`

Observed-minus-predicted residuals on the standard Oct–Dec test set,
aggregated two ways: `group_type` = `"site"` (per monitor site) or
`"season"` (fall/winter, the only two seasons the test window spans):
`city`, `pollutant`, `group_type`, `group`, `mean`, `std`, `count`. Paired
with `data/processed/lur_plots/<city>_<pollutant>_residual_diagnostics.png`
(residual vs. predicted, vs. observed, by site, by season).

No column in any validation table is named `risk_score`, `priority_score`, or
`harm_score` — enforced by `tests/test_lur_validation.py::test_no_forbidden_column_names`.

---

# Milwaukee/Madison Diagnosis tables

See `methodology.md`'s "Milwaukee Diagnosis" and "Madison Diagnosis" subsections for the
full findings and the go/no-go call each led to.

## `lur_multiscale_features_<city>` — `data/processed/lur_multiscale_features_{madison,milwaukee}.parquet`

Per site: `impervious_pct_{100,300,500,1000}m` (NLCD, mean at each buffer radius),
`landcover_pct_{developed,forest,agriculture,water,other}` (NLCD class-group share, 500 m
buffer), `road_density_{100,300,500,1000}m` (km of OSM motorway/trunk/primary way per km²,
from the cached `data/raw/osm_major_roads_<city>.json` — no new Overpass calls).

## `data/processed/lur_site_feature_distributions_<city>.csv`

Per-site static feature values (`impervious_pct`, `elevation_m`, `dist_to_major_road_km`,
plus the multiscale/land-cover-mix columns above where available): `site_id`, one row per
site, `city`, `pollutant`. Paired with
`lur_plots/<city>_<pollutant>_shap_dependence_by_site.png` (SHAP value for
`impervious_pct` vs. its value, colored by site — the step-like-clustering diagnostic) and
`lur_plots/<city>_<pollutant>_pdp.png` (partial dependence for `impervious_pct` and a top
weather feature).

## `data/processed/lur_rolling_cv_variants.csv` / `lur_site_holdout_variants.csv`

Same shape as `lur_rolling_cv.csv` / `lur_site_holdout.csv` plus a `variant` column:
`baseline_full` (unchanged features), `no_impervious` (`impervious_pct` dropped),
`multiscale_land_use` (`impervious_pct` replaced by the multi-scale features above).

## `data/processed/lur_mixed_effects.csv`

One row per pilot: `city`, `pollutant`, `n_obs`, `n_groups` (monitor sites), `group_variance`,
`residual_variance`, `icc_between_site_share` (0–1: the fraction of total outcome variance
attributable to site identity rather than shared weather/land-use predictors — diagnostic
only, not a model fit for prediction at unmonitored sites), plus `coef_<feature>` fixed-effect
coefficients (unstandardized — not comparable across features with different scales).

## `data/processed/lur_fold_diagnostics_madison_pm25.csv`

One row per rolling-CV test month: `test_month_start`, `r2`, `n_test`,
`mean_concentration`, `mean_<weather column>` for each of temperature, humidity, wind,
precipitation, and boundary-layer height — lets a failing fold's weather regime be read
off directly.

## `data/processed/lur_aqs_quality_flags_madison_pm25.csv`

Re-parsed columns from the already-cached raw AQS PM2.5 daily file (`Method Name`,
`Observation Percent`, `Event Type`, `POC`) that the original `clean_pollutant()` cleaning
step in `src/ingest_ground_truth.py` drops: `site_id`, `date`, `Method Name`,
`Observation Percent`, `Event Type`. Used to rule out (not confirm — see methodology.md)
instrument changes and exceptional-event days as explanations for Madison's summer folds.

## `data/processed/lur_persistence_comparison.csv`

Compares single-previous-day persistence against a causal 7-day trailing per-site mean
("season-aware" persistence), on the standard split (`window="standard_split"`) and each
rolling fold (`window="fold_test_<date>"`): `city`, `pollutant`, `method`
(`baseline_persistence_1day` / `baseline_persistence_7day_trailing`), `r2`, `rmse`, `mae`,
`window`.

## `data/processed/lur_quantile_coverage.csv`

Empirical coverage of a `HistGradientBoostingRegressor(loss="quantile")` 10th/90th-percentile
interval (nominal 80%) on the standard test set, overall and by season: `city`, `pollutant`,
`nominal_coverage`, `overall_empirical_coverage`, `coverage_<season>`.

No column in any diagnosis table is named `risk_score`, `priority_score`, or `harm_score` —
enforced by `tests/test_lur_diagnosis.py::test_no_forbidden_column_names`.

---

# Pre-registered Madison experiment tables

See `methodology.md`'s "Pre-registered Madison PM2.5 experiment" subsection — hypotheses,
features, and success criteria written and committed **before** this was run.

## `lur_madison_solar_radiation.parquet` / `lur_madison_aerosol_index.parquet`

Raw feature pulls (`site_id`, `date`, `surface_solar_radiation_downwards` /
`absorbing_aerosol_index`) at Madison's 2 PM2.5 sites, from collections already queried
elsewhere in this project (ERA5-Land, and the same `COPERNICUS/S5P/OFFL/L3_NO2` collection
used for the cross-satellite NO2 predictor) — no new external data source.

## `lur_madison_experiment_rolling_cv.csv` / `lur_madison_experiment_site_holdout.csv`

Same shape as `lur_rolling_cv.csv` / `lur_site_holdout.csv`, Madison/PM2.5 only, with the
two new features added via `prepare_features`'s `extra_features` parameter — no other
change to the validation methodology.

## `data/processed/lur_madison_experiment_results.csv`

One row: `city`, `pollutant`, `features_added`, `rolling_median_r2_before/after`,
`pct_folds_beating_baseline_before/after`, `site_holdout_median_r2_before/after`,
`promoted` (bool — whether the pre-specified criteria were met). Result: `promoted=False`;
see methodology.md for the full writeup.

## `data/processed/lur_plots/ablation_satellite_contribution.png` / `quantile_coverage_nominal_vs_empirical.png`

Two negative-results summary charts built from already-computed CSVs (`lur_ablation.csv`,
`lur_quantile_coverage.csv`) — no re-modeling: a bar chart of each feature family's test-set
R² contribution per pilot, and a nominal-vs-empirical prediction-interval coverage chart.
