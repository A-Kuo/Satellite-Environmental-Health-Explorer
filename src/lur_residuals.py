"""Residual diagnostics on the standard Jan-Sep/Oct-Dec test set: residual
vs. predicted, residual vs. observed, residuals by site, residuals by
season. Whatever bias shows up gets written into the summary table and the
methodology doc, not smoothed over.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT
from src.lur_model import PILOTS, SEASON_MAP, prepare_features, temporal_split

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
PLOTS_DIR = PROCESSED_DIR / "lur_plots"


def plot_diagnostics(city, pollutant, test: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 9))

    axes[0, 0].scatter(test["predicted"], test["residual"], alpha=0.5, s=14)
    axes[0, 0].axhline(0, color="k", linestyle="--", linewidth=1)
    axes[0, 0].set_xlabel("Predicted")
    axes[0, 0].set_ylabel("Residual (observed - predicted)")
    axes[0, 0].set_title("Residual vs. predicted")

    axes[0, 1].scatter(test["concentration"], test["residual"], alpha=0.5, s=14)
    axes[0, 1].axhline(0, color="k", linestyle="--", linewidth=1)
    axes[0, 1].set_xlabel("Observed")
    axes[0, 1].set_ylabel("Residual (observed - predicted)")
    axes[0, 1].set_title("Residual vs. observed")

    test.boxplot(column="residual", by="site_id", ax=axes[1, 0])
    axes[1, 0].axhline(0, color="k", linestyle="--", linewidth=1)
    axes[1, 0].set_xlabel("Site")
    axes[1, 0].set_ylabel("Residual")
    axes[1, 0].set_title("Residuals by site")

    season_order = ["winter", "spring", "summer", "fall"]
    test.boxplot(column="residual", by="season", ax=axes[1, 1])
    axes[1, 1].axhline(0, color="k", linestyle="--", linewidth=1)
    axes[1, 1].set_xlabel("Season")
    axes[1, 1].set_ylabel("Residual")
    axes[1, 1].set_title("Residuals by season")

    fig.suptitle(f"{city.title()} {pollutant.upper()}: residual diagnostics (test set)")
    plt.figtext(0.01, 0.01, "Calibration check: not a health/risk estimate.", fontsize=7, color="dimgray")
    fig.tight_layout()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOTS_DIR / f"{city}_{pollutant}_residual_diagnostics.png", dpi=150)
    plt.close(fig)


def main() -> None:
    all_summary_rows = []
    for city, pollutant in PILOTS:
        df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
        df = df.dropna(subset=["concentration", "temperature_2m"])
        train, test = temporal_split(df)

        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        satellite_col = f"satellite_{pollutant}"
        cross_col = f"cross_satellite_{other_pollutant}"
        train_feat, test_feat, feature_cols = prepare_features(train, test, satellite_col, cross_col)

        model = HistGradientBoostingRegressor(max_depth=4, random_state=0)
        model.fit(train_feat[feature_cols].to_numpy(), train_feat["concentration"].to_numpy())
        test_feat["predicted"] = model.predict(test_feat[feature_cols].to_numpy())
        test_feat["residual"] = test_feat["concentration"] - test_feat["predicted"]
        test_feat["season"] = test_feat["date"].dt.month.map(SEASON_MAP)

        plot_diagnostics(city, pollutant, test_feat)

        by_site = test_feat.groupby("site_id")["residual"].agg(["mean", "std", "count"]).reset_index()
        by_site["group_type"] = "site"
        by_site = by_site.rename(columns={"site_id": "group"})

        by_season = test_feat.groupby("season")["residual"].agg(["mean", "std", "count"]).reset_index()
        by_season["group_type"] = "season"
        by_season = by_season.rename(columns={"season": "group"})

        summary = pd.concat([by_site, by_season], ignore_index=True)
        summary["city"] = city
        summary["pollutant"] = pollutant
        all_summary_rows.append(summary)

        print(f"\n{city}/{pollutant} residual summary:")
        print(summary[["group_type", "group", "mean", "std", "count"]].to_string(index=False))

    summary_df = pd.concat(all_summary_rows, ignore_index=True)
    out_path = PROCESSED_DIR / "lur_residual_summary.csv"
    summary_df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
