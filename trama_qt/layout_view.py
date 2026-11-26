"""Screen rulers and guides in the physical coordinates of the layout page."""
from math import ceil, floor

from PySide6.QtCore import QEvent, QLineF, QLocale, QPoint, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QWidget

from analisi.figure_export import MM
from analisi.i18n import active_language

from . import theme
from .strings import qt


_STEPS_MM = tuple(factor * 10 ** decade for decade in range(5) for factor in (1, 2, 5))


def _mapped_rect(widget, surface):
    origin = surface.mapFromGlobal(widget.mapToGlobal(QPoint()))
    return QRectF(QPointF(origin), QSizeF(widget.size()))


def _marks(origin, pixels_per_mm, first, last):
    if pixels_per_mm <= 0 or first > last:
        return
    # Keep subdivisions at least 6 logical pixels apart and leave space for labels.
    minor = next((step for step in _STEPS_MM if step * pixels_per_mm >= 6), _STEPS_MM[-1])
    major = next((step for step in _STEPS_MM if step >= 10 and step % minor == 0
                  and step * pixels_per_mm >= 42), minor)
    pixels = minor * pixels_per_mm
    for index in range(max(0, ceil((first - origin) / pixels)), floor((last - origin) / pixels) + 1):
        mm = index * minor
        yield origin + index * pixels, mm, mm % major == 0


class LayoutView(QWidget):
    """Keep rulers at the viewport edges and paint a mouse-transparent page overlay."""

    def __init__(self, view):
        super().__init__()
        self.view, self.canvas = view, view.canvas
        self.top = _Ruler(self, "horizontal")
        self.left = _Ruler(self, "vertical")
        self.corner = _Ruler(self, "both")
        self.overlay = _GridOverlay(view.viewport(), self)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(self.corner, 0, 0)
        grid.addWidget(self.top, 0, 1)
        grid.addWidget(self.left, 1, 0)
        grid.addWidget(view, 1, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(1, 1)
        for widget in (view.viewport(), view.widget(), self.canvas):
            widget.installEventFilter(self)
        for scrollbar in (view.horizontalScrollBar(), view.verticalScrollBar()):
            scrollbar.valueChanged.connect(self.repaint_aids)

    @property
    def pixels_per_mm(self):
        return self.canvas.figure.dpi / self.canvas.device_pixel_ratio / MM

    def page_rect(self, surface):
        return _mapped_rect(self.canvas, surface)

    def visible_page(self, surface):
        return self.page_rect(surface).intersected(_mapped_rect(self.view.viewport(), surface))

    def set_options(self, *, rulers, grid):
        for part in (self.top, self.left, self.corner):
            part.setVisible(rulers)
        self.overlay.lines = grid
        if not rulers:
            self.overlay.guide = None
        self.overlay.setVisible(grid or self.overlay.guide is not None)
        self.repaint_aids()

    def set_guide(self, guide):
        self.overlay.guide = guide
        self.overlay.setVisible(self.overlay.lines or guide is not None)
        self.repaint_aids()

    def repaint_aids(self, *_):
        self.overlay.setGeometry(self.view.viewport().rect())
        self.overlay.raise_()
        for part in (self.top, self.left, self.corner, self.overlay):
            part.update()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            self.repaint_aids()
        return False


class _Ruler(QWidget):
    def __init__(self, frame, direction):
        super().__init__(frame)
        self.frame, self.direction = frame, direction
        self.dragging = False
        self.setAccessibleName(qt(f"qt.layout_ruler_{direction}"))
        self.setToolTip(qt(f"qt.layout_guide_{direction}"))
        self.setCursor(Qt.CursorShape.CrossCursor)
        if direction != "vertical":
            self.setFixedHeight(self.fontMetrics().height() + 11)
        if direction != "horizontal":
            self.setFixedWidth(self.fontMetrics().horizontalAdvance("000") + 16)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.T["panel2"]))
        painter.setPen(QColor(theme.T["border"]))
        right, bottom = self.width() - 1, self.height() - 1
        painter.drawLine(0, bottom, right, bottom)
        painter.drawLine(right, 0, right, bottom)
        painter.setPen(QColor(theme.T["text2"]))
        if self.direction == "both":
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, qt("qt.layout_ruler_unit"))
            return
        page = self.frame.page_rect(self)
        viewport = _mapped_rect(self.frame.view.viewport(), self)
        locale = QLocale("it_IT" if active_language() == "it" else "en_US")
        horizontal = self.direction == "horizontal"
        origin = page.x() if horizontal else page.y()
        low = max(0, origin, viewport.x() if horizontal else viewport.y())
        high = min(right, page.right(), viewport.right()) if horizontal else min(bottom, page.bottom(), viewport.bottom())
        if high <= low:
            return
        painter.setClipRect(QRectF(low, 0, high - low, self.height()) if horizontal else
                            QRectF(0, low, self.width(), high - low))
        metrics = self.fontMetrics()
        for pixel, mm, major in _marks(origin, self.frame.pixels_per_mm, low, high):
            length = 8 if major else 4
            text = locale.toString(mm // 10) if major else ""
            if horizontal:
                painter.drawLine(QLineF(pixel, bottom - length, pixel, bottom))
                if text and (width := metrics.horizontalAdvance(text)) < high - low:
                    capped = min(pixel + 3, high - width)
                    painter.drawText(QPointF(capped, metrics.ascent()), text)
            else:
                painter.drawLine(QLineF(right - length, pixel, right, pixel))
                if text and (height := metrics.height()) < high - low:
                    capped = min(max(low, pixel - height / 2), high - height)
                    label = QRectF(0, capped, right - length - 3, height)
                    painter.drawText(label, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.frame.set_guide((self.direction, event.globalPosition().toPoint()))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.frame.set_guide((self.direction, event.globalPosition().toPoint()))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.dragging and event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.frame.set_guide(None)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def event(self, event):
        if event.type() in (QEvent.Type.UngrabMouse, QEvent.Type.Hide) and self.dragging:
            self.dragging = False
            self.frame.set_guide(None)
        return super().event(event)


class _GridOverlay(QWidget):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self.lines = False
        self.guide = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        page = self.frame.page_rect(self)
        visible = self.frame.visible_page(self)
        if visible.isEmpty():
            return
        painter = QPainter(self)
        painter.setClipRect(visible)
        if self.lines:
            scale = self.frame.pixels_per_mm
            grid = QColor(theme.T["accent"])
            for horizontal in (False, True):
                origin, first, last = ((page.y(), visible.top(), visible.bottom()) if horizontal
                                       else (page.x(), visible.left(), visible.right()))
                for pixel, _, major in _marks(origin, scale, first, last):
                    grid.setAlpha(96 if major else 36)
                    painter.setPen(grid)
                    painter.drawLine(self._line(visible, pixel, horizontal))
        if self.guide is not None:
            direction, point = self.guide
            point = self.mapFromGlobal(point)
            if visible.contains(QPointF(point)):
                pen = QPen(QColor(theme.T["accent"]))
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                if direction != "vertical":
                    painter.drawLine(self._line(visible, point.y(), True))
                if direction != "horizontal":
                    painter.drawLine(self._line(visible, point.x(), False))

    @staticmethod
    def _line(area, pixel, horizontal):
        if horizontal:
            return QLineF(area.left(), pixel, area.right(), pixel)
        return QLineF(pixel, area.top(), pixel, area.bottom())
