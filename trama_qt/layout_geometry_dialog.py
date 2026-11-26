"""Position, scale and appearance controls for layout panels."""

from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QWidget)

from analisi.i18n import tr
from analisi.layout_arrangement import BORDER_DASHES
from analisi.layout_panels import rotation_target, targets_fit

from .graph_format import _color_button
from .strings import qt
from .theme import fit_dialog


class PanelGeometryDialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.form = QFormLayout(self)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.targets = self.appearance = None
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

    def choice(self, label, values, *, form=None):
        combo = QComboBox()
        combo.setAccessibleName(label)
        for text, value in values:
            combo.addItem(text, value)
        (form if form is not None else self.form).addRow(label, combo)
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
        fit_dialog(self, 470, max(235, self.sizeHint().height()))

    def show_problem(self, key):
        self.problem.setText(qt(key))
        self.problem.show()
        fit_dialog(self, 470, self.sizeHint().height())

    def submit(self, panels, targets, page, *, angles=None):
        if not targets_fit(panels, targets, page, angles=angles):
            self.show_problem("qt.layout_geometry_outside")
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
        self.rotation = None
        if panels[index].figure is not None:
            self.add_appearance(panels[index])
        self.buttons()
        self.fields[0].setFocus()

    def add_appearance(self, panel):
        section = QGroupBox(qt("qt.layout_appearance"))
        form = QFormLayout(section)
        self.rotation = self.choice(qt("qt.layout_rotation"), (
            (qt("qt.layout_rotation_none"), 0),
            (qt("qt.layout_rotation_cw"), 90),
            (qt("qt.layout_rotation_ccw"), -90),
        ), form=form)
        self.rotation.setCurrentIndex(self.rotation.findData(panel.angle))
        self.rotation.setToolTip(qt("qt.layout_rotation_center_tip"))
        border = QCheckBox(qt("qt.layout_show_border"))
        form.addRow(border)
        options = QWidget()
        style_form = QFormLayout(options)
        style_form.setContentsMargins(0, 0, 0, 0)
        width, color, style = panel.border or (1., "#000000", "solid")
        self.border_width = QDoubleSpinBox()
        self.border_width.setRange(.1, 12.)
        self.border_width.setDecimals(2)
        self.border_width.setSingleStep(.25)
        self.border_width.setValue(width)
        self.border_width.setSuffix(" pt")
        style_form.addRow(qt("qt.layout_border_width"), self.border_width)
        self.border_style = self.choice(tr("shape.line_style"),
                                        ((tr(f"shape.option.{name}"), name) for name in BORDER_DASHES),
                                        form=style_form)
        self.border_style.setCurrentIndex(self.border_style.findData(style))
        self.border_color = QLineEdit(color)
        self.border_color.setAccessibleName(tr("shape.stroke"))
        button = _color_button(self.border_color)
        button.setAutoDefault(False)
        row = QHBoxLayout()
        row.addWidget(self.border_color)
        row.addWidget(button)
        style_form.addRow(tr("shape.stroke"), row)
        self.border_on = border
        border.setChecked(panel.border is not None)
        options.setEnabled(border.isChecked())
        border.toggled.connect(options.setEnabled)
        form.addRow(options)
        self.form.addRow(section)

    def accept(self):
        original = self.panels[self.index].box
        values = tuple(old if field.value() == display else field.value() / factor
                       for field, display, old, factor in zip(self.fields, self.displayed, original,
                                                              (2.54, 2.54, 100.), strict=True))
        angles = None
        if self.rotation is not None:
            angle = self.rotation.currentData()
            border = None
            if self.border_on.isChecked():
                color = QColor(self.border_color.text().strip())
                if not color.isValid() or color.alpha() != 255:
                    self.show_problem("qt.layout_border_color_problem")
                    self.border_color.setFocus()
                    return
                border = self.border_width.value(), color.name(), self.border_style.currentData()
            self.appearance = self.index, angle, border
            angles = {self.index: angle}
            fixed = tuple(field.value() != display for field, display in zip(self.fields[:2], self.displayed[:2],
                                                                            strict=True))
            values = rotation_target(self.panels[self.index], values, angle, self.page, fixed=fixed)
        self.submit(self.panels, {self.index: values}, self.page, angles=angles)


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
