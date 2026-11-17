"""Editor for one pie or donut slice style per sheet row.

Styles are stored by sheet row number. Two categories with the same label do not
share a style, and inserting or deleting rows changes which category is styled.
"""
import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog, ttk

from matplotlib.colors import to_hex

from .i18n import tr
from .parts_of_whole import DONUT, PIE, segment_styles, sheet_rows, slice_color_defaults
from .processing import FieldError

NOTE = ("Styles follow the sheet row number. Inserting or deleting rows changes which category is styled. "
        "Two rows with the same label do not share a style.")


def pick_slice_color(parent, variable):
    try:
        initial = to_hex(variable.get())
    except ValueError:
        initial = "#216a94"
    _, selected = colorchooser.askcolor(color=initial, parent=parent)
    if selected:
        variable.set(selected)


class PartsStyleDialog(simpledialog.Dialog):
    """Change color, explode distance and visibility for each sheet row. Cancel writes nothing."""

    def __init__(self, parent, frame, options, styles):
        self.result = None
        self.frame = frame
        self.options = options or {}
        self.pie = self.options.get("Graph style", DONUT) in {PIE, DONUT}
        self.styles = {int(key.split(":", 1)[1]): dict(value)
                       for key, value in (styles or {}).items()
                       if isinstance(key, str) and isinstance(value, dict) and key.startswith("row:")}
        self.titles, self.shares = sheet_rows(frame, self.options)
        try:
            self.defaults = slice_color_defaults(frame, self.options)
        except (ValueError, TypeError):
            self.defaults = {}
        self._guard = False
        self._index = None
        self.custom_color = False
        self.error_widget = None
        super().__init__(parent, tr("parts.style.title"))

    def body(self, master):
        master.columnconfigure(1, weight=1)
        ttk.Label(master, text=tr("parts.style.note"), wraplength=460, foreground="#486075").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.listbox = tk.Listbox(master, height=8, exportselection=False, width=28)
        self.listbox.grid(row=1, column=0, rowspan=6, sticky="nsw", padx=(0, 12))
        for number, (title, share) in enumerate(zip(self.titles, self.shares, strict=True), 1):
            shown = "—" if share is None else f"{share:.1%}"
            self.listbox.insert("end", f"{number}. {title}  ·  {shown}")
        fields = ttk.Frame(master)
        fields.grid(row=1, column=1, sticky="new")
        fields.columnconfigure(1, weight=1)
        self.color = tk.StringVar()
        self.explode = tk.StringVar()
        self.visible = tk.BooleanVar(value=True)
        ttk.Label(fields, text=tr("parts.style.color")).grid(row=0, column=0, sticky="w", pady=3, padx=(0, 8))
        color_row = ttk.Frame(fields)
        color_row.grid(row=0, column=1, sticky="ew", pady=3)
        self.color_entry = ttk.Entry(color_row, textvariable=self.color, width=12)
        self.color_entry.pack(side="left")
        ttk.Button(color_row, text=tr("parts.style.pick"), command=self._pick).pack(side="left", padx=(6, 0))
        self.explode_label = ttk.Label(fields, text=tr("parts.style.explode"))
        self.explode_entry = ttk.Entry(fields, textvariable=self.explode, width=8)
        if self.pie:
            self.explode_label.grid(row=1, column=0, sticky="w", pady=3, padx=(0, 8))
            self.explode_entry.grid(row=1, column=1, sticky="w", pady=3)
        self.visible_check = ttk.Checkbutton(fields, text=tr("parts.style.visible"), variable=self.visible)
        self.visible_check.grid(row=2, column=1, sticky="w", pady=3)
        ttk.Button(fields, text=tr("parts.style.restore"), command=self._restore).grid(
            row=3, column=1, sticky="w", pady=(6, 0))
        self.explode_hint = ttk.Label(fields, text=tr("parts.style.explode_hint"),
                                      wraplength=240, foreground="#486075")
        if self.pie:
            self.explode_hint.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.color.trace_add("write", lambda *_: self._mark_color())
        self.listbox.bind("<<ListboxSelect>>", self._changed)
        if self.titles:
            self._show(0)
        return self.listbox

    def _mark_color(self):
        if not self._guard:
            self.custom_color = True

    def _pick(self):
        pick_slice_color(self, self.color)
        self.custom_color = True

    def _show(self, index):
        self._guard = True
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        number = index + 1
        style = self.styles.get(number, {})
        self.custom_color = "color" in style
        self.color.set(style.get("color", self.defaults.get(number, "#cccccc")))
        self.explode.set(f"{style.get('explode', 0):g}")
        self.visible.set(style.get("visible", True))
        self._index = index
        self._guard = False

    def _changed(self, _event=None):
        if self._guard or self._index is None:
            return
        picked = self.listbox.curselection()
        if not picked or picked[0] == self._index:
            return
        if not self._commit(self._index):
            self._guard = True
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(self._index)
            self._guard = False
            return
        self._show(picked[0])

    def _commit(self, index):
        number = index + 1
        existing = self.styles.get(number, {})
        draft = {}
        if self.custom_color:
            draft["color"] = self.color.get().strip()
        if self.pie:
            text = self.explode.get().strip()
            if text not in {"", "0"}:
                draft["explode"] = text
        if not self.visible.get():
            draft["visible"] = False
        try:
            cleaned = segment_styles(self.frame, {f"row:{number}": draft} if draft else {}, allow_explode=self.pie)
        except FieldError as error:
            target = self.explode_entry if self.pie and "explode" in str(error) else self.color_entry
            self.error_widget = target
            target.focus_set()
            messagebox.showerror(tr("parts.style.error_title"), str(error), parent=self)
            target.focus_set()
            return False
        self.error_widget = None
        item = dict(cleaned.get(number, {}))
        if not self.pie and "explode" in existing:
            item["explode"] = existing["explode"]
        if item:
            self.styles[number] = item
        else:
            self.styles.pop(number, None)
        return True

    def _restore(self):
        if self._index is None:
            return
        number = self._index + 1
        if self.pie:
            self.styles.pop(number, None)
        elif number in self.styles:
            item = {k: v for k, v in self.styles[number].items() if k == "explode"}
            if item:
                self.styles[number] = item
            else:
                self.styles.pop(number, None)
        self._show(self._index)

    def validate(self):
        if self._index is not None and not self._commit(self._index):
            return False
        raw = {f"row:{number}": style for number, style in self.styles.items() if style}
        try:
            segment_styles(self.frame, raw, allow_explode=self.pie)
        except FieldError as error:
            target = self.explode_entry if self.pie and "explode" in str(error) else self.color_entry
            self.error_widget = target
            target.focus_set()
            messagebox.showerror(tr("parts.style.error_title"), str(error), parent=self)
            target.focus_set()
            return False
        self.result = raw
        return True
