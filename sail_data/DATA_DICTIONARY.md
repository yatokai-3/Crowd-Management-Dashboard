# Data dictionary

Variable names and meanings for all cleaned datasets. Everyone uses these names in
the notebook and the dashboard, so code from different team members fits together.

**Conventions for all datasets**

- Column names: `snake_case`, English.
- Time: column `time`, timezone-aware, **Europe/Amsterdam** (local time during SAIL,
  UTC+02:00). Each row's `time` is the **start** of its interval.
- Time resolution: 3 minutes, matching the LVMA pedestrian data, so datasets can be
  joined on `time`. Use `to_interval()` from `src/config.py` to put any dataset on
  this grid.
- Cleaned files: Parquet format in `data/processed/` (fast, small, keeps data types).
- Raw files: never edited by hand and never pushed to GitHub.
- **SAIL event area** (working definition, an assumption): within 750 m of the IJ
  waterfront from the Houthavens/NDSM to the eastern docks (KNSM). Defined in
  `src/config.py`; use `sail_area()` / `road_ids_in_sail_area()` from `src/roads.py`
  so every dataset uses the same area.

---

## TomTom car traffic — `data/processed/tomtom_3min.parquet`

**Source:** `TomTom_data_20-24Aug2025.csv` (course data, ~4.3 GB), 20–24 August 2025.
**Created by:** `python -m src.tomtom process` (or `build_data.py`)
**Load with:** `from src.tomtom import load_tomtom`
**One row =** one road segment in one 3-minute interval.

| Column | Type | Unit | Description |
|---|---|---|---|
| `time` | datetime (Europe/Amsterdam) | – | Start of the 3-minute interval. |
| `date` | string `YYYY-MM-DD` | – | Date of `time`, for filtering per event day. |
| `hour` | int8 | 0–23 | Hour of `time`, for hourly summaries. |
| `road_id` | int64 | – | Road segment ID (`id` in the raw file). Joins to `road_id` in `roads.parquet`. |
| `traffic_level` | float32 | 0–1 | Average **speed relative to normal (free-flow) speed** over the snapshots in the interval. 1.0 = normal speed, 0.5 = half, 0.0 = standstill or closed (see notes). |
| `level_min` | float32 | 0–1 | Lowest value of any snapshot in the interval. |
| `level_max` | float32 | 0–1 | Highest value of any snapshot in the interval. |
| `n_obs` | int16 | count | Number of snapshots averaged (usually 4). |

**Meaning of `traffic_level`.** TomTom's documentation defines a property with
exactly this name, 0.00–1.00 in its "relative" style: "the speed relative to
free-flow, highlighting areas of congestion"
([source](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/vector-flow-tiles)).
The course README does not name the TomTom product, but the name, the range and the
data agree (quiet periods are close to 1.0). Working definition; to be confirmed
by the lecturers.

**Speed levels** (TomTom's recommended "relative0" bands,
[source](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/raster-flow-tiles);
names are ours): normal speed ≥ 0.75, slowed 0.35–0.75, heavy congestion
0.15–0.35, standstill or closed < 0.15.

**How the raw file was transformed**

1. The raw file has one row per TomTom snapshot (about every 44 seconds), with the
   whole road network packed into one text cell (`id,traffic_level` lines).
2. Each cell is unpacked into one row per road segment.
3. Snapshots with a timestamp that already appeared are used only once.
4. Malformed snapshots would be skipped and counted (there were none).
5. Timestamps are put on the shared 3-minute grid (Europe/Amsterdam, interval start).
6. Snapshots are averaged per road segment per interval (mean, min, max, count).
   The file is read in chunks and combined one day at a time, so it never has to
   fit in memory, and the order of the raw file does not matter.

**Verified findings** (`python -m src.tomtom check`, report in
`data/processed/tomtom_check_report.txt`)

| Item | Value |
|---|---|
| Rows in raw file | 27,744 |
| Unique snapshots | 6,662 |
| Repeated snapshots | 21,082 rows; each timestamp occurs 1–9 times. **All copies have identical content** (checked by fingerprint), so keeping one copy loses nothing. The file was saved repeatedly: 8 times it restarts at 20 Aug 08:45. |
| Malformed snapshots | 0 |
| Road segments | 10,742, every segment present in every interval with data |
| Time covered | Wed 20 Aug 08:36 – Sun 24 Aug 21:59 |
| Daily coverage | **08:00–01:00**; no data 01:00–08:00 every night (four 7-hour gaps) |
| Time between snapshots | median 44 s |
| Output | 17,487,976 rows, 68.6 MB |

**Notes**

- Missing night hours mean **no data**, not "no traffic". Do not fill them in.
- Exact 0.0 values (about 2%) mean standstill or a closed road (e.g. roads closed
  for SAIL), not missing data.
- One snapshot has the same content as another under a different timestamp
  (probably a moment the feed did not update); negligible.

---

## Road network (NWB) — `data/processed/roads.parquet`

**Source:** `NWB_roads.zip` / `wegen_in_out.shp` (course data).
**Created by:** `python -m src.roads process` (after the TomTom file; or `build_data.py`)
**Load with:** `from src.roads import load_roads` (returns a GeoDataFrame).
**One row =** one road segment with its location.

| Column | Type | Unit | Description |
|---|---|---|---|
| `road_id` | int64 | – | Road segment ID (`wvk_id` in the original file: the official NWB *wegvak* number). Same values as `road_id` in the TomTom table. |
| `nwb_traffic_level` | float | 0–1 | Column `traffic_le` in the original file (name cut to 10 characters by the shapefile format). One value per road, no date or time (see notes). Kept as delivered. |
| `length_m` | float | metres | Length of the road segment. |
| `in_tomtom` | bool | – | True if the segment appears in the TomTom data (safeguard; currently all True). |
| `geometry` | line | WGS84 (lat/lon) | Shape of the road segment, ready for web maps. |

**Link with TomTom:** `wvk_id` matches the TomTom road IDs **100% in both
directions**: all 10,742 road segments have TomTom data, all TomTom segments have a
location.

**Original file:** 10,742 segments, coordinate system EPSG:4326 (WGS84, lat/lon),
10,741 LineStrings and 1 MultiLineString (one road in several pieces).

**About `nwb_traffic_level`** (`python -m src.roads compare`): real values, not a
placeholder (1,465 different values, 56% exactly 1.0, average 0.90). It is **not a
copy of any TomTom snapshot** in our data; the most similar snapshots are Sunday
24 Aug around 08:05 (only ~53% of roads equal). Most likely a quiet-traffic
reference from outside our period, or an average. Use the TomTom table for traffic
over time.

**Why two tables instead of one:** copying each road's geometry into every
3-minute row would repeat it ~1,600 times. The tables are joined on `road_id` only
when needed (e.g. a map of one moment).

---

## Pedestrian flow (LVMA) — *to be added by Aryasen*

## Sensor locations — *to be added by Aryasen*

## Vessel positions — *to be added by Aryasen*

## LST — *to be added by Aryasen*
