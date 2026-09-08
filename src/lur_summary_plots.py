"""Two negative-results visuals requested for the case-study writeup, built
from already-computed CSVs (no re-modeling): (1) an ablation bar chart
showing each feature family's R2 contribution, highlighting how little the
satellite family adds; (2) a nominal-vs-empirical prediction-interval
coverage chart.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
PLOTS_DIR = PROCESSED_DIR / "lur_plots"


def plot_ablation_chart() -> None:
    df = pd.read_csv(PROCESSED_DIR / "lur_ablation.csv")
    pilots = df[["city", "pollutant"]].drop_duplicates().values.tolist()

    fig, axes = plt.subplots(1, len(pilots), figsize=(6 * len(pilots), 5), sharey=True)
    if len(pilots) == 1:
        axes = [axes]

    for ax, (city, pollutant) in zip(axes, pilots):
        subset = df[(df["city"] == city) & (df["pollutant"] == pollutant)].copy()
        subset["label"] = subset["ablated_family"].replace(
            {"none (full model)": "Full model", "satellite": "− satellite",
             "meteorology": "− meteorology", "land_use": "− land use", "time": "− time"}
        )
        order = ["Full model", "− satellite", "− meteorology", "− land use", "− time"]
        subset = subset.set_index("label").reindex(order).reset_index()
        colors = ["#4C72B0" if lbl == "Full model" else ("#DD8452" if lbl == "− satellite" else "#55A868")
                  for lbl in subset["label"]]
        ax.bar(subset["label"], subset["r2"], color=colors)
        ax.axhline(0, color="k", linewidth=0.8)
        ax.set_title(f"{city.title()} {pollutant.upper()}")
        ax.set_ylabel("Test-set R²")
        ax.tick_params(axis="x", rotation=30)

    fig.suptitle("Feature-family ablation: satellite contributes almost nothing")
    plt.figtext(0.01, 0.01, "Calibration check: not a health/risk estimate.", fontsize=7, color="dimgray")
    fig.tight_layout()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOTS_DIR / "ablation_satellite_contribution.png", dpi=150)
    plt.close(fig)


def plot_coverage_chart() -> None:
    df = pd.read_csv(PROCESSED_DIR / "lur_quantile_coverage.csv")

    fig, ax = plt.subplots(figsize=(7, 5))
    labels = [f"{row.city.title()}\n{row.pollutant.upper()}" for row in df.itertuples()]
    x = range(len(df))
    ax.bar(x, df["overall_empirical_coverage"] * 100, color="#C44E52", label="Empirical coverage")
    ax.axhline(80, color="k", linestyle="--", linewidth=1.5, label="Nominal coverage (80%)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Coverage of true value within 10-90th percentile interval (%)")
    ax.set_ylim(0, 100)
    ax.set_title("Prediction intervals are overconfident: nominal vs. empirical coverage")
    ax.legend()
    plt.figtext(0.01, 0.01, "Calibration check: not a health/risk estimate.", fontsize=7, color="dimgray")
    fig.tight_layout()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOTS_DIR / "quantile_coverage_nominal_vs_empirical.png", dpi=150)
    plt.close(fig)


def main() -> None:
    plot_ablation_chart()
    print(f"Wrote {PLOTS_DIR / 'ablation_satellite_contribution.png'}")
    plot_coverage_chart()
    print(f"Wrote {PLOTS_DIR / 'quantile_coverage_nominal_vs_empirical.png'}")


if __name__ == "__main__":
    main()
