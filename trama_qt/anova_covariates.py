"""Covariates on the model page of the Classic Qt multifactor ANOVA dialog.

Nothing is written into the recipe until at least one numeric column is checked. An empty reference
uses the mean of the rows the fit will use; a typed number is stored as that reference. The note
says which model options this release does not calculate, and when a reference leaves the observed
range.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QSizePolicy, QVBoxLayout, QWidget)

from analisi.anova_covariates import COVARIATES, REFERENCES, ERRORS, preview
from analisi.data import decimal_comma
from analisi.field_error import FieldError
from analisi.i18n import active_language, tr


class _ColumnList(QListWidget):
    """Enter reaches the dialog's Run button; the list itself does not consume it."""

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)


class CovariatePanel(QWidget):
    """The covariate columns and one reference field for each column that is checked."""

    def __init__(self, data, saved=None, parent=None):
        super().__init__(parent)
        saved = saved or {}
        self.data = data
        self._saved = [name for name in (saved.get(COVARIATES) or []) if isinstance(name, str)]
        stored = saved.get(REFERENCES) or {}
        self._saved_refs = {name: stored[name] for name in self._saved if isinstance(stored, dict) and name in stored}
        self._offered = None
        self._response, self._factors = None, []
        self.edits = {}
        self.captions = {}
        self.holders = {}

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.columns = _ColumnList()
        self.columns.setObjectName("covariateColumns")
        self.columns.itemChanged.connect(self._toggled)
        layout.addWidget(self.columns)
        self.references = QWidget()
        self.reference_form = QFormLayout(self.references)
        self.reference_form.setContentsMargins(0, 0, 0, 0)
        self.reference_form.setSpacing(4)
        layout.addWidget(self.references)
        self.note = QLabel()
        self.note.setObjectName("infoBanner")
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.note)
        self.note.hide()
        self.references.hide()

    def set_roles(self, response, factors):
        """Offer the numeric columns that are neither the response nor a model factor."""
        factors = [name for name in factors if isinstance(name, str)]
        numeric = [str(name) for name in self.data.select_dtypes(include="number").columns]
        offered = [name for name in numeric if name != response and name not in factors]
        if offered == self._offered and response == self._response and factors == self._factors:
            self._refresh_note()
            return
        checked = set(self.checked()) if self._offered is not None else set(self._saved)
        texts = {name: self.edits[name].text() for name in self.edits}
        self._offered, self._response, self._factors = offered, response, factors
        self.columns.blockSignals(True)
        self.columns.clear()
        while self.reference_form.rowCount():
            self.reference_form.removeRow(0)
        self.edits.clear()
        self.captions.clear()
        self.holders.clear()
        for name in offered:
            item = QListWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked)
            self.columns.addItem(item)
            edit = QLineEdit()
            edit.setObjectName(f"covariateReference-{name}")
            if name in texts:
                edit.setText(texts[name])
            elif name in self._saved_refs and not isinstance(self._saved_refs[name], bool):
                shown = format(float(self._saved_refs[name]), ".12g")
                edit.setText(shown.replace(".", ",") if active_language() == "it" else shown)
            caption = QLabel()
            caption.setObjectName("muted")
            caption.setWordWrap(True)
            edit.textChanged.connect(lambda _text, column=name: self._refresh_note(column))
            row = QHBoxLayout()
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(edit, 1)
            row.addWidget(caption, 2)
            self.reference_form.addRow(tr("anova.covariate.reference_caption", name=name), holder)
            self.edits[name] = edit
            self.captions[name] = caption
            self.holders[name] = holder
        self.columns.setMaximumHeight(max(72, min(160, 24 * max(len(offered), 1) + 8)))
        self.columns.blockSignals(False)
        self._toggled()

    def checked(self):
        return [self.columns.item(row).text() for row in range(self.columns.count())
                if self.columns.item(row).checkState() == Qt.CheckState.Checked]

    def values(self):
        """Recipe keys, or nothing when no covariate is checked."""
        chosen = self.checked()
        if not chosen:
            return {}
        references = {}
        for name in chosen:
            text = self.edits[name].text().strip() if name in self.edits else ""
            if not text:
                continue
            try:
                number = float(decimal_comma(text))
            except ValueError:
                raise FieldError(COVARIATES, ERRORS["reference"].format(name=name)) from None
            if number != number or number in (float("inf"), float("-inf")):
                raise FieldError(COVARIATES, ERRORS["reference"].format(name=name))
            references[name] = number
        found = {COVARIATES: chosen}
        if references:
            found[REFERENCES] = references
        return found

    def focus_problem(self, _error=None, field=None):
        del field
        self.columns.setFocus()
        return True

    def _toggled(self, _item=None):
        chosen = set(self.checked())
        for name, holder in self.holders.items():
            self.reference_form.setRowVisible(holder, name in chosen)
        self.references.setVisible(bool(chosen))
        self._refresh_note()

    def _refresh_note(self, _name=None):
        chosen = self.checked()
        if not chosen:
            self.note.hide()
            return
        try:
            typed = self.values().get(REFERENCES, {})
        except FieldError:
            typed = {}
        shown = preview(self.data, self._response, self._factors, chosen, typed)
        lines = [tr("anova.covariate.note.limits"), tr("anova.covariate.note.range")]
        details = {row["name"]: row for row in shown} if shown else {}
        for name in chosen:
            row = details.get(name)
            caption = self.captions.get(name)
            if row is None or caption is None:
                continue
            if row["source"] == "Explicit":
                text = tr("anova.covariate.explicit", value=format(row["reference"], ".8g"))
            else:
                text = tr("anova.covariate.mean", value=format(row["mean"], ".8g"))
            if row["outside"]:
                text = f"{text} {tr('anova.covariate.outside')}"
            cells = [part for part in row["cells"].split("; ") if part]
            if cells:
                text = f"{text} {tr('anova.covariate.cells', count=len(cells))}"
            caption.setText(text)
        self.note.setText("\n".join(lines))
        self.note.show()
