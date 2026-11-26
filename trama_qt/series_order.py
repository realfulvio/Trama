"""Reorder series in a graph."""

from typing import NamedTuple

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QVBoxLayout)

from .strings import qt
from .theme import fit_dialog


class SeriesOrderEntry(NamedTuple):
    key: str
    name: str


class SeriesOrderDialog(QDialog):
    """Keep the drawing order of each axes in a separate list."""

    def __init__(self, parent, groups, defaults, primary, *, grouped=False):
        super().__init__(parent)
        self.setWindowTitle(qt("qt.series_drawing_order"))
        self.groups = [list(items) for _, items in groups]
        self.defaults = [list(items) for _, items in defaults]
        self.order = None
        self.use_default = False
        layout = QVBoxLayout(self)
        hint_key = "qt.series_order_hint_dual" if len(groups) > 1 else "qt.series_order_hint"
        hint = QLabel(qt("qt.grouped_series_order_hint" if grouped else hint_key))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.axis = QComboBox()
        self.axis.setAccessibleName(qt("qt.series_order_axis"))
        for axes, _ in groups:
            self.axis.addItem(qt("qt.series_order_left" if axes is primary else "qt.series_order_right"))
        self.axis.setVisible(len(groups) > 1)
        layout.addWidget(self.axis)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setAccessibleName(qt("qt.grouped_series_order_list" if grouped else "qt.series_order_list"))
        row.addWidget(self.list, 1)
        controls = QVBoxLayout()
        self.back = QPushButton(qt("qt.series_order_up" if grouped else "qt.series_order_back"))
        self.front = QPushButton(qt("qt.series_order_down" if grouped else "qt.series_order_front"))
        self.back.clicked.connect(lambda: self.move(-1))
        self.front.clicked.connect(lambda: self.move(1))
        controls.addWidget(self.back)
        controls.addWidget(self.front)
        controls.addStretch()
        row.addLayout(controls)
        layout.addLayout(row, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        apply = buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply.setText(qt("qt.series_order_apply"))
        apply.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        reset = buttons.addButton(qt("qt.series_order_reset"), QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(self.reset)
        layout.addWidget(buttons)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        apply.setAutoDefault(True)
        apply.setDefault(True)
        self.axis.currentIndexChanged.connect(self.refresh_list)
        self.list.currentRowChanged.connect(self.update_buttons)
        if hasattr(parent, "show_shortcuts"):
            QShortcut(QKeySequence("F1"), self, parent.show_shortcuts)
        self.refresh_list()
        self.list.setFocus()
        fit_dialog(self, 460, 350)

    def refresh_list(self, *_):
        group = self.groups[self.axis.currentIndex()]
        self.list.clear()
        self.list.addItems([item.name for item in group])
        self.list.setCurrentRow(0)
        self.update_buttons()

    def update_buttons(self, *_):
        row = self.list.currentRow()
        self.back.setEnabled(row > 0)
        self.front.setEnabled(0 <= row < self.list.count() - 1)

    def move(self, step):
        row = self.list.currentRow()
        target = row + step
        group = self.groups[self.axis.currentIndex()]
        if row < 0 or not 0 <= target < len(group):
            return
        self.use_default = False
        group.insert(target, group.pop(row))
        self.list.insertItem(target, self.list.takeItem(row))
        self.list.setCurrentRow(target)

    def reset(self):
        self.use_default = True
        self.groups = [list(items) for items in self.defaults]
        self.refresh_list()

    def accept(self):
        self.order = [] if self.use_default else [item.key for group in self.groups for item in group]
        super().accept()
