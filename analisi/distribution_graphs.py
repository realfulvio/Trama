"""Box and violin plots with explicit quartile, whisker and density rules.

Percentiles use the 1-based rank r = (N + 1) p with linear interpolation,
saturated at the extremes (Hyndman–Fan definition 6). NumPy's default method
differs, so the arithmetic lives here and the plot receives resolved statistics.
"""
from dataclasses import dataclass, field

from matplotlib.colors import to_rgba
import numpy as np
import pandas as pd

from .category_graphs import COLORS, MAX_POINTS, PLACEMENTS, _spread
from .pairwise_graph import register_anchors
from .presentation import GraphGroup, register_groups
from .processing import FieldError, _column
from .reporting import Result, _plot, _report


BOX_VIOLIN = "Box / violin plot"
SINGLE, SEPARATE = INPUT_MODES = ("Single response", "Separate columns")
BOX, VIOLIN = STYLES = ("Box", "Violin")
TUKEY, MIN_MAX, P10, P5, P2_5, P1, ALL_POINTS = WHISKERS = (
    "Tukey", "Min to max", "10–90", "5–95", "2.5–97.5", "1–99", "Min to max with all observations")
PERCENTILE_WHISKERS = {P10: 10., P5: 5., P2_5: 2.5, P1: 1.}
OPTIONS = {
    "Input": INPUT_MODES, "Response": None, "Group": "Optional", "Variables": "Multiple (optional)",
    "Style": STYLES, "Whiskers": WHISKERS, "Show mean": False, "Overlay observations": False,
    "Point placement": PLACEMENTS, "Bandwidth multiplier": 1.0, "Median line": True, "Quartile lines": True,
}
MAX_GROUPS = 40
GRID_POINTS = 200
MAX_KDE_EVALUATIONS = 20_000_000
FENCE_TOLERANCE = 8 * np.finfo(float).eps
MINIMUM_FOR_BOX = 4
HALF_WIDTH = .4
BOX_WIDTH = .56
QUARTILE_NOTE = "Quartiles and percentiles: rank (N + 1) p, linear interpolation, saturated at min and max."


def visibility(input_mode, style, whiskers, overlay):
    """Fields that apply to the chosen input mode and graph style."""
    box, violin = style == BOX, style == VIOLIN
    all_points = box and whiskers == ALL_POINTS
    return {"Response": input_mode == SINGLE, "Group": input_mode == SINGLE, "Variables": input_mode == SEPARATE,
            "Whiskers": box, "Overlay observations": not all_points,
            "Point placement": all_points or bool(overlay),
            "Bandwidth multiplier": violin, "Median line": violin, "Quartile lines": violin}


def _percentile(ordered, percent):
    n = len(ordered)
    rank = min(max((n + 1) * percent / 100, 1.), float(n))
    low = int(np.floor(rank))
    high = min(low + 1, n)
    fraction = rank - low
    first = ordered[low - 1]
    if fraction == 0:
        return float(first)
    with np.errstate(over="ignore", invalid="ignore"):
        return float(first * (1 - fraction) + ordered[high - 1] * fraction)


@dataclass
class _Group:
    label: object
    values: np.ndarray
    rows: np.ndarray
    color: str
    x: float = 0.
    stats: dict | None = None
    note: str = ""
    identity: str = ""
    artists: list = field(default_factory=list)


def _identity(mode, grouped, label):
    """Source identity of a group: it does not depend on the order or on the other groups present."""
    if mode == SEPARATE:
        return f"column:{label}"
    if not grouped:
        return "all"
    value = label.item() if isinstance(label, np.generic) else label
    if isinstance(value, bool):
        return f"category:bool:{value}"
    if isinstance(value, int):
        return f"category:int:{value}"
    if isinstance(value, float):
        return f"category:float:{value!r}"
    if isinstance(value, str):
        return f"category:str:{value}"
    if isinstance(value, pd.Timestamp):
        return f"category:datetime:{value.isoformat()}"
    return f"category:{type(value).__name__}:{value!r}"


def _flag(options, name, default):
    value = options.get(name, default)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name}: choose on or off.")
    return bool(value)


def _choice(options, name, choices):
    value = options.get(name, choices[0])
    if value not in choices:
        raise FieldError(name, f"Choose a valid {name.lower()}.")
    return value


def _multiplier(options):
    value = options.get("Bandwidth multiplier", 1.)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError("Bandwidth multiplier", "The bandwidth multiplier must be a number.")
    value = float(value)
    if not np.isfinite(value) or value <= 0:
        raise FieldError("Bandwidth multiplier", "The bandwidth multiplier must be finite and greater than zero.")
    return value


def _selected(frame, options, mode):
    """Return the observations of each group in order of appearance (sheet order for columns)."""
    if not frame.columns.is_unique:
        raise FieldError("Variables" if mode == SEPARATE else "Response", "Worksheet column names must be unique.")
    omitted = []
    if mode == SEPARATE:
        names = options.get("Variables", [])
        if (not isinstance(names, (list, tuple)) or not names
                or any(not isinstance(name, str) or name not in frame for name in names)
                or len(set(names)) != len(names)):
            raise FieldError("Variables", "Choose distinct numeric columns, one distribution per column.")
        names = [name for name in frame.columns if name in set(names)]
        groups = []
        for name in names:
            numbers = _column(frame, name, "Variables").to_numpy(dtype=float)
            keep = np.isfinite(numbers)
            if keep.any():
                groups.append((name, numbers[keep], np.flatnonzero(keep) + 1))
            else:
                omitted.append(str(name))
        return groups, omitted, "", "Value"
    response, group = options.get("Response"), options.get("Group") or None
    if group is not None and (not isinstance(group, str) or group not in frame):
        raise FieldError("Group", "Choose an existing grouping column.")
    if group == response:
        raise FieldError("Group", "Choose a grouping column different from the response.")
    numbers = _column(frame, response, "Response").to_numpy(dtype=float)
    finite = np.isfinite(numbers)
    if group is None:
        return ([("All", numbers[finite], np.flatnonzero(finite) + 1)] if finite.any() else []), [], "", response
    labels = frame[group]
    present = labels.notna().to_numpy()
    levels = pd.unique(labels[present])
    groups = []
    for level in levels:
        member = present & labels.eq(level).to_numpy(dtype=bool, na_value=False)
        keep = member & finite
        if keep.any():
            groups.append((level, numbers[keep], np.flatnonzero(keep) + 1))
        else:
            omitted.append(str(level))
    return groups, omitted, group, response


def _statistics(group, whiskers):
    values = group.values
    ordered = np.sort(values)
    n = len(ordered)
    with np.errstate(over="ignore", invalid="ignore"):
        mean = float(np.mean(values))
    stats = {"n": n, "min": float(ordered[0]), "max": float(ordered[-1]), "mean": mean,
             "median": _percentile(ordered, 50.), "q1": np.nan, "q3": np.nan}
    if not np.isfinite(mean):
        raise FieldError("Response", "The selected values exceed the numeric range for this graph.")
    if n < MINIMUM_FOR_BOX:
        stats.update(low=stats["min"], high=stats["max"], outside=np.zeros(n, dtype=bool), reduced=True)
        group.note = f"N = {n}: median and range only."
        return stats
    q1, q3 = _percentile(ordered, 25.), _percentile(ordered, 75.)
    stats.update(q1=q1, q3=q3, reduced=False)
    outside = np.zeros(n, dtype=bool)
    if whiskers == TUKEY:
        with np.errstate(over="ignore", invalid="ignore"):
            iqr = q3 - q1
            spread = 1.5 * iqr
            lower, upper = q1 - spread, q3 + spread
        if not np.isfinite([iqr, lower, upper]).all():
            raise FieldError("Response", "The selected values exceed the numeric range for this graph.")
        tolerance = FENCE_TOLERANCE * max(abs(q1), abs(q3), iqr)
        inside = (values >= lower - tolerance) & (values <= upper + tolerance)
        low, high = float(values[inside].min()), float(values[inside].max())
        outside = ~inside
    elif whiskers in PERCENTILE_WHISKERS:
        percent = PERCENTILE_WHISKERS[whiskers]
        low, high = _percentile(ordered, percent), _percentile(ordered, 100 - percent)
        outside = (values < low) | (values > high)
    else:
        low, high = stats["min"], stats["max"]
    stats.update(low=low, high=high, outside=outside)
    return stats


def _density(values, multiplier):
    """Gaussian KDE with Scott's factor on a grid that includes both observed extremes."""
    n = len(values)
    if n < 2 or values.min() == values.max():
        return None
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        spread = float(np.std(values, ddof=1))
        bandwidth = multiplier * n ** (-1 / 5) * spread
        if not np.isfinite(bandwidth) or bandwidth <= 0:
            raise FieldError("Bandwidth multiplier", "The bandwidth is outside the supported numeric range.")
        grid = np.linspace(values.min(), values.max(), GRID_POINTS)
        density = np.zeros(GRID_POINTS)
        for start in range(0, n, 2000):
            z = (grid[:, None] - values[None, start:start + 2000]) / bandwidth
            density += np.exp(-.5 * z * z).sum(axis=1)
        density /= n * bandwidth * np.sqrt(2 * np.pi)
    if not np.isfinite(density).all() or density.max() <= 0:
        raise FieldError("Bandwidth multiplier", "The density is outside the supported numeric range.")
    return grid, density, bandwidth


def _draw_box(axes, boxes, width=BOX_WIDTH):
    reduced = [group for group in boxes if group.stats["reduced"]]
    full = [group for group in boxes if not group.stats["reduced"]]
    if full:
        summaries = [{"med": g.stats["median"], "q1": g.stats["q1"], "q3": g.stats["q3"], "mean": g.stats["mean"],
                      "whislo": g.stats["low"], "whishi": g.stats["high"], "cilo": np.nan, "cihi": np.nan,
                      "fliers": g.values[g.stats["outside"]]} for g in full]
        drawn = axes.bxp(summaries, positions=[g.x for g in full], widths=width, patch_artist=True,
                         showmeans=False, showfliers=True, manage_ticks=False, flierprops={"marker": "o", "markersize": 4})
        for index, group in enumerate(full):
            color = group.color
            drawn["boxes"][index].set(facecolor=to_rgba(color, .24), edgecolor=color, linewidth=1.3)
            group.artists.append((drawn["boxes"][index], "fill"))
            for line in (*drawn["whiskers"][2 * index:2 * index + 2], *drawn["caps"][2 * index:2 * index + 2]):
                line.set(color=color, linewidth=1.3)
                group.artists.append((line, "line"))
            drawn["medians"][index].set(color=color, linewidth=2.2)
            drawn["fliers"][index].set(markerfacecolor="white", markeredgecolor=color)
            group.artists.extend([(drawn["medians"][index], "line"), (drawn["fliers"][index], "marker")])
    for group in reduced:
        stats, color = group.stats, group.color
        group.artists.extend((artist, "line") for artist in (
            axes.vlines(group.x, stats["min"], stats["max"], color=color, linewidth=1.3),
            axes.hlines([stats["min"], stats["max"]], group.x - width / 8, group.x + width / 8,
                        color=color, linewidth=1.3),
            axes.hlines(stats["median"], group.x - width / 2, group.x + width / 2, color=color, linewidth=2.2)))


def _draw_violin(axes, group, multiplier, median_line, quartile_lines, density_rows, widths,
                 half_width=HALF_WIDTH, labels=None):
    """Draw one violin; ``labels`` names the leading columns of its density rows (default: Group)."""
    stats, color = group.stats, group.color
    fit = _density(group.values, multiplier)
    if fit is None:
        if stats["n"] == 1:
            group.note = "N = 1: one observation, no density."
            group.artists.extend((artist, "line") for artist in axes.plot(
                [group.x], [stats["min"]], marker="o", color=color, markersize=6, linestyle="none"))
        else:
            group.note = f"N = {stats['n']}: constant values, no density."
            group.artists.append((axes.hlines(stats["min"], group.x - half_width / 2, group.x + half_width / 2,
                                              color=color, linewidth=2.2), "line"))
        return None
    grid, density, bandwidth = fit
    half = half_width * density / density.max()
    group.artists.append((axes.fill_betweenx(grid, group.x - half, group.x + half, facecolor=to_rgba(color, .3),
                                             edgecolor=color, linewidth=1.3), "fill"))
    density_rows.append(pd.DataFrame({**(labels or {"Group": group.label}), "Value": grid, "Density": density,
                                      "Half-width": half}))
    levels = []
    if median_line:
        levels.append((stats["median"], 2.2, "-"))
    if quartile_lines and not stats["reduced"]:
        levels.extend((stats[key], 1.2, "--") for key in ("q1", "q3"))
    for level, thickness, style in levels:
        reach = float(np.interp(level, grid, half))
        group.artists.append((axes.hlines(level, group.x - reach, group.x + reach, color=color,
                                          linewidth=thickness, linestyle=style), "line"))
    if stats["n"] < MINIMUM_FOR_BOX:
        group.note = f"N = {stats['n']}: median shown, quartiles not drawn."
    widths[group.x] = bandwidth
    return bandwidth


def rule_settings(style, whiskers, multiplier):
    """Settings rows that state the whisker rule of a box or the density estimate of a violin."""
    if style == BOX:
        return {"Whiskers": whiskers,
                "Whisker rule": ("Most extreme observation within Q1 − 1.5 IQR and Q3 + 1.5 IQR, limits included."
                                 if whiskers == TUKEY else "Whiskers end at the interpolated percentiles."
                                 if whiskers in PERCENTILE_WHISKERS else "Whiskers end at the minimum and maximum.")}
    return {
        "Bandwidth rule": "Gaussian kernel, h = multiplier × N^(−1/5) × sample SD (Scott's factor)",
        "Bandwidth multiplier": multiplier,
        "Density grid": f"{GRID_POINTS} equally spaced values from the observed minimum to the maximum",
        "Width scale": "The maximum density of every violin is drawn at the same width; width does not encode N.",
        "Density table": "Densities are not renormalized after truncation at the observed range."}


def box_violin(frame, options):
    mode = _choice(options, "Input", INPUT_MODES)
    style = _choice(options, "Style", STYLES)
    whiskers = _choice(options, "Whiskers", WHISKERS)
    show_mean = _flag(options, "Show mean", False)
    all_points = style == BOX and whiskers == ALL_POINTS
    overlay = all_points or _flag(options, "Overlay observations", False)
    placement = _choice(options, "Point placement", PLACEMENTS)
    multiplier = _multiplier(options) if style == VIOLIN else 1.
    median_line = _flag(options, "Median line", True)
    quartile_lines = _flag(options, "Quartile lines", True)
    selected, omitted, group_name, response = _selected(frame, options, mode)
    field = "Variables" if mode == SEPARATE else "Response"
    if not selected:
        raise FieldError(field, "The selection has no numeric observations.")
    if len(selected) > MAX_GROUPS:
        raise FieldError("Variables" if mode == SEPARATE else "Group", f"Plot up to {MAX_GROUPS} groups at once.")
    total = sum(len(values) for _, values, _ in selected)
    if total > MAX_POINTS:
        raise FieldError(field, "Select fewer observations to draw this graph.")
    if style == VIOLIN and total * GRID_POINTS > MAX_KDE_EVALUATIONS:
        raise FieldError(field, "Select fewer observations for the density estimate.")
    grouped = mode == SINGLE and bool(group_name)
    groups = [_Group(label, values, rows, COLORS[index % len(COLORS)], float(index + 1),
                     identity=_identity(mode, grouped, label))
              for index, (label, values, rows) in enumerate(selected)]
    for group in groups:
        group.stats = _statistics(group, whiskers)
    figure, axes = _plot(style + " plot", group_name if mode == SINGLE else "", response)
    density_rows, bandwidths = [], {}
    if style == BOX:
        _draw_box(axes, groups)
    else:
        for group in groups:
            _draw_violin(axes, group, multiplier, median_line, quartile_lines, density_rows, bandwidths)
    rng = np.random.default_rng(0)
    plotted = []
    for group in groups:
        stats = group.stats
        outside = stats["outside"] if style == BOX else np.zeros(len(group.values), dtype=bool)
        shown = np.ones(len(group.values), dtype=bool) if overlay else outside
        if shown.any():
            inner = shown & ~outside
            if inner.any():
                x = group.x + _spread(group.values[inner], placement, HALF_WIDTH * 2, rng)
                group.artists.append((axes.scatter(x, group.values[inner], s=22, color=group.color,
                                                   edgecolors="white", linewidths=.6, zorder=3.5), "point"))
            plotted.append(pd.DataFrame({"Group": group.label, "Row": group.rows[shown], "Value": group.values[shown],
                                         "Role": np.where(outside[shown], "Outside whiskers", "Overlay")}))
        if show_mean:
            group.artists.append((axes.scatter([group.x], [stats["mean"]], marker="D", s=34, color="white",
                                               edgecolors=group.color, linewidths=1.4, zorder=5), "mean"))
    axes.set_xticks([g.x for g in groups], [str(g.label) for g in groups], rotation=20)
    axes._tramastat_numeric_axes = ("y",)
    axes._tramastat_categorical_axes = ("x",)
    for label in axes.get_xticklabels():
        label.set_parse_math(False)
    axes.set_xlim(.4, len(groups) + .6)
    kind = style.lower()
    register_groups(axes, [GraphGroup(f"{kind}:{g.identity}", str(g.label), kind, g.x, g.artists)
                           for g in groups if len(f"{kind}:{g.identity}") <= 1024])
    # Every element of a group is drawn at or below its maximum (whiskers, outliers, overlay, mean, density grid).
    register_anchors(axes, {g.identity: {"x": g.x, "top": g.stats["max"], "name": str(g.label),
                                         "group": f"{kind}:{g.identity}"} for g in groups})
    summary = {"Group": [g.label for g in groups], "N": [g.stats["n"] for g in groups],
               "Median": [g.stats["median"] for g in groups], "Minimum": [g.stats["min"] for g in groups],
               "Q1": [g.stats["q1"] for g in groups], "Q3": [g.stats["q3"] for g in groups],
               "Maximum": [g.stats["max"] for g in groups], "Mean": [g.stats["mean"] for g in groups]}
    if style == BOX:
        summary.update({"Lower whisker": [g.stats["low"] for g in groups],
                        "Upper whisker": [g.stats["high"] for g in groups],
                        "Outside whiskers": [int(g.stats["outside"].sum()) for g in groups]})
    else:
        summary["Bandwidth"] = [bandwidths.get(g.x, np.nan) for g in groups]
    summary["Note"] = [g.note for g in groups]
    settings = {"Input": mode, "Style": style, "Percentiles": QUARTILE_NOTE,
                "Displayed with fewer than 4 observations": "Median and range."}
    settings.update(rule_settings(style, whiskers, multiplier))
    if omitted:
        settings["Omitted (no observations)"] = ", ".join(omitted)
    tables = {"Group summary": pd.DataFrame(summary)}
    if plotted:
        tables["Plotted observations"] = pd.concat(plotted, ignore_index=True)
    if density_rows:
        tables["Violin density"] = pd.concat(density_rows, ignore_index=True)
    tables["Settings"] = _report(settings)
    return Result(tables, figure)
