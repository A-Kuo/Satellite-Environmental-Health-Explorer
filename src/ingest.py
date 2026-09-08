"""Downloads Stage One raw source files into data/raw/ and logs provenance.

Files here are never modified after download. Cleaning happens in the
clean_*.py / spatial_join.py modules, which read from data/raw/.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
METADATA_DIR = REPO_ROOT / "data" / "metadata"
INGEST_LOG = METADATA_DIR / "ingest_log.csv"

SVI_URL = "https://svi.cdc.gov/Documents/Data/2022/csv/states/Wisconsin.csv"
TIGER_TRACT_URL = "https://www2.census.gov/geo/tiger/TIGER2022/TRACT/tl_2022_55_tract.zip"
# EJScreen 2.3 was removed from EPA's own site in Feb 2025 (see methodology.md).
# Sourced instead from the Harvard Dataverse mirror, doi:10.7910/DVN/RLR5AX.
EJSCREEN_URL = "https://dataverse.harvard.edu/api/access/datafile/10775973"
DNR_MONITORS_QUERY_URL = (
    "https://dnrmaps.wi.gov/arcgis/rest/services/AM_WARP_MAP/AM_MONITORS_WTM_Int/"
    "MapServer/0/query"
)
COUNTY_FIPS_URL = "https://www2.census.gov/geo/docs/reference/codes2020/cou/st55_wi_cou2020.txt"

SOURCES = [
    {
        "filename": "svi_2022_wisconsin.csv",
        "url": SVI_URL,
        "description": "CDC/ATSDR SVI 2022, Wisconsin, census tract",
    },
    {
        "filename": "tl_2022_55_tract.zip",
        "url": TIGER_TRACT_URL,
        "description": "Census TIGER/Line 2022 Wisconsin census tract geometries",
    },
    {
        "filename": "ejscreen_2024_tract_statepct_national.csv",
        "url": EJSCREEN_URL,
        "description": (
            "EJScreen 2.3 tract-level indicators (national), Harvard Dataverse "
            "mirror of EPA data removed from epa.gov in Feb 2025"
        ),
    },
    {
        "filename": "st55_wi_cou2020.txt",
        "url": COUNTY_FIPS_URL,
        "description": "Census Bureau 2020 county FIPS-to-name reference, Wisconsin",
    },
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path, headers: dict | None = None) -> None:
    headers = headers or {"User-Agent": "wisconsin-environmental-health-explorer/0.1"}
    with requests.get(url, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)


def download_dnr_monitors(dest: Path) -> None:
    """Snapshots the WI DNR 'All Monitors' air monitoring layer as raw GeoJSON."""
    params = {"where": "1=1", "outFields": "*", "f": "geojson"}
    resp = requests.get(DNR_MONITORS_QUERY_URL, params=params, timeout=60)
    resp.raise_for_status()
    dest.write_text(resp.text, encoding="utf-8")


def append_ingest_log(rows: list[dict]) -> None:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = INGEST_LOG.exists()
    with open(INGEST_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["filename", "source_url", "description", "downloaded_at_utc", "sha256"]
        )
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    log_rows = []

    for source in SOURCES:
        dest = RAW_DIR / source["filename"]
        print(f"Downloading {source['filename']} ...")
        download_file(source["url"], dest)
        log_rows.append(
            {
                "filename": source["filename"],
                "source_url": source["url"],
                "description": source["description"],
                "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                "sha256": sha256_of(dest),
            }
        )
        print(f"  -> {dest} ({dest.stat().st_size:,} bytes)")

    dnr_dest = RAW_DIR / "wi_dnr_air_monitors_snapshot.geojson"
    print("Downloading WI DNR air monitors snapshot ...")
    download_dnr_monitors(dnr_dest)
    log_rows.append(
        {
            "filename": dnr_dest.name,
            "source_url": DNR_MONITORS_QUERY_URL,
            "description": "WI DNR Air Management Data Viewer, 'All Monitors' layer snapshot",
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": sha256_of(dnr_dest),
        }
    )
    print(f"  -> {dnr_dest} ({dnr_dest.stat().st_size:,} bytes)")

    append_ingest_log(log_rows)
    print(f"\nLogged {len(log_rows)} downloads to {INGEST_LOG}")


if __name__ == "__main__":
    main()
