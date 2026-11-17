"""Editable heat maps for matrix worksheets and long-form observations."""
from decimal import Decimal, ROUND_FLOOR
from math import sqrt
from numbers import Real

from matplotlib import colormaps
from matplotlib.collections import PolyCollection
from matplotlib.figure import Figure
from matplotlib.colors import (BoundaryNorm, LinearSegmentedColormap, ListedColormap, Normalize, TwoSlopeNorm,
                               is_color_like, to_rgba)
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
from matplotlib.transforms import Bbox
import numpy as np
import pandas as pd

from .category_graphs import _SUMMARY
from .data import decimal_comma
from .heatmap_cell_labels import (AUTO_CONTRAST as CELL_LABEL_AUTO_CONTRAST,
                                  AUTO_FORMAT as CELL_LABEL_AUTO_FORMAT,
                                  CELL_LABEL_COLOR, CELL_LABEL_COLOR_MODE, CELL_LABEL_COLOR_MODES,
                                  CELL_LABEL_DECIMALS, CELL_LABEL_FONT_SIZE, CELL_LABEL_NUMBER_FORMAT,
                                  CELL_LABEL_NUMBER_FORMATS, CELL_LABEL_PREFIX, CELL_LABEL_SUFFIX,
                                  CUSTOM_COLOR as CELL_LABEL_CUSTOM_COLOR,
                                  DEFAULT_DECIMALS as DEFAULT_CELL_LABEL_DECIMALS,
                                  format_cell_label, parse_cell_label_options)
from .heatmap_layout import (COLUMN_GAP_MODE, COLUMN_GAP_SIZE, COLUMN_GAPS_AFTER,
                             COLUMN_LABEL_EVERY, COLUMN_LABEL_FONT_SIZE, COLUMN_LABEL_FREQUENCY,
                             COLUMN_LABEL_ROTATION, COLUMN_LABEL_ROTATIONS, COLUMN_LABEL_SIDE,
                             COLUMN_LABEL_SIDES, DEFAULT_GAP_SIZE, DEFAULT_LABEL_EVERY, FREQ_AUTO,
                             FREQ_EVERY, GAP_MODES, GAP_NONE, GAP_SELECTED, LABEL_FREQUENCIES,
                             ROW_GAP_MODE, ROW_GAP_SIZE, ROW_GAPS_AFTER, ROW_LABEL_EVERY,
                             ROW_LABEL_FONT_SIZE, ROW_LABEL_FREQUENCY, ROW_LABEL_SIDE,
                             ROW_LABEL_SIDES, SHOW_COLUMN_LABELS, SHOW_ROW_LABELS,
                             build_layout_table, is_legacy_layout, label_plan, layout_geometry)
from .heatmap_number_format import (AUTO_FORMAT, DEFAULT_DECIMALS, FIXED_FORMAT, LEGEND_DECIMALS, NUMBER_FORMAT,
                                    NUMBER_FORMATS, SCIENTIFIC_FORMAT, format_legend_value, parse_legend_number_format)
from .processing import FieldError, _column, _number
from .reporting import Result, _plot
from .worksheet_series import series_columns, series_labels


HEAT_MAP = "Heat map"
MATRIX, LONG_NUMERIC, LONG_CATEGORIES = FORMATS = ("Matrix", "Long numeric", "Long categories")
MEASURES = ("Mean", "Median", "Geometric mean", "SD", "SEM", "CV (%)")
PALETTES = {"Viridis": "viridis", "Blues": "Blues", "Blue–red": "RdBu_r", "Magma": "magma", "Greys": "Greys"}
LINEAR, DIVERGING = SCALES = ("Linear", "Diverging")
MINIMUM = "Color minimum (blank = automatic)"
CENTER = "Color midpoint (blank = automatic)"
MAXIMUM = "Color maximum (blank = automatic)"
OUTSIDE = "Out-of-range color (blank = clamp)"
# 0.72 color and legend options. Every one is optional: a recipe without them draws exactly as before.
COLOR_MAPPING = "Color mapping"
PALETTE_MAPPING, SINGLE_GRADIENT, DOUBLE_GRADIENT = MAPPINGS = ("Palette", "Single gradient", "Double gradient")
MIN_COLOR, MID_COLOR, MAX_COLOR = "Minimum color", "Midpoint color", "Maximum color"
GRADIENT_COLORS = {MIN_COLOR: "#2166ac", MID_COLOR: "#f7f7f7", MAX_COLOR: "#b2182b"}
OPACITY = "Color opacity"
CATEGORY_COLORS = "Category colors"
CATEGORY_COLOR_LIST = "Category color list"  # Dialog kind of the Category colors field: a {level: color} mapping.
SHOW_LEGEND, REVERSE_LEGEND, LEGEND_TITLE = "Show color legend", "Reverse color legend", "Color legend title"
ORIENTATION = "Color legend orientation"
VERTICAL, HORIZONTAL = ORIENTATIONS = ("Vertical", "Horizontal")
LEGEND_INTERVAL, LEGEND_START = "Color legend interval", "Color legend start"
MAX_TICKS = 200
MAX_CATEGORY_COLORS = 500
MAX_LEVEL_NAME = 1000
LUT_SIZE = 2048  # Gradient look-up table; the anchors stay exact and a channel moves by at most 1/2048.
OPTIONS = {
    "Input format": FORMATS, "Variables": "Multiple", "Row labels": "Optional",
    "X categories": None, "Y categories": None, "Values": None,
    "Cell value": MEASURES, "Transpose": False, "Reverse rows": False, "Reverse columns": False,
    "Cell shape": ("Square", "Stretch"), "Cell borders": False, "Mark missing cells": False,
    "Show cell values": False,
    CELL_LABEL_NUMBER_FORMAT: CELL_LABEL_NUMBER_FORMATS,
    CELL_LABEL_DECIMALS: DEFAULT_CELL_LABEL_DECIMALS,
    CELL_LABEL_FONT_SIZE: "Text",
    CELL_LABEL_COLOR_MODE: CELL_LABEL_COLOR_MODES,
    CELL_LABEL_COLOR: "Text",
    CELL_LABEL_PREFIX: "Text",
    CELL_LABEL_SUFFIX: "Text",
    # Layout tab: cell gaps and axis label placement.
    ROW_GAP_MODE: GAP_MODES, ROW_GAP_SIZE: DEFAULT_GAP_SIZE, ROW_GAPS_AFTER: "Text",
    COLUMN_GAP_MODE: GAP_MODES, COLUMN_GAP_SIZE: DEFAULT_GAP_SIZE, COLUMN_GAPS_AFTER: "Text",
    SHOW_ROW_LABELS: True, ROW_LABEL_FREQUENCY: LABEL_FREQUENCIES, ROW_LABEL_EVERY: DEFAULT_LABEL_EVERY,
    ROW_LABEL_SIDE: ROW_LABEL_SIDES, ROW_LABEL_FONT_SIZE: "Text",
    SHOW_COLUMN_LABELS: True, COLUMN_LABEL_FREQUENCY: LABEL_FREQUENCIES, COLUMN_LABEL_EVERY: DEFAULT_LABEL_EVERY,
    COLUMN_LABEL_ROTATION: COLUMN_LABEL_ROTATIONS, COLUMN_LABEL_SIDE: COLUMN_LABEL_SIDES,
    COLUMN_LABEL_FONT_SIZE: "Text",
    # Colors tab, in the order the dialog shows it.
    COLOR_MAPPING: MAPPINGS, "Palette": tuple(PALETTES), "Color scale": SCALES,
    MIN_COLOR: "Text", MID_COLOR: "Text", MAX_COLOR: "Text",
    MINIMUM: "Text", CENTER: "Text", MAXIMUM: "Text", "Missing color": "Text", OUTSIDE: "Text", OPACITY: 1.0,
    # Categories and Legend tabs.
    CATEGORY_COLORS: CATEGORY_COLOR_LIST,
    SHOW_LEGEND: True, ORIENTATION: ORIENTATIONS, REVERSE_LEGEND: False, LEGEND_TITLE: "Text",
    LEGEND_INTERVAL: "Text", LEGEND_START: "Text",
    NUMBER_FORMAT: NUMBER_FORMATS, LEGEND_DECIMALS: DEFAULT_DECIMALS,
}
# Dialog sections. The Colors tab keeps the name the 0.72 dialog used; every field of the heat map has one place.
LAYOUT_FIELDS = (
    ROW_GAP_MODE, ROW_GAP_SIZE, ROW_GAPS_AFTER,
    COLUMN_GAP_MODE, COLUMN_GAP_SIZE, COLUMN_GAPS_AFTER,
    SHOW_ROW_LABELS, ROW_LABEL_FREQUENCY, ROW_LABEL_EVERY, ROW_LABEL_SIDE, ROW_LABEL_FONT_SIZE,
    SHOW_COLUMN_LABELS, COLUMN_LABEL_FREQUENCY, COLUMN_LABEL_EVERY, COLUMN_LABEL_ROTATION,
    COLUMN_LABEL_SIDE, COLUMN_LABEL_FONT_SIZE,
)
COLOR_FIELDS = (COLOR_MAPPING, "Palette", "Color scale", MIN_COLOR, MID_COLOR, MAX_COLOR, MINIMUM, CENTER, MAXIMUM,
                "Missing color", OUTSIDE, OPACITY)
CATEGORY_FIELDS = (CATEGORY_COLORS,)
LEGEND_FIELDS = (SHOW_LEGEND, ORIENTATION, REVERSE_LEGEND, LEGEND_TITLE, LEGEND_INTERVAL, LEGEND_START,
                 NUMBER_FORMAT, LEGEND_DECIMALS)
TAB_LAYOUT, TAB_COLORS, TAB_CATEGORIES, TAB_LEGEND = "Layout", "Colors", "Categories", "Legend"
TABS = {TAB_LAYOUT: LAYOUT_FIELDS, TAB_COLORS: COLOR_FIELDS, TAB_CATEGORIES: CATEGORY_FIELDS, TAB_LEGEND: LEGEND_FIELDS}
MAX_CELLS = 20_000
MAX_AXIS = 200
MAX_ANNOTATED = 400
MAX_LEVELS = 20


def _choice(options, field, choices):
    value = options.get(field, next(iter(choices)))
    if not isinstance(value, str) or value not in choices:
        raise FieldError(field, f"Choose a valid {field.lower()}.")
    return value


def visibility(input_format, scale, mapping=PALETTE_MAPPING, interval=None, show_legend=True,
               number_format=AUTO_FORMAT, show_cell_values=False,
               cell_label_number_format=CELL_LABEL_AUTO_FORMAT,
               cell_label_color_mode=CELL_LABEL_AUTO_CONTRAST,
               row_gap_mode=GAP_NONE, column_gap_mode=GAP_NONE,
               show_row_labels=True, row_label_frequency=FREQ_AUTO,
               show_column_labels=True, column_label_frequency=FREQ_AUTO):
    """Fields that apply to the current choices; the others are inactive, never validated and never saved."""
    matrix = input_format == MATRIX
    numeric = input_format != LONG_CATEGORIES
    palette = numeric and mapping not in (SINGLE_GRADIENT, DOUBLE_GRADIENT)
    double = numeric and mapping == DOUBLE_GRADIENT
    explicit = interval is not None and not (isinstance(interval, str) and not interval.strip())
    show_numeric_legend = numeric and show_legend
    show_labels = bool(show_cell_values)
    show_numeric_labels = numeric and show_labels
    row_labels_on = bool(show_row_labels)
    column_labels_on = bool(show_column_labels)
    return {"Variables": matrix, "Row labels": matrix, "X categories": not matrix,
            "Y categories": not matrix, "Values": not matrix, "Cell value": numeric,
            CELL_LABEL_NUMBER_FORMAT: show_numeric_labels,
            CELL_LABEL_DECIMALS: (show_numeric_labels
                                  and cell_label_number_format in (FIXED_FORMAT, SCIENTIFIC_FORMAT)),
            CELL_LABEL_FONT_SIZE: show_labels,
            CELL_LABEL_COLOR_MODE: show_labels,
            CELL_LABEL_COLOR: show_labels and cell_label_color_mode == CELL_LABEL_CUSTOM_COLOR,
            CELL_LABEL_PREFIX: show_labels,
            CELL_LABEL_SUFFIX: show_labels,
            ROW_GAP_SIZE: row_gap_mode != GAP_NONE,
            ROW_GAPS_AFTER: row_gap_mode == GAP_SELECTED,
            COLUMN_GAP_SIZE: column_gap_mode != GAP_NONE,
            COLUMN_GAPS_AFTER: column_gap_mode == GAP_SELECTED,
            ROW_LABEL_FREQUENCY: row_labels_on,
            ROW_LABEL_EVERY: row_labels_on and row_label_frequency == FREQ_EVERY,
            ROW_LABEL_SIDE: row_labels_on,
            ROW_LABEL_FONT_SIZE: row_labels_on,
            COLUMN_LABEL_FREQUENCY: column_labels_on,
            COLUMN_LABEL_EVERY: column_labels_on and column_label_frequency == FREQ_EVERY,
            COLUMN_LABEL_ROTATION: column_labels_on,
            COLUMN_LABEL_SIDE: column_labels_on,
            COLUMN_LABEL_FONT_SIZE: column_labels_on,
            COLOR_MAPPING: numeric, "Palette": palette, "Color scale": palette,
            MIN_COLOR: numeric and not palette, MID_COLOR: double, MAX_COLOR: numeric and not palette,
            MINIMUM: numeric, MAXIMUM: numeric,
            CENTER: double or (palette and scale == DIVERGING), OUTSIDE: numeric,
            CATEGORY_COLORS: not numeric, REVERSE_LEGEND: show_legend, LEGEND_TITLE: show_legend,
            ORIENTATION: show_numeric_legend, LEGEND_INTERVAL: show_numeric_legend,
            LEGEND_START: show_numeric_legend and explicit,
            NUMBER_FORMAT: show_numeric_legend,
            LEGEND_DECIMALS: show_numeric_legend and number_format in (FIXED_FORMAT, SCIENTIFIC_FORMAT)}


def _check_size(nrows, ncols):
    if max(nrows, ncols) > MAX_AXIS or nrows * ncols > MAX_CELLS:
        raise FieldError("Input format", "Choose fewer heat-map rows or columns.")


def _text_values(frame, name, field):
    if not name or name not in frame:
        raise FieldError(field, f"Choose a column for {field}.")
    values = frame[name].astype("string").fillna("")
    return values.where(values.str.strip().ne(""), "").to_numpy(dtype=object)


def _summarize(values, method):
    values = values[np.isfinite(values)]
    count = len(values)
    if not count:
        return np.nan
    if method == "Geometric mean":
        if (values <= 0).any():
            raise FieldError("Cell value", "The geometric mean requires strictly positive values.")
        return float(np.exp(np.log(values).mean()))
    if method in {"SD", "SEM", "CV (%)"} and count < 2:
        return np.nan
    scale = np.abs(values).max()
    scaled = values / (scale or 1)
    if method == "Median":
        return float(np.median(scaled) * scale)
    center = scaled.mean()
    if method == "Mean":
        return float(center * scale)
    sd = scaled.std(ddof=1)
    if method == "CV (%)":
        if center == 0:
            return np.nan
        result = (sd / center) * 100
    else:
        result = (sd / sqrt(count) if method == "SEM" else sd) * scale
    if not np.isfinite(result):
        raise FieldError("Cell value", "A heat-map summary is outside the supported numeric range.")
    return float(result)


def _matrix(frame, options, measure):
    names = options.get("Variables", ())
    if (not isinstance(names, (list, tuple)) or not names
            or any(not isinstance(name, str) for name in names) or len(names) != len(set(names))):
        raise FieldError("Variables", "Choose one or more distinct numeric variables.")
    row_name = options.get("Row labels") or next(
        (name for name in frame.columns if name.casefold() in {"row title", "row titles"}), None)
    names = [name for name in names if name != row_name]
    if not names:
        raise FieldError("Variables", "Choose a numeric column other than the row labels.")
    labels = _text_values(frame, row_name, "Row labels") if row_name else np.full(len(frame), "", dtype=object)
    matrix = np.column_stack([_column(frame, name, "Variables") for name in names])
    valid_rows = np.flatnonzero(np.isfinite(matrix).any(axis=1) | (labels != ""))
    if not len(valid_rows):
        raise FieldError("Variables", "The selected variables contain no observations.")
    end = valid_rows[-1] + 1
    kind = str(frame.attrs.get("table_format") or "").casefold()
    groups = series_columns(frame, names, recognize_replicates=kind in {"grouped", "twoway", "two way"})
    _check_size(end, len(groups))
    indices = {name: index for index, name in enumerate(names)}
    columns = []
    for group in groups:
        if len(group) > 1 and any(_SUMMARY.fullmatch(name) for name in group):
            raise FieldError("Variables", "Select a single precomputed measure per worksheet series.")
        values = matrix[:end, [indices[name] for name in group]]
        columns.append([_summarize(row, measure) for row in values])
    row_names = [label or f"Row {index}" for index, label in enumerate(labels[:end], 1)]
    return pd.DataFrame(np.asarray(columns).T, index=row_names, columns=series_labels(groups))


def _long(frame, options, measure, categorical):
    x_name, y_name, values_name = (options.get(field) for field in ("X categories", "Y categories", "Values"))
    if any(not isinstance(name, str) or not name for name in (x_name, y_name, values_name)):
        raise FieldError("Values", "Choose a column for each axis and the cell value.")
    if len({x_name, y_name, values_name}) != 3:
        raise FieldError("Values", "Choose distinct columns for the two axes and cell values.")
    x = _text_values(frame, x_name, "X categories")
    y = _text_values(frame, y_name, "Y categories")
    values = (_text_values(frame, values_name, "Values") if categorical
              else _column(frame, values_name, "Values").to_numpy())
    valid = (x != "") & (y != "")
    x, y, values = x[valid], y[valid], values[valid]
    row_names, column_names = list(pd.unique(y)), list(pd.unique(x))
    if not row_names or not column_names:
        raise FieldError("Values", "No observations have both axis categories.")
    _check_size(len(row_names), len(column_names))
    rows, columns = ({name: i for i, name in enumerate(names)} for names in (row_names, column_names))
    matrix = np.full((len(rows), len(columns)), None if categorical else np.nan,
                     dtype=object if categorical else float)
    if categorical:
        seen = set()
        for y_label, x_label, value in zip(y, x, values, strict=True):
            cell = rows[y_label], columns[x_label]
            if cell not in seen:
                matrix[cell] = value or None
                seen.add(cell)
    else:
        groups = pd.DataFrame({"Row": y, "Column": x, "Value": values}).groupby(["Row", "Column"], sort=False)
        for (y_label, x_label), group in groups:
            matrix[rows[y_label], columns[x_label]] = _summarize(group["Value"].to_numpy(), measure)
    return pd.DataFrame(matrix, index=row_names, columns=column_names)


def _color(options, field, default):
    value = options.get(field) or default
    if not isinstance(value, str) or (value and not is_color_like(value)):
        raise FieldError(field, "Choose a valid color name or hexadecimal color.")
    return value


def _bound(options, field, default):
    value = options.get(field)
    return default if value is None or isinstance(value, str) and not value.strip() else _number(value, field)


def _real(value, field, what="a finite number"):
    """A real number from a number or numeric text; booleans, blanks and non-finite values are refused."""
    if isinstance(value, (bool, np.bool_)):
        raise FieldError(field, f"{field} must be {what}.")
    try:
        number = float(decimal_comma(value) if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError):
        raise FieldError(field, f"{field} must be {what}.") from None
    if not np.isfinite(number):
        raise FieldError(field, f"{field} must be {what}.")
    return number


def _flag(options, field, default):
    value = options.get(field, default)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(field, f"{field} must be on or off.")
    return bool(value)


def _opacity(options):
    value = options.get(OPACITY, 1.0)
    number = _real(value, OPACITY, "a number from 0 to 1")
    if not 0 <= number <= 1:
        raise FieldError(OPACITY, f"{OPACITY} must be between 0 and 1.")
    return number


def _faded(rgba, opacity):
    """The color of an observation: its own alpha times the heat-map opacity."""
    red, green, blue, alpha = to_rgba(rgba)
    return red, green, blue, alpha * opacity


def _gradient(options, mapping, opacity):
    """Linear interpolation of sRGB channels and alpha between the anchors; the midpoint sits at norm 0.5."""
    names = (MIN_COLOR, MID_COLOR, MAX_COLOR) if mapping == DOUBLE_GRADIENT else (MIN_COLOR, MAX_COLOR)
    anchors = [_faded(_color(options, name, GRADIENT_COLORS[name]), opacity) for name in names]
    return LinearSegmentedColormap.from_list("heat-map gradient", anchors, N=LUT_SIZE)


def _palette(options, opacity):
    cmap = colormaps[PALETTES[_choice(options, "Palette", PALETTES)]]
    if opacity == 1:
        return cmap
    colors = cmap(np.linspace(0, 1, cmap.N))
    colors[:, 3] *= opacity
    return ListedColormap(colors, name=cmap.name).with_extremes(
        under=_faded(cmap.get_under(), opacity), over=_faded(cmap.get_over(), opacity))


def _numeric_colors(values, options, missing):
    observations = values[np.isfinite(values)]
    if not len(observations):
        raise FieldError("Cell value", "No cells have a defined value for this summary.")
    mapping = _choice(options, COLOR_MAPPING, MAPPINGS)
    palette = mapping == PALETTE_MAPPING
    # The palette and its scale are inactive under a gradient: they neither change the colors nor block the dialog.
    scale = _choice(options, "Color scale", SCALES) if palette else (
        DIVERGING if mapping == DOUBLE_GRADIENT else LINEAR)
    if palette:
        _choice(options, "Palette", PALETTES)
    opacity = _opacity(options)
    requested_low = _bound(options, MINIMUM, None)
    requested_high = _bound(options, MAXIMUM, None)
    low = float(observations.min()) if requested_low is None else requested_low
    high = float(observations.max()) if requested_high is None else requested_high
    if low == high and requested_low is None and requested_high is None:
        margin = abs(low) * .04 or 1
        low, high = max(-1e308, low - margin), min(1e308, high + margin)
    if not low < high or not np.isfinite(high - low):
        raise FieldError(MAXIMUM, "Choose finite color limits with the maximum greater than the minimum.")
    norm = Normalize(low, high)
    if scale == DIVERGING:
        default = 0. if low < 0 < high else .5 * low + .5 * high
        center = _bound(options, CENTER, default)
        if not low < center < high:
            raise FieldError(CENTER, "The midpoint must be strictly between the color limits.")
        norm = TwoSlopeNorm(center, vmin=low, vmax=high)
    outside = _color(options, OUTSIDE, "")
    cmap = (_palette(options, opacity) if palette else _gradient(options, mapping, opacity)).with_extremes(bad=missing)
    extend = "neither"
    if outside:
        cmap = cmap.with_extremes(under=_faded(outside, opacity), over=_faded(outside, opacity))
        below, above = observations.min() < low, observations.max() > high
        extend = {(True, True): "both", (True, False): "min", (False, True): "max"}.get((below, above), "neither")
    return norm, cmap, extend, (low, high)


def check_category_colors(value):
    """The {level: color} mapping of Category colors, validated, as a new dict of text pairs."""
    if value is None or value == "":
        return {}
    if not isinstance(value, dict):
        raise FieldError(CATEGORY_COLORS, "Category colors must be a mapping from each level to a color.")
    if len(value) > MAX_CATEGORY_COLORS:
        raise FieldError(CATEGORY_COLORS, f"Use at most {MAX_CATEGORY_COLORS} category colors.")
    checked = {}
    for level, color in value.items():
        if not isinstance(level, str) or not level or len(level) > MAX_LEVEL_NAME:
            raise FieldError(CATEGORY_COLORS, "Each category name must be text of 1 to 1000 characters.")
        if not isinstance(color, str) or not color.strip() or not is_color_like(color):
            raise FieldError(CATEGORY_COLORS, f"Choose a valid color for the category {level}.")
        checked[level] = color
    return checked


def _categorical_colors(values, missing, levels, options):
    if not 1 <= len(levels) <= MAX_LEVELS:
        raise FieldError("Values", f"Choose a variable with 1 to {MAX_LEVELS} observed categories.")
    custom = check_category_colors(options.get(CATEGORY_COLORS))
    opacity = _opacity(options)
    mapping = {value: index for index, value in enumerate(levels)}
    indexed = np.array([mapping.get(value, np.nan) for value in values.flat]).reshape(values.shape)
    cmap = colormaps["tab20"].resampled(len(levels))
    if custom or opacity != 1:
        # The color follows the level text, never its row or legend position; other levels keep the palette.
        colors = [_faded(custom.get(level, cmap(index)), opacity) for index, level in enumerate(levels)]
        cmap = ListedColormap(colors, name="heat-map categories")
    cmap = cmap.with_extremes(bad=missing)
    norm = BoundaryNorm(np.arange(len(levels) + 1) - .5, len(levels))
    return indexed, norm, cmap


def legend_ticks(low, high, options):
    """Explicit tick positions, or None for the automatic ones. The count is known before anything is built."""
    interval = options.get(LEGEND_INTERVAL)
    if interval is None or isinstance(interval, str) and not interval.strip():
        return None
    step = _real(interval, LEGEND_INTERVAL)
    if step <= 0:
        raise FieldError(LEGEND_INTERVAL, f"{LEGEND_INTERVAL} must be greater than zero.")
    start = options.get(LEGEND_START)
    first = low if start is None or isinstance(start, str) and not start.strip() else _real(start, LEGEND_START)
    if not low <= first <= high:
        raise FieldError(LEGEND_START, f"{LEGEND_START} must lie between the color limits.")
    step, first, top = (Decimal(repr(float(x))) for x in (step, first, high))
    count = int(((top - first) / step).to_integral_value(rounding=ROUND_FLOOR)) + 1
    if count > MAX_TICKS:
        raise FieldError(LEGEND_INTERVAL, f"{LEGEND_INTERVAL} would draw {count} ticks; use at most {MAX_TICKS}.")
    return [float(first + index * step) for index in range(count)]


def _ticks(axes, names, axis):
    step = max(1, (len(names) + 24) // 25)
    positions = np.arange(0, len(names), step)
    labels = [str(names[index]) for index in positions]
    if axis == "x":
        axes.set_xticks(positions + .5, labels, rotation=40, ha="right", parse_math=False)
    else:
        axes.set_yticks(positions + .5, labels, parse_math=False)


def _literal_title(text, title):
    """Show title as typed: no mathtext, so $…$ stays as written."""
    text.set_text(title)
    text.set_parse_math(False)


def _numeric_legend(figure, plot, cax, options, extend, limits):
    """The color bar of a numeric map. It shares the mesh's norm and colormap, so transparency and the
    out-of-range color are drawn exactly as in the cells; ticks never change the data limits."""
    horizontal = _choice(options, ORIENTATION, ORIENTATIONS) == HORIZONTAL
    reverse = _flag(options, REVERSE_LEGEND, False)
    title = options.get(LEGEND_TITLE)
    if title is not None and not isinstance(title, str):
        raise FieldError(LEGEND_TITLE, f"{LEGEND_TITLE} must be text.")
    ticks = legend_ticks(*limits, options)
    number_mode, number_decimals = parse_legend_number_format(options)
    if cax is None:
        # Follow the rendered map's width, including after equal-aspect adjustment and resizing.
        # Figure.colorbar(ax=...) instead follows the subplot slot and can dwarf a narrow square-cell map.
        bar = figure.colorbar(plot, ax=plot.axes, orientation="horizontal", location="bottom",
                              extend=extend, fraction=.06, pad=.14, aspect=30)
        locator = bar.ax.get_axes_locator()

        def aligned(axes, renderer):
            # Retain the space reserved by constrained layout for ticks and title. Also retain
            # the locator's inset for extension triangles, expressed relative to the map width.
            bounds = locator(axes, renderer) if locator else axes.get_position(original=True)
            original, area = axes.get_position(original=True), plot.axes.get_position()
            left = area.x0 + (bounds.x0 - original.x0) / original.width * area.width
            right = area.x0 + (bounds.x1 - original.x0) / original.width * area.width
            axes.set_box_aspect(None)
            return Bbox.from_extents(left, bounds.y0, right, bounds.y1)

        bar.ax.set_axes_locator(aligned)
    else:
        bar = figure.colorbar(plot, cax=cax, extend=extend)
    if ticks is not None:
        bar.set_ticks(ticks)
    if number_mode != AUTO_FORMAT:
        bar.formatter = FuncFormatter(
            lambda value, _pos, mode=number_mode, decimals=number_decimals: format_legend_value(
                float(value), mode, decimals))
        bar.update_ticks()
    if title:
        axis = bar.ax.xaxis if horizontal else bar.ax.yaxis
        bar.set_label(title)
        axis.label.set_parse_math(False)
    if reverse:
        # Only the direction of the bar changes: the cells keep their colors and the ticks follow the bar.
        (bar.ax.invert_xaxis if horizontal else bar.ax.invert_yaxis)()
    return bar


def _categorical_legend(axes, cmap, norm, levels, options, *, row_right=False):
    reverse = _flag(options, REVERSE_LEGEND, False)
    title = options.get(LEGEND_TITLE)
    if title is not None and not isinstance(title, str):
        raise FieldError(LEGEND_TITLE, f"{LEGEND_TITLE} must be text.")
    handles = [Patch(color=cmap(norm(i)), label=label) for i, label in enumerate(levels)]
    if reverse:
        handles.reverse()
    if row_right:
        anchor = {"loc": "center right", "bbox_to_anchor": (-0.03, .5)}
    else:
        anchor = {"loc": "center left", "bbox_to_anchor": (1.02, .5)}
    legend = axes.legend(handles=handles, **anchor,
                         ncols=2 if len(levels) > 10 else 1, frameon=False, title=title or None)
    for text in legend.get_texts():
        text.set_parse_math(False)
    if title:
        legend.get_title().set_parse_math(False)
    return legend


def _apply_axis_labels(axes, geometry, row_plan, col_plan):
    if not col_plan["visible"]:
        axes.set_xticks([])
        axes.tick_params(axis="x", bottom=False, top=False, labelbottom=False, labeltop=False)
    else:
        positions = [geometry["xcenters"][index] for index in col_plan["indices"]]
        top = col_plan["side"] == "Top"
        rotation = col_plan["rotation"]
        ha = "center" if rotation in (0, 90) else ("left" if top else "right")
        kwargs = {"rotation": rotation, "ha": ha, "parse_math": False}
        if col_plan["font_size"] is not None:
            kwargs["fontsize"] = col_plan["font_size"]
        axes.set_xticks(positions, col_plan["labels"], **kwargs)
        axes.xaxis.set_ticks_position("top" if top else "bottom")
        axes.tick_params(axis="x", length=0)

    if not row_plan["visible"]:
        axes.set_yticks([])
        axes.tick_params(axis="y", left=False, right=False, labelleft=False, labelright=False)
    else:
        positions = [geometry["ycenters"][index] for index in row_plan["indices"]]
        right = row_plan["side"] == "Right"
        kwargs = {"parse_math": False}
        if row_plan["font_size"] is not None:
            kwargs["fontsize"] = row_plan["font_size"]
        axes.set_yticks(positions, row_plan["labels"], **kwargs)
        axes.yaxis.set_ticks_position("right" if right else "left")
        axes.tick_params(axis="y", length=0)


def _cell_collection(numeric, geometry, cmap, norm, borders):
    nrows, ncols = numeric.shape
    x0 = np.asarray(geometry["x0"], dtype=float)
    x1 = np.asarray(geometry["x1"], dtype=float)
    y0 = np.asarray(geometry["y0"], dtype=float)
    y1 = np.asarray(geometry["y1"], dtype=float)
    left = np.broadcast_to(x0[None, :], (nrows, ncols)).ravel()
    right = np.broadcast_to(x1[None, :], (nrows, ncols)).ravel()
    top = np.broadcast_to(y0[:, None], (nrows, ncols)).ravel()
    bottom = np.broadcast_to(y1[:, None], (nrows, ncols)).ravel()
    verts = np.empty((nrows * ncols, 4, 2), dtype=float)
    verts[:, 0, 0] = left
    verts[:, 0, 1] = top
    verts[:, 1, 0] = right
    verts[:, 1, 1] = top
    verts[:, 2, 0] = right
    verts[:, 2, 1] = bottom
    verts[:, 3, 0] = left
    verts[:, 3, 1] = bottom
    collection = PolyCollection(
        verts,
        cmap=cmap,
        norm=norm,
        edgecolors="#f8fafc" if borders else "none",
        linewidths=.5 if borders else 0,
    )
    collection.set_array(np.ma.masked_invalid(numeric.ravel()))
    return collection


def _render_heat_map(table, options, levels):
    values = table.to_numpy()
    missing = _color(options, "Missing color", "#e6ebf0")
    categorical = levels is not None
    legend = _flag(options, SHOW_LEGEND, True)
    cax = None
    if categorical:
        figure, axes = _plot("Heat map")
        numeric, norm, cmap = _categorical_colors(values, missing, levels, options)
    else:
        figure = Figure(figsize=(8, 5), dpi=100, layout="constrained")
        horizontal = legend and _choice(options, ORIENTATION, ORIENTATIONS) == HORIZONTAL
        if legend and not horizontal:
            grid = figure.add_gridspec(1, 2, width_ratios=(1, .035), wspace=.035)
            axes = figure.add_subplot(grid[0, 0])
            cax = figure.add_subplot(grid[0, 1])
        else:
            # A hidden legend leaves no empty axis, and a horizontal one is carved out of the map's own space.
            axes = figure.add_subplot()
        axes.set_title("Heat map")
        axes.spines[["right", "top"]].set_visible(False)
        numeric = values
        norm, cmap, extend, limits = _numeric_colors(values, options, missing)
    nrows, ncols = len(table.index), len(table.columns)
    geometry = layout_geometry(nrows, ncols, options)
    row_plan = label_plan(table.index, "row", options)
    col_plan = label_plan(table.columns, "column", options)
    legacy = is_legacy_layout(options)
    borders = options.get("Cell borders", False)
    shape = _choice(options, "Cell shape", OPTIONS["Cell shape"])
    aspect = "equal" if shape == "Square" else "auto"
    if legacy:
        plot = axes.pcolormesh(numeric, cmap=cmap, norm=norm, shading="flat",
                               edgecolors="#f8fafc" if borders else "none", linewidth=.5 if borders else 0)
        axes.set(xlim=(0, ncols), ylim=(nrows, 0), aspect=aspect)
        _ticks(axes, table.columns, "x")
        _ticks(axes, table.index, "y")
        axes.tick_params(length=0)
        xcenters = [col + .5 for col in range(ncols)]
        ycenters = [row + .5 for row in range(nrows)]
    else:
        plot = _cell_collection(numeric, geometry, cmap, norm, borders)
        axes.add_collection(plot)
        axes.update_datalim(((0.0, 0.0), (geometry["width"], geometry["height"])))
        axes.set(xlim=(0.0, geometry["width"]), ylim=(geometry["height"], 0.0), aspect=aspect)
        _apply_axis_labels(axes, geometry, row_plan, col_plan)
        xcenters = geometry["xcenters"]
        ycenters = geometry["ycenters"]
    if categorical:
        if legend:
            _categorical_legend(
                axes, cmap, norm, levels, options,
                row_right=not legacy and row_plan["visible"] and row_plan["side"] == "Right",
            )
    elif legend:
        _numeric_legend(figure, plot, cax, options, extend, limits)
    annotations = options.get("Show cell values", False)
    mark_missing = options.get("Mark missing cells", False)
    label_settings = parse_cell_label_options(options, categorical=categorical) if annotations else None
    if (annotations or mark_missing) and table.size > MAX_ANNOTATED:
        field = "Show cell values" if annotations else "Mark missing cells"
        raise FieldError(field, f"Use at most {MAX_ANNOTATED} cells when displaying text in the heat map.")
    if annotations or mark_missing:
        font_kwargs = ({"fontsize": label_settings.font_size}
                       if label_settings is not None and label_settings.font_size is not None else {})
        for (row, col), value in np.ndenumerate(numeric):
            xcenter, ycenter = xcenters[col], ycenters[row]
            if not np.isfinite(value):
                if mark_missing:
                    axes.text(xcenter, ycenter, "×", ha="center", va="center", color="#36485a")
            elif annotations:
                if label_settings.color_mode == CELL_LABEL_CUSTOM_COLOR:
                    text_color = label_settings.color
                else:
                    color = cmap(norm(value))
                    brightness = color[0] * .2126 + color[1] * .7152 + color[2] * .0722
                    text_color = "#162633" if brightness > .55 else "#ffffff"
                raw_value = values[row, col] if categorical else value
                label = format_cell_label(raw_value, label_settings, categorical=categorical)
                axes.text(xcenter, ycenter, label, ha="center", va="center",
                          color=text_color, parse_math=False, **font_kwargs)
    return figure, geometry, legacy


def _draw_heat_map(table, options, levels):
    return _render_heat_map(table, options, levels)[0]


def category_levels(frame, options):
    """Level texts of a Long categories map in the order the legend lists them (first occurrence)."""
    table = _long(frame, options, None, True)
    return list(dict.fromkeys(value for value in table.to_numpy().flat if pd.notna(value)))


def heat_map(frame, options):
    input_format = _choice(options, "Input format", FORMATS)
    categorical = input_format == LONG_CATEGORIES
    measure = None if categorical else _choice(options, "Cell value", MEASURES)
    table = _matrix(frame, options, measure) if input_format == MATRIX else _long(frame, options, measure, categorical)
    levels = None
    if categorical:
        levels = list(dict.fromkeys(value for value in table.to_numpy().flat if pd.notna(value)))
    if options.get("Transpose", False):
        table = table.T
    if options.get("Reverse rows", False):
        table = table.iloc[::-1]
    if options.get("Reverse columns", False):
        table = table.iloc[:, ::-1]
    table.index.name = "Row"
    figure, geometry, legacy = _render_heat_map(table, options, levels)
    tables = {"Heat map data": table}
    if not legacy:
        tables["Heat map layout"] = build_layout_table(table.index, table.columns, geometry)
    return Result(tables, figure)
