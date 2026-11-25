"""A plain-text box whose selected portions can be subscript or superscript (``analisi.text_markup``).

The box shows ``CO₂`` and ``10⁻³`` as they will be drawn, but what it holds is the plain text (``CO2``,
``10-3``) and a list of ``[start, end, mask]`` spans in Python character positions, which is exactly what an
annotation stores. Qt counts UTF-16 units, so positions are converted on the way in and out; a paste keeps
the text and drops the formatting of its source.
"""
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit

from analisi.text_markup import INHERITED, MIXED, SUBSCRIPT, SUPERSCRIPT, UNIFORM, script_state, validate_spans

_ALIGNMENT = {SUBSCRIPT: QTextCharFormat.VerticalAlignment.AlignSubScript,
              SUPERSCRIPT: QTextCharFormat.VerticalAlignment.AlignSuperScript}


def utf16_offsets(text):
    """``offsets[i]`` is the UTF-16 position of character ``i`` of ``text``; one more entry marks the end."""
    offsets, position = [], 0
    for char in text:
        offsets.append(position)
        position += 2 if ord(char) > 0xFFFF else 1
    offsets.append(position)
    return offsets


def normalise_newlines(text, spans=()):
    """``text`` with ``\\r\\n`` and ``\\r`` as ``\\n`` (what the box holds) and the spans moved with it."""
    if "\r" not in text:
        return text, [list(span) for span in spans]
    kept, shift = [], []
    index = 0
    while index < len(text):
        char = text[index]
        shift.append(len(kept))
        if char == "\r":
            kept.append("\n")
            if text[index + 1:index + 2] == "\n":
                index += 1
                shift.append(len(kept) - 1)
        else:
            kept.append(char)
        index += 1
    shift.append(len(kept))
    return "".join(kept), [[shift[start], shift[end], mask] for start, end, mask in spans]


class ScriptEdit(QTextEdit):
    def __init__(self, text="", spans=(), parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.set_content(text, spans)

    def insertFromMimeData(self, source):
        if source.hasText():
            self.insertPlainText(source.text())

    def set_content(self, text, spans=()):
        text, spans = normalise_newlines(text, spans)
        self.setPlainText(text)
        offsets = utf16_offsets(text)
        for start, end, mask in spans:
            cursor = QTextCursor(self.document())
            cursor.setPosition(offsets[start])
            cursor.setPosition(offsets[end], QTextCursor.MoveMode.KeepAnchor)
            format_ = QTextCharFormat()
            format_.setVerticalAlignment(_ALIGNMENT[mask])
            cursor.mergeCharFormat(format_)
        self.document().clearUndoRedoStacks()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)

    def content(self):
        """``(text, spans)``: the plain text and its subscript and superscript portions."""
        text = self.toPlainText()
        offsets = utf16_offsets(text)
        position = {offset: index for index, offset in enumerate(offsets)}
        spans = []
        block = self.document().begin()
        while block.isValid():
            fragment_iterator = block.begin()
            while not fragment_iterator.atEnd():
                fragment = fragment_iterator.fragment()
                alignment = fragment.charFormat().verticalAlignment()
                mask = {_ALIGNMENT[SUBSCRIPT]: SUBSCRIPT, _ALIGNMENT[SUPERSCRIPT]: SUPERSCRIPT}.get(alignment)
                if mask is not None and fragment.length():
                    start = position.get(fragment.position())
                    end = position.get(fragment.position() + fragment.length())
                    if start is not None and end is not None and end > start:
                        spans.append([start, end, mask])
                fragment_iterator += 1
            block = block.next()
        return text, validate_spans(text, spans)

    def selection_range(self):
        """The selected characters as Python positions ``(start, end)``; equal when nothing is selected."""
        cursor = self.textCursor()
        text = self.toPlainText()
        index = {offset: i for i, offset in enumerate(utf16_offsets(text))}
        low, high = sorted((cursor.position(), cursor.anchor()))
        return index.get(low, 0), index.get(high, len(text))

    def script(self):
        """``(INHERITED, None)``, ``(UNIFORM, mask)`` or ``(MIXED, None)`` for the selection (or the caret)."""
        start, end = self.selection_range()
        if start == end:
            alignment = self.currentCharFormat().verticalAlignment()
            for mask, value in _ALIGNMENT.items():
                if alignment == value:
                    return UNIFORM, mask
            return INHERITED, None
        return script_state(self.content()[1], start, end)

    def set_script(self, mask):
        """Draw the selection (or what is typed next) as ``SUBSCRIPT``, ``SUPERSCRIPT`` or normal (``None``)."""
        format_ = QTextCharFormat()
        format_.setVerticalAlignment(_ALIGNMENT.get(mask, QTextCharFormat.VerticalAlignment.AlignNormal))
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(format_)
        self.mergeCurrentCharFormat(format_)

    def toggle_script(self, mask):
        kind, current = self.script()
        self.set_script(None if kind == UNIFORM and current == mask else mask)

    def clear_scripts(self):
        """Explicit cleanup: every subscript and superscript of the selection, or of the whole text if none."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.Document)
        format_ = QTextCharFormat()
        format_.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        cursor.mergeCharFormat(format_)
        self.mergeCurrentCharFormat(format_)


__all__ = ["INHERITED", "MIXED", "UNIFORM", "ScriptEdit", "normalise_newlines", "utf16_offsets"]
