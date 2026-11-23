"""Coefficient and series options for the catalog's joint nonlinear fit."""
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QHeaderView, QLabel, QTableWidget, QTableWidgetItem

from analisi.curve_models import MODELS
from analisi.field_error import FieldError
from analisi.i18n import active_language, tr
from analisi.repeated_input import curve_series_labels
from analisi.repeated_workbench import INPUT_FIELDS, check_global_weighting

from . import global_fit


METHOD = "Global nonlinear regression"
PARAMETERS = "Parameters"
SERIES = "Series constraints"
TABLE = "Catalog global coefficients"


def pages(method):
    if method != METHOD:
        return ()
    return tuple((name, global_fit.field_caption(name)) for name in (PARAMETERS, SERIES))


class CatalogParameters(QTableWidget):
    """The model defines the rows. An empty start or limit uses the model's default."""

    changed = Signal()
    NAME, SCOPE, FIXED, LOWER, UPPER, START, COMPARE = range(7)

    def __init__(self, model, saved):
        super().__init__(0, 7)
        self.model, self.problem = None, None
        self.saved, self.drafts = saved, {}
        gtext = global_fit.text
        compare = "Confronta" if active_language() == "it" else "Compare"
        self.setHorizontalHeaderLabels([gtext("coefficient"), gtext("scope"), gtext("fixed"),
                                        gtext("lower"), gtext("upper"), gtext("initial"), compare])
        self.setAccessibleName(global_fit.field_caption(PARAMETERS))
        self.setItemDelegateForColumn(self.SCOPE, global_fit.ScopeDelegate(self))
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(self.NAME, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().hide()
        self.itemChanged.connect(self._edited)
        self.set_model(model)

    def _scope(self, row):
        return self.item(row, self.SCOPE).data(Qt.ItemDataRole.UserRole)

    def _row(self, row):
        return (self._scope(row),
                *(self.item(row, column).text() for column in range(self.FIXED, self.START + 1)),
                self.item(row, self.COMPARE).checkState() == Qt.CheckState.Checked)

    def set_model(self, model):
        if model == self.model:
            return
        if self.model is not None:
            self.drafts[self.model] = [self._row(row) for row in range(self.rowCount())]
        self.model, self.problem = model, None
        spec = MODELS[model]
        saved = self.saved if self.saved.get("Model") == model else {}
        fixed = saved.get("Fixed parameters") or {}
        shared = saved.get("Shared parameters", spec.required_shared)
        bounds = saved.get("Parameter bounds") or {}
        initial = saved.get("Initial values") or {}
        compare = saved.get("Compare local parameters") or ()
        draft = self.drafts.get(model)
        with QSignalBlocker(self):
            self.setRowCount(len(spec.parameters))
            for row, name in enumerate(spec.parameters):
                state = ("Fixed" if name in fixed else "Shared" if name in shared else "Local",
                         *(global_fit.shown_number(value) for value in
                           (fixed.get(name), *bounds.get(name, (None, None)), initial.get(name))),
                         name in compare)
                scope, constant, lower, upper, start, compared = draft[row] if draft else state
                values = (name, tr(global_fit.SCOPE_KEYS[scope]), constant, lower, upper, start, "")
                for column, value in enumerate(values):
                    self.setItem(row, column, QTableWidgetItem(value))
                self.item(row, self.NAME).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.item(row, self.SCOPE).setData(Qt.ItemDataRole.UserRole, scope)
                self.item(row, self.COMPARE).setCheckState(Qt.CheckState.Checked if compared else Qt.CheckState.Unchecked)
                self._set_scope_flags(row)
        header = self.horizontalHeader().sizeHint().height()
        self.setMinimumHeight(header + min(6, self.rowCount()) * self.verticalHeader().defaultSectionSize() + 6)

    def _set_scope_flags(self, row):
        scope = self._scope(row)
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        edit = base | Qt.ItemFlag.ItemIsEditable
        check = base | Qt.ItemFlag.ItemIsUserCheckable
        self.item(row, self.FIXED).setFlags(edit if scope == "Fixed" else base)
        self.item(row, self.START).setFlags(base if scope == "Fixed" else edit)
        self.item(row, self.COMPARE).setFlags(check if scope == "Local" else base)

    def _edited(self, item):
        self.problem = None
        if item.column() == self.SCOPE:
            with QSignalBlocker(self):
                self._set_scope_flags(item.row())
        self.changed.emit()

    def rows(self):
        for row in range(self.rowCount()):
            scope, constant, lower, upper, start, _ = self._row(row)
            yield {"name": self.item(row, self.NAME).text(), "scope": scope, "lower": lower, "upper": upper,
                   "start": constant if scope == "Fixed" else start, "model_defaults": True}

    def values(self):
        self.problem = None
        shared, fixed, bounds, initial, compared = [], {}, {}, {}, []
        for row in range(self.rowCount()):
            name = self.item(row, self.NAME).text()
            scope, constant, low, high, start, compare = self._row(row)
            low = self._number(row, self.LOWER, low)
            high = self._number(row, self.UPPER, high)
            if low is not None and high is not None and low >= high:
                self._error(row, self.LOWER, "The lower limit must be less than the upper limit.",
                            "Il limite inferiore deve essere minore del limite superiore.")
            if low is not None or high is not None:
                bounds[name] = [low, high]
            if scope == "Local" and name in MODELS[self.model].required_shared:
                self._error(row, self.SCOPE, "Choose Shared or Fixed for this coefficient.",
                            "Scegli Condiviso o Fisso per questo coefficiente.")
            if scope == "Fixed":
                value = self._number(row, self.FIXED, constant)
                if value is None:
                    self._error(row, self.FIXED, "Enter a fixed value.", "Inserisci un valore fisso.")
                fixed[name] = value
                continue
            value = self._number(row, self.START, start)
            if value is not None:
                initial[name] = value
            if scope == "Shared":
                shared.append(name)
            elif compare:
                compared.append(name)
        return {"Shared parameters": shared, "Fixed parameters": fixed, "Parameter bounds": bounds,
                "Initial values": initial, "Compare local parameters": compared}

    def _number(self, row, column, value):
        try:
            return global_fit.parse_number(value)
        except ValueError:
            self._error(row, column, "Enter a finite number.", "Inserisci un numero finito.")

    def _error(self, row, column, english, italian):
        self.problem = row, column
        name = self.item(row, self.NAME).text()
        field = self.horizontalHeaderItem(column).text()
        message = italian if active_language() == "it" else english
        raise FieldError(PARAMETERS, f"{name} · {field}. {message}") from None

    def focus_problem(self, _error=None):
        if self.problem is None:
            return False
        self.setCurrentCell(*self.problem)
        self.setFocus()
        return True


def attach(dialog, forms, saved):
    if dialog.method != METHOD:
        return
    controls = dialog.controls
    model = controls["Model"][1]
    input_format = controls["Input format"][1]
    merge = controls["Merge numbered replicates"][1]
    y_columns = controls["Y columns"][1]
    roles = ("Input format", "X", "Y", "Series", "Model")

    def labels():
        selection = {role: controls[role][1].currentData() for role in roles}
        selection["Merge numbered replicates"] = merge.isChecked()
        selection["Y columns"] = [y_columns.item(i).text() for i in range(y_columns.count())
                                  if y_columns.item(i).checkState() == Qt.CheckState.Checked]
        return curve_series_labels(dialog.data, selection)

    parameters = CatalogParameters(model.currentData(), saved)
    series = global_fit.GlobalSeriesEditor(saved.get(SERIES), coefficients=parameters.rows, series=labels)
    for name, kind, editor in ((PARAMETERS, TABLE, parameters), (SERIES, global_fit.SERIES_LIST, series)):
        form = forms[name]
        form.addRow(editor)
        dialog.controls[name] = kind, editor
        dialog.rows[name] = None, editor, form

    note = QLabel("Lascia vuoti i valori iniziali e i limiti per usare quelli del modello."
                  if active_language() == "it" else "Leave starts and limits blank to use the model defaults.")
    note.setWordWrap(True)
    note.setObjectName("muted")
    forms[PARAMETERS].addRow(note)

    drafts = {}

    def switch_model():
        drafts[parameters.model] = (series.edits, series.load_error, series.series)
        parameters.set_model(model.currentData())
        series.edits, series.load_error, series.series = drafts.get(parameters.model, ({}, None, None))
        series.problem = None
        series.refresh_series()

    formats = INPUT_FIELDS[METHOD]
    format_fields = set.union(*formats.values())

    def sync_format():
        active = formats[input_format.currentData()]
        dialog._set_field_visibility({name: name in active for name in format_fields})
        series.refresh_series()

    model.currentIndexChanged.connect(switch_model)
    input_format.currentIndexChanged.connect(sync_format)
    for name in ("X", "Y", "Series"):
        controls[name][1].currentIndexChanged.connect(series.refresh_series)
    y_columns.itemChanged.connect(series.refresh_series)
    merge.toggled.connect(series.refresh_series)
    parameters.changed.connect(series.refresh_coefficients)
    sync_format()
