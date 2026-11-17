"""File → Export multiple sheets to PDF…: choose native graphs and layouts, their order and the page width."""
from dataclasses import dataclass
from tkinter import simpledialog, ttk
import tkinter as tk

from . import figure_export as fe
from .data import decimal_comma
from .i18n import tr

ERROR = "#b00020"
MUTED = "#46576b"


@dataclass(frozen=True)
class BundleEntry:
    """One exportable sheet. ``ref`` is its identity (two sheets may share a title)."""
    ref: tuple
    kind: str  # "Graph" or "Layout"
    name: str
    size: tuple
    raster: bool = False

    @property
    def label(self):
        kind = tr("pdf.graph") if self.kind == "Graph" else tr("pdf.layout")
        return f"{kind} · {self.name}"


class PdfBundleDialog(simpledialog.Dialog):
    """``entries`` are the ready sheets in project order; ``excluded`` are notes on sheets left out.

    The result is ``{"refs": [...], "settings": {...}}`` in output order, or None when cancelled.
    """

    def __init__(self, parent, entries, excluded=()):
        self.entries, self.excluded = list(entries), list(excluded)
        self.order = list(range(len(self.entries)))
        # Sheets with the same title stay distinct: the second one is shown as “… (2)” and so on.
        counts, self.labels = {}, []
        for entry in self.entries:
            counts[entry.label] = counts.get(entry.label, 0) + 1
            self.labels.append(entry.label if counts[entry.label] == 1 else f"{entry.label} ({counts[entry.label]})")
        self.plans = None
        super().__init__(parent, tr("pdf.title"))

    def body(self, master):
        self.configure(background="#f4f6f8")
        master.configure(background="#f4f6f8")
        body = ttk.Frame(master, padding=(10, 8, 10, 4))
        body.pack(fill="both", expand=True)
        sheets = ttk.LabelFrame(body, text=tr("pdf.sheets"), padding=(10, 6))
        sheets.pack(fill="both", expand=True)
        sheets.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(sheets, selectmode="extended", height=min(12, max(5, len(self.entries))),
                                  width=46, exportselection=False, activestyle="dotbox")
        self.listbox.grid(row=0, column=0, rowspan=3, sticky="nsew")
        scroll = ttk.Scrollbar(sheets, orient="vertical", command=self.listbox.yview)
        scroll.grid(row=0, column=1, rowspan=3, sticky="ns")
        self.listbox.configure(yscrollcommand=scroll.set)
        self.up = ttk.Button(sheets, text=tr("pdf.up"), command=lambda: self.move(-1))
        self.up.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self.down = ttk.Button(sheets, text=tr("pdf.down"), command=lambda: self.move(1))
        self.down.grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=4)
        for sequence, step in (("<Alt-Up>", -1), ("<Alt-Down>", 1)):
            self.listbox.bind(sequence, lambda _event, step=step: self.move(step) or "break")
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self.refresh())
        self.fill()
        if self.entries:
            self.listbox.selection_set(0)
            self.listbox.activate(0)

        page = ttk.LabelFrame(body, text=tr("pdf.pages"), padding=(10, 6))
        page.pack(fill="x", pady=(8, 0))
        self.width = tk.StringVar()
        self.transparent = tk.BooleanVar(value=False)
        ttk.Label(page, text=tr("pdf.width")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.width_entry = ttk.Entry(page, width=16, textvariable=self.width)
        self.width_entry.grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(page, text=tr("pdf.transparent"), variable=self.transparent).grid(
            row=1, column=1, sticky="w", pady=2)
        ttk.Label(page, text=tr("pdf.width_hint"),
                  foreground=MUTED, wraplength=400, justify="left").grid(row=2, column=0, columnspan=2, sticky="w")
        for variable in (self.width, self.transparent):
            variable.trace_add("write", lambda *_: self.refresh())

        self.summary = ttk.Label(body, wraplength=430, justify="left")
        self.summary.pack(anchor="w", pady=(8, 0))
        self.note = ttk.Label(body, wraplength=430, justify="left", foreground=MUTED)
        self.note.pack(anchor="w", pady=(4, 0))
        self.refresh()
        return self.listbox

    def buttonbox(self):
        bar = ttk.Frame(self, padding=5)
        ttk.Button(bar, text=tr("language.ok"), width=10, command=self.ok, default="active").pack(side="left", padx=5)
        ttk.Button(bar, text=tr("setup.cancel"), width=10, command=self.cancel).pack(side="left", padx=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        bar.pack()

    def fill(self, selected=()):
        self.listbox.delete(0, "end")
        for position, index in enumerate(self.order):
            self.listbox.insert("end", self.labels[index])
            if index in selected:
                self.listbox.selection_set(position)

    def selected(self):
        """Selected entries in output order."""
        return [self.entries[self.order[position]] for position in self.listbox.curselection()]

    def selected_labels(self):
        return [self.labels[self.order[position]] for position in self.listbox.curselection()]

    def move(self, step):
        positions = list(self.listbox.curselection())
        if not positions:
            return
        if (step < 0 and positions[0] == 0) or (step > 0 and positions[-1] == len(self.order) - 1):
            return
        chosen = {self.order[position] for position in positions}
        for position in (positions if step < 0 else reversed(positions)):
            other = position + step
            self.order[position], self.order[other] = self.order[other], self.order[position]
        self.fill(chosen)
        active = positions[0] + step if step < 0 else positions[-1] + step
        self.listbox.activate(active)
        self.listbox.see(active)
        self.refresh()

    def settings(self):
        text = self.width.get().strip()
        settings = {"format": "pdf", "transparent": bool(self.transparent.get())}
        if text:
            try:
                settings["width_mm"] = float(decimal_comma(text))
            except ValueError:
                raise ValueError(tr("pdf.invalid_width")) from None
        return settings

    def check(self):
        """Return (plans, problem, field) for the current choices."""
        chosen = self.selected()
        if not chosen:
            return None, tr("pdf.select"), self.listbox
        try:
            settings = self.settings()
            plans = fe.plan_pdf_bundle([entry.size for entry in chosen], settings, self.selected_labels())
        except ValueError as error:
            return None, str(error), self.width_entry
        return plans, None, None

    def refresh(self):
        chosen = self.selected()
        plans, problem, _field = self.check()
        self.plans = plans
        if problem:
            self.summary.configure(text=problem, foreground=ERROR)
        else:
            order = "\n".join(f"{i}. {label} — {plan['width_mm']:.1f} × {plan['height_mm']:.1f} mm"
                              for i, (label, plan) in enumerate(zip(self.selected_labels(), plans), 1))
            pages = tr("pdf.one_page") if len(plans) == 1 else tr("pdf.many_pages", count=len(plans))
            self.summary.configure(text=tr("pdf.order", pages=pages, order=order), foreground="#1c2b3a")
        notes = []
        if chosen:
            notes.append(tr("pdf.vector"))
        images = [entry.name for entry in chosen if entry.raster]
        if images:
            notes.append(tr("pdf.images", names=", ".join(images)))
        notes.extend(self.excluded)
        self.note.configure(text="\n".join(notes))

    def validate(self):
        plans, problem, field = self.check()
        if problem:
            self.summary.configure(text=problem, foreground=ERROR)
            field.focus_set()
            return False
        self.plans = plans
        return True

    def apply(self):
        self.result = {"refs": [entry.ref for entry in self.selected()], "settings": self.settings()}
