"""Arrange native drawings using the display-coordinate engine shared with Standard."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QListWidget, QListWidgetItem, QVBoxLayout)

from analisi.i18n import tr
from analisi.shape_arrange import HORIZONTAL, VERTICAL, ArrangementError, arrange_shapes

from .shapes import describe_shape


class ArrangeShapesDialog(QDialog):
    def __init__(self, parent, axes, records, *, preview):
        super().__init__(parent)
        self.setWindowTitle(tr("arrange.title"))
        self.resize(540, 390)
        self.axes, self.records, self.preview = axes, records, preview
        self.result_records = None
        layout = QVBoxLayout(self)
        hint = QLabel(tr("arrange.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.shapes = QListWidget()
        self.shapes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.shapes.setAccessibleName(tr("shape.title"))
        for index, record in enumerate(records, 1):
            item = QListWidgetItem(f"{index}. " + " · ".join(describe_shape(record)), self.shapes)
            item.setData(Qt.ItemDataRole.UserRole, record["id"])
            item.setToolTip(item.text())
        layout.addWidget(self.shapes, 1)

        form = QFormLayout()
        self.modes = {}
        for key, modes in (("horizontal", HORIZONTAL), ("vertical", VERTICAL)):
            choice = self.modes[key] = QComboBox()
            for mode in modes:
                choice.addItem(tr(f"arrange.option.{mode}"), mode)
            form.addRow(tr(f"arrange.{key}"), choice)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("graph.format.apply"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.addButton(tr("shape.preview"), QDialogButtonBox.ButtonRole.ActionRole).clicked.connect(self.preview_selection)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def candidate(self):
        try:
            records = arrange_shapes(self.axes, self.records,
                                     [item.data(Qt.ItemDataRole.UserRole) for item in self.shapes.selectedItems()],
                                     **{key: choice.currentData() for key, choice in self.modes.items()})
        except ArrangementError as error:
            self.error.setText(tr(f"arrange.error.{error.key}"))
            self.error.show()
            self.modes.get(error.field, self.shapes).setFocus()
            return None
        self.error.hide()
        return records

    def preview_selection(self):
        records = self.candidate()
        if records is not None:
            self.preview(records)

    def accept(self):
        self.result_records = self.candidate()
        if self.result_records is not None:
            super().accept()
