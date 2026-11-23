"""Linked secondary axes: the same coordinate shown in a second unit, on the top X and/or right Y axis.

The section is presentation only. Data, worksheets, calculations and recipes never see it. A graph style
saves at most one ``linked_axes`` record::

    {"x": {"multiplier": 1.8, "offset": 32.0, "label": "Temperature (°F)"},
     "y": {"multiplier": 60.0, "offset": 0.0, "label": "Seconds"}}

An axis that is absent is off. The secondary value is ``multiplier × primary + offset``; the multiplier is finite
and strictly positive, so the map is increasing and invertible and no series, interpolation or implicit unit is
involved. On a logarithmic primary axis only a change of unit is allowed (offset 0).

``apply_style`` draws every present axis with a real Matplotlib secondary axis, a child Axes of the graph's own
Axes that carries the stable ids ``trama-linked-x`` and ``trama-linked-y``. Matplotlib recomputes the limits of a
secondary axis from its parent at every draw, so pan, zoom, inversion, dialog edits and recalculation all follow
the primary axis without a callback, and a second ``apply_style`` removes the old child before adding the new
one: formatting twenty times never leaves more than one secondary axis per side.
"""
from copy import deepcopy
from math import isfinite
from sys import float_info

import numpy as np
from matplotlib.ticker import Locator

from .axis_breaks import segment_axes
from .field_error import FieldError

LINKED_AXES = "linked_axes"
DIMENSIONS = ("x", "y")
GID_PREFIX = "trama-linked-"
MAX_LABEL = 160
# Attributes the machinery keeps. The renderers of the supported graphs mark their Axes with SUPPORT_ATTR.
SUPPORT_ATTR = "_tramastat_linked_axes_support"
REASON_ATTR = "_tramastat_linked_axes_reasons"

_RECORD_KEYS = {"multiplier", "offset", "label"}
# Converted values stay far from the float limits so that matplotlib can still map them to pixels.
_LIMIT = 1e300

M_TYPE = "Linked axes need an X and/or a Y record with a multiplier, an offset and a label."
M_MULTIPLIER = "Linked {axis} axis: enter a finite multiplier greater than 0."
M_OFFSET = "Linked {axis} axis: enter a finite offset."
M_LABEL = "Linked {axis} axis: the label takes up to 160 characters, without line breaks or control characters."
M_LOG_OFFSET = "Linked {axis} axis: on a logarithmic scale only a change of unit is allowed, so the offset must be 0."
M_RANGE = "Linked {axis} axis: with this multiplier and offset the limits of the axis overflow or collapse."

P_SUPPORT = ("Linked axes are available for XY series, XY error bars, regression and survival curves, "
             "and for the value axis of column and grouped graphs.")
P_NATIVE = "Linked axes need a native graph, not an imported picture."
P_CATEGORICAL = "Linked axes need a numeric {axis} axis."
P_SCALE = "Linked axes need a linear or logarithmic {axis} axis."
P_BREAKS = "Linked axes cannot be combined with axis breaks. Remove the axis breaks first."
P_RIGHT = ("A linked right Y axis cannot be combined with an independent right Y axis. "
           "Move every series to the left axis first.")
P_PANELS = "Linked axes need a graph with a single plot panel."
P_LOG_OFFSET = "On a logarithmic {axis} axis a linked axis only changes the unit: the offset must be 0."
P_RANGE = "The linked {axis} axis cannot show this range: the converted limits overflow or collapse."
P_FAILED = "The linked axes could not be drawn ({kind}: {message})."


class LinkedAxesError(FieldError):
    """A problem with one field of the record; ``dimension`` is ``"x"``/``"y"`` or None for the whole record."""

    def __init__(self, dimension, name, message):
        super().__init__(name if dimension is None else f"{dimension}.{name}", message)
        self.dimension, self.name = dimension, name


def _number(value):
    return type(value) in (int, float) and abs(value) <= float_info.max and isfinite(value)


# ----- the record ----------------------------------------------------------------------------------------


def normalise_linked_axes(record):
    """Return the canonical copy of ``record``, or ``{}`` when the linked axes are off. Raises ``LinkedAxesError``."""
    if record is None or record == {}:
        return {}
    if not isinstance(record, dict) or record.keys() - set(DIMENSIONS):
        raise LinkedAxesError(None, "x", M_TYPE)
    canonical = {}
    for dimension in DIMENSIONS:
        if dimension not in record:
            continue
        item, shown = record[dimension], dimension.upper()
        if not isinstance(item, dict) or item.keys() != _RECORD_KEYS:
            raise LinkedAxesError(dimension, "multiplier", M_TYPE)
        multiplier, offset, label = item["multiplier"], item["offset"], item["label"]
        if not _number(multiplier) or not multiplier > 0:
            raise LinkedAxesError(dimension, "multiplier", M_MULTIPLIER.format(axis=shown))
        if not _number(offset):
            raise LinkedAxesError(dimension, "offset", M_OFFSET.format(axis=shown))
        if not isinstance(label, str) or len(label) > MAX_LABEL or not label.isprintable():
            raise LinkedAxesError(dimension, "label", M_LABEL.format(axis=shown))
        canonical[dimension] = {"multiplier": float(multiplier), "offset": float(offset), "label": label}
    return canonical


def log_offset_problem(dimension, item):
    """The message when ``item`` (canonical) shifts a logarithmic axis, or None."""
    if item["offset"] != 0:
        return M_LOG_OFFSET.format(axis=dimension.upper())
    return None


def convert(item, values):
    """Primary values to secondary values (``multiplier × value + offset``), as an array."""
    with np.errstate(all="ignore"):
        return item["multiplier"] * np.asarray(values, dtype=float) + item["offset"]


def reverse(item, values):
    """Secondary values back to primary values."""
    with np.errstate(all="ignore"):
        return (np.asarray(values, dtype=float) - item["offset"]) / item["multiplier"]


def range_problem(dimension, item, limits):
    """The message when the converted ``limits`` overflow, round trip badly or collapse, else None."""
    try:
        low, high = sorted(float(value) for value in limits)
    except (TypeError, ValueError):
        return None
    if not (isfinite(low) and isfinite(high)):
        return None
    converted = convert(item, [low, high])
    back = reverse(item, converted)
    if (not np.isfinite(converted).all() or not np.isfinite(back).all()
            or np.abs(converted).max() > _LIMIT):
        return M_RANGE.format(axis=dimension.upper())
    low_c, high_c = (float(value) for value in converted)
    if Locator().nonsingular(low_c, high_c) != (low_c, high_c):
        return M_RANGE.format(axis=dimension.upper())
    return None


class AffineMap:
    """``values -> multiplier × values + offset`` (or its inverse) that stays finite, for matplotlib.

    A callable class, not a lambda, so that a figure carrying the secondary axes can still be pickled.
    """

    def __init__(self, item, *, inverse=False):
        self.multiplier, self.offset, self.inverse = item["multiplier"], item["offset"], inverse

    def __call__(self, values):
        item = {"multiplier": self.multiplier, "offset": self.offset}
        result = (reverse if self.inverse else convert)(item, values)
        # A zoom far beyond the validated range must not make the secondary limits infinite.
        return np.clip(np.nan_to_num(result, nan=0.0, posinf=_LIMIT, neginf=-_LIMIT), -_LIMIT, _LIMIT)


# ----- what a graph can show -----------------------------------------------------------------------------


def mark_linked_axes(axes, *dimensions):
    """Called by the renderers of the graphs that accept linked axes, with the dimensions that can be linked."""
    setattr(axes, SUPPORT_ATTR, tuple(dimension for dimension in DIMENSIONS if dimension in dimensions))


def supported_dimensions(axes):
    """The axes of ``axes`` that a renderer marked as linkable (before any check of the current state)."""
    return tuple(getattr(axes, SUPPORT_ATTR, ()))


def linked_axes_reasons(figure):
    """``{dimension: message}`` for the saved linked axes that ``figure`` does not draw right now."""
    return dict(getattr(figure, REASON_ATTR, None) or {})


def _axis_of(axes, dimension):
    return axes.xaxis if dimension == "x" else axes.yaxis


def _plot_panels(figure, primary):
    """The Axes of ``figure`` other than ``primary`` that draw a plot, split into twins and independent panels."""
    twins, panels = [], []
    broken = set(segment_axes(figure))
    for other in figure.axes:
        if other is primary or other in broken or not getattr(other, "axison", True):
            continue
        (twins if primary.get_shared_x_axes().joined(primary, other) else panels).append(other)
    return twins, panels


def linked_axes_conflicts(axes, *, scales=None, breaks=None, right=None):
    """``{dimension: message}`` for the axes that cannot take a linked axis now. Never changes the graph.

    ``scales`` maps ``"x"``/``"y"`` to a scale chosen but not yet applied; ``breaks`` says whether axis breaks are
    on (default: whether the figure draws them); ``right`` says whether an independent right Y axis is wanted
    (default: whether the figure has one).
    """
    figure = axes.figure
    conflicts = {}
    allowed = supported_dimensions(axes)
    if not allowed:
        return {dimension: P_SUPPORT for dimension in DIMENSIONS}
    if getattr(axes, "_tramastat_non_native", False) or not getattr(axes, "axison", True):
        return {dimension: P_NATIVE for dimension in DIMENSIONS}
    twins, panels = _plot_panels(figure, axes)
    if breaks is None:
        breaks = bool(segment_axes(figure))
    if right is None:
        right = bool(twins)
    for dimension in DIMENSIONS:
        shown = dimension.upper()
        axis = _axis_of(axes, dimension)
        scale = (scales or {}).get(dimension) or axis.get_scale()
        if dimension not in allowed or dimension in getattr(axes, "_tramastat_categorical_axes", ()):
            conflicts[dimension] = P_CATEGORICAL.format(axis=shown) if allowed else P_SUPPORT
        elif axis.get_units() is not None:
            conflicts[dimension] = P_CATEGORICAL.format(axis=shown)
        elif scale not in ("linear", "log"):
            conflicts[dimension] = P_SCALE.format(axis=shown)
        elif breaks:
            conflicts[dimension] = P_BREAKS
        elif panels:
            conflicts[dimension] = P_PANELS
        elif dimension == "y" and right:
            conflicts[dimension] = P_RIGHT
    return conflicts


# ----- drawing -------------------------------------------------------------------------------------------


def clear_linked_axes(axes):
    """Remove the linked axes of ``axes``. Safe to call when there are none."""
    for child in list(axes.child_axes):
        if str(child.get_gid() or "").startswith(GID_PREFIX):
            child.remove()


def linked_children(axes):
    """The linked secondary axes currently attached to ``axes``, by dimension."""
    return {child.get_gid()[len(GID_PREFIX):]: child for child in axes.child_axes
            if str(child.get_gid() or "").startswith(GID_PREFIX)}


def _follow_primary(child, primary, dimension, item, style):
    """Give the secondary axis the font, sizes and colour of the primary axis."""
    axis, parent = _axis_of(child, dimension), _axis_of(primary, dimension)
    child.grid(False)
    params = parent.get_tick_params(which="major")
    options = {key: params[key] for key in ("labelsize", "labelcolor", "labelfontfamily") if key in params}
    if options:
        child.tick_params(axis=dimension, which="both", **options)
    label, source = axis.label, parent.label
    label.set_text(item["label"])
    label.set_fontproperties(source.get_fontproperties().copy())
    label.set_color(source.get_color())
    if "font_family" in style:
        label.set_fontfamily(style["font_family"])
    if "label_size" in style:
        label.set_fontsize(style["label_size"])


def _draw_axis(primary, dimension, item, style):
    functions = (AffineMap(item), AffineMap(item, inverse=True))
    if dimension == "x":
        child = primary.secondary_xaxis("top", functions=functions)
    else:
        child = primary.secondary_yaxis("right", functions=functions)
    child.set_gid(GID_PREFIX + dimension)
    _follow_primary(child, primary, dimension, item, style)
    return child


def apply_linked_axes(figure, record, style=None):
    """Draw ``record`` (canonical, ``normalise_linked_axes``) on the graph's own Axes.

    Returns the secondary axes drawn, by dimension. A dimension the graph cannot show right now is left out and
    ``linked_axes_reasons`` says why: the record stays in the style and returns when the graph allows it.
    """
    style = style or {}
    primary = figure.axes[0]
    clear_linked_axes(primary)
    reasons = {}
    setattr(figure, REASON_ATTR, reasons)
    drawn = {}
    if not record:
        return drawn
    conflicts = linked_axes_conflicts(primary)
    for dimension, item in record.items():
        axis = _axis_of(primary, dimension)
        if dimension in conflicts:
            reasons[dimension] = conflicts[dimension]
            continue
        if axis.get_scale() == "log" and log_offset_problem(dimension, item):
            reasons[dimension] = P_LOG_OFFSET.format(axis=dimension.upper())
            continue
        if range_problem(dimension, item, getattr(primary, f"get_{dimension}lim")()):
            reasons[dimension] = P_RANGE.format(axis=dimension.upper())
            continue
        try:
            drawn[dimension] = _draw_axis(primary, dimension, item, style)
        except Exception as error:  # noqa: BLE001 - the graph must stay usable; the reason says what failed.
            clear_linked_axes(primary)
            drawn.clear()
            reasons[dimension] = P_FAILED.format(kind=type(error).__name__, message=error)
            break
    figure.stale = True
    return drawn


def style_without_linked_y(style):
    """A copy of ``style`` without the linked right Y axis (the Y quantity changed, so its unit no longer holds)."""
    record = (style or {}).get(LINKED_AXES)
    if not record or "y" not in record:
        return style
    updated = deepcopy(style)
    updated[LINKED_AXES].pop("y")
    if not updated[LINKED_AXES]:
        del updated[LINKED_AXES]
    return updated


def linked_axes_status(figure, style=None):
    """One translated line when saved linked axes are not drawn on ``figure``, else None."""
    reasons = linked_axes_reasons(figure)
    if not reasons or not (style or {}).get(LINKED_AXES):
        return None
    from .i18n import tr, translate_message

    texts = {dimension: translate_message(reason, "linked_axes.error.") for dimension, reason in reasons.items()}
    if len(set(texts.values())) == 1:
        detail = next(iter(texts.values()))
    else:
        detail = " ".join(f"{dimension.upper()}: {text}" for dimension, text in texts.items())
    return tr("linked_axes.status.ignored", reason=detail)
