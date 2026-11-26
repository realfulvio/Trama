"""Find the axis represented by the visible label, ticks or spine under a click."""

from itertools import chain

from analisi.axis_breaks import segment_axes


def right_y_axes(primary):
    """Return an independent Y axis sharing X, outside the segment and secondary-axis views."""
    shared = primary.get_shared_x_axes()
    return next((axes for axes in primary.figure.axes if axes is not primary
                 and shared.joined(primary, axes) and axes.yaxis.get_label_position() == "right"), None)


def _label_hit(label, renderer, x, y, padding):
    return (label.get_visible() and bool(label.get_text())
            and label.get_window_extent(renderer).padded(padding).contains(x, y))


def _axis_hit(axes, dimension, sides, renderer, x, y, padding):
    axis = axes.xaxis if dimension == "x" else axes.yaxis
    if not axes.get_visible() or not axes.axison or not axis.get_visible():
        return False
    if any(_label_hit(label, renderer, x, y, padding) for label in (axis.label, axis.offsetText)):
        return True
    low, high = sorted(axis.get_view_interval())
    for tick in chain(axis.get_major_ticks(), axis.get_minor_ticks()):
        if tick.get_visible() and low <= tick.get_loc() <= high:
            if any(_label_hit(label, renderer, x, y, padding) for label in (tick.label1, tick.label2)):
                return True
    return any(spine.get_visible() and spine.get_window_extent(renderer).padded(padding).contains(x, y)
               for side in sides if (spine := axes.spines.get(side)) is not None)


def axis_at(event, *, include_right):
    canvas = event.canvas
    if not canvas.figure.axes or not hasattr(canvas, "renderer"):
        return None
    primary = canvas.figure.axes[0]
    if primary.name != "rectilinear":
        return None
    hit = (canvas.renderer, event.x, event.y, 3 * canvas.device_pixel_ratio)
    if include_right and (right := right_y_axes(primary)) is not None:
        if _axis_hit(right, "y", ("right",), *hit):
            return "right"
    for axes in segment_axes(canvas.figure) or (primary,):
        if _axis_hit(axes, "x", ("bottom", "top"), *hit):
            return "x"
        if _axis_hit(axes, "y", ("left", "right"), *hit):
            return "y"
    return None
