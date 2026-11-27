"""Native column and grouped plots from worksheet observations."""
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
import re
from sys import float_info

from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgba
import numpy as np
import pandas as pd
from scipy.stats import t

from .data import _worksheet_roles
from .grouped_bar_style import register_bars
from .pairwise_graph import register_anchors
from .processing import FieldError
from .reporting import Result, _plot
from .stats import geometric_interval_fields, geometric_summary
from .worksheet_column_identity import frame_ids
from .worksheet_row_identity import ROW_SPANS, current_spans, row_tokens
from .xy_series import SCALES as SERIES_SCALES, SIDES as SERIES_SIDES, _limit_pair


COLUMN_GRAPH, GROUPED_GRAPH = "Column graph", "Grouped graph"
BARS, POINTS, SYMBOLS, RANGE, PAIRED = "Bars", "Individual points", "Center and interval", "Floating range", "Before and after"
LINE_SYMBOLS = "Line and symbols"
GROUPED_STYLES = (BARS, POINTS, SYMBOLS, RANGE)
COLUMN_STYLES = (POINTS, BARS, SYMBOLS, RANGE, PAIRED)
AS_GRAPH = "As graph"
SERIES_STYLE = "Series style"
SERIES_DRAW_STYLES = (AS_GRAPH, BARS, SYMBOLS, LINE_SYMBOLS)
GROUPED_SERIES_COMPATIBLE_STYLES = frozenset({BARS, SYMBOLS})
INTERVALS = ("None", "SD", "SEM", "Confidence interval", "Range", "Interquartile range")
INTERVAL_DIRECTION = "Interval direction"
BOTH_INTERVALS, UPPER_INTERVAL, LOWER_INTERVAL = INTERVAL_DIRECTIONS = ("Both sides", "Upper only", "Lower only")
SERIES_INTERVAL_DIRECTION = "Series interval direction"
SERIES_SIDE = "Series side"
LEFT_SIDE, RIGHT_SIDE = SERIES_SIDES
RIGHT_AXIS_FIELDS = ("Right title", "Right minimum", "Right maximum", "Right scale")
PLACEMENTS = ("Spread exact ties", "Centered", "Jitter")
GEOMETRIC_CENTER = "Geometric mean"
_CENTERS = ("Mean", "Median")
OPTIONS = {"Center": (*_CENTERS, GEOMETRIC_CENTER), "Interval": INTERVALS, "Confidence level (%)": 95.,
           "Overlay observations": False, "Point placement": PLACEMENTS}
# Grouped graphs read raw replicates or summaries that were calculated elsewhere.
RAW, SUMMARIES = INPUTS = ("Raw replicates", "Precomputed summaries")
INTERLEAVED, SUPERIMPOSED, STACKED, PERCENT_STACKED = GROUP_PLACEMENTS = (
    "Interleaved", "Superimposed", "Stacked", "100% stacked")
STACKED_PLACEMENTS = frozenset({STACKED, PERCENT_STACKED})
SERIES_PLACEMENT = "Series placement"
GROUPED_SERIES_ORDER = "Grouped series order"
GROUPED_BAR_SPACING = "Grouped bar spacing"
BAR_BASELINE = "Bar baseline"
BAR_DIRECTION = "Bar direction"
VERTICAL_BARS, HORIZONTAL_BARS = BAR_DIRECTIONS = ("Vertical bars", "Horizontal bars")
BAR_SPACING_DEFAULTS = {"adjacent": 14., "groups": 45., "empty": 100., "leading": 50., "trailing": 50.}
BAR_SPACING_MAXIMUMS = {**dict.fromkeys(BAR_SPACING_DEFAULTS, 400.), "empty": 100.}
SIDE_BY_SIDE, OVERLAY_PREVIOUS, STACK_PREVIOUS, GAP_BEFORE = RELATIVE_PLACEMENTS = (
    "Beside previous", "Overlay previous", "Stack on previous", "Separate from previous")
DISTANCES, LIMITS = "Distances from estimate (minus/plus)", "Limits on axis (lower/upper)"
SUMMARY_ERRORS = ("None", "SD", "SEM", DISTANCES, LIMITS)
ENTERED_SEM, DERIVED_SEM = SEM_SOURCES = ("Entered SEM, else SD / √N", "SD / √N")
SUMMARY_STYLES = (BARS, SYMBOLS)
GROUPED_OPTIONS = {"Input": INPUTS, "Graph style": GROUPED_STYLES, "Placement of groups": GROUP_PLACEMENTS,
                   "Center": _CENTERS, "Interval": INTERVALS,
                   INTERVAL_DIRECTION: INTERVAL_DIRECTIONS,
                   "Confidence level (%)": OPTIONS["Confidence level (%)"],
                   "Summary error": SUMMARY_ERRORS, "SEM source": SEM_SOURCES,
                   "Overlay observations": False, "Point placement": PLACEMENTS}
PERCENT_LABEL = "Percent of row total (%)"
COLORS = ("#216a94", "#ca6239", "#2b8a73", "#845994", "#b08428", "#5678a9", "#b64e69", "#527f50")
_REPLICATE = re.compile(r"(.+) \[[1-9]\d*\]( \(\d+\))?")
_SUMMARY = re.compile(r".+ \[(?:Mean|SD|SEM|N|CV%?|Center|Plus|Minus|Lower|Upper)\](?: \(\d+\))?")
# A subcolumn role is only recognized at the end of the name, before an optional
# duplicate suffix that the grid adds, e.g. "Control [SD] (2)".
_SUMMARY_FIELD = re.compile(r"(.+) \[(Mean|Center|SD|SEM|N|Minus|Plus|Lower|Upper|CV%?)\]( \(\d+\))?")
_FIELD_ROLES = {"Mean": "center", "Center": "center", "SD": "sd", "SEM": "sem", "N": "n",
                "Minus": "minus", "Plus": "plus", "Lower": "lower", "Upper": "upper"}
MAX_CATEGORIES = 120
MAX_PLOT_CELLS = 1200
MAX_POINTS = 60_000


@dataclass
class _Series:
    name: str
    values: list
    x: np.ndarray
    color: str
    columns: tuple = ()


def _choice(options, name, choices):
    value = options.get(name, choices[0])
    if value not in choices:
        raise FieldError(name, f"Choose a valid {name.lower()}.")
    return value


def _numbers(frame, names):
    selected = frame.loc[:, names]
    converted = selected.apply(pd.to_numeric, errors="coerce")
    if any(np.iscomplexobj(column.to_numpy()) for _, column in converted.items()):
        raise FieldError("Variables", "Choose columns with real numeric values.")
    matrix = converted.to_numpy(dtype=float, na_value=np.nan)
    invalid = selected.notna().to_numpy() & ~np.isfinite(matrix)
    if invalid.any():
        name = names[int(np.nonzero(invalid)[1][0])]
        raise FieldError("Variables", f'"{name}" contains text or infinite values.')
    return matrix


def _title(name):
    match = _REPLICATE.fullmatch(name)
    return match[1] + (match[2] or "") if match else name


def _row_title_column(frame, row_labels, roles):
    if row_labels is None:
        aliases = {"row title", "row titles"}
        first = frame.columns[0]
        stored_groups = {name for group in roles["y"] for name in group} if roles else set()
        if first.casefold() in aliases or (stored_groups and first not in stored_groups and first not in roles["x"]):
            row_labels = first
    if row_labels is not None and row_labels not in frame:
        raise FieldError("Row titles", "Choose an existing row title variable.")
    return row_labels


def _row_title(labels, row):
    label = labels.iat[row] if labels is not None else None
    return str(label) if pd.notna(label) and str(label).strip() else f"Row {row + 1}"


def _included_rows(observed, labels, stacked):
    if not observed.any():
        raise FieldError("Variables", "The selected variables have no observations.")
    # A stack keeps positions for labeled rows with no values.
    if stacked and labels is not None:
        observed |= labels.astype("string").str.strip().fillna("").ne("").to_numpy(dtype=bool)
    return np.flatnonzero(observed)


def _check_size(rows, groups):
    if rows > MAX_CATEGORIES or rows * groups > MAX_PLOT_CELLS:
        raise FieldError("Variables", "Select fewer worksheet rows or groups to graph.")


def _unique_names(names, fallbacks):
    names = list(names)
    for i, name in enumerate(names):
        if name in names[:i]:
            title = fallbacks[i]
            while title in names[:i]:
                title += " (series)"
            names[i] = title
    return names


def _positions(rows, groups, layout, titles, names):
    """Place each series by row: side by side, overlaid or in one stack."""
    category_x = np.arange(rows, dtype=float)
    span = .76 / groups
    interleave = rows > 1 and layout == INTERLEAVED
    by_row = rows > 1 or layout in STACKED_PLACEMENTS
    positions = []
    for index in range(groups):
        offset = (index - (groups - 1) / 2) * span if interleave else 0.
        positions.append(category_x + offset if by_row else np.array([float(index)]))
    ticks = (category_x, titles) if by_row else (np.arange(groups), names)
    return positions, ticks, .88 * span if interleave else .56, by_row


def _grouped_data(frame, names, row_labels, layout):
    roles = _worksheet_roles(frame)
    row_labels = _row_title_column(frame, row_labels, roles)
    names = [name for name in names if name != row_labels]
    if not names:
        raise FieldError("Variables", "Select at least one replicate variable.")
    if any(_SUMMARY.fullmatch(name) for name in names):
        raise FieldError("Variables", "Choose raw replicate columns for this graph, "
                                      "or set Input to Precomputed summaries.")

    if roles:
        chosen = set(names)
        grouped = [[name for name in group if name in chosen] for group in roles["y"]]
        groups = [group for group in grouped if group]
        remaining = chosen.difference(name for group in groups for name in group)
        groups.extend([name] for name in names if name in remaining)
    else:
        groups_by_title = {}
        for name in names:
            groups_by_title.setdefault(_title(name), []).append(name)
        groups = list(groups_by_title.values())
    matrix = _numbers(frame, names)
    labels = frame[row_labels] if row_labels is not None else None
    rows = _included_rows(np.isfinite(matrix).any(axis=1), labels, layout in STACKED_PLACEMENTS)
    _check_size(len(rows), len(groups))

    columns = {name: index for index, name in enumerate(names)}
    titles = [_row_title(labels, row) for row in rows]
    series_names = _unique_names([_title(group[0]) for group in groups], [group[0] for group in groups])
    positions, ticks, width, legend = _positions(len(rows), len(groups), layout, titles, series_names)
    plots = []
    identities = frame_ids(frame)
    for index, (group, name, x) in enumerate(zip(groups, series_names, positions, strict=True)):
        values = matrix[np.ix_(rows, [columns[column] for column in group])]
        columns_used = tuple(sorted(identities[column] for column in group))
        plots.append(_Series(name, [row[np.isfinite(row)] for row in values], x,
                             COLORS[index % len(COLORS)], columns_used))
    return plots, titles, ticks, width, legend, rows


_ROLE_LABELS = {"center": "[Mean] or [Center]", "sd": "[SD]", "sem": "[SEM]", "n": "[N]",
                "minus": "[Minus]", "plus": "[Plus]", "lower": "[Lower]", "upper": "[Upper]"}


@dataclass
class _SummarySeries:
    title: str
    fields: dict
    first: str


def _summary_groups(frame, roles):
    """Group each recognized summary subcolumn of the sheet with its series."""
    parsed = {name: match for name in frame.columns
              if isinstance(name, str) and (match := _SUMMARY_FIELD.fullmatch(name))}
    stored = {}
    if roles:
        for index, group in enumerate(roles["y"]):
            stored.update({name: ("group", index) for name in group if name in parsed})
    groups = {}
    for name, match in parsed.items():
        # The duplicate suffix belongs to the series, like the grid's heading bands.
        key = stored.get(name, ("title", match[1], match[3] or ""))
        groups.setdefault(key, []).append(name)
    return parsed, list(groups.values())


def _required_fields(error, sem_source, selected, available):
    if error == "SD":
        return ("sd",)
    if error == "SEM":
        entered = sem_source == ENTERED_SEM and ("sem" in selected or ("sem" in available and not (
            "sd" in selected and "n" in selected)))
        return ("sem",) if entered else ("sd", "n")
    return {DISTANCES: ("minus", "plus"), LIMITS: ("lower", "upper")}.get(error, ())


def _summary_series(frame, names, roles, error, sem_source):
    parsed, groups = _summary_groups(frame, roles)
    for name in names:
        match = parsed.get(name)
        if match is None:
            if _REPLICATE.fullmatch(name):
                raise FieldError("Variables", f'"{name}" is a raw replicate. Set Input to Raw replicates, '
                                              'or select summary subcolumns such as "Series [Mean]".')
            raise FieldError("Variables", f'"{name}" is not a summary subcolumn. Name summary columns like '
                                          '"Series [Mean]" and "Series [SD]", or deselect it.')
        if match[2].startswith("CV"):
            raise FieldError("Variables", f'"{name}" holds a coefficient of variation, which this graph does not use. '
                                          'Deselect it.')
    chosen = set(names)
    series = []
    for group in groups:
        if chosen.isdisjoint(group):
            continue
        first = parsed[group[0]]
        title = first[1] + (first[3] or "")
        selected, available = {}, {}
        for name in group:
            if parsed[name][2].startswith("CV"):
                continue
            role = _FIELD_ROLES[parsed[name][2]]
            available.setdefault(role, name)
            if name in chosen:
                if role in selected:
                    raise FieldError("Variables", f'{title}: "{selected[role]}" and "{name}" both provide the '
                                                  f'{_ROLE_LABELS[role]} field. Select only one of them.')
                selected[role] = name
        required = _required_fields(error, sem_source, selected, available)
        for role in ("center", *required):
            if role in selected:
                continue
            if role in available:
                raise FieldError("Variables", f'{title} needs "{available[role]}". Select it together with the '
                                              'other subcolumns of this series.')
            if role == "center":
                raise FieldError("Variables", f"{title} has no [Mean] or [Center] subcolumn, so it has no estimate "
                                              "to plot.")
            fields = " and ".join(_ROLE_LABELS[name] for name in required)
            if error == "SEM" and sem_source == ENTERED_SEM:
                fields = "[SEM] subcolumn or [SD] and [N]"
            raise FieldError("Summary error", f"{title} has no {fields} for {error} error bars. "
                                              "Add the subcolumns to the sheet or choose another summary error.")
        series.append(_SummarySeries(title, {role: selected[role] for role in ("center", *required, "n")
                                             if role in selected}, group[0]))
    return series


def _summary_values(frame, series, labels, error):
    """Return the estimate, the interval and N of one series on each worksheet row."""

    def column(role):
        name = series.fields[role]
        source = frame[name]
        values = pd.to_numeric(source, errors="coerce")
        if np.iscomplexobj(values.to_numpy()):
            raise FieldError("Variables", f'"{name}" must contain real numbers.')
        values = values.to_numpy(dtype=float, na_value=np.nan)
        invalid = np.flatnonzero(source.notna().to_numpy() & ~np.isfinite(values))
        if len(invalid):
            row = invalid[0]
            raise FieldError("Variables", f'{_row_title(labels, row)}, {series.title}: "{name}" must be a finite number, '
                                          f'not "{source.iloc[row]}".')
        return values

    def nonnegative(role):
        values = column(role)
        invalid = np.flatnonzero(values < 0)
        if len(invalid):
            row = invalid[0]
            raise FieldError("Variables", f'{_row_title(labels, row)}, {series.title}: "{series.fields[role]}" must be zero or '
                                          f'positive, not {values[row]:g}.')
        return values

    center = column("center")
    counts = column("n") if "n" in series.fields else np.full(len(frame), np.nan)
    lower = upper = np.full(len(frame), np.nan)
    inputs = [center]
    bound_inputs = None
    with np.errstate(over="ignore", invalid="ignore"):
        if error == "SD" or (error == "SEM" and "sem" in series.fields):
            margin = nonnegative("sd" if error == "SD" else "sem")
            inputs.append(margin)
            lower, upper = center - margin, center + margin
        elif error == "SEM":
            invalid = np.flatnonzero(np.isfinite(counts) & ((counts < 2) | (counts != np.floor(counts))))
            if len(invalid):
                row = invalid[0]
                raise FieldError("Variables", f'{_row_title(labels, row)}, {series.title}: "{series.fields["n"]}" must be a whole '
                                              f'number of at least 2 to convert SD to SEM, not {counts[row]:g}.')
            spread = nonnegative("sd")
            margin = spread / np.sqrt(counts)
            inputs.extend((spread, counts))
            lower, upper = center - margin, center + margin
        elif error == DISTANCES:
            minus, plus = nonnegative("minus"), nonnegative("plus")
            bound_inputs = minus, plus
            lower, upper = center - minus, center + plus
        elif error == LIMITS:
            lower, upper = column("lower"), column("upper")
            bound_inputs = lower, upper
            contains = (lower <= center) & (center <= upper)
            ordered = lower <= upper
            invalid = np.flatnonzero(np.isfinite(lower) & np.isfinite(upper)
                                     & np.where(np.isfinite(center), ~contains, ~ordered))
            if len(invalid):
                row = invalid[0]
                raise FieldError("Variables", f'{_row_title(labels, row)}, {series.title}: the limits {lower[row]:g} and '
                                              f'{upper[row]:g} must contain the estimate {center[row]:g}.'
                                 if np.isfinite(center[row]) else
                                 f'{_row_title(labels, row)}, {series.title}: the lower limit must not exceed the upper limit.')
            for role, crossed, other in (("lower", lower > center, upper), ("upper", upper < center, lower)):
                if np.any(crossed & ~np.isfinite(other)):
                    error = FieldError("Variables", "The supplied limit is on the wrong side of the estimate.")
                    error.column = series.fields[role]
                    raise error
    if bound_inputs is None:
        lower_available = upper_available = np.logical_and.reduce([np.isfinite(values) for values in inputs])
    else:
        estimates = np.isfinite(center)
        lower_available, upper_available = (estimates & np.isfinite(values) for values in bound_inputs)
    with np.errstate(over="ignore", invalid="ignore"):
        low = np.where(lower_available, lower, center)
        high = np.where(upper_available, upper, center)
        invalid = np.flatnonzero((lower_available | upper_available) & ~np.isfinite(high - low))
    if error != "None" and len(invalid):
        row = invalid[0]
        raise FieldError("Variables", f"{_row_title(labels, row)}, {series.title}: the interval exceeds the numeric range for this graph.")
    lower = np.where(lower_available, lower, np.nan)
    upper = np.where(upper_available, upper, np.nan)
    return center, lower, upper, counts


def _summary_data(frame, names, row_labels, layout, error, sem_source):
    roles = _worksheet_roles(frame)
    row_labels = _row_title_column(frame, row_labels, roles)
    order = {name: index for index, name in enumerate(frame.columns)}
    names = sorted((name for name in names if name != row_labels), key=order.__getitem__)
    if not names:
        raise FieldError("Variables", "Select at least one summary subcolumn.")
    series = _summary_series(frame, names, roles, error, sem_source)
    labels = frame[row_labels] if row_labels is not None else None
    values = [_summary_values(frame, item, labels, error) for item in series]
    observed = np.column_stack([center for center, *_ in values])
    rows = _included_rows(np.isfinite(observed).any(axis=1), labels, layout in STACKED_PLACEMENTS)
    _check_size(len(rows), len(series))
    titles = [_row_title(labels, row) for row in rows]
    series_names = _unique_names([item.title for item in series], [item.first for item in series])
    positions, ticks, width, legend = _positions(len(rows), len(series), layout, titles, series_names)
    identities = frame_ids(frame)
    plots = [_Series(name, [np.empty(0)] * len(rows), x, COLORS[index % len(COLORS)],
                     (identities[item.fields["center"]],))
             for index, (name, x, item) in enumerate(zip(series_names, positions, series, strict=True))]
    summaries = [np.column_stack((center[rows], lower[rows], upper[rows])) for center, lower, upper, _ in values]
    counts = [count[rows] for *_, count in values]
    return plots, titles, ticks, width, legend, summaries, counts, rows


def _summary(values, center, interval, level, floating):
    if not len(values):
        return np.nan, np.nan, np.nan
    if center == GEOMETRIC_CENTER:
        if (values <= 0).any():
            raise FieldError("Variables", "Geometric mean requires strictly positive observations.")
        values_summary = geometric_summary(values, level=level, spread=True)
        midpoint = values_summary[GEOMETRIC_CENTER]
        if not np.isfinite(midpoint):
            raise FieldError("Variables", values_summary["Geometric note"])
        if interval == "Confidence interval":
            low, high = (values_summary[key] for key in geometric_interval_fields(level))
            if len(values) > 1 and not np.isfinite([low, high]).all():
                raise FieldError("Variables", values_summary["Geometric note"])
            return midpoint, low, high
        if floating:
            return midpoint, float(values.min()), float(values.max())
        return midpoint, np.nan, np.nan
    with np.errstate(over="ignore", invalid="ignore"):
        midpoint = float(np.mean(values) if center == "Mean" else np.median(values))
        if floating or interval == "Range":
            low, high = np.min(values), np.max(values)
        elif interval == "Interquartile range":
            low, high = np.quantile(values, [.25, .75])
        elif interval in {"SD", "SEM", "Confidence interval"} and len(values) > 1:
            margin = np.std(values, ddof=1)
            if interval != "SD":
                margin /= np.sqrt(len(values))
            if interval == "Confidence interval":
                margin *= t.isf((1 - level / 100) / 2, len(values) - 1)
            low, high = midpoint - margin, midpoint + margin
        else:
            low = high = np.nan
        invalid_interval = np.isinf([low, high]).any() or (np.isfinite(high) and not np.isfinite(high - low))
    if not np.isfinite(midpoint) or invalid_interval:
        raise FieldError("Variables", "The selected values exceed the numeric range for this graph.")
    return midpoint, low, high


def _spread(values, placement, width, rng):
    if placement == "Centered":
        return np.zeros(len(values))
    if placement == "Jitter":
        return rng.uniform(-.35 * width, .35 * width, len(values))
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    cuts = np.r_[0, np.flatnonzero(sorted_values[1:] != sorted_values[:-1]) + 1, len(order)]
    offsets = np.zeros(len(values))
    for start, stop in zip(cuts[:-1], cuts[1:], strict=True):
        if stop - start > 1:
            offsets[order[start:stop]] = np.linspace(-.34 * width, .34 * width, stop - start)
    return offsets


def prune_series_styles(options, valid_names=None):
    """Drop non-explicit ('As graph') or removed series entries from grouped ``options['Series style']``."""
    raw = options.get(SERIES_STYLE)
    if not isinstance(raw, dict):
        cleaned = dict(options)
        cleaned.pop(SERIES_STYLE, None)
        return cleaned
    allowed = set(valid_names) if valid_names is not None else None
    kept = {
        name: value for name, value in raw.items()
        if isinstance(name, str) and value in SERIES_DRAW_STYLES and value != AS_GRAPH
        and (allowed is None or name in allowed)
    }
    cleaned = dict(options)
    if kept:
        cleaned[SERIES_STYLE] = kept
    else:
        cleaned.pop(SERIES_STYLE, None)
    return cleaned


def has_series_style_overrides(options):
    raw = options.get(SERIES_STYLE) if isinstance(options, dict) else None
    return isinstance(raw, dict) and any(val in SERIES_DRAW_STYLES and val != AS_GRAPH for val in raw.values())


def series_placements(options, names=None):
    """Read the explicit placement of each series relative to the preceding series."""
    placements = options.get(SERIES_PLACEMENT, {})
    if not isinstance(placements, dict) or len(placements) > MAX_CATEGORIES or any(
        not isinstance(name, str) or not name or mode not in RELATIVE_PLACEMENTS
        for name, mode in placements.items()
    ):
        raise FieldError(SERIES_PLACEMENT, "Choose a valid placement for each series.")
    if names is None:
        return placements
    return {name: placements[name] for name in names[1:] if name in placements}


def grouped_series_order(options, names=None):
    """Resolve the drawing order while letting new series join in the worksheet order."""
    order = options.get(GROUPED_SERIES_ORDER, [])
    if (not isinstance(order, list) or len(order) > MAX_CATEGORIES
            or any(not isinstance(name, str) or not name or len(name) > 1024 for name in order)
            or len(set(order)) != len(order)):
        raise FieldError(GROUPED_SERIES_ORDER, "Choose a valid order for the grouped series.")
    if names is None:
        return order
    available, ordered = set(names), set(order)
    return [name for name in order if name in available] + [name for name in names if name not in ordered]


def series_interval_directions(options):
    """Return visual overrides without changing either stored endpoint of an interval."""
    directions = options.get(SERIES_INTERVAL_DIRECTION, {})
    if not isinstance(directions, dict) or len(directions) > MAX_CATEGORIES or any(
        not isinstance(name, str) or not name or direction not in INTERVAL_DIRECTIONS
        for name, direction in directions.items()
    ):
        raise FieldError(SERIES_INTERVAL_DIRECTION, "Choose a valid interval direction for each series.")
    return directions


def grouped_right_series(options):
    """Validate per-series axis choices and return the names using the independent axis."""
    sides = options.get(SERIES_SIDE, {})
    if not isinstance(sides, dict) or len(sides) > MAX_CATEGORIES or any(
        not isinstance(name, str) or not name or side not in SERIES_SIDES
        for name, side in sides.items()
    ):
        raise FieldError(SERIES_SIDE, "Choose the left or right axis for each grouped series.")
    return {name for name, side in sides.items() if side == RIGHT_SIDE}


def _grouped_right_axis(axes, options, names, right_names):
    scale = options.get("Right scale", "Linear")
    if scale not in SERIES_SCALES:
        raise FieldError("Right scale", "Choose a linear or logarithmic right axis.")
    logarithmic = scale == "Log"
    title = options.get("Right title", "")
    if not isinstance(title, str) or len(title) > 160:
        raise FieldError("Right title", "Enter an axis title of up to 160 characters.")
    limits = _limit_pair(options, "Right minimum", "Right maximum", "Right minimum", logarithmic)
    right = axes.twinx()
    right.set_ylabel(title.strip() or ", ".join(name for name in names if name in right_names))
    right.grid(False)
    if logarithmic:
        right.set_yscale("log")
    right.spines[["left", "top", "bottom"]].set_visible(False)
    # Keep the primary legend and annotations visible above artists on the right axis.
    right.set_zorder(axes.get_zorder() - 1)
    right.patch.set_visible(True)
    right.patch.set_facecolor(axes.patch.get_facecolor())
    axes.patch.set_visible(False)
    if right_names == set(names):
        axes.yaxis.set_visible(False)
        axes.spines["left"].set_visible(False)
    if limits is not None:
        right.set_ylim(*limits)
    return right


def _validate_right_log_data(series, summaries, direction, show_points):
    shown = [0]
    if direction != UPPER_INTERVAL:
        shown.append(1)
    if direction != LOWER_INTERVAL:
        shown.append(2)
    values = np.asarray(summaries, dtype=float).reshape(-1, 3)[:, shown]
    if np.any(np.isfinite(values) & (values <= 0)) or (
        show_points and any(np.any(values <= 0) for values in series.values)
    ):
        raise FieldError("Right scale", "The estimates, visible interval limits and points on the right logarithmic axis must be positive.")


def grouped_graph_metadata(axes):
    return getattr(axes, "_tramastat_grouped", None) or getattr(axes, "_tramastat_grouped_context", None)


def grouped_bar_spacing(options):
    """Return optional physical gaps as fractions of a drawn bar's width."""
    if GROUPED_BAR_SPACING not in options:
        return None
    settings = options[GROUPED_BAR_SPACING]
    if (not isinstance(settings, dict) or settings.keys() != BAR_SPACING_DEFAULTS.keys()
            or any(type(value) not in (int, float) or not 0 <= value <= BAR_SPACING_MAXIMUMS[key]
                   for key, value in settings.items())):
        raise FieldError(GROUPED_BAR_SPACING, "Choose valid percentages for the grouped bar spacing.")
    return {key: value / 100 for key, value in settings.items()}

def grouped_bar_baseline(options):
    baseline = options.get(BAR_BASELINE, 0)
    if type(baseline) not in (int, float) or abs(baseline) > float_info.max or not isfinite(baseline):
        raise FieldError(BAR_BASELINE, "Enter a finite starting value for the bars.")
    return float(baseline)


def _space_grouped_bars(plots, summaries, row_names, by_row, placements, spacing):
    """Keep overlays and stacks in a shared slot and reserve space for empty slots."""
    previous_positions = np.array([plot.x for plot in plots]).T
    observed = np.isfinite(np.array(summaries)[:, :, 0]).T
    positions = np.full(previous_positions.shape, np.nan)
    ticks, labels = [], []
    cursor = spacing["leading"]
    for row, name in enumerate(row_names):
        members_at = {}
        for series, position in enumerate(previous_positions[row]):
            members_at.setdefault(position, []).append(series)
        occupied = []
        for members in members_at.values():
            width = 1. if observed[row, members].any() else spacing["empty"]
            if width:
                occupied.append((members, width))
        if not occupied:
            continue
        if ticks:
            cursor += spacing["adjacent"] + spacing["groups"]
        start = cursor
        for index, (members, width) in enumerate(occupied):
            if index:
                cursor += spacing["adjacent"]
                if placements.get(plots[members[0]].name) == GAP_BEFORE:
                    cursor += spacing["groups"]
            center = cursor + width / 2
            positions[row, members] = center
            cursor += width
            if not by_row:
                ticks.append(center)
                labels.append(plots[members[0]].name)
        if by_row:
            ticks.append((start + cursor) / 2)
            labels.append(name)
    if not ticks:
        raise FieldError("Variables", "The selected variables have no observations.")
    for plot, position in zip(plots, positions.T, strict=True):
        plot.x = position
    return (ticks, labels), (0., cursor + spacing["trailing"])


def _series_positions(names, placements, layout):
    default = OVERLAY_PREVIOUS if layout == SUPERIMPOSED else SIDE_BY_SIDE
    slots = [0.]
    stacks = [[0]]
    for index, name in enumerate(names[1:], 1):
        placement = placements.get(name, default)
        if placement == GAP_BEFORE:
            slots.append(slots[-1] + 1.65)
        elif placement == SIDE_BY_SIDE:
            slots.append(slots[-1] + 1.)
        else:
            slots.append(slots[-1])
        if placement == STACK_PREVIOUS:
            stacks[-1].append(index)
        else:
            stacks.append([index])
    span = .76 / (slots[-1] + 1.)
    offsets = [(slot - slots[-1] / 2.) * span for slot in slots]
    return offsets, .88 * span, [members for members in stacks if len(members) > 1]


def grouped_series_names(frame, options):
    """Return the ordered series titles resolved by ``options`` without plotting."""
    names = options.get("Variables", [])
    if not isinstance(names, list) or not names:
        return []
    source = options.get("Input", INPUTS[0])
    row_labels = options.get("Row titles")
    roles = _worksheet_roles(frame)
    try:
        row_labels = _row_title_column(frame, row_labels, roles)
    except FieldError:
        row_labels = None
    names = [name for name in names if name != row_labels and name in frame]
    if not names:
        return []
    if source == SUMMARIES:
        order = {name: index for index, name in enumerate(frame.columns)}
        names = sorted(names, key=order.__getitem__)
        _, groups = _summary_groups(frame, roles)
        chosen = set(names)
        series = []
        for group in groups:
            if chosen.isdisjoint(group):
                continue
            parsed = _SUMMARY_FIELD.fullmatch(group[0])
            if parsed is not None:
                series.append((parsed[1] + (parsed[3] or ""), group[0]))
        return _unique_names([t for t, _ in series], [f for _, f in series])
    if roles:
        chosen = set(names)
        grouped = [[name for name in group if name in chosen] for group in roles["y"]]
        groups = [group for group in grouped if group]
        remaining = chosen.difference(name for group in groups for name in group)
        groups.extend([name] for name in names if name in remaining)
    else:
        groups_by_title = {}
        for name in names:
            groups_by_title.setdefault(_title(name), []).append(name)
        groups = list(groups_by_title.values())
    return _unique_names([_title(group[0]) for group in groups], [group[0] for group in groups])


def grouped_style_after_parameter_change(style, options, frame=None):
    """Retain ``grouped:1:<name>`` style entries for series that stay selected."""
    if not isinstance(style, dict) or not isinstance(style.get("series"), dict) or frame is None:
        return style
    names = set(grouped_series_names(frame, options))
    if not names:
        return style
    kept = {f"grouped:1:{name}" for name in names}
    series = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in style["series"].items()
        if not str(key).startswith("grouped:1:") or key in kept
    }
    updated = dict(style)
    if series:
        updated["series"] = series
    else:
        updated.pop("series", None)
    return updated


def transpose_grouped_bar_style(style):
    """Keep the saved data-axis formatting and data-anchored objects with their coordinates."""
    from .axis_breaks import AXIS_BREAKS
    from .axis_guides import AXIS_BANDS, AXIS_GUIDES
    from .graph_annotations import ANNOTATIONS
    from .graph_shapes import SHAPES
    from .linked_axes import LINKED_AXES

    if not style:
        return style
    swapped = {"x": "y", "y": "x"}
    keys = {"xlabel": "ylabel", "ylabel": "xlabel", "xscale": "yscale", "yscale": "xscale"}
    updated = {keys.get(key, key): deepcopy(value) for key, value in style.items()}
    for key in ("axis", LINKED_AXES):
        if updated.get(key):
            updated[key] = {swapped[axis]: value for axis, value in updated[key].items()}
    for key in ("reference_lines", AXIS_GUIDES, AXIS_BANDS):
        for record in updated.get(key) or ():
            record["axis"] = swapped[record["axis"]]
    if record := updated.get(AXIS_BREAKS):
        record["axis"] = swapped[record["axis"]]
    for record in updated.get(ANNOTATIONS, ()):
        if record["units"] == "data":
            record["position"] = record["position"][::-1]
            if "target" in record:
                record["target"] = record["target"][::-1]
    for record in updated.get(SHAPES, ()):
        if record["units"] == "data":
            record["points"] = [point[::-1] for point in record["points"]]
    return updated


def _draw_bars(axes, categories, heights, width, baseline, horizontal, **style):
    if horizontal:
        return axes.barh(categories, heights, width, left=baseline, **style)
    return axes.bar(categories, heights, width, bottom=baseline, **style)


def _draw_intervals(axes, categories, center, lower, upper, color, direction, horizontal):
    has_lower, has_upper = np.isfinite(lower), np.isfinite(upper)
    show_lower = has_lower & (direction != UPPER_INTERVAL)
    show_upper = has_upper & (direction != LOWER_INTERVAL)
    plotted = show_lower | show_upper
    if not plotted.any():
        return None

    both = has_lower & has_upper
    # A mean can fall outside an interquartile interval. Keep the shown portion within the original endpoints.
    anchor = np.where(both, np.clip(center, lower, upper), center)
    start = np.where(show_lower, lower, anchor)[plotted]
    end = np.where(show_upper, upper, anchor)[plotted]
    locations = categories[plotted]
    if not horizontal and axes.get_yscale() == "log":
        # yerr reconstructs endpoints by subtraction, which can collapse a small positive bound to zero.
        artist = axes.errorbar(locations, start, yerr=np.zeros_like(start), fmt="none",
                               ecolor=color, capsize=4, elinewidth=1.3, zorder=3)
        lower_vertices = np.column_stack((locations, start))
        upper_vertices = np.column_stack((locations, end))
        artist.lines[2][0].set_segments(np.stack((lower_vertices, upper_vertices), axis=1))
        for cap, values, shown in zip(artist.lines[1], (start, end), (show_lower[plotted], show_upper[plotted]), strict=True):
            cap.set_data(locations[shown], values[shown])
        axes.update_datalim(np.vstack((lower_vertices, upper_vertices)))
        return artist
    midpoint = start + (end - start) / 2
    x, y = (midpoint, locations) if horizontal else (locations, midpoint)
    errors = {"xerr" if horizontal else "yerr": [midpoint - start, end - midpoint]}
    artist = axes.errorbar(x, y, **errors, fmt="none", ecolor=color, capsize=4, elinewidth=1.3, zorder=3)
    for cap, shown in zip(artist.lines[1], (show_lower[plotted], show_upper[plotted]), strict=True):
        if not shown.all():
            cap.set_data(np.asarray(cap.get_xdata())[shown], np.asarray(cap.get_ydata())[shown])
    return artist


def _draw_series(axes, series, summaries, style, width, show_points, placement, rng, *,
                 grouped_track=False, bottom=None, interval_direction=BOTH_INTERVALS, horizontal=False,
                 bar_baseline=0.):
    def coordinates(category, response):
        return (response, category) if horizontal else (category, response)

    x, color = series.x, series.color
    center, lower, upper = np.asarray(summaries).T
    observed = np.isfinite(center)
    interval = np.isfinite(lower) & np.isfinite(upper)
    primary = err = pts = None
    if style == BARS:
        base = bar_baseline if bottom is None else bottom[observed]
        with np.errstate(over="ignore"):
            heights = center[observed] - bar_baseline
        if not horizontal and axes.get_yscale() == "log":
            # Keep the smaller endpoint itself as the bottom, even for ratios several decades below 1.
            base = np.minimum(center[observed], bar_baseline)
            heights = np.abs(heights)
        if not np.isfinite(heights).all():
            raise FieldError(BAR_BASELINE, "The distance from the bar baseline exceeds the numeric range.")
        primary = _draw_bars(axes, x[observed], heights, width, base, horizontal,
                             color=to_rgba(color, .76), edgecolor=color, linewidth=1.15, label=series.name, zorder=2.5)
        if bottom is not None:
            show_points = False
            finite_lower, finite_upper = np.isfinite(lower), np.isfinite(upper)
            with np.errstate(over="ignore", invalid="ignore"):
                lower, upper = lower + bottom, upper + bottom
                center = center + bottom
            if np.any(finite_lower & ~np.isfinite(lower)) or np.any(finite_upper & ~np.isfinite(upper)):
                raise FieldError("Variables", "The stacked totals exceed the numeric range for this graph.")
            for patch, value in zip(primary.patches, center[observed], strict=True):
                if value == 0:
                    patch.set_linewidth(0)
    elif style == RANGE:
        primary = axes.bar(x[interval], upper[interval] - lower[interval], width, bottom=lower[interval],
                           color=to_rgba(color, .22), edgecolor=color, linewidth=1.4, label=series.name, zorder=2.5)
    elif style == SYMBOLS:
        primary = axes.scatter(*coordinates(x[observed], center[observed]), marker="o", s=42, linewidths=1.8, color=color,
                               label=series.name, zorder=4)
    elif style == POINTS:
        axes.scatter(x[observed], center[observed], marker="_", s=160, linewidths=1.8, color=color,
                     label="_nolegend_", zorder=4)
    elif style == LINE_SYMBOLS:
        primary, = axes.plot(*coordinates(x, center), linestyle="-", linewidth=1.8, marker="o", markersize=6.5, color=color,
                             markerfacecolor=color, markeredgecolor=color, label=series.name, zorder=4)
    if style not in {RANGE, PAIRED}:
        err = _draw_intervals(axes, x, center, lower, upper, color, interval_direction, horizontal)
    if show_points:
        points = [(location + _spread(values, placement, width, rng), values)
                  for location, values in zip(x, series.values, strict=True) if len(values)]
        if points:
            x_points, y_points = (np.concatenate(parts) for parts in zip(*points, strict=True))
            pts = axes.scatter(*coordinates(x_points, y_points), s=26, color=color, edgecolors="white", linewidths=.6,
                               label=series.name if style in {POINTS, PAIRED} else "_nolegend_", zorder=3.5)
    if grouped_track and primary is not None:
        primary._tramastat_grouped_series = {
            "name": series.name,
            "draw_style": style,
            "errorbar": err,
            "points": pts,
            "default_color": color,
        }
        for companion in (err, pts):
            if companion is not None:
                companion._tramastat_grouped_companion = True
    return primary


def _stack_bottoms(heights):
    """Find each segment baseline, with independent positive and negative sums."""
    positive, negative = np.zeros(len(heights)), np.zeros(len(heights))
    bottoms = np.full(heights.shape, np.nan)
    for index, height in enumerate(heights.T):
        drawn = np.isfinite(height)
        bottom = np.where(height < 0, negative, positive)
        bottoms[drawn, index] = bottom[drawn]
        with np.errstate(over="ignore", invalid="ignore"):
            positive += np.where(drawn & (height > 0), height, 0)
            negative += np.where(drawn & (height < 0), height, 0)
            span = positive.max() - negative.min()
        if not np.isfinite(span):
            raise FieldError("Variables", "The stacked totals exceed the numeric range for this graph.")
    return bottoms


def _register_series_bars(bars, plot, row_refs, row_names, drawn):
    if row_refs:
        indices = np.flatnonzero(drawn)
        register_bars(bars.patches[0].get_figure(), bars.patches, (row_refs[i] for i in indices),
                      plot.columns, (row_names[i] for i in indices), plot.name)


def _draw_stacks(axes, plots, centers, width, percent, row_names, row_refs, horizontal=False):
    """Stack the center of each row and series, keeping positive and negative totals apart."""
    heights = centers
    if percent:
        observed = np.isfinite(centers)
        negative = np.argwhere(observed & (centers < 0))
        if len(negative):
            row, index = negative[0]
            raise FieldError("Placement of groups", f"{row_names[row]}, {plots[index].name}: 100% stacked bars need "
                                                    f"values of zero or more, not {centers[row, index]:g}. "
                                                    "Correct the value or choose Stacked.")
        heights = np.full(centers.shape, np.nan)
        for row, columns in enumerate(observed):
            values = centers[row, columns]
            if not len(values) or not values.max() > 0:
                continue  # A labeled row without a positive total keeps an empty position.
            with np.errstate(over="ignore"):
                total = values.sum()
            if not np.isfinite(total):
                values = values / values.max()
                total = values.sum()
            heights[row, columns] = (values / total) * 100
        if not np.isfinite(heights).any():
            raise FieldError("Variables", "No row has a positive total to show as 100%. Enter positive values "
                                          "in at least one row, or choose Stacked.")
    bottoms = _stack_bottoms(heights)
    for index, plot in enumerate(plots):
        height = heights[:, index]
        drawn = np.isfinite(height)
        bottom = bottoms[:, index]
        if drawn.any():
            bars = _draw_bars(axes, plot.x[drawn], height[drawn], width, bottom[drawn], horizontal,
                              color=to_rgba(plot.color, .76), edgecolor=plot.color, linewidth=1.15, label=plot.name)
            _register_series_bars(bars, plot, row_refs, row_names, drawn)
            for patch, value in zip(bars.patches, height[drawn], strict=True):
                if value == 0:
                    patch.set_linewidth(0)  # An observed zero adds no visible segment.
    return bottoms, heights


def _column_anchor(plot, summary, style, show_points):
    """Center and highest drawn value of one column, for pairwise comparison brackets."""
    midpoint, _, upper = summary
    if not np.isfinite(midpoint):
        return {}
    heights = [upper if style == RANGE else midpoint]
    if style == BARS:
        heights.append(0.)
    if style != RANGE and np.isfinite(upper):
        heights.append(upper)
    if show_points and len(plot.values[0]):
        heights.append(float(np.max(plot.values[0])))
    top = float(np.nanmax(heights))
    return {f"column:{plot.name}": {"x": float(plot.x[0]), "top": top, "name": plot.name, "group": None}}


def category_graph(frame, options, *, grouped=False):
    names = options.get("Variables", [])
    if (not isinstance(names, list) or not names or any(not isinstance(name, str) or name not in frame for name in names)
            or len(set(names)) != len(names) or not frame.columns.is_unique):
        raise FieldError("Variables", "Choose distinct existing variables for the graph.")
    source = _choice(options, "Input", INPUTS) if grouped else RAW
    layout = _choice(options, "Placement of groups", GROUP_PLACEMENTS) if grouped else None
    stacked = layout in STACKED_PLACEMENTS
    style = _choice(options, "Graph style", GROUPED_STYLES if grouped else COLUMN_STYLES)
    horizontal = grouped and _choice(options, BAR_DIRECTION, BAR_DIRECTIONS) == HORIZONTAL_BARS
    if horizontal and style != BARS:
        raise FieldError(BAR_DIRECTION, "Horizontal direction is available for grouped bar graphs.")
    baseline = grouped_bar_baseline(options)
    if baseline and (not grouped or style != BARS or stacked):
        raise FieldError(BAR_BASELINE, "A custom baseline requires a grouped bar graph without stacks.")
    spacing = grouped_bar_spacing(options)
    if spacing and (not grouped or style != BARS):
        raise FieldError(GROUPED_BAR_SPACING, "Custom spacing is available for grouped bar graphs.")
    raw_series_styles = options.get(SERIES_STYLE)
    if raw_series_styles is not None:
        if not isinstance(raw_series_styles, dict) or len(raw_series_styles) > MAX_CATEGORIES:
            raise FieldError(SERIES_STYLE, "Choose a valid per-series drawing style.")
        for s_name, s_style in raw_series_styles.items():
            if not isinstance(s_name, str) or s_style not in SERIES_DRAW_STYLES:
                raise FieldError(SERIES_STYLE, "Choose a valid per-series drawing style.")
    series_overrides = (
        {name: val for name, val in raw_series_styles.items() if val != AS_GRAPH}
        if isinstance(raw_series_styles, dict) else {}
    )
    if not grouped and series_overrides:
        raise FieldError(SERIES_STYLE, "Choose a valid per-series drawing style.")
    if grouped and series_overrides:
        if stacked:
            raise FieldError("Placement of groups",
                             "Stacked bars cannot mix per-series drawing styles. Reset every series to As graph first.")
        if style not in GROUPED_SERIES_COMPATIBLE_STYLES:
            raise FieldError("Graph style",
                             "Per-series drawing styles are available for Bars and Center and interval only. "
                             "Reset every series to As graph first.")
    relative_placements = series_placements(options)
    if relative_placements and (not grouped or stacked or style not in GROUPED_SERIES_COMPATIBLE_STYLES):
        raise FieldError(SERIES_PLACEMENT, "Choose a grouped bar or center graph with side-by-side or overlaid placement.")
    directions = series_interval_directions(options)
    if directions and (not grouped or stacked or style not in GROUPED_SERIES_COMPATIBLE_STYLES):
        raise FieldError(SERIES_INTERVAL_DIRECTION,
                         "Per-series interval direction requires a grouped bar or center graph that shows intervals.")
    right_names = grouped_right_series(options)
    if right_names and (not grouped or horizontal or stacked or style not in GROUPED_SERIES_COMPATIBLE_STYLES):
        raise FieldError(SERIES_SIDE, "An independent right axis requires a vertical grouped bar or center graph without global stacking.")
    if source == SUMMARIES and style not in SUMMARY_STYLES:
        raise FieldError("Graph style", "Precomputed summaries can be drawn as Bars or Center and interval. "
                                        "Individual points and floating ranges need raw replicates.")
    if stacked and style != BARS:
        raise FieldError("Placement of groups", "Stacked and 100% stacked placements use the Bars style.")
    if (source == SUMMARIES or stacked) and options.get("Overlay observations", False):
        reason = "stacked bars" if stacked else "precomputed summaries"
        raise FieldError("Overlay observations", f"Individual observations are not shown for {reason}.")
    if stacked and (options.get("Interval", "None") != "None" or options.get("Summary error", "None") != "None"):
        field = "Summary error" if source == SUMMARIES else "Interval"
        raise FieldError(field, "Stacked bars have no error bars. The errors of the components do not define "
                                "an interval for the stack.")
    level = 95.
    if source == SUMMARIES:
        if options.get("Center", "Mean") != "Mean":
            raise FieldError("Center", "Precomputed summaries provide the estimate in their [Mean] or [Center] "
                                       "subcolumn.")
        if options.get("Interval", "None") != "None":
            raise FieldError("Interval", "Choose error bars for precomputed summaries with Summary error.")
        center, interval = "Estimate", "None"
        error = "None" if stacked else _choice(options, "Summary error", SUMMARY_ERRORS)
        sem_source = _choice(options, "SEM source", SEM_SOURCES)
    else:
        center = _choice(options, "Center", GROUPED_OPTIONS["Center"] if grouped else OPTIONS["Center"])
        interval = "None" if style in {RANGE, PAIRED} or stacked else _choice(options, "Interval", INTERVALS)
        if center == "Median" and interval in {"SD", "SEM", "Confidence interval"}:
            raise FieldError("Interval", "Choose Range or Interquartile range for a median.")
        if center == GEOMETRIC_CENTER and interval not in {"None", "Confidence interval"}:
            raise FieldError("Interval", "For a geometric mean, choose a confidence interval or no interval.")
        if interval == "Confidence interval":
            try:
                level = float(options.get("Confidence level (%)", 95.))
            except (TypeError, ValueError, OverflowError):
                level = np.nan
            if not 0 < level < 100:
                raise FieldError("Confidence level (%)", "Choose a confidence level strictly between 0 and 100.")
    show_points = source == RAW and not stacked and (style in {POINTS, PAIRED} or options.get("Overlay observations", False))
    direction = _choice(options, INTERVAL_DIRECTION, INTERVAL_DIRECTIONS) if grouped else BOTH_INTERVALS
    placement = "Centered" if style == PAIRED else _choice(options, "Point placement", PLACEMENTS) if show_points else "Centered"
    graph = GROUPED_GRAPH if grouped else COLUMN_GRAPH
    label = PERCENT_LABEL if layout == PERCENT_STACKED else "Value"
    figure, axes = _plot(graph, label, "") if horizontal else _plot(graph, "", label)
    numeric_axis, category_axis = ("x", "y") if horizontal else ("y", "x")
    counts = None
    if grouped and source == SUMMARIES:
        plots, row_names, ticks, width, legend, summaries, counts, rows = _summary_data(
            frame, names, options.get("Row titles"), layout, error, sem_source)
    elif grouped:
        plots, row_names, ticks, width, legend, rows = _grouped_data(frame, names, options.get("Row titles"), layout)
    else:
        if len(names) > MAX_CATEGORIES:
            raise FieldError("Variables", "Select fewer columns to graph.")
        matrix = _numbers(frame, names)
        if not np.isfinite(matrix).any():
            raise FieldError("Variables", "The selected variables have no observations.")
        plots = [_Series(name, [column[np.isfinite(column)]], np.array([index]), COLORS[index % len(COLORS)])
                 for index, (name, column) in enumerate(zip(names, matrix.T, strict=True))]
        row_names, ticks, width, legend = [None], (np.arange(len(names)), names), .56, False
        if style == PAIRED:
            if len(names) < 2:
                raise FieldError("Variables", "Choose at least two columns for a before-and-after graph.")
            if np.isfinite(matrix).sum() > MAX_POINTS:
                raise FieldError("Variables", "Select fewer observations to draw matched rows.")
            rows, left = np.nonzero(np.isfinite(matrix[:, :-1]) & np.isfinite(matrix[:, 1:]))
            segments = np.stack((np.column_stack((left, matrix[rows, left])),
                                 np.column_stack((left + 1, matrix[rows, left + 1]))), axis=1)
            axes.add_collection(LineCollection(segments, colors="#8494a5", linewidths=.8, alpha=.65))
    row_refs = ()
    if grouped and ROW_SPANS in frame.attrs and current_spans(frame) is not None:
        row_refs = tuple(zip(rows, row_tokens(frame, rows), strict=True))
    if show_points and sum(len(values) for plot in plots for values in plot.values) > MAX_POINTS:
        raise FieldError("Variables", "Select fewer observations or turn off the point overlay.")

    if counts is None:
        summaries = [[_summary(values, center, interval, level, style == RANGE) for values in plot.values]
                     for plot in plots]
        counts = [[len(values) for values in plot.values] for plot in plots]
    worksheet_order = [plot.name for plot in plots]
    drawing_order = grouped_series_order(options, worksheet_order) if grouped else worksheet_order
    right_names.intersection_update(worksheet_order)
    if drawing_order != worksheet_order:
        indices = {name: index for index, name in enumerate(worksheet_order)}
        order = [indices[name] for name in drawing_order]
        plots, summaries, counts = ([sequence[index] for index in order] for sequence in (plots, summaries, counts))
        positions, ticks, width, legend = _positions(len(row_names), len(plots), layout, row_names, drawing_order)
        for plot, position in zip(plots, positions, strict=True):
            plot.x = position
    custom = series_placements(options, drawing_order) if relative_placements else {}
    piles = []
    if custom:
        offsets, width, piles = _series_positions(drawing_order, custom, layout)
        if piles and baseline:
            raise FieldError(BAR_BASELINE, "A custom baseline requires a grouped bar graph without stacks.")
        category_centers = np.arange(len(row_names), dtype=float)
        ticks, legend = (category_centers, row_names), True
        for plot, offset in zip(plots, offsets, strict=True):
            plot.x = category_centers + offset
    if spacing:
        ticks, limits = _space_grouped_bars(plots, summaries, row_names, legend, custom, spacing)
        (axes.set_ylim if horizontal else axes.set_xlim)(*limits)
        width = 1.
    right = _grouped_right_axis(axes, options, drawing_order, right_names) if right_names else None
    right_log = right is not None and right.get_yscale() == "log"
    rows_by_series = {name: [] for name in worksheet_order}
    rng = np.random.default_rng(0)
    if stacked:
        centers = np.column_stack([np.asarray(summary, dtype=float).reshape(-1, 3)[:, 0] for summary in summaries])
        bottoms, heights = _draw_stacks(axes, plots, centers, width, layout == PERCENT_STACKED, row_names,
                                        row_refs, horizontal)
        for index, plot in enumerate(plots):
            for row, category in enumerate(row_names):
                record = {"Row": category, "Group": plot.name, "N": counts[index][row], center: centers[row, index],
                          "Bottom": bottoms[row, index], "Top": bottoms[row, index] + heights[row, index]}
                if layout == PERCENT_STACKED:
                    record["Percent"] = heights[row, index]
                rows_by_series[plot.name].append(record)
        axes._tramastat_zero_baseline = (numeric_axis,)
        if layout == PERCENT_STACKED:
            (axes.set_xlim if horizontal else axes.set_ylim)(0, 100)
    else:
        anchors = {}
        series_supports_per_series = grouped and style in GROUPED_SERIES_COMPATIBLE_STYLES
        grouped_handles = {}
        effective_styles = {
            plot.name: series_overrides.get(plot.name, style) if series_supports_per_series else style
            for plot in plots
        }
        bottoms_by_index = {}
        for members in piles:
            if any(effective_styles[plots[index].name] != BARS for index in members):
                raise FieldError(SERIES_PLACEMENT, "All series in the same stack must use bars.")
            axis_sides = {plots[index].name in right_names for index in members}
            if len(axis_sides) > 1:
                raise FieldError(SERIES_SIDE, "All series in a stack must use the same value axis.")
            target = right if True in axis_sides else axes
            if target is right and right_log:
                raise FieldError("Right scale", "A stack on the right needs a linear axis.")
            target._tramastat_zero_baseline = (numeric_axis,)
            heights = np.column_stack([np.asarray(summaries[index])[:, 0] for index in members])
            bottoms_by_index.update(zip(members, _stack_bottoms(heights).T, strict=True))
        for index, (plot, summary, count) in enumerate(zip(plots, summaries, counts, strict=True)):
            target = right if plot.name in right_names else axes
            interval_side = directions.get(plot.name, direction)
            series_style = effective_styles[plot.name]
            start = baseline
            if target is right and right_log:
                _validate_right_log_data(plot, summary, interval_side, show_points)
                if series_style == BARS:
                    if baseline < 0:
                        raise FieldError(BAR_BASELINE, "The baseline of logarithmic bars must be positive.")
                    start = baseline or 1.
            primary = _draw_series(
                target, plot, summary, series_style, width, show_points, placement, rng,
                grouped_track=series_supports_per_series, bottom=bottoms_by_index.get(index),
                interval_direction=interval_side, horizontal=horizontal, bar_baseline=start,
            )
            if primary is not None:
                grouped_handles[plot.name] = primary
                if grouped and series_style == BARS and primary.patches:
                    _register_series_bars(primary, plot, row_refs, row_names, np.isfinite(np.asarray(summary)[:, 0]))
            if not grouped and style != PAIRED:
                anchors.update(_column_anchor(plot, summary[0], style, show_points))
            for category, number, (midpoint, lower, upper) in zip(row_names, count, summary, strict=True):
                row = {"Group": plot.name, "N": number, center: midpoint, "Lower": lower, "Upper": upper}
                rows_by_series[plot.name].append({"Row": category, **row} if grouped else row)
        if series_supports_per_series:
            axes._tramastat_grouped = {
                "series_order": drawing_order,
                "worksheet_order": worksheet_order,
                "layout": layout,
                "global_style": style,
                "series_styles": effective_styles,
                "summary": source == SUMMARIES,
                "handles": grouped_handles,
            }
        if anchors:
            register_anchors(axes, anchors)
    if grouped and (stacked or style not in GROUPED_SERIES_COMPATIBLE_STYLES):
        handles, labels = axes.get_legend_handles_labels()
        axes._tramastat_grouped_context = {
            "layout": layout,
            "global_style": style,
            "series_order": drawing_order,
            "worksheet_order": worksheet_order,
            "handles": dict(zip(labels, handles, strict=True)),
        }
    if horizontal:
        axes.set_yticks(*ticks)
        axes.invert_yaxis()
        ticklabels = axes.get_yticklabels()
    else:
        axes.set_xticks(*ticks, rotation=30 if len(ticks[1]) > 8 else 0)
        ticklabels = axes.get_xticklabels()
    axes._tramastat_numeric_axes = (numeric_axis,)
    axes._tramastat_categorical_axes = (category_axis,)
    for label in ticklabels:
        label.set_parse_math(False)
    if legend:
        if grouped:
            metadata = grouped_graph_metadata(axes)
            handles = metadata["handles"]
            names = [name for name in worksheet_order if name in handles]
            leg = axes.legend([handles[name] for name in names], names)
        else:
            leg = axes.legend()
        for label in leg.get_texts():
            label.set_parse_math(False)
    rows = (record for name in worksheet_order for record in rows_by_series[name])
    return Result({"Graph data": pd.DataFrame(rows)}, figure)


def default_grouped_input(frame):
    """Suggest summaries for a new graph when every numeric column is a summary subcolumn."""
    if frame.empty:
        return RAW
    title = _row_title_column(frame, None, _worksheet_roles(frame))
    numeric = [name for name in frame.select_dtypes(include="number").columns
               if isinstance(name, str) and name != title]
    return SUMMARIES if numeric and all(_SUMMARY_FIELD.fullmatch(name) for name in numeric) else RAW
