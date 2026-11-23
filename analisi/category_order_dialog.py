"""Reorder the selected worksheet's category levels in the classic Tk interface."""

import tkinter as tk
from tkinter import simpledialog, ttk

from .i18n import tr


class CategoryOrderDialog(simpledialog.Dialog):
    def __init__(self, parent, column, draft):
        self.column = column
        self.draft = draft
        super().__init__(parent, tr("command.category_order").removesuffix("…"))

    def body(self, master):
        master.columnconfigure(0, weight=1)
        ttk.Label(master, text=self.column, wraplength=400, justify='left').grid(row=0, column=0, columnspan=3, sticky="w", padx=8)
        ttk.Label(master, text=tr("worksheet_order.note"), wraplength=400, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))
        self.levels = tk.Listbox(master, width=35, height=8, exportselection=False)
        self.levels.grid(row=2, column=0, rowspan=3, sticky="nsew", padx=(8, 0))
        scroll = ttk.Scrollbar(master, orient="vertical", command=self.levels.yview)
        scroll.grid(row=2, column=1, rowspan=3, sticky="ns")
        horizontal = ttk.Scrollbar(master, orient="horizontal", command=self.levels.xview)
        horizontal.grid(row=5, column=0, sticky="ew", padx=(8, 0))
        self.levels.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.up = ttk.Button(master, text=tr("pdf.up"), command=lambda: self.move(-1))
        self.down = ttk.Button(master, text=tr("pdf.down"), command=lambda: self.move(1))
        for row, button in enumerate((self.up, self.down), 2):
            button.grid(row=row, column=2, sticky="ew", padx=8)
        self.reset = ttk.Button(master, text=tr("worksheet_order.reset"), command=self.restore)
        self.reset.grid(row=4, column=2, sticky="ew", padx=8)
        self.levels.bind("<<ListboxSelect>>", lambda _event: self.sync_buttons())
        for sequence, step in (("<Alt-Up>", -1), ("<Alt-Down>", 1)):
            self.levels.bind(sequence, lambda _event, step=step: self.move(step) or "break")
        self.render()
        return self.levels

    def buttonbox(self):
        bar = ttk.Frame(self, padding=8)
        ttk.Button(bar, text=tr("graph.inspector.apply"), command=self.ok, default="active").pack(
            side="left", padx=4)
        ttk.Button(bar, text=tr("setup.cancel"), command=self.cancel).pack(side="left", padx=4)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        bar.pack()

    def render(self, row=0):
        self.levels.delete(0, "end")
        for _, name in self.draft.levels:
            self.levels.insert("end", name)
        if self.draft.levels:
            self.levels.selection_set(row)
            self.levels.activate(row)
            self.levels.see(row)
        self.sync_buttons()

    def sync_buttons(self):
        row = next(iter(self.levels.curselection()), -1)
        self.up.state(["!disabled" if row > 0 else "disabled"])
        self.down.state(["!disabled" if 0 <= row < len(self.draft.levels) - 1 else "disabled"])

    def move(self, step):
        row = next(iter(self.levels.curselection()), -1)
        self.render(self.draft.move(row, step))

    def restore(self):
        self.draft.restore_automatic()
        self.render()

    def apply(self):
        self.result = self.draft.result()
