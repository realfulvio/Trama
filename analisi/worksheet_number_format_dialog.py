"""Change → Number format… on Tk worksheets and result tables: display only, one undoable step."""
import tkinter as tk
from tkinter import simpledialog, ttk

from . import ui_theme
from .i18n import tr
from .worksheet_number_format import AUTOMATIC, MODES, FormatDraft, edit_text, mode_label


class NumberFormatDialog(simpledialog.Dialog):
    """Choose Automatic, fixed decimals, significant digits or scientific notation for the selected columns.

    ``choice`` is ``("apply", spec)`` after OK, ``("reset", None)`` after Reset and ``None`` after Cancel or Esc,
    which leave the sheet untouched."""

    def __init__(self, parent, target):
        self.target = target
        self.draft = FormatDraft(target.spec)
        self.choice = None
        super().__init__(parent, tr("number_format.title"))

    def body(self, master):
        target = self.target
        wrap = ui_theme.px(430)
        master.columnconfigure(0, weight=1)
        ttk.Label(master, text=target.changing_text(), wraplength=wrap, justify="left").grid(
            row=0, column=0, sticky="w")
        if target.unchanged:
            ttk.Label(master, text=target.unchanged_text(), wraplength=wrap, justify="left",
                      foreground=ui_theme.MUTED).grid(row=1, column=0, sticky="w", pady=(2, 0))

        modes = ttk.LabelFrame(master, text=tr("number_format.mode"), padding=8)
        modes.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        modes.columnconfigure(1, weight=1)
        self.mode = tk.StringVar(master, value=self.draft.mode)
        self.mode_buttons = {}
        for row, mode in enumerate(MODES):
            button = ttk.Radiobutton(modes, text=mode_label(mode), value=mode, variable=self.mode,
                                     command=self.mode_changed)
            button.grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
            self.mode_buttons[mode] = button
        self.digits_label = ttk.Label(modes)
        self.digits_label.grid(row=len(MODES), column=0, sticky="w", padx=(0, 10), pady=(6, 0))
        self.digits = tk.StringVar(master, value=str(self.draft.digits))
        self.spin = ttk.Spinbox(modes, textvariable=self.digits, width=5, increment=1, command=self.digits_changed)
        self.spin.grid(row=len(MODES), column=1, sticky="w", pady=(6, 0))
        self.spin.bind("<KeyRelease>", lambda _event: self.digits_changed())
        self.note = ttk.Label(modes, text=tr("number_format.automatic_note"), foreground=ui_theme.MUTED,
                              wraplength=wrap)
        self.note.grid(row=len(MODES) + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        preview = ttk.LabelFrame(master, text=tr("number_format.preview"), padding=8)
        preview.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(preview, text=tr("number_format.stored")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Label(preview, text=edit_text(target.value)).grid(row=0, column=1, sticky="w")
        ttk.Label(preview, text=tr("number_format.shown")).grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.shown = ttk.Label(preview, font=ui_theme.font(10, "bold"))
        self.shown.grid(row=1, column=1, sticky="w")
        if target.sample:
            ttk.Label(preview, text=tr("number_format.sample"), foreground=ui_theme.MUTED, wraplength=wrap).grid(
                row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.problem = ttk.Label(master, foreground=ui_theme.ERROR, wraplength=wrap)
        self.problem.grid(row=4, column=0, sticky="w")
        ttk.Label(master, text=tr("number_format.display_only"), foreground=ui_theme.MUTED, wraplength=wrap,
                  justify="left").grid(row=5, column=0, sticky="w", pady=(6, 0))
        self._refresh()
        return self.mode_buttons[self.draft.mode]

    def buttonbox(self):
        bar = ttk.Frame(self, padding=(8, 5))
        self.ok_button = ttk.Button(bar, text=tr("number_format.apply"), width=11, command=self.ok, default="active")
        self.ok_button.pack(side="right", padx=4)
        ttk.Button(bar, text=tr("number_format.cancel"), command=self.cancel).pack(side="right")
        self.reset_button = ttk.Button(bar, text=tr("number_format.reset"), command=self.restore)
        self.reset_button.pack(side="left")
        if not self.target.has_format:
            self.reset_button.state(["disabled"])
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        bar.pack(fill="x")

    def mode_changed(self):
        self.draft.set_mode(self.mode.get())
        self.digits.set(str(self.draft.digits))
        self._refresh()

    def _typed_digits(self):
        text = self.digits.get().strip()
        if not text.isdecimal():
            return None
        digits = int(text)
        low, high = self.draft.range()
        return digits if low <= digits <= high else None

    def digits_changed(self):
        if self.draft.mode == AUTOMATIC:
            return
        digits = self._typed_digits()
        if digits is not None:
            self.draft.set_digits(digits)
            self.problem.configure(text="")
        self._refresh()

    def _refresh(self):
        automatic = self.draft.mode == AUTOMATIC
        low, high = self.draft.range()
        self.digits_label.configure(text=self.draft.digits_label())
        self.spin.configure(from_=low, to=high)
        self.spin.state(["disabled"] if automatic else ["!disabled"])
        if automatic:
            self.note.grid()
        else:
            self.note.grid_remove()
        self.shown.configure(text=self.draft.preview(self.target.value))

    def validate(self):
        if self.draft.mode != AUTOMATIC and self._typed_digits() is None:
            self.problem.configure(text=self.draft.digits_label())
            self.spin.focus_set()
            return False
        return True

    def apply(self):
        self.choice = ("apply", self.draft.spec())

    def restore(self):
        self.choice = ("reset", None)
        self.cancel()
