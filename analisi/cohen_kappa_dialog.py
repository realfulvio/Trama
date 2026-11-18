"""Dialog parts of Cohen's kappa: the category order editor, the typed bootstrap fields and the error messages.

The editor keeps the order the user saved or arranged: it shows the categories found in the complete pairs next to
it (the ones missing from the order and the ones no longer in the pairs) but never rewrites the order by itself.
Up and Down (also Alt+Up and Alt+Down on the list) move the selected category; Propose keeps the current order,
drops what is not in the pairs and appends the new categories; Restore brings back the saved order; Clear empties
it, which means the automatic order (Unweighted only). Labels live in a Python list, never read back from Tk.
"""
import tkinter as tk
from tkinter import ttk

from .cohen_kappa import FIRST, SECOND, UNWEIGHTED, observed_categories
from .cohen_kappa_workbench import CHOICE_KEYS, ERROR_PREFIX, LABEL_KEYS, PREFIX
from .competing_risks_dialog import number
from .data import decimal_comma
from .field_error import FieldError
from .i18n import tr, translate_message, ui

HINT = "#486075"
WARNING = "#9a3412"
STALE = "#9a3412"


def caption(field):
    """The dialog caption of a canonical field name (the name itself for an unknown field)."""
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else field


def choice(value):
    return tr(CHOICE_KEYS[value]) if value in CHOICE_KEYS else value


def translate_error(error):
    """An engine message in the active language; field names and choices inside it become the dialog captions.

    Worksheet values (column names, categories, cell values) are copied literally. A message that is not one of
    the catalog entries (a shared helper's) goes through the common interface catalog.
    """
    text = str(error)
    converters = {"field": caption, "first": caption, "weighting": choice, "limit": number, "count": number,
                  "high": number}
    shown = translate_message(text, ERROR_PREFIX, converters)
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


def read_typed(text):
    """A bootstrap field as typed: an integer, else a number (decimal comma accepted), else the text itself.

    The analysis reads these fields only with the bootstrap on, so a value that does not parse is kept in the
    recipe as written and reported on its own field when it is used.
    """
    raw = str(text).strip()
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(decimal_comma(raw))
    except ValueError:
        return raw


def defaults(frame):
    """First and second rating of a new analysis: the first two columns of the worksheet."""
    columns = [str(name) for name in frame.columns]
    return {FIRST: columns[0], SECOND: columns[1]} if len(columns) >= 2 else {}


def _listed(labels, limit=6):
    shown = ", ".join(labels[:limit])
    return shown + (" …" if len(labels) > limit else "")


class CategoryOrderEditor(ttk.Frame):
    """Ordered list of category labels with Up, Down, Propose, Restore and Clear."""

    def __init__(self, parent, saved=()):
        super().__init__(parent)
        self.saved = [str(item) for item in saved] if isinstance(saved, (list, tuple)) else []
        self.items = list(self.saved)
        self.observed = None
        self.problem = ""
        self.weighting = UNWEIGHTED
        self.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(self, selectmode="browse", exportselection=False, height=5, width=22,
                                  activestyle="dotbox")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        buttons = ttk.Frame(self)
        buttons.grid(row=0, column=2, sticky="n", padx=(6, 0))
        self.buttons = {}
        for key, command in (("up", lambda: self.move(-1)), ("down", lambda: self.move(1)),
                             ("propose", self.propose), ("restore", self.restore), ("clear", self.clear)):
            button = ttk.Button(buttons, text=tr(PREFIX + "order." + key), width=10, command=command)
            button.pack(fill="x", pady=(0, 3))
            self.buttons[key] = button
        for sequence, step in (("<Alt-Up>", -1), ("<Alt-Down>", 1), ("<Control-Up>", -1), ("<Control-Down>", 1)):
            self.listbox.bind(sequence, lambda _event, step=step: self.move(step) or "break")
        self.note = ttk.Label(self, foreground=WARNING, wraplength=290, justify="left")
        self.note.grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))
        self.hint = ttk.Label(self, foreground=HINT, wraplength=290, justify="left",
                              text=tr(PREFIX + "order.keys"))
        self.hint.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 0))
        # The notes wrap to the room the field really has: a longer caption (Italian) narrows this column.
        self.bind("<Configure>", self._wrap_notes)
        self.refresh()

    def focus_target(self):
        return self.listbox

    def _wrap_notes(self, event):
        width = max(160, event.width - 6)
        for label in (self.note, self.hint):
            if int(label.cget("wraplength")) != width:
                label.configure(wraplength=width)

    # -- the categories of the data and the weighting -------------------------------------------------------------

    def set_observed(self, observed, problem=""):
        """The categories of the complete pairs in automatic order, or None with the reason they are unknown."""
        self.observed = None if observed is None else list(observed)
        self.problem = problem
        self.refresh(self.selected())

    def set_weighting(self, weighting):
        self.weighting = weighting
        self.refresh(self.selected())

    # -- editing --------------------------------------------------------------------------------------------------

    def selected(self):
        selection = self.listbox.curselection()
        return selection[0] if selection else None

    def move(self, step):
        index = self.selected()
        if index is None:
            return
        target = index + step
        if 0 <= target < len(self.items):
            self.items[index], self.items[target] = self.items[target], self.items[index]
            self.refresh(target)

    def propose(self):
        if self.observed is None:
            return
        kept = [name for name in self.items if name in self.observed]
        self.items = kept + [name for name in self.observed if name not in kept]
        self.refresh(0 if self.items else None)

    def restore(self):
        self.items = list(self.saved)
        self.refresh(0 if self.items else None)

    def clear(self):
        self.items = []
        self.refresh()

    def values(self):
        return list(self.items)

    # -- display --------------------------------------------------------------------------------------------------

    def notes(self):
        """The orange note: what the data and the order disagree on, or why the order is needed."""
        lines = []
        if self.problem:
            lines.append(self.problem)
        if self.observed is not None and self.items:
            fresh = [name for name in self.observed if name not in self.items]
            stale = [name for name in self.items if name not in self.observed]
            if fresh:
                lines.append(tr(PREFIX + "order.new", levels=_listed(fresh)))
            if stale:
                lines.append(tr(PREFIX + "order.stale", levels=_listed(stale)))
        if not self.items and self.weighting != UNWEIGHTED:
            lines.append(tr(PREFIX + "order.needed"))
        return lines

    def refresh(self, selected=None):
        self.listbox.delete(0, "end")
        observed = set(self.observed or ())
        for position, name in enumerate(self.items):
            self.listbox.insert("end", name)
            if self.observed is not None and name not in observed:
                self.listbox.itemconfigure(position, foreground=STALE)
        if selected is not None and self.items:
            selected = min(selected, len(self.items) - 1)
            self.listbox.selection_set(selected)
            self.listbox.activate(selected)
            self.listbox.see(selected)
        notes = self.notes()
        self.note.configure(text="\n".join(notes))
        self.note.grid() if notes else self.note.grid_remove()
        automatic = [tr(PREFIX + "order.automatic")] if not self.items and self.weighting == UNWEIGHTED else []
        self.hint.configure(text="\n".join([*automatic, tr(PREFIX + "order.keys")]))
        self.buttons["propose"].configure(state="normal" if self.observed is not None else "disabled")


def preview(frame, first, second):
    """Categories of the complete pairs for the editor: (labels, "") or (None, the translated reason)."""
    try:
        return observed_categories(frame, first, second), ""
    except (FieldError, ValueError, KeyError, TypeError) as error:
        return None, describe_error(error)
