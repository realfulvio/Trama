"""Area under the curve split into signed regions and optional peak filters.

The totals (above, below, net) always come from the whole observed trace; the peak thresholds only choose
which regions are listed and summed as retained peaks.
"""
import numpy as np
import pandas as pd

from . import exploration
from .processing import FieldError, _number
from .reporting import Result, _plot, _report

PEAKS, HEIGHT, WIDTH = "Peaks", "Minimum height (%)", "Minimum width"
OFF, ABOVE, BOTH = "Off", "Above baseline", "Above and below"
MODES = (OFF, ABOVE, BOTH)
DEFAULT_HEIGHT = 10.0
TOLERANCE = 1e-12
COLUMNS = ["Peak", "Side", "Start X", "End X", "Peak X", "Height", "Duration", "Area", "Signed area",
           "Fraction of retained area (%)", "Truncated"]
ABOVE_COLOR, BELOW_COLOR, EXCLUDED_COLOR = "#3b7ea1", "#aa5440", "#9aa5ab"


def check_options(options):
    """Validate the optional peak fields of a saved or typed recipe; old recipes simply have none."""
    mode = options.get(PEAKS, OFF)
    if mode not in MODES:
        raise FieldError(PEAKS, "Choose Off, Above baseline or Above and below.")
    if mode == OFF:
        return OFF, DEFAULT_HEIGHT, 0.0
    height = _number(options.get(HEIGHT, DEFAULT_HEIGHT), HEIGHT)
    if not 0 <= height <= 100:
        raise FieldError(HEIGHT, f"{HEIGHT} must be between 0 and 100.")
    width = _number(options.get(WIDTH, 0.0), WIDTH)
    if width < 0:
        raise FieldError(WIDTH, f"{WIDTH} must not be negative.")
    return mode, height, width


def _polyline(xx, yy):
    """Observed points plus the linearly interpolated baseline crossings: (x, y, observed index or -1)."""
    points = [(xx[0], yy[0], 0)]
    for i in range(len(xx) - 1):
        left, right = yy[i], yy[i + 1]
        if np.sign(left) * np.sign(right) < 0:
            root = xx[i] + (xx[i + 1] - xx[i]) * (abs(left) / (abs(left) + abs(right)))
            points.append((min(max(root, xx[i]), xx[i + 1]), 0.0, -1))
        points.append((xx[i + 1], right, i + 1))
    return points


def regions(xx, yy):
    """Contiguous constant-sign regions of ``yy`` (already shifted by the baseline), in X order."""
    points = _polyline(xx, yy)
    found, current = [], None
    for first, second in zip(points, points[1:]):
        sign = np.sign(first[1] if first[1] != 0 else second[1])
        if sign == 0:
            current = None
            continue
        if current is None or current["sign"] != sign or first[1] == 0:
            current = {"sign": int(sign), "points": [first]}
            found.append(current)
        current["points"].append(second)
    last = len(xx) - 1
    for region in found:
        pts = region["points"]
        x, y = np.array([p[0] for p in pts]), np.array([abs(p[1]) for p in pts])
        region.update(x=x, y=y, start=x[0], end=x[-1], area=float(np.sum(np.diff(x) * (y[:-1] + y[1:]) / 2)),
                      height=float(y.max()), peak_x=float(x[int(np.argmax(y))]),
                      start_cut=pts[0][2] == 0 and pts[0][1] != 0, end_cut=pts[-1][2] == last and pts[-1][1] != 0)
        region["duration"] = float(region["end"] - region["start"])
    return found


def _at_least(value, limit):
    return value >= limit or bool(np.isclose(value, limit, rtol=TOLERANCE, atol=0))


def _retained(found, mode, height_limit, width):
    return [r for r in found if (mode == BOTH or r["sign"] > 0)
            and _at_least(r["height"], height_limit) and _at_least(r["duration"], width)]


def _cut(region):
    return {(False, False): "No", (True, False): "Start", (False, True): "End", (True, True): "Start and end"}[
        region["start_cut"], region["end_cut"]]


def peak_table(kept):
    total = sum(r["area"] for r in kept)
    rows = [{"Peak": n, "Side": "Above" if r["sign"] > 0 else "Below", "Start X": float(r["start"]),
             "End X": float(r["end"]), "Peak X": r["peak_x"], "Height": r["height"], "Duration": r["duration"],
             "Area": r["area"], "Signed area": r["sign"] * r["area"],
             "Fraction of retained area (%)": 100 * r["area"] / total if total > 0 else np.nan,
             "Truncated": _cut(r)} for n, r in enumerate(kept, 1)]
    return pd.DataFrame(rows, columns=COLUMNS)


def area_peaks(frame, x, y, baseline=0.0, mode=OFF, min_height=DEFAULT_HEIGHT, min_width=0.0):
    """Return (totals, peak table, observed points, all regions, retained regions)."""
    report, data = exploration.area_under_curve(frame, x, y, baseline)
    if mode == OFF:
        return report, None, data, [], []
    xx, raw = data[x].to_numpy(dtype=float), data[y].to_numpy(dtype=float)
    found = regions(xx, raw - baseline)
    kept = _retained(found, mode, min_height / 100 * float(raw.max() - raw.min()), min_width)
    totals = {**report, "Total area (geometric)": report["Area above baseline"] + report["Area below baseline"],
              "Retained peak area": sum(r["area"] for r in kept), "Retained peaks": len(kept),
              "Regions found": len(found), PEAKS: mode, HEIGHT: min_height, WIDTH: min_width}
    return totals, peak_table(kept), data, found, kept


def auc_result(frame, o):
    """Workbench result for the Area under curve method, honouring old recipes without peak fields."""
    x, y, baseline = o["X"], o["Y"], o["Baseline"]
    mode, height, width = check_options(o)
    totals, peaks, points, found, kept = area_peaks(frame, x, y, baseline, mode, height, width)
    fig, ax = _plot("Area under curve", x, y)
    ax.plot(points[x], points[y], "o-")
    if mode == OFF:
        ax.axhline(baseline, color="#aaa")
        ax.fill_between(points[x], baseline, points[y], alpha=.22)
        return Result({"Area under curve": _report(totals), "Data": points}, fig)
    ax.axhline(baseline, color="#486075", linestyle="--", linewidth=1)
    kept_ids = {id(region) for region in kept}
    batches = {}
    for region in found:
        retained = id(region) in kept_ids
        label = ("Retained above" if region["sign"] > 0 else "Retained below") if retained else "Excluded"
        color = EXCLUDED_COLOR if not retained else ABOVE_COLOR if region["sign"] > 0 else BELOW_COLOR
        _, _, xs, ys = batches.setdefault(label, (color, .4 if retained else .18, [], []))
        # NaN separates independent polygons within one collection per category.
        xs.extend((region["x"], [np.nan]))
        ys.extend((baseline + region["sign"] * region["y"], [np.nan]))
    for label, (color, alpha, xs, ys) in batches.items():
        ax.fill_between(np.concatenate(xs), baseline, np.concatenate(ys), color=color, alpha=alpha, label=label)
    if batches:
        ax.legend(loc="best")
    return Result({"Area under curve": _report(totals), "Peaks": peaks, "Data": points}, fig)
