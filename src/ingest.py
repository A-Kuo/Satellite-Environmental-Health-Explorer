"""Downloads Stage One raw source files into data/raw/ and logs provenance.

Files here are never modified after download. Cleaning happens in the
clean_*.py / spatial_join.py modules, which read from data/raw/.

Per-state sources (SVI, TIGER tracts, county FIPS reference) are generated
from URL templates driven by src/states.py -- run with `--state <ABBR>` for
a state other than the default (Wisconsin). EJScreen is a single national
file, downloaded once regardless of state. Contextual monitor points no
longer come from a per-state agency download (see src/ingest_monitors.py,
which reads the already-cached national AQS daily files instead) -- this
module no longer downloads Wisconsin DNR's ArcGIS layer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.states import StateConfig, get_state

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
METADATA_DIR = REPO_ROOT / "data" / "metadata"
INGEST_LOG = METADATA_DIR / "ingest_log.csv"

TIGER_YEAR = 2022
SVI_YEAR = 2022

# EJScreen 2.3 was removed from EPA's own site in Feb 2025 (see methodology.md).
# Sourced instead from the Harvard Dataverse mirror, doi:10.7910/DVN/RLR5AX.
# National in scope -- every state's PM2.5 rows are in this one file.
EJSCREEN_URL = "https://dataverse.harvard.edu/api/access/datafile/10775973"
EJSCREEN_FILENAME = "ejscreen_2024_tract_statepct_national.csv"


def svi_url(state: StateConfig) -> str:
    return f"https://svi.cdc.gov/Documents/Data/{SVI_YEAR}/csv/states/{state.svi_name()}.csv"


def tiger_tract_url(state: StateConfig, year: int = TIGER_YEAR) -> str:
    return f"https://www2.census.gov/geo/tiger/TIGER{year}/TRACT/tl_{year}_{state.fips}_tract.zip"


def county_fips_url(state: StateConfig) -> str:
    return (
        "https://www2.census.gov/geo/docs/reference/codes2020/cou/"
        f"st{state.fips}_{state.abbr.lower()}_cou2020.txt"
    )


def state_sources(state: StateConfig) -> list[dict]:
    return [
        {
            "filename": f"svi_{SVI_YEAR}_{state.abbr.lower()}.csv",
            "url": svi_url(state),
            "description": f"CDC/ATSDR SVI {SVI_YEAR}, {state.name}, census tract",
        },
        {
            "filename": f"tl_{TIGER_YEAR}_{state.fips}_tract.zip",
            "url": tiger_tract_url(state),
            "description": f"Census TIGER/Line {TIGER_YEAR} {state.name} census tract geometries",
        },
        {
            "filename": f"st{state.fips}_{state.abbr.lower()}_cou2020.txt",
            "url": county_fips_url(state),
            "description": f"Census Bureau 2020 county FIPS-to-name reference, {state.name}",
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="WI", help="State abbreviation, e.g. WI, MN")
    args = parser.parse_args()
    state = get_state(args.state)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    log_rows = []
    sources = state_sources(state) + [
        {
            "filename": EJSCREEN_FILENAME,
            "url": EJSCREEN_URL,
            "description": (
                "EJScreen 2.3 tract-level indicators (national), Harvard Dataverse "
                "mirror of EPA data removed from epa.gov in Feb 2025"
            ),
        }
    ]

    for source in sources:
        dest = RAW_DIR / source["filename"]
        if dest.exists() and source["filename"] == EJSCREEN_FILENAME:
            print(f"Skipping {source['filename']} (already downloaded, national file)")
            continue
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

    if log_rows:
        append_ingest_log(log_rows)
        print(f"\nLogged {len(log_rows)} downloads to {INGEST_LOG}")


if __name__ == "__main__":
    main()
