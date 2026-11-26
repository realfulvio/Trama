"""Position, scale and appearance controls for layout panels."""

from dataclasses import replace
from math import isclose

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QWidget)

from analisi.i18n import tr
from analisi.layout_arrangement import BORDER_DASHES, valid_crop
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
        QShortcut(QKeySequence("F1"), self, self.show_shortcuts)

    def show_shortcuts(self):
        self.parentWidget().show_shortcuts()
        self.ok_button.setDefault(True)

    def spin(self, label, value, low, high, suffix, *, form=None):
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(low, high)
        spin.setSuffix(suffix)
        spin.setValue(value)
        spin.setAccessibleName(label)
        (form if form is not None else self.form).addRow(label, spin)
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
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText(tr("setup.cancel"))
        cancel.setAutoDefault(False)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.form.addRow(buttons)
        fit_dialog(self, 470, max(235, self.sizeHint().height()))

    def show_problem(self, key):
        self.problem.setText(qt(key))
        self.problem.show()
        fit_dialog(self, 470, self.sizeHint().height())

    def submit(self, panels, targets, page, *, sizes=None):
        if not targets_fit(panels, targets, page, sizes=sizes):
            self.show_problem("qt.layout_geometry_outside")
            return
        self.targets = targets
        super().accept()


class PanelPositionDialog(PanelGeometryDialog):
    def __init__(self, parent, panels, index, page, *, picture=None):
        title = "qt.layout_picture_title" if picture is not None else "qt.layout_position_title"
        super().__init__(parent, qt(title, letter=chr(ord("A") + index)))
        self.panels, self.index, self.page = panels, index, page
        self.picture_size = None
        panel = panels[index]
        x, y, scale = panel.box
        geometry = self.form
        self.tabs = self.rotation = None
        if panel.figure is not None:
            self.tabs = QTabWidget()
            page_widget = QWidget()
            geometry = QFormLayout(page_widget)
            geometry.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            self.tabs.addTab(page_widget, qt("qt.layout_geometry_tab"))
            self.form.addRow(self.tabs)
        self.fields = (
            self.spin(qt("qt.layout_from_left"), x * 2.54, -2.54 * page[0], 2.54 * page[0], " cm", form=geometry),
            self.spin(qt("qt.layout_from_top"), y * 2.54, -2.54 * page[1], 2.54 * page[1], " cm", form=geometry),
        )
        self.dimensions = ()
        if picture:
            self.add_picture_size(panel, picture, geometry)
        else:
            self.fields += (self.spin(qt("qt.layout_scale_percent"), scale * 100, .001,
                                      max(10000., scale * 100), " %", form=geometry),)
        self.displayed = tuple(field.value() for field in self.fields)
        if self.tabs is not None:
            self.add_appearance(panel, geometry)
            self.add_crop(panel)
        self.buttons()
        if self.tabs is not None:
            self.tabs.currentChanged.connect(lambda _: self.ok_button.setDefault(True))
        self.fields[0].setFocus()

    def add_picture_size(self, panel, picture, form):
        from analisi.layout_picture import source_size

        native = source_size(picture[2])
        sizes = tuple(size * panel.box[2] * 2.54 for size in panel.size)
        self.dimensions = tuple(self.spin(qt(f"qt.layout_picture_{axis}"), size, .001, max(2.54 * 200, size),
                                          " cm", form=form)
                                for axis, size in zip(("width", "height"), sizes, strict=True))
        self.size_shown = tuple(field.value() for field in self.dimensions)
        self.proportions = QCheckBox(qt("qt.layout_picture_proportions"))
        self.proportions.setChecked(isclose(sizes[0] / sizes[1], native[0] / native[1], rel_tol=1e-5))
        form.addRow(self.proportions)

        def proportional(index):
            if self.proportions.isChecked():
                other = self.dimensions[1 - index]
                with QSignalBlocker(other):
                    other.setValue(self.dimensions[index].value() * native[1 - index] / native[index])

        for index, field in enumerate(self.dimensions):
            field.setKeyboardTracking(False)
            field.valueChanged.connect(lambda _, index=index: proportional(index))
        self.proportions.toggled.connect(lambda _: proportional(0))

        def restore_size():
            for value, field in zip(native, self.dimensions, strict=True):
                with QSignalBlocker(field):
                    field.setValue(value * 2.54)
            self.proportions.setChecked(True)

        original_size = QPushButton(qt("qt.layout_picture_original"))
        original_size.setAutoDefault(False)
        original_size.clicked.connect(restore_size)
        form.addRow(original_size)

    def add_crop(self, panel):
        page = QWidget()
        form = QFormLayout(page)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        hint = QLabel(qt("qt.layout_crop_tip"))
        hint.setWordWrap(True)
        form.addRow(hint)
        names = ("left", "top", "right", "bottom")
        self.crop_fields = tuple(
            self.spin(qt(f"qt.layout_crop_{name}"), fraction * length * panel.box[2] * 2.54,
                      -max(self.page) * 2.54, max(self.page) * 2.54, " cm", form=form)
            for name, fraction, length in zip(names, panel.crop, panel.size * 2, strict=True))
        self.crop_shown = tuple(field.value() for field in self.crop_fields)
        self.tabs.addTab(page, qt("qt.layout_crop_tab"))

    def add_appearance(self, panel, geometry):
        section = QGroupBox(qt("qt.layout_appearance"))
        form = QFormLayout(section)
        if self.dimensions or panel.angle not in (0, 90, -90):
            self.rotation = QSpinBox()
            self.rotation.setRange(-180, 180)
            self.rotation.setSuffix("°")
            self.rotation.setValue(panel.angle)
            self.rotation.setAccessibleName(qt("qt.layout_rotation"))
            form.addRow(qt("qt.layout_rotation"), self.rotation)
        else:
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
        geometry.addRow(section)

    def accept(self):
        panel = self.panels[self.index]
        original = panel.box
        values = tuple(old if field.value() == display else field.value() / factor
                       for field, display, old, factor in zip(self.fields, self.displayed, original[:len(self.fields)],
                                                              (2.54, 2.54, 100.)[:len(self.fields)], strict=True))
        picture_size = None
        if self.dimensions:
            values += (original[2],)
            picture_size = tuple(float(size if field.value() == display else field.value() / (2.54 * values[2]))
                                 for size, field, display in zip(panel.size, self.dimensions, self.size_shown, strict=True))
        sizes = None
        if self.rotation is not None:
            angle = self.rotation.value() if isinstance(self.rotation, QSpinBox) else self.rotation.currentData()
            border = None
            if self.border_on.isChecked():
                color = QColor(self.border_color.text().strip())
                if not color.isValid() or color.alpha() != 255:
                    self.show_problem("qt.layout_border_color_problem")
                    self.border_color.setFocus()
                    return
                border = self.border_width.value(), color.name(), self.border_style.currentData()
            shape = picture_size if picture_size is not None else panel.size
            crop = tuple(float((old * old_size * original[2] * 2.54 if field.value() == display else field.value())
                               / (2.54 * size * values[2]))
                         if picture_size is not None or field.value() != display else old
                         for field, display, old, size, old_size in zip(self.crop_fields, self.crop_shown, panel.crop,
                                                                       shape * 2, panel.size * 2, strict=True))
            if not valid_crop(crop):
                self.tabs.setCurrentIndex(1)
                self.show_problem("qt.layout_crop_problem")
                return
            candidate = replace(panel, size=shape, crop=crop)
            self.appearance = self.index, angle, border, crop
            self.picture_size = picture_size if picture_size != panel.size else None
            sizes = {self.index: replace(candidate, angle=angle).oriented_size}
            fixed = tuple(field.value() != display for field, display in zip(self.fields[:2], self.displayed[:2],
                                                                            strict=True))
            values = rotation_target(candidate, values, angle, self.page, fixed=fixed)
        self.submit(self.panels, {self.index: values}, self.page, sizes=sizes)


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
