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
    OSM_ATTRIBUTION,
    RESEARCH_APPENDIX_BOUNDARY,
    RESEARCH_APPENDIX_WARNING,
)


def _render_pilot(
    lur_model_metrics: pd.DataFrame,
    lur_rolling_cv: pd.DataFrame,
    lur_site_holdout: pd.DataFrame,
    lur_feature_importance: pd.DataFrame,
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

    with madison_tab:
        _render_pilot(
            lur_model_metrics, lur_rolling_cv, lur_site_holdout, lur_feature_importance,
            "madison", "pm25", "madison_pm25",
        )

    with milwaukee_tab:
        _render_pilot(
            lur_model_metrics, lur_rolling_cv, lur_site_holdout, lur_feature_importance,
            "milwaukee", "no2", "milwaukee_no2",
        )

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
