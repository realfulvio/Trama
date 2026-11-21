"""Choose a worksheet type in the Standard desktop interface."""
from tkinter import BooleanVar, Canvas, Listbox, StringVar, simpledialog, ttk

from .data import MAX_COLUMNS
from .i18n import tr
from .table_templates import (BASE_KINDS, EXAMPLE_KEYS, EXAMPLES, FORMAT_KEYS, GROUPED_FORMATS, TEMPLATES,
                              XY_EXAMPLES, XY_FORMATS, Template, _blank_xy, format_label, table_frame, template_detail)


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
