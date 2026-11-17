"""Ordered selection of catalog equations for Compare models (AICc)."""
import tkinter as tk
from tkinter import ttk

from .equation_dialog import EquationDialog
from .i18n import tr
from .model_selection import CANDIDATES, MAX_MODELS, MIN_MODELS

DEFAULT_MODELS = ("Straight line", "Polynomial (order 2)")


class ModelPicker(ttk.Frame):
    """The models to compare, in the order of the selection.

    Names live in a Python list and are never read back from the Tk widget, so the literal
    catalog names reach the recipe unchanged. Adding opens the same searchable catalog as
    Nonlinear regression. The count and the order are checked by the analysis, which keeps
    the error on this field.
    """

    def __init__(self, parent, saved=None):
        super().__init__(parent)
        valid = isinstance(saved, (list, tuple)) and all(isinstance(name, str) for name in saved)
        self.items = list(saved) if valid and saved else list(DEFAULT_MODELS)
        self.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(self, selectmode="browse", exportselection=False, height=8)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        buttons = ttk.Frame(self)
        buttons.grid(row=0, column=1, sticky="n", padx=(6, 0))
        self.add_button = ttk.Button(buttons, text=tr("aicc.add"), width=9, command=self.add)
        self.remove_button = ttk.Button(buttons, text=tr("aicc.remove"), width=9, command=self.remove)
        self.up_button = ttk.Button(buttons, text=tr("aicc.up"), width=9, command=lambda: self.move(-1))
        self.down_button = ttk.Button(buttons, text=tr("aicc.down"), width=9, command=lambda: self.move(1))
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button):
            button.pack(pady=(0, 4))
        self.count = ttk.Label(self, foreground="#486075", wraplength=330, justify="left")
        self.count.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.note = ttk.Label(self, text=tr("aicc.note"), wraplength=330, justify="left", foreground="#486075")
        self.note.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.refresh()

    def refresh(self, selected=None):
        self.listbox.delete(0, "end")
        for name in self.items:
            self.listbox.insert("end", name)
        if selected is not None and 0 <= selected < len(self.items):
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
        self.count.configure(text=tr("aicc.count", count=len(self.items), minimum=MIN_MODELS, maximum=MAX_MODELS))

    def add(self):
        current = self.items[self.listbox.curselection()[0]] if self.listbox.curselection() else ""
        dialog = EquationDialog(self.winfo_toplevel(), CANDIDATES, current)
        self.winfo_toplevel().grab_set()
        if dialog.result is not None:
            self.add_model(dialog.result)

    def add_model(self, name):
        self.items.append(name)
        self.refresh(len(self.items) - 1)

    def remove(self):
        selection = self.listbox.curselection()
        if selection:
            del self.items[selection[0]]
            self.refresh(min(selection[0], len(self.items) - 1))

    def move(self, step):
        selection = self.listbox.curselection()
        if not selection:
            return
        i, j = selection[0], selection[0] + step
        if 0 <= j < len(self.items):
            self.items[i], self.items[j] = self.items[j], self.items[i]
            self.refresh(j)

    def values(self):
        return list(self.items)
