"""Diagnoses whether static land-use features (impervious_pct especially)
are acting as a portable land-use relationship or as a de facto site
identifier: (a) per-site descriptive stats for the static features, (b)
partial dependence + SHAP dependence for impervious_pct (and a top
meteorological feature for contrast), points colored by site_id. A
step-like separation by site in these plots -- rather than a smooth
within-site spread -- is the signature of the model leaning on identity.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import shap
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import PartialDependenceDisplay

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT
from src.lur_model import PILOTS, prepare_features, temporal_split

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
PLOTS_DIR = PROCESSED_DIR / "lur_plots"

STATIC_COLS = ["impervious_pct", "elevation_m", "dist_to_major_road_km"]


def site_distribution_table(city: str, pollutant: str) -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
    multiscale_path = PROCESSED_DIR / f"lur_multiscale_features_{city}.parquet"
    cols = STATIC_COLS.copy()
    if multiscale_path.exists():
        multiscale = pd.read_parquet(multiscale_path)
        df = df.merge(multiscale, on="site_id", how="left", suffixes=("", "_multiscale"))
        cols += [c for c in multiscale.columns if c != "site_id"]

    summary = df.groupby("site_id")[cols].first().reset_index()
    summary["city"] = city
    summary["pollutant"] = pollutant
    return summary


def plot_dependence_by_site(city: str, pollutant: str) -> None:
    df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
    df = df.dropna(subset=["concentration", "temperature_2m"])
    train, test = temporal_split(df)

    other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
    satellite_col = f"satellite_{pollutant}"
    cross_col = f"cross_satellite_{other_pollutant}"
    train_feat, test_feat, feature_cols = prepare_features(train, test, satellite_col, cross_col)

    x_train = train_feat[feature_cols].to_numpy()
    y_train = train_feat["concentration"].to_numpy()
    model = HistGradientBoostingRegressor(max_depth=4, random_state=0)
    model.fit(x_train, y_train)

    top_weather_feature = "boundary_layer_height" if "boundary_layer_height" in feature_cols else feature_cols[0]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    PartialDependenceDisplay.from_estimator(
        model, x_train, features=[feature_cols.index("impervious_pct")], feature_names=feature_cols, ax=axes[0]
    )
    axes[0].set_title("PDP: impervious_pct")
    PartialDependenceDisplay.from_estimator(
        model, x_train, features=[feature_cols.index(top_weather_feature)], feature_names=feature_cols, ax=axes[1]
    )
    axes[1].set_title(f"PDP: {top_weather_feature}")
    fig.suptitle(f"{city.title()} {pollutant.upper()}: partial dependence (training data)")
    fig.tight_layout()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOTS_DIR / f"{city}_{pollutant}_pdp.png", dpi=150)
    plt.close(fig)

    explainer = shap.TreeExplainer(model)
    x_all = pd.concat([train_feat, test_feat])[feature_cols].to_numpy()
    site_ids_all = pd.concat([train_feat, test_feat])["site_id"].to_numpy()
    shap_values = explainer(x_all)

    impervious_idx = feature_cols.index("impervious_pct")
    fig, ax = plt.subplots(figsize=(7, 5))
    unique_sites = sorted(set(site_ids_all))
    for site in unique_sites:
        mask = site_ids_all == site
        ax.scatter(
            x_all[mask, impervious_idx],
            shap_values.values[mask, impervious_idx],
            label=str(site),
            alpha=0.6,
            s=16,
        )
    ax.axhline(0, color="k", linestyle="--", linewidth=1)
    ax.set_xlabel("impervious_pct")
    ax.set_ylabel("SHAP value (impact on prediction)")
    ax.set_title(f"{city.title()} {pollutant.upper()}: SHAP dependence for impervious_pct, colored by site")
    ax.legend(title="site_id")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"{city}_{pollutant}_shap_dependence_by_site.png", dpi=150)
    plt.close(fig)


def main() -> None:
    for city, pollutant in PILOTS:
        summary = site_distribution_table(city, pollutant)
        print(f"\n{city}/{pollutant} per-site static feature summary:")
        print(summary.to_string(index=False))

        out_path = PROCESSED_DIR / f"lur_site_feature_distributions_{city}.csv"
        summary.to_csv(out_path, index=False)
        print(f"Wrote {out_path}")

        plot_dependence_by_site(city, pollutant)
        print(f"  -> {PLOTS_DIR / f'{city}_{pollutant}_pdp.png'}")
        print(f"  -> {PLOTS_DIR / f'{city}_{pollutant}_shap_dependence_by_site.png'}")


if __name__ == "__main__":
    main()
