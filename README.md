# Regional Environmental Health Explorer

An interactive GIS screening tool combining publicly reported environmental
indicators with CDC/ATSDR Social Vulnerability Index (SVI) context, at the
census-tract level, to help analysts identify tracts that may merit further
review, community engagement, or policy attention. Built and validated on
Wisconsin first; now piloting Minnesota as the first additional state (see
"Multi-state rollout" below) using the same indicators and the same
state-relative screening methodology.

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
location-general environmental exposure prediction.

Here's a screenshot of the demo showing pastureland composition in Wisconsin.
<img width="1143" height="514" alt="image" src="https://github.com/user-attachments/assets/2ee109e5-fd79-449b-b50f-65efc8631062" />


### MVP scope

The visible screening tool stands on Stage One alone — the LUR pilots are a
documented research appendix, not a second product layer:

```
Validated tract-level public indicators (PM2.5, cropland/pastureland share, wetland extent)
        +
CDC/ATSDR SVI contextual percentile (state-relative screening, per state)
        +
EPA AQS air-monitor contextual points
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

## Running the pipeline (per state)

Every step below takes `--state <ABBR>` (default `WI`); the abbreviations and
FIPS codes onboardable today are defined in `src/states.py`. Run this full
sequence once per state you want in the app:

```bash
.venv\Scripts\python -m src.ingest --state WI
.venv\Scripts\python -m src.clean_svi --state WI
.venv\Scripts\python -m src.clean_indicator --state WI
.venv\Scripts\python -m src.ingest_cropland --state WI
.venv\Scripts\python -m src.ingest_wetlands --state WI
.venv\Scripts\python -m src.ingest_monitors --state WI
.venv\Scripts\python -m src.spatial_join --state WI
```

`ingest_cropland.py` and `ingest_wetlands.py` require the GEE service-account
key (`.env/*.json`, see below) and pull tract-level agricultural-pressure and
wetland-extent indicators via `src/gee_polygon_utils.py` (both are CONUS/
global-coverage datasets — no new external source needed per state).
`ingest_monitors.py` needs no download at all: it reads the national AQS
daily files already cached by `src/ingest_ground_truth.py`, filtered to the
target state. `spatial_join.py`'s last step always rebuilds the **combined**
`tract_screening_view.parquet` from every state's files found in
`data/processed/`, so running it for a new state doesn't lose previously
onboarded states — each state's percentiles stay relative to its own tracts
only (never pooled across states).

Every module is run as `-m src.<module>` (not `python src\<module>.py`) since
they import from `src.states`/`src.validate`, which need the repo root on
`sys.path`.

Onboarded today: **Wisconsin, Minnesota**. Configured in `src/states.py` but
not yet run: North Dakota, South Dakota, Michigan, Iowa, Illinois — onboard
one with the same 7-command sequence above.

Run `src\metrics.py` and `src\map_layers.py` (WI-only static exploratory
plots, unaffected by the multi-state work) separately if needed.

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
src/               pipeline modules (states registry, ingest, clean, join, validate, metrics, maps, satellite calibration)
app/               Streamlit app (streamlit_app.py entry, components/ for map/table/scatter/legend/appendix)
tests/             pytest validation suite
.env/              GEE service-account key (gitignored, not committed)
```

## Multi-state rollout

The screening pipeline (tracts, SVI, PM2.5, cropland/pastureland, wetlands,
AQS monitor points, and the combined screening view) is fully parameterized
by `src/states.py` — every module in the "Running the pipeline" section above
takes `--state <ABBR>`, and the app's sidebar "State" selector is a real
filter driven by whichever states exist in `tract_screening_view.parquet`.

**Live today**: Wisconsin (validated, original state) and Minnesota (pilot,
confirms the parameterized pipeline generalizes correctly — same schema, same
state-relative percentile ranges, same indicator dropdown).

**Configured but not yet run**: North Dakota, South Dakota, Michigan, Iowa,
Illinois — FIPS codes are in `src/states.py`; onboarding one is the same
7-command sequence used for Minnesota. Double-check each state's exact CDC
SVI filename spelling before running (`StateConfig.svi_csv_name` overrides
the default `name`-based guess if CDC's naming differs) and verify FIPS codes
against Census's own reference table as a transcription safety check.

**Design decisions already made, not still open**:
- **Contextual points** now come from EPA AQS (`src/ingest_monitors.py`),
  not Wisconsin DNR's ArcGIS layer — one state-agnostic source for every
  state, Wisconsin included. Trade-off: Wisconsin's contextual layer lost the
  non-AQS permitted-facility points its old DNR-sourced layer showed; it's
  ambient air monitors only now, for every state.
- **Percentiles are state-relative, always** — `indicator_percentile_wi`/
  `concern_percentile_wi` are ranked within `groupby(["state_abbr",
  "indicator_name"])`, never pooled across states. Selecting a state in the
  app shows that state's own self-contained screening view, the same pattern
  the county filter already uses within a state.
- **Multi-state map framing**: `app/components/map.py` computes its default
  view from `gdf.total_bounds()` rather than a fixed state-specific center/
  zoom constant, so a newly onboarded state's tracts are framed correctly
  with no per-state map constant to add.
estimates.
