"""Dialog parts of Ordinal logistic regression: the Category order editor and the text of the field errors.

The order is a list of the labels the categories print with, from the lowest to the highest. It follows the worksheet
while it is in step with it: choosing another response starts from that column's own order, and a predictor that adds
or drops a category keeps the arrangement of the others. A recipe whose categories no longer match the worksheet is
never repaired silently: the list stays as it was saved, a note names the new and the vanished categories, and
Run Analysis stops on this field until the order is checked.
"""
import tkinter as tk
from tkinter import ttk

from .i18n import ui
from .ordinal_logit_options import OrderState, caption, describe_error, merged, number, read_observed, translate_error

HINT, CHANGED = "#486075", "#8a4b08"
LIST_HEIGHT = 5


class OrderEditor(ttk.Frame):
    """Category order: a list moved with Up and Down, and Reset to read the categories again from the worksheet."""

    def __init__(self, parent, saved=(), on_change=None):
        super().__init__(parent)
        self.state = OrderState(saved)
        self.on_change = on_change
        self.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(self, height=LIST_HEIGHT, exportselection=False, selectmode="browse", activestyle="none")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.grid(row=0, column=0, sticky="ew")
        scroll.grid(row=0, column=1, sticky="ns")
        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.buttons = {}
        for key, text, command in (("up", "Up", lambda: self.move(-1)), ("down", "Down", lambda: self.move(1)),
                                   ("reset", "Reset", self.reset)):
            button = ttk.Button(buttons, text=ui(text), width=8, command=command)
            button.pack(side="left", padx=(0, 4))
            self.buttons[key] = button
        self.note = ttk.Label(self, foreground=HINT, wraplength=250, justify="left")
        self.note.grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.bind("<Configure>", self._wrap_note)
        self.listbox.bind("<Alt-Up>", lambda _: self.move(-1) or "break")
        self.listbox.bind("<Alt-Down>", lambda _: self.move(1) or "break")
        self.refresh()

    def _wrap_note(self, event):
        width = max(160, event.width - 6)
        if int(self.note.cget("wraplength")) != width:
            self.note.configure(wraplength=width)

    def focus_target(self):
        return self.listbox

    def values(self):
        return list(self.state.order)

    def sync(self, observed, response):
        """Follow a change of the response or the predictors: see the module text for what is kept."""
        self.state.sync(observed, response)
        self.refresh()

    def reset(self):
        self.state.reset()
        self.refresh()
        self._changed()

    def move(self, step):
        selection = self.listbox.curselection()
        if not selection:
            return
        target = self.state.move(selection[0], step)
        if target is None:
            return
        self.refresh(target)
        self._changed()

    def _changed(self):
        if self.on_change is not None:
            self.on_change()

    def refresh(self, selected=None):
        self.listbox.delete(0, "end")
        for position, label in enumerate(self.state.order, 1):
            self.listbox.insert("end", f"{position}. {label}")
        if selected is not None and self.state.order:
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
        hint, changed = self.state.hint()
        self.note.configure(text=hint, foreground=CHANGED if changed else HINT)
        for key in ("up", "down"):
            self.buttons[key].state(["!disabled"] if len(self.state.order) > 1 else ["disabled"])
