"""Edit the curves and coefficients of a function on Qt."""
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from analisi import plot_function as pf
from analisi.curve_models import MODELS
from analisi.data import decimal_comma
from analisi.field_error import FieldError
from analisi.i18n import tr

from .strings import qt


class FunctionCurves(QWidget):
    def __init__(self, model, records):
        super().__init__()
        self.parameters = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(155)
        self.setFocusProxy(self.table)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.add_button = QPushButton(tr("shape.add"))
        self.add_button.clicked.connect(self.add)
        self.remove_button = QPushButton(tr("shape.remove"))
        self.remove_button.clicked.connect(self.remove)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch()
        layout.addLayout(row)
        self.table.itemSelectionChanged.connect(self.sync)
        self.set_model(model, records)

    def records(self):
        def text(row, column):
            return self.table.item(row, column).text().strip()

        return [{"name": text(row, 0),
                 "parameters": {key: text(row, col) for col, key in enumerate(self.parameters, 1)}}
                for row in range(self.table.rowCount())]

    def set_model(self, model, records=None):
        records = self.records() if records is None else records
        self.parameters = MODELS[model].parameters
        self.table.setRowCount(0)
        self.table.setColumnCount(len(self.parameters) + 1)
        self.table.setHorizontalHeaderLabels([qt("qt.function_curve_name"), *self.parameters])
        for record in records:
            self.add_row(record)
        self.sync()

    def add_row(self, record):
        row = self.table.rowCount()
        self.table.insertRow(row)
        params = record.get("parameters") or {}
        for column, value in enumerate([record.get("name", ""), *(params.get(key, "") for key in self.parameters)]):
            self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def add(self):
        if self.table.rowCount() < pf.MAX_CURVES:
            self.add_row({})
            row = self.table.rowCount() - 1
            self.table.setCurrentCell(row, 0)
            self.table.editItem(self.table.item(row, 0))
            self.sync()

    def remove(self):
        for row in sorted({item.row() for item in self.table.selectedItems()}, reverse=True):
            self.table.removeRow(row)
        self.sync()

    def sync(self):
        self.add_button.setEnabled(self.table.rowCount() < pf.MAX_CURVES)
        self.remove_button.setEnabled(bool(self.table.selectedItems()))

    def values(self):
        records = self.records()
        for row, record in enumerate(records):
            for column, (name, value) in enumerate(record["parameters"].items(), 1):
                try:
                    record["parameters"][name] = float(decimal_comma(value))
                except ValueError:
                    self.table.setCurrentCell(row, column)
                    raise FieldError(pf.CURVES, qt("qt.function_curve_number", number=row + 1, name=name)) from None
        return records
