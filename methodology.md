# Methodology (Stage One stub)

## Purpose and ethical boundary

The Wisconsin Environmental Health Explorer is a **descriptive screening tool**
built for Clean Wisconsin analysts preparing county-level environmental-health
briefings. It combines publicly reported environmental-exposure indicators with
CDC/ATSDR Social Vulnerability Index (SVI) context at the census-tract level.

> This explorer is a descriptive screening tool. It does not estimate individual
> exposure, diagnose disease, establish causality, rank community worthiness, or
> replace environmental-health expertise and community input. Areas highlighted for
> review reflect the selected public indicators and analytic assumptions, not a
> definitive measure of risk or harm.

The tool avoids language implying measured exposure, causal health outcomes, or
proof of environmental injustice. Fields are never named `risk_score`,
`priority_score`, or `harm_score` — this is enforced in the automated test suite.

## Data sources, years, and units (Stage One)

| Table | Source | Geographic resolution | Data year | Unit |
|---|---|---|---|---|
| Geometries | Census TIGER/Line 2022 | Census tract, WI | 2022 | — |
| Social vulnerability | CDC/ATSDR SVI 2022 | Census tract, WI | 2022 | percentile, 0–1 |
| Environmental indicator | EPA EJScreen 2.3 (PM2.5), via Harvard Dataverse mirror | Census tract, WI | 2022 | µg/m³, modeled |
| Contextual points | WI DNR Air Management Data Viewer, "All Monitors" | Point, statewide | live snapshot | — |

Full field-level detail, missing-value conventions, and per-table row counts are in
`data/metadata/data_dictionary.md`.

## Known limitation: EJScreen sourcing

EPA's EJScreen — `agent.md`'s originally specified source for the PM2.5
indicator — **was removed from EPA's own website in February 2025** as part of a
broader removal of environmental-justice tools, and remains unavailable from any
official EPA endpoint. This is a documented, litigated event (public interest
groups' 2025 legal challenge over the removal was dismissed for lack of standing
in March 2026), not a transient outage.

Stage One therefore sources the EJScreen 2.3 tract-level PM2.5 file from the
**Harvard Dataverse mirror** (`doi:10.7910/DVN/RLR5AX`), a third-party archival
re-host of the same underlying federal data, rather than from `epa.gov` directly.
Implications for interpretation:

- The indicator values themselves are unchanged (same EJScreen 2.3 methodology,
  same modeled PM2.5 surface), but provenance now runs through an unofficial
  re-host rather than a live, versioned federal API. If EPA restores an official
  EJScreen endpoint, `src/ingest.py`'s `EJSCREEN_URL` should be revisited.
- No further updates to this indicator will be available from EPA going forward
  unless and until official access is restored; future refreshes would need to
  rely on continued third-party archival efforts (Harvard Dataverse,
  screening-tools.com, or similar).

## Missing-data handling

- SVI: source sentinel `-999` is converted to `NaN`. A small number of Wisconsin
  tracts (~1%) have no SVI score (typically zero-population or non-residential
  tracts) and are left as `NaN` rather than imputed.
- Environmental indicator: EJScreen has full tract coverage for Wisconsin in this
  release; no imputation was needed.
- Join coverage is validated to be ≥90% (`tests/test_joins.py`); Stage One
  achieved 100% indicator coverage and ~98.8% SVI coverage against the 1,542
  Wisconsin tract geometries.

## Percentile conventions

`overall_svi_percentile` (and the other SVI theme percentiles) are **national**-
relative, as published by CDC/ATSDR — SVI does not publish a state-relative
percentile. `indicator_percentile_wi`, by contrast, is computed directly in this
pipeline as a **Wisconsin-relative** rank of the raw PM2.5 value across all 1,542
WI tracts (not EJScreen's own national percentile column). Screening flags compare
these two percentiles at their respective (national vs. state) reference frames —
analysts should keep this distinction in mind when interpreting a flagged tract,
and it is called out explicitly in the app's methods documentation to come in
Stage Two.

## What this is not

- Not an exposure model: it does not estimate how much pollution any individual
  or household actually experiences.
- Not a health outcomes model: no morbidity, mortality, or disease data is used.
- Not causal: co-occurrence of elevated environmental indicators and elevated
  social vulnerability in a tract is a screening signal, not evidence that one
  causes the other.
- Not a ranking of community worth or need: `screening_flag` marks tracts that
  may warrant further review, not a priority order.

## Satellite Calibration Model

Before adding more environmental variables to the screening view, this project
first validates *how well a satellite-observed proxy tracks the ground-monitor
reading it's meant to stand in for*, at the sites where both exist. This is a
**data-quality calibration check**, not a health or risk model: it never touches
SVI, never produces a per-tract score, and stays entirely at the
monitor-site/day level.

**Method.** For each pollutant, a Google Earth Engine extraction pulls a daily
satellite value at each Wisconsin AQS ground-monitor location (1 km buffer,
mean-reduced), and joins it to that site's EPA AQS daily concentration for the
same day. The joined table is split **temporally** — train on Jan 1–Sep 30,
2022, test on Oct 1–Dec 31, 2022 — and both a linear regression and a random
forest are fit on the training split and scored (R², RMSE, MAE) on the held-out
test split only.

| Pollutant | Ground truth (EPA AQS, no auth) | Satellite proxy | WI monitor sites |
|---|---|---|---|
| NO2 | `daily_42602_2022.zip` | Sentinel-5P TROPOMI `L3_NO2` | 3 |
| SO2 | `daily_42401_2022.zip` | Sentinel-5P TROPOMI `L3_SO2` | 7 |
| CO | `daily_42101_2022.zip` | Sentinel-5P TROPOMI `L3_CO` | 3 |
| PM2.5 | `daily_88101_2022.zip` | MODIS `MOD08_D3`/`MYD08_D3` Aerosol Optical Depth (Terra+Aqua mean) | 20 |

**Why temporal, not spatial, validation.** Wisconsin has only 3–20 ground
monitors per pollutant statewide. That's enough daily observations per site for
a legitimate temporal holdout (does the satellite track this site's readings
over time?), but it is **not** enough sites to claim the calibration
generalizes to census tracts with no monitor at all. A test-set R² here answers
"does the satellite agree with the monitor it's co-located with," not "can we
trust the satellite value in an unmonitored tract." Any future use of this
calibration to extend indicator coverage to unmonitored tracts should be
flagged as an extrapolation, not validated accuracy.

**Why MODIS AOD instead of another TROPOMI band for PM2.5.** TROPOMI does not
retrieve particulate matter directly. MODIS AOD is the standard satellite proxy
for PM2.5, but at ~1° (~100 km) resolution here — coarser than TROPOMI's
~1×1 km NO2/SO2/CO products — chosen over the finer-resolution `MCD19A2`
granule product to avoid its QA-bitmask filtering complexity in this first
pass. This resolution mismatch should be revisited before treating PM2.5
satellite estimates with the same confidence as the trace-gas ones.

**Satellite data access.** Sentinel-5P/MODIS data is pulled via Google Earth
Engine using a project-specific service-account credential (kept outside
version control in `.env/`, gitignored) — it is not available anonymously.

**Outputs:** `data/processed/ground_truth_<pollutant>.parquet`,
`satellite_<pollutant>.parquet`, `calibration_dataset_<pollutant>.parquet`,
`satellite_coverage_report.csv` (what fraction of ground-truth site-days had a
valid, non-cloud-obscured satellite retrieval — reported honestly, not hidden),
and `calibration_model_metrics.csv`. See `data/metadata/data_dictionary.md`.

### Results (2022 run): the test split says no, and that's the finding

| Pollutant | n train / test | Same-season correlation (train / test) | Best test R² |
|---|---|---|---|
| NO2 | 306 / 83 | 0.29 / 0.49 | −0.04 (random forest) |
| SO2 | 694 / 121 | −0.02 / −0.03 | −0.03 (linear) |
| CO | 381 / 110 | 0.09 / 0.03 | −0.01 (linear) |
| PM2.5 | 1,920 / 630 | 0.29 / 0.06 | −0.32 (linear) |

**Every pollutant's held-out test R² is negative** — a model that always predicted
the training-set mean would score higher than any of these regressions on the
Oct–Dec test data. This is the calibration model's honest answer to "does the
satellite proxy track the ground monitor well enough to lean on," and the
answer, for 2022 Wisconsin, is **no, not with a same-day linear or shallow
random-forest mapping** — for two distinct reasons visible in
`data/processed/calibration_plots/`:

- **SO2 and CO show essentially no correlation in either period** (|r| < 0.1).
  Wisconsin's ambient SO2/CO levels are low post-Clean-Air-Act background
  concentrations; TROPOMI's SO2/CO column retrievals are built for point-
  source plumes, not diffuse near-background levels, so there is no signal
  here to calibrate against with this indicator, not a modeling error.
- **NO2 and PM2.5 show real same-season correlation but fail across the
  train/test seasonal boundary.** Both ground concentrations rise into fall/
  winter (heating season, boundary-layer inversions trapping pollutants near
  the surface) while their satellite proxies do the opposite or flatten
  (`pm25_predicted_vs_actual.png` shows predictions compressed to a narrow
  band regardless of the true test-season value — the model is effectively
  guessing the training mean). A model fit only on Jan–Sep data has no way to
  learn this shift, so it systematically underpredicts the winter test period.
  This is a textbook AOD-PM2.5 winter breakdown (snow-cover reflectance and
  boundary-layer effects decouple column AOD from surface PM2.5) and a
  plausible seasonal-inversion effect for NO2.

**What this means for next steps, not yet built:** before trusting any
satellite proxy as an additional environmental-indicator input, either (a) add
explicit seasonal/meteorological features (day-of-year, boundary-layer height,
temperature) so the model can learn the seasonal relationship rather than
extrapolate a single-season linear fit across it, or (b) restrict any future
satellite-derived indicator to same-season comparisons only, and say so
explicitly wherever it's shown. Shipping the current single-feature models as
an indicator would fail the project's own screening-tool honesty bar — the
test split exists precisely to catch this before it happens.

## LUR Pilot: Madison PM2.5, Milwaukee NO2

> Initial satellite-only calibration models did not generalize across the 2022
> seasonal holdout. Subsequent multisource pilots combined satellite
> observations with meteorology, land-use, road-proximity, and cyclic time
> features. In temporally held-out evaluation, the Madison PM2.5 and Milwaukee
> NO2 models outperformed global-mean, seasonal-mean, site-mean, and
> persistence baselines. These results support descriptive, model-assisted
> screening research only; they do not establish individual exposure,
> regulatory compliance, disease risk, causality, or environmental-health
> burden. Deeper validation below shows this holds more robustly for one
> pilot than the other — see "Validation & Diagnostics."

This directly follows up on the calibration model's negative result: option
(a) above — add seasonal/meteorological/land-use context rather than relying
on the satellite value alone — implemented as a proper **Land Use Regression
(LUR)** predictor stack, piloted city-by-city rather than statewide. SO2 and
CO are **parked, not discarded**: their near-zero correlation in the
calibration model reflects Wisconsin's low background levels for those
pollutants specifically, not a flaw in this approach, and they may become
useful again for future industrial point-source work (e.g. near a specific
permitted facility) where local emissions could actually produce a detectable
plume. Only PM2.5 and NO2 — the two pollutants that showed real same-season
correlation — carry into this phase.

**Blocking finding before any code was written:** Wisconsin's AQS network has
**zero NO2 monitors in Dane County/Madison** (its 3 statewide NO2 sites are
6–60 km apart in the Milwaukee/Kenosha corridor; none within ~160 km of
Madison). Madison does have 2 PM2.5 monitors. This became a two-pilot
rollout of one reusable pipeline (`src/ingest_lur_features.py`,
`src/build_lur_dataset.py`, `src/lur_model.py`): **Madison/PM2.5** (2 monitor
sites) and **Milwaukee/NO2** (3 monitor sites, city buffer widened to 70 km to
cover all three).

### Predictor stack

| Predictor | Source | Notes |
|---|---|---|
| Own-pollutant satellite proxy | `satellite_pm25`/`satellite_no2.parquet` (already built) | Same TROPOMI/MCD19A2 products as the calibration model |
| Cross-pollutant satellite proxy | Extracted fresh at each pilot's own sites (`lur_cross_satellite_<city>.parquet`) | TROPOMI NO2 as a *feature* for the Madison PM2.5 model and vice versa for Milwaukee — the existing `satellite_*.parquet` tables only cover each pollutant's own, different monitor locations |
| Temperature, humidity, wind, precipitation | ERA5-Land Hourly (`ECMWF/ERA5_LAND/HOURLY`), daily aggregated | Humidity/wind speed/direction derived locally (Magnus-Tetens, u/v components) from raw bands, not pulled pre-computed |
| Boundary layer height | ERA5 Hourly (`ECMWF/ERA5/HOURLY`) | **Not available in ERA5-Land** — confirmed by listing bands; only the coarser (~28 km) full-atmosphere reanalysis carries it, so this is a second GEE collection pull |
| Impervious surface %, elevation | NLCD 2021 (`impervious` band), USGS 3DEP 10 m (`elevation`, via the `_collection` mosaic — the singular `USGS/3DEP/10m` asset is deprecated) | Static, 500 m buffer around each site |
| Distance to nearest major road | OpenStreetMap (motorway/trunk/primary ways), queried directly against the Overpass API | See implementation note below |
| Day-of-year (sin/cos), weekend flag, heating-season flag (Oct–Apr) | Computed locally | Gives the model explicit seasonal/temporal context instead of forcing it to infer season from a single satellite value |

**OSM data is © OpenStreetMap contributors, ODbL-licensed** — this attribution
is required wherever the road-distance feature or any map built from it is
shown (e.g. the future Stage Two app).

**Implementation note on OSM access:** the original plan was to use `osmnx`,
but its graph-building request to both `overpass-api.de` and the Kumi Systems
mirror repeatedly hit connection timeouts in this environment. A plain
`requests` POST of the same Overpass query succeeded in ~20 seconds — the
actual blocker turned out to be that `overpass-api.de`'s Apache config
returns `406 Not Acceptable` for the default `python-requests` User-Agent
specifically (confirmed directly: an identical query succeeds with a
curl-style UA and fails only on that header). The pipeline queries Overpass
directly and builds road geometries with `shapely`/`geopandas` rather than
depending on `osmnx`, identifying itself with a **truthful, stable UA** —
`SatelliteEnvironmentalHealthExplorer/0.1 (repo URL; contact address)` — not
another application's identity, per OSM's usage guidance. Per that same
guidance, the raw Overpass response is fetched **once per city and cached**
to `data/raw/osm_major_roads_<city>.json` (logged with a checksum in
`ingest_log.csv`, same as every other raw source), rather than re-queried on
every pipeline run.

### Results (2022 run)

Same temporal split as the calibration model (train Jan 1–Sep 30, test
Oct 1–Dec 31), but now scored against **five baselines** per the user's own
bar — a model that can't beat a season- or persistence-aware baseline isn't
operationally useful, even with positive R²:

| Pilot | Best baseline (test R²) | Random forest | Hist gradient boosting |
|---|---|---|---|
| Madison / PM2.5 | persistence, 0.25 | 0.43 | **0.52** |
| Milwaukee / NO2 | persistence, 0.23 | 0.66 | **0.69** |

**Both models clearly beat every baseline for both pilots** — a real result,
not just a less-negative one. `data/processed/lur_plots/*.png` show the
predicted-vs-actual clouds tracking the 1:1 line reasonably well across the
full concentration range, in contrast to the calibration model's compressed,
near-constant predictions. This validates the diagnosis behind this whole
phase: a single coarse satellite pixel over a city-sized area, with no
seasonal or land-use context, was the problem — not that satellite data is
inherently useless here.

One methodological substitution, noted rather than silently made: the user's
writeup asked for a "month-specific mean" baseline, but with one year of data
split chronologically, train and test share **no calendar months at all** —
a literal month-of-year mean can't be estimated from training data for any
test month. A **meteorological-season mean** is used instead (`baseline_season_mean`
in `lur_model_metrics.csv`), which the split partially supports: Sep
(training) estimates a Fall mean applied to Oct/Nov (test); Jan–Feb
(training) estimate a Winter mean applied to Dec (test).

**Caveats that still apply:** 2–3 monitor sites per city is enough for the
temporal validation done here, not for claiming the model generalizes
spatially to un-monitored parts of either city — the same limitation
documented for the statewide calibration model. Extending this to a
tract-level indicator (rather than a monitor-site validation) would need
either more monitors or an explicit uncertainty treatment for the
interpolation, not yet built.

### Validation & Diagnostics

Before adding any more model complexity, both pilots were pushed through five
additional checks — do they hold up across time, across space, which features
actually drive them, and where do they still get it wrong. Outputs:
`lur_rolling_cv.csv`, `lur_site_holdout.csv`, `lur_ablation.csv`,
`lur_feature_importance.csv` + `lur_plots/*_shap_summary.png`,
`lur_residual_summary.csv` + `lur_plots/*_residual_diagnostics.png`.

**1. Rolling-origin temporal validation (`src/lur_rolling_cv.py`).** Instead
of trusting one Jan–Sep/Oct–Dec split, 8 expanding-window folds (train
through April/test May, ... train through Nov/test Dec), each scored against
fold-own global-mean and persistence baselines only (no full-year baseline
ever sees test-period information):

| Pilot | HGB median fold R² (range) | % of folds beating every baseline |
|---|---|---|
| Madison / PM2.5 | 0.18 (−0.68 to 0.60) | 37.5% (3 of 8) |
| Milwaukee / NO2 | 0.74 (0.43 to 0.87) | 100% (8 of 8) |

**Milwaukee/NO2 is stable — every fold beats every baseline, and R² never
drops below 0.43.** Madison/PM2.5 is not: half its folds score *below zero*.
The single-split R²=0.52 reported above was closer to Madison's best month
than its typical one. This is exactly the failure mode rolling-origin
validation exists to catch, and it means the Madison PM2.5 model, as it
stands, should not be described as reliably beating simple baselines
month-to-month — only that it can, in favorable periods.

**2. Leave-one-monitor-site-out validation (`src/lur_site_holdout.py`).**
Train on all but one site's full year, predict the held-out site. Caveat
upfront: Madison has only 2 sites (1 holdout pair), Milwaukee 3 (3 pairs) —
this checks for gross overfitting to a site's own offset, it does not
establish broad spatial generalization.

| Pilot | Held-out site | HGB R² |
|---|---|---|
| Madison / PM2.5 | 550250041 | 0.73 |
| Madison / PM2.5 | 550250047 | 0.65 |
| Milwaukee / NO2 | 550590019 (Pleasant Prairie/Kenosha) | −0.38 |
| Milwaukee / NO2 | 550790056 (Milwaukee) | −1.52 |
| Milwaukee / NO2 | 550790068 (Milwaukee) | −3.73 |

**The two pilots invert here.** Madison's site-holdout R² (0.65–0.73) is
*better* than its rolling-CV result — its two sites, ~5 km apart, are similar
enough that the model transfers between them even though it doesn't hold up
across months. Milwaukee's site-holdout is **uniformly, badly negative** —
despite acing every temporal fold, the NO2 model cannot predict a monitor
location it never trained on. Combined with the ablation/SHAP results below
(`impervious_pct` is by far the top feature, and Milwaukee's 3 sites span very
different urban contexts — dense Milwaukee vs. Kenosha/Pleasant Prairie), the
likely explanation is that the model has learned each site's local
impervious-surface level as an offset rather than a transferable
impervious→NO2 relationship. **Net read: Milwaukee/NO2 should be trusted at
its 3 existing monitor sites over time, not extrapolated to a new location in
its current form.**

**3. Feature-family ablation (`src/lur_ablation.py`, HGB only).** Full-feature
model vs. one family dropped at a time, same Jan–Sep/Oct–Dec split:

| Pilot | Full R² | −satellite | −meteorology | −land_use | −time |
|---|---|---|---|---|---|
| Madison / PM2.5 | 0.515 | 0.514 (−0.001) | 0.040 (−0.476) | 0.526 (+0.011) | 0.475 (−0.040) |
| Milwaukee / NO2 | 0.693 | 0.697 (+0.004) | 0.425 (−0.268) | 0.337 (−0.356) | 0.562 (−0.132) |

**Satellite features contribute almost nothing to either model** — removing
them changes test R² by ≤0.004 in both directions. Meteorology is the single
largest driver for both (boundary-layer height and humidity for PM2.5; wind
and BLH for NO2). Land use matters a lot for Milwaukee (removing it costs
0.356 R², consistent with the site-holdout failure above — the model leans on
`impervious_pct`) but not for Madison, where only 2 distinct site values exist
for any static feature, so there's nothing generalizable for a tree to learn
from it. This is worth stating plainly: **despite this project's satellite
integration framing, the satellite proxy is not what's making either model
work.** Weather and, for Milwaukee, land use are.

**4. Feature contribution diagnostics (`src/lur_feature_importance.py`).**
Permutation importance and SHAP (`lur_plots/*_shap_summary.png`) agree with
the ablation result and, more importantly, are physically/urban-form
plausible — no sign the model is leaning on an accidental proxy (e.g. a
missing-value flag) instead of real signal:
- **Madison/PM2.5** top features: `boundary_layer_height` (by a wide margin),
  `relative_humidity_pct`, `wind_direction_deg`, `total_precipitation` — all
  standard PM2.5 meteorological drivers (a shallower boundary layer traps
  particulates near the surface).
- **Milwaukee/NO2** top features: `impervious_pct` (by a wide margin),
  `wind_speed_ms`, `is_weekend` (SHAP shows weekends push predictions down —
  correct sign for a traffic-linked pollutant), `boundary_layer_height`. Every
  `satellite_no2`/`cross_satellite_pm25` SHAP contribution sits near zero.

**5. Residual diagnostics (`src/lur_residuals.py`).** On the standard Oct–Dec
test set:
- **Madison/PM2.5**: residual spread widens at high observed values (the
  model underpredicts the handful of highest-PM2.5 days — visible in
  `madison_pm25_residual_diagnostics.png`), but no strong site or seasonal
  split (fall mean +0.45, winter +0.22, both near zero).
  One data-coverage note: the Oct–Dec test window covers only the two Dane
  County sites, as expected.
- **Milwaukee/NO2**: a real, systematic **winter underprediction bias** —
  mean residual −2.0 (std 2.4) in winter vs. −0.26 in fall. The model
  under-forecasts NO2 in December specifically, even though it was the best
  rolling-CV performer overall. Also note: Milwaukee's third monitor
  (550590019, Pleasant Prairie/Kenosha) has **no ground-truth readings after
  September 6, 2022** — it never appears in the standard Oct–Dec test set at
  all, only in the site-holdout and rolling-CV checks above, which is why
  those two checks are the ones that surface its poor spatial transferability.

**Promotion decision, applying the five criteria mechanically where
possible:**

| Criterion | Madison / PM2.5 | Milwaukee / NO2 |
|---|---|---|
| Beats every baseline in nearly all temporal folds | ✗ (3/8) | ✓ (8/8) |
| Median rolling-fold R² positive & useful | ✗ (0.18, half the folds negative) | ✓ (0.74) |
| Site-held-out R² positive | ✓ (0.65, 0.73) | ✗ (−0.38 to −3.73) |
| No unacceptable season/site residual bias | ~ (heteroscedastic at high values, no season split) | ✗ (winter bias ≈1 std) |
| Feature importance physically plausible | ✓ | ✓ |

**Neither pilot passes cleanly, for opposite reasons.** Milwaukee/NO2 is
temporally stable but spatially brittle — usable for tracking its 3 existing
monitors over time, not for inferring NO2 anywhere else, and its winter bias
needs fixing before even that. Madison/PM2.5 transfers between its 2 nearby
sites but is not reliably better than a persistence baseline month-to-month.
**Neither is promoted to a labeled model-assisted indicator layer yet.**

### Milwaukee Diagnosis: is impervious_pct acting as a site identifier?

Following the clearest hypothesis first, before any retraining. Outputs:
`lur_multiscale_features_<city>.parquet`, `lur_site_feature_distributions_<city>.csv`,
`lur_plots/<city>_<pollutant>_shap_dependence_by_site.png`,
`lur_rolling_cv_variants.csv`, `lur_site_holdout_variants.csv`,
`lur_mixed_effects.csv`.

**Confirmed, unambiguously.** The SHAP dependence plot for `impervious_pct`,
colored by site, shows exactly the step-like pattern hypothesized: three
perfectly vertical clusters — one per site, since `impervious_pct` is a
single static value per site with zero within-site variation — each with a
*wildly different* SHAP contribution range (site 550590019: −4.0 to −1.8;
550790068: −4.0 to −1.6; 550790056: +2.3 to +5.8). With only 3 distinct
x-values ever seen, the model has learned a 3-entry lookup table keyed on
site identity, not a continuous impervious→NO2 relationship — it cannot
interpolate to a 4th value it's never seen. `lur_site_feature_distributions_milwaukee.csv`
also shows *why* this happens to work as an identity key: the three sites'
land cover is genuinely categorically different (550590019/Pleasant
Prairie-Kenosha: only 32% developed, 20.6% water, 47% "other"; the two
Milwaukee-proper sites: 83–100% developed) — real land-use diversity, but
sampled at only 3 points, which is indistinguishable from a site ID to a
tree model.

**A formal mixed-effects model (`src/lur_mixed_effects.py`, diagnostic only —
not a model to deploy at unmonitored sites) quantifies this directly:**
between-site variance accounts for **67% of Milwaukee/NO2's total outcome
variance** (ICC), vs. **0.5% for Madison/PM2.5**. Two-thirds of what
determines Milwaukee NO2 levels is *which site*, not a relationship any
model can transfer elsewhere — this is a structural property of the data
(3 sites spanning genuinely different urban contexts), not a fixable
modeling mistake. (Caveat: with only 3 groups, this ICC is directional, not
statistically precise.)

**The fix attempt was only a partial success.** Re-running rolling CV and
site holdout with (a) `impervious_pct` dropped entirely, and (b) replaced
with multi-scale impervious/road-density/land-cover-mix features at 100 m,
300 m, 500 m, and 1 km buffers (still spatially smoother, still standard LUR
practice) — from `src/lur_impervious_ablation.py`:

| Variant | Rolling median R² | Site-holdout median R² | Per-site holdout R² |
|---|---|---|---|
| Full model (baseline) | 0.741 | −1.524 | −0.38, −1.52, −3.73 |
| No impervious | 0.741 | −0.375 | −0.38, −1.52, **+0.45** |
| Multiscale land use | 0.738 | −0.375 | −0.38, −1.52, **+0.45** |

Temporal performance is unaffected either way (0.741 → 0.738) — confirming
`impervious_pct` was never carrying real temporal signal, only a spatial
shortcut. Dropping it flips *one* site (550790068) positive but leaves the
other two **numerically identical** to the full model. Verified this isn't a
bug (the feature really is excluded — 26 vs. 28 feature columns); the
identical predictions mean the model found an equally effective site-identity
substitute among the *other* static features (`elevation_m`,
`dist_to_major_road_km` also differ sharply by site) — replacing one
identity-shaped feature with another doesn't fix the underlying problem when
only 2 training sites are available to fit against.

**Conclusion, applying the user's stated decision gate directly: Milwaukee's
site-holdout performance remains negative — median R² = −0.375, two of three
sites still clearly negative — after removing the suspect feature and trying
smoother multi-scale replacements.** Per that gate, this is treated as
**evidence that a 3-monitor network is structurally insufficient for spatial
interpolation validation in Milwaukee**, not as a feature-engineering problem
still waiting for the right fix. Milwaukee/NO2 stays scoped to what its
rolling-CV result actually supports: tracking NO2 over time **at its 3
existing monitored locations**, not inferring NO2 at any other point in the
metro area. Citywide interpolation for Milwaukee is not pursued further
without either more monitors or a fundamentally different validation
strategy (e.g. borrowing strength from other Wisconsin NO2-adjacent data,
not attempted here).

### Madison Diagnosis: why does the model fail specifically in summer?

Outputs: `lur_fold_diagnostics_madison_pm25.csv`,
`lur_aqs_quality_flags_madison_pm25.csv`, `lur_persistence_comparison.csv`,
`lur_quantile_coverage.csv`.

**The failing folds are the summer ones.** Joining each rolling fold's R² to
that fold's mean weather conditions: the three worst folds (June −0.30, July
−0.68, August −0.30) are also the three warmest (mean temperature 294–296 K)
with the shallowest boundary layers (571–669 m) and lowest wind speed
(2.2–2.6 m/s); the best folds (October–December, R² 0.21–0.60) are the
coldest (268–283 K) with the deepest boundary layers and highest wind
(2.9–3.2 m/s). Mean PM2.5 is also lower in the failing folds (6.5 µg/m³ vs.
7.8 µg/m³) — the model is worse specifically when concentrations are lower
and more compressed, a regime where the same absolute error costs more R².

**Two data-quality hypotheses were checked and ruled out, not just
assumed away:**
- *Instrument/method changes*: both Madison sites run **concurrent**
  raw+corrected POC pairs (e.g. POC 3 = raw Teledyne T640 reading, POC 23 =
  its own "(Corrected)" reading) spanning the entire year, plus a short-lived
  reference sampler at one site (Jan only, 60 obs) — there is no mid-year
  instrument swap that coincides with the failing summer folds.
- *AQS "Event Type" flag* (initially treated as a possible wildfire-smoke
  indicator): turned out to be a **reporting-stream artifact**, not a
  per-day event flag — "Included" appears for literally 100% of POC 3 (raw)
  rows and 0% of POC 23 (corrected) rows, every single month, with zero
  date-level variation. Verified directly before reporting it as a finding;
  recorded here so this dead end isn't re-investigated.

**Neither check explains the instability — it looks like a genuine
regime-dependent modeling gap**, not a data artifact: the current feature
set (temperature, humidity, wind, precipitation, BLH, static land use, cyclic
day-of-year) doesn't capture whatever drives summer PM2.5 variability in
Madison as well as it captures the cold-season pattern (heating-driven
inversions the model clearly does learn, given the strong Oct–Dec folds).
Candidate causes not yet tested: warm-season secondary/photochemical aerosol
formation, and specific Canadian wildfire-smoke transport days (2022 had
documented episodes) that a `doy_sin`/`doy_cos` seasonal encoding cannot
represent — both are exactly the kind of "add features only after diagnosis"
candidates the next phase should test, not before.

**The "season-aware" persistence baseline made things worse, not better.** A
7-day trailing per-site mean (causal, no look-ahead) was compared against the
existing single-previous-day persistence on the standard split:

| Pilot | 1-day persistence R² | 7-day trailing persistence R² |
|---|---|---|
| Madison / PM2.5 | 0.251 | **−0.232** |
| Milwaukee / NO2 | 0.227 | 0.159 |

Smoothing over a week washes out real day-to-day autocorrelation faster than
it removes noise — single-day persistence remains the harder baseline to
beat for both pilots. This baseline substitution is reported as a negative
result, not adopted.

**Prediction intervals are meaningfully overconfident.** `HistGradientBoostingRegressor(loss="quantile")`
at the 10th/90th percentiles, nominal 80% coverage, on the standard test set:

| Pilot | Empirical coverage (nominal 80%) | Fall | Winter |
|---|---|---|---|
| Madison / PM2.5 | 49.5% | 45.9% | 56.5% |
| Milwaukee / NO2 | 55.4% | 47.5% | 71.0% |

Both pilots' 80% intervals actually contain the true value only about half
the time — a materially overconfident uncertainty estimate in both cases,
worse in fall than winter for both. **Any future point forecast from either
model should be accompanied by these wider, empirically-calibrated
intervals, not the model's own nominal ones**, and this alone is reason
enough not to present either model's predictions as precise values.

### Updated promotion table

| Criterion | Madison / PM2.5 | Milwaukee / NO2 |
|---|---|---|
| Beats every baseline in nearly all temporal folds | ✗ (3/8) | ✓ (8/8) |
| Median rolling-fold R² positive & useful | ✗ (0.18, half the folds negative — concentrated in summer, diagnosed above) | ✓ (0.74) |
| Site-held-out R² positive | ✓ (0.65, 0.73) | ✗ (still −0.375 median after impervious-ablation fix attempt) |
| No unacceptable season/site residual bias | ~ (heteroscedastic at high values; ICC 0.5% confirms not a site-identity problem) | ✗ (winter bias ≈1 std; ICC 67% confirms a structural site-identity problem) |
| Feature importance physically plausible | ✓ | ✓ |
| Prediction intervals well-calibrated | ✗ (49.5% vs. nominal 80%) | ✗ (55.4% vs. nominal 80%) |

**Neither pilot is promoted.** Milwaukee's spatial-transfer failure is now
understood as structural (3 sites, 67% between-site variance) rather than a
fixable feature-engineering bug, and is treated accordingly — the MVP falls
back to its strongest evidence base (tract-level public indicators, DNR
contextual layers, SVI, bounded descriptive screening) for anything
location-general, while Milwaukee/NO2's temporal result is retained as
documented research evidence about its 3 specific monitored sites only.
Madison's instability is now understood as a summer-regime gap, not a data
problem; a pre-registered test of two candidate fixes (photochemical/
secondary aerosol proxy, wildfire-smoke proxy — see below) came back
negative, closing this modeling workstream for now. Both models' prediction
intervals need recalibration before either is shown to anyone as anything
more precise than a directional signal.

### RQ1 conclusion

> With the available 2022 monitor, meteorological, land-use, and tested
> satellite data, the pilot models do not meet the project's criteria for
> location-general environmental exposure prediction. Madison PM2.5 lacks
> stable temporal generalization, while Milwaukee NO2 lacks spatial transfer
> beyond its three observed monitoring sites. Satellite predictors added
> negligible incremental predictive value in both pilots.

This is treated as a **substantive, negative research finding**, not an
unfinished result: the current multisource pipeline cannot yet generate
trustworthy model-assisted local indicators for broad tract-level screening.
It can, and does, support the two narrower claims each pilot's validation
actually earned (Milwaukee: site-time research only; Madison: unpromoted
research baseline) — see the validation matrix and "what this project does
not show" below.

| Pilot | What worked | What failed | Decision |
|---|---|---|---|
| Milwaukee NO2 | Strong temporal prediction at the 3 observed sites (rolling median R²=0.74) | All leave-one-site-out results negative; no evidence of citywide spatial transfer | Retain as site-time research only |
| Madison PM2.5 | Positive site-holdout results (R²=0.65–0.73) | Unstable summer rolling folds; only 3/8 beat baselines | Retain as unpromoted research baseline |
| Satellite ablation | Tested directly, both pilots | Removing TROPOMI/MODIS changes R² by ≤0.004 | Not decision-relevant predictors here |
| Prediction intervals | Nominal 80% intervals generated | Empirical coverage only ~50–55% | Overconfident; do not publish as calibrated uncertainty |

### What this project does not show

None of the following should be presented in the explorer, now or in Stage
Two, on the strength of the evidence gathered so far:
- A Milwaukee NO2 surface outside its 3 known monitor sites.
- Madison PM2.5 predictions presented as reliable time-general estimates.
- Either model's nominal 80% intervals, without recalibration.
- Any satellite-layer description implying TROPOMI/MODIS materially
  improved either model (ablation says otherwise, directly).
- A map combining either pilot's unvalidated predictions with SVI as if it
  were a public-action recommendation.

The MVP therefore stands on the Stage One indicator layers on their own —
tract-level environmental indicator, SVI context, DNR points, sourced and
dated — with the LUR pilots retained as a documented, non-deployed research
appendix, not a second product layer.

### Pre-registered Madison PM2.5 experiment: secondary-aerosol and wildfire-smoke features

Registered **before** running, so the result — whichever way it comes out —
is reported as obtained, not selected. This is a single bounded test of two
named hypotheses, not open-ended feature search, and closes the Madison
modeling workstream regardless of outcome per the project's own decision
rule (add features only after diagnosis; don't keep tuning once the
evidence says the bottleneck is data support, not model capacity).

**Hypotheses:**
1. *Secondary-aerosol formation*: Madison's failing folds are the three
   warmest, sunniest summer months (`lur_fold_diagnostics_madison_pm25.csv`).
   Photochemical secondary aerosol formation is driven by solar radiation,
   not captured by the current feature set. Proxy: `surface_solar_radiation_downwards`
   (ERA5-Land, daily mean) — reuses the exact collection already queried for
   Madison's other weather features, no new data source.
2. *Wildfire smoke*: 2022 had documented Canadian wildfire smoke transport
   into the Midwest, which the current cyclic day-of-year encoding cannot
   represent. Proxy: `absorbing_aerosol_index` (Sentinel-5P TROPOMI, the UV
   Aerosol Index — the standard operational smoke/dust detection product),
   from `COPERNICUS/S5P/OFFL/L3_NO2`, the same collection already queried
   for Madison's cross-satellite NO2 predictor.

**Pre-specified success criteria (identical to the existing promotion
gates — no new criteria introduced after seeing results):** re-run the exact
same rolling-origin CV (`src/lur_rolling_cv.py`'s `run_fold`) and
leave-one-site-out (`src/lur_site_holdout.py`'s `run_holdout`) logic with
these two features added, nothing else changed. Promotion requires beating
every baseline in nearly all 8 rolling folds and a positive, practically
useful median rolling-fold R² — the same bar Madison failed before.

**Result: negative. Neither feature moved the needle.** Both proxies
extracted with good coverage (solar radiation 100%, aerosol index 88.4%),
ruling out a data-availability excuse. With both added, nothing else
changed:

| Metric | Before | After |
|---|---|---|
| Rolling median R² | 0.178 | 0.169 (slightly worse) |
| % folds beating every baseline | 37.5% (3/8) | 37.5% (3/8), unchanged |
| Site-holdout median R² | 0.687 | 0.699 (no material change) |

Per-fold, the three previously-failing summer folds did not recover — June
got worse (−0.30 → −0.68), July was essentially unchanged (−0.68 → −0.59),
August got worse (−0.30 → −0.38). **Pre-specified promotion criteria: not
met.** This closes the Madison PM2.5 modeling workstream per the pre-
registered stopping rule — the two named hypotheses were tested directly and
did not hold, at least not as simple additive features on top of the
existing model. The RQ1 conclusion above stands as written: with the
available 2022 data, Madison PM2.5 does not support stable temporal
generalization, and this specific, bounded attempt to fix that is now also
part of the documented evidence, not an open loop. Any further work on
Madison PM2.5 would need either a materially different feature
representation (e.g. an interaction term, not just an additive one) or
should wait for more monitor-years of data — not another round of
single-feature additions.

## Stage Two (not yet built)

Interactive Folium map, Streamlit application, hover tooltips, sortable
screening table, and a methods/limitations drawer are explicitly out of scope for
Stage One and will be added in Stage Two.
