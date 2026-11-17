"""Editors for Fit custom equation: the formula box and the coefficient table.

Both are plain Tk widgets bound to the candidate recipe of the Analyze dialog. Nothing here fits or
evaluates while the user types; Check equation asks the engine for its pre-calculation checks only.
"""
import re
import tkinter as tk
from tkinter import ttk

from .custom_equations import FUNCTIONS, MAX_PARAMETERS, RESERVED
from .custom_fit import EXAMPLE_PARAMETERS
from .data import decimal_comma
from .i18n import tr, translate_message

_GROUP_PREFIX = re.compile(r"Group (?P<group>.+?): (?P<rest>.*)\Z", re.DOTALL)
OK, ERROR = "#1a6b3c", "#b42318"


def translate_error(message):
    """Show an engine message in the active language; a leading "Group name: " is kept and translated."""
    message = str(message)
    match = _GROUP_PREFIX.match(message)
    if match and not message.startswith("Group must"):
        return tr("custom.group_prefix", group=match["group"]) + " " + translate_error(match["rest"])
    translated = translate_message(message, "custom.error.")
    if translated == message:
        translated = translate_message(message, "parameter_ci.error.")
    return translated


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float):
        text = repr(value)
        return text[:-2] if text.endswith(".0") else text
    return str(value)


def _parse(text):
    """A number when the text reads as one; otherwise the text itself so the engine names the problem."""
    text = text.strip()
    try:
        return float(decimal_comma(text))
    except ValueError:
        return text


class EquationEditor(ttk.Frame):
    """Multi-line formula with a literal preview and a Check equation button."""

    def __init__(self, parent, equation, *, on_check):
        super().__init__(parent)
        self.on_check = on_check
        self.columnconfigure(0, weight=1)
        frame = ttk.Frame(self)
        frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        self.box = tk.Text(frame, height=5, width=44, wrap="none", undo=True, font=("Consolas", 11))
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.box.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.box.xview)
        self.box.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.box.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.box.insert("1.0", equation or "")
        self.box.edit_reset()
        self.checked = None
        # <<Modified>> also reports programmatic changes, so the preview never shows a stale formula.
        self.box.bind("<<Modified>>", self.modified)
        self.box.bind("<Tab>", lambda event: (event.widget.tk_focusNext().focus_set(), "break")[1])
        ttk.Label(self, text=tr("custom.preview")).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.preview = ttk.Label(self, wraplength=420, justify="left", font=("Consolas", 10))
        self.preview.grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Button(self, text=tr("custom.check"), command=self.check).grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.message = ttk.Label(self, wraplength=430, justify="left")
        self.message.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(self, wraplength=430, justify="left", foreground="#486075",
                  text=tr("custom.grammar", functions=", ".join(FUNCTIONS))).grid(
                      row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.refresh()

    def values(self):
        return self.box.get("1.0", "end").strip()

    def focus_target(self):
        return self.box

    def modified(self, _event=None):
        if self.box.edit_modified():
            self.box.edit_modified(False)
            self.refresh()

    def refresh(self):
        text = " ".join(self.values().split())
        self.preview.configure(text=("Y = " + text) if text else "")
        if text != self.checked:
            self.message.configure(text="")

    def show(self, message, ok):
        self.checked = " ".join(self.values().split())
        self.message.configure(text=message, foreground=OK if ok else ERROR)

    def check(self):
        self.on_check(self)


class ParameterTable(ttk.Frame):
    """Coefficients with starting value, Fixed, and lower and upper limits; edited live from a small form."""

    COLUMNS = (("name", 90), ("start", 90), ("fixed", 52), ("lower", 80), ("upper", 80))

    def __init__(self, parent, records, *, equation):
        super().__init__(parent)
        self.equation = equation
        self.rows = []
        for record in records if isinstance(records, (list, tuple)) else ():
            if isinstance(record, dict):
                self.rows.append({"name": _text(record.get("name")), "start": _text(record.get("start")),
                                  "lower": _text(record.get("lower")), "upper": _text(record.get("upper")),
                                  "fixed": bool(record.get("fixed", False))})
        self.loading = False
        self.columnconfigure(0, weight=1)
        table = ttk.Frame(self)
        table.grid(row=0, column=0, columnspan=4, sticky="nsew")
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=[name for name, _ in self.COLUMNS], show="headings",
                                 selectmode="browse", height=5)
        for name, width in self.COLUMNS:
            self.tree.heading(name, text=tr(f"custom.column.{name}"))
            self.tree.column(name, width=width, anchor="w" if name == "name" else "center", stretch=True)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.load_selection())
        self.tree.bind("<Delete>", lambda _: self.remove())
        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=0, columnspan=4, sticky="w", pady=(5, 0))
        for text, command in ((tr("custom.add"), self.add), (tr("custom.remove"), self.remove),
                              (tr("custom.from_equation"), self.from_equation)):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 5))
        form = ttk.Frame(self)
        form.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        self.variables = {key: tk.StringVar() for key in ("name", "start", "lower", "upper")}
        self.fixed = tk.BooleanVar()
        self.start_label = ttk.Label(form, text=tr("custom.start"))
        self.entries = {}
        for position, (key, label) in enumerate((("name", None), ("start", self.start_label),
                                                 ("lower", None), ("upper", None))):
            row, column = divmod(position, 2)
            caption = label or ttk.Label(form, text=tr(f"custom.column.{key}"))
            caption.grid(row=row, column=2 * column, sticky="w", padx=(10 if column else 0, 4), pady=2)
            entry = ttk.Entry(form, textvariable=self.variables[key], width=14)
            entry.grid(row=row, column=2 * column + 1, sticky="ew", pady=2)
            self.entries[key] = entry
            self.variables[key].trace_add("write", lambda *_: self.store())
        self.fixed_check = ttk.Checkbutton(form, text=tr("custom.fixed_hint"), variable=self.fixed,
                                           command=self.store)
        self.fixed_check.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(self, wraplength=420, justify="left", foreground="#486075", text=tr("custom.parameters_note")).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.refresh()
        if self.rows:
            self.tree.selection_set("0")
        self.load_selection()

    def focus_target(self):
        return self.tree

    def selected(self):
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def refresh(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(index), values=(
                row["name"], row["start"], "✓" if row["fixed"] else "", row["lower"], row["upper"]))
        if select is not None and 0 <= select < len(self.rows):
            self.tree.selection_set(str(select))
        # The form follows the selection at once, not when the virtual event is dispatched.
        self.load_selection()

    def set_form_state(self):
        state = "normal" if self.selected() is not None else "disabled"
        for entry in self.entries.values():
            entry.configure(state=state)
        self.fixed_check.configure(state=state)
        self.start_label.configure(text=tr("custom.value") if self.fixed.get() else tr("custom.start"))

    def load_selection(self):
        index = self.selected()
        self.loading = True
        try:
            row = self.rows[index] if index is not None else {"name": "", "start": "", "lower": "", "upper": "",
                                                              "fixed": False}
            for key, variable in self.variables.items():
                variable.set(row[key])
            self.fixed.set(row["fixed"])
        finally:
            self.loading = False
        self.set_form_state()

    def store(self):
        index = self.selected()
        if self.loading or index is None:
            return
        row = self.rows[index]
        for key, variable in self.variables.items():
            row[key] = variable.get()
        row["fixed"] = bool(self.fixed.get())
        self.tree.item(str(index), values=(row["name"], row["start"], "✓" if row["fixed"] else "",
                                           row["lower"], row["upper"]))
        self.set_form_state()

    def free_name(self):
        used = {row["name"] for row in self.rows}
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWZ":
            if letter not in used and letter not in RESERVED:
                return letter
        return f"P{len(self.rows) + 1}"

    def add_row(self, name, start="1"):
        self.rows.append({"name": name, "start": start, "lower": "", "upper": "", "fixed": False})

    def add(self):
        if len(self.rows) >= MAX_PARAMETERS:
            self.bell()
            return
        self.add_row(self.free_name())
        self.refresh(len(self.rows) - 1)
        self.entries["name"].focus_set()
        self.entries["name"].selection_range(0, "end")

    def remove(self):
        index = self.selected()
        if index is None:
            return
        del self.rows[index]
        self.refresh(min(index, len(self.rows) - 1))

    def from_equation(self):
        """Declare every name that the equation uses and the table does not list yet."""
        present = {row["name"] for row in self.rows}
        text = self.equation()
        for match in re.finditer(r"(?<![0-9.A-Za-z_])[A-Za-z][A-Za-z0-9_]*", text):
            name = match.group()
            call = text[match.end():].lstrip().startswith("(")
            if name in RESERVED or name in present or call or len(self.rows) >= MAX_PARAMETERS:
                continue
            present.add(name)
            self.add_row(name)
        self.refresh(len(self.rows) - 1 if self.rows else None)

    def values(self):
        return [{"name": row["name"].strip(), "start": _parse(row["start"]), "lower": _parse(row["lower"]) or None,
                 "upper": _parse(row["upper"]) or None, "fixed": bool(row["fixed"])} for row in self.rows]


def example_parameters():
    return [dict(record) for record in EXAMPLE_PARAMETERS]
