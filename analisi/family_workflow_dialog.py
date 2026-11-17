"""The dialog of Duplicate family… and Save family as…

It collects a name (or a literal prefix) and the Include layouts choice, and shows what the family will
contain before anything is copied or written. It never builds the copy: it asks ``describe`` for the
refusal and the preview lines of the current input, so the engine stays the only place that decides.
"""
import tkinter as tk
from tkinter import font as tkfont, simpledialog, ttk

from .i18n import tr
from .window_geometry import keep_native_window_on_screen


def family_error_text(error):
    """The message of a FamilyError in the active language; unknown codes keep the English text."""
    key = f"family.error.{error.code}"
    if error.code == "name-empty":
        key += f".{error.detail.get('mode', 'name')}"
    detail = dict(error.detail)
    if "limit" in detail:
        detail["limit"] = f"{detail['limit']:,}"
    text = tr(key, **detail)
    return str(error) if text == key else text


class FamilyDialog(simpledialog.Dialog):
    """``mode`` is "duplicate" or "save"; ``kind`` the kind of the selected sheet (data, result, …).

    ``describe(text, include_layouts)`` returns ``(error, lines)``: ``error`` is a FamilyError or None
    and ``lines`` are ``(tag, text)`` pairs for the preview. ``result`` is ``(text, include_layouts)``.
    """

    def __init__(self, parent, mode, kind, describe, *, initial="", include_layouts=True):
        self.mode, self.kind, self.describe = mode, kind, describe
        self.initial, self.include_default = initial, include_layouts
        self.name_var = tk.StringVar(parent, initial)
        self.include_var = tk.BooleanVar(parent, include_layouts)
        self.error_var = tk.StringVar(parent, "")
        super().__init__(parent, tr("family.duplicate_title" if mode == "duplicate" else "family.save_title"))

    def body(self, master):
        box = ttk.Frame(master, padding=12)
        box.pack(fill="both", expand=True)
        box.columnconfigure(0, weight=1)
        row = 0
        self.name_entry = None
        if self.mode == "duplicate":
            label = "family.name_label" if self.kind == "data" else "family.prefix_label"
            ttk.Label(box, text=tr(label)).grid(row=row, column=0, sticky="w")
            self.name_entry = ttk.Entry(box, textvariable=self.name_var, width=56)
            self.name_entry.grid(row=row + 1, column=0, sticky="ew", pady=(3, 0))
            row += 2
            if self.kind != "data":
                ttk.Label(box, text=tr("family.prefix_hint"), wraplength=520, justify="left").grid(
                    row=row, column=0, sticky="w", pady=(3, 0))
                row += 1
        self.error_label = ttk.Label(box, textvariable=self.error_var, foreground="#ad263b", wraplength=520,
                                     justify="left")
        self.error_label.grid(row=row, column=0, sticky="w", pady=(3, 0))
        row += 1
        forced = self.mode == "duplicate" and self.kind == "layout"
        irrelevant = self.kind == "saved-layout"
        self.include_check = ttk.Checkbutton(box, text=tr("family.include_layouts"), variable=self.include_var,
                                             command=self.refresh)
        if forced:
            self.include_var.set(True)
            self.include_check.state(["disabled"])
        elif irrelevant:
            self.include_var.set(False)
            self.include_check.state(["disabled"])
        self.include_check.grid(row=row, column=0, sticky="w", pady=(8, 0))
        row += 1
        if forced or irrelevant:
            ttk.Label(box, text=tr("family.layout_required" if forced else "family.layout_not_applicable"),
                      wraplength=520, justify="left").grid(row=row, column=0, sticky="w")
            row += 1
        frame = ttk.Frame(box)
        frame.grid(row=row, column=0, sticky="nsew", pady=(10, 0))
        box.rowconfigure(row, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.preview = tk.Text(frame, width=68, height=14, wrap="word", state="disabled", relief="flat",
                               borderwidth=1, highlightthickness=1, padx=8, pady=6, takefocus=False)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=scroll.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        base = tkfont.nametofont("TkDefaultFont").actual()
        self.preview.configure(font="TkDefaultFont")
        bold = (base["family"], base["size"], "bold")
        self.preview.tag_configure("heading", font=bold, spacing1=6)
        self.preview.tag_configure("counts", font=bold, spacing3=4)
        self.preview.tag_configure("item", lmargin1=12, lmargin2=24)
        self.preview.tag_configure("note", foreground="#176676", spacing1=4, lmargin1=0, lmargin2=12)
        self.name_var.trace_add("write", lambda *_: self.refresh())
        self.refresh()
        self.after_idle(lambda: keep_native_window_on_screen(self))
        return self.name_entry or self.include_check

    def refresh(self):
        text = self.name_var.get() if self.mode == "duplicate" else ""
        error, lines = self.describe(text, bool(self.include_var.get()))
        self.error_var.set(family_error_text(error) if error is not None and error.field == "name" else "")
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        if error is not None and error.field != "name":
            lines = [("note", family_error_text(error))]
        for tag, line in lines:
            self.preview.insert("end", line + "\n", tag)
        self.preview.configure(state="disabled")

    def buttonbox(self):
        box = ttk.Frame(self, padding=(12, 4, 12, 12))
        box.pack(fill="x")
        self.cancel_button = ttk.Button(box, text=tr("family.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.ok_button = ttk.Button(box, text=tr("family.duplicate_button" if self.mode == "duplicate"
                                                 else "family.choose_file"), command=self.ok)
        self.ok_button.pack(side="right", padx=(0, 6))
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        text = self.name_var.get() if self.mode == "duplicate" else ""
        error, _ = self.describe(text, bool(self.include_var.get()))
        if error is not None:
            self.error_var.set(family_error_text(error))
            if self.name_entry is not None and error.field == "name":
                self.name_entry.focus_set()
                self.name_entry.selection_range(0, "end")
            return False
        self.result = text, bool(self.include_var.get())
        return True

    def apply(self):
        pass
