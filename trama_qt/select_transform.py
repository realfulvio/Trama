"""Qt editors for the ordered output, row filters, and formulas of Select and Transform."""
from copy import deepcopy
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPlainTextEdit, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from analisi.i18n import tr, ui
from analisi.select_transform import CALCULATED, COMPARISONS, FILTERS, MAX_RULES, MISSING, SELECT_TRANSFORM, TARGETS

from .labels import field_label
from .reshape_long_wide import OrderedColumns
from .strings import qt

EDITOR = "Select and Transform editor"
_NUMBERED_ERROR = re.compile(r"^(Condition|Calculated variable) (\d+):\s*(.*)", re.DOTALL)


def message(error):
    text = str(error)
    if match := _NUMBERED_ERROR.match(text):
        label = ui(match[1])
        return f"{label} {match[2]}: {ui(match[3])}"
    name, separator, detail = text.partition('": ')
    if separator and name.startswith('"'):
        prefix = "Unknown column: "
        if detail.startswith(prefix):
            detail = ui(prefix.rstrip()) + " " + detail[len(prefix):]
        return f'{name}": {ui(detail)}'
    return ui(text)


def _combo(choices, caption, *, translate=False):
    combo = QComboBox()
    combo.setAccessibleName(ui(caption))
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(10)
    for value in choices:
        combo.addItem(ui(value) if translate else value, value)
    return combo


def _pick(combo, value):
    index = combo.findData(value)
    if index < 0:
        combo.addItem(value or qt("qt.none"), value)
        index = combo.count() - 1
    combo.setCurrentIndex(index)


class RecordEditor(QWidget):
    """Select and edit one ordered record at a time without changing the saved recipe."""

    edited = Signal()

    def __init__(self, saved, hint):
        super().__init__()
        self.records = [dict(record) if isinstance(record, dict) else {} for record in saved] if isinstance(saved, list) else []
        self.loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        note = QLabel(ui(hint))
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(note)
        self.list = QListWidget()
        self.list.setFixedHeight(108)
        self.list.currentRowChanged.connect(self.load)
        outer.addWidget(self.list)
        buttons = QHBoxLayout()
        self.add_button = QPushButton(ui("Add"))
        self.remove_button = QPushButton(ui("Remove"))
        self.up = QPushButton(tr("layout.up"))
        self.down = QPushButton(tr("layout.down"))
        for button, callback in ((self.add_button, self.add), (self.remove_button, self.remove),
                                 (self.up, lambda: self.move(-1)), (self.down, lambda: self.move(1))):
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        outer.addLayout(buttons)
        self.detail = QWidget()
        self.form = QFormLayout(self.detail)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addWidget(self.detail)
        outer.addStretch()

    def reload(self, row=0):
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems([self.summary(record) for record in self.records])
        row = min(row, len(self.records) - 1)
        self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        self.load(row)

    def load(self, row):
        self.loading = True
        try:
            self.write(self.records[row] if row >= 0 else {})
        finally:
            self.loading = False
        self.detail.setEnabled(row >= 0)
        self.add_button.setEnabled(len(self.records) < MAX_RULES)
        self.remove_button.setEnabled(row >= 0)
        self.up.setEnabled(row > 0)
        self.down.setEnabled(0 <= row < len(self.records) - 1)

    def changed(self, *_):
        row = self.list.currentRow()
        if not self.loading and row >= 0:
            self.records[row] = self.read()
            self.list.item(row).setText(self.summary(self.records[row]))
            self.edited.emit()

    def add(self):
        if len(self.records) < MAX_RULES:
            self.records.append(self.default())
            self.reload(len(self.records) - 1)
            self.first.setFocus()
            self.edited.emit()

    def remove(self):
        row = self.list.currentRow()
        if row >= 0:
            self.records.pop(row)
            self.reload(row)
            self.edited.emit()

    def move(self, step):
        row = self.list.currentRow()
        if row >= 0 and 0 <= row + step < len(self.records):
            self.records.insert(row + step, self.records.pop(row))
            self.reload(row + step)
            self.edited.emit()

    def values(self):
        return deepcopy(self.records)

    def focus_problem(self, error):
        match = _NUMBERED_ERROR.match(str(error))
        row = int(match[2]) - 1 if match else self.error_row(str(error))
        if 0 <= row < len(self.records):
            self.list.setCurrentRow(row)
        if self.list.currentRow() < 0:
            self.add_button.setFocus()
        else:
            self.error_control(str(error)).setFocus()
        return True

    def error_row(self, _error):
        return self.list.currentRow()


class FilterEditor(RecordEditor):
    def __init__(self, columns, numeric, saved):
        super().__init__(saved, "Rows must satisfy all the filters. Leave the list empty to use the row range.")
        self.columns, self.numeric = columns, numeric
        self.list.setAccessibleName(ui(FILTERS))
        self.first = self.column = _combo(columns, "Variable")
        self.operator = _combo((*COMPARISONS, *MISSING), "Condition", translate=True)
        self.target = _combo(TARGETS, "Compare to", translate=True)
        self.value = QLineEdit()
        self.value.setAccessibleName(ui("Value"))
        self.other_column = _combo(columns, "Comparison variable")
        self.input = QStackedWidget()
        self.input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.input.addWidget(self.value)
        self.input.addWidget(self.other_column)
        for title, control in (("Variable", self.column), ("Condition", self.operator), ("Compare to", self.target),
                               ("Value", self.input)):
            self.form.addRow(ui(title), control)
        for combo in (self.column, self.operator, self.target, self.other_column):
            combo.currentIndexChanged.connect(self.sync)
        self.value.textChanged.connect(self.changed)
        self.reload()

    def default(self):
        column = next(iter(self.numeric), self.columns[0] if self.columns else "")
        return {"column": column, "operator": "=", "target": "Number" if column in self.numeric else "Text",
                "value": ""}

    def summary(self, record):
        operator = record.get("operator", "")
        cells = [record.get("column", ""), ui(operator)]
        if operator not in MISSING:
            cells.append(record.get("value", ""))
        return "  ".join(str(cell) for cell in cells if cell) or ui("New filter")

    def sync(self, *_):
        missing = self.operator.currentData() in MISSING
        self.target.setEnabled(not missing)
        self.input.setEnabled(not missing)
        self.input.setCurrentWidget(self.other_column if self.target.currentData() == "Column" else self.value)
        self.changed()

    def write(self, record):
        for control, key, fallback in ((self.column, "column", ""), (self.operator, "operator", "="),
                                       (self.target, "target", "Number")):
            _pick(control, str(record.get(key, fallback)))
        self.value.setText(str(record.get("value", "")) if self.target.currentData() != "Column" else "")
        _pick(self.other_column, str(record.get("value", "")) if self.target.currentData() == "Column" else "")
        self.sync()

    def read(self):
        target = self.target.currentData()
        return {"column": self.column.currentData(), "operator": self.operator.currentData(), "target": target,
                "value": self.other_column.currentData() if target == "Column" else self.value.text()}

    def error_control(self, error):
        if "number." in error or "floating-point range." in error:
            return self.value
        if "same type" in error:
            return self.other_column
        if "text comparisons" in error:
            return self.operator
        return self.column


class FormulaEditor(RecordEditor):
    def __init__(self, saved):
        super().__init__(saved, "Formulas use the selected rows and run from top to bottom.")
        self.list.setAccessibleName(ui(CALCULATED))
        self.first = self.name = QLineEdit()
        self.name.setAccessibleName(ui("New variable"))
        self.expression = QPlainTextEdit()
        self.expression.setAccessibleName(ui("Formula"))
        self.expression.setPlaceholderText('COL("X") / 2')
        self.expression.setTabChangesFocus(True)
        self.expression.setFixedHeight(100)
        self.form.addRow(ui("New variable"), self.name)
        self.form.addRow(ui("Formula"), self.expression)
        self.name.textChanged.connect(self.changed)
        self.expression.textChanged.connect(self.changed)
        self.reload()

    def default(self):
        return {"name": "", "expression": ""}

    def summary(self, record):
        name = record.get("name") or ui("New variable")
        expression = " ".join(str(record.get("expression", "")).splitlines())
        return f"{name}   {expression}".strip()

    def write(self, record):
        self.name.setText(str(record.get("name", "")))
        self.expression.setPlainText(str(record.get("expression", "")))

    def read(self):
        return {"name": self.name.text(), "expression": self.expression.toPlainText()}

    def error_row(self, error):
        for row, record in enumerate(self.records):
            if error.startswith(f'"{str(record.get("name", "")).strip()}":'):
                return row
        return super().error_row(error)

    def error_control(self, error):
        return self.name if "enter a name" in error or "already exists" in error else self.expression


def pages(method):
    if method == SELECT_TRANSFORM:
        return (("select_filters", ui(FILTERS)), ("select_formulas", ui(CALCULATED)))
    return ()


def attach(dialog, forms, saved):
    if dialog.method != SELECT_TRANSFORM:
        return
    columns = list(map(str, dialog.data.columns))
    numeric = list(map(str, dialog.data.select_dtypes(include="number").columns))
    output = saved.get("Variables", columns)
    output = output if isinstance(output, list) else []
    offered = list(dict.fromkeys([*columns, *(name for name in output if isinstance(name, str))]))
    variables = OrderedColumns(offered, output, "selectTransformOutput")
    variables.list.setAccessibleName(field_label("Variables"))
    entries = [("variables", "Variables", EDITOR, variables)]

    for key in ("First row", "Last row"):
        value = QLineEdit(str(saved.get(key) or ""))
        entries.append(("select_filters", key, "Text", value))
    entries.extend((("select_filters", FILTERS, EDITOR, FilterEditor(columns, numeric, saved.get(FILTERS, []))),
                    ("select_formulas", CALCULATED, EDITOR, FormulaEditor(saved.get(CALCULATED, [])))))
    for page, name, kind, control in entries:
        form = forms[page]
        caption = QLabel(field_label(name))
        caption.setWordWrap(True)
        if name in {FILTERS, CALCULATED}:
            form.addRow(control)
            control.edited.connect(lambda field=name: dialog.clear_field_error(field))
        else:
            form.addRow(caption, control)
            if kind == "Text":
                control.textChanged.connect(lambda _text, field=name: dialog.clear_field_error(field))
        dialog.controls[name] = (kind, control)
        dialog.rows[name] = (caption, control, form)
