"""Bubble plot: encode X, Y, Size/Fixed area, Fill color/scale and Symbol shape from one worksheet."""
from math import isfinite

import numpy as np
import pandas as pd

from .bubble_style import (
    ALPHA, AREA_LIMIT, ATTR, BUBBLE, BUBBLE_PALETTES, CATEGORY_COLORS, COLOR_COLUMN, COLOR_LEGEND,
    COLOR_LIMITS, COLOR_MAX, COLOR_MID, COLOR_MIN, COLOR_TITLE, DEFAULT_AREA, DEFAULT_FIXED_AREA,
    DEFAULT_FIXED_COLOR, DEFAULT_FIXED_SHAPE, DEFAULT_MISSING_COLOR, DEFAULT_MISSING_SHAPE,
    FILL_BY_CATEGORY, FILL_CONTINUOUS, FILL_FIXED, FILL_MODE, FILL_MODES, FIXED_AREA, FIXED_COLOR,
    FIXED_SHAPE, LIMITS_AUTO, LIMITS_MANUAL, LIMITS_MODES, MAX_AREA, MAX_LABELS, MISSING_COLOR,
    MISSING_SHAPE, NEUTRAL, NEUTRAL_COLOR, PALETTE, REVERSE_PALETTE, SHAPE_BY_CATEGORY,
    SHAPE_CHOICES, SHAPE_COLUMN, SHAPE_FIXED, SHAPE_LEGEND, SHAPE_MAP, SHAPE_MODE, SHAPE_MODES,
    SHEET, SHOW_LABELS, SIZE_BY_COLUMN, SIZE_FIXED, SIZE_LEGEND, SIZE_MODE, SIZE_MODES,
    BubbleStyleError, apply_bubble_style, build_bubble_tables, resolve_category_levels,
    validate_bubble_style,
)
from .category_graphs import COLORS, MAX_POINTS
from .category_order import WORKSHEET_ORDERS
from .processing import FieldError, _column
from .reporting import Result, _plot


OPTIONS = {
    "X": None,
    "Y": None,
    "Size": None,
    "Group": "Optional",
    "Label": "Optional",
    COLOR_COLUMN: "Optional",
    SHAPE_COLUMN: "Optional",
    SIZE_MODE: SIZE_MODES,
    MAX_AREA: DEFAULT_AREA,
    FIXED_AREA: DEFAULT_FIXED_AREA,
    SIZE_LEGEND: True,
    FILL_MODE: FILL_MODES,
    FIXED_COLOR: "Text",
    CATEGORY_COLORS: "Category color map",
    PALETTE: tuple(BUBBLE_PALETTES),
    REVERSE_PALETTE: False,
    COLOR_LIMITS: LIMITS_MODES,
    COLOR_MIN: "Text",
    COLOR_MID: "Text",
    COLOR_MAX: "Text",
    MISSING_COLOR: "Text",
    COLOR_LEGEND: True,
    COLOR_TITLE: "Text",
    SHAPE_MODE: SHAPE_MODES,
    FIXED_SHAPE: SHAPE_CHOICES,
    SHAPE_MAP: "Symbol map",
    MISSING_SHAPE: SHAPE_CHOICES,
    SHAPE_LEGEND: True,
    SHOW_LABELS: True,
}

ZERO_POLICY = (
    "A size of zero is an invisible point: the row is omitted from the graph, "
    "from the sheet and from the scale maximum."
)


def _flag(options, name, default):
    value = options.get(name, default)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name}: choose on or off.")
    return bool(value)


def _choice(options, name, choices, default):
    value = options.get(name, default)
    if value not in choices:
        raise FieldError(name, f"Choose a valid {name.lower()}.")
    return value


def _positive_area(options, name, default, message):
    value = options.get(name, default)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(name, message)
    value = float(value)
    if not isfinite(value) or not 0 < value <= AREA_LIMIT:
        raise FieldError(name, message)
    return value


def _role(frame, options, name, optional=False):
    value = options.get(name) or None
    if value is None:
        if optional:
            return None
        raise FieldError(name, f"Choose a column for {name}.")
    if not isinstance(value, str) or value not in frame:
        raise FieldError(name, f"Choose an existing column for {name}.")
    return value


def _text(value):
    """Label cells as display text; blanks become None."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = value if isinstance(value, str) else str(value.item() if isinstance(value, np.generic) else value)
    return text if text.strip() else None


def _worksheet_category_order(frame, col_name):
    orders = frame.attrs.get(WORKSHEET_ORDERS) or frame.attrs.get("category_orders") or {}
    return orders.get(col_name) if isinstance(orders, dict) else None


def check_options(frame, options):
    """Cheap pre-worker validation for Qt AnalysisDialog (never draws or mutates frame)."""
    if not frame.columns.is_unique:
        raise FieldError("X", "Worksheet column names must be unique.")

    size_mode = _choice(options, SIZE_MODE, SIZE_MODES, SIZE_BY_COLUMN)
    fill_mode = _choice(options, FILL_MODE, FILL_MODES, FILL_BY_CATEGORY)
    shape_mode = _choice(options, SHAPE_MODE, SHAPE_MODES, SHAPE_FIXED)

    x_name = _role(frame, options, "X")
    y_name = _role(frame, options, "Y")
    if y_name == x_name:
        raise FieldError("Y", "Choose different columns for X and Y.")

    size_name = _role(frame, options, "Size", optional=(size_mode == SIZE_FIXED))
    if size_name is not None and size_name in {x_name, y_name}:
        raise FieldError("Size", "Choose three different columns for X, Y and Size.")

    group_name = _role(frame, options, "Group", optional=True)
    color_name = _role(frame, options, COLOR_COLUMN, optional=(fill_mode != FILL_CONTINUOUS))
    if color_name is not None and color_name in {x_name, y_name, size_name}:
        raise FieldError(COLOR_COLUMN, "Choose a Color column different from X, Y and Size.")

    shape_name = _role(frame, options, SHAPE_COLUMN, optional=(shape_mode != SHAPE_BY_CATEGORY))
    label_name = _role(frame, options, "Label", optional=True)

    maximum_area = _positive_area(
        options, MAX_AREA, DEFAULT_AREA,
        f"The maximum area must be greater than 0 and at most {AREA_LIMIT:,.0f} pt².",
    )
    fixed_area = _positive_area(
        options, FIXED_AREA, DEFAULT_FIXED_AREA,
        f"Fixed area must be greater than 0 and at most {AREA_LIMIT:,.0f} pt².",
    )
    show_labels = _flag(options, SHOW_LABELS, True)
    size_legend = _flag(options, SIZE_LEGEND, True)
    color_legend = _flag(options, COLOR_LEGEND, True)
    shape_legend = _flag(options, SHAPE_LEGEND, True)

    style_payload = {
        "size_mode": size_mode,
        "maximum_area": maximum_area,
        "fixed_area": fixed_area,
        "show_size_legend": size_legend,
        "fill_mode": fill_mode,
        "fixed_color": options.get(FIXED_COLOR) or DEFAULT_FIXED_COLOR,
        "category_colors": dict(options.get(CATEGORY_COLORS) or {}),
        "palette": options.get(PALETTE, "Viridis"),
        "reverse": _flag(options, REVERSE_PALETTE, False),
        "limits_mode": _choice(options, COLOR_LIMITS, LIMITS_MODES, LIMITS_AUTO),
        "color_min": options.get(COLOR_MIN, None) if options.get(COLOR_MIN, "") != "" else None,
        "color_mid": options.get(COLOR_MID, None) if options.get(COLOR_MID, "") != "" else None,
        "color_max": options.get(COLOR_MAX, None) if options.get(COLOR_MAX, "") != "" else None,
        "missing_color": options.get(MISSING_COLOR) or DEFAULT_MISSING_COLOR,
        "show_color_legend": color_legend,
        "color_title": str(options.get(COLOR_TITLE) or ""),
        "shape_mode": shape_mode,
        "fixed_shape": options.get(FIXED_SHAPE, DEFAULT_FIXED_SHAPE),
        "shape_map": dict(options.get(SHAPE_MAP) or {}),
        "missing_shape": options.get(MISSING_SHAPE, DEFAULT_MISSING_SHAPE),
        "show_shape_legend": shape_legend,
        "show_labels": show_labels,
    }
    try:
        baseline = validate_bubble_style(style_payload)
    except BubbleStyleError as err:
        from .bubble_style import STYLE_TO_FIELD
        raise FieldError(STYLE_TO_FIELD.get(err.field, err.field), str(err)) from None
    if baseline["limits_mode"] == LIMITS_MANUAL:
        cmin, cmax, cmid = baseline["color_min"], baseline["color_max"], baseline["color_mid"]
        if cmin is None or cmax is None:
            raise FieldError(COLOR_MIN if cmin is None else COLOR_MAX,
                             "Enter finite Color minimum and Color maximum when limits are Manual.")
        if cmin >= cmax:
            raise FieldError(COLOR_MIN, "Color minimum must be strictly less than Color maximum.")
        if cmid is not None and not (cmin < cmid < cmax):
            raise FieldError(COLOR_MID, "Diverging midpoint must lie strictly between Color minimum and Color maximum.")
    return (size_mode, fill_mode, shape_mode, x_name, y_name, size_name, group_name,
            color_name, shape_name, label_name, baseline)


def bubble_plot(frame, options):
    """Build a multivariate Bubble plot Result from ``frame`` and canonical ``options``."""
    (size_mode, fill_mode, shape_mode, x_name, y_name, size_name, group_name,
     color_name, shape_name, label_name, baseline) = check_options(frame, options)
    show_labels = baseline["show_labels"]

    x = _column(frame, x_name, "X").to_numpy(dtype=float)
    y = _column(frame, y_name, "Y").to_numpy(dtype=float)

    if size_name is not None:
        size = _column(frame, size_name, "Size").to_numpy(dtype=float)
        if (size < 0).any():
            row = int(np.flatnonzero(size < 0)[0]) + 1
            raise FieldError(
                "Size",
                f'Column "{size_name}" contains a negative size (row {row}). Sizes must be zero or positive.',
            )
    else:
        size = None

    if color_name is not None:
        color_series = _column(frame, color_name, COLOR_COLUMN).to_numpy(dtype=float)
    else:
        color_series = None

    complete = np.isfinite(x) & np.isfinite(y)
    if size_mode == SIZE_BY_COLUMN:
        complete = complete & np.isfinite(size)
        zero = complete & (size == 0)
        drawn = complete & (size > 0)
        if not drawn.any():
            if zero.any():
                raise FieldError(
                    "Size",
                    "Every complete row has a size of zero, so no bubble can be drawn. "
                    "Choose a Size column with positive values.",
                )
            raise FieldError("Size", "No row has numeric X, Y and Size values.")
    else:
        zero = np.zeros(len(frame), dtype=bool)
        drawn = complete
        if not drawn.any():
            raise FieldError("X", "No row has numeric X and Y values.")

    if int(drawn.sum()) > MAX_POINTS:
        raise FieldError("X", "Select fewer rows to draw this graph.")

    rows = np.flatnonzero(drawn)
    size_values = size[rows] if size is not None else None
    color_values = color_series[rows] if color_series is not None else None

    group_raw = frame[group_name].to_numpy(dtype=object)[rows] if group_name else None
    if group_name:
        group_levels, group_display_map, group_rows = resolve_category_levels(
            group_raw,
            column_order=_worksheet_category_order(frame, group_name),
            preserve_first_seen=True,
        )
        has_blank_group = any(entry is None for entry in group_rows)
    else:
        group_levels, group_display_map, group_rows, has_blank_group = [], {}, [], False

    shape_raw = frame[shape_name].to_numpy(dtype=object)[rows] if shape_name else None
    if shape_name:
        shape_levels, shape_display_map, shape_rows = resolve_category_levels(
            shape_raw,
            column_order=_worksheet_category_order(frame, shape_name),
            preserve_first_seen=False,
        )
    else:
        shape_levels, shape_display_map, shape_rows = [], {}, []

    label_raw = frame[label_name].to_numpy(dtype=object)[rows] if label_name else None
    labels = [_text(v) for v in label_raw] if label_name else None
    labeled_count = sum(1 for txt in (labels or ()) if txt is not None)
    if not label_name:
        label_note = "No Label column."
    elif not show_labels:
        label_note = "Hidden by option."
    elif labeled_count > MAX_LABELS:
        label_note = (
            f"Not drawn: {labeled_count} labeled points exceed the limit of {MAX_LABELS}. "
            f"Every label remains in the {SHEET} sheet."
        )
    else:
        label_note = f"{labeled_count} drawn (limit {MAX_LABELS})."

    recipe_names = tuple(str(v) for v in (x_name, y_name, size_name, group_name, label_name, color_name, shape_name) if v)
    source_positions = rows + 1

    state = {
        "x_column": x_name,
        "y_column": y_name,
        "size_column": size_name,
        "group_column": group_name,
        "color_column": color_name,
        "shape_column": shape_name,
        "label_column": label_name,
        "has_size": size_name is not None,
        "has_group": group_name is not None,
        "has_color": color_name is not None,
        "has_shape": shape_name is not None,
        "has_label": label_name is not None,
        "source_rows": source_positions,
        "x": x[rows],
        "y": y[rows],
        "size_values": size_values,
        "color_values": color_values,
        "group_raw": group_raw,
        "group_levels": group_levels,
        "group_display_map": group_display_map,
        "group_rows": group_rows,
        "has_blank_group": has_blank_group,
        "shape_raw": shape_raw,
        "shape_levels": shape_levels,
        "shape_display_map": shape_display_map,
        "shape_rows": shape_rows,
        "label_raw": label_raw,
        "labels": labels,
        "label_note": label_note,
        "omitted_zero": int(zero.sum()),
        "omitted_missing": int((~complete).sum()),
        "zero_policy": ZERO_POLICY,
        "recipe_names": recipe_names,
        "sheet_rows": len(frame),
        "row_spans_data": frame,
        "default_encoding": baseline,
        "effective_encoding": dict(baseline),
    }

    figure, _axes = _plot(BUBBLE, x_name, y_name)
    setattr(figure, ATTR, state)
    apply_bubble_style(figure, {})
    sheet, settings = build_bubble_tables(state)
    return Result({SHEET: sheet, "Settings": settings}, figure)
