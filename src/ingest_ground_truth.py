"""Downloads EPA AQS daily pre-generated files (no auth required) and cleans
them into per-pollutant ground-truth tables for the satellite calibration
model. Wisconsin only, 2022.
"""
from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
METADATA_DIR = REPO_ROOT / "data" / "metadata"
INGEST_LOG = METADATA_DIR / "ingest_log.csv"

YEAR = 2022
WI_STATE_CODE = 55

# AQS parameter code -> (pollutant label, expected unit)
POLLUTANTS = {
    "42602": ("NO2", "Parts per billion"),
    "42401": ("SO2", "Parts per billion"),
    "42101": ("CO", "Parts per million"),
    "88101": ("PM2.5", "Micrograms/cubic meter (LC)"),
}

AQS_URL_TEMPLATE = "https://aqs.epa.gov/aqsweb/airdata/daily_{param}_{year}.zip"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_aqs_zip(param: str, dest: Path) -> None:
    url = AQS_URL_TEMPLATE.format(param=param, year=YEAR)
    resp = requests.get(url, headers={"User-Agent": "wisconsin-environmental-health-explorer/0.1"}, timeout=180)
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def clean_pollutant(zip_path: Path, param: str) -> pd.DataFrame:
    pollutant_name, _unit = POLLUTANTS[param]
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, low_memory=False)

    wi = df[df["State Code"] == WI_STATE_CODE].copy()

    wi["site_id"] = (
        wi["State Code"].astype(str).str.zfill(2)
        + wi["County Code"].astype(str).str.zfill(3)
        + wi["Site Num"].astype(str).str.zfill(4)
    )
    wi["date"] = pd.to_datetime(wi["Date Local"])
    wi["pollutant"] = pollutant_name

    out = wi.rename(
        columns={
            "Latitude": "latitude",
            "Longitude": "longitude",
            "Arithmetic Mean": "concentration",
            "Units of Measure": "unit",
        }
    )[["site_id", "date", "pollutant", "latitude", "longitude", "concentration", "unit"]]

    # A site can have multiple POC (parameter occurrence code / instrument) readings
    # per day; average them to one concentration per site-day.
    out = (
        out.groupby(["site_id", "date", "pollutant", "latitude", "longitude", "unit"], as_index=False)[
            "concentration"
        ]
        .mean()
    )
    return out


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    log_rows = []

    for param, (pollutant_name, _unit) in POLLUTANTS.items():
        zip_dest = RAW_DIR / f"aqs_daily_{param}_{YEAR}.zip"
        print(f"Downloading AQS daily {pollutant_name} ({param}) for {YEAR} ...")
        download_aqs_zip(param, zip_dest)
        log_rows.append(
            {
                "filename": zip_dest.name,
                "source_url": AQS_URL_TEMPLATE.format(param=param, year=YEAR),
                "description": f"EPA AQS daily {pollutant_name} concentrations, all states, {YEAR}",
                "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                "sha256": sha256_of(zip_dest),
            }
        )
        print(f"  -> {zip_dest} ({zip_dest.stat().st_size:,} bytes)")

        cleaned = clean_pollutant(zip_dest, param)
        out_path = PROCESSED_DIR / f"ground_truth_{pollutant_name.lower().replace('.', '')}.parquet"
        cleaned.to_parquet(out_path, index=False)
        print(
            f"  -> {out_path} ({len(cleaned):,} site-day rows, "
            f"{cleaned['site_id'].nunique()} sites)"
        )

    file_exists = INGEST_LOG.exists()
    with open(INGEST_LOG, "a", newline="", encoding="utf-8") as f:
        import csv

        writer = csv.DictWriter(
            f, fieldnames=["filename", "source_url", "description", "downloaded_at_utc", "sha256"]
        )
        if not file_exists:
            writer.writeheader()
        writer.writerows(log_rows)
    print(f"\nLogged {len(log_rows)} downloads to {INGEST_LOG}")


if __name__ == "__main__":
    main()
