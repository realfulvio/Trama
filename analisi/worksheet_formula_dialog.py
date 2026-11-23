"""Classic desktop editor for calculated worksheet columns."""
from copy import copy
import tkinter as tk
from tkinter import simpledialog, ttk

from .formula_reference import function_references, matching_references, variable_references
from .grid_headings import column_label
from .i18n import tr, translate_message, ui


class WorksheetFormulaDialog(simpledialog.Dialog):
    def __init__(self, parent, dataset, column=None, *, name=""):
        self.dataset, self.column = dataset, column
        self.name = dataset.columns[column] if column is not None else name
        self.replace_values = column is not None and dataset.column_has_values(column)
        super().__init__(parent, tr("worksheet.formula.title"))

    def body(self, master):
        body = ttk.Frame(master, padding=(12, 8))
        body.pack(fill="both", expand=True)
        heading = (tr("worksheet.formula.position", letter=column_label(self.column), name=self.name)
                   if self.column is not None else self.name)
        ttk.Label(body, text=heading, style="DialogTitle.TLabel", wraplength=460).pack(anchor="w", pady=(0, 8))
        self.expression = ttk.Entry(body, width=58, exportselection=False)
        self.expression.insert(0, self.dataset.formulas.get(self.name, ""))
        self.expression.pack(fill="x")
        self.add_references(body)
        if self.replace_values:
            ttk.Label(body, text=tr("worksheet.formula.replace_warning"), wraplength=460).pack(anchor="w", pady=(6, 0))
        self.problem = ttk.Label(body, foreground="#9d283a", wraplength=460)
        self.problem.pack(anchor="w", fill="x", pady=(6, 0))
        return self.expression

    def add_references(self, parent):
        self.references = (variable_references(self.dataset), function_references())
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(10, 4))
        self.reference_group = ttk.Combobox(bar, state="readonly", width=11, values=(
            tr("worksheet.formula.columns"), tr("worksheet.formula.functions")))
        self.reference_group.current(0)
        self.reference_group.pack(side="left")
        self.reference_query = tk.StringVar(self)
        self.reference_search = ttk.Entry(bar, textvariable=self.reference_query)
        self.reference_search.pack(side="left", fill="x", expand=True, padx=6)
        self.reference_insert = ttk.Button(bar, text=tr("worksheet.formula.insert"), command=self.insert_reference)
        self.reference_insert.pack(side="right")
        self.reference_prompt = ttk.Label(parent)
        self.reference_prompt.pack(anchor="w", pady=(0, 4))
        listing = ttk.Frame(parent)
        listing.pack(fill="x")
        self.reference_results = tk.Listbox(listing, height=4, exportselection=False)
        scrollbar = ttk.Scrollbar(listing, orient="vertical", command=self.reference_results.yview)
        self.reference_results.configure(yscrollcommand=scrollbar.set)
        self.reference_results.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.reference_detail = ttk.Label(parent, wraplength=460)
        self.reference_detail.pack(anchor="w", pady=(4, 0))
        self.reference_group.bind("<<ComboboxSelected>>", self.filter_references)
        self.reference_query.trace_add("write", self.filter_references)
        self.reference_results.bind("<<ListboxSelect>>", self.show_reference)
        for widget in (self.reference_search, self.reference_results):
            widget.bind("<Return>", self.insert_reference)
        self.reference_results.bind("<Double-Button-1>", self.insert_reference)
        self.filter_references()

    def filter_references(self, *_):
        mode = self.reference_group.current()
        self.reference_prompt.configure(text=tr("worksheet.formula.search_functions" if mode
                                                else "worksheet.formula.find"))
        self.matches = matching_references(self.references[mode], self.reference_query.get(),
                                           exclude=None if mode else self.name)
        self.reference_results.delete(0, "end")
        for reference in self.matches:
            self.reference_results.insert("end", reference.label)
        if self.matches:
            self.reference_results.selection_set(0)
            self.reference_results.activate(0)
        self.show_reference()

    def show_reference(self, _event=None):
        selected = self.reference_results.curselection()
        self.reference_insert.state(["!disabled" if selected else "disabled"])
        self.reference_detail.configure(
            text=self.matches[selected[0]].detail if selected else tr("worksheet.formula.no_matches"))

    def insert_reference(self, _event=None):
        selected = self.reference_results.curselection()
        if selected:
            reference = self.matches[selected[0]]
            start = self.expression.index("insert")
            if self.expression.selection_present():
                start = self.expression.index("sel.first")
                self.expression.delete("sel.first", "sel.last")
            self.expression.insert(start, reference.text)
            length = int(self.tk.call("string", "length", reference.text))
            self.expression.icursor(start + length - int(reference.open_arguments))
            self.expression.focus_set()
        return "break"

    def buttonbox(self):
        row = ttk.Frame(self, padding=(12, 0, 12, 12))
        ttk.Button(row, text=tr("worksheet.formula.replace" if self.replace_values else "language.ok"),
                   style="Action.TButton", command=self.ok).pack(side="right", padx=(8, 0))
        ttk.Button(row, text=tr("setup.cancel"), command=self.cancel).pack(side="right")
        row.pack(fill="x")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        expression = self.expression.get().strip()
        if not expression:
            self.problem.configure(text=tr("worksheet.formula.required"))
            return False
        try:
            candidate = copy(self.dataset)
            if self.column is None:
                candidate.set_formula(self.name, expression)
            else:
                candidate.set_worksheet_formula(self.column, expression, replace_values=self.replace_values)
        except (ValueError, TypeError, OverflowError) as error:
            self.problem.configure(text=ui(translate_message(error, "worksheet.formula.error.")))
            return False
        self.result = candidate.formulas[self.name]
        return True
