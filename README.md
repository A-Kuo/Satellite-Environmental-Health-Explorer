# Wisconsin Environmental Health Explorer

An interactive GIS screening tool combining publicly reported environmental
indicators with CDC/ATSDR Social Vulnerability Index (SVI) context, at the
Wisconsin census-tract level, to help analysts identify tracts that may merit
further review, community engagement, or policy attention.

> This explorer is a descriptive screening tool. It does not estimate individual
> exposure, diagnose disease, establish causality, rank community worthiness, or
> replace environmental-health expertise and community input. Areas highlighted for
> review reflect the selected public indicators and analytic assumptions, not a
> definitive measure of risk or harm.

Ships as an interactive Streamlit app (`app/streamlit_app.py`) backed by a
reproducible data-acquisition, cleaning, and validation pipeline (`src/`). See
`methodology.md` for data sources, years, units, and known limitations.

## Model status

Experimental models are not used as public screening layers.

- Madison PM2.5: spatial transfer was positive across nearby monitors, but rolling
  temporal performance was unstable and beat baseline models in only 3 of 8 folds.
- Milwaukee NO2: temporal performance was stable, but leave-one-monitor-site-out
  performance was negative at all sites, indicating inadequate spatial transfer.
- Satellite predictors tested in these pilots did not materially improve validation
  performance beyond meteorological and land-use features.

These models are retained as documented research baselines, not deployed exposure
estimates or health-risk measures.

Milwaukee's site-transfer failure has since been diagnosed as structural (3 monitors,
67% of NO2 variance is between-site) rather than a fixable feature bug; Madison's
instability is diagnosed as a summer-regime gap. A pre-registered follow-up test of
two candidate fixes (secondary-aerosol and wildfire-smoke proxies) for Madison came
back negative, closing that modeling workstream. See `methodology.md`'s "Milwaukee
Diagnosis," "Madison Diagnosis," and "Pre-registered Madison PM2.5 experiment"
subsections for the full investigation.

**RQ1 conclusion:** with the available 2022 monitor, meteorological, land-use, and
tested satellite data, the pilot models do not meet this project's criteria for
location-general environmental exposure prediction. This is a substantive negative
finding, not an unfinished result — see `methodology.md` for the full validation
matrix and the explicit list of what this project does *not* show.

### MVP scope

The visible screening tool stands on Stage One alone — the LUR pilots are a
documented research appendix, not a second product layer:

```
Validated tract-level public indicator
        +
CDC/ATSDR SVI contextual percentile
        +
Wisconsin DNR monitor/facility context
        +
Source, year, coverage, and limitations metadata
        =
Descriptive GIS screening tool for analyst review
```

## Setup

Requires Python 3.12 (geopandas/pyogrio wheels are not yet reliable on newer
interpreters).

```bash
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Running the Stage One pipeline

```bash
.venv\Scripts\python src\ingest.py
.venv\Scripts\python src\clean_svi.py
.venv\Scripts\python src\clean_indicator.py
.venv\Scripts\python -m src.ingest_cropland
.venv\Scripts\python -m src.ingest_wetlands
.venv\Scripts\python -m src.spatial_join
.venv\Scripts\python src\metrics.py
.venv\Scripts\python src\map_layers.py
```

`ingest_cropland.py` and `ingest_wetlands.py` require the GEE service-account
key (`.env/*.json`, see below) and pull tract-level agricultural-pressure and
wetland-extent indicators via `src/gee_polygon_utils.py`. `spatial_join.py`
reads every indicator file present in `data/processed/` and concatenates them
into one long-format screening view — run as `-m src.spatial_join` (not
`python src\spatial_join.py`) since it now imports from `src.validate`.

Outputs land in `data/processed/`: geometry/SVI/indicator Parquet/GeoParquet
tables (now three indicator files: PM2.5, cropland, wetlands), a summary
statistics CSV, and two static PNGs (choropleth + scatterplot).

## Running the interactive app

```bash
.venv\Scripts\streamlit run app\streamlit_app.py
```

Opens the screening map, scatter, review table, and methods drawer under a
"Screening" tab, with the non-promoted modeling research (below) under a
separate "Research Appendix" tab in the same header tab bar.

## Running the satellite calibration model

Validates satellite-observed pollutant proxies against EPA ground monitors via
a temporal train/test split — a data-quality check, not a health/risk model.
See `methodology.md`'s "Satellite Calibration Model" section before running.

```bash
.venv\Scripts\python src\ingest_ground_truth.py
.venv\Scripts\python src\ingest_satellite.py
.venv\Scripts\python src\build_calibration_dataset.py
.venv\Scripts\python src\calibration_model.py
```

`src/ingest_satellite.py` requires a Google Earth Engine service-account key at
`.env/*.json` (gitignored) for a GEE-enabled GCP project. Outputs land in
`data/processed/`: per-pollutant ground-truth/satellite/calibration tables, a
`satellite_coverage_report.csv`, `calibration_model_metrics.csv`, and
`calibration_plots/*.png`.

## Running the LUR pilots (Madison PM2.5, Milwaukee NO2)

Follow-up to the calibration model's negative result: a full Land Use
Regression predictor stack (weather, land use, roads, seasonality), evaluated
against multiple baselines, not just a training mean. See `methodology.md`'s
"LUR Pilot" section before running.

```bash
.venv\Scripts\python -m src.ingest_lur_features
.venv\Scripts\python -m src.build_lur_dataset
.venv\Scripts\python -m src.lur_model
```

Run as `-m src.<module>` (not `python src\<module>.py`) — these modules import
from `src.ingest_satellite`, which needs the repo root on `sys.path`. Also
requires the GEE service-account key in `.env/*.json`. Outputs:
`lur_static_<city>.parquet`, `lur_dynamic_<city>.parquet`,
`lur_cross_satellite_<city>.parquet`, `lur_dataset_<city>_<pollutant>.parquet`,
`lur_model_metrics.csv`, and `lur_plots/*.png`.

## Running the LUR validation & diagnostics suite

Before trusting either LUR pilot, both go through rolling-origin temporal
CV, leave-one-site-out spatial validation, feature-family ablation,
permutation/SHAP importance, and residual diagnostics — no new data
ingestion, just re-analysis of `lur_dataset_<city>_<pollutant>.parquet`. See
`methodology.md`'s "Validation & Diagnostics" subsection for the results and
promotion verdict (spoiler: neither pilot is promoted yet, for opposite
reasons — read why before using either).

```bash
.venv\Scripts\python -m src.lur_rolling_cv
.venv\Scripts\python -m src.lur_site_holdout
.venv\Scripts\python -m src.lur_ablation
.venv\Scripts\python -m src.lur_feature_importance
.venv\Scripts\python -m src.lur_residuals
```

## Running the Milwaukee/Madison diagnosis

Follow-up to the validation suite above: diagnoses *why* Milwaukee fails
site-holdout and *why* Madison is temporally unstable, rather than just
retraining. See `methodology.md`'s "Milwaukee Diagnosis" and "Madison
Diagnosis" subsections for the findings and the resulting go/no-go call.

```bash
.venv\Scripts\python -m src.lur_multiscale_features
.venv\Scripts\python -m src.lur_site_feature_diagnostics
.venv\Scripts\python -m src.lur_impervious_ablation
.venv\Scripts\python -m src.lur_mixed_effects
.venv\Scripts\python -m src.lur_fold_diagnostics
.venv\Scripts\python -m src.lur_quantile_model
```

## Running the pre-registered Madison experiment

A single, bounded test of two named hypotheses for Madison's rolling-fold
instability (secondary-aerosol and wildfire-smoke proxies, both reusing
already-queried Earth Engine collections) — pre-registered in
`methodology.md` before it was run. Result: negative; see
`methodology.md`'s "Pre-registered Madison PM2.5 experiment" subsection.
This closes the Madison modeling workstream — no further open-ended feature
additions without new data.

```bash
.venv\Scripts\python -m src.lur_madison_experiment
.venv\Scripts\python -m src.lur_summary_plots
```

`lur_multiscale_features.py` requires the GEE service-account key (`.env/*.json`);
the rest are pure re-analysis of already-cached data.

## Validating

```bash
.venv\Scripts\python -m pytest tests/
.venv\Scripts\python src\validate.py
```

Calibration-model and LUR tests (`tests/test_calibration.py`,
`tests/test_lur.py`, `tests/test_lur_validation.py`) skip gracefully until
their respective pipelines above have been run.

## Repository structure

```
data/raw/          original downloads, never modified (gitignored; regenerate via src/ingest*.py)
data/processed/    cleaned Parquet/GeoParquet tables, summary stats, static plots, calibration outputs
data/metadata/     data dictionary + ingest log (provenance/checksums)
notebooks/         end-to-end exploration and validation notebook
src/               pipeline modules (ingest, clean, join, validate, metrics, maps, satellite calibration)
app/               Streamlit app (streamlit_app.py entry, components/ for map/table/scatter/legend/appendix)
tests/             pytest validation suite
.env/              GEE service-account key (gitignored, not committed)
```

## Multi-state roadmap

Wisconsin is currently hardcoded end-to-end. `app/config.py` and
`src/validate.py`'s `STATE_FIPS`/`STATE_NAME`/`STATE_ABBR` constants are a
first, deliberately minimal step (naming, not function) — the sidebar's
"State" selector is a disabled placeholder, not a working switch. What a
second state would actually need, not yet built:

- `src/ingest.py`'s per-source download URLs and output filenames are
  Wisconsin-specific literals, not a template (each source's URL scheme
  differs enough — state name in path vs. FIPS in filename — that a generic
  substitution would be guesswork before a second state is actually being
  onboarded).
- `src/validate.py::check_wisconsin_fips_prefix` (and its enforced test,
  `tests/test_geography.py::test_wisconsin_fips_prefix`) hard-fails on any
  non-WI GEOID — correct for a single-state pipeline, but would need to
  become state-parameterized.
- The LUR pipeline's metric buffering uses `EPSG:3070` (Wisconsin Transverse
  Mercator) — accurate only within/near Wisconsin; a second state needs its
  own suitable projected CRS.
- `indicator_percentile_wi`/`concern_percentile_wi` are computed relative to
  Wisconsin's own tracts. Multi-state needs an explicit decision: state-
  relative per state, or one national-relative percentile across all states.
- No city/place (Census Places) geometry is ingested anywhere — county is
  currently the finest sub-tract administrative unit available.

## Project summary

Built a reproducible Wisconsin environmental-health GIS pipeline integrating
public air-quality, meteorological, land-use, road-network, satellite, and
CDC/ATSDR SVI context. Implemented rolling-origin temporal and
leave-one-monitor-site-out validation, feature ablation, SHAP diagnostics,
residual analysis, and prediction-interval coverage tests. Documented
non-promotion decisions when apparent single-split gains failed temporal or
spatial generalization, preserving the application as a transparent
descriptive screening tool rather than overstating model-derived exposure
estimates.
