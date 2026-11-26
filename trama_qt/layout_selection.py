"""Pointer and keyboard selection for the editable layout page."""

from matplotlib.backend_bases import MouseButton
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from analisi.layout_panels import bounded_translation, enclosing_rectangle, resize_factor, resized_panels

from . import theme


class LayoutSelection:
    """A temporary selection. Translations are committed once, after releasing the pointer."""

    def __init__(self, canvas, layout, axes, enabled, changed, moved, resized):
        self.canvas, self.layout, self.axes = canvas, layout, axes
        self.enabled, self.changed, self.moved, self.resized = enabled, changed, moved, resized
        self.panels = canvas.figure.trama_layout_panels
        self.page = tuple(canvas.figure.get_size_inches())
        self.selected = set()
        self.indicators = []
        self.pending = None
        self.resize_corners = None
        self.dragged = False
        canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for signal, handler in (("button_press_event", self.press), ("motion_notify_event", self.motion),
                                ("button_release_event", self.release), ("key_press_event", self.key)):
            canvas.mpl_connect(signal, handler)

    @property
    def objects(self):
        return self.layout.arrangement.objects(self.selected)

    @property
    def locked(self):
        return bool(self.selected.intersection(self.layout.arrangement.locked))

    def select(self, panels):
        objects = self.layout.arrangement.objects(panels)
        self.selected = {index for obj in objects for index in obj}
        self.indicate()
        self.changed()

    def _boundary(self, members):
        return enclosing_rectangle(self.panels, members)

    @staticmethod
    def _corners(rect):
        left, top, right, bottom = rect
        return ((left, top), (right, top), (right, bottom), (left, bottom))

    def _resize_hit(self, x, y):
        width, height = self.page
        bbox = self.canvas.figure.bbox
        radius = 6 * self.canvas.device_pixel_ratio
        for members in self.objects:
            corners = self._corners(self._boundary(members))
            for index, (left, top) in enumerate(corners):
                px, py = left * bbox.width / width, (1 - top / height) * bbox.height
                if abs(x - px) <= radius and abs(y - py) <= radius:
                    return members, corners[(index + 2) % 4], (left, top)
        return None

    def indicate(self, shift=(0., 0.), *, scaled=None):
        for artist in self.indicators:
            artist.remove()
        self.indicators.clear()
        width, height = self.page
        dx, dy = shift
        for members in self.objects:
            left, top, right, bottom = self._boundary(members)
            if scaled is not None and members == scaled[0]:
                (anchor_x, anchor_y), factor = scaled[1:]
                left, right = (anchor_x + (value - anchor_x) * factor for value in (left, right))
                top, bottom = (anchor_y + (value - anchor_y) * factor for value in (top, bottom))
            locked = bool(set(members).intersection(self.layout.arrangement.locked))
            outline = Rectangle(((left + dx) / width, 1 - (bottom + dy) / height),
                                (right - left) / width, (bottom - top) / height,
                                transform=self.canvas.figure.transFigure, fill=False, clip_on=False,
                                edgecolor=theme.T["accent"], linewidth=1.5, linestyle="--" if locked else "-",
                                zorder=10000)
            self.canvas.figure.add_artist(outline)
            self.indicators.append(outline)
            if not self.locked:
                corners = self._corners((left + dx, top + dy, right + dx, bottom + dy))
                xs, ys = zip(*((x / width, 1 - y / height) for x, y in corners), strict=True)
                handles = Line2D(xs, ys, transform=self.canvas.figure.transFigure, linestyle="none", marker="s",
                                 markersize=4, markerfacecolor=theme.T["panel"], markeredgecolor=theme.T["accent"],
                                 clip_on=False, zorder=10001)
                self.canvas.figure.add_artist(handles)
                self.indicators.append(handles)
        self.canvas.draw_idle()

    def press(self, event):
        if event.button != MouseButton.LEFT or event.dblclick or not self.enabled():
            return
        index = self.axes.get(event.inaxes)
        self.pending = None
        self.resize_corners = None
        self.dragged = False
        self.canvas.setFocus()
        hit = self._resize_hit(event.x, event.y) if not self.locked else None
        if hit is not None:
            members, anchor, corner = hit
            self.resize_corners = anchor, corner
            self.pending = event.x, event.y, members
            return
        if index is None:
            self.select(())
            return
        members, = self.layout.arrangement.objects((index,))
        if event.modifiers.intersection({"ctrl", "shift"}):
            self.select(self.selected.symmetric_difference(members))
            return
        if index not in self.selected:
            self.select(members)
        self.pending = event.x, event.y, members

    def _delta(self, x, y):
        start_x, start_y, _ = self.pending
        dx, dy = x - start_x, y - start_y
        bbox = self.canvas.figure.bbox
        return dx * self.page[0] / bbox.width, -dy * self.page[1] / bbox.height

    def _scaled(self, x, y):
        anchor, corner = self.resize_corners
        dx, dy = self._delta(x, y)
        factor = resize_factor(anchor, corner, (corner[0] + dx, corner[1] + dy), self.page)
        return self.pending[2], anchor, factor

    def shift(self, dx, dy):
        return bounded_translation(enclosing_rectangle(self.panels, self.selected), (dx, dy), self.page)

    def motion(self, event):
        if self.pending is None or self.locked or not self.enabled():
            return
        x, y, _ = self.pending
        threshold = QApplication.startDragDistance() * self.canvas.device_pixel_ratio
        if not self.dragged and abs(event.x - x) + abs(event.y - y) < threshold:
            return
        self.dragged = True
        if self.resize_corners is not None:
            self.indicate(scaled=self._scaled(event.x, event.y))
        else:
            self.indicate(self.shift(*self._delta(event.x, event.y)))

    def release(self, event):
        if self.pending is None or event.button != MouseButton.LEFT:
            return
        shift, targets = None, None
        if self.dragged and self.enabled() and not self.locked:
            if self.resize_corners is not None:
                members, anchor, factor = self._scaled(event.x, event.y)
                targets = resized_panels(self.panels, members, anchor, factor)
            else:
                shift = self.shift(*self._delta(event.x, event.y))
        _, _, members = self.pending
        self.pending = None
        self.resize_corners = None
        if targets is not None:
            self.resized(targets)
        elif shift is not None and any(shift):
            self.moved(shift)
        elif not self.dragged and self.enabled():
            self.select(members)
        else:
            self.indicate()

    def key(self, event):
        if not self.enabled():
            return
        if event.key == "escape":
            self.pending = None
            self.resize_corners = None
            self.select(())
            return
        values = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
        if self.selected and not self.locked and event.key in values:
            dx, dy = values[event.key]
            # One typographic point, independent of the current zoom or device pixel ratio.
            shift = self.shift(dx / 72, dy / 72)
            if any(shift):
                self.moved(shift)
