"""Linked secondary axes on Qt: the editor, and the summary line (same record as ``analisi.linked_axes``)."""
from copy import deepcopy
from math import isfinite

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QVBoxLayout)

from analisi.data import decimal_comma
from analisi.i18n import active_language, tr, translate_message
from analisi.linked_axes import (DIMENSIONS, LinkedAxesError, convert, linked_axes_conflicts, normalise_linked_axes,
                                 range_problem)
from analisi.presentation import validate_graph_style

from .theme import fit_dialog

FIELDS = ("label", "multiplier", "offset")


def translate_linked_error(error):
    """An engine message in the active language."""
    return translate_message(str(error), "linked_axes.error.")


def linked_summary(record):
    """One line for the button that opens the editor."""
    if not record:
        return tr("linked_axes.summary_none")
    return ", ".join(tr(f"linked_axes.summary.{dimension}") for dimension in DIMENSIONS if dimension in record)


def conflict_note(conflicts):
    """One readable sentence for the axes that cannot take a linked axis now, or an empty string."""
    texts = {translate_linked_error(message) for message in conflicts.values()}
    return tr("linked_axes.note.graph", reason=" ".join(sorted(texts))) if texts else ""


def available_conflicts(axes, *, scales=None, breaks=None, right=None):
    """``linked_axes_conflicts`` for a graph, keyed by dimension (an empty dict when both axes are free)."""
    return linked_axes_conflicts(axes, scales=scales, breaks=breaks, right=right)


def reference_values(axes, dimension, logarithmic=False):
    """Two values of the primary axis to show in the preview: its first and last visible major tick.

    On a logarithmic axis only positive values can be shown, so the preview skips zero and below.
    """
    low, high = sorted(float(value) for value in getattr(axes, f"get_{dimension}lim")())
    axis = getattr(axes, f"{dimension}axis")
    try:
        ticks = [float(value) for value in axis.get_majorticklocs() if low <= value <= high and isfinite(value)]
    except (TypeError, ValueError):
        ticks = []
    if logarithmic:
        ticks = [value for value in ticks if value > 0]
        positive = [value for value in (low, high) if value > 0]
        if len(ticks) >= 2:
            return ticks[0], ticks[-1]
        return (positive[0], positive[-1]) if len(positive) == 2 and positive[0] != positive[-1] else (1.0, 10.0)
    return (ticks[0], ticks[-1]) if len(ticks) >= 2 else (low, high)


def _show(value):
    text = f"{value:.6g}"
    return text.replace(".", ",") if active_language() == "it" else text


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


class LinkedAxesDialog(QDialog):
    """Edit the ``linked_axes`` record. ``result`` is ``{}`` for no linked axes or the canonical record.

    ``conflicts`` (``{dimension: message}``, from ``linked_axes_conflicts``) disables the controls of an axis the
    graph cannot take, with the reason beside them; a saved record on such an axis can only be switched off.
    ``scales`` gives the scale each axis will have (a logarithmic axis fixes the offset at 0).
    """

    def __init__(self, parent, axes, record, *, conflicts=None, scales=None):
        super().__init__(parent)
        self.setWindowTitle(tr("linked_axes.title"))
        self.axes, self.result = axes, None
        self.record = deepcopy(record) or {}
        self.conflicts = dict(conflicts if conflicts is not None else linked_axes_conflicts(axes, scales=scales))
        self.scales = dict(scales or {})
        outer = QVBoxLayout(self)
        intro = QLabel(tr("linked_axes.hint.intro"))
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        formula = QLabel(tr("linked_axes.formula"))
        formula.setObjectName("sectionTitle")
        outer.addWidget(formula)
        self.boxes, self.fields, self.previews, self.notes = {}, {}, {}, {}
        for dimension in DIMENSIONS:
            self._group(outer, dimension)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        outer.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("linked_axes.btn.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("linked_axes.btn.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._states()
        fit_dialog(self, 560, 560)

    # -- build -------------------------------------------------------------------------------------------
    def _group(self, outer, dimension):
        saved = self.record.get(dimension)
        box = self.boxes[dimension] = QGroupBox(tr(f"linked_axes.group.{dimension}"))
        box.setCheckable(True)
        box.setChecked(saved is not None)
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for name in FIELDS:
            value = saved.get(name) if saved else {"label": "", "multiplier": 1.0, "offset": 0.0}[name]
            field = self.fields[(dimension, name)] = QLineEdit(value if name == "label" else _show(value))
            field.setAccessibleName(f"{box.title()}: {tr('linked_axes.field.' + name)}")
            field.textChanged.connect(lambda _text, dimension=dimension: self._preview(dimension))
            form.addRow(tr("linked_axes.field." + name), field)
        hint = QLabel(tr("linked_axes.hint.label"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.previews[dimension] = QLabel()
        self.previews[dimension].setWordWrap(True)
        form.addRow(self.previews[dimension])
        self.notes[dimension] = QLabel()
        self.notes[dimension].setObjectName("muted")
        self.notes[dimension].setWordWrap(True)
        form.addRow(self.notes[dimension])
        box.toggled.connect(lambda on, dimension=dimension: self._toggled(dimension, on))
        outer.addWidget(box)

    def _toggled(self, dimension, on):
        if on and dimension in self.conflicts:
            # A conflict can only be switched off: the axis stays out until the graph allows it.
            box = self.boxes[dimension]
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self._states()

    def _logarithmic(self, dimension):
        return self.scales.get(dimension) == "log"

    def _states(self):
        for dimension in DIMENSIONS:
            box, conflict = self.boxes[dimension], self.conflicts.get(dimension)
            box.setEnabled(not conflict or dimension in self.record)
            for name in FIELDS:
                self.fields[(dimension, name)].setEnabled(box.isChecked() and not conflict)
            logarithmic = self._logarithmic(dimension)
            offset = self.fields[(dimension, "offset")]
            if logarithmic:
                offset.blockSignals(True)
                offset.setText("0")
                offset.blockSignals(False)
                offset.setEnabled(False)
            if conflict:
                note = tr("linked_axes.unavailable", reason=translate_linked_error(conflict))
            elif logarithmic:
                note = tr("linked_axes.hint.log")
            else:
                note = ""
            self.notes[dimension].setText(note)
            self.notes[dimension].setVisible(bool(note))
            self._preview(dimension)

    def _preview(self, dimension):
        label = self.previews[dimension]
        label.setVisible(self.boxes[dimension].isChecked() and not self.conflicts.get(dimension))
        multiplier = _typed(self.fields[(dimension, "multiplier")].text())
        offset = _typed(self.fields[(dimension, "offset")].text())
        if (type(multiplier) is not float or type(offset) is not float or not multiplier > 0
                or abs(multiplier) == float("inf")):
            label.setText(tr("linked_axes.preview_invalid"))
            return
        first, second = reference_values(self.axes, dimension, self._logarithmic(dimension))
        item = {"multiplier": multiplier, "offset": offset}
        one, two = convert(item, [first, second])
        label.setText(tr("linked_axes.preview", first=_show(first), second=_show(float(one)),
                         third=_show(second), fourth=_show(float(two))))

    # -- read --------------------------------------------------------------------------------------------
    def read_record(self):
        record = {}
        for dimension in DIMENSIONS:
            box = self.boxes[dimension]
            if not box.isChecked():
                continue
            if self.conflicts.get(dimension):
                record[dimension] = deepcopy(self.record[dimension])  # Kept as it is; only Off removes it.
                continue
            record[dimension] = {
                "multiplier": _typed(self.fields[(dimension, "multiplier")].text()),
                "offset": 0.0 if self._logarithmic(dimension) else _typed(self.fields[(dimension, "offset")].text()),
                "label": self.fields[(dimension, "label")].text(),
            }
        canonical = normalise_linked_axes(record)
        for dimension, item in canonical.items():
            if self.conflicts.get(dimension):
                continue
            problem = range_problem(dimension, item, getattr(self.axes, f"get_{dimension}lim")())
            if problem:
                raise LinkedAxesError(dimension, "multiplier", problem)
        return canonical

    def _fail(self, text, field=None):
        self.result = None
        self.problem.setText(text)
        self.problem.setVisible(True)
        if field is not None:
            field.setFocus()
            field.selectAll()

    def accept(self):
        try:
            record = self.read_record()
            validate_graph_style(self.axes, {"linked_axes": record} if record else {})
        except LinkedAxesError as error:
            field = self.fields.get((error.dimension, error.name))
            self._fail(translate_linked_error(error), field)
            return
        except ValueError as error:
            first = next((self.fields[(dimension, "label")] for dimension in DIMENSIONS
                          if self.boxes[dimension].isChecked()), None)
            self._fail(translate_message(error), first)
            return
        self.result = record
        super().accept()


__all__ = ["LinkedAxesDialog", "linked_summary", "conflict_note", "available_conflicts", "translate_linked_error"]
