"""Font preference dialog for the Qt worksheet and result views."""
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QSpinBox

from analisi.i18n import tr
from analisi.worksheet_appearance import MAX_FONT_SIZE, MIN_FONT_SIZE


class TableFontDialog(QDialog):
    def __init__(self, parent, preference):
        super().__init__(parent)
        self.setWindowTitle(tr("command.table_font").rstrip("…"))
        form = QFormLayout(self)
        self.family = QComboBox()
        self.family.addItem(tr("worksheet.font_default"), "")
        family, size = preference
        families = sorted(set(QFontDatabase.families()) | ({family} if family else set()), key=str.casefold)
        for name in families:
            self.family.addItem(name, name)
        self.family.setCurrentIndex(self.family.findData(family))
        self.size = QSpinBox()
        self.size.setRange(MIN_FONT_SIZE - 1, MAX_FONT_SIZE)
        self.size.setSpecialValueText(tr("worksheet.font_default"))
        self.size.setValue(size if size is not None else MIN_FONT_SIZE - 1)
        form.addRow(tr("worksheet.font_family"), self.family)
        form.addRow(tr("worksheet.font_size"), self.size)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def preference(self):
        size = self.size.value()
        return self.family.currentData(), size if size >= MIN_FONT_SIZE else None
