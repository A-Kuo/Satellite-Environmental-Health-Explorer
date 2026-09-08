"""Produces the two Stage One static exploratory plots: a choropleth of the
Wisconsin-relative PM2.5 percentile, and a scatterplot of PM2.5 vs. overall
SVI percentile. matplotlib + geopandas only — no folium/streamlit (Stage Two).
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
SCREENING_VIEW_PATH = PROCESSED_DIR / "tract_screening_view.parquet"

CHOROPLETH_OUT = PROCESSED_DIR / "map_pm25_percentile_choropleth.png"
SCATTER_OUT = PROCESSED_DIR / "scatter_pm25_vs_svi.png"

DISCLAIMER = (
    "Screening tool: descriptive indicators only, not a measure of risk or harm."
)


def plot_choropleth(gdf: gpd.GeoDataFrame, out_path: Path = CHOROPLETH_OUT) -> None:
    fig, ax = plt.subplots(figsize=(8, 8))
    gdf.plot(
        column="indicator_percentile_wi",
        cmap="YlOrRd",
        legend=True,
        legend_kwds={"label": "PM2.5 percentile (Wisconsin-relative)"},
        missing_kwds={"color": "lightgrey", "label": "No data"},
        ax=ax,
    )
    ax.set_title("Wisconsin Census Tracts: PM2.5 Annual Concentration Percentile (2022)")
    ax.set_axis_off()
    ax.annotate(DISCLAIMER, xy=(0.01, 0.01), xycoords="figure fraction", fontsize=7, color="dimgray")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_scatter(gdf: gpd.GeoDataFrame, out_path: Path = SCATTER_OUT) -> None:
    fig, ax = plt.subplots(figsize=(7, 6))
    valid = gdf.dropna(subset=["indicator_value", "overall_svi_percentile"])
    ax.scatter(valid["indicator_value"], valid["overall_svi_percentile"], alpha=0.5, s=14)
    ax.set_xlabel("PM2.5 annual concentration (µg/m³, modeled)")
    ax.set_ylabel("Overall SVI percentile (Wisconsin context)")
    ax.set_title("PM2.5 vs. Social Vulnerability Index, Wisconsin Census Tracts (2022)")
    ax.annotate(DISCLAIMER, xy=(0.01, 0.01), xycoords="figure fraction", fontsize=7, color="dimgray")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    gdf = gpd.read_parquet(SCREENING_VIEW_PATH)
    plot_choropleth(gdf)
    print(f"Wrote {CHOROPLETH_OUT}")
    plot_scatter(gdf)
    print(f"Wrote {SCATTER_OUT}")


if __name__ == "__main__":
    main()
