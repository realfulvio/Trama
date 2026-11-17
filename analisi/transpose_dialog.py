"""Editor for the Y sets of Transpose X and Y: a name, a mode and the source columns of each set."""
import tkinter as tk
from tkinter import ttk

from .transpose_xy import MAX_SETS, MODES, SINGLE


class TransposeSets(ttk.Frame):
    """List of Y sets with a small editor below it; ``values()`` gives the saved ``Y sets`` option."""

    def __init__(self, parent, columns, saved, suggest):
        super().__init__(parent)
        self.columns, self.suggest = list(columns), suggest
        self.records, self.active, self.loading, self.sequence = {}, None, False, 0
        self.columnconfigure(0, weight=1)
        listing = ttk.Frame(self)
        listing.grid(row=0, column=0, sticky="ew")
        listing.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(listing, columns=("name", "mode", "columns"), show="headings",
                                 selectmode="browse", height=4)
        for key, label, width in (("name", "Name", 100), ("mode", "Mode", 120), ("columns", "Source columns", 200)):
            self.tree.heading(key, text=label, anchor="w")
            self.tree.column(key, width=width, minwidth=50)
        self.tree.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(listing, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._select)
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="w", pady=(6, 6))
        self.add_button = ttk.Button(bar, text="Add", command=self.add)
        self.remove_button = ttk.Button(bar, text="Remove", command=self.remove)
        self.suggest_button = ttk.Button(bar, text="Use table roles", command=self.use_suggestion)
        for button in (self.add_button, self.remove_button, self.suggest_button):
            button.pack(side="left", padx=(0, 5))
        editor = ttk.Frame(self)
        editor.grid(row=2, column=0, sticky="ew")
        editor.columnconfigure(1, weight=1)
        self.variables = {"name": tk.StringVar(), "mode": tk.StringVar()}
        ttk.Label(editor, text="Name").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.name_entry = ttk.Entry(editor, textvariable=self.variables["name"], width=18)
        self.name_entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(editor, text="Mode").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        self.mode_box = ttk.Combobox(editor, textvariable=self.variables["mode"], values=MODES, state="readonly",
                                     width=18)
        self.mode_box.grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Label(editor, text="Columns").grid(row=2, column=0, sticky="nw", padx=(0, 6), pady=(4, 0))
        panel = ttk.Frame(editor)
        panel.grid(row=2, column=1, sticky="ew", pady=(4, 0))
        self.listbox = tk.Listbox(panel, selectmode="extended", exportselection=False, height=4)
        shifter = ttk.Scrollbar(panel, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=shifter.set)
        shifter.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)
        for name in self.columns:
            self.listbox.insert("end", name)
        for variable in self.variables.values():
            variable.trace_add("write", self._changed)
        self.listbox.bind("<<ListboxSelect>>", self._changed)
        self.set_values(saved)

    def set_values(self, sets):
        for key in list(self.records):
            self.tree.delete(key)
        self.records.clear()
        for item in sets if isinstance(sets, (list, tuple)) else ():
            if isinstance(item, dict):
                self._insert({"name": str(item.get("name", "")), "mode": item.get("mode", SINGLE),
                              "columns": [c for c in item.get("columns", ()) if isinstance(c, str)]})
        self._select_item(next(iter(self.records), None))

    def _show(self, record):
        return (record["name"], record["mode"], "; ".join(record["columns"]))

    def _insert(self, record):
        key = f"set{self.sequence}"
        self.sequence += 1
        self.records[key] = record
        self.tree.insert("", "end", iid=key, values=self._show(record))
        return key

    def _select_item(self, key):
        if key is not None:
            self.tree.selection_set(key)
            self.tree.see(key)
        self._select()

    def _select(self, _=None):
        selected = self.tree.selection()
        self.active = selected[0] if selected else None
        current = self.records.get(self.active)
        self.loading = True
        try:
            self.variables["name"].set(current["name"] if current else "")
            self.variables["mode"].set(current["mode"] if current else "")
            self.listbox.selection_clear(0, "end")
            for column in current["columns"] if current else ():
                if column in self.columns:
                    self.listbox.selection_set(self.columns.index(column))
            state = "normal" if current else "disabled"
            self.name_entry.configure(state=state)
            self.mode_box.configure(state="readonly" if current else "disabled")
            self.remove_button.configure(state=state)
            self.add_button.configure(state="normal" if len(self.records) < MAX_SETS else "disabled")
        finally:
            self.loading = False

    def _changed(self, *_):
        if self.loading or self.active is None:
            return
        record = self.records[self.active]
        record["name"] = self.variables["name"].get()
        record["mode"] = self.variables["mode"].get()
        record["columns"] = [self.columns[i] for i in self.listbox.curselection()]
        self.tree.item(self.active, values=self._show(record))

    def choose_columns(self, names):
        """Select the source columns of the active set (what a click in the list does)."""
        self.listbox.selection_clear(0, "end")
        for name in names:
            self.listbox.selection_set(self.columns.index(name))
        self._changed()

    def add(self):
        if len(self.records) >= MAX_SETS:
            return
        self._select_item(self._insert({"name": f"Set {self.sequence + 1}", "mode": SINGLE, "columns": []}))
        self.name_entry.focus_set()

    def remove(self):
        if self.active is None:
            return
        keys = list(self.records)
        index = keys.index(self.active)
        self.tree.delete(self.active)
        del self.records[self.active]
        keys = list(self.records)
        self._select_item(keys[min(index, len(keys) - 1)] if keys else None)

    def use_suggestion(self):
        self.set_values(self.suggest())

    def values(self):
        return [{"name": r["name"], "mode": r["mode"], "columns": list(r["columns"])} for r in self.records.values()]
