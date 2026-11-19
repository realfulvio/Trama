"""Text and arrow annotations of a graph on Qt (same records as ``analisi.graph_annotations``)."""
from copy import deepcopy

from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from analisi.data import decimal_comma
from analisi.graph_annotations import ALIGNMENTS, UNITS, on_axis_domain, validate_annotation
from analisi.i18n import tr, translate_message

from .graph_format import Choice, _color_button


def _pair(values):
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    fields = tuple(QLineEdit(f"{value:g}") for value in values)
    for field in fields:
        line.addWidget(field)
    return row, fields


class AnnotationEditor(QDialog):
    def __init__(self, parent, axes, record=None):
        super().__init__(parent)
        self.setWindowTitle(tr("annotation.edit") if record is not None else tr("annotation.add"))
        self.axes, self.result = axes, None
        record = record or {"text": "", "units": "axes", "position": [.08, .9], "size": 11, "color": "#174e78",
                            "align": "left"}
        form = QFormLayout(self)
        self.text = QPlainTextEdit(record["text"])
        self.text.setMaximumHeight(90)
        form.addRow(tr("annotation.text"), self.text)
        self.units = Choice(UNITS, {option: f"annotation.option.{option}" for option in UNITS}, record["units"])
        form.addRow(tr("annotation.units"), self.units)
        self.align = Choice(ALIGNMENTS, {option: f"annotation.option.{option}" for option in ALIGNMENTS},
                            record["align"])
        form.addRow(tr("annotation.align"), self.align)
        row, self.position = _pair(record["position"])
        form.addRow(tr("annotation.position"), row)
        self.arrow = QCheckBox(tr("annotation.arrow"))
        self.arrow.setChecked("target" in record)
        form.addRow(self.arrow)
        self.target_row, self.target = _pair(record.get("target", (.5, .5)))
        form.addRow(tr("annotation.target"), self.target_row)
        self.arrow.toggled.connect(self._arrow)
        self.size = QLineEdit(f"{record['size']:g}")
        form.addRow(tr("annotation.size"), self.size)
        self.color = QLineEdit(record["color"])
        color = QWidget()
        line = QHBoxLayout(color)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.color, 1)
        line.addWidget(_color_button(self.color))
        form.addRow(tr("annotation.color"), color)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        form.addRow(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("language.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._arrow()

    def _arrow(self, *_):
        self.target_row.setVisible(self.arrow.isChecked())
        label = self.layout().labelForField(self.target_row)
        if label is not None:
            label.setVisible(self.arrow.isChecked())

    def _show(self, text):
        self.problem.setText(text)
        self.problem.setVisible(True)

    def accept(self):
        def values(fields):
            return [float(decimal_comma(field.text())) for field in fields]

        try:
            record = {"text": self.text.toPlainText(), "units": self.units.value(), "position": values(self.position),
                      "align": self.align.value(), "size": float(decimal_comma(self.size.text())),
                      "color": self.color.text().strip()}
            if self.arrow.isChecked():
                record["target"] = values(self.target)
        except ValueError:
            self._show(tr("annotation.invalid_fields"))
            return
        try:
            validate_annotation(record)
            if not on_axis_domain(self.axes, record):
                raise ValueError(tr("annotation.axis_domain"))
        except ValueError as error:
            self._show(translate_message(error, "annotation.error."))
            return
        self.result = record
        super().accept()


class GraphAnnotationsDialog(QDialog):
    """``result`` is the new list of records after Apply."""

    def __init__(self, parent, axes, records):
        super().__init__(parent)
        self.setWindowTitle(tr("annotation.title"))
        self.axes, self.records, self.result = axes, deepcopy(records), None
        outer = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("annotation.text"), tr("annotation.position"),
                                              tr("annotation.arrow_short")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit())
        self.table.itemSelectionChanged.connect(self._buttons)
        outer.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton(tr("annotation.add"))
        add.clicked.connect(self.add)
        self.edit_button = QPushButton(tr("annotation.edit"))
        self.edit_button.clicked.connect(self.edit)
        self.remove_button = QPushButton(tr("annotation.remove"))
        self.remove_button.clicked.connect(self.remove)
        for button in (add, self.edit_button, self.remove_button):
            row.addWidget(button)
        row.addStretch(1)
        outer.addLayout(row)
        buttons = QDialogButtonBox()
        buttons.addButton(tr("graph.format.apply"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(tr("setup.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.fill()
        self.resize(560, 380)

    def fill(self, selected=None):
        self.table.setRowCount(len(self.records))
        for index, record in enumerate(self.records):
            x, y = record["position"]
            first = record["text"].strip().splitlines()[0][:120] if record["text"].strip() else ""
            for column, text in enumerate((first, f"{x:g}, {y:g}", "→" if "target" in record else "")):
                self.table.setItem(index, column, QTableWidgetItem(text))
        if selected is not None and self.records:
            self.table.selectRow(min(selected, len(self.records) - 1))
        self._buttons()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _buttons(self):
        chosen = self._selected() is not None
        self.edit_button.setEnabled(chosen)
        self.remove_button.setEnabled(chosen)

    def add(self):
        dialog = AnnotationEditor(self, self.axes)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.records.append(dialog.result)
            self.fill(len(self.records) - 1)

    def edit(self):
        index = self._selected()
        if index is None:
            return
        dialog = AnnotationEditor(self, self.axes, self.records[index])
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.records[index] = dialog.result
            self.fill(index)

    def remove(self):
        index = self._selected()
        if index is not None:
            del self.records[index]
            self.fill(index)

    def accept(self):
        self.result = self.records
        super().accept()
