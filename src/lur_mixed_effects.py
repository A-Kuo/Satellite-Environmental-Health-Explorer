"""Mixed-effects diagnostic (site random intercept + fixed weather/land-use
effects) to quantify how much outcome variance is between-site (identity)
vs. explained by shared predictors -- a formal complement to the SHAP-by-site
step pattern and the impervious-ablation result.

This is diagnostic only. It is NOT a model to deploy at unmonitored sites --
a random intercept is, by definition, only estimable for sites already seen
in training, which is exactly the limitation this whole diagnosis is about.

Caveat stated plainly: with only 2-3 monitor sites, the between-site
variance *component* itself is estimated from just 2-3 groups (even though
each group has hundreds of daily observations) -- the ICC below should be
read as directional, not a precise estimate.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf

from src.ingest_lur_features import CROSS_SATELLITE_POLLUTANT
from src.lur_model import PILOTS

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

FIXED_EFFECTS = [
    "temperature_2m", "relative_humidity_pct", "wind_speed_ms",
    "total_precipitation", "boundary_layer_height",
]


def fit_mixed_model(df: pd.DataFrame, satellite_col: str) -> tuple[object, dict]:
    cols_needed = ["concentration", "site_id", satellite_col, *FIXED_EFFECTS]
    model_df = df.dropna(subset=cols_needed).copy()
    model_df["site_id"] = model_df["site_id"].astype(str)

    formula = f"concentration ~ {' + '.join(FIXED_EFFECTS)} + {satellite_col}"
    model = smf.mixedlm(formula, data=model_df, groups=model_df["site_id"])
    result = model.fit()

    group_var = float(result.cov_re.iloc[0, 0])
    residual_var = float(result.scale)
    icc = group_var / (group_var + residual_var)

    summary = {
        "n_obs": len(model_df),
        "n_groups": model_df["site_id"].nunique(),
        "group_variance": group_var,
        "residual_variance": residual_var,
        "icc_between_site_share": icc,
    }
    return result, summary


def main() -> None:
    all_rows = []
    for city, pollutant in PILOTS:
        df = pd.read_parquet(PROCESSED_DIR / f"lur_dataset_{city}_{pollutant}.parquet")
        other_pollutant = CROSS_SATELLITE_POLLUTANT[pollutant]
        satellite_col = f"satellite_{pollutant}"

        result, summary = fit_mixed_model(df, satellite_col)
        summary["city"] = city
        summary["pollutant"] = pollutant
        for fe_name, coef in result.fe_params.items():
            summary[f"coef_{fe_name}"] = coef
        all_rows.append(summary)

        print(f"\n{city}/{pollutant}: mixed-effects diagnostic (n_groups={summary['n_groups']}, n_obs={summary['n_obs']})")
        print(f"  Between-site variance share (ICC): {summary['icc_between_site_share']:.1%}")
        print(f"  (caveat: estimated from only {summary['n_groups']} groups -- directional, not precise)")
        print(result.summary().tables[1])

    out_df = pd.DataFrame(all_rows)
    out_path = PROCESSED_DIR / "lur_mixed_effects.csv"
    out_df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
