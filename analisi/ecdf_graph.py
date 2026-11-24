"""Empirical cumulative distribution function (ECDF) step graphs and tables.

Each curve is a right-continuous step function F(x) = #{i : X_i <= x} / N with
ties collapsed into a single jump. Exported tables always store probabilities in
[0, 1]; switching the Y axis between Proportion and Percent affects only the
figure presentation.
"""
from dataclasses import dataclass

from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd

from . import distribution_graphs as dist
from .category_order import ranks
from .graph_legend import typed_group_token
from .linked_axes import style_without_linked_y
from .processing import FieldError, _column
from .reporting import Result, _plot, _report


METHOD = "Empirical cumulative distribution"
INPUT = "Input"
SINGLE, SEPARATE = INPUT_MODES = dist.INPUT_MODES
RESPONSE = "Response"
GROUP = "Group"
VARIABLES = "Variables"
Y_AXIS = "Y axis"
PROPORTION, PERCENT = Y_AXIS_MODES = ("Proportion", "Percent")

OPTIONS = {
    INPUT: INPUT_MODES,
    RESPONSE: None,
    GROUP: "Optional",
    VARIABLES: "Multiple (optional)",
    Y_AXIS: Y_AXIS_MODES,
}

POINTS_SHEET = "ECDF points"
SUMMARY_SHEET = "ECDF summary"
POINTS_COLUMNS = ("X", "Count", "Cumulative count", "Probability")
LONG_POINTS_COLUMNS = ("Group", *POINTS_COLUMNS)
SUMMARY_COLUMNS = ("Group", "N", "Excluded", "Distinct values", "Minimum", "Maximum", "Note")

MAX_CURVES = 12
MAX_OBSERVATIONS = 2_000_000
MAX_KEY_LENGTH = 1024
ERROR_PREFIX = "ecdf.error."

# Twelve distinct publication colors extending Trama's category palette.
COLORS = (
    "#216a94", "#ca6239", "#2b8a73", "#845994",
    "#b08428", "#5678a9", "#b64e69", "#527f50",
    "#7b5e43", "#3d8ea8", "#a65a8a", "#6c7a38",
)


def visibility(input_mode):
    """Fields that apply to the chosen input mode."""
    single = input_mode == SINGLE
    return {RESPONSE: single, GROUP: single, VARIABLES: not single}


def _choice(options, name, choices):
    value = options.get(name, choices[0])
    if value not in choices:
        raise FieldError(name, f"Choose a valid {name.lower()}.")
    return value


def _ylabel(y_axis):
    return "Cumulative probability (%)" if y_axis == PERCENT else "Cumulative probability"


def style_after_parameter_change(style, before, after):
    """Drop stale Y-axis scale/limits/default label when switching Proportion and Percent."""
    old_unit = before.get(Y_AXIS, PROPORTION)
    new_unit = after.get(Y_AXIS, PROPORTION)
    if not style or old_unit == new_unit:
        return style
    updated = {key: value for key, value in style.items() if key not in {"yscale", "axis", "reference_lines"}}
    if updated.get("ylabel") == _ylabel(old_unit):
        updated.pop("ylabel")
    axes = {dimension: axis for dimension, axis in style.get("axis", {}).items() if dimension != "y"}
    refs = [ref for ref in style.get("reference_lines", []) if ref["axis"] != "y"]
    if axes:
        updated["axis"] = axes
    if refs:
        updated["reference_lines"] = refs
    return style_without_linked_y(updated)


def _as_finite_float_vector(values):
    """Validate and coerce ``values`` into a non-empty 1D float64 vector of finite numbers."""
    if values is None or isinstance(values, (str, bytes, dict)):
        raise ValueError("ECDF values must be a non-empty 1D sequence of finite numbers.")
    if isinstance(values, pd.Series):
        if pd.api.types.is_bool_dtype(values.dtype):
            raise ValueError("ECDF values must be numeric, not boolean.")
        raw = values.to_numpy()
    elif isinstance(values, np.ndarray):
        raw = values
    else:
        try:
            seq = list(values)
        except TypeError as error:
            raise ValueError("ECDF values must be a non-empty 1D sequence of finite numbers.") from error
        if any(isinstance(item, (bool, np.bool_)) for item in seq):
            raise ValueError("ECDF values must be numeric, not boolean.")
        raw = np.asarray(seq)
    if raw.ndim != 1 or raw.size == 0:
        raise ValueError("ECDF values must be a non-empty 1D sequence of finite numbers.")
    if raw.dtype == bool or np.issubdtype(raw.dtype, np.bool_):
        raise ValueError("ECDF values must be numeric, not boolean.")
    if np.iscomplexobj(raw):
        raise ValueError("ECDF values must be real finite numbers.")
    if raw.dtype == object:
        for item in raw:
            if isinstance(item, (bool, np.bool_, str, bytes)) or item is None:
                raise ValueError("ECDF values must be finite real numbers.")
    try:
        arr = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("ECDF values must be finite real numbers.") from error
    if not np.isfinite(arr).all():
        raise ValueError("ECDF values must all be finite numbers.")
    # Normalize -0.0 to +0.0 so both collapse into a single distinct value.
    if (arr == 0.0).any():
        arr = np.where(arr == 0.0, 0.0, arr)
    return arr


def ecdf_points(values):
    """Compute the empirical cumulative distribution table for a non-empty vector of finite numbers.

    Returns a DataFrame with columns ``X``, ``Count``, ``Cumulative count``, ``Probability``,
    sorted by ascending ``X`` with ties merged into a single jump.
    """
    arr = _as_finite_float_vector(values)
    xs, counts = np.unique(arr, return_counts=True)
    counts = counts.astype(np.int64, copy=False)
    cumulative = np.cumsum(counts, dtype=np.int64)
    probability = cumulative / float(arr.size)
    return pd.DataFrame({
        "X": xs,
        "Count": counts,
        "Cumulative count": cumulative,
        "Probability": probability,
    })


@dataclass
class _Series:
    label: object
    display: str
    identity: str
    legend_key: str
    values: np.ndarray
    excluded: int
    points: pd.DataFrame | None = None


def _text(value):
    return str(value.item() if isinstance(value, np.generic) else value)


def _group_levels(column, present, priority):
    """Return ``(levels, codes)`` over present rows preserving first-appearance or worksheet order.

    ``levels`` is a list of ``(token, value, label)`` tuples and ``codes`` is an integer array
    of length ``len(column)`` with ``-1`` for missing group rows.
    """
    n = len(column)
    codes = np.full(n, -1, dtype=np.intp)
    present_idx = np.flatnonzero(present)
    if not len(present_idx):
        return [], codes

    raw_present = column.to_numpy(dtype=object)[present_idx] if column.dtype == object else None
    homogeneous = column.dtype != object
    if not homogeneous:
        types = {type(v) for v in raw_present}
        homogeneous = len(types) <= 1

    if homogeneous:
        present_series = column.iloc[present_idx]
        fact_codes, uniques = pd.factorize(present_series, sort=False)
        levels = []
        for value in uniques:
            py_val = value.item() if isinstance(value, np.generic) else value
            levels.append((typed_group_token(py_val), py_val, _text(py_val)))
        p_codes = fact_codes.astype(np.intp, copy=False)
    else:
        index, levels = {}, []
        p_codes = np.empty(len(present_idx), dtype=np.intp)
        for pos, value in enumerate(raw_present):
            token = typed_group_token(value)
            code = index.get(token)
            if code is None:
                code = index[token] = len(levels)
                py_val = value.item() if isinstance(value, np.generic) else value
                levels.append((token, py_val, _text(py_val)))
            p_codes[pos] = code

    if priority:
        order = sorted(range(len(levels)), key=lambda i: priority.get(levels[i][0], len(priority)))
        if order != list(range(len(levels))):
            levels = [levels[i] for i in order]
            remap = np.empty(len(order), dtype=np.intp)
            for new_code, old_code in enumerate(order):
                remap[old_code] = new_code
            p_codes = remap[p_codes]

    codes[present_idx] = p_codes
    return levels, codes


def _select_series(frame, options):
    """Validate options and extract series in selection/group order without altering other columns."""
    mode = _choice(options, INPUT, INPUT_MODES)
    y_axis = _choice(options, Y_AXIS, Y_AXIS_MODES)
    if not frame.columns.is_unique:
        raise FieldError(VARIABLES if mode == SEPARATE else RESPONSE, "Worksheet column names must be unique.")

    if mode == SEPARATE:
        names = options.get(VARIABLES, [])
        if (not isinstance(names, (list, tuple)) or not names
                or any(not isinstance(name, str) or name not in frame for name in names)
                or len(set(names)) != len(names)):
            raise FieldError(VARIABLES, "Choose 1 to 12 distinct numeric columns.")
        names = list(names)
        if len(names) > MAX_CURVES:
            raise FieldError(VARIABLES, f"Plot up to {MAX_CURVES} curves at once.")
        series = []
        total_valid = 0
        for name in names:
            numbers = _column(frame, name, VARIABLES).to_numpy(dtype=np.float64)
            finite = np.isfinite(numbers)
            valid = numbers[finite]
            if not valid.size:
                raise FieldError(VARIABLES, f'Column "{name}" has no valid numeric observations.')
            total_valid += valid.size
            if total_valid > MAX_OBSERVATIONS:
                raise FieldError(VARIABLES, f"Select at most {MAX_OBSERVATIONS:,} observations across all curves.")
            identity = dist._identity(SEPARATE, False, name)
            legend_key = f"gid:ecdf:{identity}"
            series.append(_Series(
                label=name,
                display=name,
                identity=identity,
                legend_key=legend_key if len(legend_key) <= MAX_KEY_LENGTH else "",
                values=valid,
                excluded=int(len(numbers) - valid.size),
            ))
        return mode, y_axis, series, None, "Value", 0

    response = options.get(RESPONSE) or None
    group = options.get(GROUP) or None
    if response is None or not isinstance(response, str) or response not in frame:
        raise FieldError(RESPONSE, "Choose a column for Response.")
    if group is not None:
        if not isinstance(group, str) or group not in frame:
            raise FieldError(GROUP, "Choose an existing grouping column.")
        if group == response:
            raise FieldError(GROUP, "Choose a grouping column different from the response.")

    numbers = _column(frame, response, RESPONSE).to_numpy(dtype=np.float64)
    finite = np.isfinite(numbers)

    if group is None:
        valid = numbers[finite]
        if not valid.size:
            raise FieldError(RESPONSE, f'Column "{response}" has no valid numeric observations.')
        if valid.size > MAX_OBSERVATIONS:
            raise FieldError(RESPONSE, f"Select at most {MAX_OBSERVATIONS:,} observations across all curves.")
        identity = dist._identity(SINGLE, False, "All")
        series = [_Series(
            label="All",
            display="All",
            identity=identity,
            legend_key=f"gid:ecdf:{identity}",
            values=valid,
            excluded=int(len(numbers) - valid.size),
        )]
        return mode, y_axis, series, None, response, 0

    labels_col = frame[group]
    present = labels_col.notna().to_numpy()
    missing_group = int((~present).sum())
    levels, codes = _group_levels(labels_col, present, ranks(frame, group))
    if not levels:
        raise FieldError(GROUP, f'Column "{group}" has no group values.')
    if len(levels) > MAX_CURVES:
        raise FieldError(GROUP, f"Plot up to {MAX_CURVES} curves at once.")
    if not (present & finite).any():
        raise FieldError(RESPONSE, f'Column "{response}" has no valid numeric observations.')

    # Partition rows by group code in one O(N) pass so large long worksheets stay fast.
    present_idx = np.flatnonzero(present)
    present_codes = codes[present_idx]
    order_idx = np.argsort(present_codes, kind="mergesort")
    sorted_codes = present_codes[order_idx]
    sorted_rows = present_idx[order_idx]
    bounds = np.searchsorted(sorted_codes, np.arange(len(levels) + 1))

    raw_displays = [label for _, _, label in levels]
    series = []
    total_valid = 0
    for idx, (token, value, label) in enumerate(levels):
        member_rows = sorted_rows[bounds[idx]:bounds[idx + 1]]
        member_values = numbers[member_rows]
        valid = member_values[np.isfinite(member_values)]
        if not valid.size:
            raise FieldError(GROUP, f'Group "{label}" has no valid numeric observations.')
        total_valid += valid.size
        if total_valid > MAX_OBSERVATIONS:
            raise FieldError(RESPONSE, f"Select at most {MAX_OBSERVATIONS:,} observations across all curves.")
        display = label if raw_displays.count(label) == 1 else f"{label} [{token.split(':', 1)[0]}]"
        identity = dist._identity(SINGLE, True, value)
        legend_key = f"group:{token}"
        series.append(_Series(
            label=value,
            display=display,
            identity=identity,
            legend_key=legend_key if len(legend_key) <= MAX_KEY_LENGTH else "",
            values=valid,
            excluded=int(len(member_rows) - valid.size),
        ))
    return mode, y_axis, series, group, response, missing_group


def check_options(frame, options):
    """Validate recipe and worksheet without building the figure. Raises ``FieldError``."""
    _select_series(frame, options)


def _plot_bounds(series):
    """Visible horizontal bounds that leave room for both the initial 0 and final 1 plateaus."""
    low = min(float(item.points["X"].iloc[0]) for item in series)
    high = max(float(item.points["X"].iloc[-1]) for item in series)
    with np.errstate(over="ignore", invalid="ignore"):
        span = high - low
    if not np.isfinite(span):
        raise FieldError(RESPONSE, "The selected values exceed the numeric range for this graph.")
    if span == 0.0:
        pad = max(1.0, abs(low) * 0.05)
    else:
        pad = span * 0.05
    with np.errstate(over="ignore", invalid="ignore"):
        left = low - pad
        right = high + pad
    if not (np.isfinite(left) and np.isfinite(right)) or left >= right:
        left, right = low, high
    return float(left), float(right)


def ecdf_graph(frame, options):
    """Compute ECDF tables and draw the step-curve comparison figure."""
    mode, y_axis, series, group_name, xlabel, missing_group = _select_series(frame, options)
    for item in series:
        item.points = ecdf_points(item.values)

    left_edge, right_edge = _plot_bounds(series)
    scale = 100.0 if y_axis == PERCENT else 1.0
    ylabel = _ylabel(y_axis)

    figure, axes = _plot(METHOD, xlabel, ylabel)
    for artist in (axes.title, axes.xaxis.label, axes.yaxis.label):
        artist.set_parse_math(False)

    point_frames = []
    summary_rows = []
    for index, item in enumerate(series):
        pts = item.points
        xs = pts["X"].to_numpy(dtype=np.float64)
        probs = pts["Probability"].to_numpy(dtype=np.float64)

        plot_x = np.empty(len(xs) + 2, dtype=np.float64)
        plot_x[0] = left_edge
        plot_x[1:-1] = xs
        plot_x[-1] = right_edge

        plot_y = np.empty(len(probs) + 2, dtype=np.float64)
        plot_y[0] = 0.0
        plot_y[1:-1] = probs * scale
        plot_y[-1] = scale

        color = COLORS[index % len(COLORS)]
        line = axes.step(plot_x, plot_y, where="post", color=color, linewidth=1.8, label=item.display)[0]
        gid = f"ecdf:{item.identity}"
        if len(gid) <= MAX_KEY_LENGTH:
            line.set_gid(gid)
        if item.legend_key:
            line._tramastat_legend_key = item.legend_key

        n_distinct = len(xs)
        note = "Constant series (single step from 0 to 1)." if n_distinct == 1 else ""
        point_frames.append(pd.DataFrame({
            "Group": pd.Series([item.label] * n_distinct, dtype=object),
            "X": pts["X"].to_numpy(dtype=np.float64),
            "Count": pts["Count"].to_numpy(dtype=np.int64),
            "Cumulative count": pts["Cumulative count"].to_numpy(dtype=np.int64),
            "Probability": probs,
        }))
        summary_rows.append({
            "Group": item.label,
            "N": int(item.values.size),
            "Excluded": int(item.excluded),
            "Distinct values": int(n_distinct),
            "Minimum": float(xs[0]),
            "Maximum": float(xs[-1]),
            "Note": note,
        })

    axes.set_xlim(left_edge, right_edge)
    axes.set_ylim(-0.03 * scale, 1.03 * scale)
    if y_axis == PERCENT:
        axes.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
    axes._tramastat_numeric_axes = ("x", "y")

    if len(series) > 1 or group_name is not None:
        legend = axes.legend(title=group_name)
        for artist in [legend.get_title(), *legend.get_texts()]:
            artist.set_parse_math(False)

    points_table = pd.concat(point_frames, ignore_index=True)
    summary_table = pd.DataFrame({
        "Group": pd.Series([row["Group"] for row in summary_rows], dtype=object),
        "N": [row["N"] for row in summary_rows],
        "Excluded": [row["Excluded"] for row in summary_rows],
        "Distinct values": [row["Distinct values"] for row in summary_rows],
        "Minimum": [row["Minimum"] for row in summary_rows],
        "Maximum": [row["Maximum"] for row in summary_rows],
        "Note": [row["Note"] for row in summary_rows],
    })

    settings = {
        INPUT: mode,
        Y_AXIS: y_axis,
        "Curves": len(series),
        "Valid observations": int(sum(item.values.size for item in series)),
        "Excluded observations": int(sum(item.excluded for item in series)),
        "Step convention": "Right-continuous step function; horizontal segments extend to the right of each jump.",
        "Exported probabilities": "ECDF points always stores Probability in [0, 1], independent of Y axis units.",
    }
    if mode == SEPARATE:
        settings[VARIABLES] = ", ".join(item.display for item in series)
    else:
        settings[RESPONSE] = xlabel
        settings[GROUP] = group_name or "None"
        if group_name is not None:
            settings["Rows omitted (missing group)"] = missing_group

    return Result({
        POINTS_SHEET: points_table,
        SUMMARY_SHEET: summary_table,
        "Settings": _report(settings),
    }, figure)
