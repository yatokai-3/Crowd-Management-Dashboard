"""
NWB road network (Nationaal Wegen Bestand): inspection, cleaning and loading.

The TomTom table only contains road IDs, not WHERE the roads are. The NWB road
network gives each road segment its location (a line on the map). Joining the two
on the road ID makes it possible to draw TomTom traffic on a map and to select
the roads around the SAIL area.

Design choice: the geometry is NOT copied into the 17.5-million-row TomTom table
(every road's line would be repeated for every 3-minute interval, making the file
huge). Instead there are two tables that share the key `road_id`:

    roads.parquet       one row per road segment, with its line geometry  (small)
    tomtom_3min.parquet one row per road segment per 3 minutes, no geometry (large)

They are joined only when needed, e.g. for the map of one moment.

Usage (from the repository root):

    python -m src.roads inspect        # columns, coordinate system, which column matches TomTom
    python -m src.roads process        # writes data/processed/roads.parquet
    python -m src.roads compare        # what is the extra traffic value in the NWB file?

In code:
    from src.roads import load_roads, road_ids_near
    roads = load_roads()               # GeoDataFrame, coordinates in WGS84 (lat/lon)
    ids = road_ids_near(52.379, 4.900, 2000)   # road IDs within 2 km of a point
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.config import PROCESSED_DIR, RAW_DIR, raw_path  # noqa: E402

SHP_NAME = "wegen_in_out.shp"
ROADS_FILE = PROCESSED_DIR / "roads.parquet"
WGS84 = "EPSG:4326"     # latitude/longitude, used by web maps (Streamlit, folium, plotly)
RD_NEW = "EPSG:28992"   # Dutch national grid in metres, used to measure lengths/distances


def _gpd():
    try:
        import geopandas as gpd
    except ImportError:
        sys.exit("geopandas is not installed. Run: pip install -r requirements.txt")
    return gpd


# --------------------------------------------------------------------------
# Finding and reading the shapefile
# --------------------------------------------------------------------------
def find_shapefile() -> str:
    """
    A shapefile is several files together (.shp, .shx, .dbf, .prj, .cpg) that must
    stay in the same folder. This accepts either the unzipped folder anywhere inside
    the raw-data folder, or the original NWB_roads.zip.
    """
    found = sorted(RAW_DIR.rglob(SHP_NAME))
    if found:
        return str(found[0])
    z = raw_path("nwb_roads")
    if z.exists():
        inner = [n for n in zipfile.ZipFile(z).namelist() if n.endswith(SHP_NAME)]
        if inner:
            return f"zip://{z}!{inner[0]}"
    sys.exit(
        f"Could not find {SHP_NAME} or NWB_roads.zip in {RAW_DIR}.\n"
        "Put the unzipped NWB_roads folder (all 5 wegen_in_out files together) or the "
        "zip file in your raw-data folder. Check with: python -m src.config"
    )


def read_raw_roads():
    gpd = _gpd()
    src = find_shapefile()
    print(f"Reading {src}")
    return gpd.read_file(src)


def _tomtom_ids() -> pd.Series | None:
    """Unique road IDs in the cleaned TomTom file (only that column is read)."""
    from src.tomtom import processed_path
    p = processed_path("3min")
    if not p.exists():
        return None
    import pyarrow.parquet as pq
    ids = pq.read_table(p, columns=["road_id"]).column("road_id").unique().to_pandas()
    return pd.Series(ids, name="road_id")


def _match_rates(gdf, tt_ids: pd.Series) -> pd.DataFrame:
    """For every column that could be an ID, how well does it match the TomTom IDs?"""
    tt = set(tt_ids.astype("int64"))
    rows = []
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        vals = pd.to_numeric(gdf[col], errors="coerce").dropna()
        if len(vals) == 0 or not (vals % 1 == 0).all():
            continue
        vals = set(vals.astype("int64"))
        hit = len(tt & vals)
        rows.append({
            "column": col,
            "TomTom IDs found in this column": f"{hit / len(tt):.1%}",
            "values of this column used by TomTom": f"{hit / len(vals):.1%}",
            "_score": hit,
        })
    return pd.DataFrame(rows).sort_values("_score", ascending=False)


# --------------------------------------------------------------------------
# 1. Inspect
# --------------------------------------------------------------------------
def inspect_roads() -> None:
    gdf = read_raw_roads()
    print(f"\nRoad segments: {len(gdf):,}")
    print(f"Coordinate system: {gdf.crs}")
    print(f"Geometry types: {gdf.geom_type.value_counts().to_dict()}")
    print("\nColumns (type, example values):")
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        ex = gdf[col].dropna().astype(str).head(3).tolist()
        print(f"  {col:<20} {str(gdf[col].dtype):<10} {ex}")

    tt = _tomtom_ids()
    if tt is None:
        print("\n(Cleaned TomTom file not found, so the ID match cannot be checked yet.)")
        return
    print(f"\nWhich column holds the road ID used by TomTom? ({len(tt):,} TomTom road IDs)")
    rates = _match_rates(gdf, tt)
    if rates.empty:
        print("  No numeric column found. The ID may be stored as text; tell the team.")
    else:
        print(rates.drop(columns="_score").to_string(index=False))
        print(f"\n-> Most likely ID column: {rates.iloc[0]['column']}")


# --------------------------------------------------------------------------
# 2. Process
# --------------------------------------------------------------------------
def process_roads(id_col: str | None = None, out_path: Path = ROADS_FILE) -> Path:
    gdf = read_raw_roads()
    tt = _tomtom_ids()

    if id_col is None:
        if tt is None:
            sys.exit("Run `python -m src.tomtom process` first, or pass --id-col.")
        id_col = _match_rates(gdf, tt).iloc[0]["column"]
        print(f"ID column chosen automatically: {id_col}")

    gdf = gdf.rename(columns={id_col: "road_id"})
    # The NWB file also has a column `traffic_le` (shapefiles cut names to 10
    # characters). Its meaning is unknown (one value per road, not a time series).
    # Renamed so it is not confused with TomTom's `traffic_level`.
    gdf = gdf.rename(columns={"traffic_le": "nwb_traffic_level"})
    gdf["road_id"] = pd.to_numeric(gdf["road_id"], errors="coerce").astype("Int64")
    n_no_id = int(gdf["road_id"].isna().sum())
    gdf = gdf.dropna(subset=["road_id"])
    n_dup = int(gdf["road_id"].duplicated().sum())

    if gdf.crs is None:
        print("WARNING: the shapefile has no coordinate system; assuming RD New (EPSG:28992).")
        gdf = gdf.set_crs(RD_NEW)
    gdf["length_m"] = gdf.to_crs(RD_NEW).length.round(1)      # length in metres
    gdf = gdf.to_crs(WGS84)                                    # lat/lon for web maps

    if tt is not None:
        gdf["in_tomtom"] = gdf["road_id"].isin(set(tt))
        missing = set(tt) - set(gdf["road_id"].astype("int64"))
    else:
        missing = set()

    cols = ["road_id"] + [c for c in gdf.columns
                          if c not in ("road_id", gdf.geometry.name)] + [gdf.geometry.name]
    gdf = gdf[cols].sort_values("road_id").reset_index(drop=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(out_path, index=False)

    print("\nDone")
    print(f"  road segments saved:            {len(gdf):,}")
    print(f"  segments without an ID (dropped): {n_no_id:,}")
    print(f"  road IDs that occur more than once: {n_dup:,}"
          + ("  <- check: one ID with several lines" if n_dup else ""))
    if tt is not None:
        print(f"  segments used in TomTom data:   {int(gdf['in_tomtom'].sum()):,}")
        print(f"  TomTom IDs NOT found in NWB:    {len(missing):,} of {len(tt):,}")
    print(f"  output: {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    return out_path


# --------------------------------------------------------------------------
# 2b. What is the extra value in the road file? Compare it with every snapshot.
# --------------------------------------------------------------------------
def compare_nwb_value(top: int = 5) -> None:
    """
    The NWB file has one value per road (`traffic_le`) without a date or time.
    This compares it with every unique TomTom snapshot in the raw file to find
    out whether it is a copy of one moment, and describes the values themselves.
    """
    import numpy as np
    from src.tomtom import RAW_FILE, _parse_snapshot

    gdf = read_raw_roads()
    if "traffic_le" not in gdf.columns:
        sys.exit("Column traffic_le not found in the road file.")
    nwb = (gdf[["wvk_id", "traffic_le"]].rename(columns={"wvk_id": "road_id"})
           .set_index("road_id")["traffic_le"].astype(float))

    print("\n1. THE VALUES THEMSELVES")
    print(f"   roads: {len(nwb):,}   missing: {int(nwb.isna().sum()):,}")
    print(f"   min / mean / max: {nwb.min():.2f} / {nwb.mean():.3f} / {nwb.max():.2f}")
    print(f"   share exactly 1.0: {(nwb == 1).mean():.1%}   exactly 0.0: {(nwb == 0).mean():.1%}")
    print(f"   number of different values: {nwb.nunique():,}")
    vc = nwb.round(2).value_counts().head(5)
    print("   most common values: " + ", ".join(f"{v:.2f} ({n:,}x)" for v, n in vc.items()))

    print(f"\n2. COMPARISON WITH EVERY TOMTOM SNAPSHOT (reading {RAW_FILE.name}) ...")
    seen, results = set(), []
    for chunk in pd.read_csv(RAW_FILE, chunksize=500, dtype=str):
        for ts, cell in zip(chunk["time"], chunk["data"]):
            if ts in seen:
                continue
            seen.add(ts)
            try:
                snap = _parse_snapshot(cell).set_index("road_id")["traffic_level"]
            except Exception:
                continue
            a, b = nwb.align(snap.astype(float), join="inner")
            if len(a) == 0:
                continue
            diff = np.abs(a.values - b.values)
            results.append((ts, (diff < 0.005).mean(), diff.mean()))
    res = pd.DataFrame(results, columns=["time", "share_equal", "mean_abs_diff"])
    res = res.sort_values(["share_equal", "mean_abs_diff"], ascending=[False, True])
    print(f"   snapshots compared: {len(res):,}")
    print("   best matching snapshots (share of roads with the same value, mean difference):")
    for _, r in res.head(top).iterrows():
        print(f"     {r['time']}   {r['share_equal']:6.1%} equal   mean diff {r['mean_abs_diff']:.3f}")
    best = res.iloc[0]
    print("\n   ->", end=" ")
    if best["share_equal"] > 0.99:
        print(f"the NWB value is a copy of the snapshot at {best['time']}.")
    elif (nwb == 1).mean() > 0.99:
        print("almost all values are 1.0 and no snapshot matches: most likely a placeholder.")
    else:
        print("no snapshot matches: it is not a copy of one moment (maybe an average or "
              "something else). Ask the lecturers.")


# --------------------------------------------------------------------------
# 3. Load and select
# --------------------------------------------------------------------------
def load_roads(tomtom_only: bool = True):
    """Road segments with geometry (WGS84). tomtom_only keeps roads that have TomTom data."""
    gpd = _gpd()
    if not ROADS_FILE.exists():
        raise FileNotFoundError(f"{ROADS_FILE} not found. Run `python -m src.roads process`.")
    gdf = gpd.read_parquet(ROADS_FILE)
    if tomtom_only and "in_tomtom" in gdf.columns:
        gdf = gdf[gdf["in_tomtom"]]
    return gdf


def sail_area():
    """The SAIL event area as a polygon (GeoSeries, WGS84). Definition in config.py."""
    gpd = _gpd()
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    from src.config import SAIL_AREA_BUFFER_M, SAIL_AREA_EXTRA_POINTS, SAIL_AREA_WATERFRONT
    shapes = gpd.GeoSeries([LineString(SAIL_AREA_WATERFRONT)]
                           + [Point(p) for p in SAIL_AREA_EXTRA_POINTS], crs=WGS84)
    area = unary_union(shapes.to_crs(RD_NEW).buffer(SAIL_AREA_BUFFER_M))
    area = area.buffer(400).buffer(-400)     # smooth the notch where NDSM joins the waterfront
    return gpd.GeoSeries([area], crs=RD_NEW).to_crs(WGS84)


def road_ids_in_sail_area() -> set[int]:
    """IDs of road segments that lie (partly) inside the SAIL event area."""
    roads = load_roads(tomtom_only=True)
    inside = roads.intersects(sail_area().iloc[0])
    return set(int(i) for i in roads.loc[inside, "road_id"])


def road_ids_near(lat: float, lon: float, radius_m: float) -> list[int]:
    """IDs of road segments within `radius_m` metres of a point (lat/lon)."""
    gpd = _gpd()
    roads = load_roads(tomtom_only=True).to_crs(RD_NEW)
    centre = gpd.GeoSeries(gpd.points_from_xy([lon], [lat]), crs=WGS84).to_crs(RD_NEW).iloc[0]
    near = roads[roads.distance(centre) <= radius_m]
    return sorted(int(i) for i in near["road_id"])


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="NWB road network tools")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("inspect", help="show columns, coordinate system and ID match")
    pr = sub.add_parser("process", help="build data/processed/roads.parquet")
    pr.add_argument("--id-col", default=None, help="name of the road ID column")
    sub.add_parser("compare", help="compare the NWB traffic value with every TomTom snapshot")
    a = p.parse_args()

    if a.cmd is None or a.cmd == "inspect":
        if a.cmd is None:
            print("No command given, so running `inspect`.\n")
        inspect_roads()
    elif a.cmd == "process":
        process_roads(a.id_col)
    else:
        compare_nwb_value()


if __name__ == "__main__":
    main()
