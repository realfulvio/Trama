"""Pure layout geometry, axis label planning, and validation for heat maps."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import math
from numbers import Integral, Real
import re

import numpy as np
import pandas as pd

from .data import decimal_comma
from .field_error import FieldError

ROW_GAP_MODE = "Row gap mode"
ROW_GAP_SIZE = "Row gap size"
ROW_GAPS_AFTER = "Row gaps after"
COLUMN_GAP_MODE = "Column gap mode"
COLUMN_GAP_SIZE = "Column gap size"
COLUMN_GAPS_AFTER = "Column gaps after"

GAP_NONE, GAP_EVERY, GAP_SELECTED = GAP_MODES = ("None", "Every boundary", "Selected boundaries")
DEFAULT_GAP_SIZE = 0.15
MIN_GAP_SIZE = 0.0
MAX_GAP_SIZE = 2.0

SHOW_ROW_LABELS = "Show row labels"
ROW_LABEL_FREQUENCY = "Row label frequency"
ROW_LABEL_EVERY = "Row label every"
ROW_LABEL_SIDE = "Row label side"
ROW_LABEL_FONT_SIZE = "Row label font size"

SHOW_COLUMN_LABELS = "Show column labels"
COLUMN_LABEL_FREQUENCY = "Column label frequency"
COLUMN_LABEL_EVERY = "Column label every"
COLUMN_LABEL_ROTATION = "Column label rotation"
COLUMN_LABEL_SIDE = "Column label side"
COLUMN_LABEL_FONT_SIZE = "Column label font size"

FREQ_AUTO, FREQ_EVERY = LABEL_FREQUENCIES = ("Automatic", "Every Nth")
DEFAULT_LABEL_EVERY = 1
MIN_LABEL_EVERY = 1
MAX_LABEL_EVERY = 10_000

ROTATION_LEGACY, ROTATION_HORIZONTAL, ROTATION_DIAGONAL, ROTATION_VERTICAL = COLUMN_LABEL_ROTATIONS = (
    "Legacy",
    "Horizontal",
    "Diagonal",
    "Vertical",
)
ROTATION_DEGREES = {
    ROTATION_LEGACY: 40,
    ROTATION_HORIZONTAL: 0,
    ROTATION_DIAGONAL: 45,
    ROTATION_VERTICAL: 90,
}

ROW_SIDE_LEFT, ROW_SIDE_RIGHT = ROW_LABEL_SIDES = ("Left", "Right")
COLUMN_SIDE_BOTTOM, COLUMN_SIDE_TOP = COLUMN_LABEL_SIDES = ("Bottom", "Top")

MIN_FONT_SIZE = 6.0
MAX_FONT_SIZE = 36.0

LAYOUT_TABLE_COLUMNS = (
    "Display row",
    "Display column",
    "Row label",
    "Column label",
    "X left",
    "X right",
    "Y top",
    "Y bottom",
)

_BOUNDARY_TOKEN = re.compile(r"[0-9]+")


def _is_bool(value):
    return isinstance(value, (bool, np.bool_))


def _choice(options, field, choices):
    value = options.get(field, choices[0])
    if not isinstance(value, str) or value not in choices:
        raise FieldError(field, f"Choose a valid {field.lower()}.")
    return value


def _flag(options, field, default):
    value = options.get(field, default)
    if not _is_bool(value):
        raise FieldError(field, f"{field} must be on or off.")
    return bool(value)


def parse_gap_size(value, field):
    """Parse a finite gap size in 0..2 cell units (supporting decimal comma)."""
    error = FieldError(field, f"{field} must be a number from 0 to 2.")
    if _is_bool(value) or value is None:
        raise error
    if isinstance(value, str):
        text = value.strip()
        if not text or "_" in text:
            raise error
        try:
            number = float(decimal_comma(text))
        except (TypeError, ValueError, OverflowError):
            raise error from None
    elif isinstance(value, Real):
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise error from None
    else:
        raise error
    if not math.isfinite(number) or not MIN_GAP_SIZE <= number <= MAX_GAP_SIZE:
        raise error
    return number


def parse_gap_boundaries(value, n, field):
    """Parse distinct 1-based boundary positions in 1..n-1 from comma-separated text."""
    if n < 2:
        raise FieldError(field, f"{field} requires at least 2 items on the axis.")
    if not isinstance(value, str) or not value.strip():
        raise FieldError(field, f"{field} must list whole positions separated by commas.")
    parts = value.split(",")
    items = []
    for part in parts:
        token = part.strip()
        if not _BOUNDARY_TOKEN.fullmatch(token):
            raise FieldError(field, f"{field} must list whole positions separated by commas.")
        if len(token) > 12:
            raise FieldError(field, f"{field} must use positions from 1 to {n - 1}.")
        items.append(int(token))
    if len(set(items)) != len(items):
        raise FieldError(field, f"{field} cannot repeat the same boundary position.")
    if any(item < 1 or item >= n for item in items):
        raise FieldError(field, f"{field} must use positions from 1 to {n - 1}.")
    return sorted(items)


def parse_label_every(value, field):
    """Parse an integer step in 1..10000 for Every Nth axis labels."""
    error = FieldError(field, f"{field} must be a whole number from 1 to 10000.")
    if _is_bool(value):
        raise error
    if isinstance(value, Integral):
        number = int(value)
    elif isinstance(value, Real):
        try:
            numeric = float(value)
        except (ValueError, OverflowError):
            raise error from None
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise error
        number = int(numeric)
    elif isinstance(value, str):
        text = value.strip()
        if not text or "_" in text:
            raise error
        try:
            parsed = Decimal(decimal_comma(text))
        except InvalidOperation:
            raise error from None
        if not parsed.is_finite() or parsed != parsed.to_integral_value():
            raise error
        if not MIN_LABEL_EVERY <= parsed <= MAX_LABEL_EVERY:
            raise error
        return int(parsed)
    else:
        raise error
    if not MIN_LABEL_EVERY <= number <= MAX_LABEL_EVERY:
        raise error
    return number


def parse_label_font_size(value, field):
    """Parse a finite font size in 6..36 pt, or None for blank/legacy font."""
    if value is None:
        return None
    error = FieldError(field, f"{field} must be blank or a number from 6 to 36.")
    if _is_bool(value):
        raise error
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if "_" in text:
            raise error
        try:
            number = float(decimal_comma(text))
        except (TypeError, ValueError, OverflowError):
            raise error from None
    elif isinstance(value, Real):
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise error from None
    else:
        raise error
    if not math.isfinite(number) or not MIN_FONT_SIZE <= number <= MAX_FONT_SIZE:
        raise error
    return number


def _axis_gaps(n, prefix, options):
    mode = _choice(options, f"{prefix} gap mode", GAP_MODES)
    if mode == GAP_NONE:
        return [], 0.0
    size = parse_gap_size(options.get(f"{prefix} gap size", DEFAULT_GAP_SIZE), f"{prefix} gap size")
    if mode == GAP_EVERY:
        return list(range(1, n)), size
    boundaries = parse_gap_boundaries(options.get(f"{prefix} gaps after", ""), n, f"{prefix} gaps after")
    return boundaries, size


def _axis_intervals(n, boundaries, size):
    step = Fraction(str(size))
    boundary_set = set(boundaries)
    start = Fraction(0)
    starts, ends = [], []
    for index in range(n):
        starts.append(float(start))
        ends.append(float(start + 1))
        start += 1
        if index + 1 in boundary_set:
            start += step
    centers = [(a + b) / 2.0 for a, b in zip(starts, ends)]
    return starts, ends, centers


def layout_geometry(rows, columns, options):
    """Compute cell edges, centers, total extent, and active 1-based gap boundaries."""
    if not isinstance(rows, Integral) or _is_bool(rows) or rows < 1:
        raise ValueError("rows must be a positive integer.")
    if not isinstance(columns, Integral) or _is_bool(columns) or columns < 1:
        raise ValueError("columns must be a positive integer.")
    options = options or {}
    row_boundaries, row_size = _axis_gaps(int(rows), "Row", options)
    col_boundaries, col_size = _axis_gaps(int(columns), "Column", options)
    x0, x1, xcenters = _axis_intervals(int(columns), col_boundaries, col_size)
    y0, y1, ycenters = _axis_intervals(int(rows), row_boundaries, row_size)
    return {
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y1,
        "xcenters": xcenters,
        "ycenters": ycenters,
        "width": float(x1[-1]),
        "height": float(y1[-1]),
        "row_boundaries": row_boundaries,
        "column_boundaries": col_boundaries,
    }


def label_plan(names, axis, options):
    """Plan visible tick indices, literal labels, rotation, font size, and placement side."""
    if axis not in ("row", "column"):
        raise ValueError("axis must be 'row' or 'column'.")
    options = options or {}
    row = axis == "row"
    prefix = "Row" if row else "Column"
    sides = ROW_LABEL_SIDES if row else COLUMN_LABEL_SIDES
    default_side = sides[0]
    visible = _flag(options, f"Show {axis} labels", True)
    if not visible:
        return {
            "indices": [],
            "labels": [],
            "rotation": 0,
            "font_size": None,
            "side": default_side,
            "visible": False,
        }
    freq_field = f"{prefix} label frequency"
    every_field = f"{prefix} label every"
    side_field = f"{prefix} label side"
    font_field = f"{prefix} label font size"
    freq = _choice(options, freq_field, LABEL_FREQUENCIES)
    count = len(names)
    step = max(1, (count + 24) // 25) if freq == FREQ_AUTO else parse_label_every(
        options.get(every_field, DEFAULT_LABEL_EVERY), every_field
    )
    if row:
        rotation = 0
    else:
        rotation_name = _choice(options, COLUMN_LABEL_ROTATION, COLUMN_LABEL_ROTATIONS)
        rotation = ROTATION_DEGREES[rotation_name]
    side = _choice(options, side_field, sides)
    font_size = parse_label_font_size(options.get(font_field), font_field)
    indices = list(range(0, count, step))
    return {
        "indices": indices,
        "labels": [str(names[index]) for index in indices],
        "rotation": rotation,
        "font_size": font_size,
        "side": side,
        "visible": True,
    }


def is_legacy_layout(options):
    """Return True when gaps are None and all active axis label options match legacy defaults."""
    options = options or {}
    if _choice(options, ROW_GAP_MODE, GAP_MODES) != GAP_NONE:
        return False
    if _choice(options, COLUMN_GAP_MODE, GAP_MODES) != GAP_NONE:
        return False
    if not _flag(options, SHOW_ROW_LABELS, True):
        return False
    if _choice(options, ROW_LABEL_FREQUENCY, LABEL_FREQUENCIES) != FREQ_AUTO:
        return False
    if _choice(options, ROW_LABEL_SIDE, ROW_LABEL_SIDES) != ROW_SIDE_LEFT:
        return False
    if parse_label_font_size(options.get(ROW_LABEL_FONT_SIZE), ROW_LABEL_FONT_SIZE) is not None:
        return False
    if not _flag(options, SHOW_COLUMN_LABELS, True):
        return False
    if _choice(options, COLUMN_LABEL_FREQUENCY, LABEL_FREQUENCIES) != FREQ_AUTO:
        return False
    if _choice(options, COLUMN_LABEL_ROTATION, COLUMN_LABEL_ROTATIONS) != ROTATION_LEGACY:
        return False
    if _choice(options, COLUMN_LABEL_SIDE, COLUMN_LABEL_SIDES) != COLUMN_SIDE_BOTTOM:
        return False
    if parse_label_font_size(options.get(COLUMN_LABEL_FONT_SIZE), COLUMN_LABEL_FONT_SIZE) is not None:
        return False
    return True


def build_layout_table(row_labels, column_labels, geometry):
    """Build the row-major descriptive Heat map layout table for all cells."""
    nrows = len(row_labels)
    ncols = len(column_labels)
    row_names = [str(label) for label in row_labels]
    col_names = [str(label) for label in column_labels]
    return pd.DataFrame({
        "Display row": np.repeat(np.arange(1, nrows + 1, dtype=int), ncols),
        "Display column": np.tile(np.arange(1, ncols + 1, dtype=int), nrows),
        "Row label": np.repeat(np.asarray(row_names, dtype=object), ncols),
        "Column label": np.tile(np.asarray(col_names, dtype=object), nrows),
        "X left": np.tile(np.asarray(geometry["x0"], dtype=float), nrows),
        "X right": np.tile(np.asarray(geometry["x1"], dtype=float), nrows),
        "Y top": np.repeat(np.asarray(geometry["y0"], dtype=float), ncols),
        "Y bottom": np.repeat(np.asarray(geometry["y1"], dtype=float), ncols),
    })
