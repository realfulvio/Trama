"""Qt dialog for the shared process-count preference."""
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout

from analisi import parallel
from analisi.i18n import tr


class ProcessesDialog(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setting = parallel.load_setting(path)
        self.setWindowTitle(tr("processes.title"))
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        processors = parallel.logical_processors()
        layout.addWidget(QLabel(tr("processes.processors", count=processors)))
        self.count = QComboBox()
        self.count.setAccessibleName(tr("processes.title"))
        self.count.addItem(tr("processes.auto", count=parallel.auto_processes(processors)), parallel.AUTO)
        self.count.addItem(tr("processes.single"), 1)
        for count in range(2, parallel.MAX_PROCESSES + 1):
            self.count.addItem(str(count), count)
        self.count.setCurrentIndex(self.count.findData(self.setting))
        layout.addWidget(self.count)
        note = QLabel(tr("processes.note"))
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("processes.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("processes.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            self.setting = parallel.save_setting(self.path, self.count.currentData())
        except OSError as error:
            QMessageBox.critical(self, self.windowTitle(), tr("processes.error", error=error))
            return
        super().accept()
