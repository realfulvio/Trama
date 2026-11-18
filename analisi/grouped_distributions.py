"""Grouped box and violin plots: one numeric response by a category, optionally split by a second factor.

Every category × series combination is a cell with its own box or violin. The statistics, whiskers, density
estimate and spread of the points are the ones of ``distribution_graphs`` (the Box / violin plot method), so a
cell is drawn exactly as the same observations would be drawn as a single group; only the width is divided by the
number of series so that the cells of one category share its unit slot.

Cell position: 1 + j + 0.8 · (i − (s − 1) / 2) / s, with j the zero-based category, i the zero-based series
and s the number of series (s = 1 and a centered box when the plot is not split).
"""
from dataclasses import dataclass
from urllib.parse import quote, unquote

from matplotlib.colors import to_rgba
from matplotlib.patches import Patch
from matplotlib.transforms import IdentityTransform
import numpy as np
import pandas as pd

from . import distribution_graphs as base
from .category_graphs import COLORS, MAX_POINTS, PLACEMENTS, _spread
from .graph_legend import LEGEND_OPTIONS_KEY, apply_legend_options, typed_group_token
from .presentation import LEGEND_LOCATIONS, GraphGroup, register_groups
from .processing import FieldError, _column
from .reporting import Result, _plot, _report


GROUPED_DISTRIBUTIONS = "Grouped distribution plot"
OPTIONS = {
    "Response": None, "Category": None, "Split by": "Optional", "Style": base.STYLES, "Whiskers": base.WHISKERS,
    "Show mean": False, "Overlay observations": False, "Point placement": PLACEMENTS, "Bandwidth multiplier": 1.0,
    "Median line": True, "Quartile lines": True,
}
CELLS_SHEET, OBSERVATIONS_SHEET, DENSITY_SHEET = "Distribution cells", "Distribution observations", "Distribution density"
MAX_CELLS = 40
SLOT_SPAN = .8
POSITION_RULE = ("Position = 1 + j + 0.8 · (i − (s − 1) / 2) / s, with j the category and i the series (both counted "
                 "from 0) and s the number of series; without Split by, s = 1 and each box or violin is centered.")
MAX_KEY_LENGTH = 1024
_ALPHA = {base.BOX: .24, base.VIOLIN: .3}


def visibility(style, whiskers, overlay):
    """Fields that apply to the chosen style (the rules of the Box / violin plot method, one response)."""
    rules = base.visibility(base.SINGLE, style, whiskers, overlay)
    return {name: rules[name] for name in rules if name not in {"Response", "Group", "Variables"}}


# ----- identities ---------------------------------------------------------------------------------------------
def cell_identity(category, series=None):
    """Reversible key part of a cell, built from type-preserving tokens; independent of sheet order."""
    text = "cell:" + quote(category, safe="")
    return text if series is None else f"{text}:{quote(series, safe='')}"


def parse_identity(identity):
    """Inverse of :func:`cell_identity`: ``(category token, series token or None)``."""
    parts = identity.split(":")
    if parts[0] != "cell" or len(parts) not in (2, 3):
        raise ValueError("Not a grouped distribution cell.")
    return tuple(unquote(part) for part in parts[1:]) + ((None,) if len(parts) == 2 else ())


def series_key(token):
    """Stable legend entry key of a series."""
    return f"group:{token}"


@dataclass
class _Level:
    token: str
    value: object
    label: str


def _text(value):
    return str(value.item() if isinstance(value, np.generic) else value)


def _levels(column, rows):
    """Levels in order of first appearance among ``rows``; 1, 1.0, "1" and True stay different levels."""
    values = column.to_numpy(dtype=object)[rows]
    index, found = {}, []
    codes = np.empty(len(rows), dtype=np.intp)
    for position, value in enumerate(values):
        token = typed_group_token(value)
        code = index.get(token)
        if code is None:
            code = index[token] = len(found)
            found.append(_Level(token, value, _text(value)))
        codes[position] = code
    return found, codes, values


@dataclass
class _Cell:
    category: _Level
    series: _Level | None
    position: float
    color: str
    values: np.ndarray
    rows: np.ndarray
    group: base._Group | None = None
    key: str | None = None
    name: str = ""


@dataclass
class _SeriesPlan:
    token: str
    label: str
    cells: list  # (group key or None, default color), category order, non-empty cells only


def _roles(frame, options):
    if not frame.columns.is_unique:
        raise FieldError("Response", "Worksheet column names must be unique.")
    names = {}
    for field in ("Response", "Category", "Split by"):
        name = options.get(field) or None
        if name is None:
            if field == "Split by":
                names[field] = None
                continue
            raise FieldError(field, f"Choose a column for {field}.")
        if not isinstance(name, str) or name not in frame:
            raise FieldError(field, f"Choose an existing column for {field}.")
        names[field] = name
    if names["Category"] == names["Response"]:
        raise FieldError("Category", "Choose a category column different from the response.")
    if names["Split by"] is not None and names["Split by"] in (names["Response"], names["Category"]):
        raise FieldError("Split by", "Choose a Split by column different from Response and Category.")
    return names["Response"], names["Category"], names["Split by"]


def _slot_position(j, i, series_count):
    return 1 + j + SLOT_SPAN * (i - (series_count - 1) / 2) / series_count


def _legend_entries(plan, group_styles):
    """One entry per series that still has a visible cell; its symbol is that series' first visible cell."""
    entries = []
    for series in plan:
        for key, color in series.cells:
            options = group_styles.get(key, {}) if key is not None else {}
            if options.get("visible", True):
                entries.append((series.token, series.label, options.get("color", color)))
                break
    return tuple(entries)


def _build_legend(axes, entries, alpha, title, **placement):
    handles = [Patch(facecolor=to_rgba(color, alpha), edgecolor=color, linewidth=1.3) for _, _, color in entries]
    legend = axes.legend(handles, [label for _, label, _ in entries], title=title, **placement)
    legend._tramastat_legend_keys = [series_key(token) for token, _, _ in entries]
    legend._tramastat_state = (entries, None)
    for artist in [legend.get_title(), *legend.get_texts()]:
        artist.set_parse_math(False)
    return legend


def _refresh_legend(axes, plan, alpha):
    """Keep the legend in step with the style: Inspector changes to cells and the legend position.

    ``_apply_legend`` only rebuilds a legend from labelled artists, and these cells carry none, so the symbols
    and the position chosen in Format Graph are applied here, after the style.
    """
    legend = axes.get_legend()
    if legend is None:
        return
    style = getattr(axes, "_tramastat_style", {})
    entries = _legend_entries(plan, style.get("groups", {}))
    place = style.get("legend")
    state = (entries, place if place in LEGEND_LOCATIONS and place != "hidden" else None)
    if getattr(legend, "_tramastat_state", None) == state:
        return
    title = legend.get_title().get_text()
    texts = legend.get_texts()
    size, family = (texts[0].get_fontsize(), texts[0].get_fontfamily()) if texts else (None, None)
    if state[1] is not None:
        placement = {"loc": state[1]}
    else:
        placement = {"loc": legend._loc}
        if legend._bbox_to_anchor is not None:
            placement.update(bbox_to_anchor=legend.get_bbox_to_anchor(), bbox_transform=IdentityTransform())
    axes.legend_ = None
    if not entries:
        return
    legend = _build_legend(axes, entries, alpha, title, **placement)
    legend._tramastat_state = state
    if size is not None:
        for artist in [legend.get_title(), *legend.get_texts()]:
            artist.set_fontsize(size)
            artist.set_fontfamily(family)
    if style.get(LEGEND_OPTIONS_KEY):
        apply_legend_options(axes.figure, style[LEGEND_OPTIONS_KEY])


def grouped_distributions(frame, options):
    style = base._choice(options, "Style", base.STYLES)
    whiskers = base._choice(options, "Whiskers", base.WHISKERS)
    show_mean = base._flag(options, "Show mean", False)
    all_points = style == base.BOX and whiskers == base.ALL_POINTS
    overlay = all_points or base._flag(options, "Overlay observations", False)
    placement = base._choice(options, "Point placement", PLACEMENTS)
    multiplier = base._multiplier(options) if style == base.VIOLIN else 1.
    median_line = base._flag(options, "Median line", True)
    quartile_lines = base._flag(options, "Quartile lines", True)
    response, category, split = _roles(frame, options)

    numbers = _column(frame, response, "Response").to_numpy(dtype=float)
    complete = np.isfinite(numbers) & ~frame[category].isna().to_numpy()
    if split is not None:
        complete &= ~frame[split].isna().to_numpy()
    rows = np.flatnonzero(complete)
    if not len(rows):
        raise FieldError("Response", "No row has a numeric Response together with every selected category.")
    if len(rows) > MAX_POINTS:
        raise FieldError("Response", "Select fewer observations to draw this graph.")
    if style == base.VIOLIN and len(rows) * base.GRID_POINTS > base.MAX_KDE_EVALUATIONS:
        raise FieldError("Response", "Select fewer observations for the density estimate.")

    categories, category_codes, category_values = _levels(frame[category], rows)
    if split is None:
        series_levels, series_codes, series_values = [], np.zeros(len(rows), dtype=np.intp), None
    else:
        series_levels, series_codes, series_values = _levels(frame[split], rows)
    series_count = max(len(series_levels), 1)
    if len(categories) * series_count > MAX_CELLS:
        field = "Split by" if split is not None and len(categories) <= MAX_CELLS else "Category"
        raise FieldError(field, f"Plot up to {MAX_CELLS} cells at once "
                                f"({len(categories)} categories × {series_count} series).")

    # ----- cells, in category then series order; empty combinations keep their slot --------------------------
    scale = 1 / series_count
    cells, by_cell = [], np.argsort(category_codes * series_count + series_codes, kind="stable")
    cell_code = (category_codes * series_count + series_codes)[by_cell]
    for j, level in enumerate(categories):
        for i in range(series_count):
            series = series_levels[i] if split is not None else None
            code = j * series_count + i
            start, stop = np.searchsorted(cell_code, [code, code + 1])
            members = np.sort(by_cell[start:stop])
            identity = cell_identity(level.token, series.token if series else None)
            cell = _Cell(level, series, _slot_position(j, i, series_count),
                         COLORS[(i if split is not None else j) % len(COLORS)], numbers[rows[members]],
                         rows[members] + 1, name=level.label if series is None else f"{level.label} · {series.label}")
            cell.key = f"{style.lower()}:{identity}"
            if len(cell.key) > MAX_KEY_LENGTH:
                cell.key = None
            cells.append(cell)
    labels = [cell.name for cell in cells if len(cell.values)]
    for cell in cells:
        if len(cell.values) and labels.count(cell.name) > 1:
            # Same visible label, different type (the text 1 and the number 1): name the types in the Inspector.
            cell.name = f"{cell.category.label} [{cell.category.token.split(':', 1)[0]}]" + (
                f" · {cell.series.label} [{cell.series.token.split(':', 1)[0]}]" if cell.series else "")
        if len(cell.values):
            cell.group = base._Group(cell.name, cell.values, cell.rows, cell.color, cell.position,
                                     identity=cell.key or "")
            cell.group.stats = base._statistics(cell.group, whiskers)
    drawn = [cell.group for cell in cells if cell.group is not None]

    # ----- figure --------------------------------------------------------------------------------------------
    figure, axes = _plot(f"Grouped {style.lower()} plot", category, response)
    for artist in (axes.title, axes.xaxis.label, axes.yaxis.label):
        artist.set_parse_math(False)
    density_rows, bandwidths = [], {}
    if style == base.BOX:
        base._draw_box(axes, drawn, width=base.BOX_WIDTH * scale)
    else:
        for cell in cells:
            if cell.group is not None:
                labels_ = {"Category": cell.category.value, "Series": cell.series.value if cell.series else "",
                           "Position": cell.position}
                base._draw_violin(axes, cell.group, multiplier, median_line, quartile_lines, density_rows, bandwidths,
                                  half_width=base.HALF_WIDTH * scale, labels=labels_)
    rng = np.random.default_rng(0)
    displays = {}
    for cell in cells:
        group = cell.group
        if group is None:
            continue
        stats = group.stats
        outside = stats["outside"] if style == base.BOX else np.zeros(len(group.values), dtype=bool)
        shown = np.ones(len(group.values), dtype=bool) if overlay else outside
        displays[id(cell)] = np.where(outside, "Outside whiskers", np.where(shown, "Overlay", "Not drawn"))
        inner = shown & ~outside
        if inner.any():
            x = group.x + _spread(group.values[inner], placement, base.HALF_WIDTH * 2 * scale, rng)
            group.artists.append((axes.scatter(x, group.values[inner], s=22, color=group.color, edgecolors="white",
                                               linewidths=.6, zorder=3.5), "point"))
        if show_mean:
            group.artists.append((axes.scatter([group.x], [stats["mean"]], marker="D", s=34, color="white",
                                               edgecolors=group.color, linewidths=1.4, zorder=5), "mean"))
    long_labels = max(len(level.label) for level in categories) > 12
    axes.set_xticks(range(1, len(categories) + 1), [level.label for level in categories],
                    rotation=20 if len(categories) > 5 or long_labels else 0)
    axes._tramastat_numeric_axes = ("y",)
    axes._tramastat_categorical_axes = ("x",)
    for label in axes.get_xticklabels():
        label.set_parse_math(False)
    axes.set_xlim(.4, len(categories) + .6)
    register_groups(axes, [GraphGroup(cell.key, cell.name, style.lower(), cell.position, cell.group.artists)
                           for cell in cells if cell.group is not None and cell.key is not None])
    if split is not None:
        plan = [_SeriesPlan(level.token, level.label,
                            [(cell.key, cell.color) for cell in cells if cell.series is level and len(cell.values)])
                for level in series_levels]
        _build_legend(axes, _legend_entries(plan, {}), _ALPHA[style], split, loc="upper left",
                      bbox_to_anchor=(1.02, 1), borderaxespad=0)
        axes._tramastat_after_style = lambda target: _refresh_legend(target, plan, _ALPHA[style])

    # ----- sheets --------------------------------------------------------------------------------------------
    def stat(cell, name):
        return cell.group.stats[name] if cell.group is not None else np.nan

    summary = {"Category": pd.Series([cell.category.value for cell in cells], dtype=object),
               "Series": pd.Series([cell.series.value if cell.series else "" for cell in cells], dtype=object),
               "N": [len(cell.values) for cell in cells], "Position": [cell.position for cell in cells],
               "Mean": [stat(cell, "mean") for cell in cells], "Median": [stat(cell, "median") for cell in cells],
               "Minimum": [stat(cell, "min") for cell in cells], "Q1": [stat(cell, "q1") for cell in cells],
               "Q3": [stat(cell, "q3") for cell in cells], "Maximum": [stat(cell, "max") for cell in cells]}
    if style == base.BOX:
        summary.update({"Lower whisker": [stat(cell, "low") for cell in cells],
                        "Upper whisker": [stat(cell, "high") for cell in cells],
                        "Outside whiskers": [int(cell.group.stats["outside"].sum()) if cell.group else 0
                                             for cell in cells]})
    else:
        summary["Bandwidth"] = [bandwidths.get(cell.position, np.nan) for cell in cells]
    summary["Note"] = [cell.group.note if cell.group is not None else "No observations." for cell in cells]

    slot = {(level.token, series.token if series else None): cell.position
            for cell in cells for level, series in [(cell.category, cell.series)]}
    observation_display = np.empty(len(rows), dtype=object)
    for cell in cells:
        if cell.group is not None:
            observation_display[np.searchsorted(rows + 1, cell.rows)] = displays[id(cell)]
    observations = pd.DataFrame({
        "Source row": rows + 1,
        "Category": pd.Series(category_values, dtype=object),
        "Series": pd.Series(series_values if series_values is not None else [""] * len(rows), dtype=object),
        "Value": numbers[rows],
        "Position": [slot[categories[c].token, series_levels[s].token if split else None]
                     for c, s in zip(category_codes, series_codes, strict=True)],
        "Display": observation_display})

    empty = sum(not len(cell.values) for cell in cells)
    omitted = int(len(frame) - len(rows))
    settings = {"Response": response, "Category": category, "Split by": split or "None", "Style": style,
                "Rows used": len(rows),
                "Rows omitted (missing or excluded value in a selected column)": omitted,
                "Categories": len(categories), "Series": len(series_levels) if split else "None",
                "Level order": "Categories and series follow their first complete observation; text is not sorted "
                               "or translated. A row with a missing value does not add a level.",
                "Cell limit": f"Up to {MAX_CELLS} category × series cells.",
                "Position rule": POSITION_RULE,
                "Empty cells": f"{empty} (the slot stays free in the graph; N = 0 in {CELLS_SHEET})",
                "Colors": "One color per series, the same in every category." if split else
                          "One color per category.",
                "Percentiles": base.QUARTILE_NOTE,
                "Displayed with fewer than 4 observations": "Median and range.",
                **base.rule_settings(style, whiskers, multiplier)}
    tables = {CELLS_SHEET: pd.DataFrame(summary), OBSERVATIONS_SHEET: observations}
    if density_rows:
        tables[DENSITY_SHEET] = pd.concat(density_rows, ignore_index=True)
    tables["Settings"] = _report(settings)
    return Result(tables, figure)
