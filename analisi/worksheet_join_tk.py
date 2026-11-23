"""Worksheet join controls for the Classica analysis dialog."""

from tkinter import StringVar, ttk

from . import ui_theme
from . import worksheet_join as wj
from .graph_dialog import ChoiceBinding
from .i18n import tr
from .worksheet_join_labels import CARDINALITY_KEYS, FIELD_KEYS, TYPE_KEYS


class JoinEditor:
    def __init__(self, dialog, variables, options, saved):
        self.dialog = dialog
        self.sources = dialog.join_sources
        self.left_columns = tuple(dialog.data.columns)
        self.pairs = []
        self.choices = {}
        self._note(variables, 0, "join.note.left", sheet=dialog.join_left or "")
        ttk.Label(variables, text=tr(FIELD_KEYS[wj.RIGHT_SHEET])).grid(row=1, column=0, sticky="w")
        self.sheet = ttk.Combobox(variables, state="readonly", values=tuple(self.sources), width=18)
        self.sheet.set(saved.get(wj.RIGHT_SHEET) or next(iter(self.sources), ""))
        self.sheet.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        self.sheet.bind("<<ComboboxSelected>>", self.update_right_columns)
        if not self.sources:
            self._note(variables, 2, "join.note.no_sheet")

        self.keys = ttk.Frame(variables)
        self.keys.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        for column, key in enumerate(("join.caption.left_column", "join.caption.right_column"), 1):
            self.keys.columnconfigure(column, weight=1)
            ttk.Label(self.keys, text=tr(key)).grid(row=0, column=column, sticky="w")
        self.add = ttk.Button(variables, text=tr("join.caption.add"), command=lambda: self.add_pair(focus=True))
        self.add.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._note(variables, 5, "join.note.keys")
        left = saved.get(wj.LEFT_KEYS)
        right = saved.get(wj.RIGHT_KEYS)
        left = left if isinstance(left, (list, tuple)) else []
        right = right if isinstance(right, (list, tuple)) else []
        for index in range(min(wj.MAX_KEYS, max(1, len(left), len(right)))):
            self.add_pair(left[index] if index < len(left) else None, right[index] if index < len(right) else None)

        self.kind = self._choice(options, 0, wj.JOIN_TYPE, wj.TYPES, TYPE_KEYS, saved, wj.DEFAULT_TYPE)
        self._note(options, 1, "join.note.type")
        self.rule = self._choice(options, 2, wj.CARDINALITY, wj.CARDINALITIES, CARDINALITY_KEYS, saved,
                                 wj.DEFAULT_CARDINALITY)
        self._note(options, 3, "join.note.cardinality")
        self._note(options, 4, "join.note.results")

    @staticmethod
    def _note(parent, row, key, **values):
        ttk.Label(parent, text=tr(key, **values), wraplength=ui_theme.px(400), justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(6, 3))

    def _choice(self, parent, row, field, values, labels, saved, default):
        ttk.Label(parent, text=tr(FIELD_KEYS[field])).grid(row=row, column=0, sticky="w")
        box = ttk.Combobox(parent, state="readonly", width=18)
        box.grid(row=row, column=1, sticky="ew", padx=(8, 0))
        variable = StringVar(parent, value=saved.get(field, default))
        choice = self.choices[field] = ChoiceBinding(box, variable, values, labels)

        def dispose(_event):
            # Release the callbacks on the Tk thread when the user changes method or closes the dialog.
            for var in (choice.variable, choice.display):
                for modes, callback in var.trace_info():
                    var.trace_remove(modes, callback)

        box.bind("<Destroy>", dispose, add="+")
        return box

    @staticmethod
    def _next_column(columns, used):
        return next((name for name in columns if name not in used), "")

    def add_pair(self, left=None, right=None, *, focus=False):
        if len(self.pairs) >= wj.MAX_KEYS:
            return
        columns = self.sources.get(self.sheet.get(), ())
        if left is None:
            left = self._next_column(self.left_columns, {pair[1].get() for pair in self.pairs})
        if right is None:
            right = left if left in columns else self._next_column(columns, {pair[2].get() for pair in self.pairs})
        left_box = ttk.Combobox(self.keys, values=self.left_columns, width=13, state="readonly")
        right_box = ttk.Combobox(self.keys, values=columns, width=13, state="readonly")
        left_box.set(left)
        right_box.set(right)
        caption = ttk.Label(self.keys)
        remove = ttk.Button(self.keys, width=3, command=lambda: self.remove_pair(pair))
        pair = caption, left_box, right_box, remove
        self.pairs.append(pair)
        self.dialog._bind_scrollable_widgets(self.keys.master, pair)
        self.place_pairs()
        if focus:
            left_box.focus_set()

    def remove_pair(self, pair):
        if len(self.pairs) <= 1:
            return
        self.pairs.remove(pair)
        for widget in pair:
            widget.destroy()
        self.place_pairs()

    def place_pairs(self):
        for row, pair in enumerate(self.pairs, 1):
            caption, _, _, remove = pair
            caption.configure(text=tr("join.caption.pair", number=row))
            remove.configure(text="×", state="normal" if len(self.pairs) > 1 else "disabled")
            for column, widget in enumerate(pair):
                widget.grid(row=row, column=column, sticky="ew", padx=(0, 5), pady=(2, 0))
        self.add.configure(state="normal" if len(self.pairs) < wj.MAX_KEYS else "disabled")

    def update_right_columns(self, _event=None):
        columns = self.sources.get(self.sheet.get(), ())
        for _, left, right, _ in self.pairs:
            right.configure(values=columns)
            if not right.get():
                right.set(left.get() if left.get() in columns else next(iter(columns), ""))

    def request(self):
        title = self.sheet.get()
        if title not in self.sources:
            raise wj.missing_source(title or None)
        options = {
            wj.RIGHT_SHEET: title,
            wj.LEFT_KEYS: [pair[1].get() for pair in self.pairs],
            wj.RIGHT_KEYS: [pair[2].get() for pair in self.pairs],
            **{field: choice.variable.get() for field, choice in self.choices.items()},
        }
        wj.validate(options, self.left_columns, self.sources[title])
        return options

    def focus_target(self, field, pair):
        if field in {wj.LEFT_KEYS, wj.RIGHT_KEYS}:
            return self.pairs[min(pair, len(self.pairs) - 1)][1 if field == wj.LEFT_KEYS else 2]
        return {wj.RIGHT_SHEET: self.sheet, wj.JOIN_TYPE: self.kind, wj.CARDINALITY: self.rule}.get(field)
