"""
TomTom car traffic data: inspection, cleaning and loading.

The raw file (TomTom_data_20-24Aug2025.csv, ~4.5 GB) has two columns:

    time  -> timestamp of one TomTom snapshot, e.g. 2025-08-20T08:36:29.749039+02:00
    data  -> ONE text cell holding a whole small CSV:
                 id,traffic_level
                 210398154,0.69
                 209398060,0.68
                 ...

So every row is a snapshot of all road segments at one moment. That "nested"
format is impossible to use directly in a dashboard, and the file is too big to
load into memory at once. This module therefore:

  1. reads the file in chunks (never the whole file in memory),
  2. unpacks each nested cell into a long table (time, road_id, traffic_level),
  3. averages the snapshots per road segment per fixed time interval
     (default 3 minutes, the same resolution as the LVMA pedestrian data),
  4. writes the result to a compact Parquet file that loads in seconds.

Meaning of traffic_level (TomTom documentation, "relative" flow style): the speed
on the road relative to its free-flow speed. 1.0 = normal speed (no congestion),
0.5 = half the normal speed, 0.0 = standstill or closed road.
Source: https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/vector-flow-tiles

Usage (from the repository root):

    python -m src.tomtom inspect      # look at the first snapshots of the raw file
    python -m src.tomtom check        # verify duplicates and gaps, writes a report
    python -m src.tomtom process      # build the clean file

    # in a notebook or the Streamlit app:
    from src.tomtom import load_tomtom
    df = load_tomtom(start="2025-08-23 10:00", end="2025-08-23 22:00")
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time as _time
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Paths come from src/config.py, so every teammate can keep the raw data
# wherever they like (see README_DATA.md). Raw data is NOT pushed to GitHub.
# --------------------------------------------------------------------------
# Make `src` importable also when this file is run directly (e.g. with the
# run button in VS Code) instead of with `python -m src.tomtom`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.config import PROCESSED_DIR, TIMEZONE, raw_path, to_interval  # noqa: E402

RAW_FILE = raw_path("tomtom")

# The nested cells are far larger than Python's default CSV field limit.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def processed_path(freq: str = "3min") -> Path:
    return PROCESSED_DIR / f"tomtom_{freq}.parquet"


# --------------------------------------------------------------------------
# 1. Inspect: always run this first on the real file to confirm the structure
# --------------------------------------------------------------------------
def inspect_raw(path: Path = RAW_FILE, n_snapshots: int = 3) -> None:
    """Print the first few snapshots without loading the whole file."""
    print(f"File: {path}  ({path.stat().st_size / 1e9:.2f} GB)")
    reader = pd.read_csv(path, chunksize=n_snapshots, dtype=str)
    first = next(reader)
    print(f"Columns: {list(first.columns)}")
    for _, row in first.iterrows():
        segments = _parse_snapshot(row["data"])
        print(f"\nSnapshot at {row['time']}")
        print(f"  road segments in this snapshot: {len(segments):,}")
        print(f"  traffic_level min/max: {segments['traffic_level'].min()} / "
              f"{segments['traffic_level'].max()}")
        print(f"  share of exact 0.0 values: {(segments['traffic_level'] == 0).mean():.1%}")
        print(segments.head(5).to_string(index=False))


# --------------------------------------------------------------------------
# 1b. Check: are repeated snapshots real duplicates, and where are the gaps?
# --------------------------------------------------------------------------
def check_raw(path: Path = RAW_FILE, min_gap_minutes: float = 10) -> Path:
    """
    Verify the raw file without unpacking it, and write a report.

    For every row it stores the timestamp and a fingerprint (MD5 hash) of the
    whole data cell. Two cells with the same fingerprint have identical content,
    so this proves whether rows with the same timestamp are true copies.
    """
    import hashlib

    print(f"Checking {path} ...")
    t0 = _time.time()
    recs = []
    reader = pd.read_csv(path, chunksize=500, dtype=str)
    for chunk in reader:
        for ts, cell in zip(chunk["time"], chunk["data"]):
            recs.append((ts, hashlib.md5(str(cell).encode()).hexdigest()))
    df = pd.DataFrame(recs, columns=["time_raw", "hash"])
    df["row"] = np.arange(1, len(df) + 1)          # row number in the raw file
    df["time"] = pd.to_datetime(df["time_raw"], utc=True,
                                format="ISO8601").dt.tz_convert(TIMEZONE)

    lines = []
    out = lines.append

    # Duplicates
    copies = df.groupby("time_raw").size()
    out("1. DUPLICATES")
    out(f"   rows in file:                 {len(df):,}")
    out(f"   unique timestamps:            {len(copies):,}")
    out("   how often each timestamp occurs:")
    for k, v in copies.value_counts().sort_index().items():
        out(f"     {k} time(s): {v:,} timestamps")
    variants = df.groupby("time_raw")["hash"].nunique()
    n_conflict = int((variants > 1).sum())
    out(f"   timestamps whose copies have DIFFERENT content: {n_conflict:,}")
    if n_conflict == 0:
        out("   -> every repeated timestamp is an exact copy (identical content),")
        out("      so keeping one copy loses no information.")
    else:
        out("   -> some copies differ: removing them is NOT safe without a decision.")
        for t in variants[variants > 1].index[:5]:
            out(f"      example: {t}")
    same_content = df.groupby("hash")["time_raw"].nunique()
    out(f"   identical content under different timestamps: "
        f"{int((same_content > 1).sum()):,} cases")

    # How the file is laid out: where does time jump backwards?
    back = df[df["time"] < df["time"].shift()]
    out("\n2. FILE ORDER")
    out(f"   places where time jumps backwards: {len(back):,}")
    for _, r in back.head(15).iterrows():
        prev = df.loc[r["row"] - 2, "time"]
        out(f"     row {r['row']:>6,}: {prev:%d %b %H:%M:%S} -> {r['time']:%d %b %H:%M:%S}")
    if len(back) > 15:
        out(f"     ... and {len(back) - 15} more")

    # Gaps in the unique snapshots
    u = df.drop_duplicates("time_raw").sort_values("time")
    u["gap_min"] = u["time"].diff().dt.total_seconds() / 60
    big = u[u["gap_min"] > min_gap_minutes]
    out(f"\n3. GAPS LONGER THAN {min_gap_minutes:g} MINUTES (unique snapshots, time order)")
    out(f"   first snapshot: {u['time'].min():%a %d %b %H:%M}")
    out(f"   last snapshot:  {u['time'].max():%a %d %b %H:%M}")
    out(f"   median gap: {u['gap_min'].median() * 60:.0f} s")
    for _, r in big.iterrows():
        start = r["time"] - pd.Timedelta(minutes=r["gap_min"])
        out(f"     no data from {start:%a %d %b %H:%M} to {r['time']:%a %d %b %H:%M}"
            f"  ({r['gap_min'] / 60:.1f} h)")
    if big.empty:
        out("     none")

    # Snapshots per hour of the day, to see when TomTom data exists
    per_hour = u.groupby(u["time"].dt.hour).size().reindex(range(24), fill_value=0)
    out("\n4. SNAPSHOTS PER HOUR OF THE DAY (all days together)")
    out("   " + "  ".join(f"{h:02d}:{n}" for h, n in per_hour.items()))

    report = "\n".join(lines)
    print(report)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    report_path = PROCESSED_DIR / "tomtom_check_report.txt"
    report_path.write_text(report + "\n")
    print(f"\nDone in {_time.time() - t0:.0f} s. Report saved to {report_path}")
    return report_path


# --------------------------------------------------------------------------
# 2. Parse one nested cell
# --------------------------------------------------------------------------
def _parse_snapshot(cell: str) -> pd.DataFrame:
    """Turn one 'data' cell into a DataFrame with road_id and traffic_level."""
    df = pd.read_csv(io.StringIO(cell))
    if list(df.columns) != ["id", "traffic_level"]:
        raise ValueError(f"unexpected columns in snapshot: {list(df.columns)}")
    df = df.astype({"id": "int64", "traffic_level": "float32"})
    return df.rename(columns={"id": "road_id"})


# --------------------------------------------------------------------------
# 3. Process the whole file in chunks
# --------------------------------------------------------------------------
def process_tomtom(
    raw_path: Path = RAW_FILE,
    freq: str = "3min",
    chunk_rows: int = 200,
    out_path: Path | None = None,
) -> Path:
    """
    Convert the raw TomTom file into a tidy, aggregated Parquet file.

    Parameters
    ----------
    raw_path   : path to the raw TomTom CSV.
    freq       : time interval to aggregate to (pandas offset, e.g. "3min", "15min", "1h").
    chunk_rows : number of snapshots read per chunk (lower it if memory is tight).
    out_path   : where to write the result; defaults to data/processed/tomtom_<freq>.parquet.

    Output columns: see DATA_DICTIONARY.md.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    out_path = out_path or processed_path(freq)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = out_path.with_suffix(".partial.parquet")

    seen_times: set[str] = set()   # to skip snapshots that appear twice
    n_snapshots = n_bad = n_dupes = n_backwards = 0
    prev_ts = None
    t0 = _time.time()

    # ---- Pass 1: read chunks, write partial sums per (interval, road) to disk.
    # This does not assume the file is in time order: an interval that shows up
    # in several places of the file is simply combined in pass 2.
    writer = None
    reader = pd.read_csv(raw_path, chunksize=chunk_rows, dtype=str)
    for i, chunk in enumerate(reader):
        frames = []
        for ts, cell in zip(chunk["time"], chunk["data"]):
            if ts in seen_times:
                n_dupes += 1          # exact same snapshot time seen before: skip
                continue
            try:
                seg = _parse_snapshot(cell)
            except Exception:
                n_bad += 1            # malformed snapshot: skip it, but count it
                continue
            seen_times.add(ts)
            if prev_ts is not None and ts < prev_ts:
                n_backwards += 1      # same format everywhere, so text order = time order
            prev_ts = ts
            seg["time"] = ts
            frames.append(seg)
            n_snapshots += 1
        if not frames:
            continue

        long = pd.concat(frames, ignore_index=True)
        long["time"] = to_interval(long["time"], freq)   # shared 3-minute grid (config.py)
        long = long.dropna(subset=["traffic_level"])
        part = (
            long.groupby(["time", "road_id"])["traffic_level"]
            .agg(level_sum="sum", level_min="min", level_max="max", n_obs="count")
            .reset_index()
        )
        part["level_sum"] = part["level_sum"].astype("float64")
        part["n_obs"] = part["n_obs"].astype("int32")
        part["date"] = part["time"].dt.date.astype(str)

        table = pa.Table.from_pandas(part, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(partial_path, table.schema, compression="zstd")
        writer.write_table(table)

        if i % 10 == 0:
            print(f"  chunk {i}: {n_snapshots:,} snapshots read, last time "
                  f"{part['time'].max()} ({_time.time() - t0:.0f} s)")
    if writer is not None:
        writer.close()

    # ---- Pass 2: combine the partial sums, one day at a time (keeps memory low).
    print("Combining per day ...")
    dates = sorted(pq.read_table(partial_path, columns=["date"])
                   .column("date").unique().to_pylist())
    writer = None
    n_rows = 0
    for d in dates:
        day = pd.read_parquet(partial_path, filters=[("date", "==", d)])
        agg = day.groupby(["time", "road_id"]).agg(
            level_sum=("level_sum", "sum"),
            level_min=("level_min", "min"),
            level_max=("level_max", "max"),
            n_obs=("n_obs", "sum"),
        ).reset_index()
        agg["traffic_level"] = (agg["level_sum"] / agg["n_obs"]).astype("float32")
        agg["date"] = d
        agg["hour"] = agg["time"].dt.hour.astype("int8")
        agg["level_min"] = agg["level_min"].astype("float32")
        agg["level_max"] = agg["level_max"].astype("float32")
        agg["n_obs"] = agg["n_obs"].astype("int16")
        agg = agg[["time", "date", "hour", "road_id", "traffic_level",
                   "level_min", "level_max", "n_obs"]]
        agg = agg.sort_values(["time", "road_id"]).reset_index(drop=True)

        table = pa.Table.from_pandas(agg, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(out_path, table.schema, compression="zstd")
        writer.write_table(table)
        n_rows += len(agg)
        print(f"  {d}: {len(agg):,} rows")
    if writer is not None:
        writer.close()
    partial_path.unlink(missing_ok=True)

    print(f"\nDone in {_time.time() - t0:.0f} s")
    print(f"  snapshots used:              {n_snapshots:,}")
    print(f"  duplicate snapshots skipped: {n_dupes:,}")
    print(f"  malformed snapshots skipped: {n_bad:,}")
    print(f"  times going backwards:       {n_backwards:,}")
    print(f"  output rows:                 {n_rows:,}")
    print(f"  output file:                 {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    print("  (gaps and duplicates in detail: python -m src.tomtom check)")
    return out_path


# --------------------------------------------------------------------------
# 4. Load the processed file (what teammates and the dashboard use)
# --------------------------------------------------------------------------
def load_tomtom(
    freq: str = "3min",
    start: str | None = None,
    end: str | None = None,
    road_ids: list[int] | None = None,
    path: Path | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    Load the cleaned TomTom data, optionally filtered by time and road segment.
    Filters are applied while reading, so only the needed rows enter memory.

    Example
    -------
    df = load_tomtom(start="2025-08-23 10:00", end="2025-08-23 22:00")
    """
    path = path or processed_path(freq)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m src.tomtom process --freq {freq}` "
            "first, or download the processed file from the shared drive."
        )
    filters = []
    if start is not None:
        filters.append(("time", ">=", pd.Timestamp(start, tz=TIMEZONE)))
    if end is not None:
        filters.append(("time", "<", pd.Timestamp(end, tz=TIMEZONE)))
    if road_ids is not None:
        filters.append(("road_id", "in", list(road_ids)))
    # `columns` reads only the listed columns, e.g. ["time", "traffic_level"]:
    # much less memory when the whole period is needed.
    return pd.read_parquet(path, filters=filters or None, columns=columns)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="TomTom data tools")
    sub = parser.add_subparsers(dest="cmd")

    p_in = sub.add_parser("inspect", help="show the first snapshots of the raw file")
    p_in.add_argument("--raw", type=Path, default=RAW_FILE)

    p_ch = sub.add_parser("check", help="verify duplicates and gaps in the raw file")
    p_ch.add_argument("--raw", type=Path, default=RAW_FILE)

    p_pr = sub.add_parser("process", help="build the cleaned Parquet file")
    p_pr.add_argument("--raw", type=Path, default=RAW_FILE)
    p_pr.add_argument("--freq", default="3min")
    p_pr.add_argument("--chunk-rows", type=int, default=200,
                      help="snapshots per chunk; lower it if memory runs out")

    args = parser.parse_args()
    if args.cmd is None:
        # Run without a command (e.g. run button): inspect the raw file.
        print("No command given, so running `inspect`.")
        print("To build the cleaned file, run in the terminal from the sail_data folder:")
        print("    python -m src.tomtom process\n")
        args = parser.parse_args(["inspect"])
    if not args.raw.exists():
        print(f"Raw TomTom file not found:\n  {args.raw}\n")
        print("Either put the file there, or tell the code where your data is:")
        print("  create data_location.txt in the repository root with the full path")
        print("  to your raw-data folder, then check with: python -m src.config")
        sys.exit(1)
    if args.cmd == "inspect":
        inspect_raw(args.raw)
    elif args.cmd == "check":
        check_raw(args.raw)
    else:
        process_tomtom(args.raw, args.freq, args.chunk_rows)


if __name__ == "__main__":
    main()
