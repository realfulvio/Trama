"""Starting-value editor of Robust curve fit: a compact field in the analysis dialog and a table dialog.

Nothing here fits or evaluates the model. The table proposes the catalog starting values of the first fit,
lets the user override all of them, Reset returns to the catalog and Apply/Cancel decide. The editor keeps the
canonical recipe form: ``{}`` means "catalog values", otherwise a dictionary with exactly the model's parameters.
"""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import ui_theme
from .curve_models import MODELS
from .data import decimal_comma
from .i18n import tr, translate_message
from .robust_curve import (CAUCHY, COMPARE, CURVE, DISPLAY, ERROR_PREFIX, EVALUATIONS, FIXED, GROUP, HUBER, INITIAL, LOSS,
                           MODEL, PILOT_MAD, RESIDUAL_SCALE, RESIDUALS, SCALE_METHOD, SOFT_L1, THRESHOLD, WEIGHTS, X,
                           Y_COLUMNS, _bounds, initial_from)

ERROR = "#b42318"
HINT = "#486075"

# Interface captions and choices; recipes keep the English field names and values.
LABEL_KEYS = {name: f"analysis.robust_curve.field.{name}" for name in (
    X, Y_COLUMNS, GROUP, MODEL, LOSS, SCALE_METHOD, RESIDUAL_SCALE, INITIAL, EVALUATIONS, THRESHOLD, COMPARE, DISPLAY)}
CHOICE_KEYS = {CAUCHY: "analysis.robust_curve.choice.cauchy", HUBER: "analysis.robust_curve.choice.huber",
               SOFT_L1: "analysis.robust_curve.choice.soft_l1", FIXED: "analysis.robust_curve.choice.fixed",
               PILOT_MAD: "analysis.robust_curve.choice.pilot_mad", CURVE: "analysis.robust_curve.choice.curve",
               RESIDUALS: "analysis.robust_curve.choice.residuals", WEIGHTS: "analysis.robust_curve.choice.weights"}
TAB_KEYS = {"variables": "analysis.robust_curve.tab.variables", "loss": "analysis.robust_curve.tab.loss",
            "output": "analysis.robust_curve.tab.output"}


def field_caption(name):
    return tr(LABEL_KEYS[name]) if name in LABEL_KEYS else name


def visibility(scale_method):
    """The residual scale is used only by the Fixed method; under Pilot MAD it is hidden and never validated."""
    return {RESIDUAL_SCALE: scale_method == FIXED}


def describe_error(error, field):
    """The dialog banner for an engine or dialog error: translated, naming the field it belongs to."""
    message = translate_error(error, field_caption=field_caption)
    label = field_caption(field) if field else ""
    if field and field not in message and label not in message:
        message = f"{label}: {message}"
    return message


def translate_error(error, *, field_caption=lambda name: name):
    """An engine message of Robust curve fit in the active language; field names become dialog captions."""
    return translate_message(str(error), ERROR_PREFIX, {"field": field_caption})


def _text(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "" if value is None else str(value)
    return f"{value:.10g}"


def _limit(low, high):
    if low == float("-inf") and high == float("inf"):
        return ""
    return f"[{'−∞' if low == float('-inf') else f'{low:.4g}'}, {'∞' if high == float('inf') else f'{high:.4g}'}]"


def summary_text(model, values):
    """The one-line state shown next to the Edit button."""
    if not values:
        return tr("analysis.robust_curve.initial.catalog")
    if isinstance(values, dict):
        shown = ", ".join(f"{name} = {_text(value)}" for name, value in list(values.items())[:3])
        return tr("analysis.robust_curve.initial.custom", values=shown + ("…" if len(values) > 3 else ""))
    return tr("analysis.robust_curve.initial.custom", values=str(values))


class InitialParametersDialog(simpledialog.Dialog):
    """Table of the model's parameters: catalog proposal, editable start, limits. Result: a dict, or ``{}`` for the catalog."""

    def __init__(self, parent, model, values, proposed):
        self.model, self.proposed = model, dict(proposed)
        self.spec = MODELS[model]
        self.saved = values if isinstance(values, dict) else {}
        # Untouched entries mean "catalog": Apply then keeps the recipe field empty.
        self.catalog = not values
        self.variables, self.entries = {}, {}
        super().__init__(parent, tr("analysis.robust_curve.editor.title"))

    def body(self, master):
        master.columnconfigure(0, weight=1)
        ttk.Label(master, text=tr("analysis.robust_curve.editor.model", model=self.model),
                  style="DialogTitle.TLabel").grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
        ttk.Label(master, text=tr("analysis.robust_curve.editor.note"), wraplength=ui_theme.px(440), justify="left",
                  foreground=HINT).grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
        table = ttk.Frame(master)
        table.grid(row=2, column=0, sticky="nsew", padx=8)
        for column, key in enumerate(("parameter", "start", "catalog", "limits")):
            ttk.Label(table, text=tr("analysis.robust_curve.editor." + key), style="DialogTitle.TLabel").grid(
                row=0, column=column, sticky="w", padx=(0, 10), pady=(0, 3))
        lower, upper = _bounds(self.spec)
        first = None
        for row, (name, low, high) in enumerate(zip(self.spec.parameters, lower, upper, strict=True), start=1):
            ttk.Label(table, text=name).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            start = self.saved.get(name, self.proposed.get(name, ""))
            variable = tk.StringVar(value=_text(start))
            entry = ttk.Entry(table, textvariable=variable, width=16, justify="right")
            entry.grid(row=row, column=1, sticky="ew", padx=(0, 10), pady=2)
            variable.trace_add("write", lambda *_: self.edited())
            ttk.Label(table, text=_text(self.proposed.get(name, "—")), foreground=HINT).grid(
                row=row, column=2, sticky="e", padx=(0, 10), pady=2)
            ttk.Label(table, text=_limit(low, high), foreground=HINT).grid(row=row, column=3, sticky="w", pady=2)
            self.variables[name], self.entries[name] = variable, entry
            first = first or entry
        self.message = ttk.Label(master, foreground=ERROR, wraplength=ui_theme.px(440), justify="left")
        self.message.grid(row=3, column=0, sticky="w", padx=8, pady=(8, 0))
        self._loading = False
        return first

    def buttonbox(self):
        row = ttk.Frame(self, padding=(12, 6, 12, 10))
        ttk.Button(row, text=tr("analysis.robust_curve.editor.reset"), command=self.reset).pack(side="left")
        ttk.Button(row, text=tr("analysis.robust_curve.editor.apply"), style="Action.TButton", command=self.ok).pack(
            side="right", padx=(8, 0))
        ttk.Button(row, text=tr("analysis.robust_curve.editor.cancel"), command=self.cancel).pack(side="right")
        row.pack(fill="x")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def edited(self):
        if not self._loading:
            self.catalog = False

    def reset(self):
        """Back to the catalog proposal; Apply then stores the empty (catalog) form."""
        self._loading = True
        try:
            for name, variable in self.variables.items():
                variable.set(_text(self.proposed.get(name, "")))
        finally:
            self._loading = False
        self.catalog = True
        self.message.configure(text="")

    def parsed(self):
        values = {}
        for name, variable in self.variables.items():
            text = variable.get().strip()
            try:
                values[name] = float(decimal_comma(text))
            except ValueError:
                values[name] = text
        return values

    def validate(self):
        if self.catalog:
            self.result = {}
            return True
        values = self.parsed()
        try:
            initial_from(self.spec, values)
        except ValueError as error:
            name = getattr(error, "parameter", None)
            message = translate_error(error)
            self.message.configure(text=message)
            messagebox.showerror(tr("analysis.robust_curve.editor.title"), message, parent=self)
            if name in self.entries:
                self.entries[name].focus_set()
                self.initial_focus = self.entries[name]
            return False
        self.result = values
        return True


class InitialParameters(ttk.Frame):
    """The "Initial parameters" field: a summary of the recipe value and an Edit button for the table."""

    def __init__(self, parent, values, *, model, proposal):
        super().__init__(parent)
        self.model, self.proposal = model, proposal
        self.current = values if isinstance(values, dict) else {}
        self.columnconfigure(0, weight=1)
        self.summary = ttk.Label(self, wraplength=ui_theme.px(240), justify="left")
        self.summary.grid(row=0, column=0, sticky="w")
        self.button = ttk.Button(self, text=tr("analysis.robust_curve.initial.edit"), command=self.edit)
        self.button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.refresh()

    def values(self):
        return dict(self.current)

    def focus_target(self):
        return self.button

    def refresh(self):
        self.summary.configure(text=summary_text(self.model(), self.current))

    def set_model(self, model):
        """A different model has other parameters: the table returns to the catalog values."""
        names = set(MODELS[model].parameters) if model in MODELS else set()
        if self.current and set(self.current) != names:
            self.current = {}
        self.refresh()

    def edit(self):
        model = self.model()
        if model not in MODELS:
            return None
        dialog = InitialParametersDialog(self.winfo_toplevel(), model, self.current, self.proposal())
        if dialog.result is not None:
            self.current = dict(dialog.result)
            self.refresh()
        return dialog.result
