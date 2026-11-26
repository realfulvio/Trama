"""Previews for the Qt gallery: a bounded cache, a small queue and the drawing of one card.

Matplotlib figures are not thread safe, so every preview is drawn on the GUI thread, one figure per timer
tick, and never while a calculation runs in the background. A figure is drawn with ``savefig`` (which puts its
canvas back), never by attaching a new canvas, so a preview cannot take over the figure that a page shows.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass
from io import BytesIO

from PySide6.QtCore import QCoreApplication, QObject, QRectF, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from .gallery_catalog import describe

CACHE_LIMIT = 64
TICK_MS = 2  # Between two figures the event loop handles clicks and keys.
BUSY_MS = 200  # How often a queue waits for a running calculation to end.


@dataclass(eq=False)
class Thumb:
    """A drawn preview (or the reason there is none) with what it was drawn from."""
    pixmap: QPixmap | None
    refs: tuple
    sig: tuple
    error: str | None = None

    @property
    def bytes(self):
        return self.pixmap.width() * self.pixmap.height() * 4 if self.pixmap is not None else 0


def current(thumb, entry):
    """True while the preview still shows the confirmed results and style of ``entry``."""
    return (thumb.sig == entry.sig and len(thumb.refs) == len(entry.refs)
            and all(a is b for a, b in zip(thumb.refs, entry.refs)))


def _same(drawn, entry):
    return drawn.ref == entry.ref and current(Thumb(None, drawn.refs, drawn.sig), entry)


class ThumbnailCache:
    """Least recently used previews, at most ``limit``. A preview is served only while it is ``current``."""

    def __init__(self, limit=CACHE_LIMIT):
        self.limit = limit
        self._items = OrderedDict()

    def __len__(self):
        return len(self._items)

    def __contains__(self, ref):
        return ref in self._items

    def get(self, entry):
        thumb = self._items.get(entry.ref)
        if thumb is None:
            return None
        if not current(thumb, entry):  # Data, style or a recalculation changed: the preview is out of date.
            del self._items[entry.ref]
            return None
        self._items.move_to_end(entry.ref)
        return thumb

    def put(self, entry, thumb):
        self._items[entry.ref] = thumb
        self._items.move_to_end(entry.ref)
        while len(self._items) > self.limit:
            self._items.popitem(last=False)

    def prune(self, refs):
        """Forget the previews of sheets that are not in ``refs`` any more."""
        for ref in [ref for ref in self._items if ref not in refs]:
            del self._items[ref]

    def clear(self):
        self._items.clear()

    @property
    def bytes(self):
        return sum(thumb.bytes for thumb in self._items.values())


def _require_gui_thread():
    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError("Gallery previews are drawn on the GUI thread only.")


def figure_image(figure, width, height):
    """``figure`` as an image that fits ``width`` × ``height`` pixels, with its own proportions."""
    _require_gui_thread()
    inches_w, inches_h = figure.get_size_inches()
    if inches_w <= 0 or inches_h <= 0 or width < 1 or height < 1:
        raise ValueError("The figure has no size to draw.")
    dpi = max(4.0, min(300.0, width / inches_w, height / inches_h))
    with BytesIO() as buffer:
        figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
        image = QImage.fromData(buffer.getvalue(), "PNG")
    if image.isNull():
        raise ValueError("The preview could not be drawn.")
    return image


def render(entry, project, box):
    """Draw the card of ``entry`` inside ``box`` (device pixels). A generator: it yields after each figure so
    that a layout of many panels never blocks the window, and returns the image."""
    from analisi.layout_geometry import page_size
    from analisi.layout_panels import panel_plan_steps
    _require_gui_thread()
    kind, key = entry.ref
    box_w, box_h = box
    if kind != "layout":
        yield
        return figure_image(project.runs[key].result.figure, box_w, box_h)
    layout = project.layouts[key]
    figures = project.layout_figures(layout)
    page_w, page_h = page_size(layout.columns, len(figures), layout.paper)
    scale = min(box_w / page_w, box_h / page_h)  # Pixels per inch of the page: the page keeps its shape.
    placements = yield from panel_plan_steps(layout.columns, figures, layout.paper, panel_size=layout.panel_size,
                                             axis_alignment=layout.axis_alignment)
    page = QImage(max(1, round(page_w * scale)), max(1, round(page_h * scale)),
                  QImage.Format.Format_ARGB32_Premultiplied)
    page.fill(QColor(layout.background))
    painter = QPainter(page)
    try:
        for placement in placements:
            if placement.figure is None:
                continue
            w, h = placement.size
            x, y, fit = placement.box
            with placement.render() as figure:
                tile = figure_image(figure, max(1, round(w * fit * scale)), max(1, round(h * fit * scale)))
            painter.drawImage(QRectF(x * scale, y * scale, w * fit * scale, h * fit * scale), tile)
            yield
    finally:
        painter.end()
    return page


class _Task:
    def __init__(self, entry, project, box):
        self.entry = entry
        self.steps = render(entry, project, box)
        self.image = None

    def step(self):
        """Draw the next figure; True when the card is complete."""
        try:
            next(self.steps)
        except StopIteration as stop:
            self.image = stop.value
            return True
        return False

    def close(self):
        self.steps.close()


class ThumbnailService(QObject):
    """Draws the previews that are asked for, one figure at a time, and keeps them in a bounded cache.

    ``project`` returns the project the gallery shows; ``busy`` tells whether a calculation is running.
    """
    ready = Signal(object)  # The reference of a card whose preview was just drawn.
    outdated = Signal()  # A preview was dropped because its results changed while it was drawn.

    def __init__(self, project, busy, parent=None, *, limit=CACHE_LIMIT):
        super().__init__(parent)
        self.project, self.busy = project, busy
        self.cache = ThumbnailCache(limit)
        self.box, self.ratio = (240, 150), 1.0
        self.queue, self.task = deque(), None
        self.drawn = 0  # Cards drawn since the service was made, for the measurements.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

    # -- asking ----------------------------------------------------------------------------------------
    def request(self, entries, box, ratio=1.0):
        """Draw ``entries`` (the visible cards, in reading order). Anything asked for before and not listed
        again is forgotten, so scrolling never leaves a backlog of cards that are out of sight."""
        if (box, ratio) != (self.box, self.ratio):  # Another scale or card size: the old previews do not fit.
            self.cache.clear()
        self.box, self.ratio = box, ratio
        wanted = [entry for entry in entries if entry.previewable and self.cache.get(entry) is None]
        if self.task is not None and not any(_same(self.task.entry, entry) for entry in wanted):
            self._drop_task()  # It scrolled out of sight, or its results changed.
        self.queue = deque(entry for entry in wanted if self.task is None or not _same(self.task.entry, entry))
        if (self.task is not None or self.queue) and not self._timer.isActive():
            self._timer.start(TICK_MS)  # Not restarted: asking again and again must not postpone the drawing.

    def clear(self):
        """The project changed: forget every preview and everything that was waiting."""
        self._timer.stop()
        self.queue.clear()
        self._drop_task()
        self.cache.clear()

    def stop(self):
        self.clear()

    def _drop_task(self):
        if self.task is not None:
            self.task.close()
            self.task = None

    # -- drawing -----------------------------------------------------------------------------------------
    def _tick(self):
        if self.busy():  # A background calculation owns Matplotlib: wait for it to end.
            self._timer.start(BUSY_MS)
            return
        if self.task is None:
            if not self.queue:
                return
            entry = self.queue.popleft()
            self.task = _Task(entry, self.project(), (round(self.box[0]), round(self.box[1])))
        task = self.task
        try:
            done = task.step()
        except Exception as error:  # noqa: BLE001 - one bad figure must not take the gallery down.
            self.task = None
            self._store(task.entry, None, f"{type(error).__name__}: {error}")
        else:
            if done:
                self.task = None
                pixmap = QPixmap.fromImage(task.image)
                pixmap.setDevicePixelRatio(self.ratio)
                self._store(task.entry, pixmap, None)
        if self.task is not None or self.queue:
            self._timer.start(TICK_MS)

    def _store(self, entry, pixmap, error):
        fresh = describe(self.project(), entry.ref)
        if fresh is None or not _same(entry, fresh):
            self.outdated.emit()  # Recalculated or restyled while it was drawn: the next scan asks again.
            return
        self.cache.put(entry, Thumb(pixmap, entry.refs, entry.sig, error))
        self.drawn += 1
        self.ready.emit(entry.ref)
