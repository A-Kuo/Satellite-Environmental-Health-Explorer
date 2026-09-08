"""Fits and evaluates satellite-vs-ground calibration models per pollutant.

For each pollutant, splits its calibration dataset temporally (train on
Jan-Sep 2022, test on Oct-Dec 2022, across all of that pollutant's WI
monitor sites) and compares a linear regression against a random forest,
reporting held-out (test-set-only) R^2/RMSE/MAE for both -- this is a
data-quality calibration check, not a health or risk model. See
methodology.md for why the small number of WI monitors (3-20 depending on
pollutant) limits this to temporal validation at known sites rather than
spatial generalization.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
PLOTS_DIR = PROCESSED_DIR / "calibration_plots"

POLLUTANTS = ["no2", "so2", "co", "pm25"]
TRAIN_TEST_SPLIT_DATE = "2022-10-01"

MODELS = {
    "linear_regression": LinearRegression(),
    "random_forest": RandomForestRegressor(n_estimators=200, max_depth=6, random_state=0),
}

DISCLAIMER = "Calibration check: satellite proxy vs. ground monitor, not a health/risk estimate."


def temporal_split(dataset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dataset = dataset.dropna(subset=["satellite_value", "concentration"])
    train = dataset[dataset["date"] < TRAIN_TEST_SPLIT_DATE]
    test = dataset[dataset["date"] >= TRAIN_TEST_SPLIT_DATE]
    return train, test


def fit_and_evaluate(pollutant: str, train: pd.DataFrame, test: pd.DataFrame) -> list[dict]:
    x_train = train[["satellite_value"]].to_numpy()
    y_train = train["concentration"].to_numpy()
    x_test = test[["satellite_value"]].to_numpy()
    y_test = test["concentration"].to_numpy()

    results = []
    best_model_name, best_r2, best_preds = None, float("-inf"), None

    for model_name, model in MODELS.items():
        model.fit(x_train, y_train)
        preds = model.predict(x_test)

        r2 = r2_score(y_test, preds)
        rmse = mean_squared_error(y_test, preds) ** 0.5
        mae = mean_absolute_error(y_test, preds)

        results.append(
            {
                "pollutant": pollutant,
                "model": model_name,
                "n_train": len(train),
                "n_test": len(test),
                "train_start": train["date"].min(),
                "train_end": train["date"].max(),
                "test_start": test["date"].min(),
                "test_end": test["date"].max(),
                "r2": r2,
                "rmse": rmse,
                "mae": mae,
            }
        )

        if r2 > best_r2:
            best_model_name, best_r2, best_preds = model_name, r2, preds

    plot_predicted_vs_actual(pollutant, best_model_name, y_test, best_preds, best_r2)
    return results


def plot_predicted_vs_actual(pollutant, model_name, y_test, preds, r2) -> None:
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_test, preds, alpha=0.5, s=14)
    lims = [min(y_test.min(), preds.min()), max(y_test.max(), preds.max())]
    ax.plot(lims, lims, "k--", linewidth=1, label="1:1")
    ax.set_xlabel(f"Ground-monitor {pollutant.upper()} (test set)")
    ax.set_ylabel(f"Satellite-calibrated prediction ({model_name})")
    ax.set_title(f"{pollutant.upper()} calibration: predicted vs. actual (test R²={r2:.2f})")
    ax.legend()
    ax.annotate(DISCLAIMER, xy=(0.01, 0.01), xycoords="figure fraction", fontsize=7, color="dimgray")
    fig.tight_layout()

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOTS_DIR / f"{pollutant}_predicted_vs_actual.png", dpi=150)
    plt.close(fig)


def main() -> None:
    all_results = []
    for pollutant in POLLUTANTS:
        dataset = pd.read_parquet(PROCESSED_DIR / f"calibration_dataset_{pollutant}.parquet")
        train, test = temporal_split(dataset)

        if len(train) < 10 or len(test) < 10:
            print(f"{pollutant}: insufficient data after split (train={len(train)}, test={len(test)}), skipping")
            continue

        results = fit_and_evaluate(pollutant, train, test)
        all_results.extend(results)
        for r in results:
            print(f"{pollutant} [{r['model']}]: test R2={r['r2']:.3f}, RMSE={r['rmse']:.3f}, MAE={r['mae']:.3f}")

    metrics_df = pd.DataFrame(all_results)
    out_path = PROCESSED_DIR / "calibration_model_metrics.csv"
    metrics_df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
