"""Font preference dialog for the Tk worksheet and result views."""
import tkinter as tk
from tkinter import font, simpledialog, ttk

from .i18n import tr
from .worksheet_appearance import MAX_FONT_SIZE, MIN_FONT_SIZE


class TableFontDialog(simpledialog.Dialog):
    def __init__(self, parent, preference):
        self.preference = preference
        super().__init__(parent, tr("command.table_font").rstrip("…"))

    def body(self, master):
        family, size = self.preference
        self.default = tr("worksheet.font_default")
        families = sorted(set(font.families(master)) | ({family} if family else set()), key=str.casefold)
        self.family = tk.StringVar(value=family or self.default)
        self.size = tk.StringVar(value=str(size) if size is not None else self.default)
        for row, (label, values, variable) in enumerate((
            ("worksheet.font_family", (self.default, *families), self.family),
            ("worksheet.font_size", (self.default, *map(str, range(MIN_FONT_SIZE, MAX_FONT_SIZE + 1))), self.size),
        )):
            ttk.Label(master, text=tr(label)).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            combo = ttk.Combobox(master, textvariable=variable, values=values, state="readonly")
            combo.grid(row=row, column=1, sticky="ew", pady=4)
            if row == 0:
                first = combo
        return first

    def apply(self):
        family, size = self.family.get(), self.size.get()
        self.result = ("" if family == self.default else family, None if size == self.default else int(size))
