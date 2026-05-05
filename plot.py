"""Karpathy-style plot helpers — opinionated for parameter-golf research.

TWO chart types, both ruthlessly simple, both consistent style:

  CHART A — day_chart(date, records, baseline_to_beat) -> PNG
    Per-day plot for daily reports. X = records sorted by metric ascending
    (best on left). Y = metric value. Dots colored by camp. Horizontal dashed
    line = baseline to beat (best ever before this day). Top-3 labeled.

  CHART B — journey_chart(daily_bests, all_records) -> PNG
    Front-of-book plot. X = date across all days. Y = best metric achieved
    that day. Scatter by camp + running-minimum line. Records callouts.

Both render to PNG @ 130 DPI for crisp HTML/PDF embedding without bloat.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
try:
    from adjustText import adjust_text
    _HAVE_ADJUST_TEXT = True
except ImportError:
    _HAVE_ADJUST_TEXT = False

# Validity floor: any val_bpb measurement below this is a known eval/loader bug
# in the parameter-golf benchmark, not a real result. Plotted as a dotted red
# line; tests below it are marked invalid and excluded from running-min.
INVALID_VAL_BPB_FLOOR = 1.06

# Palette — matches the clean US-Graphics-style HTML report (charcoal dark).
# Neutral greys, single yellow accent, neutral whites. No green tinting.
DARK_BG       = "#111315"   # page bg (matches HTML --bg)
DARK_AXIS_BG  = "#111315"   # same — chart sits on the page bg
DARK_TEXT     = "#d6d8db"   # primary ink
DARK_TEXT_HI  = "#f4f5f7"   # emphasized
DARK_RULE     = "#2a2d31"   # hairline dividers
DARK_RULE_HI  = "#3a3e44"   # axis spines / stronger rules
DARK_GRID     = "#2a2d31"
DARK_ACCENT   = "#e3b341"   # yellow accent (used sparingly — crash flag)
DARK_INVALID  = "#e25a4a"   # warn red
DARK_INVALID_FILL = "#e25a4a"

plt.rcParams.update({
    "figure.dpi": 130,
    "savefig.dpi": 130,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.08,
    "font.family": "monospace",
    "font.monospace": ["Berkeley Mono", "JetBrains Mono", "IBM Plex Mono",
                        "Liberation Mono", "DejaVu Sans Mono", "Courier New",
                        "monospace"],
    "font.size": 9.0,
    "text.color": DARK_TEXT,
    "axes.labelsize": 9.0,
    "axes.titlesize": 10.0,
    "axes.titleweight": "bold",
    "axes.facecolor": DARK_AXIS_BG,
    "axes.edgecolor": DARK_RULE_HI,
    "axes.labelcolor": DARK_TEXT,
    "axes.titlecolor": DARK_TEXT,
    "axes.linewidth": 1.0,
    "axes.spines.top": True,
    "axes.spines.right": True,
    "axes.spines.bottom": True,
    "axes.spines.left": True,
    "axes.grid": True,
    "grid.color": DARK_GRID,
    "grid.alpha": 0.55,
    "grid.linewidth": 0.4,
    "figure.facecolor": DARK_BG,
    "figure.edgecolor": DARK_BG,
    "xtick.color": DARK_TEXT,
    "ytick.color": DARK_TEXT,
    "xtick.labelcolor": DARK_TEXT,
    "ytick.labelcolor": DARK_TEXT,
    "xtick.labelsize": 8.0,
    "ytick.labelsize": 8.0,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.major.size": 4,
    "ytick.major.size": 4,
    "xtick.minor.size": 2,
    "ytick.minor.size": 2,
    "lines.linewidth": 1.2,
    "lines.markersize": 5,
    "legend.frameon": True,
    "legend.framealpha": 0.92,
    "legend.facecolor": DARK_AXIS_BG,
    "legend.edgecolor": DARK_RULE_HI,
    "legend.labelcolor": DARK_TEXT,
    "legend.fontsize": 8.0,
})

CAMP_COLOR = {
    "neural":       "#6fbf6f",  # lighter green — neural minority (data color)
    "experimental": "#3a6e3a",  # dark green — experimental majority
    "daily_grind":  "#8a8d92",  # neutral muted
}
CAMP_MARKER = {
    "neural":       "o",
    "experimental": "s",
    "daily_grind":  "x",
}
CAMP_LABEL = {
    "neural":       "neural",
    "experimental": "experimental",
    "daily_grind":  "daily-grind",
}


# ---------- CHART A ----------------------------------------------------------

def day_chart(out_path: str | Path,
              date: str,
              records: list[dict],
              metric_name: str = "val_loss",
              baseline_to_beat: float | None = None,
              baseline_label: str = "best before today") -> tuple[str, int]:
    """Per-day TRAJECTORY chart — Karpathy-style autoresearch view.

    X = time of day (UTC). Y = metric value.
    Each test = numbered dot at its run time.
    Light gray line connects consecutive tests in time order = the journey.
    Bold step line = personal-best-of-day-so-far running minimum.
    Horizontal dashed = best before today (the bar to beat).

    Reads as: 'what did I try, in what order, and when did the bar move'.

    records: list of {"value": float, "camp": str, "title": str, "time_iso": str, "n": int}
             pre-sorted by time_iso (ascending). The 'n' is the chart's number
             label, which matches the Test Runs table's # column.
    """
    # Filter to plottable records
    pts = []
    for r in records:
        v = r.get("value")
        t = r.get("time_iso")
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            continue
        if not t:
            continue
        try:
            tdt = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        except ValueError:
            continue
        pts.append({
            "time": tdt,
            "value": float(v),
            "camp": r.get("camp", "experimental"),
            "title": r.get("title", ""),
            "n": int(r.get("n", 0)) or len(pts) + 1,
        })
    if not pts:
        return _stub(out_path, f"{metric_name} — {date}", "no records"), 0
    pts.sort(key=lambda p: p["time"])

    fig, ax = plt.subplots(figsize=(9.0, 3.6))

    times = [p["time"] for p in pts]
    values = [p["value"] for p in pts]

    # Red zone: hatched diagonal pattern on the same BG, plus a thin solid
    # ruler at the floor. The hatch (//) gives texture without relying on
    # subtly-different blacks.
    ax.axhspan(0, INVALID_VAL_BPB_FLOOR, facecolor=DARK_INVALID,
               alpha=0.10, hatch="///", edgecolor=DARK_INVALID,
               linewidth=0, zorder=0)
    ax.axhline(INVALID_VAL_BPB_FLOOR, color=DARK_INVALID, linestyle="-",
               linewidth=0.7, alpha=0.65, zorder=0)

    # Light journey line connecting consecutive tests in time order
    if len(pts) >= 2:
        ax.plot(times, values, color="#666", linewidth=0.7, alpha=0.55,
                zorder=1, label="_journey")

    # Per-camp scatter — single style per camp, no invalid variants.
    by_camp: dict[str, list[dict]] = {}
    for p in pts:
        by_camp.setdefault(p["camp"], []).append(p)
    for camp, items in by_camp.items():
        ax.scatter([it["time"] for it in items],
                   [it["value"] for it in items],
                   color=CAMP_COLOR.get(camp, "#888"),
                   marker=CAMP_MARKER.get(camp, "o"),
                   s=140, alpha=0.95,
                   edgecolors=DARK_BG, linewidths=0.9,
                   label=f"{CAMP_LABEL.get(camp, camp).upper()} · {len(items)}",
                   zorder=3)

    # Running-min line — phosphor green = "current personal best", the only
    # element on the chart that uses the accent color.
    valid_pairs = [(t, v) for t, v in zip(times, values)
                   if v >= INVALID_VAL_BPB_FLOOR]
    if valid_pairs:
        valid_times = [p[0] for p in valid_pairs]
        valid_values = [p[1] for p in valid_pairs]
        running_min = []
        cur = float("inf")
        for v in valid_values:
            cur = min(cur, v)
            running_min.append(cur)
        ax.step(valid_times, running_min, where="post",
                color=DARK_TEXT_HI, linewidth=1.6, alpha=1.0, zorder=2,
                label="BEST VALID")

    # Tighter y-clip focused on the day's actual curve, with a label gutter
    # reserved ABOVE the data zone so the numbered badges have clear airspace.
    CRASH_THRESHOLD = 3.0
    real_values = [v for v in values if v <= CRASH_THRESHOLD]
    if real_values:
        below_floor = [v for v in values if v < INVALID_VAL_BPB_FLOOR]
        if below_floor:
            y_lo = max(0.4, min(below_floor) - 0.08)
        else:
            y_lo = INVALID_VAL_BPB_FLOOR - 0.15
        data_max = max(real_values)
        data_range = max(0.4, data_max - y_lo)
        label_gutter = 0.22 * data_range
        y_hi = data_max + 0.05 + label_gutter
        ax.set_ylim(y_lo, y_hi)
        crashes = [v for v in values if v > CRASH_THRESHOLD]
        if crashes:
            # Bottom-right corner — top is reserved for the badge gutter now.
            ax.annotate(
                f"▲ {len(crashes)} CRASH RUN{'S' if len(crashes) != 1 else ''} "
                f"OFF-SCALE  (max={max(crashes):.2f})",
                xy=(1.0, 0.0), xycoords="axes fraction",
                xytext=(-6, 6), textcoords="offset points",
                fontsize=7.5, color=DARK_ACCENT, ha="right", va="bottom",
                fontweight="bold",
                bbox=dict(boxstyle="square,pad=0.3",
                          facecolor=DARK_BG,
                          edgecolor=DARK_ACCENT, linewidth=0.6))

    # Numbered badges with leader lines — packed into the gutter we just
    # reserved above the data zone. Done AFTER set_ylim so the packing math
    # uses the locked axes range, not auto-scale (which would include the
    # off-scale crashes and stretch the layout).
    sorted_pts_for_labels = sorted(pts, key=lambda p: p["time"])
    xs_num = [mdates.date2num(p["time"]) for p in sorted_pts_for_labels]
    if xs_num:
        ax.set_xlim(min(xs_num) - 0.01, max(xs_num) + 0.01)
        cur_ylim = ax.get_ylim()
        xlim_ = ax.get_xlim()
        xspan = xlim_[1] - xlim_[0]
        yspan = cur_ylim[1] - cur_ylim[0]
        min_gap_x = xspan / 30.0
        placed_x: list[float] = []
        for x in xs_num:
            if not placed_x:
                placed_x.append(x)
                continue
            placed_x.append(max(x, placed_x[-1] + min_gap_x))
        # Two-row gutter inside the axes (just below the top edge).
        y_top  = cur_ylim[1] - 0.05 * yspan
        y_alt  = cur_ylim[1] - 0.12 * yspan
        was_pushed = [False]
        for i in range(1, len(xs_num)):
            was_pushed.append(placed_x[i] > xs_num[i] + 1e-9)
        ys: list[float] = []
        for i in range(len(xs_num)):
            local_pressure = was_pushed[i] or (i + 1 < len(xs_num) and was_pushed[i + 1])
            ys.append(y_alt if (local_pressure and (i % 2 == 1)) else y_top)
        # Leader lines first (behind badges)
        for i, p in enumerate(sorted_pts_for_labels):
            ax.plot([xs_num[i], placed_x[i]],
                    [p["value"], ys[i] - 0.012 * yspan],
                    color=DARK_RULE_HI, linewidth=0.5, alpha=0.75,
                    solid_capstyle="round", zorder=4)
        # Badges on top
        for i, p in enumerate(sorted_pts_for_labels):
            ax.text(placed_x[i], ys[i], str(p["n"]),
                    fontsize=9.0, fontweight="bold",
                    color=DARK_TEXT_HI, ha="center", va="center",
                    zorder=5,
                    bbox=dict(boxstyle="square,pad=0.30",
                              facecolor=DARK_BG,
                              edgecolor=DARK_RULE_HI, linewidth=0.7, alpha=0.97))

    # Baseline-to-beat — paper-white dashed (this is reference info, not
    # "active state", so it stays neutral, not accent-green).
    if (baseline_to_beat is not None and math.isfinite(baseline_to_beat)
            and baseline_to_beat >= INVALID_VAL_BPB_FLOOR):
        ax.axhline(baseline_to_beat, color=DARK_TEXT_HI, linestyle="--",
                   linewidth=0.9, alpha=0.50, zorder=1)
        ax.annotate(f"{baseline_label.upper()} = {baseline_to_beat:.4f}",
                    xy=(1.0, baseline_to_beat),
                    xycoords=("axes fraction", "data"),
                    xytext=(-4, 4), textcoords="offset points",
                    fontsize=7.5, color=DARK_TEXT_HI, ha="right",
                    fontweight="bold")

    # Time axis formatting
    span = times[-1] - times[0] if len(times) > 1 else dt.timedelta(hours=1)
    span_h = span.total_seconds() / 3600.0
    if span_h <= 12:
        loc = mdates.HourLocator(interval=1)
    elif span_h <= 24:
        loc = mdates.HourLocator(interval=2)
    else:
        loc = mdates.HourLocator(interval=3)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    ax.set_xlabel("TIME (UTC) — left→right = day's exploration trajectory")
    ax.set_ylabel(metric_name.upper())
    ax.set_title(f"{metric_name.upper()} — {date}", loc="left")
    if len(by_camp) > 0:
        ax.legend(loc="upper left", framealpha=0.95, edgecolor="#000",
                  fontsize=7.5)

    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return str(out_path), len(pts)


# ---------- CHART B ----------------------------------------------------------

def journey_chart(out_path: str | Path,
                  per_day_bests: list[dict],
                  metric_name: str = "val_loss",
                  reference_baseline: float | None = None,
                  reference_label: str = "published baseline",
                  annotate_records: list[dict] | None = None) -> tuple[str, int]:
    """The full-arc plot for the front of the book.

    per_day_bests: list of {"date": "YYYY-MM-DD", "best": float, "camp": str,
                            "title": str (best record's title)}
    annotate_records: optional list of {"date","best","label"} to call out.
    """
    if not per_day_bests:
        return _stub(out_path, f"{metric_name} — journey", "no data"), 0

    per_day_bests = [d for d in per_day_bests
                     if isinstance(d.get("best"), (int, float))
                     and math.isfinite(d["best"])]
    per_day_bests.sort(key=lambda d: d["date"])
    dates = [dt.datetime.strptime(d["date"], "%Y-%m-%d") for d in per_day_bests]
    bests = [d["best"] for d in per_day_bests]
    camps = [d["camp"] for d in per_day_bests]

    fig, ax = plt.subplots(figsize=(11.0, 4.0))

    # Per-day scatter colored by camp
    by_camp: dict[str, list[tuple]] = {}
    for x, y, c in zip(dates, bests, camps):
        by_camp.setdefault(c, []).append((x, y))
    for c, items in by_camp.items():
        ax.scatter([x for x, _ in items], [y for _, y in items],
                   color=CAMP_COLOR.get(c, "#444"),
                   marker=CAMP_MARKER.get(c, "o"),
                   s=34, alpha=0.85, edgecolors="white", linewidths=0.4,
                   label=f"{CAMP_LABEL.get(c, c)} ({len(items)})",
                   zorder=3)

    # Running-minimum line
    running_min = []
    cur = float("inf")
    for v in bests:
        cur = min(cur, v)
        running_min.append(cur)
    ax.plot(dates, running_min, color="#222222", linewidth=1.4,
            alpha=0.7, zorder=2, label="personal best (running min)")

    # Reference baseline
    if reference_baseline is not None and math.isfinite(reference_baseline):
        ax.axhline(reference_baseline, color="#aa4444", linestyle="--",
                   linewidth=1.0, alpha=0.8, zorder=1)
        ax.annotate(f"{reference_label} = {reference_baseline:.4f}",
                    xy=(1.0, reference_baseline),
                    xycoords=("axes fraction", "data"),
                    xytext=(-2, 4), textcoords="offset points",
                    fontsize=8, color="#aa4444", ha="right")

    # Record callouts
    if annotate_records:
        for r in annotate_records:
            try:
                dx = dt.datetime.strptime(r["date"], "%Y-%m-%d")
            except (KeyError, ValueError):
                continue
            ax.annotate(r.get("label", "record"),
                        xy=(dx, r["best"]),
                        xytext=(0, -16), textcoords="offset points",
                        fontsize=7.5, color="#111111", ha="center",
                        arrowprops=dict(arrowstyle="-", color="#777",
                                        lw=0.5, shrinkA=0, shrinkB=1))

    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.set_xlabel("date")
    ax.set_ylabel(f"best {metric_name} that day")
    ax.set_title(f"Journey — best {metric_name} per day", loc="left")
    ax.legend(loc="best", framealpha=0.0)

    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return str(out_path), len(per_day_bests)


# ---------- shared helper ----------------------------------------------------

def _stub(out_path: str | Path, title: str, msg: str) -> str:
    fig, ax = plt.subplots(figsize=(5.5, 3.3))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_AXIS_BG)
    ax.text(0.5, 0.5, msg, ha="center", va="center",
            fontsize=12, color=DARK_TEXT)
    ax.set_title(title, loc="left", color=DARK_TEXT)
    ax.set_axis_off()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=DARK_BG)
    plt.close(fig)
    return str(out_path)


# Backwards-compat: keep `plot_test` as a wrapper around day_chart so the old
# render_day.py call site keeps working until it's rewritten.
def plot_test(out_path, series, x_label, y_label, title, baseline=None,
              baseline_label="baseline"):
    """DEPRECATED — kept only as a fallback. Prefer day_chart()."""
    records = []
    for s in series:
        camp = s.get("name", "neural")
        for v in s.get("y", []):
            records.append({"value": v, "camp": camp, "title": ""})
    date = title.split("—")[-1].strip() if "—" in title else ""
    return day_chart(out_path, date, records, metric_name=y_label,
                     baseline_to_beat=baseline, baseline_label=baseline_label)
