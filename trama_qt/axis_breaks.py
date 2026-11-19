"""Axis breaks of a native XY graph on Qt (same record as ``analisi.axis_breaks``)."""
from copy import deepcopy
from math import isfinite

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from analisi.axis_breaks import DEFAULT_GAP, normalise_axis_breaks, suggest_axis_breaks
from analisi.data import decimal_comma
from analisi.i18n import tr, translate_message

from .graph_format import Choice

AXIS_CHOICES = ("", "x", "y")
AXIS_LABELS = {"": "axis_breaks.axis.none", "x": "axis_breaks.axis.x", "y": "axis_breaks.axis.y"}
COUNT_LABELS = {"2": "axis_breaks.count.2", "3": "axis_breaks.count.3"}
COLUMNS = ("low", "high", "share", "major_step")
ROWS = 3


def translate_breaks_error(error):
    return translate_message(str(error), "axis_breaks.error.")


def breaks_summary(record):
    if not record:
        return tr("axis_breaks.summary_none")
    return tr("axis_breaks.summary", axis=record["axis"].upper(), count=len(record["segments"]))


def _text(value):
    return "" if value is None else f"{value:g}"


def _typed(text, blank=""):
    """The number typed in a field; anything else goes on as text, so the engine names the problem."""
    cleaned = text.strip()
    if not cleaned:
        return blank
    if "_" in cleaned:
        return cleaned
    try:
        value = float(decimal_comma(cleaned))
    except (TypeError, ValueError, OverflowError):
        return cleaned
    return value if isfinite(value) else cleaned


class AxisBreaksDialog(QDialog):
    """``result`` is ``{}`` for no breaks or the canonical record after Apply."""

    def __init__(self, parent, axes, record):
        super().__init__(parent)
        self.setWindowTitle(tr("axis_breaks.title"))
        self.axes, self.result = axes, None
        record = deepcopy(record) or {}
        segments = record.get("segments") or []
        outer = QVBoxLayout(self)
        grid = QGridLayout()
        outer.addLayout(grid)
        self.axis = Choice(AXIS_CHOICES, AXIS_LABELS, record.get("axis", ""))
        grid.addWidget(QLabel(tr("axis_breaks.field.axis")), 0, 0)
        grid.addWidget(self.axis, 0, 1, 1, 2)
        self.count = Choice(("2", "3"), COUNT_LABELS, str(len(segments) if len(segments) in (2, 3) else 3))
        grid.addWidget(QLabel(tr("axis_breaks.field.count")), 1, 0)
        grid.addWidget(self.count, 1, 1, 1, 2)
        self.gap = QLineEdit(_text(record.get("gap", DEFAULT_GAP)))
        grid.addWidget(QLabel(tr("axis_breaks.field.gap")), 2, 0)
        grid.addWidget(self.gap, 2, 1)
        hint = QLabel(tr("axis_breaks.hint.gap"))
        hint.setObjectName("muted")
        grid.addWidget(hint, 2, 2, 1, 3)
        for column, name in enumerate(COLUMNS, start=1):
            grid.addWidget(QLabel(tr(f"axis_breaks.col.{name}")), 3, column)
        self.cells = {}
        for row in range(ROWS):
            grid.addWidget(QLabel(tr("axis_breaks.row", row=row + 1)), 4 + row, 0)
            segment = segments[row] if row < len(segments) else {}
            for column, name in enumerate(COLUMNS, start=1):
                cell = self.cells[(row, name)] = QLineEdit(_text(segment.get(name)))
                cell.textChanged.connect(self._total)
                grid.addWidget(cell, 4 + row, column)
        self.total = QLabel()
        outer.addWidget(self.total)
        line = QHBoxLayout()
        self.suggest_button = QPushButton(tr("axis_breaks.btn.suggest"))
        self.suggest_button.clicked.connect(self.suggest)
        line.addWidget(self.suggest_button)
        line.addStretch(1)
        outer.addLayout(line)
        for key in ("axis_breaks.note.scale", "axis_breaks.note.limits", "axis_breaks.note.numbers"):
            note = QLabel(tr(key))
            note.setObjectName("muted")
            note.setWordWrap(True)
            outer.addWidget(note)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("axis_breaks.btn.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("axis_breaks.btn.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.axis.currentIndexChanged.connect(self._axis_changed)
        self.count.currentIndexChanged.connect(self._count_changed)
        self._states()
        self.resize(620, 460)

    def rows(self):
        return int(self.count.value())

    def _states(self):
        on = bool(self.axis.value())
        for widget in (self.count, self.gap, self.suggest_button):
            widget.setEnabled(on)
        for (row, _name), cell in self.cells.items():
            cell.setEnabled(on and row < self.rows())
        self._total()

    def _total(self, *_):
        try:
            shares = [float(decimal_comma(self.cells[(row, "share")].text().strip())) for row in range(self.rows())]
        except ValueError:
            self.total.setText("")
            return
        self.total.setText(tr("axis_breaks.total", total=f"{sum(shares):g}"))

    def _fill(self, record):
        for row in range(ROWS):
            segment = record["segments"][row] if row < len(record["segments"]) else {}
            for name in COLUMNS:
                self.cells[(row, name)].setText(_text(segment.get(name)))
        self.gap.setText(_text(record["gap"]))

    def suggest(self):
        axis = self.axis.value()
        record = suggest_axis_breaks(self.axes, axis, self.rows()) if axis else None
        if record is None:
            self._show(tr("axis_breaks.error.no_suggestion"))
            return
        self.problem.setVisible(False)
        self._fill(record)

    def _axis_changed(self, *_):
        self._states()
        if self.axis.value():
            record = suggest_axis_breaks(self.axes, self.axis.value(), self.rows())
            if record is not None:
                self._fill(record)

    def _count_changed(self, *_):
        self._states()
        blank = any(not self.cells[(row, name)].text().strip()
                    for row in range(self.rows()) for name in ("low", "high", "share"))
        if self.axis.value() and blank:
            self.suggest()

    def read_record(self):
        axis = self.axis.value()
        if not axis:
            return {}
        segments = []
        for row in range(self.rows()):
            segment = {name: _typed(self.cells[(row, name)].text()) for name in ("low", "high", "share")}
            segment["major_step"] = _typed(self.cells[(row, "major_step")].text(), blank=None)
            segments.append(segment)
        return normalise_axis_breaks({"axis": axis, "gap": _typed(self.gap.text()), "segments": segments})

    def _show(self, text):
        self.problem.setText(text)
        self.problem.setVisible(True)

    def accept(self):
        try:
            self.result = self.read_record()
        except ValueError as error:
            self.result = None
            self._show(translate_breaks_error(error))
            return
        super().accept()
