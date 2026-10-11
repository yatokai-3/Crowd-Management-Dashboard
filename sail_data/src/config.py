"""
Central place for all data paths, so every teammate's code finds the data the
same way, wherever the files are stored on their own computer.

How the raw-data folder is chosen (first match wins):

  1. Environment variable SAIL_RAW_DIR
  2. A personal file `data_location.txt` in the repository root, containing one
     line with the full path to your raw-data folder. This file is in .gitignore,
     so everyone can have their own without conflicts.
  3. Default: <repository>/data/raw/

Check your setup with:   python -m src.config
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_LOCATION_FILE = REPO_ROOT / "data_location.txt"


def _raw_dir() -> Path:
    env = os.environ.get("SAIL_RAW_DIR")
    if env:
        return Path(env).expanduser()
    if _LOCATION_FILE.exists():
        text = _LOCATION_FILE.read_text().strip().strip('"').strip("'")
        if text:
            return Path(text).expanduser()
    return REPO_ROOT / "data" / "raw"


RAW_DIR = _raw_dir()
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# File names exactly as provided by the course. Use these names everywhere.
RAW_FILES = {
    "tomtom": "TomTom_data_20-24Aug2025.csv",
    "lvma_flow": "SAIL2025_LVMA_data_3min_20August-25August2025_flow.csv",
    "sensor_locations": "sensor-location.xlsx",
    "vessels": "Vesselposition_data_20-24Aug2025.csv",
    "nwb_roads": "NWB_roads.zip",
}


# Shared time grid. Every dataset is put on the same 3-minute intervals, so tables
# can be joined on `time`. Convention: `time` = START of the interval, local time.
TIMEZONE = "Europe/Amsterdam"
INTERVAL = "3min"


def to_interval(timestamps, freq: str = INTERVAL, label: str = "start"):
    """
    Put timestamps on the shared time grid (Europe/Amsterdam, interval start).

    label="start": the raw timestamp lies inside the interval (e.g. TomTom snapshots).
    label="end":   the raw timestamp marks the END of an interval (e.g. a sensor that
                   reports the count of the 3 minutes before it). It is shifted back
                   one interval so it gets the same `time` as the other datasets.
    """
    import pandas as pd

    try:
        t = pd.to_datetime(pd.Series(timestamps), format="ISO8601")
    except ValueError:  # timestamps with different UTC offsets
        t = pd.to_datetime(pd.Series(timestamps), format="ISO8601", utc=True)
    # Timestamps without a timezone are assumed to be in Amsterdam local time.
    # CHECK this for every new dataset: if they are in UTC, localize to "UTC" first.
    t = t.dt.tz_localize(TIMEZONE) if t.dt.tz is None else t.dt.tz_convert(TIMEZONE)
    if label == "end":
        t = t - pd.Timedelta(freq)
    return t.dt.floor(freq)


# SAIL event area (ASSUMPTION, agreed in the group as a working definition):
# everything within SAIL_AREA_BUFFER_M metres of the IJ waterfront between the
# Houthavens/NDSM in the west and the eastern docks (Java-eiland/KNSM) in the
# east, where the ships were moored. Points are (longitude, latitude).
SAIL_AREA_WATERFRONT = [
    (4.862, 52.394),   # Houthavens
    (4.880, 52.391),   # Westerdok
    (4.900, 52.383),   # Centraal Station waterfront
    (4.915, 52.379),   # Oosterdok / Passenger Terminal
    (4.935, 52.378),   # Java-eiland
    (4.952, 52.376),   # KNSM-eiland
]
SAIL_AREA_EXTRA_POINTS = [(4.893, 52.401)]   # NDSM wharf (north bank)
SAIL_AREA_BUFFER_M = 750                     # 750 m each side: a ~1.5 km wide zone


def raw_path(name: str) -> Path:
    """Full path to a raw dataset, e.g. raw_path('tomtom')."""
    if name not in RAW_FILES:
        raise KeyError(f"Unknown dataset '{name}'. Options: {list(RAW_FILES)}")
    return RAW_DIR / RAW_FILES[name]


def check_data() -> None:
    """Print which raw files are found, so setup problems are easy to spot."""
    print(f"Raw data folder: {RAW_DIR}")
    if not RAW_DIR.exists():
        print("  -> this folder does not exist. See README_DATA.md, section 1.")
        return
    for name, fname in RAW_FILES.items():
        p = RAW_DIR / fname
        if p.exists():
            status = f"found ({p.stat().st_size / 1e6:,.0f} MB)"
        elif name == "nwb_roads" and any(RAW_DIR.rglob("wegen_in_out.shp")):
            fname, status = "NWB_roads/ (unzipped folder)", "found"
        else:
            status = "MISSING"
        print(f"  {name:<17} {fname:<58} {status}")


if __name__ == "__main__":
    check_data()
