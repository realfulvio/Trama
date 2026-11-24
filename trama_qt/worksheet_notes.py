"""Modeless worksheet notes attached to the data sheet that owns them."""
from dataclasses import replace

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout)

from analisi.info import InfoSheet
from analisi.i18n import ui
from .info_editor import InfoEditor
from .strings import qt


class WorksheetNotes(QDialog):
    def __init__(self, window, ref):
        super().__init__(window, Qt.WindowType.Tool)
        self.setObjectName("worksheetNotes")
        self.setWindowTitle(qt("qt.sheet_notes_title", name=window.project.sheet_title(ref)))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(420, 350)
        self.window, self.project = window, window.project
        self.sheet_key = self.project.sheet_key(ref)
        self.table = ref[1] if ref[0] == "data" else None
        self.editor = None
        outer = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.select = QComboBox()
        self.select.setAccessibleName(qt("qt.sheet_notes"))
        controls.addWidget(self.select, 1)
        add = QPushButton(qt("qt.sheet_note_new"))
        add.setObjectName("addWorksheetNote")
        add.clicked.connect(self.add_note)
        controls.addWidget(add)
        outer.addLayout(controls)
        self.empty = QLabel(qt("qt.sheet_note_empty"))
        self.empty.setWordWrap(True)
        outer.addWidget(self.empty)
        self.stack = QVBoxLayout()
        outer.addLayout(self.stack, 1)
        tools = QHBoxLayout()
        self.rename = QPushButton(qt("qt.sheet_note_rename"))
        self.rename.clicked.connect(self.rename_note)
        self.remove = QPushButton(qt("qt.sheet_note_delete"))
        self.remove.clicked.connect(self.remove_note)
        close = QPushButton(ui("Close"))
        close.clicked.connect(self.close)
        for button in (self.rename, self.remove, close):
            button.setAutoDefault(False)
            tools.addWidget(button)
        outer.addLayout(tools)
        self.select.currentIndexChanged.connect(self._select)
        self.rebuild()

    def rebuild(self, uid=None):
        with QSignalBlocker(self.select):
            self.select.clear()
            for item in self.project.info_sheets.values():
                if self.applies(item):
                    self.select.addItem(item.title, item.uid)
            if uid:
                self.select.setCurrentIndex(self.select.findData(uid))
        self._select()

    def applies(self, note):
        if not note.floating:
            return False
        return note.worksheet == self.sheet_key if self.table is None else note.table == self.table

    def _select(self, _index=None):
        if self.editor is not None:
            self.flush()
            previous, self.editor = self.editor, None
            self.stack.removeWidget(previous)
            previous.deleteLater()
        uid = self.select.currentData()
        self.empty.setVisible(uid is None)
        self.rename.setEnabled(uid is not None)
        self.remove.setEnabled(uid is not None)
        if uid is not None:
            self.editor = InfoEditor(self.project.info_sheets[uid], self.change, self.window.error, notes_only=True)
            self.stack.addWidget(self.editor)

    def flush(self):
        if self.editor is not None and self.editor.sheet.uid in self.project.info_sheets:
            self.editor.flush()

    def change(self, sheet):
        if self.project is not self.window.project or sheet.uid not in self.project.info_sheets:
            return False
        return self.window.change_info(sheet)

    def add_note(self):
        self.flush()
        title = qt("qt.sheet_note_default", number=self.select.count() + 1)
        try:
            note = InfoSheet(title, table=self.table, floating=True, use_constants=False,
                             worksheet=self.sheet_key if self.table is None else None)
            self.project.update_info_sheets({**self.project.info_sheets, note.uid: note})
        except ValueError as error:
            self.window.error(error)
            return
        self.window.refresh()
        self.rebuild(note.uid)
        self.editor.notes.setFocus()

    def rename_note(self):
        self.flush()
        uid = self.select.currentData()
        note = self.project.info_sheets[uid]
        title, ok = QInputDialog.getText(self, qt("qt.sheet_note_rename"), qt("qt.sheet_name"), text=note.title)
        if ok:
            try:
                renamed = replace(note, title=title.strip())
            except ValueError as error:
                self.window.error(error)
                return
            if self.change(renamed):
                self.rebuild(uid)

    def remove_note(self):
        self.flush()
        uid = self.select.currentData()
        note = self.project.info_sheets[uid]
        answer = QMessageBox.question(self, qt("qt.sheet_note_delete"),
                                      qt("qt.sheet_note_confirm_delete", name=note.title))
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.project.update_info_sheets({key: value for key, value in self.project.info_sheets.items()
                                                 if key != uid})
            except ValueError as error:
                self.window.error(error)
                return
            self.window.refresh()
            self.rebuild()

    def closeEvent(self, event):
        self.flush()
        super().closeEvent(event)
