"""Category ordering and bootstrap controls for Cohen's kappa in Qt."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from analisi import cohen_kappa as engine
from analisi.cohen_kappa_options import order_notes, preview, propose_order
from analisi.cohen_kappa_workbench import HINT_KEYS, PREFIX, visibility
from analisi.field_error import FieldError
from analisi.i18n import tr


class CategoryOrder(QWidget):
    changed = Signal()

    def __init__(self, saved):
        super().__init__()
        try:
            self.saved = engine.read_order(saved)
        except FieldError:
            self.saved = [str(item) for item in saved] if isinstance(saved, (list, tuple)) else []
        self.items = list(self.saved)
        self.observed = None
        self.weighting = engine.UNWEIGHTED
        self.problem = ""
        self.list = QListWidget()
        self.list.setMinimumHeight(5 * self.list.fontMetrics().lineSpacing() + 18)
        self.list.setMaximumHeight(160)
        self.setFocusProxy(self.list)
        buttons = QVBoxLayout()
        self.buttons = {}
        for name, action in (("up", lambda: self.move(-1)), ("down", lambda: self.move(1)),
                             ("propose", self.propose), ("restore", lambda: self.replace(self.saved)),
                             ("clear", lambda: self.replace([]))):
            button = QPushButton(tr(PREFIX + "order." + name))
            button.clicked.connect(action)
            buttons.addWidget(button)
            self.buttons[name] = button
        buttons.addStretch()
        for modifier in ("Alt", "Ctrl"):
            for key, step in (("Up", -1), ("Down", 1)):
                shortcut = QShortcut(QKeySequence(f"{modifier}+{key}"), self.list)
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
                shortcut.activated.connect(lambda step=step: self.move(step))
        self.list.currentRowChanged.connect(self._sync_buttons)
        row = QHBoxLayout()
        row.addWidget(self.list, 1)
        row.addLayout(buttons)
        self.note = QLabel()
        self.hint = QLabel()
        for label in (self.note, self.hint):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setObjectName("muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.note)
        layout.addWidget(self.hint)
        self._render()

    def values(self):
        return list(self.items)

    def sync(self, observed, problem, weighting):
        self.observed, self.problem, self.weighting = observed, problem, weighting
        self._render(self.list.currentRow())

    def _render(self, selected=0):
        self.list.clear()
        self.list.addItems(self.items)
        if self.items:
            self.list.setCurrentRow(max(0, min(selected, len(self.items) - 1)))
        self.note.setText("\n".join(order_notes(self.items, self.observed, self.weighting, self.problem)))
        self.note.setVisible(bool(self.note.text()))
        automatic = [tr(PREFIX + "order.automatic")] if not self.items and self.weighting == engine.UNWEIGHTED else []
        self.hint.setText("\n".join([*automatic, tr(PREFIX + "order.keys")]))
        self._sync_buttons()

    def _sync_buttons(self):
        row = self.list.currentRow()
        self.buttons["up"].setEnabled(row > 0)
        self.buttons["down"].setEnabled(0 <= row < len(self.items) - 1)
        self.buttons["propose"].setEnabled(self.observed is not None)
        self.buttons["restore"].setEnabled(self.items != self.saved)
        self.buttons["clear"].setEnabled(bool(self.items))

    def move(self, step):
        row = self.list.currentRow()
        target = row + step
        if 0 <= row < len(self.items) and 0 <= target < len(self.items):
            self.items[row], self.items[target] = self.items[target], self.items[row]
            self._render(target)
            self.changed.emit()

    def replace(self, items):
        self.items = list(items)
        self._render()
        self.changed.emit()

    def propose(self):
        if self.observed is not None:
            self.replace(propose_order(self.items, self.observed))


def attach(dialog, pages):
    first, second, weighting, order, interval = (dialog.controls[field][1] for field in
        (engine.FIRST, engine.SECOND, engine.WEIGHTING, engine.ORDER, engine.INTERVAL))

    def refresh_order():
        observed, problem = preview(dialog.data, first.currentData(), second.currentData())
        order.sync(observed, problem, weighting.currentData())

    def refresh_interval():
        dialog._set_field_visibility(visibility(interval.currentData()))
        if dialog.error_field in dialog.hidden:
            dialog.clear_field_error(dialog.error_field)

    for control in (first, second, weighting):
        control.currentIndexChanged.connect(refresh_order)
    interval.currentIndexChanged.connect(refresh_interval)
    order.changed.connect(lambda: dialog.clear_field_error(engine.ORDER))
    refresh_order()
    refresh_interval()
    for page, key in (("variables", "ratings"), ("options", "interval")):
        note = QLabel(tr(HINT_KEYS[key]))
        note.setWordWrap(True)
        note.setObjectName("muted")
        pages[page].addRow(note)
