"""
Shared look for the ROAD TRAFFIC (TomTom car traffic) figures.

traffic_level = speed relative to the road's normal (free-flow) speed:
1.0 = normal speed, 0.5 = half, 0.0 = standstill or closed (TomTom documentation).

Speed levels: the four bands of TomTom's recommended traffic style "relative0"
https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/raster-flow-tiles
The band limits are TomTom's; the names and colours are ours (one warm hue from
light = normal to dark = standstill, checked for colour-blind readers).
"""

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import PercentFormatter

# Make `src` importable when a script in this folder is run with the run button.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
TZ = "Europe/Amsterdam"

# --- Ink and surfaces --------------------------------------------------------
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e4e3df"
NO_DATA = "#ecebe7"
SAIL = "#2a78d6"            # roads in the SAIL area
REST = "#9a9993"            # roads elsewhere
GAP = "#ee9d72"             # where the SAIL area is slower than elsewhere

# --- Speed levels (TomTom relative0 bands) -----------------------------------
LEVELS = [  # name, lower limit, upper limit, colour, map line width
    ("Normal speed",         0.75, 1.01, "#bdbcb5", 2),
    ("Slowed",               0.35, 0.75, "#ee9d72", 3),
    ("Heavy congestion",     0.15, 0.35, "#c8501f", 4),
    ("Standstill or closed", 0.00, 0.15, "#6a220f", 4),
]
CLOSED_BELOW = 0.01         # TomTom draws 0-0.01 separately (grey): no movement at all


def level_of(value: float) -> tuple[str, str, int]:
    """(name, colour, line width) of the speed level for one value."""
    for name, lo, hi, colour, width in LEVELS:
        if lo <= value < hi:
            return name, colour, width
    return "No data", NO_DATA, 1


# Difference SAIL area minus elsewhere (percentage points): warm = slower near SAIL,
# blue = faster near SAIL, light grey = no difference.
DIFF_CMAP = LinearSegmentedColormap.from_list(
    "diff", ["#6a220f", "#c8501f", "#ee9d72", "#f0efec", "#9ec5f4", "#3987e5", "#184f95"])
DIFF_CMAP.set_bad(NO_DATA)

SOURCE = "Source: TomTom traffic_level (speed relative to free flow), NWB road network."

# --- Event moments (NH Nieuws, "Dit kun je allemaal zien en doen tijdens SAIL") ---
EVENTS = pd.DataFrame([
    ("2025-08-20 10:00", "Sail-in starts (IJmuiden)", "Sail-in"),
    ("2025-08-20 14:00", "First ships enter the city", "ships arrive"),
    ("2025-08-20 22:30", "Fireworks", "fireworks"),
    ("2025-08-21 22:30", "Fireworks", "fireworks"),
    ("2025-08-22 22:30", "Fireworks", "fireworks"),
    ("2025-08-23 22:30", "Fireworks", "fireworks"),
    ("2025-08-24 14:00", "Sail-out starts", "Sail-out"),
], columns=["time", "event", "short"])
EVENTS["time"] = pd.to_datetime(EVENTS["time"]).dt.tz_localize(TZ)
EVENTS_SOURCE = ("Event times: NH Nieuws (Sail-in 10:00 and ships in the city from 14:00 "
                 "on Wed, fireworks 22:30 Wed–Sat, Sail-out 14:00 Sun).")


def apply_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": TEXT_MUTED,
        "axes.titlecolor": TEXT, "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.titlepad": 22,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False,
        "xtick.color": TEXT_MUTED, "ytick.color": TEXT_MUTED,
        "font.size": 10, "lines.linewidth": 2, "legend.frameon": False,
    })


def subtitle(ax, text: str) -> None:
    """One line under the title: what the reader is looking at."""
    ax.text(0, 1.02, text, transform=ax.transAxes, color=TEXT_MUTED, fontsize=9.5, va="bottom")


def caption(fig, text: str) -> None:
    fig.text(0.01, -0.01, text, color=TEXT_MUTED, fontsize=8, va="top", wrap=True)


def percent_axis(ax, axis: str = "y") -> None:
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(PercentFormatter(1.0, decimals=0))


def shade_gaps(ax, series: pd.Series, freq: str) -> None:
    """Grey band over every stretch without data (series value is NaN)."""
    missing = series.isna()
    starts = series.index[missing & ~missing.shift(1, fill_value=False)]
    ends = series.index[missing & ~missing.shift(-1, fill_value=False)]
    for s, e in zip(starts, ends):
        ax.axvspan(s, e + pd.Timedelta(freq), color=NO_DATA, lw=0, zorder=0)


def mark_events(ax, start=None, end=None, labels: bool = True) -> None:
    """Dashed vertical line at each event moment, with a small label at the top."""
    ev = EVENTS
    if start is not None:
        ev = ev[(ev["time"] >= start) & (ev["time"] <= end)]
    for t, short in zip(ev["time"], ev["short"]):
        ax.axvline(t, color=TEXT_MUTED, lw=0.8, ls=(0, (2, 2)), zorder=1)
        if labels:
            ax.annotate(short, (t, 1), xycoords=("data", "axes fraction"), xytext=(2, -2),
                        textcoords="offset points", fontsize=7.5, color=TEXT_MUTED,
                        rotation=90, va="top", ha="left")


def save(fig, name: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {path.name}")
    return path
