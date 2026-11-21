"""Profile editor and field helpers for the Cox regression dialog."""
import tkinter as tk
from tkinter import ttk

from .cox_fit_diagnostics import COX_SNELL, SCALED, X_AXIS
from .cox_outputs import LABEL, MAX_PROFILES, VALUES, _number, categories_of, cox_message, model_terms
from .i18n import tr

TABS = {"Predicted survival": ("Predict survival", "Profiles"),
        "Diagnostics": ("Cox diagnostics", "Schoenfeld residuals", SCALED, COX_SNELL, "Graph display",
                        "Schoenfeld term", X_AXIS)}


def _shown(value):
    return f"{value:g}" if isinstance(value, float) else str(value)


class ProfileEditor(ttk.Frame):
    """Covariate profiles as {"Label": ..., "Values": {predictor: value}} records.

    Categorical predictors offer the categories present in the worksheet; continuous ones take finite numbers.
    Records whose predictors no longer match the model stay in the list so the analysis can name the problem.
    """

    def __init__(self, parent, data, profiles, *, label_key=LABEL, values_key=VALUES, hint=None, on_change=None,
                 weight_key=None):
        super().__init__(parent)
        self.data = data
        self.label_key, self.values_key = label_key, values_key
        # A profile may carry the raw precision of a future observation; the field shows only when it is needed.
        self.weight_key, self.weight_enabled = weight_key, False
        self.on_change = on_change
        self.hint = hint or f"Up to {MAX_PROFILES} profiles. Curves share the fit's baseline hazard."
        self.profiles = [dict(p, **{values_key: dict(p.get(values_key) or {})}) if isinstance(p, dict) else p
                         for p in (profiles if isinstance(profiles, (list, tuple)) else [])]
        self.predictors, self.categories, self.inputs = [], [], {}
        self.label = tk.StringVar()
        ttk.Label(self, text="Label").grid(row=0, column=0, sticky="w")
        self.name_entry = ttk.Entry(self, textvariable=self.label, width=18)
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 3))
        self.values_frame = ttk.Frame(self)
        self.values_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.values_frame.columnconfigure(1, weight=1)
        self.weight = tk.StringVar()
        self.weight_frame = ttk.Frame(self)
        self.weight_label = ttk.Label(self.weight_frame, text=tr("analysis.mlr.profile_weight"))
        self.weight_label.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.weight_entry = ttk.Entry(self.weight_frame, textvariable=self.weight, width=18)
        self.weight_entry.grid(row=0, column=1, sticky="ew")
        self.weight_frame.columnconfigure(1, weight=1)
        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, columnspan=2, sticky="w", pady=(3, 0))
        for text, command in (("Add", self.add), ("Replace", self.replace), ("Remove", self.remove)):
            ttk.Button(buttons, text=text, width=8, command=command).pack(side="left", padx=(0, 4))
        self.listbox = tk.Listbox(self, height=4, exportselection=False, selectmode="browse")
        self.listbox.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.listbox.bind("<<ListboxSelect>>", lambda _: self.load())
        self.listbox.bind("<Delete>", lambda _: self.remove())
        self.note = ttk.Label(self, foreground="#486075", wraplength=290)
        self.note.grid(row=5, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.columnconfigure(1, weight=1)
        self.refresh()

    def set_weight_visible(self, enabled):
        """Show the future-observation weight field only while the model needs it."""
        enabled = bool(enabled and self.weight_key)
        if enabled == self.weight_enabled:
            return
        self.weight_enabled = enabled
        if enabled:
            self.weight_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        else:
            self.weight_frame.grid_remove()
        self.refresh()

    def focus_target(self):
        """The first entry to fix after a rejected profile: the weight when it is the one in use."""
        return self.weight_entry if self.weight_enabled and not self.weight.get().strip() else self.name_entry

    def set_predictors(self, predictors, categories):
        predictors, categories = list(predictors), [name for name in categories if name in predictors]
        if (predictors, categories) == (self.predictors, self.categories):
            return
        self.predictors, self.categories = predictors, categories
        for child in self.values_frame.winfo_children():
            child.destroy()
        self.inputs = {}
        for row, name in enumerate(predictors):
            ttk.Label(self.values_frame, text=name).grid(row=row, column=0, sticky="w", padx=(0, 6))
            variable = tk.StringVar()
            if name in categories:
                levels = categories_of(self.data, name)
                field = ttk.Combobox(self.values_frame, textvariable=variable, values=levels, state="readonly",
                                     width=16)
                if levels:
                    variable.set(levels[0])
            else:
                field = ttk.Entry(self.values_frame, textvariable=variable, width=18)
            field.grid(row=row, column=1, sticky="ew", pady=1)
            self.inputs[name] = variable
        self.refresh()

    def describe(self, profile):
        if not isinstance(profile, dict):
            return "Unavailable profile"
        values = profile.get(self.values_key) or {}
        text = f"{profile.get(self.label_key, '')}: " + ", ".join(
            f"{key} = {_shown(value)}" for key, value in values.items())
        if self.weight_key and self.weight_key in profile:
            text += f", {self.weight_key} = {_shown(profile[self.weight_key])}"
        return text

    def refresh(self, selected=None):
        self.listbox.delete(0, "end")
        for number, profile in enumerate(self.profiles, 1):
            self.listbox.insert("end", f"{number}. {self.describe(profile)}")
        if selected is not None and self.profiles:
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
        stale = [p for p in self.profiles if not isinstance(p, dict)
                 or set((p.get(self.values_key) or {})) != set(self.predictors)]
        if not self.predictors:
            self.note.configure(text="Choose the predictors on the Variables tab first.")
        elif stale:
            self.note.configure(text="Some profiles do not match the predictors. Select and replace them.")
        else:
            self.note.configure(text=self.hint)

    def current(self):
        """The profile in the entry fields, or None after reporting the problem in the note."""
        label = self.label.get().strip()
        if not label:
            self.note.configure(text="Enter a label for the profile.")
            return None
        values = {}
        for name, variable in self.inputs.items():
            text = variable.get().strip()
            if name in self.categories:
                if not text:
                    self.note.configure(text=f"Choose a category for {name}.")
                    return None
                values[name] = text
            else:
                number = _number(text)
                if number is None:
                    self.note.configure(text=f"{name} needs a finite number.")
                    return None
                values[name] = number
        if not values:
            self.note.configure(text="Choose the predictors on the Variables tab first.")
            return None
        profile = {self.label_key: label, self.values_key: values}
        if self.weight_enabled:
            weight = _number(self.weight.get())
            if weight is None or weight <= 0:
                self.note.configure(text=tr("analysis.mlr.profile_weight_error"))
                return None
            profile[self.weight_key] = weight
        return profile

    def selected(self):
        selection = self.listbox.curselection()
        return selection[0] if selection else None

    def add(self):
        profile = self.current()
        if profile is None:
            return False
        if len(self.profiles) >= MAX_PROFILES:
            self.note.configure(text=f"Use at most {MAX_PROFILES} profiles.")
            return False
        if any(isinstance(p, dict) and p.get(self.label_key) == profile[self.label_key] for p in self.profiles):
            self.note.configure(text=f'A profile is already called "{profile[self.label_key]}".')
            return False
        self.profiles.append(profile)
        self.label.set("")
        self.refresh(len(self.profiles) - 1)
        self._notify()
        return True

    def replace(self):
        index, profile = self.selected(), self.current()
        if index is None or profile is None:
            if index is None:
                self.note.configure(text="Select the profile to replace.")
            return False
        if any(isinstance(p, dict) and p.get(self.label_key) == profile[self.label_key] and i != index
               for i, p in enumerate(self.profiles)):
            self.note.configure(text=f'A profile is already called "{profile[self.label_key]}".')
            return False
        previous = self.profiles[index]
        if self.weight_key and self.weight_key not in profile and isinstance(previous, dict) \
                and self.weight_key in previous:
            # The weight field is hidden: keep what the profile already carries.
            profile[self.weight_key] = previous[self.weight_key]
        self.profiles[index] = profile
        self.refresh(index)
        self._notify()
        return True

    def remove(self):
        index = self.selected()
        if index is None:
            return
        del self.profiles[index]
        self.refresh(min(index, len(self.profiles) - 1) if self.profiles else None)
        self._notify()

    def _notify(self):
        if self.on_change is not None:
            self.on_change()

    def load(self):
        index = self.selected()
        if index is None or not isinstance(self.profiles[index], dict):
            return
        profile = self.profiles[index]
        self.label.set(profile.get(self.label_key, ""))
        for name, variable in self.inputs.items():
            value = (profile.get(self.values_key) or {}).get(name)
            if value is not None:
                variable.set(_shown(value))
        if self.weight_key and self.weight_key in profile:
            self.weight.set(_shown(profile[self.weight_key]))

    def values(self):
        return [dict(p, **{self.values_key: dict(p[self.values_key])})
                if isinstance(p, dict) and isinstance(p.get(self.values_key), dict) else p
                for p in self.profiles]
