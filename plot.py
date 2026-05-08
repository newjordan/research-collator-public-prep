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

# Cover-derived chart palette: orange field, dark-black details.
COVER_ORANGE = "#89380e"
COVER_BLACK = "#050605"
DARK_BG       = COVER_ORANGE
DARK_AXIS_BG  = COVER_ORANGE
DARK_TEXT     = COVER_BLACK
DARK_TEXT_HI  = COVER_BLACK
DARK_TEXT_MUTE = "#1b0f08"
DARK_RULE     = COVER_BLACK
DARK_RULE_HI  = COVER_BLACK
DARK_GRID     = COVER_BLACK
DARK_ACCENT   = COVER_BLACK
DARK_INVALID_ZONE = "#78300b"


def _desaturate(color: str, factor: float = 0.5) -> str:
    """Return the same color with saturation multiplied by factor."""
    r, g, b = mcolors.to_rgb(color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return mcolors.to_hex(colorsys.hls_to_rgb(h, l, s * factor))


def _is_bpb_metric(metric_name: str | None) -> bool:
    metric = (metric_name or "").lower()
    return "bpb" in metric or "bits_per_byte" in metric

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
    "kernel":       COVER_BLACK,
    "neural":       "#2b1607",
    "experimental": "#130a04",
    "daily_grind":  "#3b1b08",
}
CAMP_MARKER = {
    "kernel":       "s",
    "neural":       "^",
    "experimental": "o",
    "daily_grind":  "x",
}
CAMP_LABEL = {
    "kernel":       "kernel",
    "neural":       "neural",
    "experimental": "experimental",
    "daily_grind":  "daily-grind",
}

POINT_SIZE = 42
INVALID_POINT_SIZE = 38
POINT_EDGE_WIDTH = 0.75
POINT_PIN_SIZE = 3.8
POINT_PIN_WIDTH = 0.62


def _assign_delta_pins(items: list[dict]) -> None:
    """Tag points by literal value movement versus the previous plotted point."""
    prev: float | None = None
    for it in items:
        value = it.get("value")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            it["delta_pin"] = "neutral"
            continue
        if prev is None:
            it["delta_pin"] = "neutral"
        elif value > prev:
            it["delta_pin"] = "up"
        elif value < prev:
            it["delta_pin"] = "down"
        else:
            it["delta_pin"] = "neutral"
        prev = float(value)


def _draw_delta_pins(ax, items: list[dict], x_key: str) -> None:
    """Draw a center mark at each point: + up, - down, dot neutral."""
    if not items:
        return
    marker_by_pin = {
        "up": "+",
        "down": "_",
        "neutral": ".",
    }
    for pin, marker in marker_by_pin.items():
        pin_items = [it for it in items if it.get("delta_pin") == pin]
        if not pin_items:
            continue
        ax.plot([it[x_key] for it in pin_items],
                [it["value"] for it in pin_items],
                linestyle="None",
                marker=marker,
                markersize=POINT_PIN_SIZE if pin != "neutral" else POINT_PIN_SIZE * 0.82,
                markeredgewidth=POINT_PIN_WIDTH,
                color=DARK_BG,
                zorder=4,
                label="_nolegend_")


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
    Dark-black line connects consecutive tests in time order = the journey.
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
    _assign_delta_pins(pts)

    fig, ax = plt.subplots(figsize=(9.0, 3.6))

    times = [p["time"] for p in pts]
    values = [p["value"] for p in pts]
    CRASH_THRESHOLD = 3.0
    is_bpb = _is_bpb_metric(metric_name)

    if is_bpb:
        # Invalid region: quiet background shift only. The floor line stays
        # subtle so below-floor runs are legible without turning the whole band
        # into an alert state.
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
        if (not is_bpb) or (INVALID_VAL_BPB_FLOOR <= p["value"] <= CRASH_THRESHOLD):
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
            it for it in items if (not is_bpb) or it["value"] >= INVALID_VAL_BPB_FLOOR
        ]
        invalid_items = [
            it for it in items if is_bpb and it["value"] < INVALID_VAL_BPB_FLOOR
        ]
        if nominal_items:
            ax.scatter([it["time"] for it in nominal_items],
                       [it["value"] for it in nominal_items],
                       color=color,
                       marker=CAMP_MARKER.get(camp, "o"),
                       s=POINT_SIZE, alpha=0.95,
                       edgecolors=DARK_BG, linewidths=POINT_EDGE_WIDTH,
                       label=label,
                       zorder=3)
            _draw_delta_pins(ax, nominal_items, "time")
        if invalid_items:
            ax.scatter([it["time"] for it in invalid_items],
                       [it["value"] for it in invalid_items],
                       color=_desaturate(color, 0.5),
                       marker=CAMP_MARKER.get(camp, "o"),
                       s=INVALID_POINT_SIZE, alpha=0.78,
                       edgecolors=_desaturate(DARK_TEXT_MUTE, 0.5),
                       linewidths=0.55,
                       label="_nolegend_" if nominal_items else label,
                       zorder=3)
            _draw_delta_pins(ax, invalid_items, "time")

    # Running-min line — best valid value seen so far. Below-floor eval bugs
    # and crash-class values never move the personal-best step.
    valid_pairs = [(t, v) for t, v in zip(times, values)
                   if (not is_bpb) or (INVALID_VAL_BPB_FLOOR <= v <= CRASH_THRESHOLD)]
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
                label="BEST VALID" if is_bpb else "BEST")

    # Tight y-clip focused on the day's actual curve. Crash-class values are
    # summarized separately instead of stretching the chart scale.
    real_values = [v for v in values if (not is_bpb) or v <= CRASH_THRESHOLD]
    if real_values:
        below_floor = [v for v in values if is_bpb and v < INVALID_VAL_BPB_FLOOR]
        if is_bpb and below_floor:
            y_lo = max(0.4, min(below_floor) - 0.08)
        elif is_bpb:
            y_lo = INVALID_VAL_BPB_FLOOR - 0.15
        else:
            data_min = min(real_values)
            data_range = max(0.08, max(real_values) - data_min)
            y_lo = max(0.0, data_min - 0.18 * data_range)
        data_max = max(real_values)
        data_range = max(0.4 if is_bpb else 0.04, data_max - y_lo)
        y_hi = data_max + (0.12 if is_bpb else 0.18) * data_range
        ax.set_ylim(y_lo, y_hi)

        crashes = [v for v in values if is_bpb and v > CRASH_THRESHOLD]
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
            if (not is_bpb) or (INVALID_VAL_BPB_FLOOR <= p["value"] <= CRASH_THRESHOLD)
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

    # Baseline-to-beat: dark-black dashed reference line.
    if (baseline_to_beat is not None and math.isfinite(baseline_to_beat)
            and ((not is_bpb) or baseline_to_beat >= INVALID_VAL_BPB_FLOOR)):
        ax.axhline(baseline_to_beat, color=DARK_TEXT_HI, linestyle="--",
                   linewidth=0.9, alpha=0.50, zorder=1)

    # Time axis formatting
    span = min(
        times[-1] - times[0] if len(times) > 1 else dt.timedelta(hours=1),
        dt.timedelta(hours=MAX_DAY_CHART_WINDOW_HOURS),
    )
    span_h = span.total_seconds() / 3600.0
    if span_h <= 2:
        loc = mdates.MinuteLocator(byminute=[0, 30])
    elif span_h <= 12:
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
        ax.text(0.012, 0.985, panel_label.upper(), transform=ax.transAxes,
                fontsize=7.2, color=DARK_TEXT, ha="left", va="top",
                fontweight="bold",
                bbox=dict(boxstyle="square,pad=0.18",
                          facecolor=DARK_BG,
                          edgecolor=DARK_RULE_HI,
                          linewidth=0.45,
                          alpha=0.92),
                zorder=6)
    if (baseline_to_beat is not None and math.isfinite(baseline_to_beat)
            and ((not is_bpb) or baseline_to_beat >= INVALID_VAL_BPB_FLOOR)):
        baseline_value = f"{baseline_to_beat:.4f}" if is_bpb else f"{baseline_to_beat:.3f}×"
        ax.set_title(f"PRIOR DAY {metric_name.upper()}  ·  {baseline_value}",
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
        time_label = f"{start} UTC" if start == end else f"{start}-{end} UTC"
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
            panel_label=f"panel {idx}/{len(chunks)} · {time_label}",
            prior_best=prior_best,
        )
        paths.append(path)
        total += n
        for _, rec in chunk:
            v = rec.get("value")
            if (isinstance(v, (int, float)) and math.isfinite(v)
                    and ((not _is_bpb_metric(metric_name)) or INVALID_VAL_BPB_FLOOR <= v <= 3.0)):
                prior_best = v if prior_best is None else min(prior_best, v)
    return paths, total


def week_focus_chart(out_path: str | Path,
                     week_dates: list[str],
                     daily_counts: list[dict],
                     current_date: str | None = None) -> tuple[str, int]:
    """Stacked percent bars for category-local daily focus inside one week."""
    rows = []
    for date in week_dates:
        counts = next((d.get("counts", {}) for d in daily_counts if d.get("date") == date), {})
        total = sum(int(counts.get(camp, 0) or 0) for camp in ("experimental", "neural", "kernel"))
        rows.append({"date": date, "counts": counts, "total": total})

    out_path = Path(out_path)
    fig_w = max(6.8, min(10.8, 1.05 * max(1, len(rows)) + 2.6))
    fig, ax = plt.subplots(figsize=(fig_w, 3.8))
    x = list(range(len(rows)))
    bottoms = [0.0 for _ in rows]
    order = ("experimental", "neural", "kernel")
    hatch = {"experimental": "", "neural": "////", "kernel": "xx"}

    for camp in order:
        vals = []
        for row in rows:
            total = row["total"]
            vals.append(100.0 * int(row["counts"].get(camp, 0) or 0) / total if total else 0.0)
        ax.bar(
            x,
            vals,
            bottom=bottoms,
            color=CAMP_COLOR.get(camp, COVER_BLACK),
            edgecolor=COVER_BLACK,
            linewidth=0.8,
            hatch=hatch.get(camp, ""),
            label=CAMP_LABEL.get(camp, camp),
        )
        bottoms = [b + v for b, v in zip(bottoms, vals)]

    for idx, row in enumerate(rows):
        if row["date"] == current_date:
            ax.axvline(idx, color=COVER_BLACK, linewidth=1.6, alpha=0.95)
        if row["total"]:
            ax.text(
                idx,
                103,
                str(row["total"]),
                ha="center",
                va="bottom",
                fontsize=7.5,
                color=COVER_BLACK,
            )

    labels = [d[-5:] for d in week_dates]
    ax.set_title("WEEK-LOCAL DAILY FOCUS SPLIT")
    ax.set_ylabel("% measured rows")
    ax.set_xlabel("campaign day in week")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=0)
    ax.set_ylim(0, 110)
    ax.yaxis.set_major_locator(plt.MultipleLocator(25))
    ax.grid(axis="y", alpha=0.35)
    ax.grid(axis="x", alpha=0.0)
    ax.legend(loc="upper left", ncol=3, fontsize=7.5)
    fig.text(
        0.99,
        0.01,
        "bar height = category share of category-local measured rows; top number = row count",
        ha="right",
        va="bottom",
        fontsize=7.0,
        color=COVER_BLACK,
    )
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return str(out_path), len(rows)


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
    journey_points = [
        {"date": x, "value": y, "camp": c}
        for x, y, c in zip(dates, bests, camps)
    ]
    _assign_delta_pins(journey_points)

    fig, ax = plt.subplots(figsize=(11.0, 4.0))

    # Per-day scatter colored by camp
    by_camp: dict[str, list[tuple]] = {}
    for p in journey_points:
        by_camp.setdefault(p["camp"], []).append(p)
    for c, items in by_camp.items():
        ax.scatter([p["date"] for p in items], [p["value"] for p in items],
                   color=CAMP_COLOR.get(c, DARK_TEXT_MUTE),
                   marker=CAMP_MARKER.get(c, "o"),
                   s=34, alpha=0.85, edgecolors=DARK_BG, linewidths=0.4,
                   label=f"{CAMP_LABEL.get(c, c)} ({len(items)})",
                   zorder=3)
        _draw_delta_pins(ax, items, "date")

    # Running-minimum line
    running_min = []
    cur = float("inf")
    for v in bests:
        cur = min(cur, v)
        running_min.append(cur)
    ax.plot(dates, running_min, color=DARK_ACCENT, linewidth=1.4,
            alpha=0.7, zorder=2, label="personal best (running min)")

    # Reference baseline
    if reference_baseline is not None and math.isfinite(reference_baseline):
        ax.axhline(reference_baseline, color="#2b0000", linestyle="--",
                   linewidth=1.0, alpha=0.8, zorder=1)
        ax.annotate(f"{reference_label} = {reference_baseline:.4f}",
                    xy=(1.0, reference_baseline),
                    xycoords=("axes fraction", "data"),
                    xytext=(-2, 4), textcoords="offset points",
                    fontsize=8, color="#2b0000", ha="right")

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
                        fontsize=7.5, color=DARK_TEXT, ha="center",
                        arrowprops=dict(arrowstyle="-", color=DARK_RULE,
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


# ---------- CHART C ----------------------------------------------------------

def week_chart(out_path: str | Path,
               week_label: str,
               daily_points: list[dict],
               metric_name: str = "val_bpb") -> tuple[str, int]:
    """Weekly rollup plot.

    Each point is one rendered daily report, not one training run. Mixed-metric
    weeks should call this once per metric so the y-axis remains honest.
    daily_points: {"date": "YYYY-MM-DD", "value": float, "camp": str,
                   "title": str, "n": int}
    """
    if not daily_points:
        return _stub(out_path, f"{metric_name} - {week_label}", "no daily points"), 0

    pts = []
    for p in daily_points:
        value = p.get("value")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        try:
            date = dt.datetime.strptime(str(p.get("date")), "%Y-%m-%d")
        except ValueError:
            continue
        pts.append({
            "date": date,
            "value": float(value),
            "camp": p.get("camp", "neural"),
            "title": p.get("title", ""),
            "n": int(p.get("n") or len(pts) + 1),
        })
    if not pts:
        return _stub(out_path, f"{metric_name} - {week_label}", "no plottable daily points"), 0
    pts.sort(key=lambda p: p["date"])
    _assign_delta_pins(pts)

    fig, ax = plt.subplots(figsize=(9.0, 3.6))
    dates = [p["date"] for p in pts]
    values = [p["value"] for p in pts]
    is_bpb = _is_bpb_metric(metric_name)

    if is_bpb:
        ax.axhspan(0, INVALID_VAL_BPB_FLOOR, facecolor=DARK_INVALID_ZONE,
                   alpha=1.0, edgecolor="none", linewidth=0, zorder=0)
        ax.axhline(INVALID_VAL_BPB_FLOOR, color=DARK_RULE_HI, linestyle="-",
                   linewidth=0.65, alpha=0.55, zorder=1)

    ax.plot(dates, values, color=DARK_RULE_HI, linewidth=0.85,
            alpha=0.62, zorder=1, label="_week")

    by_camp: dict[str, list[dict]] = {}
    for p in pts:
        by_camp.setdefault(p["camp"], []).append(p)
    for camp, items in by_camp.items():
        color = CAMP_COLOR.get(camp, DARK_TEXT_MUTE)
        ax.scatter([it["date"] for it in items],
                   [it["value"] for it in items],
                   color=color,
                   marker=CAMP_MARKER.get(camp, "o"),
                   s=POINT_SIZE, alpha=0.95,
                   edgecolors=DARK_BG, linewidths=POINT_EDGE_WIDTH,
                   label=f"{CAMP_LABEL.get(camp, camp).upper()} · {len(items)}",
                   zorder=3)
        _draw_delta_pins(ax, items, "date")

    real_values = [p["value"] for p in pts if (not is_bpb) or p["value"] <= 3.0]
    if real_values:
        if is_bpb:
            y_lo = INVALID_VAL_BPB_FLOOR - 0.12
            data_max = max(real_values)
            y_hi = data_max + 0.12 * max(0.4, data_max - y_lo)
        else:
            data_min = min(real_values)
            data_max = max(real_values)
            data_range = max(0.04, data_max - data_min)
            y_lo = max(0.0, data_min - 0.18 * data_range)
            y_hi = data_max + 0.18 * data_range
        ax.set_ylim(y_lo, y_hi)

    start = dates[0] - dt.timedelta(hours=12)
    end = dates[-1] + dt.timedelta(hours=12)
    if start == end:
        end = start + dt.timedelta(days=1)
    ax.set_xlim(start, end)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    ax.set_xlabel("DATE (UTC) - LEFT->RIGHT = WEEK'S DAILY REPORTS",
                  labelpad=8, fontsize=8.5, color=DARK_TEXT,
                  fontweight="normal")
    ax.set_ylabel(metric_name.upper(), labelpad=8, fontsize=9, color=DARK_TEXT)
    ax.set_title(f"{metric_name.upper()}  ·  {week_label}", loc="left", pad=10,
                 fontsize=10.5, fontweight="bold", color=DARK_TEXT_HI)
    if by_camp:
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


# ---------- CHART D ----------------------------------------------------------

def campaign_overlay_chart(out_path: str | Path,
                           campaign_label: str,
                           category_points: list[dict],
                           metric_name: str = "val_bpb") -> tuple[str, int]:
    """Campaign cumulative plot with classifications overlaid.

    Each point is one category-local daily datapoint. The caller must keep the
    metric homogeneous; this helper overlays classifications on one y-axis but
    never mixes BPB with kernel-ratio values.
    category_points: {"date": "YYYY-MM-DD", "value": float, "camp": str,
                      "title": str, "n": int}
    """
    if not category_points:
        return _stub(out_path, f"{metric_name} - {campaign_label}", "no category points"), 0

    pts = []
    for p in category_points:
        value = p.get("value")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        try:
            date = dt.datetime.strptime(str(p.get("date")), "%Y-%m-%d")
        except ValueError:
            continue
        pts.append({
            "date": date,
            "value": float(value),
            "camp": p.get("camp") or p.get("category") or "neural",
            "title": p.get("title", ""),
            "n": int(p.get("n") or len(pts) + 1),
        })
    if not pts:
        return _stub(out_path, f"{metric_name} - {campaign_label}", "no plottable category points"), 0
    pts.sort(key=lambda p: (p["date"], p["camp"]))
    _assign_delta_pins(pts)

    fig, ax = plt.subplots(figsize=(10.8, 4.0))
    dates = [p["date"] for p in pts]
    values = [p["value"] for p in pts]
    is_bpb = _is_bpb_metric(metric_name)

    if is_bpb:
        ax.axhspan(0, INVALID_VAL_BPB_FLOOR, facecolor=DARK_INVALID_ZONE,
                   alpha=1.0, edgecolor="none", linewidth=0, zorder=0)
        ax.axhline(INVALID_VAL_BPB_FLOOR, color=DARK_RULE_HI, linestyle="-",
                   linewidth=0.65, alpha=0.55, zorder=1)

    order = ("kernel", "experimental", "neural", "daily_grind")
    by_camp: dict[str, list[dict]] = {}
    for p in pts:
        by_camp.setdefault(p["camp"], []).append(p)
    ordered_camps = [c for c in order if c in by_camp] + [
        c for c in sorted(by_camp) if c not in order
    ]

    for camp in ordered_camps:
        items = sorted(by_camp[camp], key=lambda p: p["date"])
        color = CAMP_COLOR.get(camp, DARK_TEXT_MUTE)
        if len(items) >= 2:
            ax.plot([it["date"] for it in items],
                    [it["value"] for it in items],
                    color=color, linewidth=0.9, alpha=0.55,
                    zorder=1, label="_nolegend_")
        ax.scatter([it["date"] for it in items],
                   [it["value"] for it in items],
                   color=color,
                   marker=CAMP_MARKER.get(camp, "o"),
                   s=POINT_SIZE, alpha=0.95,
                   edgecolors=DARK_BG, linewidths=POINT_EDGE_WIDTH,
                   label=f"{CAMP_LABEL.get(camp, camp).upper()} · {len(items)}",
                   zorder=3)
        _draw_delta_pins(ax, items, "date")

    real_values = [p["value"] for p in pts if (not is_bpb) or p["value"] <= 3.0]
    if real_values:
        data_min = min(real_values)
        data_max = max(real_values)
        if is_bpb:
            y_lo = min(INVALID_VAL_BPB_FLOOR - 0.12, data_min - 0.04)
            y_lo = max(0.4, y_lo)
            data_range = max(0.4, data_max - y_lo)
            y_hi = data_max + 0.12 * data_range
        else:
            data_range = max(0.04, data_max - data_min)
            y_lo = max(0.0, data_min - 0.18 * data_range)
            y_hi = data_max + 0.18 * data_range
        ax.set_ylim(y_lo, y_hi)

    start = dates[0] - dt.timedelta(days=2)
    end = dates[-1] + dt.timedelta(days=2)
    if start == end:
        end = start + dt.timedelta(days=1)
    ax.set_xlim(start, end)
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    ax.set_xlabel("DATE (UTC) - LEFT->RIGHT = CAMPAIGN COURSE",
                  labelpad=8, fontsize=8.5, color=DARK_TEXT,
                  fontweight="normal")
    ax.set_ylabel(metric_name.upper(), labelpad=8, fontsize=9, color=DARK_TEXT)
    ax.set_title(f"{metric_name.upper()}  ·  {campaign_label}", loc="left", pad=10,
                 fontsize=10.5, fontweight="bold", color=DARK_TEXT_HI)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.26),
              framealpha=0.92,
              edgecolor=DARK_RULE_HI, facecolor=DARK_BG,
              fontsize=7.5, ncol=max(1, min(3, len(ordered_camps))),
              columnspacing=1.1, handletextpad=0.5, borderpad=0.5)

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.25, top=0.86)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return str(out_path), len(pts)


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
