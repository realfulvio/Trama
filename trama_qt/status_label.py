"""The status bar message: one line that elides instead of widening the window.

A long message (for example a linked result that names a missing worksheet) is cut with an ellipsis at the
available width; the tooltip keeps the whole text and ``text()`` still returns it.
"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel


class StatusLabel(QLabel):
    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.fontMetrics().averageCharWidth() * 12), hint.height())

    def paintEvent(self, event):
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width())
        painter = QPainter(self)
        self.style().drawItemText(painter, rect, int(self.alignment()), self.palette(), self.isEnabled(), text,
                                  self.foregroundRole())
