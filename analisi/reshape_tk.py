"""Classica editor for the shared long/wide reshape analysis."""

import tkinter as tk
from tkinter import ttk

import pandas as pd

from . import reshape_long_wide as rl
from .i18n import active_language, tr, translate_message


DIRECTION_KEYS = {rl.LONG_TO_WIDE: "reshape.choice.long_to_wide", rl.WIDE_TO_LONG: "reshape.choice.wide_to_long"}
ORDERED_FIELDS = (rl.ID_COLUMNS, rl.MEASURE_COLUMNS)


def defaults(columns, numeric, saved):
    ids = saved.get(rl.ID_COLUMNS) or columns[:1]
    remaining = [name for name in columns if name not in ids]
    numbers = [name for name in remaining if name in numeric]
    names = next((name for name in remaining if name not in numeric), next(iter(remaining), ""))
    value = next((name for name in reversed(numbers or remaining) if name != names), "")
    return {
        rl.ID_COLUMNS: ids, rl.NAME_COLUMN: names, rl.VALUE_COLUMN: value, rl.MEASURE_COLUMNS: numbers,
        rl.OUTPUT_NAMES: rl.DEFAULT_NAMES, rl.OUTPUT_VALUES: rl.DEFAULT_VALUES, **saved,
    }


def format_error(error):
    return translate_message(error, "reshape.error.",
                             dict.fromkeys(("count", "limit", "cells", "rows", "columns"), _italian_count))


def _italian_count(text):
    return text.replace(",", ".")


def _number(value):
    text = f"{value:,}"
    return _italian_count(text) if active_language() == "it" else text


def _plural(key, count):
    return tr(f"{key}_one" if count == 1 else f"{key}_many", count=_number(count))


def _cell(value):
    return "" if pd.isna(value) else rl.level_name(value)


class OrderedColumns(ttk.Frame):
    """Multiple selection in the order shown, with the selected column movable."""

    def __init__(self, parent, columns, selected):
        super().__init__(parent)
        self.columns = list(dict.fromkeys([*selected, *columns]))
        self.listbox = tk.Listbox(self, selectmode="multiple", exportselection=False, height=4, width=25)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.grid(row=0, column=0, rowspan=2, sticky="nsew")
        scrollbar.grid(row=0, column=1, rowspan=2, sticky="ns")
        ttk.Button(self, text=tr("reshape.caption.up"), command=lambda: self.move(-1)).grid(row=0, column=2)
        ttk.Button(self, text=tr("reshape.caption.down"), command=lambda: self.move(1)).grid(row=1, column=2)
        self.columnconfigure(0, weight=1)
        self.listbox.bind("<Control-Up>", lambda _: self.move(-1))
        self.listbox.bind("<Control-Down>", lambda _: self.move(1))
        self._refresh(set(selected))

    def _refresh(self, selected):
        self.listbox.delete(0, "end")
        for index, name in enumerate(self.columns):
            self.listbox.insert("end", name)
            if name in selected:
                self.listbox.selection_set(index)

    def values(self):
        return [self.columns[index] for index in self.listbox.curselection()]

    def unselect(self, names):
        for index in self.listbox.curselection():
            if self.columns[index] in names:
                self.listbox.selection_clear(index)

    def move(self, step):
        index = self.listbox.index("active")
        target = index + step
        if 0 <= index < len(self.columns) and 0 <= target < len(self.columns):
            selected = set(self.values())
            self.columns[index], self.columns[target] = self.columns[target], self.columns[index]
            self._refresh(selected)
            self.listbox.activate(target)
            self.listbox.see(target)
            self.listbox.event_generate("<<ListboxSelect>>")
        return "break"

    def focus_target(self):
        return self.listbox


class ReshapeEditor:
    def __init__(self, dialog):
        self.dialog = dialog
        self.page = ttk.Frame(dialog.fields, padding=10)
        dialog.fields.add(self.page, text=tr("reshape.tab.preview"))
        self.pending = None
        self.summary = ttk.Label(self.page, wraplength=400, justify="left")
        self.summary.pack(anchor="w", pady=(0, 6))
        self.note = ttk.Label(self.page, wraplength=400, justify="left")
        self.note.pack(side="bottom", anchor="w", pady=(6, 0))
        body = ttk.Frame(self.page)
        body.pack(fill="both", expand=True)
        self.preview = ttk.Treeview(body, show="headings", selectmode="none")
        vertical = ttk.Scrollbar(body, orient="vertical", command=self.preview.yview)
        horizontal = ttk.Scrollbar(body, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        vertical.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x")
        self.preview.pack(fill="both", expand=True)
        controls = dialog.controls
        self.traces = [(control, control.trace_add("write", self.schedule))
                       for name, (_, control) in controls.items() if name not in ORDERED_FIELDS]
        ids, measures = (controls[name][1] for name in ORDERED_FIELDS)
        ids.listbox.bind("<<ListboxSelect>>", lambda _: self.selection_changed(ids, measures))
        measures.listbox.bind("<<ListboxSelect>>", lambda _: self.selection_changed(measures, ids))
        self.page.bind("<Destroy>", self.dispose)
        self.pending = self.page.after(150, self.refresh_preview)
        self.show_active_fields()

    def selection_changed(self, current, other):
        other.unselect(set(current.values()))
        self.schedule()

    def request(self):
        return rl.canonical({name: control.values() if name in ORDERED_FIELDS else control.get()
                             for name, (_, control) in self.dialog.controls.items()})

    def cancel_preview(self):
        if self.pending is not None:
            self.page.after_cancel(self.pending)
            self.pending = None

    def dispose(self, _):
        self.cancel_preview()
        for control, trace in self.traces:
            control.trace_remove("write", trace)
        self.traces.clear()

    def show_active_fields(self):
        chosen = self.dialog.controls[rl.DIRECTION][1].get()
        active = rl.WIDE_FIELDS if chosen == rl.LONG_TO_WIDE else rl.LONG_FIELDS
        self.dialog.show_fields({name: name in active for name in rl.OPTIONS})

    def schedule(self, *_):
        self.show_active_fields()
        self.cancel_preview()
        self.pending = self.page.after(150, lambda: self.refresh_preview(edited=True))

    def refresh_preview(self, *, edited=False):
        self.cancel_preview()
        self.preview.delete(*self.preview.get_children())
        try:
            result = rl.preview(self.dialog.data, self.request())
        except (ValueError, OverflowError) as error:
            self.summary.configure(text=tr("reshape.preview.error", message=format_error(error)))
            self.note.configure(text="")
            self.preview.configure(columns=())
            return
        if edited and self.dialog.error_label is not None:
            self.dialog.error_label.master.grid_remove()
        self.summary.configure(text=tr("reshape.preview.summary", rows=_plural("reshape.preview.rows", result.rows),
                                        columns=_plural("reshape.preview.columns", result.columns),
                                        mapped=_number(result.mapped), missing=_number(result.missing)))
        notes = [_plural(key, count) for key, count in (("reshape.preview.hidden_rows", result.hidden_rows),
                                                         ("reshape.preview.hidden_columns", result.hidden_columns))
                 if count]
        self.note.configure(text=" ".join(notes) or tr("reshape.preview.complete"))
        columns = tuple(f"column{index}" for index in range(len(result.table.columns)))
        self.preview.configure(columns=columns)
        for key, title in zip(columns, result.table.columns, strict=True):
            self.preview.heading(key, text=str(title))
            self.preview.column(key, minwidth=80, width=125, stretch=False)
        for values in result.table.itertuples(index=False, name=None):
            self.preview.insert("", "end", values=tuple(_cell(value) for value in values))
