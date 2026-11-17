"""Two-pane preview for importing selected rows and columns from a text file."""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import pandas as pd

from .text_import import DECIMAL_MARKS, DELIMITERS, ImportOptions, TextImport, read_text_file


class TextImportDialog(simpledialog.Dialog):
    def __init__(self, parent, path):
        self.path = path
        self.content = read_text_file(path)
        self.source = self.parsed_delimiter = None
        self.preview_job = None
        super().__init__(parent, "Import text data")

    def body(self, master):
        self.configure(background="#f4f6f8")
        master.configure(background="#f4f6f8")
        ttk.Label(master, text=self.path.name, style="DialogTitle.TLabel").pack(anchor="w", padx=8, pady=(5, 8))
        panes = ttk.Frame(master, padding=(8, 0, 8, 3))
        panes.pack(fill="both", expand=True)
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(0, weight=1)
        settings = ttk.Frame(panes)
        settings.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        self.separator = tk.StringVar(self, "Automatic")
        self.decimal = tk.StringVar(self, "Automatic")
        self.header = tk.BooleanVar(self, True)
        self.mark_excluded = tk.BooleanVar(self, False)
        self.missing_code = tk.StringVar(self)
        self.bounds = {}
        source = ttk.LabelFrame(settings, text="Source", padding=8)
        source.pack(fill="x", pady=(0, 6))
        for row, (label, variable, values) in enumerate((
                ("Delimiter", self.separator, tuple(DELIMITERS)), ("Decimals", self.decimal, tuple(DECIMAL_MARKS)))):
            ttk.Label(source, text=label).grid(row=row, column=0, sticky="w", padx=(0, 9), pady=2)
            ttk.Combobox(source, textvariable=variable, values=values, width=12, state="readonly").grid(
                row=row, column=1, sticky="ew", pady=2)
        ttk.Checkbutton(source, text="First record is a header", variable=self.header).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        for axis in ("rows", "columns"):
            group = ttk.LabelFrame(settings, text=axis.capitalize(), padding=8)
            group.pack(fill="x", pady=(0, 6))
            for row, (field, label, default) in enumerate((
                    (f"first_{axis[:-1]}", "First", "1"),
                    (f"last_{axis[:-1]}", "Last (blank = all)", ""),
                    (f"skip_{axis}", "Skip after each", "0"))):
                ttk.Label(group, text=label).grid(row=row, column=0, sticky="w", padx=(0, 9), pady=1)
                var = self.bounds[field] = tk.StringVar(self, default)
                ttk.Entry(group, width=8, justify="right", textvariable=var).grid(row=row, column=1, sticky="e", pady=1)

        values = ttk.LabelFrame(settings, text="Values", padding=8)
        values.pack(fill="x")
        ttk.Label(values, text="Missing code").grid(row=0, column=0, sticky="w")
        ttk.Entry(values, width=10, textvariable=self.missing_code).grid(row=0, column=1, sticky="e")
        ttk.Checkbutton(values, text="Trailing * marks exclusion", variable=self.mark_excluded).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))

        preview = ttk.LabelFrame(panes, text="Filtered preview", padding=8)
        preview.grid(row=0, column=1, sticky="nsew")
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(1, weight=1)
        self.summary = ttk.Label(preview, wraplength=460)
        self.summary.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        self.tree = ttk.Treeview(preview, show="headings", height=11, selectmode="none")
        self.tree.grid(row=1, column=0, sticky="nsew")
        xbar = ttk.Scrollbar(preview, orient="horizontal", command=self.tree.xview)
        xbar.grid(row=2, column=0, sticky="ew")
        ybar = ttk.Scrollbar(preview, orient="vertical", command=self.tree.yview)
        ybar.grid(row=1, column=1, sticky="ns")
        self.tree.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.tree.tag_configure("alternate", background="#f0f5fa")
        for variable in (self.separator, self.decimal, self.header, self.mark_excluded,
                         self.missing_code, *self.bounds.values()):
            variable.trace_add("write", self.schedule_preview)
        self.refresh_preview()

    def buttonbox(self):
        bar = ttk.Frame(self, padding=(12, 0, 12, 8))
        ttk.Button(bar, text="Import", style="Action.TButton", command=self.ok).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Cancel", command=self.cancel).pack(side="right")
        bar.pack(fill="x")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def inputs(self):
        delimiter = self.separator.get()
        if delimiter != self.parsed_delimiter:
            self.source = TextImport.parse(self.content, self.path.suffix.lower(), delimiter)
            self.parsed_delimiter = delimiter
        bounds = {}
        for field, var in self.bounds.items():
            text = var.get().strip()
            try:
                bounds[field] = None if not text and field.startswith("last_") else int(text)
            except ValueError as error:
                raise ValueError(f"Enter a whole number for {field.replace('_', ' ')}.") from error
        return ImportOptions(header=self.header.get(), decimal=self.decimal.get(),
                             missing_code=self.missing_code.get(), mark_excluded=self.mark_excluded.get(), **bounds)

    def schedule_preview(self, *_):
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
        self.preview_job = self.after(160, self.refresh_preview)

    def refresh_preview(self):
        self.preview_job = None
        self.tree.delete(*self.tree.get_children())
        try:
            options = self.inputs()
            selection = self.source.plan(options)
            frame = self.source.table(options, limit=(12, 5))
        except ValueError as error:
            self.tree["columns"] = ()
            self.summary.configure(text=str(error), foreground="#923b26")
            return
        columns = tuple(str(index) for index in range(len(frame.columns)))
        self.tree["columns"] = columns
        for key, name in zip(columns, frame.columns, strict=True):
            self.tree.heading(key, text=name, anchor="w")
            self.tree.column(key, width=94, minwidth=70, stretch=False)
        excluded = set(frame.attrs.get("excluded", []))
        for row, values in enumerate(frame.itertuples(index=False, name=None)):
            shown = ["" if pd.isna(value) else ("* " if (row, col) in excluded else "") + str(value)
                     for col, value in enumerate(values)]
            self.tree.insert("", "end", values=shown, tags=("alternate",) if row % 2 else ())
        suffix = f"  ·  Showing {len(frame):,} × {len(columns):,}" if frame.shape != (
            len(selection.rows), len(selection.columns)) else ""
        self.summary.configure(text=f"{len(selection.rows):,} rows × {len(selection.columns):,} columns{suffix}",
                               foreground="#486075")

    def validate(self):
        try:
            options = self.inputs()
            self.result = self.source.table(options)
        except ValueError as error:
            messagebox.showerror("Check import settings", str(error), parent=self)
            return False
        return True

    def destroy(self):
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
            self.preview_job = None
        super().destroy()
