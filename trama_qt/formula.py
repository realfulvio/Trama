"""Formula… on Qt: add a calculated column or change the expression of an existing one.

Same rules as the classic window: the name is new or an existing calculated column, and the expression must
evaluate on the whole table before it is kept (``Dataset.set_formula``).
"""
from copy import copy

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit

from analisi.i18n import active_language, tr, ui

_ITALIAN = {"Edit formula": "Modifica formula", "Choose a new column name.": "Scegli un nuovo nome di colonna.",
            "Enter a formula.": "Inserisci una formula.",
            "A calculated column cannot depend on itself, directly or indirectly.":
                "Una colonna calcolata non può dipendere da sé stessa, direttamente o indirettamente."}


def t(text):
    return _ITALIAN.get(text, ui(text)) if active_language() == "it" else text


class FormulaDialog(QDialog):
    """``result`` is ``(name, expression)`` after OK; the expression was checked on a copy of ``dataset``."""

    def __init__(self, parent, dataset, name=""):
        super().__init__(parent)
        self.setWindowTitle(ui("Calculated column"))
        self.dataset, self.result = dataset, None
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText(ui("New or existing calculated column name"))
        form.addRow(ui("Calculated column"), self.name)
        self.expression = QPlainTextEdit(dataset.formulas.get(name, ""))
        self.expression.setTabChangesFocus(True)
        self.expression.setMinimumHeight(70)
        self.expression.setMaximumHeight(140)
        form.addRow(ui("Formula"), self.expression)
        examples = QLabel(tr("worksheet.formula.examples"))
        examples.setObjectName("muted")
        examples.setWordWrap(True)
        form.addRow(examples)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        form.addRow(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("language.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.name.textEdited.connect(self.load_existing)
        self.resize(560, self.sizeHint().height())

    def load_existing(self, text):
        """Typing the name of a calculated column shows its expression to change."""
        existing = self.dataset.formulas.get(text.strip())
        if existing is not None:
            self.expression.setPlainText(existing)

    def show_problem(self, text):
        self.problem.setText(text)
        self.problem.setVisible(bool(text))

    def accept(self):
        name, expression = self.name.text().strip(), self.expression.toPlainText().strip()
        if not name:
            self.show_problem(t("Choose a new column name."))
            self.name.setFocus()
            return
        if not expression:
            self.show_problem(t("Enter a formula."))
            self.expression.setFocus()
            return
        try:
            candidate = copy(self.dataset)
            candidate.set_formula(name, expression)
        except (ValueError, TypeError, OverflowError) as error:
            self.show_problem(t(str(error)))
            self.expression.setFocus()
            return
        self.result = name, candidate.formulas[name]
        super().accept()
