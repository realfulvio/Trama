"""Search the nonlinear model catalog by equation or family."""
import tkinter as tk
from tkinter import simpledialog, ttk

from .curve_models import MODEL_GROUPS, MODELS


class EquationDialog(simpledialog.Dialog):
    def __init__(self, parent, choices, current):
        self.choices = set(choices)
        self.current = current
        super().__init__(parent, "Choose an Equation")

    def body(self, master):
        master.columnconfigure(0, weight=1)
        master.rowconfigure(2, weight=1)
        ttk.Label(master, text="Search equations and families", style="DialogTitle.TLabel").grid(
            row=0, column=0, sticky="w", padx=8, pady=(6, 3))
        self.search = tk.StringVar()
        entry = ttk.Entry(master, textvariable=self.search, width=60)
        entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 7))
        self.tree = ttk.Treeview(master, show="tree", selectmode="browse", height=14)
        self.tree.column("#0", width=465)
        scroll = ttk.Scrollbar(master, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=2, column=0, sticky="nsew", padx=(8, 0))
        scroll.grid(row=2, column=1, sticky="ns", padx=(0, 8))
        self.tree.bind("<<TreeviewSelect>>", self.show_description)
        self.tree.bind("<Double-1>", lambda _: self.ok() if self.selected_model() else None)
        self.description = ttk.Label(master, wraplength=465, justify="left")
        self.description.grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 0))
        self.search.trace_add("write", self.fill)
        self.fill()
        return entry

    def fill(self, *_):
        current = self.selected_model() or self.current
        self.tree.delete(*self.tree.get_children())
        query = self.search.get().casefold().strip()
        first, selected = None, None
        for family, models in MODEL_GROUPS.items():
            matches = [model for model in models if model in self.choices
                       and (query in family.casefold() or query in model.casefold())]
            if not matches:
                continue
            category = self.tree.insert("", "end", text=family, open=bool(query) or current in matches)
            for model in matches:
                item = self.tree.insert(category, "end", text=model)
                first = first or item
                if model == current:
                    selected = item
        if selected or first:
            self.tree.selection_set(selected or first)
            self.tree.see(selected or first)
        self.show_description()

    def selected_model(self):
        selection = self.tree.selection()
        name = self.tree.item(selection[0], "text") if selection else None
        return name if name in self.choices else None

    def show_description(self, _=None):
        model = self.selected_model()
        if model is None:
            self.description.configure(text="Select an equation from a family.")
            return
        spec = MODELS[model]
        text = "Parameters · " + ", ".join(spec.parameters)
        if spec.required_fixed:
            text += "\nFixed values required · " + ", ".join(spec.required_fixed)
        if spec.required_shared:
            text += "\nShared or common fixed values · " + ", ".join(spec.required_shared)
        if spec.domain:
            text += "\nX values · " + spec.domain
        self.description.configure(text=text)

    def validate(self):
        self.result = self.selected_model()
        return self.result is not None
