"""Estimated marginal means in the Classic Qt Multifactor ANOVA dialog.

One check box on the Options page. While it is off the recipe gains none of the four keys, so an
analysis saved before this option keeps the same sheets. While it is on, the panel writes the
factors (in the order they were ticked), the overall mean and the confidence as a proportion.
The field shows a percent: 95 is stored as 0.95, and Italian accepts a comma.
"""
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QSizePolicy, QVBoxLayout, QWidget

from analisi.anova_marginal_means import CONFIDENCE, DEFAULT_CONFIDENCE, ENABLED, FACTORS, OVERALL
from analisi.data import decimal_comma
from analisi.field_error import FieldError
from analisi.i18n import active_language, tr

PERCENT_ERROR = "Enter a confidence percentage greater than 0 and less than 100."


def percent_text(value):
    """The percent shown for a stored proportion. Empty when the stored value is not a proportion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return ""
    text = f"{100 * float(value):.10g}"
    return text.replace(".", ",") if active_language() == "it" else text


class _ToggleLabel(QLabel):
    """A wrapping caption that toggles the check box beside it."""

    def __init__(self, text, box):
        super().__init__(text)
        self.box = box
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def mouseReleaseEvent(self, event):
        self.box.toggle()
        super().mouseReleaseEvent(event)


def _check_line(layout, text, object_name):
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    box = QCheckBox()
    box.setObjectName(object_name)
    label = _ToggleLabel(text, box)
    row.addWidget(box, 0, Qt.AlignmentFlag.AlignTop)
    row.addWidget(label, 1)
    layout.addLayout(row)
    return box, label


def _note(text=""):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setObjectName("muted")
    return label


class MeansPanel(QWidget):
    """The four recipe keys. ``values`` returns nothing while the option is off."""

    def __init__(self, saved=None, parent=None):
        super().__init__(parent)
        saved = saved or {}
        self.setObjectName("marginalMeansPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.context = lambda: ([], {}, None)
        on = saved.get(ENABLED) is True
        self._order = [name for name in (saved.get(FACTORS) or []) if isinstance(name, str)] if on else []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.enabled, self.title = _check_line(layout, tr("anova.means.field.enabled"), "marginalMeansEnabled")
        self.enabled.setChecked(on)
        self.help = _note(tr("anova.means.help"))
        layout.addWidget(self.help)
        self.factors_label = _note(tr("anova.means.factors"))
        self.factors_label.setObjectName("")
        layout.addWidget(self.factors_label)
        self.factor_list = QListWidget()
        self.factor_list.setObjectName("marginalMeansFactors")
        self.factor_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.factor_list.setMinimumHeight(72)
        self.factor_list.setMaximumHeight(148)
        self.factor_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.factor_list.itemChanged.connect(self._toggled)
        layout.addWidget(self.factor_list)
        self.overall, self.overall_label = _check_line(layout, tr("anova.means.overall"), "marginalMeansOverall")
        self.overall.setChecked(saved.get(OVERALL) is True if on else False)
        confidence_row = QHBoxLayout()
        confidence_row.setContentsMargins(0, 0, 0, 0)
        confidence_row.setSpacing(8)
        self.confidence_label = _note(tr("anova.means.confidence"))
        self.confidence = QLineEdit(percent_text(saved.get(CONFIDENCE, DEFAULT_CONFIDENCE) if on else DEFAULT_CONFIDENCE))
        self.confidence.setObjectName("marginalMeansConfidence")
        self.confidence.setMaximumWidth(96)
        self.confidence.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        confidence_row.addWidget(self.confidence_label, 1)
        confidence_row.addWidget(self.confidence, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(confidence_row)
        self.note = _note()
        self.note.setObjectName("marginalMeansAbsent")
        self.note.hide()
        layout.addWidget(self.note)
        self.weighting = _note(tr("anova.means.weighting"))
        layout.addWidget(self.weighting)
        self.enabled.toggled.connect(self._sync)
        self._sync()

    def factors(self):
        """Ticked names in the order they were ticked, which is the order a saved recipe reopens with."""
        present = []
        for row in range(self.factor_list.count()):
            item = self.factor_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                present.append(item.data(Qt.ItemDataRole.UserRole))
        chosen = set(present)
        ordered = [name for name in self._order if name in chosen]
        return ordered + [name for name in present if name not in ordered]

    def refresh(self):
        """Rebuild the factor list from the model as the dialog stands now. Checks are kept."""
        try:
            model, _levels, _check = self.context()
        except (TypeError, ValueError):
            model = []
        model = list(model or [])
        names = list(model)
        for name in self._order:
            if name not in names:
                names.append(name)
        self.factor_list.blockSignals(True)
        self.factor_list.clear()
        chosen = set(self._order)
        for name in names:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in chosen else Qt.CheckState.Unchecked)
            self.factor_list.addItem(item)
        self.factor_list.blockSignals(False)
        self._show_absent(model)

    def _toggled(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            if name not in self._order:
                self._order.append(name)
        else:
            self._order = [kept for kept in self._order if kept != name]
        try:
            model = list(self.context()[0] or [])
        except (TypeError, ValueError):
            model = []
        self._show_absent(model)

    def _show_absent(self, model):
        absent = [name for name in self._order if name not in model]
        if absent and self.enabled.isChecked():
            self.note.setText(tr("anova.means.note.absent", factors=", ".join(absent)))
            self.note.setVisible(True)
        else:
            self.note.clear()
            self.note.hide()

    def _sync(self, *_args):
        on = self.enabled.isChecked()
        for widget in (self.help, self.factors_label, self.factor_list, self.overall, self.overall_label,
                       self.confidence_label, self.confidence, self.weighting):
            widget.setEnabled(on)
        if not on:
            self.note.hide()

    def _confidence(self):
        """Proportion for the recipe. The line edit is a percentage, so 95 is stored as 0.95."""
        text = decimal_comma(self.confidence.text().strip())
        try:
            percent = float(text)
        except ValueError:
            raise FieldError(CONFIDENCE, PERCENT_ERROR) from None
        if not math.isfinite(percent) or not 0 < percent < 100:
            raise FieldError(CONFIDENCE, PERCENT_ERROR)
        return percent / 100.0

    def values(self):
        """The four keys, or nothing while the option is off."""
        if not self.enabled.isChecked():
            return {}
        return {ENABLED: True, FACTORS: self.factors(), OVERALL: self.overall.isChecked(),
                CONFIDENCE: self._confidence()}

    def focus_problem(self, error=None, field=None):
        """Put the cursor on the field the error names, and turn the option on so it can be edited."""
        field = field or getattr(error, "field", None)
        target = {CONFIDENCE: self.confidence, OVERALL: self.overall, FACTORS: self.factor_list,
                  ENABLED: self.enabled}.get(field, self.enabled)
        if field in (ENABLED, FACTORS, OVERALL, CONFIDENCE) and not self.enabled.isChecked():
            self.enabled.setChecked(True)
        self._sync()
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        if target is self.confidence:
            self.confidence.selectAll()
        return True


__all__ = ["MeansPanel", "PERCENT_ERROR", "percent_text"]
