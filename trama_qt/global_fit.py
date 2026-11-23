"""Qt editors for Global fit custom equation: the coefficient list and the per-series constraints.

The recipe keeps the canonical records of :mod:`analisi.global_custom_fit`:

* ``Parameters``: ``{name, start, lower, upper, fixed, shared}``. Local, Shared and Fixed write ``fixed`` and
  ``shared``; a fixed coefficient keeps its value in ``start`` (the convention of the engine). A blank limit is
  ``None``.
* ``Series constraints``: ``[{series, parameters: {name: {fixed|lower|upper|initial: number}}}]``. A missing key
  inherits the common setting.

Both editors work on their own copies of the records: nothing reaches the caller until the analysis dialog is
confirmed, and Cancel leaves the caller's recipe as it was. The rules (limits, sharing, conditional thresholds,
identifiability) stay in :func:`check_options`, called before the worker starts. This module does not import
tkinter.
"""
import ast
from copy import deepcopy
import math
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSplitter,
                               QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from analisi import global_uncertainty as uncertainty
from analisi.custom_equations import (ARITHMETIC, CONDITIONAL, CONDITIONAL_RESERVED, MAX_PARAMETERS, RESERVED,
                                      _tokens, compile_equation, syntax_of)
from analisi.custom_fit import LEVEL, POINTS, SD_COLUMN, SYNTAX
from analisi.data import decimal_comma
from analisi.field_error import FieldError
from analisi.fit_weights import INVERSE_VARIANCE, UNWEIGHTED
from analisi.global_custom_fit import (DEFAULT_LEVEL, DEFAULT_POINTS, EXAMPLE_PARAMETERS, GLOBAL_CUSTOM_EQUATION,
                                       PARAMETER_LIST, SERIES_LIST, TABS, check_options, series_in)
from analisi.i18n import active_language, tr, translate_message
from analisi.parameter_intervals import METHOD as INTERVAL_METHOD, WALD
from analisi.repeated_input import decode_series_constraints

SCOPES = ("Local", "Shared", "Fixed")
SCOPE_KEYS = {"Local": "gfit.scope.local", "Shared": "gfit.scope.shared", "Fixed": "gfit.scope.fixed"}
OVERRIDE_KEYS = ("initial", "lower", "upper", "fixed")
# Pages of the dialog after Variables, in the order of the classic dialog; Output is the Options page.
PAGES = ("Equation", "Parameters", "Series constraints", "Response")
PAGE_KEYS = {"Equation": "gfit.tab.equation", "Parameters": "gfit.tab.parameters",
             "Series constraints": "gfit.tab.series", "Response": "gfit.tab.response"}
# Captions of the classic dialog (tramastat.GLOBAL_LABEL_KEYS): the recipe keeps the English keys.
LABEL_KEYS = {"X": "gfit.field.X", "Y": "gfit.field.Y", "Group": "gfit.field.Group",
              "Equation": "gfit.field.Equation", "Parameters": "gfit.field.Parameters",
              "Series constraints": "gfit.field.Series constraints", "Weighting": "gfit.field.Weighting",
              SD_COLUMN: "gfit.field.SD column", LEVEL: "gfit.field.Confidence level (%)",
              POINTS: "gfit.field.Curve points", INTERVAL_METHOD: "parameter_ci.method",
              SYNTAX: "conditional.field.syntax",
              **{name: "gfit.field." + name for name in TABS["Response"]}}
CHOICE_KEYS = {"None": "gfit.choice.none", "Confidence": "gfit.choice.confidence",
               "Prediction": "gfit.choice.prediction", "Filled": "gfit.choice.filled", "Lines": "gfit.choice.lines"}
# The value the engine reads when a key is missing. A new key equal to it is not written into the recipe, so a
# saved recipe confirmed without changes comes back identical (the classic dialog drops the same keys).
ENGINE_DEFAULTS = {SYNTAX: ARITHMETIC, SD_COLUMN: None, LEVEL: DEFAULT_LEVEL, POINTS: DEFAULT_POINTS,
                   INTERVAL_METHOD: WALD, uncertainty.CURVE_BAND: uncertainty.NONE,
                   uncertainty.RESPONSE_LEVEL: uncertainty.DEFAULT_RESPONSE_LEVEL,
                   uncertainty.BAND_DRAWING: uncertainty.FILLED, uncertainty.PREDICT: False,
                   uncertainty.QUERY_X: None, uncertainty.QUERY_GROUP: None,
                   uncertainty.QUERY_INTERVAL: uncertainty.NONE, uncertainty.QUERY_K: None,
                   uncertainty.EXTRAPOLATE: False}
SERIES_ROLES = ("X", "Y", "Group", "Weighting", SD_COLUMN)

_TEXT = {
    "name": ("Name", "Nome"),
    "start": ("Start / fixed value", "Valore iniziale / fissato"),
    "lower": ("Lower", "Inferiore"),
    "upper": ("Upper", "Superiore"),
    "scope": ("Scope", "Ambito"),
    "read": ("Read from equation", "Leggi dall'equazione"),
    "read_done": ("Read {count} coefficient(s) from the equation, in order of appearance.",
                  "Letti {count} coefficienti dall'equazione, nell'ordine in cui compaiono."),
    "removed": ("Removed (no longer in the equation): {names}.", "Rimossi (non più nell'equazione): {names}."),
    "missing": ("In the equation but not in the list: {names}. Use Read from equation.",
                "Nell'equazione ma non nell'elenco: {names}. Usa Leggi dall'equazione."),
    "max": ("Use at most {count} coefficients.", "Usa al massimo {count} coefficienti."),
    "series_title": ("Overrides for one series. A blank field inherits the common setting shown in grey.",
                     "Vincoli per una serie. Un campo vuoto eredita l'impostazione comune mostrata in grigio."),
    "series_list": ("Selected series", "Serie selezionate"),
    "coefficient": ("Coefficient", "Coefficiente"),
    "initial": ("Start", "Iniziale"),
    "fixed": ("Fixed value", "Valore fisso"),
    "model_default": ("From model", "Da modello"),
    "estimated": ("estimated", "stimato"),
    "local_tag": ("Local", "Locale"),
    "shared_tag": ("Shared · all series", "Condiviso · tutte le serie"),
    "fixed_tag": ("Fixed · all series", "Fisso · tutte le serie"),
    "unknown_tag": ("Not a coefficient", "Non è un coefficiente"),
    "shared_note": ("A shared coefficient has one value for every series: its start and value stay on Parameters, "
                    "and a limit set here applies to all series (the shared range is the intersection).",
                    "Un coefficiente condiviso ha un solo valore per tutte le serie: iniziale e valore restano in "
                    "Coefficienti, e un limite impostato qui vale per tutte le serie (l'intervallo comune è "
                    "l'intersezione)."),
    "fixed_note": ("A coefficient that is Fixed on Parameters is fixed for every series.",
                   "Un coefficiente Fisso in Coefficienti è fissato per tutte le serie."),
    "shared_tip": ("Shared: set the start or the value on Parameters.",
                   "Condiviso: imposta iniziale o valore in Coefficienti."),
    "fixed_tip": ("Fixed for every series on Parameters.", "Fissato per tutte le serie in Coefficienti."),
    "clear": ("Clear this series", "Azzera questa serie"),
    "clear_all": ("Clear all", "Azzera tutto"),
    "prune": ("Remove non-applicable constraints", "Rimuovi vincoli non applicabili"),
    "outside": ("outside the data", "fuori dai dati"),
    "outside_list": ("Constraints for series not in the complete rows: {names}.",
                     "Vincoli per serie assenti dalle righe complete: {names}."),
    "leftover": ("Constraints for coefficients no longer in the list: {names}.",
                 "Vincoli per coefficienti non più nell'elenco: {names}."),
    "none": ("Select the source columns on the Variables tab to list the available series.",
             "Seleziona le colonne nella scheda Variabili per vedere le serie disponibili."),
    "pruned": ("Removed {count} non-applicable constraint(s).", "Rimossi {count} vincoli non applicabili."),
}


def text(key, **values):
    english, italian = _TEXT[key]
    shown = italian if active_language() == "it" else english
    return shown.format(**values) if values else shown


# -- recipe values ------------------------------------------------------------------------------------------
def shown_number(value):
    """A recipe number as the user reads it: 1.0 is "1", None is blank."""
    if value is None:
        return ""
    if isinstance(value, float):
        shown = repr(value)
        return shown[:-2] if shown.endswith(".0") else shown
    return str(value)


def parse_number(raw):
    """``None`` for a blank field, a float for a finite number (decimal comma accepted), else ``ValueError``."""
    raw = (raw or "").strip()
    if not raw:
        return None
    value = float(decimal_comma(raw))
    if not math.isfinite(value):
        raise ValueError(raw)
    return value


def scope_of(record):
    if record.get("fixed"):
        return "Fixed"
    if record.get("shared"):
        return "Shared"
    return "Local"


def equation_names(equation, syntax=ARITHMETIC):
    """Coefficient names in order of first appearance, read with the tokenizer of the equation compiler.

    The names are checked by :func:`compile_equation` (syntax, reserved words, length), so an equation that
    does not compile raises its ``FieldError`` instead of returning a partial list.
    """
    syntax = syntax_of(syntax)
    tokens = _tokens(equation or "", syntax)
    reserved = CONDITIONAL_RESERVED if syntax == CONDITIONAL else RESERVED
    names = []
    for position, (kind, value, _) in enumerate(tokens):
        following = tokens[position + 1] if position + 1 < len(tokens) else ("end", None, 0)
        if kind == "name" and value not in reserved and following[:2] != ("op", "(") and value not in names:
            names.append(value)
    compile_equation(equation, names, syntax=syntax)
    return names


def loose_names(equation, syntax=ARITHMETIC):
    """The names of :func:`equation_names`, or ``None`` while the equation does not compile."""
    try:
        return equation_names(equation, syntax)
    except (ValueError, OverflowError):
        return None


# -- messages -----------------------------------------------------------------------------------------------
_GROUP_PREFIX = re.compile(r"Group (?P<group>.+?): (?P<rest>.*)\Z", re.DOTALL)


def _custom_message(message):
    """The Fit custom equation sentences (as analisi.custom_equation_dialog.translate_error, without Tk)."""
    match = _GROUP_PREFIX.match(message)
    if match and not message.startswith("Group must"):
        return tr("custom.group_prefix", group=match["group"]) + " " + _custom_message(match["rest"])
    translated = translate_message(message, "conditional.error.")
    if translated == message:
        translated = translate_message(message, "custom.error.")
    if translated == message:
        translated = translate_message(message, "parameter_ci.error.")
    return translated


def translate_error(message):
    """A global-fit message in the active language (as analisi.global_custom_dialog.translate_error)."""
    message = str(message)
    match = _GROUP_PREFIX.match(message)
    if match and not message.startswith("Group must") and not message.startswith("Group is required"):
        return tr("custom.group_prefix", group=match["group"]) + " " + translate_error(match["rest"])
    translated = translate_message(message, "gfit.error.")
    if translated != message:
        return translated
    translated = translate_message(message, "gfit.response.error.")
    if translated != message:
        return translated
    return _custom_message(message)


def field_caption(label):
    key = LABEL_KEYS.get(label)
    shown = tr(key) if key else label
    return label if shown == key else shown


def describe_error(error, field=None):
    """The banner text: the translated message, led by the translated field when it does not name it."""
    message = translate_error(error)
    if field:
        label = field_caption(field)
        if label not in message:
            message = f"{label}: {message}"
    return message


def _series_prefix(message):
    """``(label, coefficient)`` from an engine sentence that starts with Series 'label'[, name]."""
    match = re.match(r"Series (?P<label>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")"
                     r"(?:, (?P<name>[A-Za-z][A-Za-z0-9_]*))?", message)
    if not match:
        return None, None
    try:
        label = ast.literal_eval(match["label"])
    except (ValueError, SyntaxError):
        return None, None
    return str(label), match["name"]


def _key_in(message, fallback=None):
    lowered = message.lower()
    for key, words in (("lower", ("lower",)), ("upper", ("upper",)), ("fixed", ("fixed",)),
                       ("initial", ("initial", "starting value", " start"))):
        if any(word in lowered for word in words):
            return key
    return fallback


# -- coefficients -------------------------------------------------------------------------------------------
class ScopeDelegate(QStyledItemDelegate):
    """Local, Shared or Fixed in a combo box; the item keeps the canonical value in UserRole."""

    def createEditor(self, parent, _option, _index):
        box = QComboBox(parent)
        for scope in SCOPES:
            box.addItem(tr(SCOPE_KEYS[scope]), scope)
        box.activated.connect(lambda _=None, box=box: self.commitData.emit(box))
        return box

    def setEditorData(self, editor, index):
        editor.setCurrentIndex(max(0, editor.findData(index.data(Qt.ItemDataRole.UserRole))))

    def setModelData(self, editor, model, index):
        scope = editor.currentData() or "Local"
        model.setData(index, scope, Qt.ItemDataRole.UserRole)
        model.setData(index, tr(SCOPE_KEYS[scope]), Qt.ItemDataRole.DisplayRole)


class GlobalCoefficientEditor(QWidget):
    """Name, start (or fixed value), lower, upper and scope of each coefficient of the global equation."""

    changed = Signal()
    NAME, START, LOWER, UPPER, SCOPE = range(5)
    KEYS = ("name", "start", "lower", "upper", "scope")

    def __init__(self, records, *, equation, syntax, parent=None):
        super().__init__(parent)
        self.equation, self.syntax = equation, syntax
        self.problem = None
        self.read_note = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("globalCoefficients")
        self.table.setAccessibleName(tr("gfit.field.Parameters"))
        self.table.setHorizontalHeaderLabels([text(key) for key in self.KEYS])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers
                                   & ~QAbstractItemView.EditTrigger.CurrentChanged)
        self.table.setItemDelegateForColumn(self.SCOPE, ScopeDelegate(self.table))
        self.table.setMinimumHeight(170)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.add_button = QPushButton(tr("gfit.add"))
        self.remove_button = QPushButton(tr("gfit.remove"))
        self.read_button = QPushButton(text("read"))
        for button, command in ((self.add_button, self.add), (self.remove_button, self.remove),
                                (self.read_button, self.read_equation)):
            button.setAutoDefault(False)
            button.clicked.connect(command)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        note = QLabel(tr("gfit.parameters_note"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setObjectName("notice")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        for record in records if isinstance(records, (list, tuple)) else ():
            if isinstance(record, dict):
                self._append(shown_number(record.get("name")), shown_number(record.get("start")),
                             shown_number(record.get("lower")), shown_number(record.get("upper")),
                             scope_of(record))
        self.table.itemChanged.connect(self._edited)
        self.mark()

    # rows
    def _append(self, name, start="1", lower="", upper="", scope="Local"):
        row = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(row)
        for column, value in enumerate((name, start, lower, upper)):
            self.table.setItem(row, column, QTableWidgetItem(value))
        item = QTableWidgetItem(tr(SCOPE_KEYS[scope]))
        item.setData(Qt.ItemDataRole.UserRole, scope)
        self.table.setItem(row, self.SCOPE, item)
        self.table.blockSignals(False)
        return row

    def cell(self, row, column):
        item = self.table.item(row, column)
        return item.text() if item is not None else ""

    def rows(self):
        """The rows as typed: name, start, lower, upper (text) and the canonical scope."""
        found = []
        for row in range(self.table.rowCount()):
            scope = self.table.item(row, self.SCOPE).data(Qt.ItemDataRole.UserRole) or "Local"
            found.append({"name": self.cell(row, self.NAME).strip(), "start": self.cell(row, self.START),
                          "lower": self.cell(row, self.LOWER), "upper": self.cell(row, self.UPPER),
                          "scope": scope if scope in SCOPES else "Local"})
        return found

    def names(self):
        return [row["name"] for row in self.rows() if row["name"]]

    def set_scope(self, row, scope):
        item = self.table.item(row, self.SCOPE)
        item.setData(Qt.ItemDataRole.UserRole, scope)
        item.setText(tr(SCOPE_KEYS[scope]))

    def set_cell(self, row, column, value):
        self.table.item(row, column).setText(value)

    def _edited(self, _item=None):
        self.problem = None
        self.mark()
        self.changed.emit()

    def free_name(self):
        used = set(self.names())
        reserved = CONDITIONAL_RESERVED if self.syntax() == CONDITIONAL else RESERVED
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWZ":
            if letter not in used and letter not in reserved:
                return letter
        return f"P{self.table.rowCount() + 1}"

    def add(self):
        if self.table.rowCount() >= MAX_PARAMETERS:
            self.status.setText(text("max", count=MAX_PARAMETERS))
            return
        row = self._append(self.free_name())
        self.focus_cell(row, self.NAME, edit=True)
        self._edited()

    def remove(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)
        if self.table.rowCount():
            self.table.setCurrentCell(min(row, self.table.rowCount() - 1), self.NAME)
        self._edited()

    def read_equation(self):
        """Rebuild the list from the equation; rows still in it keep start, limits, value and scope."""
        try:
            names = equation_names(self.equation(), self.syntax())
        except (ValueError, OverflowError) as error:
            self.read_note = ""
            self.status.setText(describe_error(error, getattr(error, "field", None)))
            self.status.setVisible(True)
            return False
        kept = {row["name"]: row for row in self.rows() if row["name"]}
        removed = [name for name in kept if name not in names]
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        for name in names[:MAX_PARAMETERS]:
            row = kept.get(name, {"start": "1", "lower": "", "upper": "", "scope": "Local"})
            self._append(name, row["start"], row["lower"], row["upper"], row["scope"])
        lines = [text("read_done", count=min(len(names), MAX_PARAMETERS))]
        if removed:
            lines.append(text("removed", names=", ".join(removed)))
        self.read_note = " ".join(lines)
        if self.table.rowCount():
            self.table.setCurrentCell(0, self.NAME)
        self._edited()
        return True

    def mark(self):
        """Unused coefficients and names of the equation that the list does not declare."""
        lines = [self.read_note] if self.read_note else []
        present = loose_names(self.equation(), self.syntax())
        if present is not None:
            listed = self.names()
            unused = [name for name in listed if name not in present]
            missing = [name for name in present if name not in listed]
            if unused:
                lines.append(tr("gfit.unused", names=", ".join(unused)))
            if missing:
                lines.append(text("missing", names=", ".join(missing)))
        self.status.setText(" ".join(lines))
        self.status.setVisible(bool(lines))

    # values
    def values(self):
        """Canonical records. A number that does not read as a finite number is a Parameters error here."""
        records = []
        for row, values in enumerate(self.rows()):
            name = values["name"]
            if not name and not any(values[key].strip() for key in ("start", "lower", "upper")):
                continue
            fixed, shared = values["scope"] == "Fixed", values["scope"] == "Shared"
            numbers = {}
            for key, column in (("start", self.START), ("lower", self.LOWER), ("upper", self.UPPER)):
                try:
                    numbers[key] = parse_number(values[key])
                except ValueError:
                    numbers[key] = None
                    message = (f"{name}: the {key} limit must be a finite number or empty." if key != "start"
                               else f"{name}: the value must be a finite number." if fixed
                               else f"{name}: the starting value must be a finite number.")
                    self.problem = (row, column)
                    raise FieldError("Parameters", message) from None
            if numbers["start"] is None:
                self.problem = (row, self.START)
                raise FieldError("Parameters", f"{name}: the value must be a finite number." if fixed
                                 else f"{name}: the starting value must be a finite number.")
            records.append({"name": name, "start": numbers["start"], "lower": numbers["lower"],
                            "upper": numbers["upper"], "fixed": fixed, "shared": shared})
        self.problem = None
        return records

    # focus
    def focus_cell(self, row, column, *, edit=False):
        if not 0 <= row < self.table.rowCount():
            self.table.setFocus()
            return
        self.table.setCurrentCell(row, column)
        self.table.scrollToItem(self.table.item(row, column))
        self.table.setFocus()
        if edit:
            self.table.editItem(self.table.item(row, column))

    def focus_problem(self, error=None):
        """Put the cursor on the cell the error is about: a located value error, else the named coefficient."""
        if self.problem is not None:
            self.focus_cell(*self.problem)
            return True
        message = str(error or "")
        names = self.names()
        row = None
        match = re.match(r"(?:Coefficient name |The coefficient )?(?P<name>[A-Za-z][A-Za-z0-9_]*)", message)
        if match and match["name"] in names:
            row = names.index(match["name"])
            if message.startswith("The coefficient") and names.count(match["name"]) > 1:
                row = [i for i, name in enumerate(names) if name == match["name"]][1]
        elif message.startswith("The equation does not use "):
            unused = message[len("The equation does not use "):].split(".")[0].split(", ")
            row = names.index(unused[0]) if unused and unused[0] in names else None
        if row is None:
            self.focus_cell(max(0, self.table.currentRow()), self.NAME)
            return True
        lowered = message.lower()
        if "coefficient name" in lowered or "reserved" in lowered or "more than once" in lowered \
                or "word of the conditional" in lowered or "does not use" in lowered:
            column = self.NAME
        elif "lower" in lowered:
            column = self.LOWER
        elif "upper" in lowered:
            column = self.UPPER
        elif "shared" in lowered or "true or false" in lowered or "condition" in lowered:
            column = self.SCOPE
        else:
            column = self.START
        self.focus_cell(row, column)
        return True


# -- series constraints -------------------------------------------------------------------------------------
class GlobalSeriesEditor(QWidget):
    """Per-series overrides: one series at a time, one row of fields per coefficient."""

    changed = Signal()

    def __init__(self, saved, *, coefficients, series, parent=None):
        super().__init__(parent)
        self.coefficients, self.series_labels = coefficients, series
        self.edits, self.load_error = {}, None
        self.available, self.series, self.fields, self.problem = [], None, {}, None
        self._read(saved)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(text("series_title"))
        title.setObjectName("muted")
        title.setWordWrap(True)
        layout.addWidget(title)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        caption = QLabel(text("series_list"))
        caption.setWordWrap(True)
        left_layout.addWidget(caption)
        self.list = QListWidget()
        self.list.setObjectName("globalSeries")
        self.list.setAccessibleName(text("series_list"))
        self.list.currentItemChanged.connect(self._picked)
        left_layout.addWidget(self.list, 1)
        caption.setBuddy(self.list)
        splitter.addWidget(left)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        splitter.addWidget(self.scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 430])
        layout.addWidget(splitter, 1)
        buttons = QHBoxLayout()
        self.clear_button = QPushButton(text("clear"))
        self.clear_all_button = QPushButton(text("clear_all"))
        self.prune_button = QPushButton(text("prune"))
        for button, command in ((self.clear_button, self.clear_series), (self.clear_all_button, self.clear_all),
                                (self.prune_button, self.prune)):
            button.setAutoDefault(False)
            button.clicked.connect(command)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.warning = QLabel()
        self.warning.setObjectName("notice")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)
        self.refresh_series()

    def _read(self, saved):
        if saved is None:
            saved = []
        try:
            decoded = decode_series_constraints(deepcopy(saved))
        except ValueError as error:
            self.load_error = str(error)
            return
        for label, parameters in decoded.items():
            self.edits[label] = {str(name): {k: shown_number(v) for k, v in fields.items()}
                               for name, fields in parameters.items() if isinstance(fields, dict)}

    # series
    def refresh_series(self):
        """Series of the complete rows (recomputed when X, Y, Group or the SD column change)."""
        try:
            self.available = list(self.series_labels())
        except (ValueError, TypeError, OverflowError):
            self.available = []
        labels = [*self.available, *[label for label in self.edits if label not in self.available]]
        current = self.series if self.series in labels else (labels[0] if labels else None)
        self.list.blockSignals(True)
        self.list.clear()
        for label in labels:
            shown = str(label) if label in self.available else f"{label}  · {text('outside')}"
            item = QListWidgetItem(shown)
            item.setData(Qt.ItemDataRole.UserRole, label)
            item.setToolTip(repr(label))
            if label in self.edits:
                font = item.font()
                font.setWeight(QFont.Weight.Bold)
                item.setFont(font)
            if label not in self.available:
                item.setForeground(Qt.GlobalColor.darkRed)
            self.list.addItem(item)
            if label == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.series = current
        self.refresh_coefficients()

    def labels(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _picked(self, item, _previous=None):
        self.series = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        self.refresh_coefficients()

    def select_series(self, label):
        for index in range(self.list.count()):
            if self.list.item(index).data(Qt.ItemDataRole.UserRole) == label:
                self.list.setCurrentRow(index)
                return True
        return False

    # coefficient rows of the selected series
    def _common(self):
        try:
            rows = self.coefficients()
        except (ValueError, TypeError):
            rows = []
        return [row for row in rows if row.get("name")]

    def refresh_coefficients(self):
        common = self._common()
        declared = [row["name"] for row in common]
        saved = self.edits.get(self.series, {}) if self.series is not None else {}
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        headings = (text("coefficient"), text("scope"), text("initial"), tr("gfit.series.lower"),
                    tr("gfit.series.upper"), text("fixed"))
        for column, heading in enumerate(headings):
            label = QLabel(heading)
            label.setObjectName("sectionTitle")
            grid.addWidget(label, 0, column)
        self.fields = {}
        rows = [*common, *[{"name": name, "scope": None} for name in saved if name not in declared]]
        shared = fixed = False
        for position, row in enumerate(rows, start=1):
            name, scope = row["name"], row.get("scope")
            grid.addWidget(QLabel(name), position, 0)
            tag = {"Local": text("local_tag"), "Shared": text("shared_tag"), "Fixed": text("fixed_tag")}.get(
                scope, text("unknown_tag"))
            tag_label = QLabel(tag)
            tag_label.setObjectName("muted" if scope else "notice")
            grid.addWidget(tag_label, position, 1)
            shared |= scope == "Shared"
            fixed |= scope == "Fixed"
            inherited = self._inherited(row)
            for column, key in enumerate(OVERRIDE_KEYS, start=2):
                field = QLineEdit(saved.get(name, {}).get(key, ""))
                field.setObjectName(f"override:{name}:{key}")
                field.setAccessibleName(f"{self.series} · {name} · {key}")
                field.setPlaceholderText(inherited[key])
                field.setMinimumWidth(64)
                blocked = (scope in ("Shared", "Fixed") and key in ("initial", "fixed")) or self.series is None
                if blocked and not field.text():
                    field.setEnabled(False)
                    field.setToolTip(text("shared_tip" if scope == "Shared" else "fixed_tip"))
                field.textEdited.connect(lambda _text, name=name, key=key: self._typed(name, key))
                grid.addWidget(field, position, column)
                self.fields[(name, key)] = field
        grid.setColumnStretch(0, 0)
        for column in range(2, 6):
            grid.setColumnStretch(column, 1)
        grid.setRowStretch(len(rows) + 1, 1)
        self.scroll.setWidget(body)
        notes = []
        if shared:
            notes.append(text("shared_note"))
        if fixed:
            notes.append(text("fixed_note"))
        self.note.setText(" ".join(notes))
        self.note.setVisible(bool(notes))
        self._warn(declared)

    def _inherited(self, row):
        """The common setting shown in grey in each blank field."""
        scope = row.get("scope")
        if scope is None:
            return dict.fromkeys(OVERRIDE_KEYS, "")
        default = text("model_default") if row.get("model_defaults") else None
        start = row.get("start", "").strip() or default or "1"
        lower = row.get("lower", "").strip() or default or "−∞"
        upper = row.get("upper", "").strip() or default or "+∞"
        if scope == "Fixed":
            return {"initial": "", "lower": lower, "upper": upper, "fixed": start}
        if scope == "Shared":
            return {"initial": start, "lower": lower, "upper": upper, "fixed": text("estimated")}
        return {"initial": start, "lower": lower, "upper": upper, "fixed": text("estimated")}

    def _typed(self, name, key):
        if self.series is None:
            return
        self.problem = None
        value = self.fields[(name, key)].text()
        overrides = self.edits.setdefault(self.series, {})
        settings = overrides.setdefault(name, {})
        if value.strip():
            settings[key] = value
        else:
            settings.pop(key, None)
        if not settings:
            overrides.pop(name, None)
        if not overrides:
            self.edits.pop(self.series, None)
        item = self.list.currentItem()
        if item is not None:
            font = item.font()
            font.setWeight(QFont.Weight.Bold if self.series in self.edits else QFont.Weight.Normal)
            item.setFont(font)
        self._warn([row["name"] for row in self._common()])
        self.changed.emit()

    def set_override(self, label, name, key, value):
        """Type ``value`` into one field of one series (used by tests and the smoke)."""
        self.select_series(label)
        field = self.fields[(name, key)]
        field.setEnabled(True)
        field.setText(value)
        self._typed(name, key)

    def _inapplicable(self, declared):
        outside = [label for label in self.edits if label not in self.available]
        leftover = sorted({name for label, overrides in self.edits.items() if label in self.available
                           for name in overrides if name not in declared})
        return outside, leftover

    def _warn(self, declared):
        outside, leftover = self._inapplicable(declared)
        lines = []
        if self.load_error:
            lines.append(translate_error(self.load_error))
        if not self.available and not self.edits and not self.load_error:
            lines.append(text("none"))
        if outside:
            lines.append(text("outside_list", names=", ".join(repr(label) for label in outside)))
        if leftover:
            lines.append(text("leftover", names=", ".join(leftover)))
        self.warning.setText(" ".join(lines))
        self.warning.setVisible(bool(lines))
        self.prune_button.setEnabled(bool(outside or leftover))
        self.clear_button.setEnabled(self.series in self.edits)
        self.clear_all_button.setEnabled(bool(self.edits or self.load_error))

    # actions
    def clear_series(self):
        if self.series is not None:
            self.edits.pop(self.series, None)
            self.refresh_series()
            self.changed.emit()

    def clear_all(self):
        self.edits.clear()
        self.load_error = None
        self.refresh_series()
        self.changed.emit()

    def prune(self):
        """Remove the overrides of series outside the complete rows and of coefficients no longer listed."""
        declared = {row["name"] for row in self._common()}
        count = 0
        for label in list(self.edits):
            if label not in self.available:
                count += sum(len(fields) for fields in self.edits.pop(label).values())
                continue
            for name in list(self.edits[label]):
                if name not in declared:
                    count += len(self.edits[label].pop(name))
            if not self.edits[label]:
                del self.edits[label]
        self.problem = None
        self.refresh_series()
        self.warning.setText(" ".join(filter(None, [self.warning.text(), text("pruned", count=count)])))
        self.warning.setVisible(True)
        self.changed.emit()
        return count

    # values
    def values(self):
        """The persisted list. A constraint that does not apply to the data is a field error here."""
        if self.load_error:
            raise FieldError("Series constraints", self.load_error)
        self.refresh_series()
        declared = [row["name"] for row in self._common()]
        records = []
        for label, overrides in self.edits.items():
            if label not in self.available:
                name = next(iter(overrides), None)
                self.problem = (label, name, next(iter(overrides.get(name, {})), None))
                raise FieldError("Series constraints", f"Series {label!r} is not among the series with complete "
                                                       "rows. Remove that override or correct the name.")
            parameters = {}
            for name, settings in overrides.items():
                if name not in declared:
                    self.problem = (label, name, next(iter(settings), None))
                    raise FieldError("Series constraints",
                                     f"Series {label!r}, {name} is not a coefficient of this equation. "
                                     "Remove the override or restore the coefficient.")
                numbers = {}
                for key in OVERRIDE_KEYS:
                    if key not in settings:
                        continue
                    try:
                        value = parse_number(settings[key])
                    except ValueError:
                        value = None
                    if value is None:
                        self.problem = (label, name, key)
                        raise FieldError("Series constraints",
                                         f"Series {label!r}, {name}: {key} must be a finite number.")
                    numbers[key] = value
                if numbers:
                    parameters[name] = numbers
            if parameters:
                records.append({"series": label, "parameters": parameters})
        self.problem = None
        return records

    # focus
    def focus_override(self, label, name=None, key=None):
        if label is not None and not self.select_series(label):
            self.list.setFocus()
            return
        field = self.fields.get((name, key)) if name else None
        if field is None and name:
            field = next((self.fields[(n, k)] for (n, k) in self.fields if n == name and self.fields[(n, k)].isEnabled()),
                         None)
        if field is None:
            self.list.setFocus()
            return
        field.setEnabled(True)
        self.scroll.ensureWidgetVisible(field)
        field.setFocus()
        field.selectAll()

    def focus_problem(self, error=None):
        """Select the series and the field the error is about (located here, or named by the engine)."""
        if self.problem is not None:
            self.focus_override(*self.problem)
            return True
        message = str(error or "")
        label, name = _series_prefix(message)
        if label is not None:
            if label not in self.labels():
                self.list.setFocus()
                return True
            self.focus_override(label, name, _key_in(message.split(":", 1)[-1], "lower") if name else None)
            return True
        match = re.match(r"(?P<name>[A-Za-z][A-Za-z0-9_]*): the (shared limits|starting value)", message)
        if match:
            name = match["name"]
            label = next((series for series, overrides in self.edits.items()
                          if name in overrides and series in self.available), self.series)
            self.focus_override(label, name, "lower")
            return True
        self.list.setFocus()
        return True


# -- the analysis dialog ------------------------------------------------------------------------------------
def default_recipe():
    """A new analysis starts from A + B*X with A local and B shared, which this equation uses."""
    from analisi.custom_fit import DEFAULT_EQUATION
    return {"Equation": DEFAULT_EQUATION, "Parameters": [dict(record) for record in EXAMPLE_PARAMETERS],
            "Series constraints": []}


def pages(method):
    """The extra pages of the analysis dialog, after Variables."""
    return [(name, tr(PAGE_KEYS[name])) for name in PAGES] if method == GLOBAL_CUSTOM_EQUATION else []


def page_of(method, label):
    """The page of a field of Global fit custom equation (None: the dialog's usual choice)."""
    if method != GLOBAL_CUSTOM_EQUATION:
        return None
    if label in ("Weighting", SD_COLUMN):
        return "variables"
    for page in PAGES:
        if label in TABS[page]:
            return page
    return None


def build_editor(kind, label, saved, dialog):
    """The Qt editor for a compound kind of Global fit custom equation, or None for another kind."""
    if kind == PARAMETER_LIST:
        return GlobalCoefficientEditor(saved.get(label, ()), equation=lambda: _equation(dialog),
                                       syntax=lambda: _syntax(dialog))
    if kind == SERIES_LIST:
        return GlobalSeriesEditor(saved.get(label, []), coefficients=lambda: _coefficients(dialog),
                                  series=lambda: series_for(dialog))
    return None


def _control(dialog, name):
    return dialog.controls.get(name, (None, None))[1]


def _equation(dialog):
    control = _control(dialog, "Equation")
    return control.toPlainText() if control is not None else ""


def _syntax(dialog):
    control = _control(dialog, SYNTAX)
    value = control.currentData() if control is not None else None
    return value if value in (ARITHMETIC, CONDITIONAL) else ARITHMETIC


def _coefficients(dialog):
    control = _control(dialog, "Parameters")
    return control.rows() if isinstance(control, GlobalCoefficientEditor) else []


def _choice(dialog, name):
    control = _control(dialog, name)
    if control is None:
        return None
    value = control.currentData()
    return value if value is not None else control.currentText()


def series_for(dialog):
    """``series_in`` on the chosen columns. The equation is a placeholder, so a half-typed formula or coefficient
    list does not empty the series list: only X, Y, Group and (for Inverse variance) the SD column count."""
    weighting = _choice(dialog, "Weighting") or UNWEIGHTED
    options = {"X": _choice(dialog, "X"), "Y": _choice(dialog, "Y"), "Group": _choice(dialog, "Group") or None,
               "Equation": "A", "Parameters": [{"name": "A", "start": 1.0, "lower": None, "upper": None,
                                                "fixed": False, "shared": False}],
               "Series constraints": [], "Weighting": weighting,
               SD_COLUMN: (_choice(dialog, SD_COLUMN) or None) if weighting == INVERSE_VARIANCE else None}
    return series_in(dialog.data, options)


def attach(dialog):
    """Translate the captions, then keep the two editors in step with the equation and the columns."""
    if dialog.method != GLOBAL_CUSTOM_EQUATION:
        return
    for label, (caption, widget, _form) in dialog.rows.items():
        if label in LABEL_KEYS:
            caption.setText(field_caption(label))
        if isinstance(widget, QComboBox) and label in (uncertainty.CURVE_BAND, uncertainty.BAND_DRAWING,
                                                        uncertainty.QUERY_INTERVAL):
            for index in range(widget.count()):
                key = CHOICE_KEYS.get(widget.itemData(index))
                if key:
                    widget.setItemText(index, tr(key))
    coefficients = _control(dialog, "Parameters")
    series = _control(dialog, "Series constraints")
    equation = _control(dialog, "Equation")
    syntax = _control(dialog, SYNTAX)
    if isinstance(coefficients, GlobalCoefficientEditor):
        if equation is not None:
            equation.textChanged.connect(coefficients.mark)
        if syntax is not None:
            syntax.currentIndexChanged.connect(lambda _=None: coefficients.mark())
    if isinstance(series, GlobalSeriesEditor):
        if isinstance(coefficients, GlobalCoefficientEditor):
            coefficients.changed.connect(series.refresh_coefficients)
        for name in SERIES_ROLES:
            control = _control(dialog, name)
            if isinstance(control, QComboBox):
                control.currentIndexChanged.connect(lambda _=None: series.refresh_series())
        series.refresh_series()


def confirm(dialog, options):
    """The recipe to run: engine defaults that the saved recipe did not have are left out, then the cheap checks
    of :func:`check_options` (FieldError keeps the dialog open on the field). The fit runs on the worker."""
    if dialog.method != GLOBAL_CUSTOM_EQUATION:
        return options
    saved = dialog.current[1] if dialog.current and dialog.current[0] == dialog.method else {}
    options = dict(options)
    if options.get("Weighting") != INVERSE_VARIANCE:
        options[SD_COLUMN] = None
    for key, default in ENGINE_DEFAULTS.items():
        if key not in saved and key in options and options[key] == default:
            options.pop(key)
    check_options(dialog.data, options)
    return options


__all__ = ["GlobalCoefficientEditor", "GlobalSeriesEditor", "attach", "build_editor", "confirm", "describe_error",
           "equation_names", "page_of", "pages", "series_for"]
