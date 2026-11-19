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

from analisi.custom_fit import CUSTOM_EQUATION, DEFAULT_EQUATION, EQUATION_TEXT, EXAMPLE_PARAMETERS
from analisi.data import decimal_comma
from analisi.field_error import FieldError
from analisi.i18n import tr
from analisi.select_transform import SELECT_TRANSFORM
from analisi.workbench import (CLASSIC_RESPONSES, GROUP_CHOICE, GROUPS, METHODS, MULTIPLE, OPTIONAL,
                               OPTIONAL_MULTIPLE, TEXT, classic_roles)

from .labels import choice_label, field_label, method_label
from .strings import qt

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
        method = current[0] if current and current[0] in METHODS else None
        self.method = method or self._first_method()
        screen = self.screen()
        if screen is None:
            self.resize(940, 640)
        else:
            available = screen.availableGeometry()
            self.resize(min(940, available.width() - 32), min(640, available.height() - 48))

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
            self.banner.setText(str(error))
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
        if error_field:
            self.focus_field(error_field)
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
        if self.method in CLASSIC_RESPONSES:
            saved = {**saved, **classic_roles(self.method, saved)}
        return saved

    def configure_fields(self):
        self.heading.setText(method_label(self.method))
        self.tabs.clear()
        self.controls.clear()
        self.rows.clear()
        pages = {}
        for name in (qt("qt.variables"), qt("qt.options")):
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
            pages[name] = form
            self.tabs.addTab(scroll, name)
        variables, options = pages.values()
        saved = self._saved()
        if self.method == CUSTOM_EQUATION and not saved:
            saved = {"Equation": DEFAULT_EQUATION, "Parameters": [dict(record) for record in EXAMPLE_PARAMETERS]}
        text_defaults = _text_defaults(self.method)
        columns = [str(name) for name in self.data.columns]
        numeric = [str(name) for name in self.data.select_dtypes(include="number").columns]
        categorical = [name for name in columns if name not in numeric] or columns
        numeric_position = category_position = 0
        for label, kind in METHODS[self.method].items():
            variable = (kind in VARIABLE_KINDS or label == "Input format") and label not in {
                "Comparison factor", "Condition on factors"}
            form = variables if variable else options
            caption = QLabel(field_label(label))
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
            elif kind == EQUATION_TEXT:
                widget = QPlainTextEdit(str(saved.get(label, DEFAULT_EQUATION)))
                widget.setMinimumHeight(90)
            elif kind == PARAMETER_LIST:
                widget = ParameterTable(saved.get(label, ()))
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
            form.addRow(caption, widget)
            self.controls[label] = (kind, widget)
            self.rows[label] = (caption, widget, form)
        if options.rowCount() == 0:
            self.tabs.removeTab(1)

    def focus_field(self, name):
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
        widget.setFocus()
        return True

    # -- values ----------------------------------------------------------------------------------
    def options(self):
        options = {}
        for name, (kind, control) in self.controls.items():
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
            elif kind == EQUATION_TEXT:
                options[name] = control.toPlainText().strip()
            elif kind == PARAMETER_LIST:
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
        return options

    def accept(self):
        try:
            options = self.options()
        except FieldError as error:
            self.show_error(error, error.field)
            return
        except ValueError as error:
            self.show_error(error)
            return
        self.result = (self.method, options)
        super().accept()

    def show_error(self, error, field=None):
        self.banner.setText(str(error))
        self.banner.setVisible(True)
        if field:
            self.focus_field(field)


def choose(parent, frame, **options):
    """Show the dialog; return (method, options) or None."""
    dialog = AnalysisDialog(parent, frame, **options)
    return dialog.result if dialog.exec() == QDialog.DialogCode.Accepted else None


__all__ = ["AnalysisDialog", "choose", "tr"]
