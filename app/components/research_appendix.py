"""Renders the research-appendix content: the non-promoted satellite-
calibration and LUR modeling workstreams. Called from within a dedicated
st.tabs() tab in app/streamlit_app.py rather than a separate Streamlit
`pages/` entry -- the non-promotion warning is still the first thing
rendered inside that tab, so folding it into a tab does not blend it with
the screening view's own content or state.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.data_loader import calibration_plot_path, load_lur_csv, lur_plot_path
from app.text_content import (
    CALIBRATION_SUMMARY,
    LUR_PROMOTION_TABLE,
    LUR_PROMOTION_VERDICT,
    MADISON_DIAGNOSIS_SUMMARY,
    MADISON_EXPERIMENT_HYPOTHESES,
    MADISON_EXPERIMENT_RESULT,
    MILWAUKEE_DIAGNOSIS_SUMMARY,
    MILWAUKEE_FIX_ATTEMPT_SUMMARY,
    OSM_ATTRIBUTION,
    RESEARCH_APPENDIX_BOUNDARY,
    RESEARCH_APPENDIX_WARNING,
)


def _render_pilot(
    lur_model_metrics: pd.DataFrame,
    lur_rolling_cv: pd.DataFrame,
    lur_site_holdout: pd.DataFrame,
    lur_feature_importance: pd.DataFrame,
    lur_ablation: pd.DataFrame,
    city: str,
    pollutant: str,
    plot_prefix: str,
) -> None:
    st.subheader(f"{city.title()} / {pollutant.upper()}")

    st.markdown("**Full-split model metrics (baselines + models)**")
    subset = lur_model_metrics[
        (lur_model_metrics["city"] == city) & (lur_model_metrics["pollutant"] == pollutant)
    ]
    st.dataframe(subset, use_container_width=True, hide_index=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Rolling-origin temporal validation (median R² by method)**")
        rolling = lur_rolling_cv[
            (lur_rolling_cv["city"] == city) & (lur_rolling_cv["pollutant"] == pollutant)
        ]
        st.dataframe(
            rolling.groupby("method")["r2"].median().reset_index().rename(columns={"r2": "median_r2"}),
            use_container_width=True, hide_index=True,
        )
    with col_b:
        st.markdown("**Leave-one-monitor-site-out (HGB R² per held-out site)**")
        holdout = lur_site_holdout[
            (lur_site_holdout["city"] == city) & (lur_site_holdout["pollutant"] == pollutant)
            & (lur_site_holdout["method"] == "model_hist_gradient_boosting")
        ]
        st.dataframe(
            holdout[["held_out_site", "r2"]], use_container_width=True, hide_index=True,
        )

    st.markdown("**Top permutation-importance features**")
    importance = lur_feature_importance[
        (lur_feature_importance["city"] == city) & (lur_feature_importance["pollutant"] == pollutant)
    ].sort_values("perm_importance_mean", ascending=False).head(5)
    st.dataframe(importance, use_container_width=True, hide_index=True)

    st.markdown(
        "**Feature-family ablation** (test R² when each family is dropped -- "
        "this is the direct evidence behind \"satellite added negligible "
        "value,\" not just a proxy for it)"
    )
    ablation = lur_ablation[
        (lur_ablation["city"] == city) & (lur_ablation["pollutant"] == pollutant)
    ][["ablated_family", "r2", "r2_drop_from_full"]]
    st.dataframe(ablation, use_container_width=True, hide_index=True)

    if plot_prefix == "milwaukee_no2":
        st.caption(OSM_ATTRIBUTION)

    plot_cols = st.columns(2)
    with plot_cols[0]:
        st.image(
            str(lur_plot_path(f"{plot_prefix}_predicted_vs_actual.png")),
            caption="Test-set predicted vs. actual", use_container_width=True,
        )
    with plot_cols[1]:
        st.image(
            str(lur_plot_path(f"{plot_prefix}_shap_summary.png")),
            caption="SHAP feature contributions", use_container_width=True,
        )


def _render_milwaukee_diagnosis(lur_site_holdout_variants: pd.DataFrame) -> None:
    st.markdown("**Milwaukee / NO2 — is `impervious_pct` acting as a site identifier?**")
    st.markdown(MILWAUKEE_DIAGNOSIS_SUMMARY)
    st.image(
        str(lur_plot_path("milwaukee_no2_shap_dependence_by_site.png")),
        caption="SHAP value for impervious_pct vs. its value, colored by site",
        use_container_width=True,
    )
    st.markdown("**Fix attempt: dropping / replacing `impervious_pct`**")
    variants = lur_site_holdout_variants[
        (lur_site_holdout_variants["city"] == "milwaukee")
        & (lur_site_holdout_variants["pollutant"] == "no2")
        & (lur_site_holdout_variants["method"] == "model_hist_gradient_boosting")
    ][["variant", "held_out_site", "r2"]]
    st.dataframe(variants, use_container_width=True, hide_index=True)
    st.markdown(MILWAUKEE_FIX_ATTEMPT_SUMMARY)


def _render_madison_diagnosis(
    lur_fold_diagnostics: pd.DataFrame, lur_quantile_coverage: pd.DataFrame
) -> None:
    st.markdown("**Madison / PM2.5 — why does the model fail specifically in summer?**")
    st.markdown(MADISON_DIAGNOSIS_SUMMARY)
    st.markdown("**Rolling-CV fold diagnostics (weather regime per fold)**")
    st.dataframe(
        lur_fold_diagnostics[
            ["test_month_start", "r2", "mean_concentration", "mean_boundary_layer_height", "mean_wind_speed_ms"]
        ],
        use_container_width=True, hide_index=True,
    )
    st.markdown("**Prediction-interval coverage (nominal 80%, both pilots)**")
    st.dataframe(lur_quantile_coverage, use_container_width=True, hide_index=True)


def _render_madison_experiment(lur_madison_experiment_results: pd.DataFrame) -> None:
    st.markdown(MADISON_EXPERIMENT_HYPOTHESES)
    row = lur_madison_experiment_results.iloc[0]
    before_after = pd.DataFrame(
        [
            {
                "Metric": "Rolling median R²",
                "Before": row["rolling_median_r2_before"],
                "After": row["rolling_median_r2_after"],
            },
            {
                "Metric": "% folds beating every baseline",
                "Before": row["pct_folds_beating_baseline_before"],
                "After": row["pct_folds_beating_baseline_after"],
            },
            {
                "Metric": "Site-holdout median R²",
                "Before": row["site_holdout_median_r2_before"],
                "After": row["site_holdout_median_r2_after"],
            },
        ]
    )
    st.dataframe(before_after, use_container_width=True, hide_index=True)
    st.markdown(MADISON_EXPERIMENT_RESULT)


def render_research_appendix() -> None:
    st.header("Research Appendix: Modeling Workstream (Not Promoted)")
    st.warning(RESEARCH_APPENDIX_WARNING)

    st.subheader("1. Satellite Calibration Model")
    st.markdown(
        "Data-quality check of whether a satellite-observed proxy tracks the "
        "ground-monitor reading it's meant to stand in for, at Wisconsin AQS "
        "monitor sites. Train Jan 1–Sep 30, 2022; test Oct 1–Dec 31, 2022."
    )
    calibration_metrics = load_lur_csv("calibration_model_metrics.csv")
    st.dataframe(calibration_metrics, use_container_width=True, hide_index=True)
    st.error(CALIBRATION_SUMMARY)

    cal_cols = st.columns(2)
    for col, pollutant in zip(cal_cols, ["no2", "pm25"]):
        with col:
            st.image(
                str(calibration_plot_path(f"{pollutant}_predicted_vs_actual.png")),
                caption=f"{pollutant.upper()}: test-set predicted vs. actual",
                use_container_width=True,
            )

    st.divider()
    st.subheader("2. LUR Pilots: Madison PM2.5, Milwaukee NO2")
    st.markdown(
        "Multisource pilots adding meteorology, land-use, road-proximity, and "
        "cyclic time features to the own-pollutant satellite proxy, piloted "
        "city-by-city. Both pilots beat baselines in a single Jan–Sep/Oct–Dec "
        "split, but neither survives the full validation battery below."
    )

    madison_tab, milwaukee_tab = st.tabs(["Madison / PM2.5", "Milwaukee / NO2"])

    lur_model_metrics = load_lur_csv("lur_model_metrics.csv")
    lur_site_holdout = load_lur_csv("lur_site_holdout.csv")
    lur_rolling_cv = load_lur_csv("lur_rolling_cv.csv")
    lur_feature_importance = load_lur_csv("lur_feature_importance.csv")
    lur_ablation = load_lur_csv("lur_ablation.csv")

    with madison_tab:
        _render_pilot(
            lur_model_metrics, lur_rolling_cv, lur_site_holdout, lur_feature_importance, lur_ablation,
            "madison", "pm25", "madison_pm25",
        )

    with milwaukee_tab:
        _render_pilot(
            lur_model_metrics, lur_rolling_cv, lur_site_holdout, lur_feature_importance, lur_ablation,
            "milwaukee", "no2", "milwaukee_no2",
        )

    st.divider()
    st.subheader("3. Why each pilot fails (diagnosis)")
    st.markdown(
        "Before adding any more model complexity, both pilots were diagnosed "
        "further -- not just scored, but investigated for *why* they land "
        "where they do."
    )
    diag_col_a, diag_col_b = st.columns(2)
    with diag_col_a:
        _render_milwaukee_diagnosis(load_lur_csv("lur_site_holdout_variants.csv"))
    with diag_col_b:
        _render_madison_diagnosis(
            load_lur_csv("lur_fold_diagnostics_madison_pm25.csv"),
            load_lur_csv("lur_quantile_coverage.csv"),
        )

    st.divider()
    st.subheader("4. Pre-registered Madison PM2.5 experiment")
    _render_madison_experiment(load_lur_csv("lur_madison_experiment_results.csv"))

    st.divider()
    st.subheader("Promotion decision")
    st.dataframe(pd.DataFrame(LUR_PROMOTION_TABLE), use_container_width=True, hide_index=True)
    st.markdown(LUR_PROMOTION_VERDICT)

    st.divider()
    st.subheader("What this project does not show")
    st.markdown(
        "None of the following should be presented in the explorer, now or later, "
        "on the strength of the evidence gathered so far:"
    )
    for item in RESEARCH_APPENDIX_BOUNDARY:
        st.markdown(f"- {item}")

    st.caption(OSM_ATTRIBUTION)
