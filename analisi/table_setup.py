"""Choose a worksheet type before entering or importing data."""
from dataclasses import dataclass, replace
from tkinter import BooleanVar, Canvas, Listbox, StringVar, simpledialog, ttk

import pandas as pd

from .data import MAX_COLUMNS
from .i18n import tr


@dataclass(frozen=True)
class Template:
    name: str
    kind: str
    detail: str
    columns: tuple
    rows: tuple


TEMPLATES = (
    Template("XY", "xy", "Pair an X value with one or more Y series. Use this for curves and regression.",
             ("X", "Control", "Treatment"), ((0.1, 2.4, 2.1), (1, 4.1, 5.3), (10, 8.2, 11.4), (100, 9.3, 13.2))),
    Template("Column", "column", "Place each group in its own column. Use this for comparisons and distributions.",
             ("Control", "Treatment"), ((12, 19), (15, 24), (11, 18), (16, 26), (14, 21))),
    Template("Grouped", "grouped", "Organize observations by row and column groups, with separate replicate columns.",
             ("Row title", "Control [1]", "Control [2]", "Treatment [1]", "Treatment [2]"),
             (("Week 1", 4.1, 4.4, 5.6, 5.9), ("Week 2", 4.7, 4.9, 7.1, 7.6), ("Week 3", 5.2, 5.5, 8.2, 8.7))),
    Template("Contingency", "contingency", "Enter whole counts for each combination of group and outcome.",
             ("Row title", "Event", "No event"), (("Control", 12, 28), ("Treatment", 5, 35))),
    Template("Survival", "survival", "Record a time, event indicator and group for each subject.",
             ("Time", "Event", "Group"), ((6, 1, "Control"), (8, 1, "Control"), (11, 0, "Control"),
                                          (9, 1, "Treatment"), (12, 0, "Treatment"), (15, 1, "Treatment"))),
    Template("Parts of whole", "parts_of_whole", "Enter one value per category to plot each part as a share of the total.",
             ("Row title", "Count"), (("Category A", 22), ("Category B", 16), ("Category C", 12), ("Category D", 8))),
    Template("Multiple variables", "multivariable", "Record each observation as a row with numeric or categorical variables.",
             ("Subject", "Measurement", "Group"), (("S01", 12.4, "Control"), ("S02", 14.1, "Control"),
                                                   ("S03", 18.3, "Treatment"), ("S04", 20.2, "Treatment"))),
    Template("Nested", "nested", "Give each independent subject or unit its own subcolumn and stack its repeated measurements.",
             ("Control [1]", "Control [2]", "Control [3]", "Treatment [1]", "Treatment [2]", "Treatment [3]"),
             ((4.1, 5.4, 6.0, 7.8, 8.3, 9.1), (3.8, 5.1, 5.8, 7.2, 8.6, 9.5),
              (4.4, 5.7, 6.3, 7.6, 8.1, 9.2), (None, 5.4, None, 7.4, None, 9.3))),
)

XY_FORMATS = {
    "A single Y value for each X": TEMPLATES[0],
    "Replicates in side-by-side subcolumns": Template(
        "XY replicates", "XY with replicates", TEMPLATES[0].detail,
        ("X", "Control [1]", "Control [2]", "Treatment [1]", "Treatment [2]"),
        ((0.1, 2.4, 2.6, 2.1, 2.7), (1, 4.1, 4.5, 5.3, 5.8), (10, 8.2, 8.7, 11.4, 10.8),
         (100, 9.3, 8.9, 13.2, 13.6)),
    ),
    "Precalculated mean, SD and N": Template(
        "XY mean and SD", "XY with precomputed error", TEMPLATES[0].detail,
        ("X", "Control [Mean]", "Control [SD]", "Control [N]", "Treatment [Mean]", "Treatment [SD]", "Treatment [N]"),
        ((0.1, 2.5, 0.2, 3, 2.4, 0.3, 3), (1, 4.3, 0.4, 3, 5.6, 0.5, 3),
         (10, 8.5, 0.5, 3, 11.1, 0.6, 3), (100, 9.1, 0.4, 3, 13.4, 0.4, 3)),
    ),
}

XY_EXAMPLES = (
    ("Curves and regression", "Dose–response with two data sets", "A single Y value for each X"),
    ("Replicates and error bars", "Measure duplicate observations", "Replicates in side-by-side subcolumns"),
    ("Replicates and error bars", "Enter means, SD and sample sizes", "Precalculated mean, SD and N"),
)

def _grouped_summary(name, fields, rows):
    """Reuse the Grouped worksheet with one subcolumn for each entered statistic."""
    columns = ("Row title", *(f"{group} [{field}]" for group in ("Control", "Treated") for field in fields))
    return Template(name, "grouped", TEMPLATES[2].detail, columns, rows)


GROUPED_FORMATS = {
    "Replicates in side-by-side subcolumns": TEMPLATES[2],
    "Mean, SD and N": _grouped_summary("Grouped mean, SD and N", ("Mean", "SD", "N"), (
        ("Week 1", 4.3, .2, 4, 5.8, .3, 4), ("Week 2", 4.8, .3, 4, 7.4, .4, 4), ("Week 3", 5.4, .2, 4, 8.5, .4, 4))),
    "Mean and SEM": _grouped_summary("Grouped mean and SEM", ("Mean", "SEM"), (
        ("Week 1", 4.3, .1, 5.8, .15), ("Week 2", 4.8, .15, 7.4, .2), ("Week 3", 5.4, .1, 8.5, .2))),
    "Mean with minus and plus distances": _grouped_summary(
        "Grouped asymmetric distances", ("Mean", "Minus", "Plus"), (
            ("Week 1", 4.3, .2, .4, 5.8, .3, .5), ("Week 2", 4.8, .3, .2, 7.4, .4, .6),
            ("Week 3", 5.4, .2, .3, 8.5, .5, .4))),
    "Mean with lower and upper limits": _grouped_summary(
        "Grouped asymmetric limits", ("Mean", "Lower", "Upper"), (
            ("Week 1", 4.3, 4.1, 4.7, 5.8, 5.5, 6.3), ("Week 2", 4.8, 4.5, 5., 7.4, 7., 8.),
            ("Week 3", 5.4, 5.2, 5.7, 8.5, 8., 8.9))),
}

# Display keys for the canonical format and example names; choices keep the English names as codes.
FORMAT_KEYS = {
    "A single Y value for each X": "format.xy_single", "Replicates in side-by-side subcolumns": "format.replicates",
    "Precalculated mean, SD and N": "format.xy_mean_sd_n", "Mean, SD and N": "format.mean_sd_n",
    "Mean and SEM": "format.mean_sem", "Mean with minus and plus distances": "format.mean_distances",
    "Mean with lower and upper limits": "format.mean_limits",
}
EXAMPLE_KEYS = {
    "Curves and regression": "example.curves", "Replicates and error bars": "example.replicates",
    "Dose–response with two data sets": "example.dose_response",
    "Measure duplicate observations": "example.duplicates", "Enter means, SD and sample sizes": "example.means",
}
BASE_KINDS = {template.kind for template in TEMPLATES}


def format_label(code):
    """Visible name of a table format; code is the canonical kind or format name."""
    if code in BASE_KINDS:
        return tr(f"table.{code}")
    return tr(FORMAT_KEYS[code]) if code in FORMAT_KEYS else code


def template_detail(template):
    kind = template.kind if template.kind in BASE_KINDS else "xy"
    return tr(f"table_detail.{kind}")


EXAMPLES = {
    "column": "Compare a control and a treated group",
    "grouped": "Repeated measurements by week",
    "contingency": "Treatment and event counts",
    "survival": "Time to event in two groups",
    "parts_of_whole": "Composition of four categories",
    "multivariable": "Subject, measurement and group",
    "nested": "Repeated measurements within independent units",
}


def _blank_xy(template, datasets, replicates, row_titles):
    if template.kind == "XY with replicates":
        suffixes = tuple(f" [{index}]" for index in range(1, replicates + 1))
    elif template.kind == "XY with precomputed error":
        suffixes = (" [Mean]", " [SD]", " [N]")
    else:
        suffixes = ("",)
    groups = ("Control", "Treatment", *(f"Series {index}" for index in range(3, datasets + 1)))
    values = ("X", *(f"{group}{suffix}" for group in groups[:datasets] for suffix in suffixes))
    return replace(template, columns=(("Row title",) if row_titles else ()) + values,
                   rows=((("",) if row_titles else ()) + (0,) * len(values),))


def table_frame(template, sample):
    if sample:
        frame = pd.DataFrame(template.rows, columns=template.columns)
    else:
        frame = pd.DataFrame({
            name: pd.Series(index=range(20), dtype="Float64" if isinstance(value, (int, float)) else "string")
            for name, value in zip(template.columns, template.rows[0], strict=True)
        })
    frame.attrs["table_format"] = template.kind
    return frame


class TableSetup(ttk.Frame):
    def __init__(self, parent, create=None, open_project=None, *, create_info=None, brand=None, version=""):
        super().__init__(parent)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        rail = ttk.Frame(self, style="SetupRail.TFrame", padding=(0, 14))
        rail.grid(row=0, column=0, sticky="nsew")
        ttk.Label(rail, text="Trama", image=brand or "", compound="left",
                  style="SetupBrand.TLabel").pack(anchor="w", padx=11)
        if version:
            ttk.Label(rail, text=tr("setup.version", version=version), style="SetupVersion.TLabel").pack(anchor="w", padx=14)
        ttk.Label(rail, text=tr("setup.new_data_table"), style="SetupRail.TLabel").pack(anchor="w", padx=12, pady=(23, 4))
        self.types = Listbox(rail, width=20, height=len(TEMPLATES), borderwidth=0, highlightthickness=0,
                             exportselection=False, font=("Segoe UI", 10), background="#173546",
                             foreground="#f2f7fa", selectbackground="#f7fafc", selectforeground="#183e5a",
                             activestyle="none")
        self.types.pack(fill="x")
        for template in TEMPLATES:
            self.types.insert("end", f"   {format_label(template.kind)}")
        self.types.selection_set(0)
        self.types.bind("<<ListboxSelect>>", self.refresh)
        if open_project is not None:
            ttk.Label(rail, text=tr("setup.existing_project"), style="SetupRail.TLabel").pack(anchor="w", padx=12, pady=(24, 4))
            ttk.Button(rail, text=tr("setup.open_file"), style="SetupLink.TButton", command=open_project).pack(fill="x", padx=9)
        if create_info is not None:
            ttk.Button(rail, text=tr("setup.new_project_info"), style="SetupLink.TButton",
                       command=create_info).pack(fill="x", padx=9, pady=(5, 0))

        detail = ttk.Frame(self, style="SetupBody.TFrame", padding=(16, 14, 15, 16))
        detail.grid(row=0, column=1, sticky="nsew")
        self.heading = ttk.Label(detail, style="SetupTitle.TLabel")
        self.heading.pack(anchor="w")
        self.description = ttk.Label(detail, style="SetupBody.TLabel", wraplength=490, justify="left")
        self.description.pack(anchor="w", pady=(4, 13))
        examples = self.previews = ttk.Frame(detail, style="SetupBody.TFrame")
        examples.pack(anchor="w")
        ttk.Label(examples, text=tr("setup.worksheet_preview"), style="SetupCaption.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(examples, text=tr("setup.graph_example"), style="SetupCaption.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        preview_panel = ttk.Frame(examples, width=384, height=112)
        preview_panel.grid(row=1, column=0, sticky="n")
        preview_panel.pack_propagate(False)
        self.preview = ttk.Treeview(preview_panel, show="headings", height=4, selectmode="none", style="Setup.Treeview")
        self.preview.pack(fill="both", expand=True)
        preview_panel.configure(height=max(112, self.preview.winfo_reqheight()))
        self.chart = Canvas(examples, width=126, height=112, background="#ffffff", highlightthickness=0)
        self.chart.grid(row=1, column=1, sticky="n", padx=(12, 0))
        self.section(detail, tr("setup.data_table")).pack(fill="x", pady=(16, 4))
        self.mode = BooleanVar(self, False)
        for title, example in ((tr("setup.enter_data"), False), (tr("setup.sample_data"), True)):
            ttk.Radiobutton(detail, text=title, variable=self.mode, value=example, command=self.refresh,
                            style="Setup.TRadiobutton").pack(anchor="w", padx=10, pady=2)
        self.options = ttk.Frame(detail, style="SetupBody.TFrame")
        self.options.pack(fill="x", pady=(13, 0))
        self.option_label = ttk.Label(self.options, style="SetupCaption.TLabel")
        self.option_label.pack(anchor="w", pady=(0, 5))
        self.example_label = ttk.Label(self.options, style="SetupBody.TLabel", padding=(8, 4))
        self.example_list = ttk.Treeview(self.options, show="tree", height=5, selectmode="browse",
                                         style="Setup.Treeview")
        self.example_list.column("#0", width=372, stretch=False)
        self.example_list.bind("<<TreeviewSelect>>", self.choose_example)
        self.xy_format = StringVar(self, next(iter(XY_FORMATS)))
        self.xy_controls = ttk.Frame(self.options, style="SetupBody.TFrame")
        ttk.Label(self.xy_controls, text=tr("setup.x_numbers"), style="SetupBody.TLabel").pack(anchor="w", pady=(0, 4))
        for text in XY_FORMATS:
            ttk.Radiobutton(self.xy_controls, text=format_label(text), variable=self.xy_format, value=text,
                            command=self.refresh, style="Setup.TRadiobutton").pack(anchor="w", padx=10, pady=2)
        self.preview_note = ttk.Label(detail, style="SetupBody.TLabel")
        shape = ttk.Frame(self.xy_controls, style="SetupBody.TFrame")
        shape.pack(anchor="w", pady=(7, 0))
        self.dataset_count = StringVar(self, "2")
        self.replicate_count = StringVar(self, "2")
        self.row_titles = BooleanVar(self, True)
        ttk.Label(shape, text=tr("setup.data_sets"), style="SetupBody.TLabel").pack(side="left")
        datasets = ttk.Combobox(shape, textvariable=self.dataset_count, state="readonly", width=4,
                                values=tuple(range(1, 17)))
        datasets.pack(side="left", padx=(5, 14))
        datasets.bind("<<ComboboxSelected>>", self.refresh)
        ttk.Label(shape, text=tr("setup.replicates"), style="SetupBody.TLabel").pack(side="left")
        self.replicate_input = ttk.Combobox(shape, textvariable=self.replicate_count, state="disabled", width=5)
        self.replicate_input.pack(side="left", padx=(5, 14))
        self.replicate_input.bind("<<ComboboxSelected>>", self.refresh)
        ttk.Checkbutton(shape, text=tr("setup.row_titles"), variable=self.row_titles, command=self.refresh).pack(side="left")
        self.grouped_format = StringVar(self, next(iter(GROUPED_FORMATS)))
        self.grouped_controls = ttk.Frame(self.options, style="SetupBody.TFrame")
        for text in GROUPED_FORMATS:
            ttk.Radiobutton(self.grouped_controls, text=format_label(text), variable=self.grouped_format, value=text,
                            command=self.refresh, style="Setup.TRadiobutton").pack(anchor="w", padx=10, pady=2)
        if create is not None:
            footer = ttk.Frame(self, style="Ribbon.TFrame", padding=(10, 8))
            footer.grid(row=1, column=0, columnspan=2, sticky="ew")
            ttk.Button(footer, text=tr("setup.create"), width=12, style="Action.TButton",
                       command=lambda: create(*self.selection())).pack(side="right")
        self.refresh()

    @staticmethod
    def section(parent, label):
        row = ttk.Frame(parent, style="SetupBody.TFrame")
        ttk.Label(row, text=label, style="SetupCaption.TLabel").pack(side="left", padx=(0, 8))
        ttk.Separator(row).pack(side="left", expand=True, fill="x")
        return row

    def selection(self):
        selected = self.types.curselection()
        template = TEMPLATES[selected[0] if selected else 0]
        sample = self.mode.get()
        if template.kind == "xy":
            template = XY_FORMATS[self.xy_format.get()]
            if not sample:
                datasets, titles = int(self.dataset_count.get()), self.row_titles.get()
                maximum = min(256, (MAX_COLUMNS - 1 - int(titles)) // datasets)
                replicates = min(int(self.replicate_count.get()), maximum)
                self.replicate_input.configure(values=tuple(range(2, maximum + 1)),
                                               state="readonly" if template.kind == "XY with replicates" else "disabled")
                if template.kind == "XY with replicates":
                    self.replicate_count.set(str(replicates))
                template = _blank_xy(template, datasets, replicates, titles)
        elif template.kind == "grouped":
            template = GROUPED_FORMATS[self.grouped_format.get()]
        return template, sample

    def choose_example(self, _event=None):
        if not self.mode.get():
            return
        selected = self.example_list.selection()
        if not selected or not selected[0].startswith("example:"):
            return
        index = int(selected[0].split(":")[1])
        key = XY_EXAMPLES[index][2]
        if key != self.xy_format.get():
            self.xy_format.set(key)
            self.refresh()

    def show_examples(self, template, is_xy):
        tree = self.example_list
        tree.delete(*tree.get_children())
        if is_xy:
            sections = {}
            for index, (group, name, key) in enumerate(XY_EXAMPLES):
                if group not in sections:
                    sections[group] = tree.insert("", "end", text=tr(EXAMPLE_KEYS[group]), open=True)
                node = tree.insert(sections[group], "end", iid=f"example:{index}", text=tr(EXAMPLE_KEYS[name]))
                if key == self.xy_format.get():
                    tree.selection_set(node)
                    tree.focus(node)
        else:
            node = tree.insert("", "end", text=tr(f"example.{template.kind}"))
            tree.selection_set(node)
        tree.pack(anchor="w", pady=(0, 3))

    def refresh(self, _event=None):
        template, sample = self.selection()
        is_xy = template.kind.casefold().startswith("xy")
        base = "xy" if is_xy else template.kind if template.kind in BASE_KINDS else "grouped"
        self.heading.configure(text=tr(f"setup.heading.{base}"))
        self.description.configure(text=template_detail(template))
        self.preview.delete(*self.preview.get_children())
        preview_columns = template.columns[:8]
        keys = [f"c{i}" for i in range(len(preview_columns))]
        self.preview.configure(columns=keys)
        if len(template.columns) > len(preview_columns):
            self.preview_note.configure(text=tr("setup.preview_note", shown=len(preview_columns),
                                                     total=len(template.columns)))
            self.preview_note.pack(after=self.previews, anchor="w", pady=(4, 0))
        else:
            self.preview_note.pack_forget()
        for key, label in zip(keys, preview_columns, strict=True):
            if len(keys) > 5 and label.endswith("]"):
                group, subcolumn = label[:-1].split(" [", 1)
                label = f"{group.rsplit(' ', 1)[-1] if group.startswith('Series ') else group[0]} {subcolumn}"
            elif len(keys) > 5 and label == "Row title":
                label = "Title"
            self.preview.heading(key, text=label, anchor="center")
            self.preview.column(key, width=380 // len(keys), minwidth=40, anchor="center", stretch=False)
        for row in range(4):
            values = template.rows[row][:len(keys)] if sample and row < len(template.rows) else ("",) * len(keys)
            self.preview.insert("", "end", values=tuple("" if value is None else value for value in values))
        self.xy_controls.pack_forget()
        self.grouped_controls.pack_forget()
        self.example_label.pack_forget()
        self.example_list.pack_forget()
        if sample:
            self.option_label.configure(text=tr("setup.select_sample"))
            self.show_examples(template, is_xy)
        else:
            self.option_label.configure(text=tr("setup.options") if is_xy else tr("setup.structure"))
            if is_xy:
                self.xy_controls.pack(anchor="w")
            elif template.kind == "grouped":
                self.grouped_controls.pack(anchor="w")
            else:
                self.example_label.configure(text="  ·  ".join(template.columns))
                self.example_label.pack(anchor="w")
        self.draw_chart(template.kind.casefold())

    def draw_chart(self, kind):
        canvas = self.chart
        canvas.delete("all")
        first, second = "#2a659b", "#198276"
        if kind == "parts_of_whole":
            start = 90
            for fraction, color in ((.38, first), (.28, second), (.20, "#c47653"), (.14, "#8c6da0")):
                extent = -360 * fraction
                canvas.create_arc(26, 14, 106, 94, start=start, extent=extent, fill=color, outline="white")
                start += extent
            canvas.create_oval(47, 35, 85, 73, fill="white", outline="white")
            return
        canvas.create_line(19, 15, 19, 91, 112, 91, fill="#64778b")
        if kind in {"column", "grouped", "contingency", "nested"}:
            for x, height, color in ((28, 33, first), (45, 46, second), (71, 52, first), (88, 62, second)):
                canvas.create_rectangle(x, 91 - height, x + 12, 91, fill=color, outline="")
        else:
            coordinates = ((28, 73, 49, 58, 72, 49, 103, 37), (28, 77, 49, 63, 72, 39, 103, 24))
            if kind == "survival":
                coordinates = ((22, 22, 39, 22, 39, 44, 60, 44, 60, 57, 99, 57),
                               (22, 22, 52, 22, 52, 33, 80, 33, 80, 45, 106, 45))
            for points, color in zip(coordinates, (first, second), strict=True):
                if kind == "survival":
                    canvas.create_line(points, fill=color, width=2)
                if kind != "survival":
                    for x, y in zip(points[::2], points[1::2], strict=True):
                        if kind.startswith("xy with "):
                            canvas.create_line(x, y - 5, x, y + 5, fill=color)
                            canvas.create_line(x - 3, y - 5, x + 3, y - 5, fill=color)
                            canvas.create_line(x - 3, y + 5, x + 3, y + 5, fill=color)
                        canvas.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill=color, outline="")


class NewTableDialog(simpledialog.Dialog):
    def body(self, master):
        self.setup = TableSetup(master)
        self.setup.pack(fill="both", expand=True)
        return self.setup.types

    def buttonbox(self):
        bar = ttk.Frame(self, padding=(8, 5))
        ttk.Button(bar, text=tr("setup.create"), width=12, style="Action.TButton", command=self.ok).pack(side="right", padx=4)
        ttk.Button(bar, text=tr("setup.cancel"), command=self.cancel).pack(side="right")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        bar.pack(fill="x")

    def apply(self):
        self.result = self.setup.selection()
