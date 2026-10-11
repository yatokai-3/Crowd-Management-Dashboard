# Road traffic visualisations (TomTom car traffic)

Figures about **car traffic on the road network** during SAIL 2025, made from the
TomTom data and the NWB road network. (Pedestrian / other figures live in their
own folders.)

**Before running:** build the processed data (`build_data.py`, see `README_DATA.md`).

**Run:** open `road_traffic_figures.py` and press the run button, or from the
repository root: `python road_traffic_visualisations/road_traffic_figures.py`.
Output goes to `road_traffic_visualisations/output/` (not on GitHub: always
recreated from the code, so it updates when the data changes).

## The core idea: SAIL area vs the rest of the city

There is no "normal week" in the data to compare with: all five days are SAIL days.
And averaged over all roads, ordinary city traffic (rush hour) dominates: the slowest
hour of the whole period is a Wednesday afternoon rush hour, not a SAIL moment.

So the figures compare roads **in the SAIL area** with roads **elsewhere** at the
same moment. City-wide traffic affects both; the **difference** is what SAIL adds.

The SAIL area is a working definition (an assumption, agreed in the group): within
750 m of the IJ waterfront from the Houthavens/NDSM to the eastern docks (KNSM),
where the ships were moored. It is defined once in `src/config.py` and drawn on the map.

## The figures

| File | Shows | Question it answers |
|---|---|---|
| `1_map.html` | Interactive map (open in a browser): roads coloured by speed level at key moments, the SAIL area, and the roads of figure 4 | Where is traffic slow at a given moment? |
| `2_sail_vs_rest.png` | Average speed in the SAIL area (blue) vs elsewhere (grey), whole event, with event moments | When did SAIL slow traffic down beyond normal city traffic? |
| `3_difference_grid.png` | That difference per day and hour, in percentage points | Which days and hours were most affected? |
| `4_most_slowed.png` | The most slowed (still moving) roads in the SAIL area in a chosen period | Which roads were worst at that time? |
| `5_closures.png` | Share of roads at zero speed over time, and when the longest-closed roads in the SAIL area were closed | Which roads were closed, and when? |

Titles are generated from the data, so they always state the current finding.

## What `traffic_level` means

Speed on a road **relative to its normal (free-flow) speed**: 1.0 = normal speed,
0.5 = half, 0.0 = standstill or closed
([TomTom documentation](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/vector-flow-tiles)).
"Normal" means the speed on an empty road, so every busy daytime hour looks slower
than normal, with or without an event.

Speed levels follow TomTom's "relative0" bands
([TomTom documentation](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/raster-flow-tiles)):
normal ≥ 75%, slowed 35–75%, heavy congestion 15–35%, standstill or closed < 15%.
"Closed" in figures 4–5 means below 1% of normal speed (TomTom draws this band
separately: no movement). Most likely road closures for SAIL, but it could also
mean TomTom measured no cars there.

## Event moments (dashed lines)

From [NH Nieuws](https://www.nhnieuws.nl/nieuws/351282/dit-kun-je-allemaal-zien-en-doen-tijdens-sail):
Sail-in starts Wed 20 Aug 10:00 (IJmuiden), first ships enter the city from 14:00;
fireworks 22:30 Wed–Sat; Sail-out Sun 24 Aug 14:00.

## Settings (top of `road_traffic_figures.py`)

| Setting | Default | Meaning |
|---|---|---|
| `MAP_MOMENTS` | Sat 15:00, Sat 22:30, Sun 14:00 | Moments you can switch between on the map |
| `RANK_PERIOD` | Sat 21:30 – Sun 00:30 | Period for the ranking (around Saturday's fireworks) |
| `TOP_N` | 15 | Roads in the ranking |
| `MIN_LENGTH_M` | 50 | Very short segments are left out of the ranking (noisy) |
| `CLOSED_SHARE` | 0.5 | Closed in more than half of the period = closure, not congestion |
| `CLOSURE_MIN_HOURS` | 3 | Minimum length of a closure to count in figure 5 |
| `CLOSURE_ROADS` | 15 | Roads shown in the closure timeline |

## Notes

- **No data is never shown as a value:** TomTom has no data 01:00–08:00 (grey bands,
  hatched cells).
- **The map needs internet** to load the background map (OpenStreetMap) when opened.
- **Averages count every road segment equally**, short or long.
- **Colours:** speed levels in one warm hue (light = normal, dark = standstill);
  SAIL area blue, elsewhere grey; in the grid, orange = slower near SAIL, blue =
  faster. Defined once in `style.py`.

## Adding a figure

Write a function `fig_something()` in `road_traffic_figures.py` that returns a
figure (data via `all_traffic()`, `sail_vs_rest()`, `load_tomtom()`, `load_roads()`;
colours via `s.`), and add it to `FIGURES` at the bottom.
