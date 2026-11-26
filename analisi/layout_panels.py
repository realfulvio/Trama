"""Plan the size and position of native layout panels for both raster and vector output."""
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, replace
from math import isclose

from matplotlib.figure import Figure

from .layout_geometry import AUTO_PAPER, page_size, panel_boxes, panel_cells


# Explicit empty slot passed to the renderers. A missing figure still signals an error.
EMPTY_PANEL = object()


@contextmanager
def _panel_figure(figure, size, axes=(), bounds=None, *, measuring=False):
    """Temporarily reflow a source figure, restoring its canvas and axes geometry afterwards."""
    original_size = tuple(figure.get_size_inches())
    if not measuring and size == original_size and bounds is None:
        yield figure
        return
    original_canvas, original_engine, original_dpi = figure.canvas, figure.get_layout_engine(), figure.dpi
    subplot_params = {key: getattr(figure.subplotpars, key)
                      for key in ("left", "right", "bottom", "top", "wspace", "hspace")}
    axis_views = [(axis, axis.get_xlim(), axis.get_ylim()) for axis in figure.axes]
    original_axes = [(axis, axis.get_position(original=True).frozen(), axis.get_position().frozen(),
                      axis.get_in_layout()) for axis in figure.axes]
    try:
        if size != original_size:
            figure.set_size_inches(size, forward=False)
        if bounds is not None:
            if original_engine is not None:
                figure.set_layout_engine("none")
            for axis in axes:
                axis.set_position(bounds)
        yield figure
    finally:
        if figure.get_layout_engine() is not original_engine:
            figure.set_layout_engine(original_engine)
        figure.set_size_inches(original_size, forward=False)
        figure.dpi = original_dpi
        figure.set_canvas(original_canvas)
        figure.subplotpars.update(**subplot_params)
        for axis, original, active, in_layout in original_axes:
            axis.set_position(original, which="original")
            axis.set_position(active, which="active")
            axis.set_in_layout(in_layout)
        for axis, xlim, ylim in axis_views:
            if axis.get_xlim() != xlim:
                axis.set_xlim(xlim, emit=False, auto=None)
            if axis.get_ylim() != ylim:
                axis.set_ylim(ylim, emit=False, auto=None)


@dataclass(frozen=True)
class LayoutPanel:
    figure: Figure | None
    size: tuple
    box: tuple                  # left, top, scale in the layout page
    axes: tuple = ()
    bounds: tuple | None = None  # target axes position relative to the panel

    def render(self):
        return _panel_figure(self.figure, self.size, self.axes, self.bounds)


def _plot_bounds(panel):
    axes = tuple(axis for axis in panel.figure.axes if axis.get_visible())
    if not axes or any(not axis.axison or axis.name != "rectilinear" or axis.get_aspect() != "auto"
                       or axis.get_box_aspect() is not None or axis.get_axes_locator() is not None for axis in axes):
        return None
    with _panel_figure(panel.figure, panel.size, measuring=True) as figure:
        figure.draw_without_rendering()
        bounds = axes[0].get_position().bounds
        if not all(all(isclose(a, b, abs_tol=1e-7) for a, b in zip(bounds, axis.get_position().bounds, strict=True))
                   for axis in axes[1:]):
            return None
    return axes, bounds


def _align_panels(panels, columns, alignment, measurements):
    # Work in page inches so the axes line up even when the source figure sizes and cell scales differ.
    rows, cols, bounds = defaultdict(list), defaultdict(list), {}
    for index, (panel, measured) in enumerate(zip(panels, measurements, strict=True)):
        if measured is None:
            continue
        axes, (left, bottom, width, height) = measured
        x, y, scale = panel.box
        w, h = (length * scale for length in panel.size)
        edges = (x + left * w, y + (1 - bottom) * h, x + (left + width) * w, y + (1 - bottom - height) * h)
        bounds[index] = (edges, axes)
        row, col = divmod(index, columns)
        rows[row].append(index)
        cols[col].append(index)

    left_by_index, bottom_by_index = {}, {}
    if alignment in ("y", "both"):
        for indices in cols.values():
            if len(indices) > 1:
                left = max(bounds[index][0][0] for index in indices)
                if left < min(bounds[index][0][2] for index in indices):
                    left_by_index.update(dict.fromkeys(indices, left))
    if alignment in ("x", "both"):
        for indices in rows.values():
            if len(indices) > 1:
                bottom = min(bounds[index][0][1] for index in indices)
                if bottom > max(bounds[index][0][3] for index in indices):
                    bottom_by_index.update(dict.fromkeys(indices, bottom))

    for index in left_by_index.keys() | bottom_by_index.keys():
        panel = panels[index]
        (left, bottom, right, top), axes = bounds[index]
        target_left = left_by_index.get(index, left)
        target_bottom = bottom_by_index.get(index, bottom)
        # Freeze every participating axes after measuring it. Renderers can otherwise rerun
        # constrained layout at a different DPI and introduce new offsets.
        x, y, scale = panel.box
        w, h = (length * scale for length in panel.size)
        position = (max(0., (target_left - x) / w), min(1., 1 - (target_bottom - y) / h),
                    (right - target_left) / w, (target_bottom - top) / h)
        panels[index] = replace(panel, axes=axes, bounds=position)
    return panels


def panel_plan_steps(columns, figures, paper=AUTO_PAPER, *, panel_size="original", axis_alignment="none",
                     offsets=()):
    """Match panel sizes and axes, yielding after each measured graph for the gallery."""

    figures = tuple(figures)
    sizes = [None if figure is EMPTY_PANEL else tuple(figure.get_size_inches()) for figure in figures]
    populated = [size for size in sizes if size is not None]
    if populated and panel_size == "both":
        # Reflow the graphs onto a common canvas. Empty slots are not part of the measurement.
        common_size = tuple(max(values) for values in zip(*populated, strict=True))
        sizes = [common_size if size is not None else None for size in sizes]
    boxes = panel_boxes(columns, sizes, paper, panel_size=panel_size)
    _, _, width, height = panel_cells(columns, len(sizes), paper)
    panels = [LayoutPanel(figure if size is not None else None, size or (width, height), box)
              for figure, size, box in zip(figures, sizes, boxes, strict=True)]
    if axis_alignment != "none" and len(panels) > 1:
        measurements = []
        for panel in panels:
            measurements.append(_plot_bounds(panel) if panel.figure is not None else None)
            yield
        panels = _align_panels(panels, columns, axis_alignment, measurements)
    if offsets:
        width, height = page_size(columns, len(panels), paper)
        for index, dx, dy in offsets:
            panel = panels[index]
            x, y, scale = panel.box
            panels[index] = replace(panel, box=(x + dx * width, y + dy * height, scale))
    return panels


def plan_panels(columns, figures, paper=AUTO_PAPER, *, panel_size="original", axis_alignment="none", offsets=()):
    steps = panel_plan_steps(columns, figures, paper, panel_size=panel_size, axis_alignment=axis_alignment,
                             offsets=offsets)
    try:
        while True:
            next(steps)
    except StopIteration as finished:
        return finished.value

def panel_rectangle(panel):
    """The graph's outer rectangle in page inches, with the origin at the top left."""
    x, y, scale = panel.box
    w, h = panel.size
    return x, y, x + w * scale, y + h * scale


def enclosing_rectangle(panels, indices):
    corners = [panel_rectangle(panels[index]) for index in indices]
    return (min(r[0] for r in corners), min(r[1] for r in corners),
            max(r[2] for r in corners), max(r[3] for r in corners))


def bounded_translation(rect, shift, page):
    """Constrain movement so the selection fits without increasing any existing overflow."""
    x, y, right, bottom = rect
    dx, dy = shift
    width, height = page
    return (min(max(dx, min(0., -x)), max(0., width - right)),
            min(max(dy, min(0., -y)), max(0., height - bottom)))


def _axis_anchor(panel, axis):
    if panel.figure is None:
        return None
    measured = (panel.axes, panel.bounds) if panel.bounds is not None else _plot_bounds(panel)
    if measured is None:
        return None
    left, top, right, bottom = panel_rectangle(panel)
    _, (axis_x, axis_y, _, _) = measured
    return top + (bottom - top) * (1 - axis_y) if axis == "x" else left + (right - left) * axis_x


class PanelAlignmentError(ValueError):
    """The selected objects cannot be arranged with the requested operation."""


def layout_shifts(panels, objects, command):
    """Compute one page translation per selected panel, with axis positions measured from its graph."""
    boxes = [enclosing_rectangle(panels, obj) for obj in objects]
    direction = {
        "left": 0, "center": 0, "right": 0, "top": 1, "middle": 1, "bottom": 1,
        "align_x": 1, "align_y": 0, "distribute_x": 0, "distribute_y": 1,
    }[command]
    lows, highs = [box[direction] for box in boxes], [box[direction + 2] for box in boxes]
    if command.startswith("align_"):
        anchors = [_axis_anchor(panels[obj[0]], command[-1]) if len(obj) == 1 else None for obj in objects]
        if None in anchors:
            raise PanelAlignmentError("axes")
        target = max(anchors) if command == "align_x" else min(anchors)
        deltas = [target - anchor for anchor in anchors]
    elif command.startswith("distribute_"):
        gap = (max(highs) - min(lows) - sum(high - low for low, high in zip(lows, highs, strict=True)))
        if gap < -1e-8:
            raise PanelAlignmentError("space")
        gap = max(0., gap) / (len(objects) - 1)
        cursor = min(lows)
        deltas = [0.] * len(objects)
        for index in sorted(range(len(lows)), key=lows.__getitem__):
            deltas[index] = cursor - lows[index]
            cursor += highs[index] - lows[index] + gap
    elif command in {"left", "top"}:
        deltas = [min(lows) - low for low in lows]
    elif command in {"right", "bottom"}:
        deltas = [max(highs) - high for high in highs]
    else:
        center = (min(lows) + max(highs)) / 2
        deltas = [center - (low + high) / 2 for low, high in zip(lows, highs, strict=True)]
    return {index: (0., delta) if direction else (delta, 0.)
            for delta, members in zip(deltas, objects, strict=True) for index in members}
