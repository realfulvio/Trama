"""Axis breaks of a native XY graph on Qt (same record as ``analisi.axis_breaks``)."""
from copy import deepcopy
from math import isfinite

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from analisi.axis_breaks import (AxisBreakError, DEFAULT_GAP, M_NONNEGATIVE, is_survival_axes, normalise_axis_breaks,
                                 suggest_axis_breaks)
from analisi.data import decimal_comma
from analisi.i18n import tr, translate_message

from .graph_format import Choice
from .theme import fit_dialog

AXIS_CHOICES = ("", "x", "y")
AXIS_LABELS = {"": "axis_breaks.axis.none", "x": "axis_breaks.axis.x", "y": "axis_breaks.axis.y"}
COUNT_LABELS = {"2": "axis_breaks.count.2", "3": "axis_breaks.count.3"}
COLUMNS = ("low", "high", "share", "major_step", "major_origin", "minor_ticks")
ROWS = 3


def translate_breaks_error(error):
    return translate_message(str(error), "axis_breaks.error.")


def breaks_summary(record):
    if not record:
        return tr("axis_breaks.summary_none")
    return tr("axis_breaks.summary", axis=record["axis"].upper(), count=len(record["segments"]))


def _text(value):
    return "" if value is None else str(value)


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

    def __init__(self, parent, axes, record, *, preview=None, busy=None):
        super().__init__(parent)
        self.setWindowTitle(tr("axis_breaks.title"))
        self.axes, self.result = axes, None
        self._preview, self._busy_check = preview, busy
        self._previewed = self._accepted = False
        self.survival = is_survival_axes(axes)
        self.record = record = deepcopy(record) or {}
        segments = record.get("segments") or []
        outer = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 4, 0)
        grid = QGridLayout()
        body.addLayout(grid)
        axis_choices = ("", "x") if self.survival else AXIS_CHOICES
        current_axis = record.get("axis", "") if record.get("axis", "") in axis_choices else ""
        self.axis = Choice(axis_choices, AXIS_LABELS, current_axis)
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
            caption = "major_step_short" if name == "major_step" else name
            grid.addWidget(QLabel(tr(f"axis_breaks.col.{caption}")), 3, column)
        self.cells = {}
        for row in range(ROWS):
            grid.addWidget(QLabel(tr("axis_breaks.row", row=row + 1)), 4 + row, 0)
            segment = segments[row] if row < len(segments) else {}
            for column, name in enumerate(COLUMNS, start=1):
                cell = self.cells[(row, name)] = QLineEdit(_text(segment.get(name)))
                cell.setAccessibleName(f"{tr('axis_breaks.row', row=row + 1)} · {tr(f'axis_breaks.col.{name}')}")
                if name == "share":
                    cell.textChanged.connect(self._total)
                if name in ("major_origin", "minor_ticks"):
                    cell.setToolTip(tr(f"axis_breaks.hint.{name}"))
                grid.addWidget(cell, 4 + row, column)
        self.total = QLabel()
        self.total.setObjectName("muted")
        body.addWidget(self.total)
        line = QHBoxLayout()
        self.suggest_button = QPushButton(tr("axis_breaks.btn.suggest"))
        self.suggest_button.setAutoDefault(False)
        self.suggest_button.clicked.connect(self.suggest)
        line.addWidget(self.suggest_button)
        self.preview_button = QPushButton(tr("axis_breaks.btn.preview"))
        self.preview_button.setAutoDefault(False)
        self.preview_button.clicked.connect(self.preview)
        self.preview_button.setVisible(preview is not None)
        line.addWidget(self.preview_button)
        line.addStretch(1)
        body.addLayout(line)
        notes = ["axis_breaks.note.scale", "axis_breaks.note.limits", "axis_breaks.note.numbers"]
        if self.survival:
            notes.append("axis_breaks.note.survival")
        for key in notes:
            note = QLabel(tr(key))
            note.setObjectName("muted")
            note.setWordWrap(True)
            body.addWidget(note)
        body.addStretch(1)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText(tr("axis_breaks.btn.ok"))
        ok_button.setAutoDefault(True)
        ok_button.setDefault(True)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText(tr("axis_breaks.btn.cancel"))
        cancel_button.setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.axis.currentIndexChanged.connect(self._axis_changed)
        self.count.currentIndexChanged.connect(self._count_changed)
        self._states()
        fit_dialog(self, 700, 560)

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
        if not self.axis.value():
            self.total.setText("")
            return
        try:
            shares = [float(decimal_comma(self.cells[(row, "share")].text().strip())) for row in range(self.rows())]
        except ValueError:
            self.total.setText("")
            return
        total = sum(shares)
        self.total.setText(tr("axis_breaks.total", total=f"{total:g}"))
        name = "muted" if abs(total - 100.0) <= 1e-6 else "errorText"
        if self.total.objectName() != name:
            self.total.setObjectName(name)
            self.total.style().unpolish(self.total)
            self.total.style().polish(self.total)

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
        saved = self.record.get("segments", ()) if axis == self.record.get("axis") else ()
        segments = []
        for row in range(self.rows()):
            segment = {name: _typed(self.cells[(row, name)].text()) for name in ("low", "high", "share")}
            for name in ("major_step", "major_origin", "minor_ticks"):
                segment[name] = _typed(self.cells[(row, name)].text(), blank=None)
            if row < len(saved):
                for key in ("tick_labels", "tick_format"):
                    if key in saved[row]:
                        segment[key] = saved[row][key]
            segments.append(segment)
        record = normalise_axis_breaks({"axis": axis, "gap": _typed(self.gap.text()), "segments": segments})
        if self.survival:
            for row, segment in enumerate(record["segments"]):
                if segment["low"] < 0:
                    raise AxisBreakError(row, "low", M_NONNEGATIVE.format(row=row + 1))
        return record

    def _error_widget(self, error):
        if isinstance(error, AxisBreakError):
            widget = self.cells.get((error.row, error.name))
            if widget is not None:
                return widget
        field = getattr(error, "field", None)
        if field == "gap":
            return self.gap
        if field == "segments":
            return self.count
        if field == "axis":
            return self.axis
        return None

    def _show(self, error):
        text = str(error) if isinstance(error, str) else translate_breaks_error(error)
        self.problem.setText(text)
        self.problem.setVisible(True)
        widget = self._error_widget(error) if not isinstance(error, str) else None
        if widget is not None:
            self.scroll.ensureWidgetVisible(widget)
            widget.setFocus()
            if isinstance(widget, QLineEdit):
                widget.selectAll()

    def _try(self, draw):
        if self._busy_check and self._busy_check():
            self._show(tr("axis_breaks.error.busy"))
            return None
        try:
            record = self.read_record()
            if draw and self._preview is not None:
                self._preview(record)
                self._previewed = True
        except ValueError as error:
            self.result = None
            self._show(error)
            return None
        self.problem.setVisible(False)
        return record

    def preview(self):
        return self._try(True) is not None

    def accept(self):
        record = self._try(True)
        if record is None:
            return
        self.result = record
        self._accepted = True
        super().accept()

    def reject(self):
        if not self._accepted and self._previewed and self._preview is not None:
            try:
                self._preview(None)
            except ValueError:
                pass
        self.result = None
        super().reject()
