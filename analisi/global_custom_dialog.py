"""Editors for Global fit custom equation.

The formula box is the Fit custom equation editor. The coefficient table adds Local, Shared or Fixed,
and the series page stores per-series overrides. Nothing here fits or evaluates while the user types.
"""
import re
import tkinter as tk
from tkinter import ttk

from .custom_equations import ARITHMETIC, MAX_PARAMETERS
from .custom_equation_dialog import reserved_names, translate_error as translate_custom_error
from .data import decimal_comma
from .field_error import FieldError
from .graph_dialog import ChoiceBinding
from .i18n import tr, translate_message
from .repeated_input import decode_series_constraints

_GROUP_PREFIX = re.compile(r"Group (?P<group>.+?): (?P<rest>.*)\Z", re.DOTALL)
_NAME = re.compile(r"(?<![0-9.A-Za-z_])[A-Za-z][A-Za-z0-9_]*")
SCOPES = ("Local", "Shared", "Fixed")
SCOPE_KEYS = {"Local": "gfit.scope.local", "Shared": "gfit.scope.shared", "Fixed": "gfit.scope.fixed"}
_OVERRIDE_KEYS = ("fixed", "lower", "upper", "initial")


def translate_error(message):
    """Translate a global-fit message, then a sentence shared with Fit custom equation."""
    message = str(message)
    match = _GROUP_PREFIX.match(message)
    if match and not message.startswith("Group must") and not message.startswith("Group is required"):
        return tr("custom.group_prefix", group=match["group"]) + " " + translate_error(match["rest"])
    translated = translate_message(message, "gfit.error.")
    if translated != message:
        return translated
    return translate_custom_error(message)


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
    if text == "":
        return None
    try:
        return float(decimal_comma(text))
    except ValueError:
        return text


def _finite(value):
    return isinstance(value, float) and value == value and value not in (float("inf"), float("-inf"))


def _scope(record):
    if record.get("fixed"):
        return "Fixed"
    if record.get("shared"):
        return "Shared"
    return "Local"


def names_in(equation, syntax=ARITHMETIC):
    """Coefficient-like names in the formula. Calls and reserved words (if/and/or/not in Conditional) are not."""
    found = []
    reserved = reserved_names(syntax)
    for match in _NAME.finditer(equation or ""):
        name = match.group()
        if name in reserved or equation[match.end():].lstrip().startswith("(") or name in found:
            continue
        found.append(name)
    return found


class GlobalCoefficientTable(ttk.Frame):
    """Coefficients with a starting value, Local/Shared/Fixed, and limits."""

    COLUMNS = (("name", 88), ("scope", 88), ("start", 88), ("lower", 72), ("upper", 72))

    def __init__(self, parent, records, *, equation, syntax=lambda: ARITHMETIC):
        super().__init__(parent)
        self.equation = equation
        self.syntax = syntax
        self.rows = []
        for record in records if isinstance(records, (list, tuple)) else ():
            if isinstance(record, dict):
                self.rows.append({"name": _text(record.get("name")), "start": _text(record.get("start")),
                                  "lower": _text(record.get("lower")), "upper": _text(record.get("upper")),
                                  "scope": _scope(record)})
        self.loading = False
        self.columnconfigure(0, weight=1)
        table = ttk.Frame(self)
        table.grid(row=0, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=[name for name, _ in self.COLUMNS], show="headings",
                                 selectmode="browse", height=5)
        for name, width in self.COLUMNS:
            self.tree.heading(name, text=tr(f"gfit.column.{name}"))
            self.tree.column(name, width=width, anchor="w" if name == "name" else "center", stretch=True)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.load_selection())
        self.tree.bind("<Delete>", lambda _: self.remove())
        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=0, sticky="w", pady=(5, 0))
        for text, command in ((tr("gfit.add"), self.add), (tr("gfit.remove"), self.remove),
                              (tr("gfit.from_equation"), self.from_equation)):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 5))
        form = ttk.Frame(self)
        form.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        self.variables = {key: tk.StringVar() for key in ("name", "start", "lower", "upper")}
        self.scope = tk.StringVar(value="Local")
        self.start_label = ttk.Label(form, text=tr("gfit.start"))
        self.entries = {}
        for position, (key, label) in enumerate((("name", None), ("start", self.start_label),
                                                 ("lower", None), ("upper", None))):
            row, column = divmod(position, 2)
            caption = label or ttk.Label(form, text=tr(f"gfit.column.{key}"))
            caption.grid(row=row, column=2 * column, sticky="w", padx=(10 if column else 0, 4), pady=2)
            entry = ttk.Entry(form, textvariable=self.variables[key], width=14)
            entry.grid(row=row, column=2 * column + 1, sticky="ew", pady=2)
            self.entries[key] = entry
            self.variables[key].trace_add("write", lambda *_: self.store())
        scope_box = ttk.Combobox(form, state="readonly", width=14)
        scope_box.grid(row=2, column=1, sticky="w", pady=(4, 0))
        ttk.Label(form, text=tr("gfit.column.scope")).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.scope_binding = ChoiceBinding(scope_box, self.scope, SCOPES, SCOPE_KEYS)
        self.scope.trace_add("write", lambda *_: self.store())
        ttk.Label(self, wraplength=460, justify="left", foreground="#486075",
                  text=tr("gfit.parameters_note")).grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.unused = ttk.Label(self, wraplength=460, justify="left", foreground="#b42318")
        self.unused.grid(row=4, column=0, sticky="w")
        self.refresh()
        if self.rows:
            self.tree.selection_set("0")
        self.load_selection()
        self.mark_unused()

    def focus_target(self):
        return self.tree

    def selected(self):
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def _shown(self, row):
        scope = tr(SCOPE_KEYS[row["scope"]]) if row["scope"] in SCOPE_KEYS else row["scope"]
        return (row["name"], scope, row["start"], row["lower"], row["upper"])

    def refresh(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(index), values=self._shown(row))
        if select is not None and 0 <= select < len(self.rows):
            self.tree.selection_set(str(select))
        self.load_selection()
        self.mark_unused()

    def set_form_state(self):
        state = "normal" if self.selected() is not None else "disabled"
        for entry in self.entries.values():
            entry.configure(state=state)
        self.scope_binding.combobox.configure(state="readonly" if state == "normal" else "disabled")
        self.start_label.configure(text=tr("gfit.value") if self.scope.get() == "Fixed" else tr("gfit.start"))

    def load_selection(self):
        index = self.selected()
        self.loading = True
        try:
            row = self.rows[index] if index is not None else {"name": "", "start": "", "lower": "", "upper": "",
                                                              "scope": "Local"}
            for key, variable in self.variables.items():
                variable.set(row[key])
            self.scope.set(row["scope"] if row["scope"] in SCOPES else "Local")
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
        scope = self.scope.get()
        row["scope"] = scope if scope in SCOPES else row["scope"]
        self.tree.item(str(index), values=self._shown(row))
        self.set_form_state()
        self.mark_unused()

    def mark_unused(self):
        present = names_in(self.equation(), self.syntax())
        unused = [row["name"].strip() for row in self.rows if row["name"].strip() and row["name"].strip() not in present]
        self.unused.configure(text=tr("gfit.unused", names=", ".join(unused)) if unused else "")

    def free_name(self):
        used = {row["name"] for row in self.rows}
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWZ":
            if letter not in used and letter not in reserved_names(self.syntax()):
                return letter
        return f"P{len(self.rows) + 1}"

    def add_row(self, name, start="1", scope="Local"):
        self.rows.append({"name": name, "start": start, "lower": "", "upper": "", "scope": scope})

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
        self.refresh(min(index, len(self.rows) - 1) if self.rows else None)

    def from_equation(self):
        present = {row["name"] for row in self.rows}
        for name in names_in(self.equation(), self.syntax()):
            if name in present or len(self.rows) >= MAX_PARAMETERS:
                continue
            present.add(name)
            self.add_row(name)
        self.refresh(len(self.rows) - 1 if self.rows else None)

    def values(self):
        """Recipe rows. A limit of zero stays zero; only a blank limit is omitted."""
        rows = []
        for row in self.rows:
            scope = row["scope"] if row["scope"] in SCOPES else "Local"
            rows.append({"name": row["name"].strip(), "start": _parse(row["start"]),
                         "lower": _parse(row["lower"]), "upper": _parse(row["upper"]),
                         "fixed": scope == "Fixed", "shared": scope == "Shared"})
        return rows


class SeriesConstraintEditor(ttk.Frame):
    """Per-series overrides. A series or coefficient no longer in the selection is kept and rejected."""

    def __init__(self, parent, saved, *, names, series):
        super().__init__(parent)
        self.names = names
        self.series_labels = series
        self.edits = {}
        self.load_error = None
        self._read_saved(saved)
        self.labels = []
        self.series = None
        self.rows = []
        self.loading = False
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text=tr("gfit.series.title"), wraplength=460).grid(row=0, column=0, sticky="w")
        selector = ttk.Frame(self)
        selector.grid(row=1, column=0, sticky="ew", pady=(6, 4))
        ttk.Label(selector, text=tr("gfit.series.series")).pack(side="left", padx=(0, 8))
        self.choices = ttk.Combobox(selector, state="readonly", width=36)
        self.choices.pack(side="left", fill="x", expand=True)
        self.choices.bind("<<ComboboxSelected>>", self._select)
        table = ttk.Frame(self)
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        columns = ("name", *_OVERRIDE_KEYS)
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse", height=4)
        headings = {"name": tr("gfit.series.parameter"), "fixed": tr("gfit.series.fixed"),
                    "lower": tr("gfit.series.lower"), "upper": tr("gfit.series.upper"),
                    "initial": tr("gfit.series.initial")}
        for name in columns:
            self.tree.heading(name, text=headings[name])
            self.tree.column(name, width=88 if name == "name" else 78, anchor="w" if name == "name" else "center",
                             stretch=True)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.load_selection())
        form = ttk.Frame(self)
        form.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.variables = {}
        self.entries = {}
        for column, key in enumerate(_OVERRIDE_KEYS):
            ttk.Label(form, text=headings[key]).grid(row=0, column=column, sticky="w", padx=(0, 4))
            variable = tk.StringVar()
            entry = ttk.Entry(form, textvariable=variable, width=12)
            entry.grid(row=1, column=column, sticky="ew", padx=(0, 4))
            variable.trace_add("write", lambda *_: self.store())
            self.variables[key] = variable
            self.entries[key] = entry
        buttons = ttk.Frame(self)
        buttons.grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Button(buttons, text=tr("gfit.series.clear"), command=self.clear_series).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text=tr("gfit.series.clear_all"), command=self.clear_all).pack(side="left")
        ttk.Label(self, wraplength=460, justify="left", foreground="#486075",
                  text=tr("gfit.series.blank")).grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.warning = ttk.Label(self, wraplength=460, justify="left", foreground="#b42318")
        self.warning.grid(row=6, column=0, sticky="w")
        self.refresh_labels()

    def focus_target(self):
        return self.choices

    def _read_saved(self, saved):
        if saved is None:
            saved = []
        if not isinstance(saved, list):
            self.load_error = "Series constraints must be a list of series records."
            return
        try:
            decoded = decode_series_constraints(saved)
        except ValueError as error:
            self.load_error = str(error)
            return
        for label, parameters in decoded.items():
            self.edits[str(label)] = {
                str(name): {key: _text(value) for key, value in fields.items() if key in _OVERRIDE_KEYS}
                for name, fields in parameters.items() if isinstance(fields, dict)
            }

    def current_labels(self):
        try:
            return [str(label) for label in self.series_labels()]
        except (ValueError, TypeError):
            return []

    def coefficient_names(self):
        try:
            return [str(name) for name in self.names() if str(name).strip()]
        except (ValueError, TypeError):
            return []

    def refresh_labels(self):
        self._store_current()
        available = self.current_labels()
        extras = [label for label in self.edits if label not in available]
        self.labels = [*available, *extras]
        outside = tr("gfit.series.outside")
        display = [f"{index}. {label!r}" + ("" if label in available else f" · {outside}")
                   for index, label in enumerate(self.labels, 1)]
        self.choices.configure(values=display)
        if self.labels:
            index = self.labels.index(self.series) if self.series in self.labels else 0
            self.choices.current(index)
            self.series = self.labels[index]
        else:
            self.choices.set("")
            self.series = None
        self._draw_rows()
        self._warn(available)

    def _warn(self, available):
        names = set(self.coefficient_names())
        leftover = sorted({name for overrides in self.edits.values() for name in overrides if name not in names})
        outside = [label for label in self.edits if label not in available]
        lines = []
        if self.load_error:
            lines.append(translate_error(self.load_error))
        if not available and not self.edits and not self.load_error:
            lines.append(tr("gfit.series.none"))
        if leftover:
            lines.append(tr("gfit.series.leftover", names=", ".join(leftover)))
        if outside:
            lines.append(tr("gfit.series.outside_list", names=", ".join(repr(label) for label in outside)))
        self.warning.configure(text=" ".join(lines))

    def _select(self, _=None):
        index = self.choices.current()
        if index < 0 or index >= len(self.labels):
            return
        self._store_current()
        self.series = self.labels[index]
        self._draw_rows()

    def select_series(self, label):
        self.refresh_labels()
        if str(label) not in self.labels:
            raise ValueError(f"series {label} is not listed")
        self.choices.current(self.labels.index(str(label)))
        self._select()

    def select_coefficient(self, name):
        index = next(position for position, row in enumerate(self.rows) if row["name"] == name)
        self.tree.selection_set(str(index))
        self.tree.see(str(index))
        self.load_selection()

    def _draw_rows(self):
        names = self.coefficient_names()
        saved = self.edits.get(self.series, {}) if self.series is not None else {}
        self.rows = [{"name": name, **{key: saved.get(name, {}).get(key, "") for key in _OVERRIDE_KEYS}}
                     for name in names]
        self.tree.delete(*self.tree.get_children())
        if self.series is None:
            self.load_selection()
            return
        for index, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(index),
                             values=(row["name"], *(row[key] for key in _OVERRIDE_KEYS)))
        if self.rows:
            self.tree.selection_set("0")
        self.load_selection()

    def selected(self):
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def load_selection(self):
        index = self.selected()
        self.loading = True
        try:
            row = self.rows[index] if index is not None else {key: "" for key in _OVERRIDE_KEYS}
            for key, variable in self.variables.items():
                variable.set(row.get(key, ""))
        finally:
            self.loading = False
        state = "normal" if index is not None else "disabled"
        for entry in self.entries.values():
            entry.configure(state=state)

    def store(self):
        index = self.selected()
        if self.loading or index is None or self.series is None:
            return
        row = self.rows[index]
        for key, variable in self.variables.items():
            row[key] = variable.get()
        self.tree.item(str(index), values=(row["name"], *(row[key] for key in _OVERRIDE_KEYS)))
        self._store_current()

    def _store_current(self):
        if self.series is None or not self.rows:
            return
        parameters = {}
        for row in self.rows:
            values = {key: row[key].strip() for key in _OVERRIDE_KEYS if row[key].strip()}
            if values:
                parameters[row["name"]] = values
        # Keep overrides for coefficients that are no longer declared: Run must reject them.
        previous = self.edits.get(self.series, {})
        declared = {row["name"] for row in self.rows}
        for name, values in previous.items():
            if name not in declared and values:
                parameters[name] = values
        if parameters:
            self.edits[self.series] = parameters
        else:
            self.edits.pop(self.series, None)

    def clear_series(self):
        if self.series is None:
            return
        self.edits.pop(self.series, None)
        self.rows = []
        self.refresh_labels()

    def clear_all(self):
        self.edits.clear()
        self.load_error = None
        self.rows = []
        self.refresh_labels()

    def values(self):
        """The persisted list. An override that no longer matches the data is a field error."""
        self._store_current()
        if self.load_error:
            raise FieldError("Series constraints", self.load_error)
        available = self.current_labels()
        names = self.coefficient_names()
        records = []
        for label, overrides in self.edits.items():
            if label not in available:
                raise FieldError("Series constraints",
                                 f"Series {label!r} is not among the series with complete rows. "
                                 "Remove that override or correct the name.")
            parameters = {}
            for name, settings in overrides.items():
                if name not in names:
                    raise FieldError("Series constraints",
                                     f"Series {label!r}, {name} is not a coefficient of this equation. "
                                     "Remove the override or restore the coefficient.")
                numbers = {}
                for key, raw in settings.items():
                    if key not in _OVERRIDE_KEYS:
                        raise FieldError("Series constraints",
                                         f"Series {label!r}, {name}: use only fixed, lower, upper and initial.")
                    parsed = _parse(raw)
                    if not _finite(parsed):
                        raise FieldError("Series constraints",
                                         f"Series {label!r}, {name}: {key} must be a finite number.")
                    numbers[key] = parsed
                if numbers:
                    parameters[name] = numbers
            if parameters:
                records.append({"series": label, "parameters": parameters})
        return records
