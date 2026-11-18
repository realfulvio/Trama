"""Axis breaks for native XY graphs: two or three numeric segments on the X or the left Y axis.

The section is presentation only. Calculation, data, worksheets and recipes never see it. A
recipe saves at most one ``axis_breaks`` record in the graph style::

    {"axis": "x", "gap": 0.04,
     "segments": [{"low": 0, "high": 4, "share": 35, "major_step": 2}, ...]}

``apply_style`` draws every segment on a real Matplotlib Axes. The first segment is the graph's own
Axes, so the other presentation settings keep working on it; the others are subplots of one GridSpec
that share the other axis. The extra panels repeat the data artists of the first one (never the data)
and a constrained-layout engine re-slices the band reserved for the panels after every layout pass,
so the shares and gaps follow the window, the export size and the layout composer.
"""
from copy import copy, deepcopy
from math import floor, fsum, isfinite
from sys import float_info

import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.gridspec import GridSpec
from matplotlib.layout_engine import ConstrainedLayoutEngine
from matplotlib.lines import Line2D
from matplotlib.path import Path
from matplotlib.ticker import AutoMinorLocator, FixedLocator, MaxNLocator, NullLocator, ScalarFormatter
from matplotlib.transforms import Bbox

from .field_error import FieldError

AXIS_BREAKS = "axis_breaks"
AXES = ("x", "y")
GAP_RANGE = (0.01, 0.10)
SEGMENT_COUNTS = (2, 3)
MAX_TICKS = 200
SHARE_TOLERANCE = 1e-8
EDGE_TOLERANCE = 1e-9
MARKER_PREFIX = "axis-break-marker-"
GID_PREFIX = "trama-axis-break:"

# Attributes the machinery keeps. The renderers of the supported graphs set SUPPORT_ATTR on their Axes.
SUPPORT_ATTR = "_tramastat_axis_breaks_support"
STATE_ATTR = "_tramastat_axis_breaks"
REASON_ATTR = "_tramastat_axis_breaks_reason"
SCOPE_ATTR = "_tramastat_axis_break_scope"

_RECORD_KEYS = {"axis", "gap", "segments"}
_SEGMENT_KEYS = {"low", "high", "share", "major_step"}
_SEGMENT_REQUIRED = {"low", "high", "share"}
_SLASH = Path([(-1.0, -1.0), (1.0, 1.0)], [Path.MOVETO, Path.LINETO])
_NO_LINE = ("None", "none", None, "", " ")
_OWN_GIDS = ("tramastat-shape-", "trama-axis-guide:", "trama-axis-band:")

M_TYPE = "Axis breaks need an axis, a gap and two or three segments."
M_AXIS = "Choose the X axis or the left Y axis for the breaks."
M_GAP = "The gap must be a number from 0.01 to 0.10 of the band reserved for the panels."
M_COUNT = "Use two or three segments."
M_SEGMENT = "Segment {row} needs a low limit, a high limit, a share and a major interval."
M_FINITE = "Segment {row}: enter finite numbers for the low and high limits."
M_ORDER = "Segment {row}: the low limit must be smaller than the high limit."
M_SEPARATE = "Segment {row}: the low limit must be larger than the high limit of segment {previous}."
M_SHARE = "Segment {row}: enter a share greater than 0."
M_TOTAL = "The shares must add up to 100. They add up to {total}."
M_STEP = "Segment {row}: enter a major interval greater than 0, or leave it blank for automatic ticks."
M_TICKS = "Segment {row}: the major interval would place more than 200 ticks."

P_SUPPORT = "Axis breaks are available for XY series and XY error bars graphs only."
P_NATIVE = "Axis breaks need a native graph, not an imported picture."
P_RIGHT = "Axis breaks cannot be combined with a right Y axis. Move every series to the left axis first."
P_LAYOUT = "Axis breaks need the standard graph layout."
P_ARTISTS = "This graph has drawing elements that axis breaks cannot repeat on every panel."
P_LINEAR = "Axis breaks need a linear {axis} axis."
P_OTHER = "Axis breaks need a linear or logarithmic {axis} axis."
P_NUMERIC = "Axis breaks need a numeric {axis} axis."
P_INVERTED = "Axis breaks need an {axis} axis that increases."
P_PLOT_FRACTIONS = ("Drawings and annotations placed in plot fractions cannot be combined with axis breaks. "
                    "Place them in data coordinates or remove them.")
P_FAILED = "The axis breaks could not be drawn ({kind}: {message})."


class AxisBreakError(FieldError):
    """A problem with one field of the record; ``row`` is the 0-based segment (None for the whole record)."""

    def __init__(self, row, name, message):
        super().__init__(name if row is None else f"segments.{row}.{name}", message)
        self.row, self.name = row, name


def _number(value):
    return type(value) in (int, float) and isfinite(value) and abs(value) <= float_info.max


# ----- the record ----------------------------------------------------------------------------------------


def segment_lengths(record):
    """Fractions of the band reserved for the panels, in data order: ``(1-(N-1)*gap)*share/100``."""
    use = 1 - (len(record["segments"]) - 1) * record["gap"]
    return [use * segment["share"] / 100 for segment in record["segments"]]


def explicit_ticks(low, high, step):
    """Ticks every ``step`` from ``low``; ``high`` is included when it falls on the grid."""
    count = floor((high - low) / step + EDGE_TOLERANCE)
    ticks = [low + index * step for index in range(count + 1)]
    if abs(ticks[-1] - high) <= EDGE_TOLERANCE * max(abs(step), abs(high), 1e-300):
        ticks[-1] = high
    return ticks


def segment_ticks(segment):
    """The major ticks drawn for ``segment``: its explicit grid, or round numbers inside it."""
    low, high, step = segment["low"], segment["high"], segment.get("major_step")
    if step is not None:
        return explicit_ticks(low, high, step)
    bins = max(2, min(6, round(segment["share"] / 100 * 8)))
    values = MaxNLocator(nbins=bins, steps=[1, 2, 2.5, 5, 10]).tick_values(low, high)
    margin = EDGE_TOLERANCE * (high - low)
    ticks = [float(value) for value in values if low - margin <= value <= high + margin]
    return ticks if len(ticks) >= 2 else [float(low), float(high)]


def normalise_axis_breaks(record):
    """Return the canonical copy of ``record``, or ``{}`` when the breaks are off. Raises ``AxisBreakError``."""
    if record is None or record == {}:
        return {}
    if not isinstance(record, dict) or record.keys() != _RECORD_KEYS:
        raise AxisBreakError(None, "segments", M_TYPE)
    axis, gap, segments = record["axis"], record["gap"], record["segments"]
    if type(axis) is not str or axis not in AXES:
        raise AxisBreakError(None, "axis", M_AXIS)
    if not _number(gap) or not GAP_RANGE[0] - 1e-12 <= gap <= GAP_RANGE[1] + 1e-12:
        raise AxisBreakError(None, "gap", M_GAP)
    if not isinstance(segments, list) or len(segments) not in SEGMENT_COUNTS:
        raise AxisBreakError(None, "segments", M_COUNT)
    canonical = []
    for row, segment in enumerate(segments):
        shown = row + 1
        if (not isinstance(segment, dict) or segment.keys() - _SEGMENT_KEYS
                or _SEGMENT_REQUIRED - segment.keys()):
            raise AxisBreakError(row, "low", M_SEGMENT.format(row=shown))
        low, high, share = segment["low"], segment["high"], segment["share"]
        step = segment.get("major_step")
        if not (_number(low) and _number(high)):
            raise AxisBreakError(row, "low" if not _number(low) else "high", M_FINITE.format(row=shown))
        if not low < high or not _number(high - low):
            raise AxisBreakError(row, "high", M_ORDER.format(row=shown))
        if canonical and not low > canonical[-1]["high"]:
            raise AxisBreakError(row, "low", M_SEPARATE.format(row=shown, previous=row))
        if not _number(share) or not share > 0:
            raise AxisBreakError(row, "share", M_SHARE.format(row=shown))
        if step is not None:
            if not _number(step) or not step > 0:
                raise AxisBreakError(row, "major_step", M_STEP.format(row=shown))
            if not (high - low) / step <= MAX_TICKS - 1 + EDGE_TOLERANCE:
                raise AxisBreakError(row, "major_step", M_TICKS.format(row=shown))
        canonical.append({"low": low, "high": high, "share": share, "major_step": step})
    total = fsum(segment["share"] for segment in canonical)
    if not abs(total - 100) <= SHARE_TOLERANCE:
        raise AxisBreakError(len(canonical) - 1, "share", M_TOTAL.format(total=f"{total:g}"))
    return {"axis": axis, "gap": gap, "segments": canonical}


# ----- what a graph can show -----------------------------------------------------------------------------


def mark_supported(axes):
    """Called by the renderers of the graphs that accept axis breaks."""
    setattr(axes, SUPPORT_ATTR, True)


def segment_axes(figure):
    """The segment Axes of ``figure`` in increasing data order, or an empty list for a normal figure."""
    state = getattr(figure, STATE_ATTR, None)
    return list(state["panels"]) if state else []


def axis_breaks_reason(figure):
    """Why saved axis breaks are not drawn on ``figure`` right now, or None."""
    return getattr(figure, REASON_ATTR, None)


def panel_scope(axes):
    """``(axis, low, high, index, count)`` for a segment panel, or None for a normal Axes."""
    return getattr(axes, SCOPE_ATTR, None)


def _foreign_artists(axes):
    """Artists that the panels cannot repeat. Only lines and line collections are cloned."""
    return (list(axes.patches) + list(axes.images) + list(axes.tables)
            + [artist for artist in axes.collections if not isinstance(artist, LineCollection)]
            + list(axes.texts))


def axis_breaks_problem(axes, record):
    """Why ``record`` cannot be drawn on the graph that owns ``axes`` right now, or None. Never changes it."""
    if not record:
        return None
    figure = axes.figure
    if not getattr(axes, SUPPORT_ATTR, False):
        return P_SUPPORT
    if getattr(axes, "_tramastat_non_native", False) or not getattr(axes, "axison", True):
        return P_NATIVE
    state = getattr(figure, STATE_ATTR, None)
    own = set(state["panels"]) if state else {axes}
    if any(other not in own for other in figure.axes):
        return P_RIGHT
    if not isinstance(figure.get_layout_engine(), ConstrainedLayoutEngine) or axes.get_subplotspec() is None:
        return P_LAYOUT
    dimension = record["axis"]
    other = "y" if dimension == "x" else "x"
    if dimension in getattr(axes, "_tramastat_categorical_axes", ()) or _axis_of(axes, dimension).get_units() is not None:
        return P_NUMERIC.format(axis=dimension.upper())
    if _axis_of(axes, dimension).get_scale() != "linear":
        return P_LINEAR.format(axis=dimension.upper())
    if _axis_of(axes, other).get_scale() not in ("linear", "log"):
        return P_OTHER.format(axis=other.upper())
    if state is None:
        low, high = getattr(axes, f"get_{dimension}lim")()
        if low > high:
            return P_INVERTED.format(axis=dimension.upper())
        if _foreign_artists(axes):
            return P_ARTISTS
    return None


def plot_fraction_problem(style):
    """Why drawings or annotations of ``style`` cannot share a graph with axis breaks, or None."""
    from .graph_annotations import ANNOTATIONS
    from .graph_shapes import SHAPES

    if not style.get(AXIS_BREAKS):
        return None
    for record in (*style.get(SHAPES, ()), *style.get(ANNOTATIONS, ())):
        if record.get("units") == "axes":
            return P_PLOT_FRACTIONS
    return None


# ----- layout ----------------------------------------------------------------------------------------------


class _BreakEngine(ConstrainedLayoutEngine):
    """Constrained layout, then the panels are re-sliced to the exact shares and gaps of the record."""

    def execute(self, fig):
        result = super().execute(fig)
        _after_layout(fig)
        return result


def _place(panel, rect):
    panel.set_position(rect)
    panel.set_in_layout(True)  # set_position switches it off


def _slice_panels(state):
    record, panels = state["record"], state["panels"]
    gap, lengths = record["gap"], segment_lengths(record)
    boxes = [panel.get_position() for panel in panels]
    if state["axis"] == "x":
        start = min(box.x0 for box in boxes)
        span = max(box.x1 for box in boxes) - start
        for panel, box, length in zip(panels, boxes, lengths, strict=True):
            _place(panel, [start, box.y0, length * span, box.height])
            start += (length + gap) * span
    else:
        start = min(box.y0 for box in boxes)
        span = max(box.y1 for box in boxes) - start
        for panel, box, length in zip(panels, boxes, lengths, strict=True):
            _place(panel, [box.x0, start, box.width, length * span])
            start += (length + gap) * span


def _band(state):
    boxes = [panel.get_position() for panel in state["panels"]]
    return Bbox.from_extents(min(box.x0 for box in boxes), min(box.y0 for box in boxes),
                             max(box.x1 for box in boxes), max(box.y1 for box in boxes))


def _center_labels(state, band):
    """The axis name that spans the panels sits on the band, not on the one panel that owns it."""
    primary = state["primary"]
    box = primary.get_position()
    if state["axis"] == "x":
        fraction = ((band.x0 + band.x1) / 2 - box.x0) / box.width
        primary.xaxis.label.set_x(fraction)
        primary.title.set_x(fraction)
    else:
        primary.yaxis.label.set_y(((band.y0 + band.y1) / 2 - box.y0) / box.height)


def _legend_corner(figure, state, band, legend):
    """The corner of the band with the fewest data points under the legend, like loc="best"."""
    extent = legend.get_window_extent(figure._get_renderer())
    (left, bottom), (right, top) = figure.transFigure.transform([[band.x0, band.y0], [band.x1, band.y1]])
    texts = legend.get_texts()
    pad = 0.5 * texts[0].get_fontsize() * figure.dpi / 72 if texts else 4.0
    reach = 4 * figure.dpi / 72  # a symbol reaches this far from its point
    cloud = []
    for panel in state["panels"]:
        (xlow, xhigh), (ylow, yhigh) = sorted(panel.get_xlim()), sorted(panel.get_ylim())
        for x, y in state["points"]:
            keep = (x >= xlow) & (x <= xhigh) & (y >= ylow) & (y <= yhigh)
            if keep.any():
                cloud.append(panel.transData.transform(np.column_stack([x[keep], y[keep]])))
    cloud = np.vstack(cloud) if cloud else np.empty((0, 2))
    best, fewest = "upper right", None
    for name, x0, y0 in (("upper right", right - pad - extent.width, top - pad - extent.height),
                         ("upper left", left + pad, top - pad - extent.height),
                         ("lower left", left + pad, bottom + pad),
                         ("lower right", right - pad - extent.width, bottom + pad)):
        inside = ((cloud[:, 0] >= x0 - reach) & (cloud[:, 0] <= x0 + extent.width + reach)
                  & (cloud[:, 1] >= y0 - reach) & (cloud[:, 1] <= y0 + extent.height + reach)).sum()
        if fewest is None or inside < fewest:
            best, fewest = name, inside
    return best


def _place_legend(figure, state, band):
    legend = state["legend"]
    if legend is None or legend is not state["primary"].get_legend():
        return
    location = state["legend_loc"]
    if location in (0, "best"):
        try:
            location = _legend_corner(figure, state, band, legend)
        except (ValueError, IndexError, AttributeError):
            location = "upper right"
    legend.set_loc(location)
    legend.set_bbox_to_anchor(band, transform=figure.transFigure)


def _after_layout(figure):
    state = getattr(figure, STATE_ATTR, None)
    if not state:
        return
    _slice_panels(state)
    band = _band(state)
    _center_labels(state, band)
    _place_legend(figure, state, band)


# ----- the legend --------------------------------------------------------------------------------------------


def refresh_legend(figure):
    """Take over the legend the graph shows now. ``apply_style`` calls it after the legend options ran."""
    state = getattr(figure, STATE_ATTR, None)
    if not state:
        return
    legend = state["primary"].get_legend()
    state["legend"] = None
    if legend is None or legend._bbox_to_anchor is not None:
        return  # no legend, or one the user placed by hand
    if all(entry[0] is not legend for entry in state["legends"]):
        state["legends"].append((legend, legend._loc, legend.get_in_layout()))
    legend.set_in_layout(False)  # it lives in the band, not in the margins of the first panel
    state["legend"], state["legend_loc"] = legend, state["legends"][-1][1]
    for entry in state["legends"]:
        if entry[0] is legend:
            state["legend_loc"] = entry[1]


def _restore_legends(state):
    for legend, location, in_layout in state["legends"]:
        legend.set_loc(location)
        legend.set_bbox_to_anchor(None)
        legend.set_in_layout(in_layout)


# ----- drawing the panels ----------------------------------------------------------------------------------


class _EdgeMarkers(Line2D):
    """The symbols of the points that sit exactly on a limit of the broken axis, drawn whole.

    A limit is inclusive, but the clip of the panel would cut such a symbol in half. The lines and the
    symbols inside stay clipped; only the symbols on the closed limits are drawn again, unclipped.
    """

    def __init__(self, x, y, dimension, **kwargs):
        super().__init__([], [], **kwargs)
        self._all = (np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        self._dimension = dimension

    def draw(self, renderer):
        x, y = self._all
        (xlow, xhigh), (ylow, yhigh) = sorted(self.axes.get_xlim()), sorted(self.axes.get_ylim())
        low, high, values = (xlow, xhigh, x) if self._dimension == "x" else (ylow, yhigh, y)
        px, py = (xhigh - xlow) * EDGE_TOLERANCE, (yhigh - ylow) * EDGE_TOLERANCE
        tolerance = (high - low) * EDGE_TOLERANCE
        with np.errstate(invalid="ignore"):
            inside = (x >= xlow - px) & (x <= xhigh + px) & (y >= ylow - py) & (y <= yhigh + py)
            on_edge = (np.abs(values - low) <= tolerance) | (np.abs(values - high) <= tolerance)
        keep = inside & on_edge
        if not keep.any():
            return
        self.set_data(x[keep], y[keep])
        super().draw(renderer)


def _clone_artist(clone, source, panel, gid):
    clone.update_from(source)
    clone.set_transform(panel.transData)
    clone.set_zorder(source.get_zorder())
    clone.set_label("_nolegend_")
    clone.set_gid(GID_PREFIX + gid)


def _copy_line(source, panel, gid):
    clone = Line2D(np.asarray(source.get_xdata(orig=False), dtype=float), np.asarray(source.get_ydata(orig=False), dtype=float))
    _clone_artist(clone, source, panel, gid)
    clone.set_clip_path(panel.patch)
    clone.set_clip_on(True)
    panel.add_artist(clone)
    return clone


def _copy_edge_markers(source, panel, dimension, gid):
    clone = _EdgeMarkers(np.asarray(source.get_xdata(orig=False), dtype=float), np.asarray(source.get_ydata(orig=False), dtype=float),
                         dimension)
    _clone_artist(clone, source, panel, gid)
    clone.set_linestyle("None")
    clone.set_clip_on(False)
    clone.set_in_layout(False)  # it has no data until it draws: an empty line would pull the margins to the corner
    panel.add_artist(clone)
    return clone


def _copy_collection(source, panel, gid):
    clone = LineCollection(source.get_segments())
    _clone_artist(clone, source, panel, gid)
    clone.set_clip_path(panel.patch)
    clone.set_clip_on(True)
    panel.add_collection(clone, autolim=False)
    return clone


def _is_data_line(line):
    gid = str(line.get_gid() or "")
    return not gid.startswith((GID_PREFIX, *_OWN_GIDS))


def _repeat_data(primary, panel, dimension, position):
    """Repeat the data artists of ``primary`` on panel number ``position``; on ``primary`` only the edge symbols."""
    made = []
    for index, source in enumerate(list(primary.lines)):
        if not _is_data_line(source):
            continue
        tag = f"{position}:{index}:{source.get_gid() or ''}"
        has_marker = source.get_marker() not in _NO_LINE
        if position:
            made.append(_copy_line(source, panel, f"line:{tag}"))
        if has_marker:
            made.append(_copy_edge_markers(source, panel, dimension, f"edge:{tag}"))
    if position:
        for index, source in enumerate(list(primary.collections)):
            made.append(_copy_collection(source, panel, f"bars:{position}:{index}"))
    return made


def _data_points(primary):
    points = []
    for source in primary.lines:
        if not _is_data_line(source):
            continue
        x, y = np.asarray(source.get_xdata(orig=False), dtype=float), np.asarray(source.get_ydata(orig=False), dtype=float)
        finite = np.isfinite(x) & np.isfinite(y)
        x, y = x[finite], y[finite]
        if source.get_linestyle() not in _NO_LINE and len(x) > 1:  # a line also occupies the space between its points
            x, y = np.concatenate([x, (x[1:] + x[:-1]) / 2]), np.concatenate([y, (y[1:] + y[:-1]) / 2])
        points.append((x, y))
    return points


def _axis_of(panel, dimension):
    return getattr(panel, dimension + "axis")


def _snapshot(primary, dimension):
    axis = _axis_of(primary, dimension)
    return {
        "limits": getattr(primary, f"get_{dimension}lim")(),
        "auto": getattr(primary, f"get_autoscale{dimension}_on")(),
        "major_locator": axis.get_major_locator(), "minor_locator": axis.get_minor_locator(),
        "major_formatter": axis.get_major_formatter(),
        "spines": {name: spine.get_visible() for name, spine in primary.spines.items()},
        "zorder": primary.get_zorder(), "in_layout": primary.get_in_layout(),
        "title_visible": primary.title.get_visible(),
        "title_x": primary.title.get_position()[0],
        "xlabel_x": primary.xaxis.label.get_position()[0],
        "ylabel_y": primary.yaxis.label.get_position()[1],
    }


def _formatter(source):
    if isinstance(source, ScalarFormatter):
        return ScalarFormatter(useOffset=False)
    return copy(source)


def _set_segment(panel, dimension, segment, formatter, minor):
    axis = _axis_of(panel, dimension)
    getattr(panel, f"set_{dimension}lim")(segment["low"], segment["high"])
    axis.set_major_locator(FixedLocator(segment_ticks(segment)))
    axis.set_major_formatter(_formatter(formatter))
    axis.set_minor_locator(AutoMinorLocator(minor.ndivs) if isinstance(minor, AutoMinorLocator) else NullLocator())


def _copy_decoration(primary, panel):
    panel.set_facecolor(primary.get_facecolor())
    panel.set_axisbelow(primary.get_axisbelow())
    for name, spine in primary.spines.items():
        target = panel.spines[name]
        target.set_visible(spine.get_visible())
        target.set_linewidth(spine.get_linewidth())
        target.set_edgecolor(spine.get_edgecolor())
    for dimension in AXES:
        for which in ("major", "minor"):
            _axis_of(panel, dimension).set_tick_params(which=which, **_axis_of(primary, dimension).get_tick_params(which))
    for dimension, grid in (("x", primary.xaxis), ("y", primary.yaxis)):
        for which in ("major", "minor"):
            ticks = grid.majorTicks if which == "major" else grid.minorTicks
            if ticks and ticks[0].gridline.get_visible():
                getattr(panel, dimension + "axis").grid(True, which=which)


def _trim_panel(panel, dimension, index, count):
    """Hide the decoration that faces a gap or repeats the labels of the other axis."""
    if dimension == "x":
        if index > 0:
            panel.spines["left"].set_visible(False)
            panel.tick_params(axis="y", which="both", left=False, right=False, labelleft=False, labelright=False)
        if index < count - 1:
            panel.spines["right"].set_visible(False)
    else:
        if index > 0:
            panel.spines["bottom"].set_visible(False)
            panel.tick_params(axis="x", which="both", bottom=False, top=False, labelbottom=False, labeltop=False)
        if index < count - 1:
            panel.spines["top"].set_visible(False)


def _break_marks(primary, panels, dimension):
    """The slanted bars on both sides of every gap, as ordinary artists with stable ids."""
    marks = []
    spine = primary.spines["left" if dimension == "y" else "bottom"]
    boxed = primary.spines["top" if dimension == "x" else "right"].get_visible()
    color, width = spine.get_edgecolor(), spine.get_linewidth()
    for gap, (before, after) in enumerate(zip(panels, panels[1:]), start=1):
        for side, panel, edge in (("before", before, 1), ("after", after, 0)):
            places = ([("bottom", (edge, 0)), ("top", (edge, 1))] if dimension == "x"
                      else [("left", (0, edge)), ("right", (1, edge))])
            for name, (x, y) in places:
                if name in ("top", "right") and not boxed:
                    continue
                mark = Line2D([x], [y], transform=panel.transAxes, marker=_SLASH, markersize=8,
                              markeredgewidth=max(0.8, width), markeredgecolor=color, markerfacecolor="none",
                              linestyle="None", clip_on=False, zorder=10, label="_nolegend_")
                mark.set_gid(f"{MARKER_PREFIX}{dimension}{gap}-{side}-{name}")
                mark.set_in_layout(False)
                panel.add_artist(mark)
                marks.append(mark)
    return marks


def _refresh_toolbar(figure):
    toolbar = getattr(getattr(figure, "canvas", None), "toolbar", None)
    if toolbar is not None and hasattr(toolbar, "update"):
        toolbar.update()


def apply_axis_breaks(figure, record):
    """Draw ``record`` on ``figure``. Returns the panels in data order, or ``[primary]`` when not drawn.

    ``record`` must be canonical (``normalise_axis_breaks``) and the figure must not be segmented.
    A graph that cannot show the breaks stays untouched and ``axis_breaks_reason`` says why.
    """
    primary = figure.axes[0]
    setattr(figure, REASON_ATTR, None)
    if not record:
        return [primary]
    reason = axis_breaks_problem(primary, record)
    if reason:
        setattr(figure, REASON_ATTR, reason)
        return [primary]
    try:
        return _build(figure, primary, record)
    except Exception as error:
        clear_axis_breaks(figure)
        setattr(figure, REASON_ATTR, P_FAILED.format(kind=type(error).__name__, message=error))
        return [primary]


def _build(figure, primary, record):
    dimension = record["axis"]
    other = "y" if dimension == "x" else "x"
    segments = record["segments"]
    count = len(segments)
    lengths = segment_lengths(record)
    saved = _snapshot(primary, dimension)
    engine = figure.get_layout_engine()
    state = {"axis": dimension, "record": deepcopy(record), "primary": primary, "panels": [primary],
             "clones": [], "artists": [], "saved": saved, "spec": primary.get_subplotspec(), "engine": engine,
             "legend": None, "legend_loc": None, "legends": [], "points": []}
    setattr(figure, STATE_ATTR, state)
    if dimension == "x":
        grid = GridSpec(1, count, figure=figure, width_ratios=lengths)
        cells = [grid[0, index] for index in range(count)]
    else:
        grid = GridSpec(count, 1, figure=figure, height_ratios=lengths[::-1])
        cells = [grid[count - 1 - index, 0] for index in range(count)]
    primary.set_subplotspec(cells[0])
    for index in range(1, count):
        panel = figure.add_subplot(cells[index], **{"share" + other: primary})
        _copy_decoration(primary, panel)
        state["clones"].append(panel)
        state["panels"].append(panel)
    minor, formatter = saved["minor_locator"], saved["major_formatter"]
    # Everything the panels repeat is copied before the first panel is trimmed.
    for index, (panel, segment) in enumerate(zip(state["panels"], segments, strict=True)):
        state["artists"].extend(_repeat_data(primary, panel, dimension, index))
        _set_segment(panel, dimension, segment, formatter, minor)
        _trim_panel(panel, dimension, index, count)
        setattr(panel, SCOPE_ATTR, (dimension, segment["low"], segment["high"], index, count))
    state["artists"].extend(_break_marks(primary, state["panels"], dimension))
    state["points"] = _data_points(primary)
    primary.set_zorder(max(saved["zorder"], 0) + count)
    if dimension == "y":
        top, title = state["panels"][-1], primary.title
        top.set_title(title.get_text(), fontproperties=title.get_fontproperties().copy(), color=title.get_color())
        top.title.set_parse_math(title.get_parse_math())
        title.set_visible(False)
    refresh_legend(figure)
    figure.set_layout_engine(_BreakEngine(**engine.get()))
    figure.stale = True
    _refresh_toolbar(figure)
    return state["panels"]


def clear_axis_breaks(figure):
    """Undo ``apply_axis_breaks``: remove the extra panels and give the first Axes its own state back."""
    state = getattr(figure, STATE_ATTR, None)
    if state is None:
        return
    primary, saved, dimension = state["primary"], state["saved"], state["axis"]
    for artist in state["artists"]:
        if artist.axes is primary:
            try:
                artist.remove()
            except (ValueError, NotImplementedError):
                pass
    for panel in state["clones"]:
        figure.delaxes(panel)
        setattr(panel, SCOPE_ATTR, None)
    setattr(primary, SCOPE_ATTR, None)
    delattr(figure, STATE_ATTR)
    if state["spec"] is not None:
        primary.set_subplotspec(state["spec"])
    primary.set_in_layout(saved["in_layout"])
    primary.set_zorder(saved["zorder"])
    axis = _axis_of(primary, dimension)
    axis.set_major_locator(saved["major_locator"])
    axis.set_minor_locator(saved["minor_locator"])
    axis.set_major_formatter(saved["major_formatter"])
    getattr(primary, f"set_{dimension}lim")(saved["limits"], auto=saved["auto"])
    for name, visible in saved["spines"].items():
        primary.spines[name].set_visible(visible)
    primary.title.set_visible(saved["title_visible"])
    primary.title.set_x(saved["title_x"])
    primary.xaxis.label.set_x(saved["xlabel_x"])
    primary.yaxis.label.set_y(saved["ylabel_y"])
    _restore_legends(state)
    figure.set_layout_engine(state["engine"])
    figure.stale = True
    _refresh_toolbar(figure)


# ----- overlays ---------------------------------------------------------------------------------------------


def panel_guides(guides, record, index, count):
    """The guides one panel draws.

    A guide on the broken axis is given to every panel and the clip keeps it where it has content. A guide
    on the other axis crosses every panel, but its tick or its label belongs to one edge of the band only.
    """
    kept = []
    for guide in guides:
        if guide["axis"] == record["axis"]:
            kept.append(guide)
            continue
        side = guide.get("side", "primary")
        if (index == 0) if side == "primary" else (index == count - 1):
            kept.append(guide)
        elif guide.get("line"):
            kept.append({**guide, "tick": False, "label": ""})
    return kept


def tag_new_artists(panel, before, index):
    """Give the overlay artists a panel added their own ids, so the SVG ids stay unique."""
    for artist in panel.get_children():
        if artist in before:
            continue
        gid = artist.get_gid()
        if gid:
            artist.set_gid(f"{GID_PREFIX}{index}:{gid}")
