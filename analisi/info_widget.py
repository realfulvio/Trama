"""Worksheet with ordered constants and freeform notes."""

from collections import deque
from dataclasses import replace
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog, simpledialog, ttk

import pandas as pd

from . import ui_theme
from .grid_data import clipboard_rows, copy_block
from .grid_widget import DataGrid
from .info import (InfoSheet, MAX_INFO_FIELDS, MAX_INFO_NOTES, NOTE_BOLD, NOTE_ITALIC,
                   NOTE_STYLE_MASK, NOTE_UNDERLINE)


_NOTE_TAGS = {mask: f"note-style-{mask}" for mask in range(1, NOTE_STYLE_MASK + 1)}
_NOTE_MASKS = {tag: mask for mask, tag in _NOTE_TAGS.items()}


class InfoDetails(simpledialog.Dialog):
    def __init__(self, parent, title, table, tables, *, creating=False):
        self.name, self.table, self.tables = title, table, tuple(tables)
        super().__init__(parent, "New Info sheet" if creating else "Info sheet properties")

    def body(self, master):
        ttk.Label(master, text="Sheet name").grid(row=0, column=0, sticky="w", padx=8, pady=5)
        ttk.Label(master, text="Scope").grid(row=1, column=0, sticky="w", padx=8, pady=5)
        self.title_field = ttk.Entry(master, width=37)
        self.title_field.insert(0, self.name)
        self.title_field.select_range(0, "end")
        self.title_field.grid(row=0, column=1, sticky="ew", padx=8, pady=5)
        self.scope = ttk.Combobox(master, state="readonly", values=("Entire project", *self.tables))
        self.scope.current(self.tables.index(self.table) + 1 if self.table in self.tables else 0)
        self.scope.grid(row=1, column=1, sticky="ew", padx=8, pady=5)
        self.error = ttk.Label(master, foreground="#9d2931", wraplength=330)
        self.error.grid(row=2, columnspan=2, sticky="w", padx=8, pady=5)
        return self.title_field

    def validate(self):
        title = self.title_field.get().strip()
        index = self.scope.current()
        table = self.tables[index - 1] if index > 0 else None
        try:
            InfoSheet(title, table=table)
        except ValueError as error:
            self.error.configure(text=str(error))
            return False
        self.result = title, table
        return True


class InfoEditor(ttk.Frame):
    def __init__(self, parent, sheet, change, error, properties, remove, move_sheet, address):
        super().__init__(parent)
        self.sheet, self.change, self.error = sheet, change, error
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 8))
        ttk.Button(header, text="Properties…", command=properties).pack(side="left")
        sheet_actions = ttk.Menubutton(header, text="Sheet")
        menu = tk.Menu(sheet_actions, tearoff=False)
        menu.add_command(label="Move sheet up", command=lambda: move_sheet(-1))
        menu.add_command(label="Move sheet down", command=lambda: move_sheet(1))
        menu.add_separator()
        menu.add_command(label="Delete Info sheet…", command=remove)
        sheet_actions.configure(menu=menu)
        sheet_actions.pack(side="left", padx=6)
        ttk.Button(header, text="Import notes…", command=self.import_notes).pack(side="left")

        split = ttk.Panedwindow(self, orient="horizontal")
        split.pack(fill="both", expand=True)
        left = ttk.Frame(split, width=322, padding=(0, 0, 6, 0))
        right = ttk.Frame(split, padding=(6, 0, 0, 0))
        split.add(left, weight=2)
        split.add(right, weight=3)

        ttk.Label(left, text="Constants", font=ui_theme.font(10, "bold")).pack(anchor="w")
        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=(5, 5))
        for label, command in (("Add row", self.add_row), ("Delete row", self.remove_row),
                               ("↑", lambda: self.move_row(-1)), ("↓", lambda: self.move_row(1))):
            ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 3))
        self.grid = DataGrid(left, self._frame(), self.edit, self.copy, self.paste, str,
                             excluded=set(), source_columns=2, address_widget=address)
        self.grid.pack(fill="both", expand=True)

        ttk.Label(right, text="Notes", font=ui_theme.font(10, "bold")).pack(anchor="w")
        note_tools = ttk.Frame(right)
        note_tools.pack(fill="x", pady=(5, 5))
        text_panel = ttk.Frame(right)
        text_panel.pack(fill="both", expand=True)
        self.notes = tk.Text(text_panel, width=20, height=1, wrap="word", padx=9, pady=7, exportselection=False,
                             font=ui_theme.font(10), highlightthickness=1, highlightbackground="#c3d3dd",
                             highlightcolor="#1666b1", borderwidth=0, foreground="#203848")
        self.note_fonts = {}
        for mask, tag in _NOTE_TAGS.items():
            self.note_fonts[mask] = tkfont.Font(
                root=self, family=ui_theme.family(), size=10, weight="bold" if mask & NOTE_BOLD else "normal",
                slant="italic" if mask & NOTE_ITALIC else "roman", underline=bool(mask & NOTE_UNDERLINE),
            )
            self.notes.tag_configure(tag, font=self.note_fonts[mask])
        self.notes.tag_raise("sel")
        for label, key, mask in (("Bold", "b", NOTE_BOLD), ("Italic", "i", NOTE_ITALIC),
                                 ("Underline", "u", NOTE_UNDERLINE)):
            ttk.Button(note_tools, text=label, command=lambda style=mask: self.toggle_note_style(style)).pack(
                side="left", padx=(0, 3))
            self.notes.bind(f"<Control-{key}>", lambda _event, style=mask: self.toggle_note_style(style))
        scrollbar = ttk.Scrollbar(text_panel, command=self.notes.yview)
        self.notes.configure(yscrollcommand=scrollbar.set)
        self.notes.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.notes_undo, self.notes_redo = deque(maxlen=24), deque(maxlen=24)
        self._render_notes()
        self.notes.bind("<<Modified>>", self.notes_changed)
        self.notes.bind("<<Undo>>", lambda _event: self._restore_note_edit(self.notes_undo, self.notes_redo))
        self.notes.bind("<<Redo>>", lambda _event: self._restore_note_edit(self.notes_redo, self.notes_undo))
        self.notes.bind("<Control-y>", lambda _event: self._restore_note_edit(self.notes_redo, self.notes_undo))

    def _frame(self):
        return pd.DataFrame(self.sheet.fields, columns=("Constant", "Value"), dtype="string")

    def commit(self, **changes):
        try:
            revised = replace(self.sheet, **changes)
            if revised != self.sheet:
                self.change(revised)
                self.sheet = revised
        except (ValueError, OverflowError) as error:
            self.error(error)
            return False
        return True

    def replace_rows(self, rows):
        if not self.commit(fields=tuple(rows)):
            return False
        self.grid.frame = self._frame()
        self.grid.minimum_rows = max(20, len(rows) + 1)
        self.grid.resize(None)
        return True

    def put(self, row, column, values):
        size = row + len(values)
        if size > MAX_INFO_FIELDS or any(column + len(line) > 2 for line in values):
            raise ValueError("Paste into the Constant and Value columns. An Info sheet supports up to 500 rows.")
        fields = [list(pair) for pair in self.sheet.fields]
        fields.extend([["", ""] for _ in range(size - len(fields))])
        for offset, line in enumerate(values):
            fields[row + offset][column:column + len(line)] = line
        return self.replace_rows(fields)

    def edit(self, row, column, text):
        try:
            self.put(row, column, [[text]])
        except ValueError as error:
            self.error(error)

    def add_row(self):
        row = len(self.sheet.fields)
        if row >= MAX_INFO_FIELDS:
            self.error("An Info sheet supports up to 500 rows.")
            return
        if self.replace_rows([*self.sheet.fields, ("", "")]):
            self.grid.select((row, 0), reveal=True)
            self.grid.canvas.focus_set()

    def remove_row(self):
        row, _ = self.grid.active_cell
        if row < len(self.sheet.fields):
            self.replace_rows(self.sheet.fields[:row] + self.sheet.fields[row + 1:])

    def move_row(self, direction):
        row, column = self.grid.active_cell
        destination = row + direction
        if 0 <= row < len(self.sheet.fields) and 0 <= destination < len(self.sheet.fields):
            fields = list(self.sheet.fields)
            fields[row], fields[destination] = fields[destination], fields[row]
            if self.replace_rows(fields):
                self.grid.select((destination, column), reveal=True)

    def copy(self):
        if self.focus_get() == self.notes:
            self.notes.event_generate("<<Copy>>")
        else:
            try:
                content = copy_block(self.grid.frame, self.grid.selection, set())
                self.clipboard_clear()
                self.clipboard_append(content.replace("\r\n", "\n") if sys.platform == "win32" else content)
            except (tk.TclError, ValueError) as error:
                self.error(error)
        return "break"

    def paste(self):
        if self.focus_get() == self.notes:
            self.notes.event_generate("<<Paste>>")
            return "break"
        try:
            values = clipboard_rows(self.clipboard_get(), max_columns=2)
            row, column, _, _ = self.grid.selection
            if self.put(row, column, values):
                self.grid.select_block(row, column, row + len(values) - 1, column + len(values[0]) - 1)
        except (tk.TclError, ValueError) as error:
            self.error(error)
        return "break"

    def _render_notes(self):
        caret = self.notes.index("insert")
        self.notes.delete("1.0", "end")
        position = 0
        for start, end, mask in self.sheet.note_styles:
            self.notes.insert("end-1c", self.sheet.notes[position:start], ())
            self.notes.insert("end-1c", self.sheet.notes[start:end], (_NOTE_TAGS[mask],))
            position = end
        self.notes.insert("end-1c", self.sheet.notes[position:], ())
        self.notes.mark_set("insert", caret)
        self.notes.edit_modified(False)

    def _note_styles(self):
        ranges = []
        for mask, tag in _NOTE_TAGS.items():
            endpoints = iter(self.notes.tag_ranges(tag))
            ranges.extend((start, end, mask) for start, end in zip(endpoints, endpoints, strict=True))
        ranges.sort(key=lambda item: tuple(map(int, str(item[0]).split("."))))
        spans, position, previous = [], 0, "1.0"
        for start, end, mask in ranges:
            # Measure successive text slices in Python so supplementary
            # Unicode characters have the same width on every Tk version.
            position += len(self.notes.get(previous, start))
            finish = position + len(self.notes.get(start, end))
            spans.append((position, finish, mask))
            position, previous = finish, end
        return tuple(spans)

    def _commit_notes(self):
        previous = self.sheet.notes, self.sheet.note_styles
        notes = self.notes.get("1.0", "end-1c")
        styles = self._note_styles() if len(notes) <= MAX_INFO_NOTES else ()
        if (notes, styles) == previous:
            return
        if self.commit(notes=notes, note_styles=styles):
            self.notes_undo.append(previous)
            self.notes_redo.clear()
        else:
            self._render_notes()

    def notes_changed(self, _event=None):
        if self.notes.edit_modified():
            self.notes.edit_modified(False)
            self._commit_notes()

    def toggle_note_style(self, mask):
        self.notes_changed()
        selection = self.notes.tag_ranges("sel")
        self.notes.focus_set()
        if not selection:
            return "break"
        first, last = map(str, selection)
        if self.notes.compare(last, ">", "end-1c"):
            last = self.notes.index("end-1c")
        if self.notes.compare(first, ">=", last):
            return "break"
        current = next((_NOTE_MASKS[tag] for tag in self.notes.tag_names(first) if tag in _NOTE_MASKS), 0)
        spans, start = [], first
        for event, tag, position in self.notes.dump(first, last, tag=True):
            if tag in _NOTE_MASKS:
                if position != start:
                    spans.append((start, position, current))
                    start = position
                if event == "tagon":
                    current = _NOTE_MASKS[tag]
                elif current == _NOTE_MASKS[tag]:
                    current = 0
        if start != last:
            spans.append((start, last, current))
        remove = all(style & mask for _, _, style in spans)
        for tag in _NOTE_TAGS.values():
            self.notes.tag_remove(tag, first, last)
        for start, end, style in spans:
            revised = style & ~mask if remove else style | mask
            if revised:
                self.notes.tag_add(_NOTE_TAGS[revised], start, end)
        self._commit_notes()
        return "break"

    def _restore_note_edit(self, history, opposite):
        self.notes_changed()
        if history:
            notes, styles = history[-1]
            previous = self.sheet.notes, self.sheet.note_styles
            if self.commit(notes=notes, note_styles=styles):
                history.pop()
                opposite.append(previous)
                self._render_notes()
        return "break"

    def import_notes(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("UTF-8 text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with Path(path).open(encoding="utf-8-sig") as stream:
                text = stream.read(MAX_INFO_NOTES + 1)
            if len(text) > MAX_INFO_NOTES:
                raise ValueError("Info notes exceed the size limit.")
            if text:
                if self.notes.get("1.0", "end-1c"):
                    text = "\n\n" + text
                self.notes.insert("end-1c", text)
                self.notes_changed()
        except (OSError, ValueError) as error:
            self.error(error)
