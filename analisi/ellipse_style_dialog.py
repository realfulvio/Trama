"""Edit sparse fill and border overrides for one confidence overlay group at a time."""

from collections import Counter
import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog, ttk

from matplotlib.colors import to_hex

from .data import decimal_comma
from .ellipse_workbench import (BY_GROUP, DEFAULT_COLOR, GROUP_BORDER_FIELDS, GROUP_FILL_FIELDS,
                               GROUP_STYLES, LINE_PATTERNS, normalize_ellipse_group_styles)
from .graph_dialog import ChoiceBinding
from .graph_legend import typed_group_token
from .i18n import fixed_choice_keys, ui
from .processing import FieldError


class EllipseStyleDialog(simpledialog.Dialog):
    def __init__(self, parent, values, options, column, styles):
        self.result = None
        self.column = column
        self.fields = ()
        if options.get("Fill") == BY_GROUP:
            self.fields += GROUP_FILL_FIELDS
        if options.get("Border") == BY_GROUP:
            self.fields += GROUP_BORDER_FIELDS
        self.levels = [(typed_group_token(value), str(value)) for value in values]
        self.styles = normalize_ellipse_group_styles(styles)
        self.index = 0
        super().__init__(parent, ui(GROUP_STYLES))

    def body(self, parent):
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text=ui("Empty fields inherit the graph style."), wraplength=355).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 9))
        ttk.Label(parent, text=ui("Group")).grid(row=1, column=0, sticky="w", padx=(0, 8))
        counts = Counter(label for _, label in self.levels)
        captions = [f"{label} ({ui('Text') if token.startswith('str:') else ui('Number')})"
                    if counts[label] > 1 else label for token, label in self.levels]
        self.groups = ttk.Combobox(parent, state="readonly", width=30, values=captions)
        self.groups.grid(row=1, column=1, sticky="ew")
        self.groups.bind("<<ComboboxSelected>>", self._select_group)
        self.variables, self.inputs = {}, {}
        for row, field in enumerate(self.fields, 2):
            ttk.Label(parent, text=ui(field)).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            variable = tk.StringVar(parent)
            if field == "Border style":
                entry = ttk.Combobox(parent, state="readonly", width=20)
                choices = ("", *LINE_PATTERNS)
                ChoiceBinding(entry, variable, choices, fixed_choice_keys(choices))
            else:
                entry = ttk.Entry(parent, textvariable=variable, width=20)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            if field in ("Fill color", "Border color"):
                ttk.Button(parent, text=ui("Choose color…"), command=lambda value=variable: self._pick(value)).grid(
                    row=row, column=2, sticky="w", padx=(5, 0))
            self.variables[field], self.inputs[field] = variable, entry
        self._show(0)
        return self.groups

    def buttonbox(self):
        buttons = ttk.Frame(self)
        ttk.Button(buttons, text=ui("Cancel"), command=self.cancel).pack(side="right")
        ttk.Button(buttons, text=ui("OK"), command=self.ok).pack(side="right", padx=(0, 6))
        buttons.pack(fill="x", padx=10, pady=(3, 8))
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def _pick(self, variable):
        try:
            initial = to_hex(variable.get())
        except ValueError:
            initial = DEFAULT_COLOR
        _, selected = colorchooser.askcolor(color=initial, parent=self)
        if selected:
            variable.set(selected)

    def _show(self, index):
        self.index = index
        self.groups.current(index)
        identity = self.levels[index][0]
        saved = self.styles.get(self.column, {}).get(identity, {})
        for field, variable in self.variables.items():
            variable.set(saved.get(field, ""))

    def _select_group(self, _event=None):
        new_index = self.groups.current()
        if new_index == self.index or new_index < 0:
            return
        if self.validate():
            self._show(new_index)
        else:
            self.groups.current(self.index)

    def validate(self):
        identity = self.levels[self.index][0]
        current = self.styles.get(self.column, {})
        item = {key: value for key, value in current.get(identity, {}).items() if key not in self.variables}
        for key, variable in self.variables.items():
            value = variable.get().strip()
            if value:
                item[key] = value if key in ("Fill color", "Border color", "Border style") else decimal_comma(value)
        try:
            self.styles = normalize_ellipse_group_styles({**self.styles, self.column: {**current, identity: item}})
        except FieldError as error:
            messagebox.showerror(ui(GROUP_STYLES), ui(str(error)), parent=self)
            self.inputs.get(error.field, self.groups).focus_set()
            return False
        return True

    def apply(self):
        self.result = self.styles
