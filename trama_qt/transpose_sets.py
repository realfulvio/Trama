"""Choose the source columns of each Y set without parsing their display labels."""
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from analisi import transpose_xy as xy
from analisi.i18n import tr

from .labels import choice_label, field_label
from .strings import qt


class TransposeSets(QWidget):
    def __init__(self, frame, x, records):
        super().__init__()
        self.frame, self.x = frame, x
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([qt("qt.function_curve_name"), field_label("Mode"), field_label("Columns")])
        self.table.setMinimumHeight(155)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.setFocusProxy(self.table)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.add_button = QPushButton(tr("shape.add"))
        self.add_button.clicked.connect(lambda: self.add({}))
        self.remove_button = QPushButton(tr("shape.remove"))
        self.remove_button.clicked.connect(self.remove)
        suggest = QPushButton(qt("qt.transpose_suggest"))
        suggest.clicked.connect(self.suggest)
        for button in (self.add_button, self.remove_button, suggest):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.table.itemSelectionChanged.connect(self.sync)
        for record in records:
            self.add(record)
        self.sync()

    def suggest(self):
        self.table.setRowCount(0)
        for record in xy.propose_sets(self.frame, self.x.currentData())[:xy.MAX_SETS]:
            self.add(record)
        self.sync()

    def add(self, record):
        row = self.table.rowCount()
        if row >= xy.MAX_SETS:
            return
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(record.get("name", "")))
        mode = QComboBox()
        for value in xy.MODES:
            mode.addItem(choice_label(value), value)
        mode.setCurrentIndex(max(0, mode.findData(record.get("mode"))))
        self.table.setCellWidget(row, 1, mode)
        columns = QToolButton()
        columns.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(columns)
        columns.setMenu(menu)
        names = list(dict.fromkeys([*record.get("columns", ()), *map(str, self.frame.columns)]))

        def caption():
            checked = ", ".join(action.data() for action in menu.actions() if action.isChecked())
            columns.setText(checked if len(checked) <= 28 else checked[:25] + "…")
            columns.setToolTip(checked or qt("qt.transpose_columns"))
            if not checked:
                columns.setText(qt("qt.transpose_columns"))

        for name in names:
            action = menu.addAction(name.replace("&", "&&"))
            action.setData(name)
            action.setCheckable(True)
            action.setChecked(name in record.get("columns", ()))
            action.toggled.connect(caption)
        caption()
        self.table.setCellWidget(row, 2, columns)
        self.sync()

    def remove(self):
        rows = {item.row() for item in self.table.selectedItems()}
        for row in sorted(rows, reverse=True):
            self.table.removeRow(row)
        self.sync()

    def sync(self):
        self.add_button.setEnabled(self.table.rowCount() < xy.MAX_SETS)
        self.remove_button.setEnabled(bool(self.table.selectedItems()))

    def values(self):
        return [{"name": self.table.item(row, 0).text(), "mode": self.table.cellWidget(row, 1).currentData(),
                 "columns": [action.data() for action in self.table.cellWidget(row, 2).menu().actions()
                             if action.isChecked()]}
                for row in range(self.table.rowCount())]
