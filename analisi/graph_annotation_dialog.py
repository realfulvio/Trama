"""Manage the text and arrow annotations belonging to one graph."""
from copy import deepcopy
import tkinter as tk
from tkinter import simpledialog, ttk

from .data import decimal_comma
from .graph_annotations import ALIGNMENTS, UNITS, on_axis_domain, validate_annotation
from .graph_dialog import pick_color
from .i18n import tr, translate_message


class AnnotationEditor(simpledialog.Dialog):
    def __init__(self, parent, axes, record=None):
        self.axes = axes
        self.record = record or {"text": "", "units": "axes", "position": [.08, .9],
                                 "size": 11, "color": "#174e78", "align": "left"}
        super().__init__(parent, tr("annotation.edit") if record is not None else tr("annotation.add"))

    def body(self, master):
        self.configure(background="#f4f6f8")
        master.configure(background="#f4f6f8")
        master.columnconfigure(1, weight=1)
        self.fields = {}
        ttk.Label(master, text=tr("annotation.text")).grid(row=0, column=0, sticky="nw", padx=(0, 8))
        self.text = tk.Text(master, width=36, height=4, wrap="word", padx=5, pady=4)
        self.text.grid(row=0, column=1, columnspan=3, sticky="ew")
        self.text.insert("1.0", self.record["text"])
        for row, (key, options) in enumerate((("units", UNITS), ("align", ALIGNMENTS)), 1):
            labels = {option: tr(f"annotation.option.{option}") for option in options}
            self.fields[key] = tk.StringVar(self, labels[self.record[key]])
            ttk.Label(master, text=tr(f"annotation.{key}")).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Combobox(master, textvariable=self.fields[key], values=tuple(labels.values()), state="readonly",
                         width=22).grid(row=row, column=1, columnspan=3, sticky="w", pady=3)
        self.position = self.coordinate_fields(master, 3, "annotation.position", self.record["position"])[0]
        self.arrow = tk.BooleanVar(self, "target" in self.record)
        ttk.Checkbutton(master, text=tr("annotation.arrow"), variable=self.arrow, command=self.show_arrow
                        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(5, 0))
        self.target, self.target_widgets = self.coordinate_fields(
            master, 5, "annotation.target", self.record.get("target", (.5, .5)))
        self.show_arrow()
        for row, key in ((6, "size"), (7, "color")):
            ttk.Label(master, text=tr(f"annotation.{key}")).grid(row=row, column=0, sticky="w", pady=3)
            self.fields[key] = tk.StringVar(self, str(self.record[key]))
            ttk.Entry(master, textvariable=self.fields[key], width=12).grid(row=row, column=1, sticky="w", pady=3)
        ttk.Button(master, text=tr("graph.field.pick"), command=lambda: pick_color(self, self.fields["color"])
                   ).grid(row=7, column=2, columnspan=2, sticky="w")
        self.problem = ttk.Label(master, wraplength=415, foreground="#b00020")
        self.problem.grid(row=8, column=0, columnspan=4, sticky="w", pady=(5, 0))
        return self.text

    def coordinate_fields(self, master, row, label, values):
        caption = ttk.Label(master, text=tr(label))
        caption.grid(row=row, column=0, sticky="w", pady=3)
        fields = tuple(tk.StringVar(self, f"{value:g}") for value in values)
        widgets = [caption]
        for column, field in enumerate(fields, 1):
            entry = ttk.Entry(master, textvariable=field, width=9)
            entry.grid(row=row, column=column, sticky="w", padx=(0, 5), pady=3)
            widgets.append(entry)
        return fields, widgets

    def show_arrow(self):
        for widget in self.target_widgets:
            widget.grid() if self.arrow.get() else widget.grid_remove()

    def buttonbox(self):
        row = ttk.Frame(self, padding=6)
        row.pack(fill="x")
        ttk.Button(row, text=tr("setup.cancel"), command=self.cancel).pack(side="right")
        ttk.Button(row, text=tr("language.ok"), style="Action.TButton", command=self.ok).pack(side="right", padx=6)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        def values(fields):
            return [float(decimal_comma(value.get())) for value in fields]

        def choice(key, options):
            return next(option for option in options if tr(f"annotation.option.{option}") == self.fields[key].get())

        try:
            record = {"text": self.text.get("1.0", "end-1c"), "units": choice("units", UNITS),
                      "position": values(self.position), "align": choice("align", ALIGNMENTS),
                      "size": float(decimal_comma(self.fields["size"].get())), "color": self.fields["color"].get().strip()}
            if self.arrow.get():
                record["target"] = values(self.target)
        except (StopIteration, ValueError):
            self.problem.configure(text=tr("annotation.invalid_fields"))
            return False
        try:
            validate_annotation(record)
            if not on_axis_domain(self.axes, record):
                raise ValueError(tr("annotation.axis_domain"))
        except ValueError as error:
            self.problem.configure(text=translate_message(error, "annotation.error."))
            return False
        self.result = record
        return True


class GraphAnnotationsDialog(simpledialog.Dialog):
    def __init__(self, parent, axes, records):
        self.axes = axes
        self.records = deepcopy(records)
        super().__init__(parent, tr("annotation.title"))

    def body(self, master):
        self.configure(background="#f4f6f8")
        master.configure(background="#f4f6f8")
        body = ttk.Frame(master, padding=8)
        body.pack(fill="both", expand=True)
        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("text", "position", "arrow"), show="headings", height=8,
                                 selectmode="browse")
        for key, label, width in (("text", "annotation.text", 280), ("position", "annotation.position", 110),
                                  ("arrow", "annotation.arrow_short", 55)):
            self.tree.heading(key, text=tr(label))
            self.tree.column(key, width=width, stretch=key == "text")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-Button-1>", lambda event: self.edit() if self.tree.identify_row(event.y) else None)
        self.tree.bind("<Delete>", lambda _event: self.remove())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.update_buttons())
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(6, 0))
        add_button = ttk.Button(buttons, text=tr("annotation.add"), command=self.add)
        self.edit_button = ttk.Button(buttons, text=tr("annotation.edit"), command=self.edit)
        self.remove_button = ttk.Button(buttons, text=tr("annotation.remove"), command=self.remove)
        for button in (add_button, self.edit_button, self.remove_button):
            button.pack(side="left", padx=(0, 6))
        self.fill()
        return self.tree

    def update_buttons(self):
        state = "disabled" if not self.tree.selection() else "!disabled"
        self.edit_button.state([state])
        self.remove_button.state([state])

    def fill(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        for i, record in enumerate(self.records):
            x, y = record["position"]
            self.tree.insert("", "end", iid=str(i),
                             values=(record["text"].strip().splitlines()[0][:120], f"{x:g}, {y:g}",
                                     "→" if "target" in record else ""))
        if selected is not None and self.records:
            iid = str(min(selected, len(self.records) - 1))
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
        self.update_buttons()

    def add(self):
        dialog = AnnotationEditor(self, self.axes)
        self.grab_set()
        if dialog.result is not None:
            self.records.append(dialog.result)
            self.fill(len(self.records) - 1)

    def edit(self):
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            dialog = AnnotationEditor(self, self.axes, self.records[index])
            self.grab_set()
            if dialog.result is not None:
                self.records[index] = dialog.result
                self.fill(index)

    def remove(self):
        selected = self.tree.selection()
        if selected:
            index = int(selected[0])
            del self.records[index]
            self.fill(index)

    def buttonbox(self):
        row = ttk.Frame(self, padding=6)
        row.pack(fill="x")
        ttk.Button(row, text=tr("setup.cancel"), command=self.cancel).pack(side="right")
        ttk.Button(row, text=tr("graph.format.apply"), style="Action.TButton", command=self.ok).pack(
            side="right", padx=6)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def apply(self):
        self.result = self.records
