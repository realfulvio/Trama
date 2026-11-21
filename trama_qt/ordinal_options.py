"""Qt category order editor for ordinal regression."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from analisi import ordinal_logit as engine
from analisi.i18n import tr, ui
from analisi.ordinal_logit_options import OrderState, describe_error, read_observed


class OrderEditor(QWidget):
    changed = Signal()

    def __init__(self, saved):
        super().__init__()
        self.state = OrderState(saved)
        self.list = QListWidget()
        self.list.setFixedHeight(5 * self.list.fontMetrics().lineSpacing() + 14)
        self.setFocusProxy(self.list)
        self.up = QPushButton(ui("Up"))
        self.down = QPushButton(ui("Down"))
        self.reset = QPushButton(ui("Reset"))
        self.up.clicked.connect(lambda: self.move(-1))
        self.down.clicked.connect(lambda: self.move(1))
        self.reset.clicked.connect(self.reset_order)
        self.list.currentRowChanged.connect(self._sync_buttons)
        for direction, step in (("Up", -1), ("Down", 1)):
            shortcut = QShortcut(QKeySequence(f"Alt+{direction}"), self.list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda step=step: self.move(step))
        self.note = QLabel()
        self.note.setWordWrap(True)
        buttons = QHBoxLayout()
        for button in (self.up, self.down, self.reset):
            buttons.addWidget(button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        layout.addLayout(buttons)
        layout.addWidget(self.note)
        self._render()

    def values(self):
        return list(self.state.order)

    def sync(self, observed, response):
        self.state.sync(observed, response)
        self._render()

    def _render(self, selected=0):
        self.list.clear()
        self.list.addItems([f"{index}. {label}" for index, label in enumerate(self.state.order, 1)])
        self.list.setCurrentRow(selected if self.state.order else -1)
        hint, _ = self.state.hint()
        self.note.setText(hint)
        self._sync_buttons()

    def _sync_buttons(self):
        row = self.list.currentRow()
        self.up.setEnabled(row > 0)
        self.down.setEnabled(0 <= row < self.list.count() - 1)
        self.reset.setEnabled(bool(self.state.observed))

    def move(self, step):
        target = self.state.move(self.list.currentRow(), step)
        if target is not None:
            self._render(target)
            self.changed.emit()

    def reset_order(self):
        self.state.reset()
        self._render()
        self.changed.emit()


def attach(dialog, profiles_page):
    response, predictors, categories, order, profiles = (
        dialog.controls[name][1] for name in
        (engine.RESPONSE, engine.PREDICTORS, engine.CATEGORICAL, engine.ORDER, engine.PROFILES)
    )

    def picked(box):
        return [box.item(row).text() for row in range(box.count())
                if box.item(row).checkState() == Qt.CheckState.Checked]

    def sync_order():
        selected = response.currentData()
        order.sync(read_observed(dialog.data, selected, picked(predictors)), selected)

    def sync_profiles():
        profiles.change_predictors(picked(predictors), picked(categories))

    response.currentIndexChanged.connect(sync_order)
    predictors.itemChanged.connect(sync_order)
    predictors.itemChanged.connect(sync_profiles)
    categories.itemChanged.connect(sync_profiles)
    order.changed.connect(lambda: dialog.clear_field_error(engine.ORDER))
    sync_order()
    sync_profiles()
    note = QLabel(tr("ord.hint.profiles"))
    note.setWordWrap(True)
    profiles_page.addRow(note)
