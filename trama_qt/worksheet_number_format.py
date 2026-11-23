"""Change → Number format… on Qt worksheets and result tables: display only, one undoable step."""
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel,
                               QRadioButton, QSpinBox, QVBoxLayout)

from analisi.i18n import tr
from analisi.worksheet_number_format import AUTOMATIC, MODES, FormatDraft, edit_text, mode_label


class NumberFormatDialog(QDialog):
    """Choose Automatic, fixed decimals, significant digits or scientific notation for the selected columns.

    ``choice`` is ``("apply", spec)`` after OK, ``("reset", None)`` after Reset and ``None`` after Cancel or Esc,
    which leave the sheet untouched."""

    def __init__(self, parent, target):
        super().__init__(parent)
        self.target = target
        self.draft = FormatDraft(target.spec)
        self.choice = None
        self.setWindowTitle(tr("number_format.title"))
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        self.changing = QLabel(target.changing_text())
        self.changing.setWordWrap(True)
        self.changing.setObjectName("numberFormatColumns")
        layout.addWidget(self.changing)
        self.unchanged = QLabel(target.unchanged_text())
        self.unchanged.setWordWrap(True)
        self.unchanged.setObjectName("muted")
        self.unchanged.setVisible(bool(target.unchanged))
        layout.addWidget(self.unchanged)

        modes = QGroupBox(tr("number_format.mode"))
        modes_layout = QVBoxLayout(modes)
        self.modes = QButtonGroup(self)
        self.mode_buttons = {}
        for number, mode in enumerate(MODES):
            button = QRadioButton(mode_label(mode))
            self.modes.addButton(button, number)
            self.mode_buttons[mode] = button
            modes_layout.addWidget(button)
        form = QFormLayout()
        self.digits_label = QLabel()
        self.digits = QSpinBox()
        self.digits.setAccessibleName(tr("number_format.digits_automatic"))
        form.addRow(self.digits_label, self.digits)
        modes_layout.addLayout(form)
        self.note = QLabel(tr("number_format.automatic_note"))
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        modes_layout.addWidget(self.note)
        layout.addWidget(modes)

        preview = QGroupBox(tr("number_format.preview"))
        preview_form = QFormLayout(preview)
        self.stored = QLabel(edit_text(target.value))
        self.shown = QLabel()
        self.shown.setObjectName("numberFormatPreview")
        preview_form.addRow(tr("number_format.stored"), self.stored)
        preview_form.addRow(tr("number_format.shown"), self.shown)
        if target.sample:
            sample = QLabel(tr("number_format.sample"))
            sample.setObjectName("muted")
            sample.setWordWrap(True)
            preview_form.addRow(sample)
        layout.addWidget(preview)
        explanation = QLabel(tr("number_format.display_only"))
        explanation.setObjectName("muted")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        buttons = QDialogButtonBox()
        self.ok = buttons.addButton(tr("number_format.apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.reset = buttons.addButton(tr("number_format.reset"), QDialogButtonBox.ButtonRole.ResetRole)
        self.reset.setToolTip(tr("number_format.reset_tip"))
        self.reset.setEnabled(target.has_format)
        self.cancel = buttons.addButton(tr("number_format.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.confirm)
        self.reset.clicked.connect(self.restore)
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.mode_buttons[self.draft.mode].setChecked(True)
        self.modes.idClicked.connect(lambda number: self.set_mode(MODES[number]))
        self.digits.valueChanged.connect(self.set_digits)
        self._refresh()

    def set_mode(self, mode):
        self.draft.set_mode(mode)
        self.mode_buttons[mode].setChecked(True)
        self._refresh()

    def set_digits(self, digits):
        if self.draft.mode != AUTOMATIC and self.draft.range()[0] <= digits <= self.draft.range()[1]:
            self.draft.set_digits(digits)
            self._refresh(digits=False)

    def _refresh(self, *, digits=True):
        automatic = self.draft.mode == AUTOMATIC
        self.digits_label.setText(self.draft.digits_label())
        if digits:
            self.digits.blockSignals(True)
            low, high = self.draft.range()
            self.digits.setRange(low, high)
            self.digits.setValue(self.draft.digits)
            self.digits.blockSignals(False)
        self.digits.setEnabled(not automatic)
        self.note.setVisible(automatic)
        self.shown.setText(self.draft.preview(self.target.value))

    def confirm(self):
        self.choice = ("apply", self.draft.spec())
        self.accept()

    def restore(self):
        self.choice = ("reset", None)
        self.accept()
