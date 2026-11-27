"""Edit the appearance of selected rectangles without changing their values or series."""
from copy import deepcopy

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from analisi.data import decimal_comma
from analisi.grouped_bar_style import MAX_OVERRIDES, PATTERNS, style_key, valid_appearance
from analisi.i18n import tr

from .graph_format import Choice, _color_button
from .theme import classic_icon, fit_dialog


def bar_caption(bar):
    return tr("grouped_bar.choice", row=bar.row + 1, category=bar.category, series=bar.series)


class BarAppearanceFields(QWidget):
    """Fields shared by per-series and per-observation formatting."""
    def __init__(self):
        super().__init__()
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.colors, self.transparent = {}, {}
        for key in ("fill", "border", "pattern_color"):
            label = tr(f"grouped_bar.{key}")
            field = self.colors[key] = QLineEdit()
            field.setAccessibleName(label)
            field.setPlaceholderText(tr("grouped_bar.inherit"))
            field.setMinimumWidth(75)
            clear = self.transparent[key] = QCheckBox(tr("grouped_bar.transparent"))
            clear.setAccessibleName(tr(f"grouped_bar.transparent_{key}"))
            pick = _color_button(field)
            description = label + " · " + pick.text()
            pick.setAccessibleName(description)
            pick.setToolTip(description)
            pick.setIcon(classic_icon("palette"))
            pick.setText("")
            pick.setFixedWidth(32)
            clear.toggled.connect(field.setDisabled)
            clear.toggled.connect(pick.setDisabled)
            row = QHBoxLayout()
            row.addWidget(field, 1)
            row.addWidget(pick)
            row.addWidget(clear)
            if key == "pattern_color":
                pattern_color_row = row
            else:
                form.addRow(label, row)
        self.width = QLineEdit()
        self.width.setPlaceholderText(tr("grouped_bar.inherit"))
        form.addRow(tr("grouped_bar.width"), self.width)
        patterns = ("", *PATTERNS)
        names = {key: f"grouped_bar.pattern.{key}" for key in PATTERNS}
        names[""] = "grouped_bar.inherit"
        self.pattern = Choice(patterns, names)
        form.addRow(tr("grouped_bar.pattern"), self.pattern)
        form.addRow(tr("grouped_bar.pattern_color"), pattern_color_row)

    def set_appearance(self, style):
        for key, field in self.colors.items():
            value = style.get(key, "")
            self.transparent[key].setChecked(value == "none")
            field.setText("" if value == "none" else value)
        width = style.get("width", "")
        self.width.setText(f"{width:g}" if isinstance(width, (int, float)) else str(width))
        self.pattern.set(style.get("pattern", ""))

    def draft(self):
        style = {}
        for key, field in self.colors.items():
            if self.transparent[key].isChecked():
                style[key] = "none"
            elif value := field.text().strip().lower():
                style[key] = value
        if value := self.width.text().strip():
            style["width"] = value
        if self.pattern.value():
            style["pattern"] = self.pattern.value()
        return style


def validate_appearance(draft):
    style = dict(draft)
    if "width" in style and isinstance(style["width"], str):
        text = style["width"]
        try:
            style["width"] = float(decimal_comma(text)) if "_" not in text else None
        except ValueError:
            style["width"] = None
    if style and not valid_appearance(style):
        raise ValueError(tr("grouped_bar.error"))
    return style


class GroupedBarEditor(QDialog):
    def __init__(self, parent, bars, previous, preview, *, target=None):
        super().__init__(parent)
        self.setObjectName("groupedBarEditor")
        self.setWindowTitle(tr("grouped_bar.title"))
        self.bars = sorted(bars, key=lambda bar: bar.row)
        self.records = {style_key(record): deepcopy(record) for record in previous}
        self.preview = preview
        self.result = None
        self.active_index = next((index for index, bar in enumerate(self.bars) if bar.key == target), 0)

        outer = QVBoxLayout(self)
        form = QFormLayout()
        outer.addLayout(form)
        self.target = QComboBox()
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.setMinimumContentsLength(25)
        for bar in self.bars:
            self.target.addItem(bar_caption(bar))
        form.addRow(tr("grouped_bar.bar"), self.target)
        self.target.setCurrentIndex(self.active_index)
        self.fields = BarAppearanceFields()
        outer.addWidget(self.fields)

        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox()
        reset = buttons.addButton(tr("grouped_bar.reset"), QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(self.reset_fields)
        preview_button = buttons.addButton(tr("axis_guides.btn.preview"), QDialogButtonBox.ButtonRole.ActionRole)
        preview_button.clicked.connect(self._preview)
        apply = buttons.addButton(tr("axis_guides.btn.apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(tr("axis_guides.btn.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        apply.setAutoDefault(True)
        apply.setDefault(True)
        if hasattr(parent, "show_shortcuts"):
            QShortcut(QKeySequence("F1"), self, parent.show_shortcuts)
        self._load_fields()
        self.target.currentIndexChanged.connect(self._choose)
        self.target.setFocus()
        fit_dialog(self, 520, self.sizeHint().height())

    def _load_fields(self):
        style = self.records.get(self.bars[self.active_index].key, {}).get("style", {})
        self.fields.set_appearance(style)
        self.problem.hide()

    def _store_fields(self):
        bar = self.bars[self.active_index]
        try:
            style = validate_appearance(self.fields.draft())
        except ValueError as error:
            self.problem.setText(str(error))
            self.problem.show()
            return False
        if style and bar.key not in self.records and len(self.records) >= MAX_OVERRIDES:
            self.problem.setText(tr("grouped_bar.limit", count=MAX_OVERRIDES))
            self.problem.show()
            return False
        if style:
            self.records[bar.key] = bar.record(style)
        else:
            self.records.pop(bar.key, None)
        self.problem.hide()
        return True

    def _choose(self, index):
        if not self._store_fields():
            with QSignalBlocker(self.target):
                self.target.setCurrentIndex(self.active_index)
            return
        self.active_index = index
        self._load_fields()

    def reset_fields(self):
        self.records.pop(self.bars[self.active_index].key, None)
        self._load_fields()

    def _preview(self):
        if self._store_fields():
            self.preview(list(self.records.values()))

    def accept(self):
        if self._store_fields():
            self.result = list(self.records.values())
            super().accept()
