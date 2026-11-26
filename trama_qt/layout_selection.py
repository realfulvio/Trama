"""Pointer and keyboard selection for the editable layout page."""

from matplotlib.backend_bases import MouseButton
from matplotlib.patches import Rectangle
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from analisi.layout_panels import bounded_translation, enclosing_rectangle

from . import theme


class LayoutSelection:
    """A temporary selection. Translations are committed once, after releasing the pointer."""

    def __init__(self, canvas, layout, axes, enabled, changed, moved):
        self.canvas, self.layout, self.axes = canvas, layout, axes
        self.enabled, self.changed, self.moved = enabled, changed, moved
        self.panels = canvas.figure.trama_layout_panels
        self.page = tuple(canvas.figure.get_size_inches())
        self.selected = set()
        self.indicators = []
        self.pending = None
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

    def indicate(self, shift=(0., 0.)):
        for patch in self.indicators:
            patch.remove()
        self.indicators.clear()
        width, height = self.page
        dx, dy = shift
        for members in self.objects:
            left, top, right, bottom = enclosing_rectangle(self.panels, members)
            locked = bool(set(members).intersection(self.layout.arrangement.locked))
            outline = Rectangle(((left + dx) / width, 1 - (bottom + dy) / height),
                                (right - left) / width, (bottom - top) / height,
                                transform=self.canvas.figure.transFigure, fill=False, clip_on=False,
                                edgecolor=theme.T["accent"], linewidth=1.5, linestyle="--" if locked else "-",
                                zorder=10000)
            self.canvas.figure.add_artist(outline)
            self.indicators.append(outline)
        self.canvas.draw_idle()

    def press(self, event):
        if event.button != MouseButton.LEFT or event.dblclick or not self.enabled():
            return
        index = self.axes.get(event.inaxes)
        self.pending = None
        self.dragged = False
        self.canvas.setFocus()
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
        self.indicate(self.shift(*self._delta(event.x, event.y)))

    def release(self, event):
        if self.pending is None or event.button != MouseButton.LEFT:
            return
        shift = self.shift(*self._delta(event.x, event.y)) if self.dragged and self.enabled() and not self.locked else None
        _, _, members = self.pending
        self.pending = None
        if shift is not None and any(shift):
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
            self.select(())
            return
        values = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
        if self.selected and not self.locked and event.key in values:
            dx, dy = values[event.key]
            # One typographic point, independent of the current zoom or device pixel ratio.
            shift = self.shift(dx / 72, dy / 72)
            if any(shift):
                self.moved(shift)
