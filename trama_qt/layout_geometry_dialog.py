"""Numeric position and scale controls for layout panels."""

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel

from analisi.i18n import tr
from analisi.layout_panels import targets_fit

from .strings import qt
from .theme import fit_dialog


class PanelGeometryDialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.form = QFormLayout(self)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.targets = None
        QShortcut(QKeySequence("F1"), self, parent.show_shortcuts)

    def spin(self, label, value, low, high, suffix):
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(low, high)
        spin.setSuffix(suffix)
        spin.setValue(value)
        spin.setAccessibleName(label)
        self.form.addRow(label, spin)
        return spin

    def choice(self, label, values):
        combo = QComboBox()
        combo.setAccessibleName(label)
        for text, value in values:
            combo.addItem(text, value)
        self.form.addRow(label, combo)
        return combo

    def buttons(self):
        self.problem = QLabel()
        self.problem.setObjectName("infoBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        self.form.addRow(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.form.addRow(buttons)
        fit_dialog(self, 460, 235)

    def submit(self, panels, targets, page):
        if not targets_fit(panels, targets, page):
            self.problem.setText(qt("qt.layout_geometry_outside"))
            self.problem.show()
            return
        self.targets = targets
        super().accept()


class PanelPositionDialog(PanelGeometryDialog):
    def __init__(self, parent, panels, index, page):
        super().__init__(parent, qt("qt.layout_position_title", letter=chr(ord("A") + index)))
        self.panels, self.index, self.page = panels, index, page
        x, y, scale = panels[index].box
        self.fields = (
            self.spin(qt("qt.layout_from_left"), x * 2.54, -2.54 * page[0], 2.54 * page[0], " cm"),
            self.spin(qt("qt.layout_from_top"), y * 2.54, -2.54 * page[1], 2.54 * page[1], " cm"),
            self.spin(qt("qt.layout_scale_percent"), scale * 100, .001, max(10000., scale * 100), " %"),
        )
        self.displayed = tuple(field.value() for field in self.fields)
        self.buttons()
        self.fields[0].setFocus()

    def accept(self):
        original = self.panels[self.index].box
        values = tuple(old if field.value() == display else field.value() / factor
                       for field, display, old, factor in zip(self.fields, self.displayed, original,
                                                              (2.54, 2.54, 100.), strict=True))
        self.submit(self.panels, {self.index: values}, self.page)


class PanelScaleDialog(PanelGeometryDialog):
    def __init__(self, parent, panels, eligible, selected, page):
        super().__init__(parent, qt("qt.layout_equalize_title"))
        self.panels, self.page = panels, page
        self.eligible, self.selected = tuple(eligible), tuple(selected)
        scopes = [(qt("qt.layout_all_graphs"), self.eligible)]
        if len(self.selected) > 1:
            scopes.append((qt("qt.layout_selected_graphs"), self.selected))
        self.scope = self.choice(qt("qt.layout_scale_scope"), scopes)
        self.mode = self.choice(qt("qt.layout_scale_target"), (
            (qt("qt.layout_scale_smallest"), "min"),
            (qt("qt.layout_scale_largest"), "max"),
            (qt("qt.layout_scale_custom"), "custom"),
        ))
        self.percent = self.spin(qt("qt.layout_scale_percent"), 100, .001, 10000., " %")
        self.scope.currentIndexChanged.connect(self.update_range)
        self.mode.currentIndexChanged.connect(self.update_range)
        self.buttons()
        self.update_range()
        self.mode.setFocus()

    def update_range(self):
        scales = [self.panels[index].box[2] for index in self.scope.currentData()]
        mode = self.mode.currentData()
        self.percent.setEnabled(mode == "custom")
        if mode != "custom":
            self.percent.setValue((min(scales) if mode == "min" else max(scales)) * 100)

    def accept(self):
        panels = self.scope.currentData()
        scales = [self.panels[index].box[2] for index in panels]
        mode = self.mode.currentData()
        scale = (min(scales) if mode == "min" else max(scales) if mode == "max" else self.percent.value() / 100)
        targets = {index: (*self.panels[index].box[:2], scale) for index in panels}
        self.submit(self.panels, targets, self.page)
