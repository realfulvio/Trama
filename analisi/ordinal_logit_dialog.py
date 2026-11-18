"""Dialog parts of Ordinal logistic regression: the Category order editor and the text of the field errors.

The order is a list of the labels the categories print with, from the lowest to the highest. It follows the worksheet
while it is in step with it: choosing another response starts from that column's own order, and a predictor that adds
or drops a category keeps the arrangement of the others. A recipe whose categories no longer match the worksheet is
never repaired silently: the list stays as it was saved, a note names the new and the vanished categories, and
Run Analysis stops on this field until the order is checked.
"""
import tkinter as tk
from tkinter import ttk

from .competing_risks_dialog import number
from .i18n import tr, translate_message, ui
from .ordinal_logit import proposed_order

HINT, CHANGED = "#486075", "#8a4b08"
ERROR_PREFIX = "ord.error."
LIST_HEIGHT = 5


def caption(field):
    return ui(field)


def translate_error(error):
    """An engine message in the active language; worksheet names inside it are copied literally."""
    text = str(error)
    shown = translate_message(text, ERROR_PREFIX, {"limit": number, "count": number, "parameters": number,
                                                   "minimum": number})
    return ui(shown) if shown == text else shown


def describe_error(error, field=None):
    """The dialog banner for an error: translated, and naming the field it belongs to."""
    field = getattr(error, "field", field)
    message = translate_error(error)
    label = caption(field) if field else ""
    named = message.lower()
    if field and field.lower() not in named and label.lower() not in named:
        message = f"{label}: {message}"
    return message


def read_observed(data, response, predictors):
    """The categories of the response in the rows where the response and every predictor are filled."""
    if not response:
        return []
    return proposed_order(data, response, predictors)


def merged(order, observed):
    """The current arrangement restricted to the observed categories, each new one placed after its predecessor."""
    kept = [label for label in order if label in observed]
    for position, label in enumerate(observed):
        if label in kept:
            continue
        before = next((previous for previous in reversed(observed[:position]) if previous in kept), None)
        kept.insert(0 if before is None else kept.index(before) + 1, label)
    return kept


def shown(labels, limit=4):
    text = ", ".join(f'"{label}"' for label in labels[:limit])
    return text + (", …" if len(labels) > limit else "")


class OrderEditor(ttk.Frame):
    """Category order: a list moved with Up and Down, and Reset to read the categories again from the worksheet."""

    def __init__(self, parent, saved=(), on_change=None):
        super().__init__(parent)
        self.order = [str(label) for label in saved] if isinstance(saved, (list, tuple)) else []
        self.observed = None      # categories of the worksheet at the last refresh; None until the first one
        self.response = None
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
        return list(self.order)

    def sync(self, observed, response):
        """Follow a change of the response or the predictors: see the module text for what is kept."""
        observed = list(observed)
        if self.observed is None:
            if not self.order:
                self.order = list(observed)
        elif response != self.response:
            self.order = list(observed)
        elif observed and set(self.order) == set(self.observed) and set(observed) != set(self.order):
            self.order = merged(self.order, observed)
        self.observed, self.response = observed, response
        self.refresh()

    def reset(self):
        self.order = list(self.observed or [])
        self.refresh()
        self._changed()

    def move(self, step):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        target = index + step
        if not 0 <= target < len(self.order):
            return
        self.order[index], self.order[target] = self.order[target], self.order[index]
        self.refresh(target)
        self._changed()

    def _changed(self):
        if self.on_change is not None:
            self.on_change()

    def difference(self):
        """The categories new in the worksheet and those the saved order lists but the worksheet no longer has."""
        if not self.observed:
            return [], []
        return ([label for label in self.observed if label not in self.order],
                [label for label in self.order if label not in self.observed])

    def refresh(self, selected=None):
        self.listbox.delete(0, "end")
        for position, label in enumerate(self.order, 1):
            self.listbox.insert("end", f"{position}. {label}")
        if selected is not None and self.order:
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
        added, removed = self.difference()
        if not self.observed and not self.order:
            self.note.configure(text=tr("ord.hint.order_empty"), foreground=HINT)
        elif added and removed:
            self.note.configure(text=tr("ord.hint.order_changed", added=shown(added), removed=shown(removed)),
                                foreground=CHANGED)
        elif removed:
            self.note.configure(text=tr("ord.hint.order_removed", removed=shown(removed)), foreground=CHANGED)
        elif added:
            self.note.configure(text=tr("ord.hint.order_added", added=shown(added)), foreground=CHANGED)
        else:
            self.note.configure(text=tr("ord.hint.order"), foreground=HINT)
        for key in ("up", "down"):
            self.buttons[key].state(["!disabled"] if len(self.order) > 1 else ["disabled"])

