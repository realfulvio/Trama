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
"""

import math

import numpy as np
import pandas as pd

from .axis_breaks import mark_supported
from .processing import FieldError
from .reporting import Result, _plot

XY_METHOD = "XY series"
DRAW_STYLES = ("Points", "Line", "Line and points")
SIDES = ("Left", "Right")
SCALES = ("Linear", "Log")
SHEET = "Series values"
SOURCE_ROW = "Source row"
Y_COLUMN = "Y column"
PALETTE = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
)
RECIPE_KEYS = (
    "Series style", "Series side", "Series color",
    "Right title", "Right scale", "Right minimum", "Right maximum",
    "Y minimum", "Y maximum",
)
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


def xy_series(frame, options, left_scale="linear"):
    """Draw one artist per selected Y column and list every plotted coordinate."""
    check_xy_options(frame, options, left_scale)
    columns = list(options["Y columns"])
    x_name = options["X"]
    info = _sides_and_scales(options, columns, left_scale)
    colors = assign_colors(columns, _mapping(options, "Series color"))
    x_values = _numbers(frame, x_name)
    left_names = [column for column in columns if info[column][1] == "Left"]
    right_names = [column for column in columns if info[column][1] == "Right"]
    left_title = ", ".join(left_names) if left_names else "Y"
    figure, axes = _plot(XY_METHOD, x_name, left_title)
    mark_supported(axes)
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
    handles = []
    order = []
    rows = []
    for column in columns:
        style, side, log = info[column]
        target = right if side == "Right" else axes
        y_values = _numbers(frame, column)
        mask = _drawn(x_values, y_values, log)
        plotted_y = np.where(mask, y_values, np.nan)
        marker = "o" if style != "Line" else "None"
        linestyle = "None" if style == "Points" else "-"
        artist, = target.plot(x_values, plotted_y, color=colors[column], marker=marker,
                               linestyle=linestyle, label=_legend_label(column) or "_")
        artist.set_gid(_GID + column)
        order.append(artist.get_gid())
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
