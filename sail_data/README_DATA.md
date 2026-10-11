# Working with the SAIL 2025 data

The course data is **not** in this repository: the files are too large for GitHub
(TomTom alone is ~4.3 GB) and course data should not be in a public repository.
Every teammate keeps their own copy, and the code finds it as described below.

## 1. One-time setup

```bash
pip install -r requirements.txt
```

Get the raw files from the course (Brightspace / shared drive). Keep the original
file names. Then choose **one** of these options:

**Option A (simplest): put the files in the repository's `data/raw/` folder**

```
data/raw/TomTom_data_20-24Aug2025.csv
data/raw/SAIL2025_LVMA_data_3min_20August-25August2025_flow.csv
data/raw/sensor-location.xlsx
data/raw/Vesselposition_data_20-24Aug2025.csv
data/raw/NWB_roads.zip
```

`data/` is in `.gitignore`, so nothing in it is ever pushed.

**Option B: keep the files wherever you like**

Create a file called `data_location.txt` in the repository root with one line: the
full path to the folder that holds the raw files, for example

```
/Users/yourname/Documents/SAIL_raw_data
```

`data_location.txt` is in `.gitignore`, so everyone can have their own path.

**Check your setup:**

```bash
python -m src.config
```

This lists every dataset as `found` or `MISSING`.

> Tip for Mac users: do not keep the 4.3 GB file in an iCloud-synced folder
> (Desktop / Documents with iCloud on). If it is only stored in the cloud, Python
> reads it very slowly or fails. Right-click → "Download now", or use another folder.

## 2. Build the cleaned data

**Easiest:** run `build_data.py` (run button, or `python build_data.py`). It checks
the raw data, then builds the TomTom file and the road network file. Files that
already exist are skipped; set `REBUILD = True` at the top to rebuild everything.

The individual steps, if you want to run them separately:

### 2a. The cleaned TomTom file (~2 minutes)

Run from the repository root:

```bash
python -m src.tomtom inspect      # check the raw file looks as expected
python -m src.tomtom process      # writes data/processed/tomtom_3min.parquet
```

Other interval lengths: `python -m src.tomtom process --freq 15min`.
If your computer runs out of memory, add `--chunk-rows 50`.

**Shortcut:** one person builds the processed file and uploads it to the team's
shared drive (not GitHub). Others download it into `data/processed/` and skip this step.

To verify the raw file (duplicates and gaps), run once:

```bash
python -m src.tomtom check        # writes data/processed/tomtom_check_report.txt
```

### 2b. The road network file (once, ~1 minute)

The TomTom table contains road IDs but no locations. The NWB road network adds
the location of every road, so traffic can be drawn on a map.

Put the NWB road files in your raw-data folder: either `NWB_roads.zip`, or the
unzipped folder with all five `wegen_in_out` files (.shp, .shx, .dbf, .prj, .cpg)
together. Then, **after** the TomTom file has been built:

```bash
python -m src.roads inspect       # columns, coordinate system, which column matches TomTom
python -m src.roads process       # writes data/processed/roads.parquet
python -m src.roads compare       # optional: what is the extra traffic value in the NWB file?
```

## 3. Use it in the notebook or dashboard

```python
from src.tomtom import load_tomtom

df = load_tomtom()                                                    # everything
sat = load_tomtom(start="2025-08-23 10:00", end="2025-08-23 22:00")   # Saturday daytime only
two = load_tomtom(road_ids=[210398154, 209398060])                   # selected segments
small = load_tomtom(columns=["time", "traffic_level"])               # only some columns
```

Notebooks in a subfolder (e.g. `notebooks/`) need the repository root on the path:

```python
import sys; sys.path.append("..")
from src.tomtom import load_tomtom
```

In Streamlit, cache the loading so it only runs once:

```python
import streamlit as st

@st.cache_data
def get_tomtom(start, end):
    return load_tomtom(start=start, end=end)
```

Column names and meanings: see `DATA_DICTIONARY.md`.
`traffic_level` = speed relative to normal speed (1.0 = normal, 0.0 = standstill).

Traffic on a map for one moment (join the two tables on `road_id`):

```python
from src.roads import load_roads
from src.tomtom import load_tomtom

roads = load_roads()                                                      # where the roads are
now = load_tomtom(start="2025-08-23 21:00", end="2025-08-23 21:03")       # traffic at 21:00
map_data = roads.merge(now, on="road_id")                                 # roads + traffic
map_data.plot(column="traffic_level", legend=True)
```

Raw file paths for other datasets: `from src.config import raw_path`, e.g.
`raw_path("lvma_flow")`.

The SAIL event area (shared definition, also for the pedestrian sensors):

```python
from src.roads import sail_area, road_ids_in_sail_area
area = sail_area()                  # polygon (GeoSeries, lat/lon)
ids = road_ids_in_sail_area()       # road segments inside it
```

The definition (waterfront points and the 750 m buffer) is in `src/config.py`.
Roads near any point: `road_ids_near(52.379, 4.900, 2000)` (within 2 km).

## 4. Road traffic visualisations

Car traffic figures (interactive map, SAIL area vs the rest of the city, difference
per day and hour, most slowed roads, road closures) are in
`road_traffic_visualisations/`. Run `road_traffic_figures.py`; see
`road_traffic_visualisations/README.md`.
