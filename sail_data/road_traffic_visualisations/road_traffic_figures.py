"""
ROAD TRAFFIC FIGURES: TomTom car traffic during SAIL 2025.

Core idea: there is no "normal week" to compare with, so roads IN the SAIL area are
compared with roads ELSEWHERE at the same moment. City-wide traffic (rush hour)
affects both; the difference between them is what SAIL adds.

Run this file (run button, or `python road_traffic_visualisations/road_traffic_figures.py`).
Output in road_traffic_visualisations/output/:

    1_map.html              Interactive map (open in a browser): roads by speed level at
                            key moments, the SAIL area, and the most slowed roads
    2_sail_vs_rest.png      Average speed in the SAIL area vs elsewhere, whole event
    3_difference_grid.png   That difference per day and hour
    4_most_slowed.png       Most slowed roads in the SAIL area in a chosen period
    5_closures.png          Roads at zero speed (closed): how many, which, and when

traffic_level = speed relative to normal (free-flow) speed: 1.0 = normal, 0.0 = standstill.
Data: data/processed/tomtom_3min.parquet and roads.parquet (run build_data.py first).
"""

from functools import lru_cache

import folium
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely

import style as s                      # also makes `src` importable
from src.config import INTERVAL, TIMEZONE
from src.roads import load_roads, road_ids_in_sail_area, sail_area
from src.tomtom import load_tomtom

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
MAP_MOMENTS = {                              # moments to switch between on the map
    "2025-08-23 15:00": "Sat 15:00 (afternoon)",
    "2025-08-23 22:30": "Sat 22:30 (fireworks)",
    "2025-08-24 14:00": "Sun 14:00 (Sail-out)",
}
RANK_PERIOD = ("2025-08-23 21:30", "2025-08-24 00:30")   # figure 4: around Saturday's fireworks
TOP_N = 15                                   # figure 4: number of roads in the ranking
MIN_LENGTH_M = 50                            # figure 4: skip very short segments (noisy)
CLOSED_SHARE = 0.5                           # figure 4: closed in > 50% of the period = closure
CLOSURE_MIN_HOURS = 3                        # figure 5: closures of at least this long
CLOSURE_ROADS = 15                           # figure 5: roads shown in the timeline


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz=TIMEZONE)


def naive(t: pd.Timestamp) -> str:
    return str(t.tz_localize(None))


@lru_cache(maxsize=1)
def sail_ids() -> frozenset:
    return frozenset(road_ids_in_sail_area())


@lru_cache(maxsize=1)
def all_traffic() -> pd.DataFrame:
    """Every road every 3 minutes, flagged in / outside the SAIL area."""
    df = load_tomtom(columns=["time", "road_id", "traffic_level"])
    df["in_sail"] = np.isin(df["road_id"].to_numpy(), np.fromiter(sail_ids(), int))
    return df


@lru_cache(maxsize=1)
def sail_vs_rest() -> pd.DataFrame:
    """Average speed per 3 minutes: SAIL area vs elsewhere (gaps kept as empty rows)."""
    g = all_traffic().groupby(["time", "in_sail"])["traffic_level"].mean().unstack()
    g = g.rename(columns={True: "sail", False: "rest"})
    g["diff"] = g["sail"] - g["rest"]
    grid = pd.date_range(g.index.min(), g.index.max(), freq=INTERVAL, tz=TIMEZONE)
    return g.reindex(grid)


def most_slowed(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Roads in the SAIL area ranked by average speed in a period (slowest first).
    Returns (ranking, closed roads). Closed = zero speed in most of the period."""
    df = load_tomtom(start=start, end=end, road_ids=list(sail_ids()),
                     columns=["road_id", "traffic_level"])
    r = df.groupby("road_id")["traffic_level"].agg(
        speed="mean", closed_share=lambda v: (v < s.CLOSED_BELOW).mean()).reset_index()
    r = r.merge(load_roads()[["road_id", "length_m"]], on="road_id")
    closed = r[r["closed_share"] > CLOSED_SHARE]
    moving = r[(r["closed_share"] <= CLOSED_SHARE) & (r["length_m"] >= MIN_LENGTH_M)]
    return moving.nsmallest(TOP_N, "speed").reset_index(drop=True), closed


# ----------------------------------------------------------------------------
# 1. Interactive map
# ----------------------------------------------------------------------------
def map_interactive():
    roads = load_roads()[["road_id", "length_m", "geometry"]].copy()
    roads["geometry"] = shapely.set_precision(roads.geometry.values, 1e-5)   # smaller file
    area = sail_area()
    centre = area.iloc[0].centroid

    m = folium.Map(location=[centre.y, centre.x], zoom_start=13, tiles=None)
    # Background: Esri light grey map (free, no key, also works when the HTML file is
    # opened directly from disk; OpenStreetMap's servers block that).
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
              "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
        name="Map", control=False, max_native_zoom=16, max_zoom=19,
    ).add_to(m)

    for i, (moment, label) in enumerate(MAP_MOMENTS.items()):
        t = ts(moment)
        now = load_tomtom(start=moment, end=naive(t + pd.Timedelta(INTERVAL)),
                          columns=["road_id", "traffic_level"])
        if now.empty:
            print(f"  no TomTom data at {moment}; left out of the map")
            continue
        g = roads.merge(now, on="road_id")
        lv = g["traffic_level"].map(s.level_of)
        g["level"], g["colour"], g["weight"] = zip(*lv)
        g["speed"] = (g["traffic_level"] * 100).round().astype(int).astype(str) + "% of normal"
        g = g.sort_values("traffic_level", ascending=False)      # slow roads drawn on top
        layer = folium.FeatureGroup(name=label, overlay=False, show=(i == 0))
        folium.GeoJson(
            g[["road_id", "speed", "level", "colour", "weight", "geometry"]],
            style_function=lambda f: {"color": f["properties"]["colour"],
                                      "weight": f["properties"]["weight"], "opacity": 0.9},
            tooltip=folium.GeoJsonTooltip(["road_id", "speed", "level"],
                                          aliases=["Road segment", "Speed", "Level"]),
        ).add_to(layer)
        layer.add_to(m)

    folium.GeoJson(area, name="SAIL area (assumption)", style_function=lambda f: {
        "color": s.SAIL, "weight": 2, "dashArray": "6 4", "fillOpacity": 0.04}).add_to(m)

    ranked, _ = most_slowed(*RANK_PERIOD)
    top = roads.merge(ranked, on="road_id")
    rank_layer = folium.FeatureGroup(name=f"Most slowed roads {RANK_PERIOD[0][-5:]}–"
                                          f"{RANK_PERIOD[1][-5:]} (figure 4)", show=False)
    for _, r in ranked.iterrows():
        p = top.loc[top["road_id"] == r["road_id"], "geometry"].iloc[0].interpolate(0.5, normalized=True)
        folium.Marker([p.y, p.x], tooltip=f"{_ + 1}. road {r['road_id']}: {r['speed']:.0%}",
                      icon=folium.DivIcon(html=f'<div style="background:{s.TEXT};color:white;'
                      f'border-radius:50%;width:20px;height:20px;text-align:center;'
                      f'font:bold 11px sans-serif;line-height:20px">{_ + 1}</div>')).add_to(rank_layer)
    rank_layer.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    legend = "".join(f'<div><span style="display:inline-block;width:22px;height:4px;'
                     f'background:{c};margin-right:6px;vertical-align:middle"></span>'
                     f'{n} ({lo:.0%}{"+" if hi > 1 else "–" + format(hi, ".0%")})</div>'
                     for n, lo, hi, c, _ in s.LEVELS)
    m.get_root().html.add_child(folium.Element(
        f'<div style="position:fixed;bottom:20px;left:20px;z-index:999;background:white;'
        f'padding:10px 12px;font:12px sans-serif;border-radius:6px;box-shadow:0 1px 4px #0003">'
        f'<b>Car traffic during SAIL 2025</b><br>Speed, % of normal speed (TomTom bands)'
        f'{legend}<div style="margin-top:4px;color:{s.SAIL}">- - SAIL area (assumption)</div>'
        f'<div style="color:{s.TEXT_MUTED};margin-top:4px">Pick a moment top right. '
        f'Hover a road for its speed.</div></div>'))
    s.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = s.OUTPUT_DIR / "1_map.html"
    m.save(path)
    print(f"  saved {path.name}  (open it in a browser)")


# ----------------------------------------------------------------------------
# 2-5. Figures
# ----------------------------------------------------------------------------
def fig_sail_vs_rest():
    g = sail_vs_rest()
    n_sail = len(sail_ids())
    n_rest = all_traffic()["road_id"].nunique() - n_sail
    fig, ax = plt.subplots(figsize=(15, 5.8))
    ax.fill_between(g.index, g["sail"], g["rest"], where=g["sail"] < g["rest"],
                    color=s.GAP, alpha=0.45, lw=0, label="slower in the SAIL area")
    ax.plot(g.index, g["rest"], color=s.REST, lw=1.3, label=f"elsewhere ({n_rest:,} road segments)")
    ax.plot(g.index, g["sail"], color=s.SAIL, lw=1.6, label=f"SAIL area ({n_sail:,} road segments)")
    s.shade_gaps(ax, g["sail"], INTERVAL)
    s.mark_events(ax)
    s.percent_axis(ax)
    ax.set_ylabel("Average speed, % of normal")
    ax.legend(loc="lower left", ncols=3, fontsize=9)
    ax.xaxis.set_major_locator(mdates.DayLocator(tz=g.index.tz))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b", tz=g.index.tz))
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18], tz=g.index.tz))
    t = g["diff"].idxmin()
    ax.set_title(f"Largest difference: {t:%A %d %B, %H:%M}, roads in the SAIL area at "
                 f"{g.loc[t, 'sail']:.0%} of normal speed, elsewhere {g.loc[t, 'rest']:.0%}")
    s.subtitle(ax, "Average speed of road segments in the SAIL area (blue) and elsewhere "
                   "(grey). Orange = SAIL area slower than the rest of the city.")
    s.caption(fig, "Grey bands: no TomTom data (01:00–08:00). Dashed lines: event moments. "
                   + s.EVENTS_SOURCE + " SAIL area: within 750 m of the IJ waterfront, "
                   "NDSM to KNSM (assumption). " + s.SOURCE)
    return fig


def fig_difference_grid():
    d = sail_vs_rest()["diff"].dropna() * 100
    table = (d.groupby([d.index.date, d.index.hour]).mean().unstack()
             .reindex(columns=range(24)))
    lim = np.nanmax(np.abs(table.values))
    day, hour = table.stack().idxmin()

    fig, ax = plt.subplots(figsize=(15, 4.4))
    ax.grid(False)
    im = ax.imshow(np.ma.masked_invalid(table.values), cmap=s.DIFF_CMAP, vmin=-lim, vmax=lim,
                   aspect="auto")
    for (i, j), v in np.ndenumerate(table.values):
        if np.isnan(v):
            ax.add_patch(plt.Rectangle((j - .5, i - .5), 1, 1, fill=False, hatch="////",
                                       edgecolor="#d3d2cc", lw=0))
        else:
            ax.text(j, i, "0" if round(v) == 0 else f"{round(v):+d}", ha="center", va="center", fontsize=8.5,
                    color="white" if abs(v) > lim * 0.6 else s.TEXT)
    ax.set_xticks(range(24), [f"{h:02d}" for h in range(24)])
    ax.set_yticks(range(len(table)), [pd.Timestamp(x).strftime("%a %d %b") for x in table.index])
    ax.set_xlabel("Hour of the day")
    ax.set_xticks(np.arange(-.5, 24), minor=True)
    ax.set_yticks(np.arange(-.5, len(table)), minor=True)
    ax.grid(which="minor", color=s.SURFACE, lw=2)
    ax.tick_params(which="both", length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title(f"SAIL area most slowed compared with the rest of the city: "
                 f"{pd.Timestamp(day):%A %d %B} {hour:02d}:00–{hour + 1:02d}:00 "
                 f"({abs(table.loc[day, hour]):.0f} percentage points slower)")
    s.subtitle(ax, "Average speed in the SAIL area minus elsewhere, per hour. −10 = traffic "
                   "near SAIL moved 10 points (of normal speed) slower than in the rest of the city.")
    fig.colorbar(im, ax=ax, pad=0.01, shrink=0.9,
                 label="SAIL area minus elsewhere,\npercentage points")
    s.caption(fig, "Orange: slower in the SAIL area; blue: faster. Hatched: no TomTom data. "
                   + s.SOURCE)
    return fig


def fig_most_slowed():
    ranked, closed = most_slowed(*RANK_PERIOD)
    a, b = ts(RANK_PERIOD[0]), ts(RANK_PERIOD[1])
    fig, ax = plt.subplots(figsize=(11, 0.42 * len(ranked) + 2))
    y = np.arange(len(ranked))[::-1]
    ax.barh(y, ranked["speed"], color=[s.level_of(v)[1] for v in ranked["speed"]], height=0.62)
    for yi, v in zip(y, ranked["speed"]):
        ax.text(v + 0.01, yi, f"{v:.0%}", va="center", fontsize=9)
    ax.set_yticks(y, [f"{i + 1}.  road {r.road_id}  ({r.length_m:,.0f} m)"
                      for i, r in enumerate(ranked.itertuples())], fontsize=9)
    for name, lo, hi, colour, _ in s.LEVELS:           # level limits as faint guides
        if lo > 0:
            ax.axvline(lo, color=colour, lw=1, ls=(0, (3, 2)))
            ax.annotate(f"{lo:.0%}", (lo, 1), xycoords=("data", "axes fraction"),
                        xytext=(2, 2), textcoords="offset points", fontsize=7.5, color=s.TEXT_MUTED)
    ax.set_xlim(0, 1)
    s.percent_axis(ax, "x")
    ax.set_xlabel("Average speed in this period, % of normal")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_title(f"Most slowed roads in the SAIL area, {a:%A %d %B %H:%M}–{b:%H:%M}")
    s.subtitle(ax, "Roads still moving, ranked by average speed; colour = TomTom speed level. "
                   "Numbers match the map layer in 1_map.html.")
    s.caption(fig, f"Left out: {len(closed)} segments closed (zero speed) for most of the period, "
                   f"see figure 5, and segments shorter than {MIN_LENGTH_M} m. " + s.SOURCE)
    return fig


def fig_closures():
    df = all_traffic()
    df = df.assign(closed=df["traffic_level"] < s.CLOSED_BELOW)
    share = df.groupby(["time", "in_sail"])["closed"].mean().unstack()
    share = share.reindex(pd.date_range(share.index.min(), share.index.max(),
                                        freq=INTERVAL, tz=TIMEZONE))
    hours = (df[df["in_sail"] & df["closed"]].groupby("road_id").size()
             * pd.Timedelta(INTERVAL).total_seconds() / 3600)
    long = hours[hours >= CLOSURE_MIN_HOURS].sort_values(ascending=False)
    shown = long.head(CLOSURE_ROADS)

    fig, (top, bot) = plt.subplots(2, 1, figsize=(15, 8.5), sharex=True,
                                   gridspec_kw={"height_ratios": [1, 1.4], "hspace": 0.35})
    top.plot(share.index, share[True], color=s.SAIL, lw=1.5, label="SAIL area")
    top.plot(share.index, share[False], color=s.REST, lw=1.2, label="elsewhere")
    s.percent_axis(top)
    top.set_ylabel("Share of road\nsegments closed")
    top.legend(loc="center left", fontsize=9)
    s.shade_gaps(top, share[True], INTERVAL)
    s.mark_events(top)
    top.set_title(f"Road closures: {len(long)} road segments in the SAIL area at zero speed "
                  f"for {CLOSURE_MIN_HOURS} hours or more")
    s.subtitle(top, "Top: share of road segments with zero speed. Bottom: when the "
                    f"{len(shown)} longest-closed segments in the SAIL area were closed.")

    step = pd.Timedelta(INTERVAL)
    sub = df[df["road_id"].isin(shown.index) & df["closed"]].sort_values(["road_id", "time"])
    for row, (road, h) in enumerate(shown.items()):
        t = sub.loc[sub["road_id"] == road, "time"]
        run = (t.diff() != step).cumsum()
        spans = [(g.iloc[0], g.iloc[-1] - g.iloc[0] + step) for _, g in t.groupby(run)]
        bot.broken_barh([(mdates.date2num(a), d / pd.Timedelta("1D")) for a, d in spans],
                        (row - 0.35, 0.7), color=s.LEVELS[-1][3])
    bot.set_yticks(range(len(shown)), [f"road {r}  ({h:.0f} h)" for r, h in shown.items()],
                   fontsize=8.5)
    bot.invert_yaxis()
    bot.grid(axis="y", visible=False)
    bot.tick_params(axis="y", length=0)
    s.shade_gaps(bot, share[True], INTERVAL)
    s.mark_events(bot, labels=False)
    bot.xaxis.set_major_locator(mdates.DayLocator(tz=share.index.tz))
    bot.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b", tz=share.index.tz))
    s.caption(fig, f"Closed = speed below {s.CLOSED_BELOW:.0%} of normal (TomTom shows this band "
                   "separately: no movement measured). Most likely road closures for SAIL, but it "
                   "could also mean TomTom measured no cars. Hours count only times with data. "
                   + s.SOURCE)
    return fig


# ----------------------------------------------------------------------------
FIGURES = {
    "2_sail_vs_rest": fig_sail_vs_rest,
    "3_difference_grid": fig_difference_grid,
    "4_most_slowed": fig_most_slowed,
    "5_closures": fig_closures,
}


def main() -> None:
    s.apply_style()
    print(f"Making road traffic figures ({len(sail_ids()):,} road segments in the SAIL area) ...")
    map_interactive()
    for name, make in FIGURES.items():
        s.save(make(), name)
    print(f"Done. Figures are in {s.OUTPUT_DIR}")


if __name__ == "__main__":
    main()
