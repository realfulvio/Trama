"""The Model terms field of the Multifactor ANOVA dialog (0.83).

Three groups of checkboxes (main effects, two-way and three-way interactions) built from the
Factors chosen on the Variables tab, and a readable summary of the model. The terms live in a Python
set of factor-name sets, never in the Tk widgets, so the literal names reach the recipe unchanged and
a term survives while its factor is deselected for a moment. ``values()`` returns the ticked terms
that use only the current Factors, in model order: orders 1 to 3, factors in the order of Factors.

A picker that has never been edited, and was not given a saved list, follows the Full hierarchy of the
chosen Factors and Interaction order. The first edit freezes it, so switching to Selected terms starts
from the model that Full hierarchy would fit and the user prunes from there. Nothing is added silently
afterwards: ``Add required terms`` is an explicit button, and a term that lacks a prerequisite is named
in the summary and refused when the analysis is requested.
"""
from itertools import combinations
import tkinter as tk
from tkinter import ttk

from .anova_terms import MAX_ORDER, full_terms, label, prerequisites
from .i18n import tr

ANOVA_MODEL_TAB = "Model"
GROUP_KEYS = {1: "anova.terms.group.main", 2: "anova.terms.group.two", 3: "anova.terms.group.three"}
_MUTED, _WARNING = "#486075", "#a63a2b"


def _clean(saved):
    """A saved ``Model terms`` list as a set of frozensets of names; anything malformed is ignored."""
    if not isinstance(saved, (list, tuple)):
        return set()
    terms = set()
    for term in saved:
        if isinstance(term, (list, tuple)) and term and all(isinstance(name, str) for name in term):
            terms.add(frozenset(term))
    return terms


class TermPicker(ttk.Frame):
    """Checkboxes for the terms of the model, a summary, and the notes of the chosen term selection.

    ``factors``, ``response``, ``selected`` and ``order`` are callables read at every refresh: the
    names chosen in Factors, the response caption, whether Selected terms is on, and the text of
    Interaction order. ``on_build`` receives the widgets created by a refresh (the dialog binds the
    mouse wheel and the scroll-into-view of its page to them).
    """

    def __init__(self, parent, saved=None, *, factors, response, selected, order, on_build=None):
        super().__init__(parent)
        self.factors, self.response, self.selected, self.order = factors, response, selected, order
        self.on_build = on_build
        self.chosen = _clean(saved)
        self.touched = bool(self.chosen)
        self.vars, self.boxes, self.groups = {}, {}, {}
        self._building = False
        self.columnconfigure(0, weight=1)
        tools = ttk.Frame(self)
        tools.grid(row=0, column=0, sticky="w")
        self.all_button = ttk.Button(tools, text=tr("anova.terms.select_all"), command=self.select_all)
        self.clear_button = ttk.Button(tools, text=tr("anova.terms.clear"), command=self.clear)
        self.add_button = ttk.Button(tools, text=tr("anova.terms.add_required"), command=self.add_required)
        for button in (self.all_button, self.clear_button, self.add_button):
            button.pack(side="left", padx=(0, 4))
        self.tools = tools
        for position, key in GROUP_KEYS.items():
            frame = ttk.LabelFrame(self, text=tr(key), padding=(8, 4))
            frame.columnconfigure(0, weight=1)
            self.groups[position] = frame
            frame.grid(row=position, column=0, sticky="ew", pady=(6, 0))
        self.summary = ttk.Label(self, wraplength=410, justify="left")
        self.summary.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.outside = ttk.Label(self, wraplength=410, justify="left", foreground=_MUTED)
        self.outside.grid(row=5, column=0, sticky="w", pady=(2, 0))
        self.problem = ttk.Label(self, wraplength=410, justify="left", foreground=_WARNING)
        self.problem.grid(row=6, column=0, sticky="w", pady=(2, 0))
        self.note = ttk.Label(self, wraplength=410, justify="left", foreground=_MUTED)
        self.note.grid(row=7, column=0, sticky="w", pady=(6, 0))
        self.refresh()

    # -- state -----------------------------------------------------------------------------
    def static_widgets(self):
        """The widgets inside the picker that are never rebuilt."""
        return [self.tools, self.all_button, self.clear_button, self.add_button, *self.groups.values(),
                self.summary, self.outside, self.problem, self.note]

    def names(self):
        return [name for name in self.factors() if isinstance(name, str)]

    def available(self):
        """Every term the current Factors allow, in model order."""
        return list(full_terms(self.names(), min(MAX_ORDER, len(self.names()))))

    def _order_value(self):
        try:
            value = int(str(self.order()).strip())
        except (TypeError, ValueError):
            return 1
        return max(1, min(MAX_ORDER, value))

    def _follow_full(self):
        """An untouched picker holds the Full hierarchy of the current Factors and Interaction order."""
        if not self.touched:
            names = self.names()
            self.chosen = {frozenset(term) for term in full_terms(names, min(self._order_value(), len(names)))}

    def terms(self):
        """The ticked terms that use only the current Factors, in model order (tuples of names)."""
        self._follow_full()
        return [term for term in self.available() if frozenset(term) in self.chosen]

    def values(self):
        return [list(term) for term in self.terms()]

    def set_values(self, saved):
        self.chosen = _clean(saved)
        self.touched = True
        self.refresh()

    # -- editing ---------------------------------------------------------------------------
    def _toggle(self, term):
        if self._building:
            return
        self._follow_full()
        key = frozenset(term)
        if self.vars[term].get():
            self.chosen.add(key)
        else:
            self.chosen.discard(key)
        self.touched = True
        self._describe()

    def select_all(self):
        self._follow_full()
        self.chosen |= {frozenset(term) for term in self.available()}
        self.touched = True
        self.refresh()

    def clear(self):
        self._follow_full()
        self.chosen -= {frozenset(term) for term in self.available()}
        self.touched = True
        self.refresh()

    def add_required(self):
        names = self.names()
        self.chosen |= {frozenset(term) for term in prerequisites(self.terms(), names)}
        self.touched = True
        self.refresh()

    # -- display ---------------------------------------------------------------------------
    def refresh(self):
        """Rebuild the checkboxes for the current Factors and show the summary of the current model."""
        self._follow_full()
        self._building = True
        try:
            for box in self.boxes.values():
                box.destroy()
            self.boxes, self.vars = {}, {}
            for position, frame in self.groups.items():
                members = [term for term in self.available() if len(term) == position]
                for row, term in enumerate(members):
                    variable = tk.BooleanVar(self, value=frozenset(term) in self.chosen)
                    box = ttk.Checkbutton(frame, text=label(term), variable=variable,
                                          command=lambda term=term: self._toggle(term))
                    box.grid(row=row, column=0, sticky="w")
                    self.vars[term], self.boxes[term] = variable, box
        finally:
            self._building = False
        if self.on_build is not None:
            self.on_build(list(self.boxes.values()))
        self.sync()

    def sync(self):
        """Show what the current mode needs: the checkboxes only for Selected terms, the notes for both."""
        selected = bool(self.selected())
        if selected:
            self.tools.grid()
            for position, frame in self.groups.items():
                if any(len(term) == position for term in self.boxes):
                    frame.grid()
        else:
            self.tools.grid_remove()
            for frame in self.groups.values():
                frame.grid_remove()
        self._describe()

    @staticmethod
    def _say(label, text):
        """Set the text of a note and keep an empty note out of the layout."""
        label.configure(text=text)
        if text:
            label.grid()
        else:
            label.grid_remove()

    def _describe(self):
        names, selected = self.names(), bool(self.selected())
        terms = (self.terms() if selected
                 else list(full_terms(names, min(self._order_value(), len(names)))) if names else [])
        if not names:
            self._say(self.summary, tr("anova.terms.no_factors"))
            self._say(self.outside, "")
            self._say(self.problem, "")
        else:
            text = " + ".join(label(term) for term in terms)
            self._say(self.summary, tr("anova.terms.summary", model=f"{self.response() or 'Y'} = {text}")
                      if terms else tr("anova.terms.summary_none"))
            used = {name for term in terms for name in term}
            idle = [name for name in names if name not in used]
            self._say(self.outside, tr("anova.terms.outside", factors=", ".join(idle)) if selected and idle else "")
            self._say(self.problem, self._problems(terms) if selected else "")
        self.note.configure(text=tr("anova.terms.selected_note" if selected else "anova.terms.full_note"))
        self.all_button.state(["!disabled" if names else "disabled"])
        self.clear_button.state(["!disabled" if self.chosen else "disabled"])
        self.add_button.state(["!disabled" if prerequisites(terms, names) else "disabled"])

    @staticmethod
    def _problems(terms):
        have = {frozenset(term) for term in terms}
        lines = []
        for term in terms:
            if len(term) < 2:
                continue
            missing = [label(part) for size in range(1, len(term)) for part in combinations(term, size)
                       if frozenset(part) not in have]
            if missing:
                lines.append(tr("anova.terms.needs", term=label(term), missing=", ".join(missing)))
        return "\n".join(lines)

    def focus_target(self):
        for term in self.available():
            if term in self.boxes and self.boxes[term].winfo_viewable():
                return self.boxes[term]
        return self.all_button if self.all_button.winfo_viewable() else self
