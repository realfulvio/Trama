"""Bubble plot: one symbol per row, with X, Y and marker area taken from three numeric columns.

Marker area is proportional to Size: area = Maximum area × size / largest drawn size, so a size four
times larger has twice the diameter. The scale is shared by every group and is recomputed from the rows
that are drawn, after missing and excluded cells are removed.
"""
from math import isfinite, sqrt

from matplotlib.legend import Legend
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from .category_graphs import COLORS, MAX_POINTS
from .processing import FieldError, _column
from .reporting import Result, _plot, _report


BUBBLE = "Bubble plot"
MAX_AREA = "Maximum area (pt²)"
SHOW_LABELS = "Show labels"
SIZE_LEGEND = "Show size legend"
OPTIONS = {"X": None, "Y": None, "Size": None, "Group": "Optional", "Label": "Optional",
           MAX_AREA: 400.0, SHOW_LABELS: True, SIZE_LEGEND: True}
DEFAULT_AREA = 400.
AREA_LIMIT = 10_000.
# Beyond this many labeled points the annotations would hide the graph: labels stay in the sheet only.
MAX_LABELS = 60
NEUTRAL = "No group"
NEUTRAL_COLOR = "#7d8894"
ALPHA = .62
SHEET = "Bubble values"
ZERO_POLICY = ("A size of zero is an invisible point: the row is omitted from the graph, "
               "from the sheet and from the scale maximum.")


def _flag(options, name, default):
    value = options.get(name, default)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name}: choose on or off.")
    return bool(value)


def _maximum_area(options):
    value = options.get(MAX_AREA, DEFAULT_AREA)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(MAX_AREA, "The maximum area must be a number of square points.")
    value = float(value)
    if not isfinite(value) or not 0 < value <= AREA_LIMIT:
        raise FieldError(MAX_AREA, f"The maximum area must be greater than 0 and at most {AREA_LIMIT:,.0f} pt².")
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
    """Group and label cells as display text; blanks become None."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = value if isinstance(value, str) else str(value.item() if isinstance(value, np.generic) else value)
    return text if text.strip() else None


def _legend_values(sizes):
    """Up to three distinct reference sizes: the smallest, the median and the largest drawn size."""
    picked = []
    for value in (float(sizes.max()), float(np.median(sizes)), float(sizes.min())):
        label = f"{value:.4g}"
        if all(label != existing for _, existing in picked):
            picked.append((value, label))
    return picked


def bubble_plot(frame, options):
    if not frame.columns.is_unique:
        raise FieldError("X", "Worksheet column names must be unique.")
    x_name, y_name, size_name = (_role(frame, options, name) for name in ("X", "Y", "Size"))
    if len({x_name, y_name, size_name}) < 3:
        field = "Y" if y_name == x_name else "Size"
        raise FieldError(field, "Choose three different columns for X, Y and Size.")
    group_name = _role(frame, options, "Group", optional=True)
    label_name = _role(frame, options, "Label", optional=True)
    maximum_area = _maximum_area(options)
    show_labels = _flag(options, SHOW_LABELS, True)
    size_legend = _flag(options, SIZE_LEGEND, True)

    x = _column(frame, x_name, "X").to_numpy(dtype=float)
    y = _column(frame, y_name, "Y").to_numpy(dtype=float)
    size = _column(frame, size_name, "Size").to_numpy(dtype=float)
    if (size < 0).any():
        row = int(np.flatnonzero(size < 0)[0]) + 1
        raise FieldError("Size", f'Column "{size_name}" contains a negative size (row {row}). '
                                 "Sizes must be zero or positive.")
    complete = np.isfinite(x) & np.isfinite(y) & np.isfinite(size)
    zero = complete & (size == 0)
    drawn = complete & (size > 0)
    if not drawn.any():
        if zero.any():
            raise FieldError("Size", "Every complete row has a size of zero, so no bubble can be drawn. "
                                     "Choose a Size column with positive values.")
        raise FieldError("Size", "No row has numeric X, Y and Size values.")
    if drawn.sum() > MAX_POINTS:
        raise FieldError("X", "Select fewer rows to draw this graph.")

    rows = np.flatnonzero(drawn)
    largest = float(size[rows].max())
    areas = maximum_area * (size[rows] / largest)
    groups = [_text(value) for value in frame[group_name].to_numpy(dtype=object)[rows]] if group_name else None
    labels = [_text(value) for value in frame[label_name].to_numpy(dtype=object)[rows]] if label_name else None

    sheet = pd.DataFrame({"Source row": rows + 1, "X": x[rows], "Y": y[rows], "Size": size[rows],
                          "Marker area (pt²)": areas})
    if group_name:
        sheet["Group"] = frame[group_name].to_numpy(dtype=object)[rows]
    if label_name:
        sheet["Label"] = frame[label_name].to_numpy(dtype=object)[rows]

    figure, axes = _plot(BUBBLE, x_name, y_name)
    order = list(dict.fromkeys(name if name is not None else NEUTRAL for name in groups)) if groups else [None]
    palette = iter(COLORS * (len(order) // len(COLORS) + 1))
    collections = []
    for name in order:
        if name is None:
            member = np.ones(len(rows), dtype=bool)
        else:
            member = np.array([(g if g is not None else NEUTRAL) == name for g in groups])
        color = NEUTRAL_COLOR if name == NEUTRAL else next(palette)
        artist = axes.scatter(x[rows][member], y[rows][member], s=areas[member], marker="o",
                              color=color, alpha=ALPHA, edgecolors="white", linewidths=.7,
                              label=name if name is not None else "_nolegend_", zorder=2.5)
        artist.set_gid(f"bubble:{name if name is not None else ''}")
        collections.append(artist)
    axes.margins(.08)

    labeled = [(index, text) for index, text in enumerate(labels or ()) if text is not None]
    label_note = "No Label column." if not label_name else "Hidden by option." if not show_labels else ""
    if label_name and show_labels:
        if len(labeled) > MAX_LABELS:
            label_note = (f"Not drawn: {len(labeled)} labeled points exceed the limit of {MAX_LABELS}. "
                          f"Every label remains in the {SHEET} sheet.")
        else:
            for index, text in labeled:
                offset = sqrt(areas[index]) / 2 + 2
                note = axes.annotate(text, (x[rows][index], y[rows][index]), xytext=(offset, 0),
                                     textcoords="offset points", va="center", ha="left", fontsize=8,
                                     color="#34414f", zorder=3)
                note.set_parse_math(False)
            label_note = f"{len(labeled)} drawn (limit {MAX_LABELS})."

    if groups:
        legend = axes.legend(loc="upper left", bbox_to_anchor=(1.02, 1), borderaxespad=0, title=group_name)
        for handle in legend.legend_handles:
            handle.set_sizes([64.])
        for text in [legend.get_title(), *legend.get_texts()]:
            text.set_parse_math(False)
    references = _legend_values(size[rows])
    if size_legend:
        handles = [Line2D([], [], marker="o", linestyle="none", markersize=sqrt(maximum_area * value / largest),
                          markerfacecolor=(.55, .6, .65, ALPHA), markeredgecolor="white")
                   for value, _ in references]
        legend = Legend(axes, handles, [label for _, label in references], title=size_name,
                        loc="lower left", bbox_to_anchor=(1.02, 0), borderaxespad=0, labelspacing=1.4,
                        borderpad=.9, frameon=False)
        legend.get_title().set_parse_math(False)
        legend.set_gid("bubble-size-legend")
        axes.add_artist(legend)
        axes._tramastat_size_legend = legend

    omitted_zero = int(zero.sum())
    omitted_missing = int((~complete).sum())
    settings = {"X": x_name, "Y": y_name, "Size": size_name, "Group": group_name or "None",
                "Label": label_name or "None", "Rows drawn": len(rows),
                "Rows omitted (missing or excluded X, Y or Size)": omitted_missing,
                "Rows omitted (size zero)": omitted_zero,
                "Area rule": "area = Maximum area × Size / largest drawn Size (shared by every group)",
                "Largest drawn size": largest, MAX_AREA: maximum_area,
                "Size legend": (", ".join(label for _, label in references) if size_legend else "Hidden"),
                "Zero sizes": ZERO_POLICY, "Labels": label_note}
    if groups and NEUTRAL in order:
        settings["Blank groups"] = f'Drawn in gray as "{NEUTRAL}".'
    return Result({SHEET: sheet, "Settings": _report(settings)}, figure)
