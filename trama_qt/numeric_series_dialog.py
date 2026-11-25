"""Compact dialog for generating an arithmetic or geometric numeric series in a worksheet column."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                               QSpinBox, QVBoxLayout)

from analisi.data import MAX_CELLS
from analisi.numeric_series import (ARITHMETIC, GEOMETRIC, format_preview, plan_numeric_series, series_text)
from analisi.worksheet_number_format import display_decimal_mark

from . import theme


class NumericSeriesDialog(QDialog):
    """Prompt for first value, count, and step/ratio with live preview and explicit replacement confirmation."""

    def __init__(self, parent, dataset, target):
        super().__init__(parent)
        self.dataset = dataset
        self.target = target
        self.plan = None
        self._last_replace_key = None

        self.setWindowTitle(series_text("title"))
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.mode = QComboBox()
        self.mode.addItem(series_text("arithmetic"), ARITHMETIC)
        self.mode.addItem(series_text("geometric"), GEOMETRIC)
        form.addRow(series_text("mode"), self.mode)

        self.first = QLineEdit("1")
        self.first.setAccessibleName(series_text("first"))
        form.addRow(series_text("first"), self.first)

        self.count = QSpinBox()
        self.count.setRange(1, MAX_CELLS)
        self.count.setValue(max(1, min(MAX_CELLS, target.proposed_count)))
        self.count.setAccessibleName(series_text("count"))
        form.addRow(series_text("count"), self.count)

        self.step_label = QLabel(series_text("step"))
        self.step = QLineEdit("1")
        self.step.setAccessibleName(series_text("step"))
        form.addRow(self.step_label, self.step)

        self.range_label = QLabel()
        self.range_label.setObjectName("numericSeriesRange")
        form.addRow(series_text("range"), self.range_label)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("numericSeriesPreview")
        self.preview_label.setWordWrap(True)
        form.addRow(series_text("preview"), self.preview_label)

        layout.addLayout(form)

        self.replace_warning = QLabel()
        self.replace_warning.setObjectName("notice")
        self.replace_warning.setWordWrap(True)
        self.replace_warning.hide()
        layout.addWidget(self.replace_warning)

        self.confirm_replace = QCheckBox()
        self.confirm_replace.hide()
        layout.addWidget(self.confirm_replace)

        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        layout.addWidget(self.problem)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.ok_button.setText(series_text("insert"))
        self.cancel_button.setText(series_text("cancel"))
        self.ok_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.first.textChanged.connect(self._refresh)
        self.count.valueChanged.connect(self._refresh)
        self.step.textChanged.connect(self._refresh)
        self.confirm_replace.toggled.connect(self._sync_ok)

        self._refresh()
        theme.fit_dialog(self, 440, self.sizeHint().height())
        self.first.setFocus()
        self.first.selectAll()

    def _mode_changed(self):
        is_geo = self.mode.currentData() == GEOMETRIC
        label = series_text("ratio" if is_geo else "step")
        self.step_label.setText(label)
        self.step.setAccessibleName(label)
        self._refresh()

    def _build_plan(self):
        return plan_numeric_series(
            self.dataset,
            self.target.start_row,
            self.target.column,
            mode=self.mode.currentData(),
            start_text=self.first.text(),
            count=self.count.value(),
            step_text=self.step.text(),
        )

    def _sync_ok(self):
        needs_confirm = self._current_plan is not None and self._current_plan.occupied_count > 0
        self.ok_button.setEnabled(
            self._current_plan is not None and (not needs_confirm or self.confirm_replace.isChecked())
        )

    def _refresh(self):
        try:
            plan = self._build_plan()
        except ValueError as error:
            self._current_plan = None
            self.range_label.setText("—")
            self.preview_label.setText("—")
            self.replace_warning.hide()
            self.confirm_replace.hide()
            self.problem.setText(str(error))
            self.problem.show()
            self._sync_ok()
            return

        self._current_plan = plan
        self.problem.hide()
        self.range_label.setText(plan.range_label)
        mark = display_decimal_mark()
        self.preview_label.setText(format_preview(plan.preview_first, plan.preview_last, plan.count, decimal_mark=mark))

        if plan.occupied_count > 0:
            replace_key = (plan.range_label, plan.occupied_count)
            if replace_key != self._last_replace_key:
                self.confirm_replace.blockSignals(True)
                self.confirm_replace.setChecked(False)
                self.confirm_replace.blockSignals(False)
                self._last_replace_key = replace_key
            self.replace_warning.setText(
                series_text("replace_warning", occupied=plan.occupied_count, total=plan.count)
            )
            self.confirm_replace.setText(series_text("confirm_replace", occupied=plan.occupied_count))
            self.replace_warning.show()
            self.confirm_replace.show()
        else:
            self._last_replace_key = None
            self.replace_warning.hide()
            self.confirm_replace.hide()
        self._sync_ok()

    def accept(self):
        self._refresh()
        if self._current_plan is None:
            return
        if self._current_plan.occupied_count > 0 and not self.confirm_replace.isChecked():
            self.problem.setText(series_text("err.confirm_required"))
            self.problem.show()
            return
        self.plan = self._current_plan
        super().accept()
