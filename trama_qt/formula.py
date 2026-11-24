"""Edit calculated columns beside the Qt worksheet."""
from copy import copy

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QComboBox, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from analisi.data import formula_column_references
from analisi.formula_reference import function_references, matching_references, variable_references
from analisi.grid_headings import column_label
from analisi.i18n import active_language, tr, translate_message, ui

_ITALIAN = {"Edit formula": "Modifica formula", "Choose a new column name.": "Scegli un nuovo nome di colonna.",
            "Enter a formula.": "Inserisci una formula.",
            "The worksheet columns changed. Close the editor and reopen the formula.":
                "Le colonne del foglio sono cambiate. Chiudi l’editor e riapri la formula.",
            "Example": "Esempio",
            "A calculated column cannot depend on itself, directly or indirectly.":
                "Una colonna calcolata non può dipendere da sé stessa, direttamente o indirettamente."}

# The expression and result are kept as a pair so the examples can be checked against the engine.
FUNCTION_EXAMPLES = {
    "ABS": ("Absolute value.", "Valore assoluto.", "=ABS(-3)", "3"),
    "ARCTAN2": ("Angle of the point (x, y) in radians. The first argument is y.",
                "Angolo del punto (x, y) in radianti. Il primo argomento è y.", "=ARCTAN2(0, 1)", "0"),
    "BINOMIAL": ("Probability of at least k successes in n independent trials with probability p.",
                 "Probabilità di ottenere almeno k successi in n prove indipendenti con probabilità p.",
                 "=BINOMIAL(1, 2, 0.5)", "0.75"),
    "COS": ("Cosine of an angle in radians. Use RAD to convert degrees.",
            "Coseno di un angolo in radianti. Usa RAD per convertire i gradi.", "=COS(0)", "1"),
    "IF": ("Choose the first result when the condition is true, or the second when it is false.",
           "Sceglie il primo risultato se la condizione è vera, il secondo se è falsa.", "=IF(2 > 1, 3, 4)", "3"),
    "LN": ("Natural logarithm of a positive number.", "Logaritmo naturale di un numero positivo.", "=LN(1)", "0"),
    "LOG": ("Base-10 logarithm of a positive number.", "Logaritmo in base 10 di un numero positivo.",
            "=LOG(1000)", "3"),
    "POWER": ("Raise a number to the given exponent.", "Eleva un numero all’esponente indicato.",
              "=POWER(2, 3)", "8"),
    "ROUND": ("Round to the given number of decimal places.",
              "Arrotonda al numero di decimali indicato.", "=ROUND(-2.345, 2)", "-2.35"),
    "SUM": ("Add values across a row when given several arguments, or down a column with one argument.",
            "Somma i valori sulla riga con più argomenti, o lungo la colonna con un solo argomento.",
            "=SUM(2, 3, 5)", "10"),
}


def t(text):
    return _ITALIAN.get(text, ui(text)) if active_language() == "it" else text


class FormulaEditor(QWidget):
    """Keep edits in this panel until the window commits a validated formula."""

    apply_requested = Signal()
    cancelled = Signal()

    def __init__(self, dataset, name="", *, column=None):
        super().__init__()
        self.setMinimumWidth(252)
        self.dataset = dataset
        self.columns = dataset.columns
        self.column = column
        self.replace_values = column is not None and dataset.column_has_values(column)
        if column is not None:
            name = dataset.columns[column]
        layout = QVBoxLayout(self)
        heading = QLabel(tr("worksheet.formula.title"))
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        contents = QWidget()
        form = QFormLayout(contents)
        form.setContentsMargins(0, 0, 6, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.scroll.setWidget(contents)
        layout.addWidget(self.scroll, 1)
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
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setTextFormat(Qt.TextFormat.PlainText)
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        form.addRow(self.problem)
        self.name.textChanged.connect(lambda: self.show_problem(""))
        self.expression.textChanged.connect(lambda: self.show_problem(""))
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.addButton(
            tr("worksheet.formula.replace" if self.replace_values else "graph.format.apply"),
            QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setObjectName("primary")
        self.apply_button.setAutoDefault(False)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setText(tr("setup.cancel"))
        buttons.accepted.connect(self.apply_requested)
        buttons.rejected.connect(self.cancelled)
        layout.addWidget(buttons)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.cancelled.emit,
                  Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.name.textEdited.connect(self.load_existing)

    def focus_input(self):
        (self.expression if self.column is not None or self.name.text() else self.name).setFocus()

    def add_references(self, form):
        self.references = (variable_references(self.dataset), function_references())
        self.reference_group = QComboBox()
        self.reference_group.addItems([tr("worksheet.formula.columns"), tr("worksheet.formula.functions")])
        form.addRow(self.reference_group)
        bar = QHBoxLayout()
        self.reference_search = QLineEdit()
        self.reference_search.setClearButtonEnabled(True)
        self.reference_insert = QPushButton(tr("worksheet.formula.insert"))
        self.reference_insert.setAutoDefault(False)
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
        if watched in (self.reference_search, self.reference_results) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.insert_reference()
                return True
            if (watched is self.reference_search and self.matches and event.modifiers() == Qt.KeyboardModifier.NoModifier
                    and key in (Qt.Key.Key_Up, Qt.Key.Key_Down)):
                direction = -1 if key == Qt.Key.Key_Up else 1
                row = self.reference_results.currentRow() + direction
                self.reference_results.setCurrentRow(max(0, min(len(self.matches) - 1, row)))
                return True
        return super().eventFilter(watched, event)

    def filter_references(self):
        mode = self.reference_group.currentIndex()
        self.reference_search.setPlaceholderText(tr("worksheet.formula.search_functions" if mode
                                                    else "worksheet.formula.find"))
        exclude = self.name.text().strip() if mode == 0 else None
        query = self.reference_search.text()
        self.matches = matching_references(self.references[mode], query, exclude=exclude)
        if mode and (needle := query.strip().casefold()):
            self.matches.sort(key=lambda reference: (reference.name.casefold() != needle,
                                                    not reference.name.casefold().startswith(needle)))
        self.reference_results.clear()
        self.reference_results.addItems([reference.label for reference in self.matches])
        self.reference_results.setCurrentRow(0)
        self.show_reference(self.reference_results.currentRow())

    def show_reference(self, row):
        self.reference_insert.setEnabled(row >= 0)
        if row < 0:
            self.reference_detail.setText(tr("worksheet.formula.no_matches"))
            return
        reference = self.matches[row]
        detail = reference.detail
        if reference.open_arguments and reference.name in FUNCTION_EXAMPLES:
            english, italian, expression, result = FUNCTION_EXAMPLES[reference.name]
            description = italian if active_language() == "it" else english
            detail += f"\n{description}\n{t('Example')} · {expression} → {result}"
        self.reference_detail.setText(detail)

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
        if text:
            self.scroll.ensureWidgetVisible(self.problem, 0, 0)

    def referenced_columns(self):
        """Parse the draft with the same letter binding used when committing an in-place formula."""
        if self.dataset.columns != self.columns:
            return ()
        try:
            names = formula_column_references(self.expression.toPlainText(),
                                              worksheet_columns=self.columns if self.column is not None else None)
        except ValueError:
            return ()
        return tuple(index for index, name in enumerate(self.columns) if name in names)

    def validated_formula(self):
        if self.dataset.columns != self.columns:
            self.show_problem(t("The worksheet columns changed. Close the editor and reopen the formula."))
            return None
        name, expression = self.name.text().strip(), self.expression.toPlainText().strip()
        if not name:
            self.show_problem(t("Choose a new column name."))
            self.name.setFocus()
            return None
        if not expression:
            self.show_problem(t("Enter a formula."))
            self.expression.setFocus()
            return None
        try:
            candidate = copy(self.dataset)
            if self.column is None:
                candidate.set_formula(name, expression)
            else:
                candidate.set_worksheet_formula(self.column, expression, replace_values=self.replace_values)
        except (ValueError, TypeError, OverflowError) as error:
            self.show_problem(t(translate_message(error, "worksheet.formula.error.")))
            self.expression.setFocus()
            return None
        return name, candidate.formulas[name]
