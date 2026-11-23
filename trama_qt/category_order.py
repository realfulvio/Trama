"""Reorder the selected worksheet's category levels in the Qt interface."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout

from analisi.i18n import tr


class CategoryOrderDialog(QDialog):
    def __init__(self, parent, column, draft):
        super().__init__(parent)
        self.draft = draft
        self.setWindowTitle(tr("command.category_order").removesuffix("…"))
        layout = QVBoxLayout(self)
        heading = QLabel(column)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        note = QLabel(tr("worksheet_order.note"))
        note.setWordWrap(True)
        layout.addWidget(note)
        entries = QHBoxLayout()
        self.levels = QListWidget()
        self.levels.setMinimumHeight(7 * self.levels.fontMetrics().lineSpacing())
        entries.addWidget(self.levels, 1)
        controls = QVBoxLayout()
        self.up = QPushButton(tr("pdf.up"))
        self.down = QPushButton(tr("pdf.down"))
        self.reset = QPushButton(tr("worksheet_order.reset"))
        self.up.clicked.connect(lambda: self.move(-1))
        self.down.clicked.connect(lambda: self.move(1))
        self.reset.clicked.connect(self.restore)
        for button in (self.up, self.down, self.reset):
            controls.addWidget(button)
        controls.addStretch()
        entries.addLayout(controls)
        layout.addLayout(entries)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("graph.inspector.apply"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.levels.currentRowChanged.connect(self.sync_buttons)
        for direction, step in (("Up", -1), ("Down", 1)):
            shortcut = QShortcut(QKeySequence(f"Alt+{direction}"), self.levels)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda step=step: self.move(step))
        self.resize(460, 315)
        self.render()
        self.levels.setFocus()

    def render(self, row=0):
        self.levels.clear()
        self.levels.addItems([name for _, name in self.draft.levels])
        self.levels.setCurrentRow(row)
        self.sync_buttons()

    def sync_buttons(self):
        row = self.levels.currentRow()
        self.up.setEnabled(row > 0)
        self.down.setEnabled(0 <= row < self.levels.count() - 1)

    def move(self, step):
        self.render(self.draft.move(self.levels.currentRow(), step))

    def restore(self):
        self.draft.restore_automatic()
        self.render()
