"""Edit the appearance of selected rectangles without changing their values or series."""
from copy import deepcopy

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout)

from analisi.data import decimal_comma
from analisi.grouped_bar_style import MAX_OVERRIDES, PATTERNS, style_key, valid_appearance
from analisi.i18n import tr

from .graph_format import Choice, _color_button
from .theme import fit_dialog


def bar_caption(bar):
    return tr("grouped_bar.choice", row=bar.row + 1, category=bar.category, series=bar.series)


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

        self.colors, self.transparent = {}, {}
        for key in ("fill", "border"):
            label = tr(f"grouped_bar.{key}")
            field = self.colors[key] = QLineEdit()
            field.setAccessibleName(label)
            field.setPlaceholderText(tr("grouped_bar.inherit"))
            clear = self.transparent[key] = QCheckBox(tr("grouped_bar.transparent"))
            clear.setAccessibleName(tr(f"grouped_bar.transparent_{key}"))
            pick = _color_button(field)
            pick.setAccessibleName(label + " · " + pick.text())
            clear.toggled.connect(field.setDisabled)
            clear.toggled.connect(pick.setDisabled)
            row = QHBoxLayout()
            row.addWidget(field, 1)
            row.addWidget(pick)
            row.addWidget(clear)
            form.addRow(label, row)
        self.width = QLineEdit()
        self.width.setPlaceholderText(tr("grouped_bar.inherit"))
        form.addRow(tr("grouped_bar.width"), self.width)
        patterns = ("", *PATTERNS)
        names = {key: f"grouped_bar.pattern.{key}" for key in PATTERNS}
        names[""] = "grouped_bar.inherit"
        self.pattern = Choice(patterns, names)
        form.addRow(tr("grouped_bar.pattern"), self.pattern)

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
        for key, field in self.colors.items():
            value = style.get(key, "")
            self.transparent[key].setChecked(value == "none")
            field.setText("" if value == "none" else value)
        self.width.setText(f"{style['width']:g}" if "width" in style else "")
        self.pattern.set(style.get("pattern", ""))
        self.problem.hide()

    def _store_fields(self):
        bar = self.bars[self.active_index]
        style = {}
        for key, field in self.colors.items():
            if self.transparent[key].isChecked():
                style[key] = "none"
            elif value := field.text().strip().lower():
                style[key] = value
        if value := self.width.text().strip():
            try:
                style["width"] = float(decimal_comma(value)) if "_" not in value else None
            except ValueError:
                style["width"] = None
        if self.pattern.value():
            style["pattern"] = self.pattern.value()
        if style and not valid_appearance(style):
            self.problem.setText(tr("grouped_bar.error"))
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
