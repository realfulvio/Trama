"""Assign graph references from the navigator to layout panels."""

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QTreeWidget


GRAPH_MIME = "application/x-trama-graph"


class GraphNavigator(QTreeWidget):
    def __init__(self, graph_id):
        super().__init__()
        self.graph_id = graph_id
        self.pending_drop = None

    def startDrag(self, _actions):
        item = self.currentItem()
        reference = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        identifier = self.graph_id(reference)
        if identifier is None:
            return
        data = QMimeData()
        data.setData(GRAPH_MIME, identifier.encode("ascii"))
        drag = QDrag(self)
        drag.setMimeData(data)
        self.pending_drop = None
        try:
            if drag.exec(Qt.DropAction.CopyAction) == Qt.DropAction.CopyAction and self.pending_drop is not None:
                # The drop can replace the canvas and rebuild the tree. Leave the native drag first.
                QTimer.singleShot(0, self.pending_drop)
        finally:
            self.pending_drop = None
            drag.deleteLater()


class LayoutDrop(QObject):
    def __init__(self, canvas, navigator, slots, resolve, assign):
        super().__init__(canvas)
        self.canvas, self.navigator, self.slots = canvas, navigator, slots
        self.resolve, self.assign = resolve, assign
        canvas.setAcceptDrops(True)
        canvas.installEventFilter(self)

    def eventFilter(self, _obj, event):
        phase = event.type()
        if phase not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return False
        if event.source() is not self.navigator or not event.mimeData().hasFormat(GRAPH_MIME):
            return False
        identifier = bytes(event.mimeData().data(GRAPH_MIME)).decode("ascii", "replace")
        graph = self.resolve(identifier)
        point = self.canvas.mouseEventCoords(event.position())
        slot = self.slots.get(self.canvas.inaxes(point))
        if graph is None or (slot is None and phase != QEvent.Type.DragEnter):
            event.ignore()
        else:
            event.acceptProposedAction()
            if phase == QEvent.Type.Drop:
                def finish():
                    if (current := self.resolve(identifier)) is not None:
                        self.assign(slot, current)

                self.navigator.pending_drop = finish
        return True
