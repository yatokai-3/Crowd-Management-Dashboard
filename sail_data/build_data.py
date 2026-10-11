"""
Build all processed data files in one go.

Run this file with the run button (VS Code / Cursor), or in the terminal:

    python build_data.py

It creates, in data/processed/:
    tomtom_3min.parquet          cleaned TomTom traffic, 3-minute intervals
    roads.parquet                NWB road network with locations (if the NWB files are present)

Files that already exist are skipped, so running it again is quick. To rebuild
everything from the raw data (e.g. if a file is damaged), set REBUILD = True.

Requirements: the raw data must be found (check with `python -m src.config`)
and the packages installed (`pip install -r requirements.txt`).
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
REBUILD = False        # True = rebuild files even if they already exist
FREQ = "3min"          # time interval for the TomTom data

# Make `src` importable no matter where this file is run from.
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import check_data, raw_path, RAW_DIR  # noqa: E402
from src import tomtom, roads  # noqa: E402


def main() -> None:
    print("=" * 70)
    print("Step 0: checking the raw data")
    print("=" * 70)
    check_data()
    if not raw_path("tomtom").exists():
        sys.exit("\nThe raw TomTom file was not found. See README_DATA.md, section 1.")

    print("\n" + "=" * 70)
    print("Step 1: TomTom traffic data")
    print("=" * 70)
    tt_file = tomtom.processed_path(FREQ)
    if tt_file.exists() and not REBUILD:
        print(f"Already exists, skipped: {tt_file.name}  (set REBUILD = True to rebuild)")
    else:
        tomtom.process_tomtom(freq=FREQ)

    print("\n" + "=" * 70)
    print("Step 2: NWB road network")
    print("=" * 70)
    has_nwb = raw_path("nwb_roads").exists() or any(RAW_DIR.rglob(roads.SHP_NAME))
    if not has_nwb:
        print("NWB road files not found in the raw-data folder, skipped.")
    elif roads.ROADS_FILE.exists() and not REBUILD:
        print(f"Already exists, skipped: {roads.ROADS_FILE.name}  (set REBUILD = True to rebuild)")
    else:
        roads.process_roads()

    print("\nAll done. Load the data with:")
    print("    from src.tomtom import load_tomtom")
    print("    from src.roads import load_roads")


if __name__ == "__main__":
    main()
