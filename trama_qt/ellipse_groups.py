"""Edit confidence ellipse overrides for the observed groups in a worksheet."""

from collections import Counter
from copy import deepcopy

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout)

from analisi.data import decimal_comma
from analisi.ellipse_workbench import (BY_GROUP, DEFAULT_COLOR, GROUP_BORDER_FIELDS, GROUP_FILL_FIELDS,
                                      GROUP_STYLES, LINE_PATTERNS, ellipse_grouping_column,
                                      ellipse_visibility, normalize_ellipse_group_styles)
from analisi.field_error import FieldError
from analisi.graph_legend import typed_group_token
from analisi.i18n import ui
from .labels import choice_label

METHOD = "Scatter / confidence ellipse"
CHOICES = ("Group", "Ellipse grouping", "Ellipse group", "Ellipse", "Fill", "Border", "Center marker")


class GroupDialog(QDialog):
    def __init__(self, parent, series, options, styles):
        super().__init__(parent)
        self.column = str(series.name)
        self.styles = normalize_ellipse_group_styles(styles)
        self.setWindowTitle(ui(GROUP_STYLES))
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(ui("Empty fields inherit the graph style.")))
        form = QFormLayout()
        outer.addLayout(form)
        self.groups = QComboBox()
        form.addRow(ui("Group"), self.groups)
        levels = [(str(v), typed_group_token(v)) for v in series.dropna().unique()]
        labels = Counter(name for name, _ in levels)
        for name, token in levels:
            if labels[name] > 1:
                kind = ui("Text") if token.startswith("str:") else ui("Number")
                name = f"{name} ({kind})"
            self.groups.addItem(name, token)

        self.fields = {}
        fill = GROUP_FILL_FIELDS if options["Fill"] == BY_GROUP else ()
        border = GROUP_BORDER_FIELDS if options["Border"] == BY_GROUP else ()
        for field in fill + border:
            if field == "Border style":
                widget = QComboBox()
                for value in ("", *LINE_PATTERNS):
                    widget.addItem(choice_label(value), value)
            else:
                widget = QLineEdit()
            self.fields[field] = widget
            if field in ("Fill color", "Border color"):
                row = QHBoxLayout()
                pick = QPushButton(ui("Choose color…"))
                pick.clicked.connect(lambda _=False, edit=widget: self.pick_color(edit))
                row.addWidget(widget)
                row.addWidget(pick)
                form.addRow(ui(field), row)
            else:
                form.addRow(ui(field), widget)

        self.error = QLabel()
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(ui("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.groups.currentIndexChanged.connect(self.switch)
        self.load_group(0)

    def pick_color(self, edit):
        color = QColorDialog.getColor(QColor(edit.text() or DEFAULT_COLOR), self)
        if color.isValid():
            edit.setText(color.name())

    def load_group(self, index):
        self.index = index
        record = self.styles.get(self.column, {}).get(self.groups.itemData(index), {})
        for field, edit in self.fields.items():
            value = record.get(field, "")
            if isinstance(edit, QComboBox):
                edit.setCurrentIndex(edit.findData(value))
            else:
                edit.setText(str(value))

    def store_group(self):
        token = self.groups.itemData(self.index)
        groups = self.styles.get(self.column, {})
        record = dict(groups.get(token, {}))
        for field, edit in self.fields.items():
            record.pop(field, None)
            value = edit.currentData() if isinstance(edit, QComboBox) else edit.text().strip()
            if value:
                record[field] = decimal_comma(value) if field in ("Fill opacity (%)", "Border opacity (%)",
                                                                  "Border width") else value
        try:
            self.styles = normalize_ellipse_group_styles({**self.styles, self.column: {**groups, token: record}})
        except FieldError as error:
            self.error.setText(ui(str(error)))
            self.fields.get(error.field, self.groups).setFocus()
            return False
        self.error.clear()
        return True

    def switch(self, index):
        if self.store_group():
            self.load_group(index)
        else:
            with QSignalBlocker(self.groups):
                self.groups.setCurrentIndex(self.index)

    def accept(self):
        if self.store_group():
            super().accept()


class GroupEditor(QPushButton):
    def __init__(self, dialog, saved):
        super().__init__(ui("Edit group styles…"), dialog)
        self.dialog = dialog
        self.styles = deepcopy(saved.get(GROUP_STYLES, {}))
        self.clicked.connect(self.edit)

    def choices(self):
        return {name: self.dialog.controls[name][1].currentData() for name in CHOICES}

    def sync(self):
        options = self.choices()
        column = ellipse_grouping_column(options)
        fields = ellipse_visibility(options)
        fields[GROUP_STYLES] = (options["Ellipse"] != "None" and column in self.dialog.data
                                and BY_GROUP in (options["Fill"], options["Border"]))
        self.dialog._set_field_visibility(fields)

    def edit(self):
        options = self.choices()
        series = self.dialog.data[ellipse_grouping_column(options)]
        if not series.notna().any():
            self.dialog.show_error(ui("The grouping column has no observed values."), GROUP_STYLES)
            return
        try:
            editor = GroupDialog(self, series, options, self.styles)
        except FieldError as error:
            self.dialog.show_error(error, GROUP_STYLES)
            return
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.styles = editor.styles
