"""XY series on a shared X axis, with an optional second Y axis.

Series follow the Y-column list. Each series starts on the left axis and is
drawn as points. A line follows source-row order and breaks where X cannot be
used or Y is missing or excluded. Duplicate X values are kept in that order;
nothing is averaged. A row with no Y for one series can still be drawn for
another.

The right axis shares X and keeps its own Y scale, limits and title. Values
are not moved from one scale onto the other. The left axis owns the grid.

On a logarithmic axis only Y values greater than 0 are plotted and listed.
A non-positive Y is a break in the line and a gap in the Series values sheet.

Step holds each value until the next X of the sheet (``steps-post``) and breaks
like a line. Bars draw one rectangle from Y = 0 for each valid point, on the
series' own axis, which must be linear. A position is a virtual cluster with one
slot per Bars series in Y-column order, on either axis; a slot keeps its place
when a value is missing or the series is hidden by its style. Bars are never
summed or stacked, so a Bars series rejects a repeated X among its valid points.
The automatic cluster width is 0.8 times the smallest positive X step between
valid bar positions (0.8 X units for a single position). Bar centers are only
geometry: Series values keeps the original X.
"""

import math

import numpy as np
import pandas as pd

from .axis_breaks import mark_supported
from .linked_axes import mark_linked_axes
from .worksheet_row_identity import ROW_SPANS
from .point_style import attach_points
from .processing import FieldError
from .reporting import Result, _plot

XY_METHOD = "XY series"
STEP = "Step"
BARS = "Bars"
DRAW_STYLES = ("Points", "Line", "Line and points", STEP, BARS)
SIDES = ("Left", "Right")
SCALES = ("Linear", "Log")
SHEET = "Series values"
SOURCE_ROW = "Source row"
Y_COLUMN = "Y column"
PALETTE = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
)
BAR_WIDTH = "Bar cluster width"
RECIPE_KEYS = (
    "Series style", "Series side", "Series color",
    "Right title", "Right scale", "Right minimum", "Right maximum",
    "Y minimum", "Y maximum", BAR_WIDTH,
)
# Share of the smallest X step filled by one cluster of bars when the width is automatic.
AUTO_CLUSTER = 0.8
BAR_GID = "xybar:"
_GID = "xy:1:"


def _mapping(options, key):
    value = options.get(key)
    return value if isinstance(value, dict) else {}


def assign_colors(columns, stored):
    """Reuse a stored color for each column. New columns take the next unused palette entry."""
    stored = stored if isinstance(stored, dict) else {}
    colors = {}
    for column in columns:
        current = stored.get(column)
        if isinstance(current, str) and current:
            colors[column] = current
            continue
        used = set(colors.values())
        colors[column] = next((color for color in PALETTE if color not in used), PALETTE[len(colors) % len(PALETTE)])
    return colors


def prune_options(options):
    """Drop per-series entries for columns that are no longer selected.

    A selected column keeps its style, side and color even when it currently
    has no plotted point, so it can return after an edit.
    """
    selected = list(options.get("Y columns") or [])
    kept = set(selected)
    cleaned = dict(options)
    for key in ("Series style", "Series side", "Series color"):
        if key not in cleaned:
            continue
        mapping = cleaned[key]
        if not isinstance(mapping, dict):
            cleaned.pop(key)
            continue
        cleaned[key] = {column: mapping[column] for column in selected if column in mapping and column in kept}
    return cleaned


def retain_recipe_options(options, saved):
    """Apply a data selection while retaining the saved XY drawing options."""
    return prune_options({**{key: saved[key] for key in RECIPE_KEYS if key in saved}, **options})


def style_after_parameter_change(style, options):
    """Drop saved ``xy:1:<column>`` style entries for Y columns that are no longer selected."""
    if not isinstance(style, dict) or not isinstance(style.get("series"), dict):
        return style
    kept = {_GID + column for column in (options.get("Y columns") or []) if isinstance(column, str)}
    series = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in style["series"].items()
        if not str(key).startswith(_GID) or key in kept
    }
    updated = dict(style)
    if series:
        updated["series"] = series
    else:
        updated.pop("series", None)
    return updated



def _blank(value):
    return value is None or (isinstance(value, str) and not str(value).strip())


def _finite(value):
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return math.nan
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return math.nan
    return float(value)


def _is_log(scale):
    return str(scale).casefold() in {"log", "logarithmic"}


def _limit_pair(options, low_key, high_key, field, log):
    low_raw, high_raw = options.get(low_key), options.get(high_key)
    if _blank(low_raw) and _blank(high_raw):
        return None
    if _blank(low_raw) or _blank(high_raw):
        raise FieldError(field, "Enter both axis limits, or leave both blank for an automatic range.")
    low, high = _finite(low_raw), _finite(high_raw)
    if not (math.isfinite(low) and math.isfinite(high) and low < high):
        raise FieldError(field, "Enter finite limits with the minimum below the maximum.")
    if log and (low <= 0 or high <= 0):
        raise FieldError(field, "Logarithmic axis limits must be strictly positive.")
    return low, high


def _numbers(frame, name):
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)


def _drawn(x_values, y_values, log):
    ok = np.isfinite(x_values) & np.isfinite(y_values)
    if log:
        ok &= y_values > 0
    return ok


def _sides_and_scales(options, columns, left_scale):
    styles = _mapping(options, "Series style")
    sides = _mapping(options, "Series side")
    info = {}
    for column in columns:
        style = styles.get(column, "Points")
        side = sides.get(column, "Left")
        if style not in DRAW_STYLES:
            raise FieldError("Y columns", f"Choose a draw style of {', '.join(DRAW_STYLES)}.")
        if side not in SIDES:
            raise FieldError("Y columns", "Place each series on the left or the right axis.")
        scale = options.get("Right scale", "Linear") if side == "Right" else left_scale
        if side == "Right" and scale not in SCALES and not _is_log(scale) and str(scale) != "Linear":
            raise FieldError("Right scale", "Choose a linear or logarithmic right axis.")
        info[column] = (style, side, _is_log(scale))
    return info


def parse_bar_width(raw):
    """An explicit cluster width in X units, or None for Auto (blank). A decimal comma is accepted."""
    if _blank(raw):
        return None
    value = raw
    if isinstance(value, str):
        text = value.strip()
        if text.count(",") == 1 and "." not in text:
            text = text.replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            value = math.nan
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        value = math.nan
    try:
        value = float(value)
    except OverflowError:
        value = math.nan
    if not (math.isfinite(value) and value > 0):
        raise FieldError(BAR_WIDTH, "Enter a finite positive bar cluster width in X units, or leave it blank for Auto.")
    return value


def bar_layout(frame, options, left_scale="linear"):
    """Cluster geometry of the Bars series: ``{column: (mask, centers, slot)}`` in Y-column order.

    ``mask`` marks the sheet rows that draw a rectangle, ``centers`` holds their shifted centers and
    ``slot`` is the width of one rectangle. Raises FieldError for a repeated X, a non-linear value
    axis, an invalid width or rectangles that collapse or overflow in floating point.
    """
    columns = list(options.get("Y columns") or [])
    info = _sides_and_scales(options, columns, left_scale)
    bars = [column for column in columns if info[column][0] == BARS]
    if not bars:
        return {}
    right_scale = options.get("Right scale", "Linear")
    for column in bars:
        side = info[column][1]
        if side == "Right" and _is_log(right_scale):
            raise FieldError("Right scale", f"{column} is drawn as bars, which need a linear right Y axis.")
        if side == "Left" and str(left_scale).casefold() != "linear":
            raise FieldError("Y scale", f"{column} is drawn as bars, which need a linear left Y axis.")
    width = parse_bar_width(options.get(BAR_WIDTH))
    x_values = _numbers(frame, options["X"])
    masks = {}
    for column in bars:
        mask = _drawn(x_values, _numbers(frame, column), False)
        valid = x_values[mask]
        unique, counts = np.unique(valid, return_counts=True)
        if (counts > 1).any():
            repeated = float(unique[counts > 1][0])
            error = FieldError("Y columns", f"{column} is drawn as bars and repeats X = {repeated:g} among its "
                                            "valid points. Bars are not summed or stacked: keep one Y per X, "
                                            "or choose another draw style.")
            error.column = column  # Format Graph selects this series and its draw style.
            raise error
        masks[column] = mask
    if width is None:
        positions = np.unique(np.concatenate([x_values[mask] for mask in masks.values()]))
        with np.errstate(over="ignore", invalid="ignore"):
            steps = np.diff(positions)
        width = AUTO_CLUSTER * float(steps.min()) if len(steps) else AUTO_CLUSTER
    count = len(bars)
    with np.errstate(over="ignore", invalid="ignore"):
        slot = width / count
        layout = {}
        for index, column in enumerate(bars):
            mask = masks[column]
            centers = x_values[mask] + width * ((index + 0.5) / count - 0.5)
            low, high = centers - slot / 2, centers + slot / 2
            if not (math.isfinite(slot) and slot > 0 and np.isfinite(centers).all()
                    and np.isfinite(low).all() and np.isfinite(high).all() and (high > low).all()):
                raise FieldError(BAR_WIDTH, "The bars cannot be drawn at these X values with this cluster width: "
                                            "the rectangles would collapse or overflow. Enter another bar "
                                            "cluster width in X units.")
            layout[column] = (mask, centers, slot)
    return layout


def check_xy_options(frame, options, left_scale="linear"):
    """Raise FieldError when a dialog choice blocks the graph. Do not mutate options."""
    x_name = options.get("X")
    columns = list(options.get("Y columns") or [])
    if not isinstance(x_name, str) or x_name not in frame.columns:
        raise FieldError("X", "Choose an X column.")
    if not columns:
        raise FieldError("Y columns", "Select at least one Y column.")
    if any(not isinstance(column, str) or column not in frame.columns for column in columns):
        raise FieldError("Y columns", "Choose existing Y columns.")
    if x_name in columns:
        raise FieldError("Y columns", "Select distinct columns for X and Y.")
    right_log = _is_log(options.get("Right scale", "Linear"))
    _limit_pair(options, "Y minimum", "Y maximum", "Y minimum", _is_log(left_scale))
    _limit_pair(options, "Right minimum", "Right maximum", "Right minimum", right_log)
    info = _sides_and_scales(options, columns, left_scale)
    bar_layout(frame, options, left_scale)
    x_values = _numbers(frame, x_name)
    plotted = False
    for column, (_style, side, log) in info.items():
        y_values = _numbers(frame, column)
        finite_y = np.isfinite(y_values)
        if log and finite_y.any() and not (finite_y & (y_values > 0)).any():
            field = "Right scale" if side == "Right" else "Y minimum"
            raise FieldError(field, f"{column} has no positive Y on the {side.lower()} log axis.")
        plotted = plotted or bool(_drawn(x_values, y_values, log).any())
    if right_log:
        members = [column for column, (_style, side, _log) in info.items() if side == "Right"]
        if members and not any(_drawn(x_values, _numbers(frame, column), True).any() for column in members):
            raise FieldError("Right scale", "The right log axis has no positive Y.")
    if _is_log(left_scale):
        members = [column for column, (_style, side, _log) in info.items() if side == "Left"]
        if members and not any(_drawn(x_values, _numbers(frame, column), True).any() for column in members):
            raise FieldError("Y minimum", "The left log axis has no positive Y.")
    if not plotted:
        raise ValueError("XY series needs at least one plotted point.")


def _source_label(label):
    if isinstance(label, np.generic):
        label = label.item()
    return label


def _legend_label(column):
    text = str(column)
    return text if text and not text.startswith("_") else None


def _source_ids(frame):
    """A distinct text per sheet row for vector IDs; a repeated index label takes its position."""
    labels = [str(_source_label(label)) for label in frame.index]
    seen = {}
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
    return [label if seen[label] == 1 else f"{label}@{position}" for position, label in enumerate(labels)]


def xy_series(frame, options, left_scale="linear"):
    """Draw one artist per selected Y column and list every plotted coordinate."""
    check_xy_options(frame, options, left_scale)
    columns = list(options["Y columns"])
    x_name = options["X"]
    info = _sides_and_scales(options, columns, left_scale)
    bars = bar_layout(frame, options, left_scale)
    colors = assign_colors(columns, _mapping(options, "Series color"))
    x_values = _numbers(frame, x_name)
    left_names = [column for column in columns if info[column][1] == "Left"]
    right_names = [column for column in columns if info[column][1] == "Right"]
    left_title = ", ".join(left_names) if left_names else "Y"
    figure, axes = _plot(XY_METHOD, x_name, left_title)
    mark_supported(axes)
    mark_linked_axes(axes, "x", "y")
    if _is_log(left_scale):
        axes.set_yscale("log")
    right = None
    if right_names:
        right = axes.twinx()
        title = options.get("Right title")
        right.set_ylabel(title if isinstance(title, str) and title.strip() else ", ".join(right_names))
        right.grid(False)
        right.set_axisbelow(False)
        right.spines[["left", "top", "bottom"]].set_visible(False)
        if _is_log(options.get("Right scale", "Linear")):
            right.set_yscale("log")
        if any(column in bars for column in right_names) and not any(column in bars for column in left_names):
            # Bars only on the right: draw that axes first, so left lines, points and the legend stay on top.
            right.set_zorder(axes.get_zorder() - 1)
            right.patch.set_visible(True)
            right.patch.set_facecolor(axes.patch.get_facecolor())
            axes.patch.set_visible(False)
    source_ids = _source_ids(frame) if bars else []
    handles = []
    order = []
    rows = []
    for column in columns:
        style, side, log = info[column]
        target = right if side == "Right" else axes
        y_values = _numbers(frame, column)
        mask = _drawn(x_values, y_values, log)
        if style == BARS:
            mask, centers, slot = bars[column]
            artist = target.bar(centers, y_values[mask], width=slot, bottom=0, align="center",
                                color=colors[column], label=_legend_label(column) or "_")
            artist._tramastat_xy_gid = _GID + column
            for patch, position in zip(artist.patches, np.flatnonzero(mask), strict=True):
                patch.set_gid(f"{BAR_GID}{column}:{source_ids[position]}")
            order.append(artist._tramastat_xy_gid)
        else:
            plotted_y = np.where(mask, y_values, np.nan)
            marker = "o" if style in {"Points", "Line and points"} else "None"
            linestyle = "None" if style == "Points" else "-"
            artist, = target.plot(x_values, plotted_y, color=colors[column], marker=marker, linestyle=linestyle,
                                   drawstyle="steps-post" if style == STEP else "default",
                                   label=_legend_label(column) or "_")
            artist.set_gid(_GID + column)
            order.append(artist.get_gid())
            # One vertex per worksheet row, so a single point can be formatted and found again.
            attach_points(artist, np.arange(1, len(frame) + 1), x_values, y_values, (x_name, column), len(frame),
                          drawn=mask, row_spans=frame.attrs.get(ROW_SPANS))
        if mask.any() and _legend_label(column):
            handles.append(artist)
        for position, keep in enumerate(mask):
            if not keep:
                continue
            rows.append({
                SOURCE_ROW: _source_label(frame.index[position]),
                "X": float(x_values[position]),
                Y_COLUMN: column,
                "Y": float(y_values[position]),
            })
    axes._tramastat_xy_order = order
    axes._tramastat_numeric_axes = ("x", "y")
    if handles:
        axes.legend(handles, [artist.get_label() for artist in handles])
    left_limits = _limit_pair(options, "Y minimum", "Y maximum", "Y minimum", _is_log(left_scale))
    right_limits = _limit_pair(options, "Right minimum", "Right maximum", "Right minimum",
                               _is_log(options.get("Right scale", "Linear")))
    if left_limits:
        axes.set_ylim(*left_limits)
    if right is not None and right_limits:
        right.set_ylim(*right_limits)
    sheet = pd.DataFrame(rows, columns=[SOURCE_ROW, "X", Y_COLUMN, "Y"])
    return Result({SHEET: sheet}, figure)
