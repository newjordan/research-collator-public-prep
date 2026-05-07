"""Karpathy-style plot helpers — opinionated for parameter-golf research.

TWO chart types, both ruthlessly simple, both consistent style:

  CHART A — day_charts(date, records, baseline_to_beat) -> [PNG, ...]
    Per-day plot panels for daily reports. X = run time through the day,
    capped at 12 hours per panel. Y = metric value. Dots colored by camp.
    Horizontal dashed line = baseline to beat (best ever before this day).
    Numbered gutter badges match the Test Runs table row numbers.

  CHART B — journey_chart(daily_bests, all_records) -> PNG
    Front-of-book plot. X = date across all days. Y = best metric achieved
    that day. Scatter by camp + running-minimum line. Records callouts.

Both render to PNG @ 130 DPI for crisp HTML/PDF embedding without bloat.
"""

from __future__ import annotations

import datetime as dt
import colorsys
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.colors as mcolors
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
MAX_DAY_CHART_WINDOW_HOURS = 12.0

# Chart palette from the Claude Design reference chart: dark lab plot,
# phosphor grid/running-best line, gold experimental points, slate neural
# points. This is intentionally higher contrast than the surrounding page.
DARK_BG       = "#0a0d0a"
DARK_AXIS_BG  = "#0a0d0a"
DARK_TEXT     = "#c8d4c0"
DARK_TEXT_HI  = "#f0f4ed"
DARK_TEXT_MUTE = "#6a766a"
DARK_RULE     = "#7dff7d33"
DARK_RULE_HI  = "#7dff7d66"
DARK_GRID     = "#7dff7d22"
DARK_ACCENT   = "#7dff7d"
DARK_INVALID_ZONE = "#101510"


def _desaturate(color: str, factor: float = 0.5) -> str:
    """Return the same color with saturation multiplied by factor."""
    r, g, b = mcolors.to_rgb(color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return mcolors.to_hex(colorsys.hls_to_rgb(h, l, s * factor))

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
    "neural":       "#6196c4",
    "experimental": "#d8a040",
    "daily_grind":  "#6a766a",
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
              baseline_label: str = "best before today",
              panel_label: str | None = None,
              prior_best: float | None = None) -> tuple[str, int]:
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
    CRASH_THRESHOLD = 3.0

    # Invalid region: quiet background shift only. The floor line stays subtle
    # so below-floor runs are legible without turning the whole band into an
    # alert state.
    ax.axhspan(0, INVALID_VAL_BPB_FLOOR, facecolor=DARK_INVALID_ZONE,
               alpha=1.0, edgecolor="none", linewidth=0, zorder=0)
    ax.axhline(INVALID_VAL_BPB_FLOOR, color=DARK_RULE_HI, linestyle="-",
               linewidth=0.65, alpha=0.55, zorder=1)
    ax.axhspan(0, INVALID_VAL_BPB_FLOOR, facecolor=DARK_BG,
               alpha=0.22, edgecolor="none", linewidth=0, zorder=2.8)

    # Light journey line across consecutive in-scale valid tests only. Invalid
    # and crash-class points remain visible as points, but they do not drag the
    # trajectory through the quiet invalid band or into clipped off-scale space.
    journey_segments: list[list[dict]] = []
    current_segment: list[dict] = []
    for p in pts:
        if INVALID_VAL_BPB_FLOOR <= p["value"] <= CRASH_THRESHOLD:
            current_segment.append(p)
        elif current_segment:
            journey_segments.append(current_segment)
            current_segment = []
    if current_segment:
        journey_segments.append(current_segment)
    for segment in journey_segments:
        if len(segment) >= 2:
            ax.plot([p["time"] for p in segment],
                    [p["value"] for p in segment],
                    color=DARK_RULE_HI, linewidth=0.7, alpha=0.55,
                    zorder=1, label="_journey")

    # Per-camp scatter. Below-floor points use the same hue family at half
    # saturation so the invalid zone reads as supporting evidence, not the
    # primary signal.
    by_camp: dict[str, list[dict]] = {}
    for p in pts:
        by_camp.setdefault(p["camp"], []).append(p)
    for camp, items in by_camp.items():
        color = CAMP_COLOR.get(camp, DARK_TEXT_MUTE)
        label = f"{CAMP_LABEL.get(camp, camp).upper()} · {len(items)}"
        nominal_items = [
            it for it in items if it["value"] >= INVALID_VAL_BPB_FLOOR
        ]
        invalid_items = [
            it for it in items if it["value"] < INVALID_VAL_BPB_FLOOR
        ]
        if nominal_items:
            ax.scatter([it["time"] for it in nominal_items],
                       [it["value"] for it in nominal_items],
                       color=color,
                       marker=CAMP_MARKER.get(camp, "o"),
                       s=58, alpha=0.95,
                       edgecolors=DARK_BG, linewidths=0.9,
                       label=label,
                       zorder=3)
        if invalid_items:
            ax.scatter([it["time"] for it in invalid_items],
                       [it["value"] for it in invalid_items],
                       color=_desaturate(color, 0.5),
                       marker=CAMP_MARKER.get(camp, "o"),
                       s=50, alpha=0.78,
                       edgecolors=_desaturate(DARK_TEXT_MUTE, 0.5),
                       linewidths=0.65,
                       label="_nolegend_" if nominal_items else label,
                       zorder=3)

    # Running-min line — best valid value seen so far. Below-floor eval bugs
    # and crash-class values never move the personal-best step.
    valid_pairs = [(t, v) for t, v in zip(times, values)
                   if INVALID_VAL_BPB_FLOOR <= v <= CRASH_THRESHOLD]
    if valid_pairs:
        valid_times = [p[0] for p in valid_pairs]
        valid_values = [p[1] for p in valid_pairs]
        running_min = []
        cur = prior_best if (
            isinstance(prior_best, (int, float)) and math.isfinite(prior_best)
        ) else float("inf")
        for v in valid_values:
            cur = min(cur, v)
            running_min.append(cur)
        ax.step(valid_times, running_min, where="post",
                color=DARK_ACCENT, linewidth=1.2, alpha=0.95, zorder=2,
                label="BEST VALID")

    # Tight y-clip focused on the day's actual curve. Crash-class values are
    # summarized separately instead of stretching the chart scale.
    real_values = [v for v in values if v <= CRASH_THRESHOLD]
    if real_values:
        below_floor = [v for v in values if v < INVALID_VAL_BPB_FLOOR]
        if below_floor:
            y_lo = max(0.4, min(below_floor) - 0.08)
        else:
            y_lo = INVALID_VAL_BPB_FLOOR - 0.15
        data_max = max(real_values)
        data_range = max(0.4, data_max - y_lo)
        y_hi = data_max + 0.12 * data_range
        ax.set_ylim(y_lo, y_hi)

        crashes = [v for v in values if v > CRASH_THRESHOLD]
        if crashes:
            # Crash-class runs sit outside the plotting area so the grid and
            # data remain readable.
            ax.annotate(
                f"▲ {len(crashes)} CRASH RUN{'S' if len(crashes) != 1 else ''} "
                f"OFF-SCALE  (max={max(crashes):.2f})",
                xy=(1.0, 1.0), xycoords="axes fraction",
                xytext=(0, 2), textcoords="offset points",
                fontsize=7.5, color=DARK_ACCENT, ha="right", va="bottom",
                fontweight="bold", annotation_clip=False, clip_on=False,
                zorder=6,
                bbox=dict(boxstyle="square,pad=0.3",
                          facecolor=DARK_BG,
                          edgecolor=DARK_ACCENT, linewidth=0.6))

    # Keep the chart as a chart. Run identity is preserved in the Test Runs
    # table directly below, so per-run labels are deliberately not drawn here.
    sorted_pts_for_labels = sorted(pts, key=lambda p: p["time"])
    xs_num = [mdates.date2num(p["time"]) for p in sorted_pts_for_labels]
    if xs_num:
        x_min = sorted_pts_for_labels[0]["time"]
        x_max = sorted_pts_for_labels[-1]["time"]
        max_window = dt.timedelta(hours=MAX_DAY_CHART_WINDOW_HOURS)
        if x_max <= x_min:
            x_start = x_min - dt.timedelta(minutes=30)
            x_end = x_min + dt.timedelta(minutes=30)
        else:
            span = x_max - x_min
            spare = max_window - span
            if spare.total_seconds() > 0:
                pad = min(dt.timedelta(minutes=15), spare / 2)
            else:
                pad = dt.timedelta(0)
            x_start = x_min - pad
            x_end = x_max + pad
            if x_end - x_start > max_window:
                x_end = x_start + max_window
        ax.set_xlim(x_start, x_end)
        valid_labeled = [
            p for p in sorted_pts_for_labels
            if INVALID_VAL_BPB_FLOOR <= p["value"] <= CRASH_THRESHOLD
        ]
        if valid_labeled:
            best = min(valid_labeled, key=lambda p: p["value"])
            ax.annotate(
                f"BEST #{best['n']}",
                xy=(best["time"], best["value"]),
                xytext=(8, -14), textcoords="offset points",
                fontsize=7.0, fontweight="bold",
                color=DARK_ACCENT, ha="left", va="top",
                zorder=5,
                bbox=dict(boxstyle="square,pad=0.16",
                          facecolor=DARK_BG,
                          edgecolor=DARK_ACCENT,
                          linewidth=0.55,
                          alpha=0.92),
            )

    # Baseline-to-beat — paper-white dashed (this is reference info, not
    # "active state", so it stays neutral, not accent-green).
    if (baseline_to_beat is not None and math.isfinite(baseline_to_beat)
            and baseline_to_beat >= INVALID_VAL_BPB_FLOOR):
        ax.axhline(baseline_to_beat, color=DARK_TEXT_HI, linestyle="--",
                   linewidth=0.9, alpha=0.50, zorder=1)

    # Time axis formatting
    span = min(
        times[-1] - times[0] if len(times) > 1 else dt.timedelta(hours=1),
        dt.timedelta(hours=MAX_DAY_CHART_WINDOW_HOURS),
    )
    span_h = span.total_seconds() / 3600.0
    if span_h <= 12:
        loc = mdates.HourLocator(interval=1)
    elif span_h <= 24:
        loc = mdates.HourLocator(interval=2)
    else:
        loc = mdates.HourLocator(interval=3)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    ax.set_xlabel("TIME (UTC) — LEFT→RIGHT = DAY'S EXPLORATION TRAJECTORY",
                  labelpad=8, fontsize=8.5, color=DARK_TEXT,
                  fontweight="normal")
    ax.set_ylabel(metric_name.upper(), labelpad=8, fontsize=9, color=DARK_TEXT)
    ax.set_title(f"{metric_name.upper()}  ·  {date}", loc="left", pad=10,
                 fontsize=10.5, fontweight="bold", color=DARK_TEXT_HI)
    if panel_label:
        ax.text(0.0, 1.035, panel_label.upper(), transform=ax.transAxes,
                fontsize=7.2, color=DARK_TEXT_MUTE, ha="left", va="bottom",
                fontweight="bold")
    if (baseline_to_beat is not None and math.isfinite(baseline_to_beat)
            and baseline_to_beat >= INVALID_VAL_BPB_FLOOR):
        ax.set_title(f"PRIOR DAY {metric_name.upper()}  ·  "
                     f"{baseline_to_beat:.4f}",
                     loc="right", pad=22, fontsize=7.8,
                     fontweight="bold", color=DARK_TEXT_HI)
    if len(by_camp) > 0:
        # Centered below the time axis, outside the data grid.
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.30),
                  framealpha=0.92,
                  edgecolor=DARK_RULE_HI, facecolor=DARK_BG,
                  fontsize=7.5, ncol=3, columnspacing=1.1,
                  handletextpad=0.5, borderpad=0.5)

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.26, top=0.84)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return str(out_path), len(pts)


def day_charts(out_path: str | Path,
               date: str,
               records: list[dict],
               metric_name: str = "val_loss",
               baseline_to_beat: float | None = None,
               baseline_label: str = "best before today",
               max_window_hours: float = MAX_DAY_CHART_WINDOW_HOURS
               ) -> tuple[list[str], int]:
    """Render one or more daily trajectory panels.

    No panel may cover more than max_window_hours on the x-axis. Points are
    split greedily by run time, which avoids rendering empty half-days when old
    archive mtimes create large gaps in early recovered records.
    """
    parsed: list[tuple[dt.datetime, dict]] = []
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
        parsed.append((tdt, r))

    out_path = Path(out_path)
    if not parsed:
        path, n = day_chart(out_path, date, records, metric_name,
                            baseline_to_beat, baseline_label)
        return [path], n

    parsed.sort(key=lambda item: item[0])
    window = dt.timedelta(hours=max_window_hours)
    chunks: list[list[tuple[dt.datetime, dict]]] = []
    current: list[tuple[dt.datetime, dict]] = []
    current_start: dt.datetime | None = None
    for item in parsed:
        tdt, _ = item
        if current_start is None:
            current = [item]
            current_start = tdt
            continue
        if tdt - current_start <= window:
            current.append(item)
        else:
            chunks.append(current)
            current = [item]
            current_start = tdt
    if current:
        chunks.append(current)

    if len(chunks) == 1:
        path, n = day_chart(out_path, date, records, metric_name,
                            baseline_to_beat, baseline_label)
        return [path], n

    paths: list[str] = []
    total = 0
    prior_best: float | None = None
    for idx, chunk in enumerate(chunks, start=1):
        chunk_records = [r for _, r in chunk]
        start = chunk[0][0].strftime("%H:%M")
        end = chunk[-1][0].strftime("%H:%M")
        chunk_path = out_path.with_name(
            f"{out_path.stem}_{idx:02d}{out_path.suffix}"
        )
        path, n = day_chart(
            chunk_path,
            date=date,
            records=chunk_records,
            metric_name=metric_name,
            baseline_to_beat=baseline_to_beat,
            baseline_label=baseline_label,
            panel_label=f"panel {idx}/{len(chunks)} · {start}-{end} UTC",
            prior_best=prior_best,
        )
        paths.append(path)
        total += n
        for _, rec in chunk:
            v = rec.get("value")
            if (isinstance(v, (int, float)) and math.isfinite(v)
                    and INVALID_VAL_BPB_FLOOR <= v <= 3.0):
                prior_best = v if prior_best is None else min(prior_best, v)
    return paths, total


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
