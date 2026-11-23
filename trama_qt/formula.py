"""Formula… on Qt: add a calculated column or change the expression of an existing one.

Same rules as the classic window: the name is new or an existing calculated column, and the expression must
evaluate on the whole table before it is kept (``Dataset.set_formula``).
"""
from copy import copy

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPlainTextEdit, QPushButton)

from analisi.formula_reference import function_references, matching_references, variable_references
from analisi.grid_headings import column_label
from analisi.i18n import active_language, tr, translate_message, ui

_ITALIAN = {"Edit formula": "Modifica formula", "Choose a new column name.": "Scegli un nuovo nome di colonna.",
            "Enter a formula.": "Inserisci una formula.",
            "A calculated column cannot depend on itself, directly or indirectly.":
                "Una colonna calcolata non può dipendere da sé stessa, direttamente o indirettamente."}


def t(text):
    return _ITALIAN.get(text, ui(text)) if active_language() == "it" else text


class FormulaDialog(QDialog):
    """``result`` is ``(name, expression)`` after OK; the expression was checked on a copy of ``dataset``."""

    def __init__(self, parent, dataset, name="", *, column=None):
        super().__init__(parent)
        self.setWindowTitle(tr("worksheet.formula.title"))
        self.dataset, self.result = dataset, None
        self.column = column
        self.replace_values = column is not None and dataset.column_has_values(column)
        if column is not None:
            name = dataset.columns[column]
        form = QFormLayout(self)
        self.name = QLineEdit(name, self)
        self.name.setPlaceholderText(ui("New or existing calculated column name"))
        if column is not None:
            position = QLabel(tr("worksheet.formula.position", letter=column_label(column), name=name))
            position.setTextFormat(Qt.TextFormat.PlainText)
            position.setWordWrap(True)
            form.addRow(position)
            self.name.hide()
        else:
            form.addRow(ui("Calculated column"), self.name)
        self.expression = QPlainTextEdit(dataset.formulas.get(name, ""))
        self.expression.setTabChangesFocus(True)
        self.expression.setMinimumHeight(70)
        self.expression.setMaximumHeight(92)
        form.addRow(ui("Formula"), self.expression)
        examples = QLabel(tr("worksheet.formula.examples"))
        examples.setObjectName("muted")
        examples.setWordWrap(True)
        if column is not None:
            letters = QLabel(tr("worksheet.formula.letters"))
            letters.setWordWrap(True)
            form.addRow(letters)
        self.add_references(form)
        form.addRow(examples)
        if self.replace_values:
            warning = QLabel(tr("worksheet.formula.replace_warning"))
            warning.setWordWrap(True)
            form.addRow(warning)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        form.addRow(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            tr("worksheet.formula.replace" if self.replace_values else "language.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.name.textEdited.connect(self.load_existing)
        if column is not None:
            self.expression.setFocus()
        self.resize(560, self.sizeHint().height())

    def add_references(self, form):
        self.references = (variable_references(self.dataset), function_references())
        bar = QHBoxLayout()
        self.reference_group = QComboBox()
        self.reference_group.addItems([tr("worksheet.formula.columns"), tr("worksheet.formula.functions")])
        self.reference_search = QLineEdit()
        self.reference_insert = QPushButton(tr("worksheet.formula.insert"))
        self.reference_insert.setAutoDefault(False)
        bar.addWidget(self.reference_group)
        bar.addWidget(self.reference_search, 1)
        bar.addWidget(self.reference_insert)
        form.addRow(bar)
        self.reference_results = QListWidget()
        self.reference_results.setMinimumHeight(78)
        self.reference_results.setMaximumHeight(106)
        form.addRow(self.reference_results)
        self.reference_detail = QLabel()
        self.reference_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.reference_detail.setWordWrap(True)
        self.reference_detail.setObjectName("muted")
        self.reference_detail.setMinimumHeight(self.fontMetrics().lineSpacing() * 2)
        form.addRow(self.reference_detail)
        self.reference_group.currentIndexChanged.connect(self.filter_references)
        self.reference_search.textChanged.connect(self.filter_references)
        self.name.textChanged.connect(self.filter_references)
        self.reference_results.currentRowChanged.connect(self.show_reference)
        self.reference_results.itemDoubleClicked.connect(self.insert_reference)
        self.reference_insert.clicked.connect(self.insert_reference)
        self.reference_search.installEventFilter(self)
        self.reference_results.installEventFilter(self)
        self.filter_references()

    def eventFilter(self, watched, event):
        if (watched in (self.reference_search, self.reference_results) and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self.insert_reference()
            return True
        return super().eventFilter(watched, event)

    def filter_references(self):
        mode = self.reference_group.currentIndex()
        self.reference_search.setPlaceholderText(tr("worksheet.formula.search_functions" if mode
                                                    else "worksheet.formula.find"))
        exclude = self.name.text().strip() if mode == 0 else None
        self.matches = matching_references(self.references[mode], self.reference_search.text(), exclude=exclude)
        self.reference_results.clear()
        self.reference_results.addItems([reference.label for reference in self.matches])
        self.reference_results.setCurrentRow(0)
        self.show_reference(self.reference_results.currentRow())

    def show_reference(self, row):
        self.reference_insert.setEnabled(row >= 0)
        self.reference_detail.setText(self.matches[row].detail if row >= 0 else tr("worksheet.formula.no_matches"))

    def insert_reference(self):
        row = self.reference_results.currentRow()
        if row >= 0:
            reference = self.matches[row]
            cursor = self.expression.textCursor()
            cursor.insertText(reference.text)
            if reference.open_arguments:
                cursor.movePosition(QTextCursor.MoveOperation.Left)
            self.expression.setTextCursor(cursor)
            self.expression.setFocus()

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
            if self.column is None:
                candidate.set_formula(name, expression)
            else:
                candidate.set_worksheet_formula(self.column, expression, replace_values=self.replace_values)
        except (ValueError, TypeError, OverflowError) as error:
            self.show_problem(t(translate_message(error, "worksheet.formula.error.")))
            self.expression.setFocus()
            return
        self.result = name, candidate.formulas[name]
        super().accept()
