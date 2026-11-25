"""Variable properties for an editable multiple-variables worksheet."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from analisi.i18n import tr
from analisi.variable_types import TYPES, VARIABLE_TYPES, inferred_type


class VariablesDialog(QDialog):
    def __init__(self, parent, dataset, apply, *, column=-1):
        super().__init__(parent)
        self.setWindowTitle(tr("variables.title"))
        self.dataset, self.apply = dataset, apply
        self.affected = None
        self.resize(550, 385)
        outer = QVBoxLayout(self)
        self.table = QTableWidget(len(dataset.columns), 3)
        self.table.setHorizontalHeaderLabels([tr(f"variables.{key}") for key in ("name", "type", "observed")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAccessibleName(tr("variables.title"))
        self.table.setTabKeyNavigation(True)
        self.types = {}
        stored = dataset.raw.attrs.get(VARIABLE_TYPES, {})
        for row, name in enumerate(dataset.columns):
            label = QTableWidgetItem(str(name))
            self.table.setItem(row, 0, label)
            if name in dataset.formulas:
                label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 1, self._readonly(tr("variables.calculated")))
                continue
            choice = QComboBox()
            choice.setAccessibleName(f'{tr("variables.type")} · {name}')
            for kind in ("auto", *TYPES):
                choice.addItem(tr(f"variables.{kind}"), kind)
            choice.setCurrentIndex(choice.findData(stored.get(name, "auto")))
            self.table.setCellWidget(row, 1, choice)
            self.types[row] = choice
            series = dataset.raw[name]
            detected = tr(f"variables.{inferred_type(series)}")
            if choice.currentData() == "categorical":
                detected = tr("variables.levels", count=series.nunique())
            self.table.setItem(row, 2, self._readonly(detected))
        if 0 <= column < len(dataset.columns):
            self.table.setCurrentCell(column, 0)
        outer.addWidget(self.table, 1)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    @staticmethod
    def _readonly(text):
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def accept(self):
        changes = {self.dataset.columns[row]: (self.table.item(row, 0).text(), choice.currentData())
                   for row, choice in self.types.items()}
        try:
            self.affected = self.apply(changes)
        except (ValueError, TypeError, OverflowError) as error:
            self.problem.setText(str(error))
            self.problem.show()
            return
        super().accept()
