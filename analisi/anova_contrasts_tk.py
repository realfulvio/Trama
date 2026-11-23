"""Transactional planned-contrast editor for the Classica ANOVA dialog."""

from copy import deepcopy
from itertools import product
import math
import tkinter as tk
from tkinter import simpledialog, ttk

from . import anova_planned_contrasts as planned
from .anova_contrast_editor import clean_state, coefficient_text, parse_coefficient
from .anova_planned_contrasts import ALPHA, CONTRASTS, CORRECTION, FACTORS, ContrastError
from .data import decimal_comma
from .field_error import FieldError
from .graph_dialog import ChoiceBinding
from .i18n import tr, ui
from .scrollable_dialog import ScrolledBody
from .window_geometry import keep_native_window_on_screen


def caption(key, **values):
    return tr(f"anova.contrasts.{key}", **values)


class ContrastEditor(simpledialog.Dialog):
    def __init__(self, parent, saved, model, levels, check):
        state = clean_state(saved)
        self.model, self.levels, self.check = model, levels, check
        self.factor_order = list(dict.fromkeys([*state[FACTORS], *model]))
        self.initial_factors = state[FACTORS] if state[FACTORS] or state[CONTRASTS] else model
        self.items = [
            {"name": item["name"], "weights": [
                {"levels": dict(zip(state[FACTORS], weight["levels"])),
                 "coefficient": coefficient_text(weight["coefficient"])}
                for weight in item["weights"]]}
            for item in state[CONTRASTS]
        ]
        self.alpha = tk.StringVar(parent, value=coefficient_text(state[ALPHA]))
        self.correction = tk.StringVar(parent, value=state[CORRECTION])
        self.name = tk.StringVar(parent)
        self.coefficient = tk.StringVar(parent)
        self.traces = []
        self.contrast_index = self.weight_index = None
        super().__init__(parent, caption("title"))

    def body(self, master):
        self.scrolled = ScrolledBody(master, max(350, self.winfo_screenheight() - 150), fit_height=True)
        self.scrolled.outer.pack(fill="both", expand=True)
        master = self.scrolled.body
        master.configure(padding=12)
        master.columnconfigure(1, weight=1)
        ttk.Label(master, text=caption("help"), wraplength=min(760, self.winfo_screenwidth() - 70),
                  justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        settings = ttk.Frame(master)
        settings.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        settings.columnconfigure(0, weight=1)
        ttk.Label(settings, text=caption("factors")).grid(row=0, column=0, sticky="w")
        self.factor_list = tk.Listbox(settings, selectmode="multiple", exportselection=False,
                                      height=max(1, len(self.factor_order)), width=30)
        for row, name in enumerate(self.factor_order):
            self.factor_list.insert("end", name if name in self.model else caption("factor_absent", factor=name))
            if name in self.initial_factors:
                self.factor_list.selection_set(row)
        self.factor_list.grid(row=1, column=0, rowspan=2, sticky="ew", padx=(0, 12))
        self.factor_list.bind("<<ListboxSelect>>", lambda _event: self.show_weights(self.weight_index))
        ttk.Label(settings, text=caption("correction")).grid(row=1, column=1, sticky="w")
        self.correction_box = ttk.Combobox(settings, state="readonly", width=16)
        self.correction_box.grid(row=1, column=2, sticky="ew", padx=(6, 0))
        self.choice = ChoiceBinding(self.correction_box, self.correction, planned.CORRECTIONS, planned.CHOICE_KEYS)
        ttk.Label(settings, text=caption("alpha")).grid(row=2, column=1, sticky="w")
        self.alpha_box = ttk.Entry(settings, textvariable=self.alpha, width=9)
        self.alpha_box.grid(row=2, column=2, sticky="ew", padx=(6, 0))

        left = ttk.LabelFrame(master, text=caption("list"), padding=6)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        list_area = ttk.Frame(left)
        list_area.pack(fill="both", expand=True)
        self.contrast_list = tk.Listbox(list_area, height=8, width=22, exportselection=False)
        self.contrast_list.pack(side="left", fill="both", expand=True)
        list_scroll = ttk.Scrollbar(list_area, orient="vertical", command=self.contrast_list.yview)
        list_scroll.pack(side="right", fill="y")
        self.contrast_list.configure(yscrollcommand=list_scroll.set)
        self.contrast_list.bind("<<ListboxSelect>>", self.pick_contrast)
        self.contrast_buttons = {}
        for label, command in (("add", self.add_contrast), ("duplicate", self.duplicate),
                               ("up", lambda: self.move(-1)), ("down", lambda: self.move(1)),
                               ("remove", self.remove_contrast)):
            self.contrast_buttons[label] = ttk.Button(left, text=caption(label), command=command)
            self.contrast_buttons[label].pack(fill="x", pady=(2, 0))

        detail = ttk.LabelFrame(master, text=caption("weights"), padding=6)
        detail.grid(row=2, column=1, sticky="nsew")
        detail.columnconfigure(1, weight=1)
        ttk.Label(detail, text=caption("name")).grid(row=0, column=0, sticky="w")
        self.name_box = ttk.Entry(detail, textvariable=self.name)
        self.name_box.grid(row=0, column=1, sticky="ew")
        table = ttk.Frame(detail)
        table.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=6)
        table.columnconfigure(0, weight=1)
        self.weight_table = ttk.Treeview(table, show="headings", selectmode="browse", height=5)
        self.weight_table.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.weight_table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.weight_table.configure(yscrollcommand=scroll.set)
        self.weight_table.bind("<<TreeviewSelect>>", self.pick_weight)

        self.level_row = ttk.Frame(detail)
        self.level_row.grid(row=2, column=0, columnspan=2, sticky="ew")
        coefficient_row = ttk.Frame(detail)
        coefficient_row.grid(row=3, column=0, columnspan=2, sticky="ew")
        ttk.Label(coefficient_row, text=caption("coefficient")).pack(side="left")
        self.coefficient_box = ttk.Entry(coefficient_row, textvariable=self.coefficient, width=12)
        self.coefficient_box.pack(side="left", padx=6)
        self.add_weight_button = ttk.Button(detail, text=caption("add_weight"), command=self.add_weight)
        self.add_weight_button.grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.remove_weight_button = ttk.Button(detail, text=caption("remove_weight"), command=self.remove_weight)
        self.remove_weight_button.grid(row=4, column=1, sticky="w", pady=(6, 0))
        self.total = ttk.Label(detail, wraplength=380, justify="left")
        self.total.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(detail, text=caption("coefficient.help"), wraplength=380, justify="left").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.bind_reveal((self.factor_list, self.correction_box, self.alpha_box, self.contrast_list,
                          *self.contrast_buttons.values(), self.name_box, self.weight_table,
                          self.coefficient_box, self.add_weight_button, self.remove_weight_button))
        for variable, callback in ((self.name, self.rename), (self.coefficient, self.edit_coefficient)):
            self.traces.append((variable, variable.trace_add("write", callback)))
        self.show_contrasts(0 if self.items else None)
        return self.contrast_list

    def buttonbox(self):
        bar = ttk.Frame(self, padding=(12, 0, 12, 10))
        self.problem = ttk.Label(bar, foreground="#a22032", justify="left",
                                 wraplength=min(760, self.winfo_screenwidth() - 70))
        self.problem.pack(fill="x", pady=(0, 3))
        self.ok_button = ttk.Button(bar, text=ui("OK"), command=self.ok)
        self.ok_button.pack(side="right")
        ttk.Button(bar, text=ui("Cancel"), command=self.cancel).pack(side="right", padx=(0, 6))
        bar.pack(fill="x")
        self.bind("<Escape>", self.cancel)

    def bind_reveal(self, widgets):
        for widget in widgets:
            widget.bind("<FocusIn>", lambda event: self.scrolled.reveal(event.widget), add="+")

    def wait_visibility(self, window=None):
        super().wait_visibility(window)
        if window is None:
            self.keep_on_screen()

    def keep_on_screen(self):
        if not self.winfo_ismapped():
            return
        self.update_idletasks()
        if keep_native_window_on_screen(self):
            return
        x = max(0, min(self.winfo_x(), self.winfo_screenwidth() - self.winfo_width()))
        y = max(0, min(self.winfo_y(), self.winfo_screenheight() - self.winfo_height()))
        if (x, y) != (self.winfo_x(), self.winfo_y()):
            self.geometry(f"+{x}+{y}")

    def destroy(self):
        for variable, callback in self.traces:
            variable.trace_remove("write", callback)
        self.traces.clear()
        if hasattr(self, "choice"):
            for variable in (self.choice.variable, self.choice.display):
                for modes, callback in variable.trace_info():
                    variable.trace_remove(modes, callback)
        super().destroy()

    def factors(self):
        return [self.factor_order[row] for row in self.factor_list.curselection()]

    def contrast(self):
        return self.items[self.contrast_index] if self.contrast_index is not None else None

    def show_contrasts(self, index):
        self.contrast_list.delete(0, "end")
        for item in self.items:
            self.contrast_list.insert("end", item["name"] or "—")
        if index is not None:
            self.contrast_list.selection_set(index)
            self.contrast_list.see(index)
        self.show_contrast(index)

    def show_contrast(self, index):
        self.contrast_index = None
        self.name.set(self.items[index]["name"] if index is not None else "")
        self.contrast_index = index
        self.name_box.configure(state="normal" if index is not None else "disabled")
        availability = {"add": len(self.items) < planned.MAX_CONTRASTS,
                        "duplicate": index is not None and len(self.items) < planned.MAX_CONTRASTS,
                        "up": index is not None and index > 0,
                        "down": index is not None and index < len(self.items) - 1,
                        "remove": index is not None}
        for name, enabled in availability.items():
            self.contrast_buttons[name].configure(state="normal" if enabled else "disabled")
        self.show_weights(0)

    def pick_contrast(self, _event):
        choice = self.contrast_list.curselection()
        if choice and choice[0] != self.contrast_index:
            self.show_contrast(choice[0])

    def rename(self, *_):
        item = self.contrast()
        if item is not None:
            index = self.contrast_index
            item["name"] = self.name.get()
            self.contrast_list.delete(index)
            self.contrast_list.insert(index, item["name"] or "—")
            self.contrast_list.selection_set(index)

    def unique_name(self, candidate):
        used = {item["name"] for item in self.items}
        base = candidate[:planned.MAX_NAME]
        name = base
        number = 2
        while name in used:
            suffix = f" ({number})"
            name = base[:planned.MAX_NAME - len(suffix)] + suffix
            number += 1
        return name

    def add_contrast(self):
        if len(self.items) >= planned.MAX_CONTRASTS:
            return
        name = self.unique_name(caption("new_name", number=len(self.items) + 1))
        item = {"name": name, "weights": []}
        for value in ("1", "-1"):
            cell = self.unused_cell(item)
            if cell is not None:
                item["weights"].append({"levels": cell, "coefficient": value})
        self.items.append(item)
        self.show_contrasts(len(self.items) - 1)
        self.name_box.focus_set()
        self.name_box.selection_range(0, "end")

    def duplicate(self):
        source = self.contrast()
        if source is not None and len(self.items) < planned.MAX_CONTRASTS:
            item = deepcopy(source)
            item["name"] = self.unique_name(caption("copy_name", name=source["name"]))
            index = self.contrast_index + 1
            self.items.insert(index, item)
            self.show_contrasts(index)

    def move(self, offset):
        index = self.contrast_index
        if index is not None and 0 <= index + offset < len(self.items):
            self.items.insert(index + offset, self.items.pop(index))
            self.show_contrasts(index + offset)

    def remove_contrast(self):
        index = self.contrast_index
        if index is not None:
            del self.items[index]
            self.show_contrasts(min(index, len(self.items) - 1) if self.items else None)

    def unused_cell(self, item):
        factors = self.factors()
        used = {tuple(weight["levels"].get(name) for name in factors) for weight in item["weights"]}
        if factors:
            cell = next((values for values in product(*(self.levels.get(name, ()) for name in factors))
                         if values not in used), None)
            if cell is not None:
                return dict(zip(factors, cell))
        return None

    def show_weights(self, selected):
        factors = self.factors()
        columns = tuple(f"col{index}" for index in range(len(factors) + 1))
        if self.weight_table["columns"] != columns:
            self.weight_table.configure(columns=columns)
        for column, name in zip(columns, [*factors, caption("coefficient")]):
            self.weight_table.heading(column, text=name)
            self.weight_table.column(column, width=100, minwidth=62, stretch=False)
        self.weight_table.delete(*self.weight_table.get_children())
        item = self.contrast()
        weights = item["weights"] if item is not None else []
        for index, weight in enumerate(weights):
            self.weight_table.insert("", "end", iid=str(index), values=self.weight_values(weight))
        index = min(selected, len(weights) - 1) if weights and selected is not None else None
        if index is not None:
            self.weight_table.selection_set(str(index))
            self.weight_table.see(str(index))
        self.add_weight_button.configure(
            state="normal" if item is not None and len(weights) < planned.MAX_WEIGHTS else "disabled")
        self.show_weight(index)
        self.update_sum()
        self.keep_on_screen()

    def weight_values(self, weight):
        levels = [weight["levels"].get(name, "") for name in self.factors()]
        return [*levels, weight["coefficient"]]

    def show_weight(self, index):
        self.weight_index = None
        for widget in self.level_row.winfo_children():
            widget.destroy()
        self.level_boxes = {}
        self.coefficient_box.configure(state="normal" if index is not None else "disabled")
        self.remove_weight_button.configure(state="normal" if index is not None else "disabled")
        if index is None:
            self.coefficient.set("")
            return
        weight = self.contrast()["weights"][index]
        self.coefficient.set(weight["coefficient"])
        self.weight_index = index
        for column, name in enumerate(self.factors()):
            ttk.Label(self.level_row, text=name, width=14).grid(row=0, column=column, sticky="w", padx=(0, 4))
            box = ttk.Combobox(self.level_row, state="readonly", values=self.levels.get(name, ()), width=13)
            value = weight["levels"].get(name)
            if value is not None:
                box.set(value if value in self.levels.get(name, ()) else caption("level_absent", level=value))
            box.grid(row=1, column=column, sticky="ew", padx=(0, 4), pady=(0, 3))
            self.level_row.columnconfigure(column, weight=1)
            box.bind("<<ComboboxSelected>>", lambda _event, factor=name, picker=box: self.edit_level(factor, picker))
            self.level_boxes[name] = box
        self.bind_reveal(self.level_boxes.values())

    def pick_weight(self, _event):
        choice = self.weight_table.selection()
        if choice and int(choice[0]) != self.weight_index:
            self.show_weight(int(choice[0]))

    def edit_level(self, factor, box):
        weight = self.contrast()["weights"][self.weight_index]
        weight["levels"][factor] = box.get()
        self.weight_table.item(str(self.weight_index), values=self.weight_values(weight))

    def edit_coefficient(self, *_):
        if self.weight_index is not None:
            weight = self.contrast()["weights"][self.weight_index]
            weight["coefficient"] = self.coefficient.get()
            self.weight_table.item(str(self.weight_index), values=self.weight_values(weight))
            self.update_sum()

    def add_weight(self):
        item = self.contrast()
        if item is not None and len(item["weights"]) < planned.MAX_WEIGHTS:
            item["weights"].append({"levels": self.unused_cell(item) or {}, "coefficient": ""})
            self.show_weights(len(item["weights"]) - 1)
            self.coefficient_box.focus_set()

    def remove_weight(self):
        index = self.weight_index
        if index is not None:
            del self.contrast()["weights"][index]
            self.show_weights(index)

    def update_sum(self):
        item = self.contrast()
        text = ""
        if item is not None and item["weights"]:
            try:
                values = [parse_coefficient(weight["coefficient"]) for weight in item["weights"]]
                total = math.fsum(values)
                scale = math.fsum(abs(value) for value in values)
            except (ValueError, OverflowError):
                text = caption("sum.unknown")
            else:
                if math.isfinite(total) and abs(total) <= planned.SUM_TOLERANCE * scale:
                    text = caption("sum.ok")
                else:
                    text = caption("sum.bad", total=coefficient_text(total))
        self.total.configure(text=text)

    def values(self):
        factors = self.factors()
        contrasts = []
        for index, item in enumerate(self.items):
            weights = []
            for row, weight in enumerate(item["weights"]):
                try:
                    value = parse_coefficient(weight["coefficient"])
                except (ValueError, OverflowError):
                    message = planned.ERRORS["coefficient"].format(name=f"“{item['name']}”", row=row + 1)
                    raise ContrastError(CONTRASTS, message, contrast=index, weight=row, part="coefficient") from None
                weights.append({"levels": [weight["levels"].get(name) for name in factors], "coefficient": value})
            contrasts.append({"name": item["name"], "weights": weights})
        text = self.alpha.get()
        try:
            alpha = float(decimal_comma(text))
        except ValueError:
            alpha = text
        return {FACTORS: factors, CONTRASTS: contrasts, CORRECTION: self.correction.get(), ALPHA: alpha}

    def validate(self):
        try:
            options = self.values()
            request = planned.check_request(options, self.model)
            if request is not None:
                self.check(self.model)
                planned.check_levels(request[1], request[0], self.levels, self.model)
        except FieldError as error:
            self.show_error(error)
            return False
        self.result = options if options[CONTRASTS] else {}
        return True

    def show_error(self, error):
        self.problem.configure(text=planned.format_error(error) or str(error))
        target = {FACTORS: self.factor_list, CORRECTION: self.correction_box, ALPHA: self.alpha_box}.get(
            error.field, self.contrast_list)
        if isinstance(error, ContrastError) and error.contrast is not None:
            self.show_contrasts(error.contrast)
            target = self.name_box if error.part == "name" else self.weight_table
            if error.weight is not None:
                self.show_weights(error.weight)
                if error.part == "coefficient":
                    target = self.coefficient_box
                elif self.level_boxes:
                    target = next(iter(self.level_boxes.values()))
        self.keep_on_screen()
        self.scrolled.reveal(target)
        self.initial_focus = target
        target.focus_set()


class ContrastPanel(ttk.Frame):
    def __init__(self, parent, dialog, saved, context):
        super().__init__(parent)
        self.dialog, self.context = dialog, context
        self.state = {key: deepcopy(saved[key]) for key in planned.KEYS if key in saved}
        self.button = ttk.Button(self, text=caption("button"), command=self.open_editor)
        self.button.pack(anchor="w")
        self.summary = ttk.Label(self, wraplength=390, justify="left")
        self.summary.pack(anchor="w", pady=(3, 0))
        self.refresh()

    def focus_target(self):
        return self.button

    def refresh(self):
        state = clean_state(self.state)
        contrasts = state[CONTRASTS]
        text = caption("summary.none")
        if contrasts:
            alpha = state[ALPHA]
            level = 100 * (1 - alpha) if isinstance(alpha, (int, float)) and not isinstance(alpha, bool) else None
            correction = planned.CHOICE_KEYS.get(str(state[CORRECTION]))
            text = caption("summary.one" if len(contrasts) == 1 else "summary", count=len(contrasts),
                           factors=" × ".join(state[FACTORS]), level=coefficient_text(level) or "?",
                           correction=tr(correction) if correction else str(state[CORRECTION]))
        self.summary.configure(text=text)

    def open_editor(self):
        model, levels, check = self.context()
        try:
            editor = ContrastEditor(self.dialog, self.state, model, levels, check)
        finally:
            self.dialog.grab_set()
            self.button.focus_set()
        if editor.result is not None:
            self.state = editor.result
            self.refresh()

    def values(self):
        return deepcopy(self.state)
