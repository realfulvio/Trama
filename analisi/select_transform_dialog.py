"""Editable condition and formula lists for Select and Transform."""
import tkinter as tk
from tkinter import ttk

from .select_transform import COMPARISONS, MAX_RULES, MISSING, TARGETS


class _Records(ttk.Frame):
    """One compact editor for an ordered set of related text fields."""

    def __init__(self, parent, fields, saved, caption, initial):
        super().__init__(parent)
        self.fields, self.initial = fields, initial
        self.variables, self.widgets, self.records = {}, {}, {}
        self.active = None
        self.loading = False
        self.sequence = 0
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text=caption, wraplength=415, justify="left").grid(row=0, column=0, sticky="w", pady=(0, 6))
        listing = ttk.Frame(self)
        listing.grid(row=1, column=0, sticky="ew")
        listing.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(listing, columns=[key for key, *_ in fields], show="headings",
                                 selectmode="browse", height=4)
        self.tree.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(listing, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._select)
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="w", pady=(6, 8))
        self.add_button = ttk.Button(bar, text="Add", command=self.add)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(bar, text="Remove", command=self.remove)
        self.remove_button.pack(side="left", padx=(5, 0))
        editor = ttk.Frame(self)
        editor.grid(row=3, column=0, sticky="ew")
        for index, (key, label, choices, width) in enumerate(fields):
            self.tree.heading(key, text=label, anchor="w")
            self.tree.column(key, width=7 * width, minwidth=42)
            ttk.Label(editor, text=label).grid(row=0, column=index, sticky="w", padx=(0, 4))
            variable = self.variables[key] = tk.StringVar()
            widget = self.widgets[key] = (ttk.Entry(editor, textvariable=variable, width=width)
                                          if choices is None else ttk.Combobox(
                                              editor, textvariable=variable, width=width, values=choices))
            widget.grid(row=1, column=index, sticky="ew", padx=(0, 4))
            editor.columnconfigure(index, weight=1 if index == len(fields) - 1 else 0)
            variable.trace_add("write", self._changed)
        for record in saved:
            self._insert(record)
        self._select_item(next(iter(self.records), None))

    def _insert(self, record):
        key = f"record{self.sequence}"
        self.sequence += 1
        entry = self.records[key] = {name: record.get(name, "") for name in self.variables}
        self.tree.insert("", "end", iid=key, values=tuple(entry.values()))
        return key

    def _select_item(self, key):
        if key is not None:
            self.tree.selection_set(key)
            self.tree.see(key)
        self._select()

    def _select(self, _=None):
        selected = self.tree.selection()
        self.active = selected[0] if selected else None
        current = self.records.get(self.active, {})
        self.loading = True
        try:
            for name, value in self.variables.items():
                value.set(current.get(name, ""))
            self._states()
        finally:
            self.loading = False

    def _states(self):
        for key, _, choices, _ in self.fields:
            mode = ("normal" if choices is None else "readonly") if self.active else "disabled"
            self.widgets[key].configure(state=mode)
        self.remove_button.configure(state="normal" if self.active else "disabled")
        self.add_button.configure(state="normal" if len(self.records) < MAX_RULES else "disabled")

    def _changed(self, *_):
        if self.loading or self.active is None:
            return
        entry = self.records[self.active] = {name: value.get() for name, value in self.variables.items()}
        self.tree.item(self.active, values=tuple(entry.values()))
        self._states()

    def add(self, record=None):
        if len(self.records) >= MAX_RULES:
            return
        self._select_item(self._insert(self.initial if record is None else record))
        next(iter(self.widgets.values())).focus_set()

    def remove(self):
        if self.active is None:
            return
        keys = list(self.records)
        index = keys.index(self.active)
        self.tree.delete(self.active)
        del self.records[self.active]
        keys = list(self.records)
        self._select_item(keys[min(index, len(keys) - 1)] if keys else None)

    def values(self):
        return list(self.records.values())


class RowFilters(_Records):
    def __init__(self, parent, columns, saved):
        super().__init__(parent, (
            ("column", "Variable", columns, 12),
            ("operator", "Condition", (*COMPARISONS, *MISSING), 13),
            ("target", "Compare to", TARGETS, 9),
            ("value", "Value / variable", columns, 12),
        ), saved, "Rows must match every condition. Leave the list empty to use the whole row range.",
                         {"column": columns[0], "operator": "=", "target": "Number"})

    def _states(self):
        super()._states()
        if self.active is None:
            return
        missing = self.variables["operator"].get() in MISSING
        target = self.variables["target"].get()
        self.widgets["target"].configure(state="disabled" if missing else "readonly")
        self.widgets["value"].configure(state="disabled" if missing else "readonly" if target == "Column" else "normal")


class CalculatedVariables(_Records):
    def __init__(self, parent, saved):
        super().__init__(parent, (("name", "New variable", None, 18), ("expression", "Formula", None, 32)),
                         saved, 'Formulas use the selected rows. Refer to a variable by name or use COL("Variable name").',
                         {})
