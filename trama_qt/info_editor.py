"""Info sheets on Qt: name and scope, constants, and notes with bold, italic and underline.

Same ``InfoSheet`` records as the classic window (``analisi.info_widget`` needs Tk). Note styles are
``(start, end, mask)`` spans counted in Python characters, so supplementary characters (counted twice by Qt)
are converted at the boundary.
"""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from analisi.i18n import active_language, ui
from analisi.info import (MAX_INFO_FIELDS, MAX_INFO_NOTES, NOTE_BOLD, NOTE_ITALIC, NOTE_STYLE_MASK, NOTE_UNDERLINE,
                          InfoSheet)

_ITALIAN = {"New Info sheet": "Nuovo foglio Info", "Info sheet properties": "Proprietà del foglio Info",
            "Sheet name": "Nome del foglio", "Scope": "Ambito", "Entire project": "Tutto il progetto",
            "Properties…": "Proprietà…", "Move sheet up": "Sposta su", "Move sheet down": "Sposta giù",
            "Delete Info sheet…": "Elimina foglio Info…", "Import notes…": "Importa note…",
            "Constants": "Costanti", "Notes": "Note", "Delete row": "Elimina riga", "Bold": "Grassetto",
            "Italic": "Corsivo", "Underline": "Sottolineato",
            "An Info sheet supports up to 500 rows.": "Un foglio Info ha al massimo 500 righe.",
            "Info notes exceed the size limit.": "Le note superano la dimensione massima."}


def t(text):
    return _ITALIAN.get(text, ui(text)) if active_language() == "it" else text


def _python_index(text, units):
    """The Python index of a Qt (UTF-16) position in ``text``."""
    count = 0
    for index, char in enumerate(text):
        if count >= units:
            return index
        count += 2 if ord(char) > 0xFFFF else 1
    return len(text)


def _spans(masks):
    spans, start = [], 0
    for index in range(1, len(masks) + 1):
        if index == len(masks) or masks[index] != masks[start]:
            if masks[start]:
                spans.append((start, index, masks[start]))
            start = index
    return tuple(spans)


class InfoDetails(QDialog):
    """Name and scope of an Info sheet; ``result`` is ``(title, table)``."""

    def __init__(self, parent, title, table, tables, *, creating=False):
        super().__init__(parent)
        self.setWindowTitle(t("New Info sheet" if creating else "Info sheet properties"))
        self.tables, self.result = tuple(tables), None
        form = QFormLayout(self)
        self.title = QLineEdit(title)
        self.title.selectAll()
        form.addRow(t("Sheet name"), self.title)
        self.scope = QComboBox()
        self.scope.addItems([t("Entire project"), *self.tables])
        self.scope.setCurrentIndex(self.tables.index(table) + 1 if table in self.tables else 0)
        form.addRow(t("Scope"), self.scope)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        form.addRow(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def accept(self):
        title = self.title.text().strip()
        index = self.scope.currentIndex()
        table = self.tables[index - 1] if index > 0 else None
        try:
            InfoSheet(title, table=table)
        except ValueError as error:
            self.problem.setText(ui(str(error)))
            self.problem.setVisible(True)
            return
        self.result = title, table
        super().accept()


class InfoEditor(QWidget):
    """Constants and notes of one sheet. ``change(revised)`` stores a sheet and returns False when refused."""

    def __init__(self, sheet, change, error):
        super().__init__()
        self.sheet, self.change, self.error = sheet, change, error
        self._loading = False
        split = QSplitter()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(split)

        left = QWidget()
        column = QVBoxLayout(left)
        column.setContentsMargins(0, 0, 6, 0)
        caption = QLabel(t("Constants"))
        caption.setObjectName("sectionTitle")
        column.addWidget(caption)
        row = QHBoxLayout()
        for text, handler in ((ui("Add row"), self.add_row), (t("Delete row"), self.remove_row),
                              ("↑", lambda: self.move_row(-1)), ("↓", lambda: self.move_row(1))):
            button = QPushButton(text)
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch(1)
        column.addLayout(row)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([ui("Constant"), ui("Value")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._cell_changed)
        column.addWidget(self.table, 1)
        split.addWidget(left)

        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(6, 0, 0, 0)
        caption = QLabel(t("Notes"))
        caption.setObjectName("sectionTitle")
        column.addWidget(caption)
        row = QHBoxLayout()
        self.notes = QTextEdit()
        self.notes.setAcceptRichText(False)
        for text, key, mask in ((t("Bold"), "Ctrl+B", NOTE_BOLD), (t("Italic"), "Ctrl+I", NOTE_ITALIC),
                                (t("Underline"), "Ctrl+U", NOTE_UNDERLINE)):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, mask=mask: self.toggle_style(mask))
            row.addWidget(button)
            QShortcut(QKeySequence(key), self.notes, activated=lambda mask=mask: self.toggle_style(mask))
        importer = QPushButton(t("Import notes…"))
        importer.clicked.connect(self.import_notes)
        row.addWidget(importer)
        row.addStretch(1)
        column.addLayout(row)
        column.addWidget(self.notes, 1)
        split.addWidget(right)
        split.setSizes([320, 480])
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.flush)
        self.notes.textChanged.connect(lambda: None if self._loading else self.timer.start())
        self._fill_table()
        self._render_notes()

    # -- constants ----------------------------------------------------------------------------------
    def _fill_table(self, current=None):
        self._loading = True
        self.table.setRowCount(len(self.sheet.fields))
        for index, pair in enumerate(self.sheet.fields):
            for column, text in enumerate(pair):
                self.table.setItem(index, column, QTableWidgetItem(text))
        self._loading = False
        if current is not None and self.sheet.fields:
            self.table.setCurrentCell(min(current, len(self.sheet.fields) - 1), 0)

    def commit(self, **changes):
        try:
            revised = replace(self.sheet, **changes)
        except (ValueError, OverflowError) as error:
            self.error(error)
            return False
        if revised != self.sheet:
            if self.change(revised) is False:
                return False
            self.sheet = revised
        return True

    def _cell_changed(self, item):
        if self._loading:
            return
        fields = [list(pair) for pair in self.sheet.fields]
        fields[item.row()][item.column()] = item.text()
        if not self.commit(fields=tuple(tuple(pair) for pair in fields)):
            self._fill_table(item.row())

    def add_row(self):
        if len(self.sheet.fields) >= MAX_INFO_FIELDS:
            self.error(t("An Info sheet supports up to 500 rows."))
            return
        if self.commit(fields=(*self.sheet.fields, ("", ""))):
            self._fill_table(len(self.sheet.fields) - 1)
            self.table.editItem(self.table.item(len(self.sheet.fields) - 1, 0))

    def remove_row(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.sheet.fields) and self.commit(
                fields=self.sheet.fields[:row] + self.sheet.fields[row + 1:]):
            self._fill_table(row)

    def move_row(self, step):
        row = self.table.currentRow()
        target = row + step
        if 0 <= row < len(self.sheet.fields) and 0 <= target < len(self.sheet.fields):
            fields = list(self.sheet.fields)
            fields[row], fields[target] = fields[target], fields[row]
            if self.commit(fields=tuple(fields)):
                self._fill_table(target)

    # -- notes --------------------------------------------------------------------------------------
    @staticmethod
    def _format(mask):
        style = QTextCharFormat()
        style.setFontWeight(QFont.Weight.Bold if mask & NOTE_BOLD else QFont.Weight.Normal)
        style.setFontItalic(bool(mask & NOTE_ITALIC))
        style.setFontUnderline(bool(mask & NOTE_UNDERLINE))
        return style

    def _render_notes(self, selection=None):
        self._loading = True
        self.notes.clear()
        cursor = QTextCursor(self.notes.document())
        text, position = self.sheet.notes, 0
        for start, end, mask in self.sheet.note_styles:
            cursor.insertText(text[position:start], self._format(0))
            cursor.insertText(text[start:end], self._format(mask))
            position = end
        cursor.insertText(text[position:], self._format(0))
        if selection is not None:
            cursor.setPosition(selection[0])
            cursor.setPosition(selection[1], QTextCursor.MoveMode.KeepAnchor)
            self.notes.setTextCursor(cursor)
        self._loading = False

    def read_notes(self):
        """``(text, styles)`` of the editor, styles in Python characters."""
        masks, parts, block = [], [], self.notes.document().begin()
        while block.isValid():
            if parts:
                parts.append("\n")
                masks.append(0)
            fragments = block.begin()
            while not fragments.atEnd():
                fragment = fragments.fragment()
                style = fragment.charFormat()
                mask = ((NOTE_BOLD if style.fontWeight() >= QFont.Weight.Bold else 0)
                        | (NOTE_ITALIC if style.fontItalic() else 0) | (NOTE_UNDERLINE if style.fontUnderline() else 0))
                parts.append(fragment.text())
                masks.extend([mask & NOTE_STYLE_MASK] * len(fragment.text()))
                fragments += 1
            block = block.next()
            if not parts:
                parts.append("")
        text = "".join(parts)
        return text, _spans(masks) if len(text) <= MAX_INFO_NOTES else ()

    def flush(self):
        """Store the notes as typed (called on a pause, before leaving the sheet and before saving)."""
        self.timer.stop()
        text, styles = self.read_notes()
        if (text, styles) != (self.sheet.notes, self.sheet.note_styles) and not self.commit(notes=text,
                                                                                            note_styles=styles):
            self._render_notes()

    def toggle_style(self, mask):
        self.flush()
        cursor = self.notes.textCursor()
        if not cursor.hasSelection():
            return
        plain = self.notes.toPlainText()
        first, last = (_python_index(plain, cursor.selectionStart()), _python_index(plain, cursor.selectionEnd()))
        masks = [0] * len(self.sheet.notes)
        for start, end, style in self.sheet.note_styles:
            masks[start:end] = [style] * (end - start)
        remove = all(masks[index] & mask for index in range(first, last))
        for index in range(first, last):
            masks[index] = masks[index] & ~mask if remove else masks[index] | mask
        if self.commit(note_styles=_spans(masks)):
            self._render_notes((cursor.selectionStart(), cursor.selectionEnd()))

    def import_notes(self):
        path, _ = QFileDialog.getOpenFileName(self, t("Import notes…"), "", "UTF-8 text (*.txt);;* (*)")
        if not path:
            return
        try:
            with Path(path).open(encoding="utf-8-sig") as stream:
                text = stream.read(MAX_INFO_NOTES + 1)
            if len(text) > MAX_INFO_NOTES:
                raise ValueError(t("Info notes exceed the size limit."))
        except (OSError, ValueError) as error:
            self.error(error)
            return
        if text:
            cursor = self.notes.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(("\n\n" if self.notes.toPlainText() else "") + text, self._format(0))
            self.flush()
