"""Tk editor for parameter sharing and constraints in a joint fit."""
import math
import tkinter as tk
from tkinter import ttk

from .curve_models import MODELS
from .data import decimal_comma
from .repeated_input import decode_series_constraints


class GlobalParameters(ttk.Frame):
    def __init__(self, parent, model, saved):
        super().__init__(parent, padding=10)
        self.rows = {}
        self.widgets = {}
        self.models = {}
        self.model = None
        self.saved = saved
        self.set_model(model)

    def set_model(self, model):
        if model == self.model:
            return
        if self.model:
            self.models[self.model] = {name: [variable.get() for variable in row]
                                       for name, row in self.rows.items()}
        self.model = model
        self.rows.clear()
        self.widgets.clear()
        for child in self.winfo_children():
            child.destroy()
        ttk.Label(self, text="Choose how each coefficient is fitted across series.",
                  wraplength=430).grid(row=0, column=0, columnspan=7, sticky="w", pady=(0, 8))
        for i, header in enumerate(("Parameter", "Scope", "Fixed value", "Lower", "Upper", "Start", "Compare")):
            ttk.Label(self, text=header).grid(row=1, column=i, sticky="w", padx=2)
        current = self.saved if self.saved.get("Model") == model else {}
        fixed = current.get("Fixed parameters", {})
        shared = current.get("Shared parameters", MODELS[model].required_shared)
        bounds = current.get("Parameter bounds", {})
        initial = current.get("Initial values", {})
        compared = current.get("Compare local parameters", ())
        for row_index, name in enumerate(MODELS[model].parameters, 2):
            initial_state = [("Fixed" if name in fixed else "Shared" if name in shared else "Local"),
                             fixed.get(name), *bounds.get(name, (None, None)), initial.get(name), name in compared]
            initial_state = self.models.get(model, {}).get(name, initial_state)
            scope = tk.StringVar(value=initial_state[0])
            values = [tk.StringVar(value="" if value is None else str(value)) for value in initial_state[1:5]]
            compare = tk.BooleanVar(value=initial_state[5])
            self.rows[name] = (scope, *values, compare)
            ttk.Label(self, text=name, wraplength=100).grid(row=row_index, column=0, sticky="w", padx=2, pady=4)
            ttk.Combobox(self, textvariable=scope, values=("Local", "Shared", "Fixed"),
                         width=8, state="readonly").grid(row=row_index, column=1, sticky="w", padx=2)
            entries = [ttk.Entry(self, textvariable=variable, width=9) for variable in values]
            for column, widget in enumerate(entries, 2):
                widget.grid(row=row_index, column=column, sticky="w", padx=2)
            check = ttk.Checkbutton(self, variable=compare)
            check.grid(row=row_index, column=6, padx=2)
            self.widgets[name] = entries, check
            scope.trace_add("write", lambda *_, label=name: self.set_scope(label))
            self.set_scope(name)
        actions = ttk.Frame(self)
        actions.grid(row=len(self.rows) + 2, column=0, columnspan=7, sticky="w", pady=9)
        for label, value in (("Share all", "Shared"), ("Make all local", "Local")):
            ttk.Button(actions, text=label, command=lambda mode=value: self.set_all(mode)).pack(side="left", padx=(0, 6))
        ttk.Label(self, text="Compare tests selected local coefficients for equality while retaining existing sharing. "
                             "Blank bounds and starts use the model defaults.",
                  wraplength=425, justify="left").grid(row=len(self.rows) + 3, column=0, columnspan=7, sticky="w")

    def set_scope(self, label):
        scope = self.rows[label][0].get()
        compare = self.rows[label][-1]
        entries, check = self.widgets[label]
        entries[0].configure(state="normal" if scope == "Fixed" else "disabled")
        entries[3].configure(state="disabled" if scope == "Fixed" else "normal")
        check.configure(state="normal" if scope == "Local" else "disabled")
        if scope != "Local":
            compare.set(False)

    def set_all(self, mode):
        for row in self.rows.values():
            row[0].set(mode)

    @staticmethod
    def _number(variable, name, field):
        value = variable.get().strip()
        if not value:
            return None
        try:
            number = float(decimal_comma(value))
        except ValueError as error:
            raise ValueError(f"{name}: {field} must be a number.") from error
        if not math.isfinite(number):
            raise ValueError(f"{name}: {field} must be finite.")
        return number

    def values(self):
        shared, fixed, bounds, initial, compared = [], {}, {}, {}, []
        for name, (scope, constant, lower, upper, start, compare) in self.rows.items():
            mode = scope.get()
            low = self._number(lower, name, "lower bound")
            high = self._number(upper, name, "upper bound")
            if low is not None and high is not None and low >= high:
                raise ValueError(f"{name}: lower bound must be less than upper bound.")
            if low is not None or high is not None:
                bounds[name] = [low, high]
            if mode == "Fixed":
                value = self._number(constant, name, "fixed value")
                if value is None:
                    raise ValueError(f"Enter a fixed value for {name}.")
                fixed[name] = value
            else:
                guess = self._number(start, name, "start")
                if guess is not None:
                    initial[name] = guess
                if mode == "Shared":
                    shared.append(name)
                elif compare.get():
                    compared.append(name)
        return {"Shared parameters": shared, "Fixed parameters": fixed, "Parameter bounds": bounds,
                "Initial values": initial, "Compare local parameters": compared}


class SeriesConstraints(ttk.Frame):
    fields = (("fixed", "Fixed value"), ("lower", "Lower"), ("upper", "Upper"), ("initial", "Start"))

    def __init__(self, parent, model, saved):
        super().__init__(parent, padding=10)
        self.model = None
        self.series = None
        self.labels = []
        self.available = []
        self.rows = {}
        self.edits = {
            (saved.get("Model"), label): {name: {key: str(value) for key, value in fields.items()}
                                         for name, fields in parameters.items()}
            for label, parameters in decode_series_constraints(saved.get("Series constraints", [])).items()
        }
        ttk.Label(self, text="Override fit settings for individual series.", style="DialogTitle.TLabel").pack(anchor="w")
        selector = ttk.Frame(self)
        selector.pack(fill="x", pady=(8, 10))
        ttk.Label(selector, text="Series").pack(side="left", padx=(0, 8))
        self.choices = ttk.Combobox(selector, state="readonly")
        self.choices.pack(side="left", fill="x", expand=True)
        self.choices.bind("<<ComboboxSelected>>", self._select)
        self.table = ttk.Frame(self)
        self.table.pack(fill="x")
        ttk.Button(self, text="Clear this series", command=self._clear).pack(anchor="w", pady=8)
        ttk.Label(self, text="A blank field inherits the common setting. Fix values and set starts on local "
                             "parameters. Bounds also apply to shared parameters.",
                  wraplength=500, justify="left").pack(anchor="w")
        self.set_model(model)

    def _store(self):
        if self.series is None:
            return
        parameters = {}
        for name, row in self.rows.items():
            values = {key: variable.get().strip() for key, variable in row.items() if variable.get().strip()}
            if values:
                parameters[name] = values
        key = self.model, self.series
        if parameters:
            self.edits[key] = parameters
        else:
            self.edits.pop(key, None)

    def set_model(self, model):
        self._store()
        self.model = model
        self._refresh_choices()

    def set_labels(self, labels):
        self._store()
        self.available = labels
        self._refresh_choices()

    def _refresh_choices(self):
        self.labels = list(dict.fromkeys([*self.available, *(label for model, label in self.edits if model == self.model)]))
        display = []
        for i, label in enumerate(self.labels, 1):
            suffix = "" if label in self.available else " · outside selection"
            display.append(f"{i}. {label!r}{suffix}")
        self.choices.configure(values=display)
        if self.labels:
            index = self.labels.index(self.series) if self.series in self.labels else 0
            self.choices.current(index)
            self.series = self.labels[index]
        else:
            self.choices.set("")
            self.series = None
        self._draw_rows()

    def _select(self, _=None):
        index = self.choices.current()
        if index >= 0:
            self._store()
            self.series = self.labels[index]
            self._draw_rows()

    def _clear(self):
        self.edits.pop((self.model, self.series), None)
        self._refresh_choices()

    def _draw_rows(self):
        for child in self.table.winfo_children():
            child.destroy()
        self.rows.clear()
        if self.series is None:
            ttk.Label(self.table, text="Select XY columns and series on the Variables tab.").grid(sticky="w")
            return
        for i, heading in enumerate(("Parameter", *(title for _, title in self.fields))):
            ttk.Label(self.table, text=heading).grid(row=0, column=i, padx=3, sticky="w")
        saved = self.edits.get((self.model, self.series), {})
        for i, name in enumerate(MODELS[self.model].parameters, 1):
            ttk.Label(self.table, text=name).grid(row=i, column=0, padx=3, pady=4, sticky="w")
            row = self.rows[name] = {}
            for column, (key, _) in enumerate(self.fields, 1):
                row[key] = tk.StringVar(value=saved.get(name, {}).get(key, ""))
                ttk.Entry(self.table, textvariable=row[key], width=11).grid(row=i, column=column, padx=3)

    def values(self):
        self._store()
        records = []
        for (model, label), overrides in self.edits.items():
            if model != self.model:
                continue
            if label not in self.available:
                raise ValueError(f"Series {label!r} is outside the input selection. Clear its overrides or include it.")
            parameters = {}
            for name, settings in overrides.items():
                numbers = {}
                for key, value in settings.items():
                    try:
                        number = float(decimal_comma(value))
                    except ValueError as error:
                        raise ValueError(f"Series {label!r}, {name}: {key} must be a number.") from error
                    if not math.isfinite(number):
                        raise ValueError(f"Series {label!r}, {name}: {key} must be finite.")
                    numbers[key] = number
                parameters[name] = numbers
            records.append({"series": label, "parameters": parameters})
        return records
