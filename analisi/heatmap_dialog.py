"""Editor of the colors of a categorical heat map: one row per observed level, colors stored by level text."""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from matplotlib import colormaps
from matplotlib.colors import is_color_like, to_hex

from . import ui_theme
from .graph_dialog import pick_color
from .heatmap import MAX_LEVELS, check_category_colors
from .i18n import tr, ui
from .processing import FieldError

HINT = "#486075"
ERROR = "#a02a2a"


def palette_colors(count):
    """The colors an unmapped level gets today, so the editor can show what blank means."""
    cmap = colormaps["tab20"].resampled(max(1, count))
    return [to_hex(cmap(index)) for index in range(count)]


def shown(color, fallback):
    return to_hex(color) if color and is_color_like(color) else fallback


class CategoryColorsDialog(simpledialog.Dialog):
    """Choose a color per category. A blank color keeps the palette color; Cancel and Esc write nothing."""

    def __init__(self, parent, levels, mapping):
        self.levels = list(levels)[:MAX_LEVELS]
        self.extra = len(levels) - len(self.levels)
        self.mapping = dict(mapping)
        self.defaults = palette_colors(len(levels))
        self.rows = []
        self.result = self.checked = None
        super().__init__(parent, tr("heat.cat.title"))

    def body(self, master):
        master.columnconfigure(0, weight=1)
        ttk.Label(master, text=tr("heat.cat.note"), wraplength=ui_theme.px(430), foreground=HINT,
                  justify="left").grid(row=0, column=0, sticky="w", pady=(0, 8))
        viewport = ttk.Frame(master)
        viewport.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(viewport, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.canvas = tk.Canvas(viewport, highlightthickness=0, yscrollcommand=scroll.set,
                                background=ttk.Style(self).lookup("TFrame", "background") or "#ffffff")
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.canvas.yview)
        table = ttk.Frame(self.canvas)
        window = self.canvas.create_window(0, 0, window=table, anchor="nw")
        self.table = table
        table.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
        table.columnconfigure(0, weight=1)
        for column, key in enumerate(("heat.cat.level", "heat.cat.color"), 0):
            ttk.Label(table, text=tr(key), style="DialogTitle.TLabel").grid(
                row=0, column=0 if column == 0 else 1, columnspan=1 if column == 0 else 3, sticky="w", padx=(0, 8))
        first = None
        for index, level in enumerate(self.levels, 1):
            text = tk.StringVar(value=self.mapping.get(level, ""))
            ttk.Label(table, text=level, wraplength=ui_theme.px(190)).grid(row=index, column=0, sticky="w", pady=2, padx=(0, 8))
            swatch = tk.Label(table, width=3, relief="solid", borderwidth=1,
                              background=shown(text.get(), self.defaults[index - 1]))
            swatch.grid(row=index, column=1, padx=(0, 6), pady=2)
            entry = ttk.Entry(table, textvariable=text, width=11)
            entry.grid(row=index, column=2, padx=(0, 6), pady=2)
            pick = ttk.Button(table, text=ui("Pick…"), command=lambda variable=text: pick_color(self, variable))
            pick.grid(row=index, column=3, pady=2)
            for control in (entry, pick):
                control.bind("<FocusIn>", lambda _e, widget=control: self.reveal(widget))
            text.trace_add("write", lambda *_, v=text, s=swatch, i=index - 1: s.configure(
                background=shown(v.get().strip(), self.defaults[i])))
            self.rows.append((level, text, entry))
            first = first or entry
        if not self.levels:
            ttk.Label(table, text=tr("heat.cat.empty"), foreground=HINT).grid(row=1, column=0, columnspan=4, sticky="w")
        table.update_idletasks()
        self.canvas.configure(width=table.winfo_reqwidth(),
                              height=min(table.winfo_reqheight(), max(160, self.winfo_screenheight() - ui_theme.px(270))))
        for widget in (self.canvas, table, *table.winfo_children()):
            widget.bind("<MouseWheel>", lambda event: self._wheel(-1 if event.delta > 0 else 1))
            widget.bind("<Button-4>", lambda _e: self._wheel(-1))
            widget.bind("<Button-5>", lambda _e: self._wheel(1))
        if self.extra > 0:
            ttk.Label(master, text=tr("heat.cat.more", count=MAX_LEVELS), foreground=HINT, wraplength=ui_theme.px(430),
                      justify="left").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.message = ttk.Label(master, foreground=ERROR, wraplength=ui_theme.px(430), justify="left")
        self.message.grid(row=3, column=0, sticky="w", pady=(6, 0))
        return first

    def _wheel(self, direction):
        self.canvas.yview_scroll(direction, "units")
        return "break"

    def reveal(self, widget):
        """Keep keyboard focus and a validation error's row inside the scrolling viewport."""
        self.canvas.update_idletasks()
        total = max(1, self.table.winfo_height())
        top = widget.winfo_rooty() - self.table.winfo_rooty()
        first, last = self.canvas.yview()
        if top < first * total or top + widget.winfo_height() > last * total:
            self.canvas.yview_moveto(max(0., (top - 8) / total))

    def buttonbox(self):
        row = ttk.Frame(self, padding=(15, 0, 15, 12))
        ttk.Button(row, text=ui("Apply"), style="Action.TButton", command=self.ok).pack(side="right", padx=(8, 0))
        ttk.Button(row, text=ui("Cancel"), command=self.cancel).pack(side="right")
        ttk.Button(row, text=tr("heat.cat.reset"), command=self.reset).pack(side="left")
        row.pack(fill="x")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def reset(self):
        for _, text, _ in self.rows:
            text.set("")

    def validate(self):
        merged = dict(self.mapping)
        for level, text, entry in self.rows:
            value = text.get().strip()
            if not value:
                merged.pop(level, None)
            elif not is_color_like(value):
                self.message.configure(text=tr("heat.cat.invalid", level=level))
                self.reveal(entry)
                entry.focus_set()
                return False
            else:
                merged[level] = value
        try:
            self.checked = check_category_colors(merged)
        except FieldError as error:
            self.message.configure(text=str(error))
            return False
        return True

    def apply(self):
        self.result = self.checked


class CategoryColorsField(ttk.Frame):
    """The Category colors control of the analysis dialog: a summary and the button that opens the editor.

    ``levels()`` returns the observed levels of the current column choice or raises ``FieldError``;
    ``values()`` is the {level: color} mapping, which also keeps the pairs of levels that are absent now."""

    def __init__(self, parent, saved, levels):
        super().__init__(parent)
        self.mapping = dict(saved) if isinstance(saved, dict) else {}
        self._levels = levels
        self.summary = ttk.Label(self, wraplength=ui_theme.px(300), justify="left")
        self.summary.pack(anchor="w")
        self.button = ttk.Button(self, text=tr("heat.cat.edit"), command=self.edit)
        self.button.pack(anchor="w", pady=(4, 0))
        self.refresh()

    def values(self):
        return dict(self.mapping)

    def focus_target(self):
        return self.button

    def refresh(self):
        try:
            levels = self._levels()
        except FieldError:
            self.summary.configure(text=tr("heat.cat.choose"))
            return
        custom = sum(level in self.mapping for level in levels)
        self.summary.configure(text=tr("heat.cat.summary", custom=custom, total=len(levels)))

    def edit(self):
        try:
            levels = self._levels()
        except FieldError as error:
            messagebox.showerror(ui("Check parameters"), str(error), parent=self)
            return
        dialog = CategoryColorsDialog(self.winfo_toplevel(), levels, self.mapping)
        if dialog.result is not None:
            self.mapping = dialog.result
        self.refresh()
