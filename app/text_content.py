"""Hand-maintained copy for the methods drawer and the research-appendix
boundary list. Kept as plain constants (not parsed live from methodology.md)
because methodology.md mixes MVP content with the full LUR/calibration
research narrative — auto-extracting sections by heading match would be
brittle and could silently pull research framing into the default screening
workflow. tests/test_app_smoke.py canaries these against methodology.md so a
future edit there doesn't drift silently.
"""
from __future__ import annotations

DISCLAIMER_BANNER = (
    "Descriptive screening tool only. It does not estimate individual exposure, "
    "health risk, disease burden, or causality, and does not rank community worth."
)

BASIS_MISMATCH_NOTE = (
    "Indicator percentile is Wisconsin-relative; SVI percentile is national-relative. "
    "These are not on the same reference frame. Map color and the review table's "
    "\"relative concern\" column are direction-normalized per indicator (see Methods) "
    "so a high value always means more concern, even for protective indicators."
)

PURPOSE_AND_BOUNDARY = """
The Wisconsin Environmental Health Explorer is a **descriptive screening tool**
built for Clean Wisconsin analysts preparing county-level environmental-health
briefings. It combines publicly reported environmental-exposure indicators with
CDC/ATSDR Social Vulnerability Index (SVI) context at the census-tract level.

> This explorer is a descriptive screening tool. It does not estimate individual
> exposure, diagnose disease, establish causality, rank community worthiness, or
> replace environmental-health expertise and community input. Areas highlighted for
> review reflect the selected public indicators and analytic assumptions, not a
> definitive measure of risk or harm.
"""

DATA_SOURCES_TABLE = [
    {"Table": "Geometries", "Source": "Census TIGER/Line 2022", "Resolution": "Census tract, WI", "Year": "2022", "Unit": "—"},
    {"Table": "Social vulnerability", "Source": "CDC/ATSDR SVI 2022", "Resolution": "Census tract, WI", "Year": "2022", "Unit": "percentile, 0–1"},
    {"Table": "PM2.5", "Source": "EPA EJScreen 2.3, via Harvard Dataverse mirror", "Resolution": "Census tract, WI", "Year": "2022", "Unit": "µg/m³, modeled"},
    {"Table": "Row-crop & pastureland share", "Source": "USDA NASS Cropland Data Layer, via Google Earth Engine", "Resolution": "Census tract, WI", "Year": "2022", "Unit": "fraction of tract area"},
    {"Table": "Wetland & surface water extent", "Source": "Google Dynamic World V1, via Google Earth Engine", "Resolution": "Census tract, WI", "Year": "2022 (Jun–Sep composite)", "Unit": "fraction of tract area"},
    {"Table": "Contextual points", "Source": "WI DNR Air Management Data Viewer, \"All Monitors\"", "Resolution": "Point, statewide", "Year": "live snapshot", "Unit": "—"},
]

EJSCREEN_CAVEAT = """
EPA's EJScreen — the originally specified source for the PM2.5 indicator —
was removed from EPA's own website in February 2025 and remains unavailable from
any official EPA endpoint. This indicator is instead sourced from the **Harvard
Dataverse mirror** (doi:10.7910/DVN/RLR5AX), a third-party archival re-host of the
same underlying federal data: the values are unchanged (same EJScreen 2.3
methodology), but provenance now runs through an unofficial re-host rather than a
live, versioned federal API. No further EPA updates are available for this
indicator unless official access is restored.
"""

PERCENTILE_BASIS_MISMATCH = """
`overall_svi_percentile` is **national-relative**, as published by CDC/ATSDR (SVI
does not publish a state-relative percentile). `indicator_percentile_wi` is
**Wisconsin-relative**, computed directly in this pipeline as a rank of the raw
indicator value within that indicator's own distribution across all 1,542 WI
tracts (percentile is never computed across different indicators together). A
tract flagged for review is high on both reference frames at once — not on a
single, shared percentile scale.

**Indicator direction:** most indicators are "high is concern" (more PM2.5, more
row-crop or pastureland intensity = more concern), but wetland/surface-water
extent is a protective indicator — a *low* value is the concerning direction.
The map's color and the table's "relative concern" column use a direction-
normalized `concern_percentile_wi`, not the raw `indicator_percentile_wi`, so a
high value always means more concern regardless of which indicator is selected.
"""

MISSING_DATA_HANDLING = """
**SVI:** source sentinel `-999` is converted to `NaN`. A small number of Wisconsin
tracts (~1%) have no SVI score (typically zero-population or non-residential
tracts) and are shown as no-data, not imputed.

**Environmental indicators:** PM2.5 (EJScreen), row-crop/pastureland share (CDL),
and wetland/surface-water extent (Dynamic World) all have full tract coverage
for Wisconsin; no imputation was needed for any of them.

Join coverage is validated to be ≥90%; Stage One achieved 100% indicator
coverage and ~98.8% SVI coverage against the 1,542 Wisconsin tract geometries.
"""

WHAT_THIS_IS_NOT = [
    "Not an exposure model — it does not estimate how much pollution any individual or household actually experiences.",
    "Not a health outcomes model — no morbidity, mortality, or disease data is used.",
    "Not causal — co-occurrence of an elevated environmental indicator and elevated social vulnerability in a tract is a screening signal, not evidence that one causes the other.",
    "Not a ranking of community worth or need — the screening flag marks tracts that may warrant further review, not a priority order.",
]

DNR_CONTEXTUAL_NOTE = (
    "DNR points are a contextual layer only — they are not joined to any tract, "
    "and nearby tracts should not be assumed to share a monitor's readings."
)

RESEARCH_APPENDIX_WARNING = (
    "Research appendix: none of the modeling work below is used in, or combined "
    "with, the screening view above. Both pilot models were **not promoted** — "
    "see the promotion-decision tables below. This page documents a negative/mixed "
    "research finding, not a deployed feature."
)

RESEARCH_APPENDIX_BOUNDARY = [
    "A Milwaukee NO2 surface outside its 3 known monitor sites.",
    "Madison PM2.5 predictions presented as reliable time-general estimates.",
    "Either model's nominal 80% prediction intervals, without recalibration.",
    "Any satellite-layer description implying TROPOMI/MODIS materially improved either model — ablation testing found the opposite.",
    "A map combining either pilot's unvalidated predictions with SVI as if it were a public-action recommendation.",
]

CALIBRATION_SUMMARY = (
    "Every pollutant's held-out test R² is negative — a model that always predicted "
    "the training-set mean would score higher than any of these regressions on the "
    "Oct–Dec 2022 test data. This is the calibration model's honest answer to "
    "\"does the satellite proxy track the ground monitor well enough to lean on,\" "
    "and for 2022 Wisconsin, the answer is no with a same-day linear or shallow "
    "random-forest mapping."
)

OSM_ATTRIBUTION = "Road-distance feature derived from OpenStreetMap data. © OpenStreetMap contributors, ODbL."

LUR_PROMOTION_TABLE = [
    {
        "Criterion": "Beats every baseline in nearly all temporal folds",
        "Madison / PM2.5": "✗ (3/8)",
        "Milwaukee / NO2": "✓ (8/8)",
    },
    {
        "Criterion": "Median rolling-fold R² positive & useful",
        "Madison / PM2.5": "✗ (0.18, half the folds negative)",
        "Milwaukee / NO2": "✓ (0.74)",
    },
    {
        "Criterion": "Site-held-out R² positive",
        "Madison / PM2.5": "✓ (0.65, 0.73)",
        "Milwaukee / NO2": "✗ (−0.375 median after impervious-ablation fix attempt)",
    },
    {
        "Criterion": "No unacceptable season/site residual bias",
        "Madison / PM2.5": "~ (heteroscedastic at high values; ICC 0.5%)",
        "Milwaukee / NO2": "✗ (winter bias ≈1 std; ICC 67% — structural site-identity problem)",
    },
    {
        "Criterion": "Feature importance physically plausible",
        "Madison / PM2.5": "✓",
        "Milwaukee / NO2": "✓",
    },
    {
        "Criterion": "Prediction intervals well-calibrated",
        "Madison / PM2.5": "✗ (49.5% vs. nominal 80%)",
        "Milwaukee / NO2": "✗ (55.4% vs. nominal 80%)",
    },
]

LUR_PROMOTION_VERDICT = (
    "**Neither pilot is promoted.** Milwaukee/NO2 is temporally stable but spatially "
    "brittle (usable only for tracking its 3 existing monitors over time, with a "
    "winter bias still to fix); Madison/PM2.5 transfers between its 2 nearby sites "
    "but is not reliably better than a persistence baseline month-to-month, and a "
    "pre-registered attempt to add secondary-aerosol/wildfire-smoke features did "
    "not close that gap."
)
