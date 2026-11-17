"""Compact editor for the curves of Plot a function: names and parameter values of one catalog model."""
import math
import tkinter as tk
from tkinter import ttk

from .curve_models import MODELS
from .data import decimal_comma
from .plot_function import MAX_CURVES, _bounds, _is_number


def _text(value):
    if isinstance(value, float):
        text = repr(value)
        return text[:-2] if text.endswith(".0") else text
    return "" if value is None else str(value)


def _parse(text):
    """A number when the text reads as one, otherwise the text itself so the check names it."""
    text = text.strip()
    try:
        return float(decimal_comma(text))
    except ValueError:
        return text


class CurveEditor(ttk.Frame):
    """Add, duplicate, rename and remove curves; set one parameter on every selected curve."""

    def __init__(self, parent, model, curves):
        super().__init__(parent)
        self.model = model
        self.curves = []
        for entry in curves if isinstance(curves, (list, tuple)) else ():
            if isinstance(entry, dict):
                parameters = entry.get("parameters")
                parameters = parameters if isinstance(parameters, dict) else {}
                self.curves.append({"name": str(entry.get("name", "")), "parameters": {
                    key: float(value) if _is_number(value) else value for key, value in parameters.items()}})
        self.columnconfigure(0, weight=1)
        table = ttk.Frame(self)
        table.grid(row=0, column=0, columnspan=4, sticky="nsew")
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, selectmode="extended", height=6, show="headings")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_selection())
        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=0, columnspan=4, sticky="w", pady=(5, 0))
        for text, command in (("Add", self.add), ("Duplicate", self.duplicate), ("Remove", self.remove)):
            ttk.Button(buttons, text=text, width=10, command=command).pack(side="left", padx=(0, 5))
        ttk.Label(self, text="Name").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.name = tk.StringVar()
        self.name_entry = ttk.Entry(self, textvariable=self.name, width=18)
        self.name_entry.grid(row=3, column=0, sticky="ew")
        self.name_entry.bind("<Return>", lambda _: self.rename())
        ttk.Button(self, text="Rename", command=self.rename).grid(row=3, column=1, sticky="w", padx=(5, 0))
        ttk.Label(self, text="Parameter").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Label(self, text="Value for selected curves").grid(row=4, column=1, columnspan=3, sticky="w",
                                                                padx=(5, 0), pady=(6, 0))
        self.parameter = tk.StringVar()
        self.parameter_box = ttk.Combobox(self, textvariable=self.parameter, state="readonly", width=16)
        self.parameter_box.grid(row=5, column=0, sticky="ew")
        self.parameter_box.bind("<<ComboboxSelected>>", lambda _: self.show_selection())
        self.value = tk.StringVar()
        self.value_entry = ttk.Entry(self, textvariable=self.value, width=12)
        self.value_entry.grid(row=5, column=1, sticky="w", padx=(5, 0))
        self.value_entry.bind("<Return>", lambda _: self.apply())
        ttk.Button(self, text="Apply", command=self.apply).grid(row=5, column=2, sticky="w", padx=(5, 0))
        self.note = ttk.Label(self, foreground="#9a3412", wraplength=420, justify="left")
        self.note.grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.set_model(model, keep_all=True)

    # Model -----------------------------------------------------------------------------------------
    def parameters(self):
        spec = MODELS.get(self.model)
        return spec.parameters if spec else ()

    def set_model(self, model, *, keep_all=False):
        """A new model keeps only same-named parameters that are still valid; the note lists the rest."""
        self.model = model
        names = self.parameters()
        bounds = _bounds(MODELS[model]) if names else {}
        for curve in self.curves:
            kept = {}
            for key in names:
                if key not in curve["parameters"]:
                    continue
                value = curve["parameters"][key]
                # A reopened recipe keeps its own values, even invalid ones, so the check can name them.
                if keep_all or (isinstance(value, float) and math.isfinite(value)
                                and bounds[key][0] <= value <= bounds[key][1]):
                    kept[key] = value
            curve["parameters"] = kept
        columns = ["name", *(f"p{i}" for i in range(len(names)))]
        self.tree.configure(columns=columns, displaycolumns=columns)
        self.tree.heading("name", text="Curve")
        self.tree.column("name", width=90, minwidth=60, stretch=False)
        for i, key in enumerate(names):
            self.tree.heading(f"p{i}", text=key)
            self.tree.column(f"p{i}", width=max(70, 8 * len(key)), minwidth=50, stretch=True)
        self.parameter_box.configure(values=names)
        if self.parameter.get() not in names:
            self.parameter.set(names[0] if names else "")
        self.refresh()

    # Display ---------------------------------------------------------------------------------------
    def refresh(self, selected=None):
        selected = list(range(len(self.curves)))[:1] if selected is None else selected
        self.tree.delete(*self.tree.get_children())
        names = self.parameters()
        for index, curve in enumerate(self.curves):
            self.tree.insert("", "end", iid=str(index),
                             values=[curve["name"], *(_text(curve["parameters"].get(key)) for key in names)])
        items = [str(index) for index in selected if 0 <= index < len(self.curves)]
        if items:
            self.tree.selection_set(items)
            self.tree.see(items[0])
        self.show_selection()
        self.show_missing()

    def selected(self):
        return sorted(int(item) for item in self.tree.selection())

    def show_selection(self):
        chosen = self.selected()
        if not chosen:
            return
        curve = self.curves[chosen[0]]
        self.name.set(curve["name"])
        values = {_text(self.curves[i]["parameters"].get(self.parameter.get())) for i in chosen}
        self.value.set(values.pop() if len(values) == 1 else "")

    def show_missing(self):
        names = self.parameters()
        lacking = [curve["name"] or "(unnamed)" for curve in self.curves
                   if any(key not in curve["parameters"] for key in names)]
        if not self.curves:
            self.note.configure(text="Add a curve.")
        elif lacking:
            self.note.configure(text="Fill in the missing parameters of " + ", ".join(lacking) + ".")
        else:
            self.note.configure(text="Select several curves to give them the same parameter value.")

    # Commands --------------------------------------------------------------------------------------
    def unique(self, base):
        taken = {curve["name"].strip().casefold() for curve in self.curves}
        name, number = base, 2
        while name.casefold() in taken or name.casefold() == "x":
            name = f"{base} {number}"
            number += 1
        return name

    def add(self):
        if len(self.curves) >= MAX_CURVES:
            self.note.configure(text=f"Plot up to {MAX_CURVES} curves.")
            return
        self.curves.append({"name": self.unique(f"Curve {len(self.curves) + 1}"), "parameters": {}})
        self.refresh([len(self.curves) - 1])

    def duplicate(self):
        chosen = self.selected()
        if not chosen:
            return
        if len(self.curves) + len(chosen) > MAX_CURVES:
            self.note.configure(text=f"Plot up to {MAX_CURVES} curves.")
            return
        for index in chosen:
            source = self.curves[index]
            self.curves.append({"name": self.unique(f"{source['name'].strip()} copy"),
                                "parameters": dict(source["parameters"])})
        self.refresh(list(range(len(self.curves) - len(chosen), len(self.curves))))

    def remove(self):
        chosen = self.selected()
        for index in reversed(chosen):
            del self.curves[index]
        if chosen:
            self.refresh([min(chosen[0], len(self.curves) - 1)] if self.curves else [])

    def rename(self):
        chosen = self.selected()
        if len(chosen) != 1:
            self.note.configure(text="Select one curve to rename.")
            return
        self.curves[chosen[0]]["name"] = self.name.get()
        self.refresh(chosen)

    def apply(self):
        chosen, key = self.selected(), self.parameter.get()
        if not chosen or not key:
            self.note.configure(text="Select the curves and the parameter to set.")
            return
        value = _parse(self.value.get())
        for index in chosen:
            if value == "":
                self.curves[index]["parameters"].pop(key, None)
            else:
                self.curves[index]["parameters"][key] = value
        self.refresh(chosen)

    def values(self):
        """JSON-ready curve list for the recipe."""
        return [{"name": curve["name"], "parameters": dict(curve["parameters"])} for curve in self.curves]
