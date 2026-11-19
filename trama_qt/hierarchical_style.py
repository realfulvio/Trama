"""Qt editor for the existing dendrogram and clustered heat-map style section."""
from copy import deepcopy

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QScrollArea, QTabWidget, QVBoxLayout, QWidget)

from analisi.data import decimal_comma
from analisi.hierarchical_style import (ASPECTS, CMAPS, COLOR_MODES, LINE_STYLES, ORIENTATIONS,
                                       HierarchicalStyleError, apply_hierarchical_style, baseline_hierarchical_style,
                                       snapshot_hierarchical_style, validate_hierarchical_style)
from analisi.i18n import tr, translate_message

from .graph_format import Choice, _color_button
from .theme import fit_dialog

BRANCH_FIELDS = (
    ("visible", bool), ("color_mode", COLOR_MODES), ("color", "color"), ("mixed_color", "color"),
    ("palette", list), ("width", float), ("line_style", LINE_STYLES), ("alpha", float),
)
LABEL_FIELDS = (
    ("visible", bool), ("rotation", float), ("size", float), ("color", "color"), ("first", int), ("interval", int),
)
DISTANCE_FIELDS = (
    ("visible", bool), ("minimum", float), ("maximum", float), ("step", float), ("reversed", bool),
)
HEAT_FIELDS = (
    ("cmap", CMAPS), ("reverse", bool), ("minimum", float), ("maximum", float),
    ("colorbar", bool), ("title", str), ("orientation", ORIENTATIONS), ("cell_aspect", ASPECTS),
)


def _get(values, path):
    for key in path:
        if key not in values:
            return None
        values = values[key]
    return values


def _drop(values, path):
    """Remove a field and clean up the now-empty sections on its path."""
    key, *remaining = path
    if key not in values:
        return
    if remaining:
        _drop(values[key], remaining)
        if values[key]:
            return
    del values[key]


def _put(values, path, value):
    for key in path[:-1]:
        values = values.setdefault(key, {})
    values[path[-1]] = value


class HierarchicalStyleDialog(QDialog):
    """Return only the edited section. Even Apply ends this dialog's canvas preview."""

    def __init__(self, parent, figure, section):
        super().__init__(parent)
        self.setWindowTitle(tr("hierarchy.style.title"))
        self.figure = figure
        self.baseline = baseline_hierarchical_style(figure)
        self.original = deepcopy(section or {})
        self._before = snapshot_hierarchical_style(figure)
        self._previewed = False
        self.result = None
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.addWidget(self._note("blank"))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        for dimension in ("row", "column"):
            if dimension in self.baseline:
                self._tree_page(dimension)
        if "heatmap" in self.baseline:
            form, scroll = self._page("heatmap", "colorbar")
            self._fields(form, scroll, ("heatmap",), HEAT_FIELDS)
        if "layout" in self.baseline:
            form, scroll = self._page("layout", "layout")
            self._fields(form, scroll, ("layout",), tuple((name, float) for name in self.baseline["layout"]))
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setObjectName("errorBanner")
        self.banner.hide()
        layout.addWidget(self.banner)
        buttons = QDialogButtonBox()
        self.preview_button = buttons.addButton(tr("hierarchy.style.preview"), QDialogButtonBox.ButtonRole.ActionRole)
        self.preview_button.clicked.connect(self.preview)
        buttons.addButton(tr("hierarchy.style.apply"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(tr("hierarchy.style.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        fit_dialog(self, 650, 620)

    @staticmethod
    def _note(name):
        note = QLabel(tr(f"hierarchy.style.hint.{name}"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        return note

    def _page(self, name, hint):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, tr(f"hierarchy.style.tab.{name}"))
        form = self._form(page)
        form.addRow(self._note(hint))
        return form, scroll

    @staticmethod
    def _form(parent):
        form = QFormLayout(parent)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return form

    def _tree_page(self, dimension):
        form, scroll = self._page(dimension, "hidden")
        for group, subgroup, fields, hint in (
                ("branches", (), BRANCH_FIELDS, "palette"),
                ("labels", ("labels",), LABEL_FIELDS, "labels"),
                ("distance", ("distance",), DISTANCE_FIELDS, "distance")):
            box = QGroupBox(tr(f"hierarchy.style.group.{group}"))
            grid = self._form(box)
            self._fields(grid, scroll, (dimension, *subgroup), fields)
            grid.addRow(self._note(hint))
            form.addRow(box)

    def _fields(self, form, scroll, section, fields):
        for key, kind in fields:
            path = (*section, key)
            name = ".".join(path)
            caption = ".".join(path[1:])
            label = tr(f"hierarchy.style.field.{caption}")
            default = _get(self.baseline, path)
            value = _get(self.original, path)
            if kind is bool:
                control = QCheckBox()
                control.setChecked(default if value is None else value)
                form.addRow(label, control)
            elif isinstance(kind, tuple):
                labels = {} if kind == CMAPS else {option: f"hierarchy.style.choice.{option}" for option in kind}
                control = Choice(kind, labels, default if value is None else value)
                form.addRow(label, control)
            else:
                control = QLineEdit(self._text(value))
                control.setPlaceholderText(self._text(default))
                if kind == "color":
                    row = QHBoxLayout()
                    row.addWidget(control, 1)
                    row.addWidget(_color_button(control))
                    form.addRow(label, row)
                else:
                    form.addRow(label, control)
            control.setObjectName(name)
            control.setAccessibleName(label)
            self.fields[name] = (path, kind, control, scroll)

    @staticmethod
    def _text(value):
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return ", ".join(value)
        return str(value)

    def _section(self):
        section = deepcopy(self.original)
        for name, (path, kind, control, _) in self.fields.items():
            if kind is bool:
                value = control.isChecked()
            elif isinstance(kind, tuple):
                value = control.value()
            else:
                value = control.text().strip()
                if value and kind in (int, float):
                    try:
                        value = kind(decimal_comma(value))
                    except ValueError:
                        message = "Enter a whole number." if kind is int else "Enter a finite number."
                        raise HierarchicalStyleError(name, message) from None
                elif value and kind is list:
                    value = [part.strip() for part in value.split(",")]
            if kind is bool or isinstance(kind, tuple):
                if value == _get(self.baseline, path) and _get(self.original, path) != value:
                    _drop(section, path)
                else:
                    _put(section, path, value)
            elif value == "":
                _drop(section, path)
            else:
                _put(section, path, value)
        return validate_hierarchical_style(section, figure=self.figure)

    def _problem(self, error):
        self.banner.setText(translate_message(error, "hierarchy.style.error."))
        self.banner.show()
        field = self.fields.get(error.field)
        if field is not None:
            _, _, control, scroll = field
            self.tabs.setCurrentWidget(scroll)
            scroll.ensureWidgetVisible(control)
            control.setFocus()
            if isinstance(control, QLineEdit):
                control.selectAll()

    def preview(self):
        try:
            apply_hierarchical_style(self.figure, self._section())
        except HierarchicalStyleError as error:
            self._problem(error)
            return
        self._previewed = True
        self.banner.hide()
        self.figure.canvas.draw_idle()

    def accept(self):
        try:
            self.result = self._section()
        except HierarchicalStyleError as error:
            self._problem(error)
            return
        super().accept()

    def done(self, result):
        if self._previewed:
            apply_hierarchical_style(self.figure, self._before)
            self.figure.canvas.draw_idle()
            self._previewed = False
        super().done(result)

