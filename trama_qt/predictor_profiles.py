"""Editable named predictor profiles shared by regression dialogs."""
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHeaderView, QHBoxLayout, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from analisi.cox_outputs import categories_of
from analisi.data import decimal_comma
from analisi.i18n import ui

from .strings import qt


class Profiles(QWidget):
    """One editable row per profile, with literal labels and the current predictor columns."""

    def __init__(self, frame, records, *, limit=12):
        super().__init__()
        self.frame = frame
        self.limit = limit
        self.predictors = ()
        self.fields = ()
        self.categories = frozenset()
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(122)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(120)
        self.table.setMaximumHeight(190)
        self.setFocusProxy(self.table)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.add = QPushButton(ui("Add"))
        self.remove = QPushButton(ui("Remove"))
        self.add.clicked.connect(self.add_profile)
        self.remove.clicked.connect(self.remove_profiles)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        buttons.addWidget(self.add)
        buttons.addWidget(self.remove)
        buttons.addStretch()
        layout.addLayout(buttons)
        self._render(records if isinstance(records, (list, tuple)) else [])

    def _render(self, profiles):
        self.table.clear()
        self.table.setRowCount(0)
        extra = [name for profile in profiles if isinstance(profile, dict)
                 and isinstance(profile.get("Values"), dict) for name in profile["Values"]]
        self.fields = tuple(dict.fromkeys((*self.predictors, *extra)))
        self.table.setColumnCount(len(self.fields) + 1)
        self.table.setHorizontalHeaderLabels([qt("qt.profile_name"), *self.fields])
        levels = {name: categories_of(self.frame, name) for name in self.fields if name in self.categories}
        for profile in profiles:
            self._append(profile, levels)
        self._sync_buttons()

    def _append(self, profile, levels):
        row = self.table.rowCount()
        self.table.insertRow(row)
        record = profile if isinstance(profile, dict) else {}
        values = record.get("Values")
        values = values if isinstance(values, dict) else {}
        self.table.setItem(row, 0, QTableWidgetItem(str(record.get("Name") or "")))
        for col, name in enumerate(self.fields, 1):
            value = values.get(name)
            text = "" if value is None else str(value)
            if name in levels:
                choice = QComboBox()
                choice.setEditable(True)
                choice.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                choice.addItems(["", *levels[name]])
                choice.setCurrentText(text)
                self.table.setCellWidget(row, col, choice)
            else:
                self.table.setItem(row, col, QTableWidgetItem(text))

    def change_predictors(self, predictors, categories):
        records = self.values(parse_numbers=False)
        self.predictors = tuple(predictors)
        self.categories = frozenset(categories)
        self._render(records)

    def _sync_buttons(self):
        self.add.setEnabled(self.table.rowCount() < self.limit)
        self.remove.setEnabled(bool(self.table.selectedIndexes()))

    def add_profile(self):
        if self.table.rowCount() >= self.limit:
            return
        levels = {name: categories_of(self.frame, name) for name in self.fields if name in self.categories}
        self._append({}, levels)
        row = self.table.rowCount() - 1
        self.table.setCurrentCell(row, 0)
        self.table.editItem(self.table.item(row, 0))
        self._sync_buttons()

    def remove_profiles(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self._sync_buttons()

    def values(self, *, parse_numbers=True):
        records = []
        for row in range(self.table.rowCount()):
            values = {}
            for col, name in enumerate(self.fields, 1):
                choice = self.table.cellWidget(row, col)
                text = choice.currentText() if choice is not None else self.table.item(row, col).text()
                if text.strip():
                    values[name] = typed_number(text) if choice is None and parse_numbers else text
            records.append({"Name": self.table.item(row, 0).text().strip(), "Values": values})
        return records


def typed_number(text):
    try:
        return float(decimal_comma(text.strip()))
    except ValueError:
        return text
