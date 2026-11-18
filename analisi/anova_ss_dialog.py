"""Notes and factor order under the Sums of squares selector of the Multifactor ANOVA dialog.

Type I adds the terms in model order, so the order of ``Factors`` matters. The Factors list of the
Variables page keeps only the order of the worksheet, so this panel holds the order of the chosen
factors in a Python list of names, never in a Tk widget, and the dialog writes that order into the
``Factors`` of the recipe. The panel starts from the order of the recipe being edited, keeps the
position of a factor that is unticked for a moment, and appends a newly ticked factor at the end.

Under the selector it shows one short note for the type chosen: the role of the order for Type I, and
the marginality of Type II when the model has an interaction. For Type I it also shows the factors
with Up and Down and the effective order of the terms, which follows the Interaction order, or the
terms ticked under Selected terms, in the order of the factors shown here.
"""
import tkinter as tk
from tkinter import ttk

from .anova_ss import TYPE_I, TYPE_II
from .anova_terms import label
from .i18n import tr, ui

_MUTED = "#486075"


class SumsOfSquaresPanel(ttk.Frame):
    """The notes, the factor order and the preview of the order of the terms.

    ``kind``, ``factors`` and ``terms`` are callables read at every refresh: the type chosen, the names
    ticked in Factors (worksheet order), and the model terms (tuples of names) in model order, for the
    order shown here. ``on_order`` runs after the user moves a factor.
    """

    def __init__(self, parent, saved=None, *, kind, factors, terms, on_order=None):
        super().__init__(parent)
        self.kind, self.factors, self.terms, self.on_order = kind, factors, terms, on_order
        self.rank = [name for name in dict.fromkeys(saved or ()) if isinstance(name, str)]
        self.columnconfigure(0, weight=1)
        self.note = ttk.Label(self, wraplength=410, justify="left", foreground=_MUTED)
        self.note.grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.order = ttk.Frame(self)
        self.order.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.order.columnconfigure(0, weight=1)
        self.caption = ttk.Label(self.order, text=tr("anova.ss.order"), wraplength=410, justify="left")
        self.caption.grid(row=0, column=0, columnspan=2, sticky="w")
        self.listbox = tk.Listbox(self.order, selectmode="browse", exportselection=False, height=4)
        self.listbox.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        buttons = ttk.Frame(self.order)
        buttons.grid(row=1, column=1, sticky="n", padx=(6, 0), pady=(2, 0))
        self.up = ttk.Button(buttons, text=ui("Up"), width=6, command=lambda: self.move(-1))
        self.down = ttk.Button(buttons, text=ui("Down"), width=6, command=lambda: self.move(1))
        self.up.pack()
        self.down.pack(pady=(4, 0))
        self.buttons = buttons
        self.help = ttk.Label(self.order, text=tr("anova.ss.order.help"), wraplength=410, justify="left",
                              foreground=_MUTED)
        self.help.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.preview = ttk.Label(self, wraplength=410, justify="left")
        self.preview.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.refresh()

    def static_widgets(self):
        """The widgets that are never rebuilt (for the wheel and focus bindings of the scrollable page)."""
        return [self.note, self.order, self.caption, self.listbox, self.buttons, self.up, self.down, self.help,
                self.preview]

    def names(self):
        return [name for name in self.factors() if isinstance(name, str)]

    def arrange(self, names):
        """``names`` (worksheet order) in the order chosen here. A name not seen before goes last."""
        for name in names:
            if name not in self.rank:
                self.rank.append(name)
        return [name for name in self.rank if name in names]

    def ordered(self):
        return self.arrange(self.names())

    def move(self, step):
        selection = self.listbox.curselection()
        names = self.ordered()
        if not selection or not names:
            return
        i, j = selection[0], selection[0] + step
        if not 0 <= j < len(names):
            return
        a, b = self.rank.index(names[i]), self.rank.index(names[j])
        self.rank[a], self.rank[b] = self.rank[b], self.rank[a]
        self.refresh(selected=j)
        if self.on_order is not None:
            # The checkboxes of the term picker follow the new order, then so does the preview.
            self.on_order()
            self.describe()

    def refresh(self, selected=None):
        """Show the factors in the order chosen, the note of the type, and the order of the terms."""
        names = self.ordered()
        if selected is None:
            current = self.listbox.curselection()
            picked = self.listbox.get(current[0]) if current else None
            selected = names.index(picked) if picked in names else None
        self.listbox.delete(0, "end")
        for name in names:
            self.listbox.insert("end", name)
        if selected is not None and names:
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
        self.sync()

    @staticmethod
    def _say(widget, text):
        widget.configure(text=text)
        if text:
            widget.grid()
        else:
            widget.grid_remove()

    def sync(self):
        """Show what the chosen type needs: the order of Type I, the notes of Type I and of Type II."""
        kind = self.kind()
        if kind == TYPE_I and self.names():
            self.order.grid()
            self.up.state(["!disabled" if len(self.names()) > 1 else "disabled"])
            self.down.state(["!disabled" if len(self.names()) > 1 else "disabled"])
        else:
            self.order.grid_remove()
        self.describe()

    def describe(self):
        kind = self.kind()
        terms = list(self.terms()) if self.names() else []
        if kind == TYPE_I:
            self._say(self.note, tr("anova.ss.note.1"))
            self._say(self.preview, tr("anova.ss.preview", terms=" → ".join(label(term) for term in terms))
                      if terms else "")
        elif kind == TYPE_II and any(len(term) > 1 for term in terms):
            self._say(self.note, tr("anova.ss.note.2"))
            self._say(self.preview, "")
        else:
            self._say(self.note, "")
            self._say(self.preview, "")
