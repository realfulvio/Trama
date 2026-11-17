"""Parts-of-whole graphics and goodness of fit for categorical counts."""
from math import ceil, cos, fsum, isclose, radians, sin, sqrt
import re

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba
from scipy.stats import chi2

from .category_graphs import COLORS
from .contingency import MAX_TOTAL, _whole_count
from .processing import TEXT, FieldError, _column
from .reporting import Result, _plot, _report


PARTS_GRAPH = "Parts of whole graph"
GOODNESS_OF_FIT = "Compare observed distribution with expected"
DONUT, PIE, HORIZONTAL, VERTICAL, DOTS = "Donut", "Pie", "Horizontal slices", "Vertical slices", "Dot plot"
STYLES = (DONUT, PIE, HORIZONTAL, VERTICAL, DOTS)
LEGENDS = ("Category and percent", "Category and value", "Category only", "None")
EXPECTED = ("Equal proportions", "Weights in a column", "Expected counts in a column")
START_ANGLE, CLOCKWISE = "Start angle", "Clockwise"
SLICE_LABELS, BORDER_COLOR, BORDER_WIDTH = "Slice labels", "Border color", "Border width"
SEGMENT_STYLES, APPLY_SEGMENT_STYLES = "Segment styles", "Apply segment styles"
SLICE_LABEL_CHOICES = ("None", "Percent")
# A slice style is bound to the sheet row number (1-based iloc), not to the category
# label. Inserting or deleting rows changes which category sits on that number.
# Duplicate labels do not share a style. The style is resolved before blank rows are
# dropped and before Reverse order is applied.
PARTS_OPTIONS = {
    "Values": None, "Row titles": "Optional", "Graph style": STYLES, "Legend": LEGENDS,
    "Reverse order": False, "Show total": True, "Donut hole (%)": 52., "Number of dots": 100,
    START_ANGLE: 90., CLOCKWISE: True, SLICE_LABELS: SLICE_LABEL_CHOICES,
    BORDER_COLOR: TEXT, BORDER_WIDTH: 1.3,
}
_ROW_KEY = re.compile(r"row:[1-9]\d*$")
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$")
_STYLE_FIELDS = ("color", "explode", "visible")
_EXPLODE_LIMIT = 0.35
GOODNESS_OPTIONS = {
    "Observed counts": None, "Row titles": "Optional", "Expected distribution": EXPECTED,
    "Expected values": "Optional", "Estimated parameters": 0,
}
MAX_PARTS = 128
MAX_GRAPH_PARTS = 24


def _choice(options, field, values):
    choice = options.get(field, values[0])
    if choice not in values:
        raise FieldError(field, f"Choose a valid {field.lower()}.")
    return choice


def _titles(frame, positions, options):
    name = options.get("Row titles")
    if name is None and len(frame.columns):
        first = frame.columns[0]
        roles = frame.attrs.get("worksheet_roles")
        if first.casefold() in {"row title", "row titles"} or (
                roles and first not in {item for group in roles["y"] for item in group}):
            name = first
    if name is not None and name not in frame:
        raise FieldError("Row titles", "Choose an existing row title column.")
    titles = []
    for position in positions:
        raw = frame[name].iloc[position] if name else None
        titles.append(str(raw) if pd.notna(raw) and str(raw).strip() else f"Row {position + 1}")
    return titles


def pie_value_is_default(label, value):
    """True when a pie-only option matches the historical pie and can be omitted."""
    if label == START_ANGLE:
        try:
            return np.isfinite(float(value)) and float(value) % 360 == 90
        except (TypeError, ValueError, OverflowError):
            return False
    if label == CLOCKWISE:
        return value is True
    if label == SLICE_LABELS:
        return value == "None"
    if label == BORDER_COLOR:
        try:
            return to_rgba(value) == to_rgba("white")
        except (ValueError, TypeError):
            return False
    if label == BORDER_WIDTH:
        try:
            return abs(float(value) - 1.3) <= 1e-12
        except (TypeError, ValueError, OverflowError):
            return False
    return False


def _finite_number(value, field, message):
    if isinstance(value, bool):
        raise FieldError(field, message)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise FieldError(field, message) from None
    if not np.isfinite(number):
        raise FieldError(field, message)
    return number


def _one_style(number, style, *, allow_explode=True):
    if not isinstance(style, dict):
        raise FieldError(SEGMENT_STYLES, f"Row {number} needs a style.")
    unknown = next((name for name in style if name not in _STYLE_FIELDS), None)
    if unknown is not None:
        raise FieldError(SEGMENT_STYLES, f"Row {number}: {unknown} is not a slice setting. "
                                         "Use color, explode or visible.")
    cleaned = {}
    if "color" in style:
        color = style["color"]
        if not isinstance(color, str) or _COLOR.fullmatch(color) is None:
            raise FieldError(SEGMENT_STYLES, f"Row {number}: color must be #RRGGBB or #RRGGBBAA.")
        cleaned["color"] = color
    if allow_explode and "explode" in style:
        explode = _finite_number(style["explode"], SEGMENT_STYLES,
                                 f"Row {number}: explode must be between 0 and {_EXPLODE_LIMIT}.")
        if not 0 <= explode <= _EXPLODE_LIMIT:
            raise FieldError(SEGMENT_STYLES, f"Row {number}: explode must be between 0 and {_EXPLODE_LIMIT}.")
        if explode != 0:
            cleaned["explode"] = explode
    if "visible" in style:
        visible = style["visible"]
        if not isinstance(visible, bool):
            raise FieldError(SEGMENT_STYLES, f"Row {number}: visible must be yes or no.")
        if visible is False:
            cleaned["visible"] = False
    return cleaned


def segment_styles(frame, raw, *, allow_explode=True):
    """Validate the row-number style map. An empty map means every slice keeps its default."""
    if raw in (None, {}, ()):
        return {}
    if not isinstance(raw, dict):
        raise FieldError(SEGMENT_STYLES, "Segment styles must be a map of row styles.")
    limit = len(frame)
    cleaned = {}
    for key, style in raw.items():
        if not isinstance(key, str) or _ROW_KEY.fullmatch(key) is None:
            raise FieldError(SEGMENT_STYLES, f"{key!r} is not a sheet row (use row:1, row:2, …).")
        number = int(key.split(":", 1)[1])
        if not 1 <= number <= limit:
            raise FieldError(SEGMENT_STYLES, f"Row {number} is outside this sheet (1–{limit}).")
        item = _one_style(number, style, allow_explode=allow_explode)
        if item:
            cleaned[number] = item
    return cleaned


def _pie_settings(options):
    if START_ANGLE not in options or options[START_ANGLE] in (None, ""):
        angle = 90.0
    else:
        angle = _finite_number(options[START_ANGLE], START_ANGLE, "Start angle must be a finite number of degrees.")
        angle %= 360
    if CLOCKWISE not in options:
        clockwise = True
    else:
        clockwise = options[CLOCKWISE]
        if not isinstance(clockwise, bool):
            raise FieldError(CLOCKWISE, "Clockwise must be yes or no.")
    labels = options.get(SLICE_LABELS, "None") or "None"
    if labels not in SLICE_LABEL_CHOICES:
        raise FieldError(SLICE_LABELS, "Choose None or Percent for slice labels.")
    border = options.get(BORDER_COLOR) or "white"
    try:
        to_rgba(border)
    except (ValueError, TypeError):
        raise FieldError(BORDER_COLOR, "Border color must be a color such as #RRGGBB.") from None
    if BORDER_WIDTH not in options or options[BORDER_WIDTH] in (None, ""):
        border_width = 1.3
    else:
        border_width = _finite_number(options[BORDER_WIDTH], BORDER_WIDTH,
                                      "Border width must be between 0 and 6 points.")
        if not 0 <= border_width <= 6:
            raise FieldError(BORDER_WIDTH, "Border width must be between 0 and 6 points.")
    return angle, clockwise, labels, border, border_width


def sheet_rows(frame, options):
    """Every sheet row, with its title and share, before blank or zero rows are dropped."""
    count = len(frame)
    titles = _titles(frame, range(count), options) if count else []
    shares = [None] * count
    name = options.get("Values")
    if not isinstance(name, str) or name not in frame:
        return titles, shares
    numbers = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
    usable = np.isfinite(numbers) & (numbers >= 0)
    total = float(numbers[usable].sum()) if usable.any() else 0.0
    for index in range(count):
        if not usable[index]:
            continue
        shares[index] = 0.0 if total <= 0 else float(numbers[index] / total)
    return titles, shares


def slice_color_defaults(frame, options):
    """Palette color of each wedge, keyed by 1-based sheet row, after reverse order."""
    name = options.get("Values")
    if not isinstance(name, str) or name not in frame:
        return {}
    values = pd.to_numeric(frame[name], errors="coerce")
    positions = np.flatnonzero(values.notna().to_numpy())
    if not len(positions):
        return {}
    amounts = values.iloc[positions].to_numpy(dtype=float)
    if not np.isfinite(amounts).all() or (amounts < 0).any():
        return {}
    rows = positions + 1
    if options.get("Reverse order", False):
        amounts, rows = amounts[::-1], rows[::-1]
    colors = {}
    for slot, (amount, row) in enumerate(zip(amounts, rows, strict=True)):
        if amount > 0:
            colors[int(row)] = COLORS[slot % len(COLORS)]
    return colors


def _positive_total(values, field):
    try:
        total = fsum(values)
    except OverflowError:
        total = np.inf
    if not np.isfinite(total) or total <= 0:
        raise FieldError(field, "The selected values need a positive total within the numeric range.")
    return total


def _dot_counts(fractions, size):
    ideal = fractions * size
    counts = np.floor(ideal).astype(int)
    missing = size - int(counts.sum())
    order = np.argsort(counts - ideal, kind="stable")
    counts[order[:missing]] += 1
    return counts


def parts_graph(frame, options):
    name = options.get("Values")
    values = _column(frame, name, "Values")
    positions = np.flatnonzero(values.notna().to_numpy())
    if not 1 <= len(positions) <= MAX_PARTS:
        raise FieldError("Values", f"Use 1 to {MAX_PARTS} nonblank values.")
    amounts = values.iloc[positions].to_numpy(dtype=float)
    if (amounts < 0).any():
        raise FieldError("Values", "A composition graph requires nonnegative values.")
    total = _positive_total(amounts, "Values")
    titles = _titles(frame, positions, options)
    # Sheet row numbers travel with the slices so a style stays on its row after reverse.
    row_numbers = positions + 1
    if options.get("Reverse order", False):
        titles, amounts, row_numbers = titles[::-1], amounts[::-1], row_numbers[::-1]
    fractions = amounts / total
    active = amounts > 0
    if active.sum() > MAX_GRAPH_PARTS:
        raise FieldError("Values", f"Use at most {MAX_GRAPH_PARTS} nonzero values in a composition graph.")
    style = _choice(options, "Graph style", STYLES)
    legend = _choice(options, "Legend", LEGENDS)
    colors = [COLORS[index % len(COLORS)] for index in np.flatnonzero(active)]
    plot_values = fractions[active]
    figure, axes = _plot(PARTS_GRAPH)
    axes.set_axis_off()
    table = pd.DataFrame({"Category": titles, "Value": amounts, "Fraction": fractions, "Percent": 100 * fractions})
    apply_styles = options.get(APPLY_SEGMENT_STYLES, False)
    if not isinstance(apply_styles, bool):
        raise FieldError(APPLY_SEGMENT_STYLES, "Apply segment styles must be yes or no.")
    shown = None
    if style in {PIE, DONUT}:
        styles = segment_styles(frame, options.get(SEGMENT_STYLES))
        angle, clockwise, slice_labels, border, border_width = _pie_settings(options)
        width = 1.
        if style == DONUT:
            try:
                hole = float(options.get("Donut hole (%)", 52.))
            except (ValueError, TypeError, OverflowError):
                hole = np.nan
            if not 10 <= hole <= 90:
                raise FieldError("Donut hole (%)", "Choose a donut hole between 10 and 90 percent.")
            width -= hole / 100
        active_rows = row_numbers[active]
        explode, shown = [], []
        for slot, row in enumerate(active_rows.tolist()):
            item = styles.get(int(row), {})
            if "color" in item:
                colors[slot] = item["color"]
            explode.append(item.get("explode", 0.0))
            # A hidden slice keeps its angle and its share of the denominator.
            shown.append(item.get("visible", True))
        handles, _ = axes.pie(plot_values, explode=explode, colors=colors, startangle=angle,
                              counterclock=not clockwise, labeldistance=None,
                              wedgeprops={"width": width, "edgecolor": border, "linewidth": border_width})
        for wedge, show in zip(handles, shown, strict=True):
            if not show:
                wedge.set_visible(False)
        if slice_labels == "Percent":
            radius = 1 - width / 2
            for wedge, fraction, show in zip(handles, plot_values, shown, strict=True):
                if not show:
                    continue
                mid = radians((wedge.theta1 + wedge.theta2) / 2)
                axes.text(wedge.center[0] + radius * cos(mid), wedge.center[1] + radius * sin(mid),
                          f"{fraction:.1%}", ha="center", va="center", fontsize=9, color="#1d3348",
                          parse_math=False)
    else:
        if apply_styles:
            styles = segment_styles(frame, options.get(SEGMENT_STYLES), allow_explode=False)
            active_rows = row_numbers[active]
            shown = []
            for slot, row in enumerate(active_rows.tolist()):
                item = styles.get(int(row), {})
                if "color" in item:
                    colors[slot] = item["color"]
                shown.append(item.get("visible", True))
        if style == DOTS:
            count = options.get("Number of dots", 100)
            if type(count) is not int or not 10 <= count <= 1000:
                raise FieldError("Number of dots", "Choose an integer between 10 and 1,000.")
            allocation = _dot_counts(plot_values, count)
            table["Dots"] = 0
            table.loc[active, "Dots"] = allocation
            columns = ceil(sqrt(count))
            handles, start = [], 0
            for color, dots in zip(colors, allocation, strict=True):
                positions = np.arange(start, start + dots)
                handles.append(axes.scatter(positions % columns, -(positions // columns), s=28, color=color))
                start += dots
            if shown is not None:
                for collection, show in zip(handles, shown, strict=True):
                    if not show:
                        collection.set_visible(False)
            axes.set_aspect("equal")
        else:
            starts = np.r_[0., np.cumsum(plot_values)[:-1]]
            vertical = style == VERTICAL
            method = axes.bar if vertical else axes.barh
            offset = "bottom" if vertical else "left"
            dimension = "width" if vertical else "height"
            handles = [method(0, value, color=color, edgecolor="white", linewidth=1.2,
                              **{offset: start, dimension: .45})[0]
                       for start, value, color in zip(starts, plot_values, colors, strict=True)]
            if shown is not None:
                for patch, show in zip(handles, shown, strict=True):
                    if not show:
                        patch.set_visible(False)
            if vertical:
                axes.set(xlim=(-.65, .65), ylim=(0, 1))
            else:
                axes.set(xlim=(0, 1), ylim=(-.65, .65))
    if legend != "None":
        labels, legend_handles = [], []
        visible = [True] * len(handles) if shown is None else shown
        for handle, title, amount, fraction, show in zip(
                handles, np.asarray(titles)[active], amounts[active], plot_values, visible, strict=True):
            if not show:
                continue
            if legend == "Category and percent":
                title = f"{title} · {fraction:.1%}"
            elif legend == "Category and value":
                title = f"{title} · {amount:,.6g}"
            legend_handles.append(handle)
            labels.append(title)
        if legend_handles:
            for label in axes.legend(legend_handles, labels, loc="center left", bbox_to_anchor=(1, .5),
                                     frameon=False).get_texts():
                label.set_parse_math(False)
    if options.get("Show total", True):
        position = (0., 0.) if style == DONUT else (.5, -.03)
        transform = axes.transData if style == DONUT else axes.transAxes
        axes.text(*position, f"Total\n{total:,.6g}", transform=transform, ha="center",
                  va="center" if style == DONUT else "top", fontsize=11, color="#27465e")
    return Result({"Composition": table, "Total": _report({"Total": total})}, figure)


def goodness_of_fit(frame, options):
    observed = options.get("Observed counts")
    if not isinstance(observed, str) or observed not in frame:
        raise FieldError("Observed counts", "Choose a column of observed counts.")
    raw = frame[observed].replace("", np.nan)
    positions = np.flatnonzero(raw.notna().to_numpy())
    if not 2 <= len(positions) <= MAX_PARTS:
        raise FieldError("Observed counts", f"Use 2 to {MAX_PARTS} categories.")
    numbers = [_whole_count(value, observed, field="Observed counts") for value in raw.iloc[positions]]
    total = sum(numbers)
    if not 0 < total <= MAX_TOTAL:
        raise FieldError("Observed counts", "The total count must be positive and within the exact integer range.")
    mode = _choice(options, "Expected distribution", EXPECTED)
    if mode == EXPECTED[0]:
        weights = np.ones(len(numbers))
    else:
        name = options.get("Expected values")
        if name == observed:
            raise FieldError("Expected values", "Choose a separate column of expected values.")
        weights = _column(frame, name, "Expected values").iloc[positions].to_numpy(dtype=float)
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise FieldError("Expected values", "Enter a positive expected value for every observed category.")
    denominator = _positive_total(weights, "Expected values")
    if mode == EXPECTED[2] and not isclose(denominator, total, rel_tol=1e-10):
        raise FieldError("Expected values", "Expected counts must sum to the observed total.")
    fitted = options.get("Estimated parameters", 0)
    if type(fitted) is not int or not 0 <= fitted < len(numbers) - 1:
        raise FieldError("Estimated parameters", "Choose a nonnegative parameter count that leaves positive degrees of freedom.")
    expected = (weights / denominator) * total
    if (expected <= 0).any():
        raise FieldError("Expected values", "The expected values are too uneven to resolve at this precision.")
    with np.errstate(over="ignore", invalid="ignore"):
        residuals = (np.asarray(numbers) - expected) / np.sqrt(expected)
        contributions = residuals**2
    if not np.isfinite(contributions).all():
        raise FieldError("Expected values", "The test statistic exceeds the numeric range.")
    statistic = _positive_total(contributions, "Expected values") if contributions.any() else 0.
    df = len(numbers) - 1 - fitted
    details = pd.DataFrame({"Category": _titles(frame, positions, options), "Observed": numbers,
                            "Expected": expected, "Pearson residual": residuals, "Contribution": contributions})
    return Result({"Test": _report({"Pearson χ²": statistic, "df": df, "p": chi2.sf(statistic, df),
                                    "Total count": total, "Minimum expected count": expected.min()}),
                   "Categories": details})
