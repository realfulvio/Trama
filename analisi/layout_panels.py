"""Plan the size and position of native layout panels for both raster and vector output."""
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, replace
from math import isclose

from matplotlib.figure import Figure

from .layout_arrangement import EMPTY_CROP, PanelArrangement
from .layout_geometry import AUTO_PAPER, PT, page_size, panel_boxes, panel_cells


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

    angle: int = 0  # Clockwise, as seen on the page.
    border: tuple[float, str, str] | None = None
    crop: tuple[float, float, float, float] = EMPTY_CROP

    @property
    def crop_bounds(self):
        width, height = self.size
        left, top, right, bottom = self.crop
        return left * width, top * height, (1 - right) * width, (1 - bottom) * height

    @property
    def cropped_size(self):
        left, top, right, bottom = self.crop_bounds
        return right - left, bottom - top

    @property
    def oriented_size(self):
        size = self.cropped_size
        return size[::-1] if self.angle else size

    def crop_pixels(self, width, height):
        left, top, right, bottom = self.crop
        x, y = round(left * width), round(top * height)
        return x, y, max(x + 1, round((1 - right) * width)), max(y + 1, round((1 - bottom) * height))

    def render(self):
        return _panel_figure(self.figure, self.size, self.axes, self.bounds)


def _plot_bounds(panel):
    if panel.angle:
        return None
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
        crop_l, crop_t, crop_r, crop_b = panel.crop_bounds
        origin_x, origin_y = x - crop_l * scale, y - crop_t * scale
        edges = (origin_x + left * w, origin_y + (1 - bottom) * h,
                 origin_x + (left + width) * w, origin_y + (1 - bottom - height) * h)
        if x <= edges[0] <= origin_x + crop_r * scale and y <= edges[1] <= origin_y + crop_b * scale:
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
        crop_l, crop_t, _, _ = panel.crop_bounds
        x, y = x - crop_l * scale, y - crop_t * scale
        position = (max(0., (target_left - x) / w), min(1., 1 - (target_bottom - y) / h),
                    (right - target_left) / w, (target_bottom - top) / h)
        panels[index] = replace(panel, axes=axes, bounds=position)
    return panels


def panel_plan_steps(columns, figures, paper=AUTO_PAPER, *, panel_size="original", axis_alignment="none",
                     arrangement=PanelArrangement()):
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
    for index, angle in arrangement.rotations:
        panels[index] = replace(panels[index], angle=angle)
    for index, *border in arrangement.borders:
        panels[index] = replace(panels[index], border=tuple(border))
    for index, *crop in arrangement.crops:
        panels[index] = replace(panels[index], crop=tuple(crop))
    if axis_alignment != "none" and len(panels) > 1:
        measurements = []
        for panel in panels:
            measurements.append(_plot_bounds(panel) if panel.figure is not None else None)
            yield
        panels = _align_panels(panels, columns, axis_alignment, measurements)
    width, height = page_size(columns, len(panels), paper)
    for index, dx, dy in arrangement.offsets:
        panel = panels[index]
        x, y, scale = panel.box
        panels[index] = replace(panel, box=(x + dx * width, y + dy * height, scale))
    for index, factor in arrangement.scales:
        panel = panels[index]
        x, y, scale = panel.box
        panels[index] = replace(panel, box=(x, y, scale * factor))
    return panels


def plan_panels(columns, figures, paper=AUTO_PAPER, *, panel_size="original", axis_alignment="none", arrangement=PanelArrangement()):
    steps = panel_plan_steps(columns, figures, paper, panel_size=panel_size, axis_alignment=axis_alignment,
                             arrangement=arrangement)
    try:
        while True:
            next(steps)
    except StopIteration as finished:
        return finished.value


def panel_rectangle(panel):
    """The graph's outer rectangle in page inches, with the origin at the top left."""
    x, y, scale = panel.box
    w, h = panel.oriented_size
    return x, y, x + w * scale, y + h * scale


def layout_labels(panels, order):
    """Use the foreground label when two panel corners coincide on the page."""
    labels = set()
    occupied = []
    for index in reversed(order):
        if panels[index].figure is None:
            continue
        x, y, _ = panels[index].box
        if not any(abs(x - left) * PT < 1 and abs(y - top) * PT < 1 for left, top in occupied):
            labels.add(index)
            occupied.append((x, y))
    return labels


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
    crop_l, crop_t, _, _ = panel.crop_bounds
    scale = panel.box[2]
    if axis == "x":
        anchor = top + scale * (panel.size[1] * (1 - axis_y) - crop_t)
        return anchor if top <= anchor <= bottom else None
    anchor = left + scale * (panel.size[0] * axis_x - crop_l)
    return anchor if left <= anchor <= right else None


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


def rotation_target(panel, box, angle, page, *, fixed):
    """Keep the center on each untouched axis and stay inside the page when possible."""
    if bool(angle) == bool(panel.angle):
        return box
    x, y, scale = box
    width, height = (value * scale for value in panel.oriented_size)
    if not fixed[0]:
        x = min(max(0., x + (width - height) / 2), max(0., page[0] - height))
    if not fixed[1]:
        y = min(max(0., y + (height - width) / 2), max(0., page[1] - width))
    return x, y, scale


def targets_fit(panels, targets, page, *, sizes=None):
    """Check page limits without imposing the preview's pixel precision on saved values."""
    width, height = page
    for index, (x, y, scale) in targets.items():
        panel = panels[index]
        w, h = sizes.get(index, panel.oriented_size) if sizes else panel.oriented_size
        current = panel_rectangle(panel)
        if (scale <= 0 or x < min(0., current[0]) - 1e-8 or y < min(0., current[1]) - 1e-8
                or x + w * scale > max(width, current[2]) + 1e-8
                or y + h * scale > max(height, current[3]) + 1e-8):
            return False
    return True


def resized_panels(panels, indices, anchor, factor):
    """Scale a group about its opposite corner, preserving relative panel positions."""
    left, top = anchor
    targets = {}
    for index in indices:
        x, y, scale = panels[index].box
        targets[index] = left + (x - left) * factor, top + (y - top) * factor, scale * factor
    return targets


def resize_factor(anchor, corner, cursor, page):
    """Project the pointer onto the diagonal, stopping before either edge of the page."""
    x, y = anchor
    dx, dy = corner[0] - x, corner[1] - y
    u, v = cursor[0] - x, cursor[1] - y
    result = (dx * u + dy * v) / (dx * dx + dy * dy)
    right, bottom = page
    limit = max(1e-8, min((right - x) / dx if dx > 0 else -x / dx,
                           (bottom - y) / dy if dy > 0 else -y / dy))
    return max(min(.05, limit), min(result, max(1., limit)))
