"""Compact dialog for sorting all rows of a worksheet by a non-calculated source column."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)

from analisi.worksheet_sort import (
    ASCENDING,
    DESCENDING,
    plan_row_sort,
    sort_text,
    sortable_columns,
    x_sort_column,
)

from . import theme
from .project import reorder_rows_allowed


class SortRowsDialog(QDialog):
    """Choose the source key column and sort direction with upfront scope and live validation."""

    def __init__(self, parent, project, title, dataset, *, initial_column=None):
        super().__init__(parent)
        self.project = project
        self.sheet_title = title
        self.initial_revision = project.revision
        self.initial_raw = dataset.raw
        self.plan = None

        self.setWindowTitle(sort_text("title"))
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.sheet_label = QLabel(title)
        self.sheet_label.setObjectName("sortRowsSheet")
        form.addRow(sort_text("sheet"), self.sheet_label)

        self.scope_label = QLabel(sort_text("scope_value", rows=len(dataset.raw)))
        self.scope_label.setObjectName("sortRowsScope")
        form.addRow(sort_text("scope"), self.scope_label)

        self.key_combo = QComboBox()
        self.key_combo.setAccessibleName(sort_text("key"))
        options = sortable_columns(dataset)
        for opt in options:
            self.key_combo.addItem(opt.name, opt.name)
        preferred = self._initial_key_name(dataset, options, initial_column)
        if preferred is not None:
            index = self.key_combo.findData(preferred)
            if index >= 0:
                self.key_combo.setCurrentIndex(index)
        form.addRow(sort_text("key"), self.key_combo)

        direction_row = QHBoxLayout()
        self.ascending_radio = QRadioButton(sort_text("ascending"))
        self.descending_radio = QRadioButton(sort_text("descending"))
        self.ascending_radio.setChecked(True)
        self.direction_group = QButtonGroup(self)
        self.direction_group.addButton(self.ascending_radio)
        self.direction_group.addButton(self.descending_radio)
        direction_row.addWidget(self.ascending_radio)
        direction_row.addWidget(self.descending_radio)
        direction_row.addStretch(1)
        form.addRow(sort_text("direction"), direction_row)

        layout.addLayout(form)

        self.missing_note = QLabel(sort_text("missing_note"))
        self.missing_note.setWordWrap(True)
        layout.addWidget(self.missing_note)

        self.identity_note = QLabel(sort_text("identity_note"))
        self.identity_note.setObjectName("notice")
        self.identity_note.setWordWrap(True)
        self.identity_note.hide()
        layout.addWidget(self.identity_note)

        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        layout.addWidget(self.problem)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.ok_button.setText(sort_text("ok"))
        self.cancel_button.setText(sort_text("cancel"))
        self.ok_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.key_combo.currentIndexChanged.connect(self._refresh)
        self.ascending_radio.toggled.connect(self._refresh)

        self._refresh()
        theme.fit_dialog(self, 420, self.sizeHint().height())
        self.key_combo.setFocus()

    @staticmethod
    def _initial_key_name(dataset, options, initial_column):
        if initial_column is not None:
            for opt in options:
                if opt.display_column == initial_column:
                    return opt.name
        x_name = x_sort_column(dataset)
        if x_name is not None:
            return x_name
        return options[0].name if options else None

    def selected_direction(self) -> str:
        return ASCENDING if self.ascending_radio.isChecked() else DESCENDING

    def is_stale(self) -> bool:
        if self.project.revision != self.initial_revision:
            return True
        if self.sheet_title not in self.project.tables:
            return True
        return self.project.tables[self.sheet_title].raw is not self.initial_raw

    def _compute_plan(self):
        if self.is_stale():
            raise ValueError(sort_text("err.stale"))
        dataset = self.project.tables[self.sheet_title]
        if self.key_combo.count() == 0:
            raise ValueError(sort_text("err.empty"))
        return plan_row_sort(
            dataset,
            self.key_combo.currentData(),
            self.selected_direction(),
            locked=self.project.sheet_locked(("data", self.sheet_title)),
            reorder_allowed=reorder_rows_allowed(dataset),
        )

    def _refresh(self):
        try:
            self.plan = self._compute_plan()
        except ValueError as error:
            self.plan = None
            self.identity_note.hide()
            self.problem.setText(str(error))
            self.problem.show()
            self.ok_button.setEnabled(False)
            return
        self.problem.hide()
        self.identity_note.setVisible(not self.plan.changed)
        self.ok_button.setEnabled(True)

    def accept(self):
        try:
            self.plan = self._compute_plan()
        except ValueError as error:
            self.plan = None
            self.identity_note.hide()
            self.problem.setText(str(error))
            self.problem.show()
            self.ok_button.setEnabled(False)
            return
        super().accept()
