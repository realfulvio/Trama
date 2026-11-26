"""Visit-order list for the AR(1) mixed model.

The shared recipe keeps the order as the within-subject levels themselves. This
widget only confirms that order; the fit stays on the worker.
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from analisi.ar1 import AR1, COVARIANCE, VISIT_ORDER, align_visit_order
from analisi.field_error import FieldError
from analisi.i18n import tr, ui
from analisi.repeated_workbench import mixed_coverage

METHOD = "Mixed-effects model (REML)"
DENOMINATOR = "Denominator method"


def plain(value):
    """A JSON-safe Python value for a factor level stored in the recipe."""
    if isinstance(value, str):
        return value
    convert = getattr(value, "item", None)
    if not callable(convert):
        return value
    try:
        converted = convert()
    except (TypeError, ValueError):
        return value
    return converted if isinstance(converted, (str, int, float)) and not isinstance(converted, bool) else value


def natural_key(value):
    parts = re.split(r"(\d+)", str(value))
    return [(0, int(part)) if part.isdigit() else (1, part.casefold()) for part in parts if part]


class _OrderList(QListWidget):
    """Enter stays on the dialog's Run button; the list only moves the selection."""

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)


class VisitOrder(QWidget):
    """The confirmed order of one within-subject factor, with the coverage note."""

    def __init__(self, saved):
        super().__init__()
        self._saved = saved
        self.levels = []
        self.list = _OrderList()
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setFixedHeight(5 * self.list.fontMetrics().lineSpacing() + 12)
        self.setFocusProxy(self.list)
        self.up = QPushButton(ui("Up"))
        self.down = QPushButton(ui("Down"))
        for button, key, step in ((self.up, "mixed.ar1.move_up", -1), (self.down, "mixed.ar1.move_down", 1)):
            button.setAutoDefault(False)
            button.setToolTip(tr(key))
            button.clicked.connect(lambda _checked=False, step=step: self.move(step))
        for direction, step in (("Up", -1), ("Down", 1)):
            shortcut = QShortcut(QKeySequence(f"Alt+{direction}"), self.list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda step=step: self.move(step))
        self.note = QLabel()
        self.note.setObjectName("infoBanner")
        self.note.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.up)
        buttons.addWidget(self.down)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        layout.addLayout(buttons)
        layout.addWidget(self.note)
        self._sync_buttons()

    def values(self):
        return list(self.levels)

    def set_note(self, text):
        self.note.setText(text)
        self.up.setToolTip(tr("mixed.ar1.move_up"))
        self.down.setToolTip(tr("mixed.ar1.move_down"))

    def set_levels(self, levels):
        levels = [plain(level) for level in levels]
        if not levels:
            if self.levels:
                self.levels = []
                self._render()
            return
        current = [str(level) for level in self.levels]
        incoming = [str(level) for level in levels]
        if current and len(current) == len(set(current)) == len(incoming) and set(current) == set(incoming):
            by_text = {str(level): level for level in levels}
            self.levels = [by_text[text] for text in current]
            return
        self.levels = self._propose(levels)
        self._render()

    def focus_problem(self, _error=None, field=None):
        self.list.setFocus()
        if self.list.count():
            self.list.setCurrentRow(max(self.list.currentRow(), 0))
        return True

    def move(self, step):
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < len(self.levels):
            return
        self.levels[row], self.levels[target] = self.levels[target], self.levels[row]
        self._render(target)

    def _propose(self, levels):
        saved = self._saved
        if saved not in (None, "", []):
            try:
                ordered = [plain(level) for level in align_visit_order(saved, levels)]
            except FieldError:
                ordered = None
            else:
                self._saved = None
                return ordered
        self._saved = None
        return sorted(levels, key=natural_key)

    def _render(self, selected=0):
        self.list.clear()
        self.list.addItems([str(level) for level in self.levels])
        if self.levels:
            self.list.setCurrentRow(min(max(selected, 0), len(self.levels) - 1))
        self._sync_buttons()

    def _sync_buttons(self):
        row = self.list.currentRow()
        self.up.setEnabled(row > 0)
        self.down.setEnabled(0 <= row < self.list.count() - 1)


def _checked(widget):
    return [widget.item(index).text() for index in range(widget.count())
            if widget.item(index).checkState() == Qt.CheckState.Checked]


def _control_value(kind, widget):
    if isinstance(widget, VisitOrder):
        return widget.values()
    if isinstance(widget, QListWidget):
        return _checked(widget)
    if kind == "Text":
        return widget.text()
    data = widget.currentData()
    return widget.currentText() if data is None else data


def recipe_snapshot(dialog):
    """The mixed-model fields the coverage note can read before Run is pressed."""
    snapshot = {}
    for name, (kind, widget) in dialog.controls.items():
        if name in {"Input format", "Y", "Subject", "Within factors", "Between factors",
                    "Measurement columns", "Row labels", "Repeat across", "Subject IDs",
                    COVARIANCE, VISIT_ORDER}:
            snapshot[name] = _control_value(kind, widget)
    return snapshot


def attach(dialog):
    if dialog.method != METHOD or VISIT_ORDER not in dialog.controls:
        return None
    covariance = dialog.controls[COVARIANCE][1]
    editor = dialog.controls[VISIT_ORDER][1]
    lists = ("Within factors", "Between factors", "Measurement columns")
    combos = ("Input format", "Y", "Subject", "Row labels", "Repeat across", "Subject IDs", COVARIANCE)

    def sync(*_args):
        structure = covariance.currentData()
        dialog._set_field_visibility({
            VISIT_ORDER: structure == AR1,
            DENOMINATOR: structure != AR1,
        })
        if structure != AR1:
            return
        options = recipe_snapshot(dialog)
        coverage = mixed_coverage(dialog.data, options)
        editor.set_levels([] if coverage is None else coverage["levels"])
        if coverage is None:
            editor.set_note(tr("mixed.ar1.not_ready"))
        else:
            editor.set_note(tr("mixed.ar1.coverage", partial=coverage["partial"], excluded=coverage["excluded"]))
        if dialog.error_field in dialog.hidden:
            dialog.clear_field_error(dialog.error_field)

    covariance.currentIndexChanged.connect(sync)
    for name in combos:
        if name != COVARIANCE:
            dialog.controls[name][1].currentIndexChanged.connect(sync)
    for name in lists:
        dialog.controls[name][1].itemChanged.connect(sync)
    sync()
    return editor
