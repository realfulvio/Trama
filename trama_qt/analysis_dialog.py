"""The analysis dialog, built from the field specification of ``analisi.workbench.METHODS``.

Each analysis declares its fields as column roles, choices, flags, numbers or text. The Qt dialog
renders every declared field directly: Variables holds the column roles, Options the rest. The few
compound editors of the classic dialog (pair lists, profiles, term pickers…) keep the value of the
analysis being edited, or the engine default for a new one.
"""
from copy import deepcopy

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QScrollArea,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget, QHeaderView, QAbstractItemView)

from analisi.anova_planned_contrasts import ALPHA as CONTRAST_ALPHA, CONTRAST_LIST, CORRECTION as CONTRAST_CORRECTION
from analisi.anova_planned_contrasts import FACTOR_LIST as CONTRAST_FACTOR_LIST
from analisi.anova_terms import TERM_LIST
from analisi.custom_fit import CUSTOM_EQUATION, DEFAULT_EQUATION, EQUATION_TEXT, EXAMPLE_PARAMETERS
from analisi.data import decimal_comma
from analisi.field_error import FieldError
from analisi import kmeans_options, kmeans_reports, mean_permutation
from analisi.i18n import tr, ui
from analisi.select_transform import SELECT_TRANSFORM
from analisi.workbench import (CLASSIC_RESPONSES, GROUP_CHOICE, GROUPS, METHODS, MULTIPLE, OPTIONAL,
                               OPTIONAL_MULTIPLE, TEXT, classic_roles)

from . import anova_model, global_fit, logistic_validation, planned_contrasts
from . import kmeans_stability as stability_options
from . import bland_altman_repeated as repeated_agreement
from .labels import choice_label, field_label, method_label
from .strings import qt
from .theme import fit_dialog

try:  # Optional helpers: the dialog still works if a later refactor moves them.
    from analisi.hierarchical_workbench import hierarchy_view_available
except Exception:  # pragma: no cover
    def hierarchy_view_available(_frame):
        return True

try:
    from analisi.custom_fit import PARAMETER_LIST
except Exception:  # pragma: no cover
    PARAMETER_LIST = "Parameter list"

HIERARCHY_GRAPH = "Hierarchy graph"
CATEGORY_ROLES = {"Group", "Rows", "Columns", "Subject", "Row label", "Row factor variable",
                  "Column factor variable", "Row (treatment) variable", "Column (outcome) variable",
                  "X categories", "Y categories"}
VARIABLE_KINDS = (None, OPTIONAL, MULTIPLE, OPTIONAL_MULTIPLE)
PLANNED_PANEL_FIELDS = {CONTRAST_CORRECTION, CONTRAST_ALPHA}


def _text_defaults(method):
    """Defaults the classic dialog types into text fields (status codes, colours)."""
    defaults = {}
    try:
        if method == "Kaplan–Meier survival":
            from analisi.survival_input import STATUS_DEFAULTS
            defaults.update(STATUS_DEFAULTS)
        elif method == "Cox regression":
            from analisi.cox_outputs import STATUS_DEFAULTS
            defaults.update(STATUS_DEFAULTS)
        elif method == "Prune rows":
            defaults["X threshold"] = "0"
        else:
            from analisi.competing_risks_workbench import COMPETING_RISKS, DEFAULTS
            if method == COMPETING_RISKS:
                defaults.update(DEFAULTS)
            from analisi.heatmap import GRADIENT_COLORS, HEAT_MAP
            if method == HEAT_MAP:
                defaults.update(GRADIENT_COLORS)
                from analisi.heatmap_cell_labels import CELL_LABEL_COLOR, DEFAULT_LABEL_COLOR
                defaults[CELL_LABEL_COLOR] = DEFAULT_LABEL_COLOR
    except Exception:  # pragma: no cover - defaults are a convenience only
        pass
    return defaults


class ParameterTable(QTableWidget):
    """Name, start, lower, upper and fixed of each parameter of a user-defined equation."""

    HEADERS = ("name", "start", "lower", "upper", "fixed")

    def __init__(self, records, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels([field_label(name.capitalize()) for name in self.HEADERS])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setMinimumHeight(150)
        for record in records or ():
            self.add(record)
        self.add({})
        self.itemChanged.connect(self._grow)

    def add(self, record):
        row = self.rowCount()
        self.insertRow(row)
        for column, key in enumerate(self.HEADERS[:4]):
            value = record.get(key)
            self.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))
        fixed = QTableWidgetItem()
        fixed.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        fixed.setCheckState(Qt.CheckState.Checked if record.get("fixed") else Qt.CheckState.Unchecked)
        self.setItem(row, 4, fixed)

    def _grow(self, item):
        if item.row() == self.rowCount() - 1 and item.column() == 0 and item.text().strip():
            self.blockSignals(True)
            self.add({})
            self.blockSignals(False)

    def values(self):
        def number(text):
            text = (text or "").strip()
            if not text:
                return None
            try:
                return float(decimal_comma(text))
            except ValueError:
                raise FieldError("Parameters", f"{text} is not a number.") from None

        records = []
        for row in range(self.rowCount()):
            name = (self.item(row, 0).text() if self.item(row, 0) else "").strip()
            if not name:
                continue
            start = number(self.item(row, 1).text() if self.item(row, 1) else "")
            records.append({"name": name, "start": 1.0 if start is None else start,
                            "lower": number(self.item(row, 2).text() if self.item(row, 2) else ""),
                            "upper": number(self.item(row, 3).text() if self.item(row, 3) else ""),
                            "fixed": self.item(row, 4).checkState() == Qt.CheckState.Checked})
        return records


class AnalysisDialog(QDialog):
    def __init__(self, parent, frame, *, current=None, only=None, error=None, error_field=None):
        super().__init__(parent)
        self.setWindowTitle(qt("qt.analysis_title"))
        self.data = frame
        self.current = current
        self.only = {only} if isinstance(only, str) else set(only) if only else None
        self.result = None
        self.controls = {}
        self.rows = {}
        self.hidden = set()  # fields the current choices hide: left out of options()
        self.anova = None  # Multifactor ANOVA bindings (trama_qt.anova_model)
        self.stability = None  # K-means stability bindings (trama_qt.kmeans_stability)
        self.repeated = None  # Bland–Altman for repeated pairs (trama_qt.bland_altman_repeated)
        method = current[0] if current and current[0] in METHODS else None
        self.method = method or self._first_method()
        fit_dialog(self, 940, 640)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        picker = QWidget()
        picker_layout = QVBoxLayout(picker)
        picker_layout.setContentsMargins(0, 0, 8, 0)
        caption = QLabel(qt("qt.find_analysis"))
        caption.setObjectName("sectionTitle")
        picker_layout.addWidget(caption)
        self.query = QLineEdit()
        self.query.setPlaceholderText(qt("qt.find_analysis"))
        self.query.setClearButtonEnabled(True)
        self.query.textChanged.connect(self.fill_methods)
        picker_layout.addWidget(self.query)
        self.methods = QTreeWidget()
        self.methods.setHeaderHidden(True)
        self.methods.setRootIsDecorated(False)
        self.methods.setIndentation(10)
        self.methods.currentItemChanged.connect(self._picked)
        picker_layout.addWidget(self.methods, 1)
        splitter.addWidget(picker)

        workspace = QWidget()
        work_layout = QVBoxLayout(workspace)
        work_layout.setContentsMargins(8, 0, 0, 0)
        self.heading = QLabel()
        self.heading.setObjectName("pageTitle")
        self.heading.setWordWrap(True)
        work_layout.addWidget(self.heading)
        self.banner = QLabel()
        self.banner.setObjectName("errorBanner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(bool(error))
        if error:
            self.banner.setText(self._message(error, error_field))
        work_layout.addWidget(self.banner)
        self.tabs = QTabWidget()
        work_layout.addWidget(self.tabs, 1)
        splitter.addWidget(workspace)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 640])

        buttons = QDialogButtonBox()
        self.run_button = buttons.addButton(qt("qt.run"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.run_button.setDefault(True)
        buttons.addButton(qt("qt.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.fill_methods()
        self.configure_fields()
        if error and self.stability is not None:  # engine errors reopen here; word them in the active language
            self.banner.setText(self.stability.message(error))
        if error and self.repeated is not None:  # engine errors reopen here; word them in the active language
            self.banner.setText(self.repeated.message(error))
        if error_field:
            if self.anova is not None and error:  # engine errors reopen here; word them in the active language
                self.banner.setText(self.anova.message(FieldError(error_field, str(error))))
            self.focus_field(error_field, error)
        if self.only and len(self.only) == 1:
            splitter.widget(0).setVisible(False)

    # -- method list -----------------------------------------------------------------------------
    def _offered(self, name):
        if self.only and name not in self.only:
            return False
        return name != HIERARCHY_GRAPH or name == self.method or hierarchy_view_available(self.data)

    def _first_method(self):
        for methods in GROUPS.values():
            for name in methods:
                if name in METHODS and self._offered(name):
                    return name
        return next(iter(METHODS))

    def fill_methods(self):
        search = self.query.text().strip().casefold()
        self.methods.blockSignals(True)
        self.methods.clear()
        selected = None
        for group, methods in GROUPS.items():
            matches = [name for name in methods if name in METHODS and self._offered(name)
                       and any(search in caption.casefold()
                               for caption in (name, group, method_label(name), method_label(group)))]
            if not matches:
                continue
            folder = QTreeWidgetItem([method_label(group)])
            folder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = folder.font(0)
            font.setBold(True)
            folder.setFont(0, font)
            self.methods.addTopLevelItem(folder)
            for name in matches:
                item = QTreeWidgetItem([method_label(name)])
                item.setData(0, Qt.ItemDataRole.UserRole, name)
                folder.addChild(item)
                if name == self.method:
                    selected = item
            folder.setExpanded(True)
        if selected is not None:
            self.methods.setCurrentItem(selected)
            self.methods.scrollToItem(selected)
        self.methods.blockSignals(False)

    def _picked(self, item, _previous=None):
        name = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if name in METHODS and name != self.method:
            self.method = name
            self.banner.setVisible(False)
            self.configure_fields()

    # -- fields ----------------------------------------------------------------------------------
    def _saved(self):
        if not self.current or self.current[0] != self.method:
            return {}
        saved = dict(self.current[1])
        if self.method in kmeans_options.METHODS:
            saved = kmeans_options.saved_scaling(saved)
        if self.method in CLASSIC_RESPONSES:
            saved = {**saved, **classic_roles(self.method, saved)}
        return saved

    def configure_fields(self):
        self.heading.setText(method_label(self.method))
        self.tabs.clear()
        self.controls.clear()
        self.rows.clear()
        self.hidden.clear()
        self.anova = None
        self.stability = None
        self.repeated = None
        pages, scrolls = {}, {}
        # Global fit custom equation adds Equation, Parameters, Series constraints and Response pages.
        for key, name in (("variables", qt("qt.variables")), *global_fit.pages(self.method),
                          ("options", qt("qt.options"))):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            body = QWidget()
            form = QFormLayout(body)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            form.setContentsMargins(12, 12, 12, 12)
            form.setVerticalSpacing(8)
            scroll.setWidget(body)
            pages[key], scrolls[key] = form, scroll
            self.tabs.addTab(scroll, name)
        variables, options = pages["variables"], pages["options"]
        saved = self._saved()
        if self.method == CUSTOM_EQUATION and not saved:
            saved = {"Equation": DEFAULT_EQUATION, "Parameters": [dict(record) for record in EXAMPLE_PARAMETERS]}
        elif self.method == global_fit.GLOBAL_CUSTOM_EQUATION and not saved:
            saved = global_fit.default_recipe()
        text_defaults = _text_defaults(self.method)
        columns = [str(name) for name in self.data.columns]
        numeric = [str(name) for name in self.data.select_dtypes(include="number").columns]
        categorical = [name for name in columns if name not in numeric] or columns
        numeric_position = category_position = 0
        for label, kind in METHODS[self.method].items():
            if kind == CONTRAST_FACTOR_LIST or (kind != CONTRAST_LIST and label in PLANNED_PANEL_FIELDS
                                                and CONTRAST_LIST in METHODS[self.method].values()):
                continue  # the Planned contrasts… editor holds these fields
            variable = (kind in VARIABLE_KINDS or label == "Input format") and label not in {
                "Comparison factor", "Condition on factors"}
            form = pages.get(global_fit.page_of(self.method, label)) or (variables if variable else options)
            caption_label = ("Report scaled observations"
                             if self.method in kmeans_options.METHODS and label == kmeans_reports.SCALED else label)
            caption = QLabel(field_label(caption_label))
            caption.setWordWrap(True)
            caption.setMinimumWidth(150)
            caption.setMaximumWidth(230)
            widget = None
            if kind in (MULTIPLE, OPTIONAL_MULTIPLE):
                widget = QListWidget()
                widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
                defaults = saved.get(label, numeric if label in {"Variables", "Count columns"} else ())
                if self.method == SELECT_TRANSFORM and label not in saved:
                    defaults = columns
                offered = list(dict.fromkeys([*columns, *[str(name) for name in (defaults or ())]]))
                for name in offered:
                    item = QListWidgetItem(name)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if name in [str(d) for d in (defaults or ())]
                                       else Qt.CheckState.Unchecked)
                    widget.addItem(item)
                widget.setMaximumHeight(max(70, min(170, 24 * len(offered) + 8)))
            elif type(kind) is bool:
                widget = QCheckBox()
                widget.setChecked(bool(saved.get(label, kind)))
            elif type(kind) in (int, float) or kind == TEXT:
                default = text_defaults.get(label, "") if kind == TEXT else kind
                value = saved.get(label, default)
                widget = QLineEdit("" if value is None else str(value))
            elif kind == TERM_LIST:  # Multifactor ANOVA model terms; bound below by anova_model.attach
                widget = anova_model.TermEditor(saved.get(label))
            elif kind == CONTRAST_LIST:  # Multifactor ANOVA planned contrasts; bound by anova_model.attach
                widget = planned_contrasts.ContrastPanel(saved)
            elif kind == EQUATION_TEXT:
                widget = QPlainTextEdit(str(saved.get(label, DEFAULT_EQUATION)))
                widget.setMinimumHeight(90)
            elif kind == PARAMETER_LIST:
                widget = ParameterTable(saved.get(label, ()))
            elif kind in (global_fit.PARAMETER_LIST, global_fit.SERIES_LIST):
                # Global coefficient list / Global series constraints (Global fit custom equation).
                widget = global_fit.build_editor(kind, label, saved, self)
            elif isinstance(kind, tuple) or kind in (None, OPTIONAL, GROUP_CHOICE):
                widget = QComboBox()
                widget.setMinimumContentsLength(18)
                if isinstance(kind, tuple):
                    choices = list(kind)
                    for choice in choices:
                        widget.addItem(choice_label(str(choice)), choice)
                    default = choices[0] if choices else ""
                elif kind == GROUP_CHOICE:
                    widget.setEditable(True)
                    widget.addItem("", "")
                    default = ""
                else:
                    if kind == OPTIONAL:
                        widget.addItem(qt("qt.none"), "")
                    for name in columns:
                        widget.addItem(name, name)
                    if kind is None and label in CATEGORY_ROLES and categorical:
                        default = categorical[category_position % len(categorical)]
                        category_position += 1
                    elif kind is None and numeric:
                        default = numeric[numeric_position % len(numeric)]
                        numeric_position += 1
                    else:
                        default = "" if kind == OPTIONAL else (columns[0] if columns else "")
                value = saved.get(label) or default
                position = widget.findData(value)
                if position < 0 and value not in (None, ""):
                    widget.addItem(str(value), value)
                    position = widget.count() - 1
                widget.setCurrentIndex(max(position, 0))
                if kind == GROUP_CHOICE and value:
                    widget.setEditText(str(value))
            if widget is None:
                # A compound editor of the classic dialog: keep the saved value or the default.
                note = QLabel(qt("qt.saved_setting") if label in saved else qt("qt.default_setting"))
                note.setObjectName("muted")
                note.setWordWrap(True)
                form.addRow(caption, note)
                if label in saved:
                    self.controls[label] = ("kept", deepcopy(saved[label]))
                continue
            if kind in (TERM_LIST, CONTRAST_LIST, global_fit.PARAMETER_LIST, global_fit.SERIES_LIST):
                form.addRow(caption)
                form.addRow(widget)
            else:
                form.addRow(caption, widget)
            self.controls[label] = (kind, widget)
            self.rows[label] = (caption, widget, form)
        self.anova = anova_model.attach(self, saved)
        global_fit.attach(self)
        if self.method in kmeans_options.METHODS:
            algorithm = self.controls[kmeans_options.ALGORITHM][1]
            algorithm.currentIndexChanged.connect(self._sync_kmeans_options)
            self.controls[kmeans_options.SCALE][1].currentIndexChanged.connect(self._sync_kmeans_options)
            self._sync_kmeans_options()
        self.stability = stability_options.attach(self)
        self.repeated = repeated_agreement.attach(self)
        if options.rowCount() == 0:
            self.tabs.removeTab(self.tabs.indexOf(scrolls["options"]))

    def _sync_kmeans_options(self):
        algorithm = self.controls[kmeans_options.ALGORITHM][1].currentData()
        fields = {field: key == algorithm for key, field in kmeans_options.ITERATION_FIELDS.items()}
        scale = self.controls[kmeans_options.SCALE][1].currentData()
        fields[kmeans_reports.SCALED] = scale != kmeans_options.UNSCALED
        if self.method == kmeans_options.CLUSTERING:
            fields[kmeans_options.INITIAL_ROWS] = algorithm in kmeans_options.ITERATION_FIELDS
        for name, visible in fields.items():
            _, control, form = self.rows[name]
            form.setRowVisible(control, visible)
            if visible:
                self.hidden.discard(name)
            else:
                self.hidden.add(name)

    def focus_field(self, name, error=None):
        row = self.rows.get(name)
        if row is None:
            return False
        caption, widget, form = row
        for index in range(self.tabs.count()):
            scroll = self.tabs.widget(index)
            if scroll.widget().layout() is form:
                self.tabs.setCurrentIndex(index)
                scroll.ensureWidgetVisible(widget)
                break
        # A compound editor puts the cursor on the cell the error is about.
        if not (hasattr(widget, "focus_problem") and widget.focus_problem(error)):
            widget.setFocus()
        return True

    # -- values ----------------------------------------------------------------------------------
    def options(self):
        options = {}
        for name, (kind, control) in self.controls.items():
            if name in self.hidden:
                continue
            if kind == "kept":
                options[name] = deepcopy(control)
            elif kind in (MULTIPLE, OPTIONAL_MULTIPLE):
                value = [control.item(i).text() for i in range(control.count())
                         if control.item(i).checkState() == Qt.CheckState.Checked]
                if kind == MULTIPLE and not value:
                    raise FieldError(name, qt("qt.select_columns", name=field_label(name)))
                options[name] = value
            elif type(kind) is bool:
                options[name] = control.isChecked()
            elif type(kind) in (int, float):
                text = control.text().strip()
                try:
                    value = type(kind)(decimal_comma(text) if type(kind) is float else text)
                except ValueError:
                    raise FieldError(name, qt("qt.whole_number" if type(kind) is int else "qt.number",
                                              name=field_label(name))) from None
                if type(kind) is float and not np.isfinite(value):
                    raise FieldError(name, qt("qt.number", name=field_label(name)))
                options[name] = value
            elif kind == TEXT:
                options[name] = control.text()
            elif kind == TERM_LIST:
                options[name] = control.values()
            elif kind == CONTRAST_LIST:
                options.update(control.values())  # the four planned-contrast keys, or none
            elif kind == EQUATION_TEXT:
                options[name] = control.toPlainText().strip()
            elif kind == PARAMETER_LIST:
                options[name] = control.values()
            elif kind in (global_fit.PARAMETER_LIST, global_fit.SERIES_LIST):
                options[name] = control.values()
            elif kind == GROUP_CHOICE:
                options[name] = control.currentText().strip()
            else:
                value = control.currentData()
                if value is None:
                    value = control.currentText()
                if kind == OPTIONAL:
                    value = value or None
                elif kind is None and not value:
                    raise FieldError(name, qt("qt.choose_column", name=field_label(name)))
                options[name] = value
        return self.anova.canonical(options) if self.anova is not None else options

    def accept(self):
        try:
            options = global_fit.confirm(self, self.options())
            if self.anova is not None:
                self.anova.check(options)  # the engine's cheap checks; the fit stays on the worker
            if self.stability is not None:
                self.stability.check(options)  # the engine's checks and budgets; the fits stay on the worker
            if self.repeated is not None:
                self.repeated.check(options)  # recipe and worksheet checks; the bootstrap stays on the worker
            if self.method == mean_permutation.METHOD:
                mean_permutation.check_options(self.data, options)
            if self.method in kmeans_options.METHODS:
                kmeans_options.scale(options)
                kmeans_options.fit_options(self.method, self.data, options)
            logistic_validation.check(self, options)  # Validate binary logistic model: no fit before the worker
        except FieldError as error:
            self.show_error(self.anova.message(error) if self.anova is not None else error, error.field)
            return
        except (ValueError, OverflowError) as error:
            self.show_error(error)
            return
        self.result = (self.method, options)
        super().accept()

    def _message(self, error, field=None):
        if self.method == global_fit.GLOBAL_CUSTOM_EQUATION:
            return global_fit.describe_error(error, field)
        if self.method in kmeans_options.METHODS:
            return ui(str(error))
        if self.stability is not None:  # K-means stability: engine messages in the active language
            return self.stability.message(error)
        if logistic_validation.applies(self):
            return logistic_validation.message(error)
        if self.repeated is not None:  # Bland–Altman for repeated pairs: engine messages in the active language
            return self.repeated.message(error)
        return str(error)

    def show_error(self, error, field=None):
        self.banner.setText(self._message(error, field))
        self.banner.setVisible(True)
        if field:
            self.focus_field(field, error)


def choose(parent, frame, **options):
    """Show the dialog; return (method, options) or None."""
    dialog = AnalysisDialog(parent, frame, **options)
    return dialog.result if dialog.exec() == QDialog.DialogCode.Accepted else None


__all__ = ["AnalysisDialog", "choose", "tr"]
