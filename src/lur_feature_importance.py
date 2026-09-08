"""Permutation importance and SHAP summaries for the candidate
HistGradientBoostingRegressor models, on the held-out Oct-Dec test set.

The point is a sanity check, not a leaderboard: does the model lean on
plausible physical/urban-form signal, or on something like a missing-value
flag that accidentally encodes season or location?
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import shap
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT
from src.lur_model import PILOTS, prepare_features, temporal_split

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
PLOTS_DIR = PROCESSED_DIR / "lur_plots"


def main() -> None:
    all_rows = []
    for city, pollutant in PILOTS:
        df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
        df = df.dropna(subset=["concentration", "temperature_2m"])
        train, test = temporal_split(df)

        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        satellite_col = f"satellite_{pollutant}"
        cross_col = f"cross_satellite_{other_pollutant}"
        train_feat, test_feat, feature_cols = prepare_features(train, test, satellite_col, cross_col)

        x_train, y_train = train_feat[feature_cols].to_numpy(), train_feat["concentration"].to_numpy()
        x_test, y_test = test_feat[feature_cols].to_numpy(), test_feat["concentration"].to_numpy()

        model = HistGradientBoostingRegressor(max_depth=4, random_state=0)
        model.fit(x_train, y_train)

        perm = permutation_importance(model, x_test, y_test, n_repeats=30, random_state=0, scoring="r2")
        for i, col in enumerate(feature_cols):
            all_rows.append(
                {
                    "city": city,
                    "pollutant": pollutant,
                    "feature": col,
                    "perm_importance_mean": perm.importances_mean[i],
                    "perm_importance_std": perm.importances_std[i],
                }
            )

        print(f"\n{city}/{pollutant}: top 8 features by permutation importance")
        top = sorted(zip(feature_cols, perm.importances_mean), key=lambda t: -t[1])[:8]
        for col, imp in top:
            print(f"  {col}: {imp:.4f}")

        explainer = shap.TreeExplainer(model)
        shap_values = explainer(x_test)
        shap_values.feature_names = feature_cols

        PLOTS_DIR.mkdir(parents=True, exist_ok=True)
        plt.figure()
        shap.summary_plot(shap_values, x_test, feature_names=feature_cols, show=False)
        plt.title(f"{city.title()} {pollutant.upper()}: SHAP feature contributions")
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / f"{city}_{pollutant}_shap_summary.png", dpi=150)
        plt.close()

    importance_df = pd.DataFrame(all_rows)
    out_path = PROCESSED_DIR / "lur_feature_importance.csv"
    importance_df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
