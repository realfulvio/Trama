"""Arrange native drawings using the display-coordinate engine shared with Standard."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

from analisi.i18n import tr
from analisi.shape_arrange import HORIZONTAL, VERTICAL, ArrangementError, arrange_shapes
from analisi.shape_objects import edit_objects, is_locked, selected_objects

from .flow import FlowLayout
from .shapes import describe_shape
from .theme import fit_dialog


class ArrangeShapesDialog(QDialog):
    def __init__(self, parent, axes, records, *, preview):
        super().__init__(parent)
        self.setWindowTitle(tr("arrange.title"))
        self.axes, self.records, self.preview = axes, records, preview
        self.result_records = None
        layout = QVBoxLayout(self)
        hint = QLabel(tr("shape.objects.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.shapes = QListWidget()
        self.shapes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.shapes.setAccessibleName(tr("shape.title"))
        layout.addWidget(self.shapes, 1)
        object_buttons = FlowLayout()
        self.object_buttons = {}
        for command in ("group", "ungroup", "lock", "unlock"):
            button = QPushButton(tr(f"shape.objects.{command}"))
            button.clicked.connect(lambda _checked=False, command=command: self.edit_objects(command))
            object_buttons.addWidget(button)
            self.object_buttons[command] = button
        layout.addLayout(object_buttons)
        self.shapes.itemSelectionChanged.connect(self.sync_objects)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.modes = {}
        for key, modes in (("horizontal", HORIZONTAL), ("vertical", VERTICAL)):
            choice = self.modes[key] = QComboBox()
            for mode in modes:
                choice.addItem(tr(f"arrange.option.{mode}"), mode)
            form.addRow(tr(f"arrange.{key}"), choice)
        self.arrange_hint = QLabel(tr("shape.objects.align_hint"))
        self.arrange_hint.setWordWrap(True)
        layout.addWidget(self.arrange_hint)
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
        self.refresh_objects()
        fit_dialog(self, 540, 450)

    def selection(self):
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.shapes.selectedItems()]

    def refresh_objects(self, selected=()):
        self.shapes.blockSignals(True)
        self.shapes.clear()
        group_numbers = {}
        locked_groups = {record.get("group") for record in self.records
                         if record.get("group") and record.get("locked")}
        selected = set(selected)
        for index, record in enumerate(self.records, 1):
            description = list(describe_shape(record))
            group = record.get("group")
            if group:
                number = group_numbers.setdefault(group, len(group_numbers) + 1)
                description.append(tr("shape.objects.group_number", number=number))
            if record.get("locked") or group in locked_groups:
                description.append(tr("shape.objects.locked_label"))
            item = QListWidgetItem(f"{index}. " + " · ".join(description), self.shapes)
            item.setData(Qt.ItemDataRole.UserRole, record["id"])
            item.setToolTip(item.text())
            item.setSelected(record["id"] in selected)
        self.shapes.blockSignals(False)
        self.sync_objects()

    def sync_objects(self):
        objects = selected_objects(self.records, self.selection())
        locked = [is_locked(members) for members in objects]
        self.object_buttons["group"].setEnabled(len(objects) > 1 and not any(locked))
        self.object_buttons["ungroup"].setEnabled(
            any(members[0].get("group") and not lock for members, lock in zip(objects, locked, strict=True))
            and not any(locked))
        self.object_buttons["lock"].setEnabled(bool(objects) and not all(locked))
        self.object_buttons["unlock"].setEnabled(any(locked))

    def edit_objects(self, command):
        ids = [record["id"] for members in selected_objects(self.records, self.selection()) for record in members]
        try:
            self.records = edit_objects(self.records, ids, command)
        except ValueError as error:
            self.error.setText(str(error))
            self.error.show()
            return
        selected = [record["id"] for members in selected_objects(self.records, ids) for record in members]
        self.refresh_objects(selected)
        self.error.hide()
        self.preview(self.records)

    def candidate(self):
        options = {key: choice.currentData() for key, choice in self.modes.items()}
        if all(mode == "none" for mode in options.values()):
            return self.records
        try:
            records = arrange_shapes(self.axes, self.records, self.selection(), **options)
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
