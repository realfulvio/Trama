"""Dialog parts of Competing risks: the line editors of the event codes and the requested times.

Both editors keep what the user typed. Codes stay literal text (spaces included, one code per line), times are
numbers when they parse and the raw text otherwise, so the analysis reports the value that needs fixing on the
right field instead of the dialog rewriting it.
"""
import tkinter as tk
from tkinter import ttk

from .competing_risks_workbench import ERROR_PREFIX, LABEL_KEYS
from .i18n import localized_count as number, tr, translate_message, ui

HINT = "#486075"


def caption(field):
    return tr(LABEL_KEYS[field]) if field in LABEL_KEYS else field


def translate_error(error):
    """An engine message in the active language; the field names inside it become the dialog captions.

    Messages of the shared dialog fields (the confidence level) come from the common interface catalog.
    """
    text = str(error)
    converters = {"field": caption, "role": caption, "first": caption,
                  "limit": number, "count": number, "rows": number, "work": number}
    shown = translate_message(text, ERROR_PREFIX, converters)
    return ui(shown) if shown == text else shown


def describe_error(error, field=None):
    """The dialog banner for an error: translated, and naming the field it belongs to."""
    field = getattr(error, "field", field)
    message = translate_error(error)
    label = caption(field) if field else ""
    named = message.lower()
    if field and field.lower() not in named and label.lower() not in named:
        message = f"{label}: {message}"
    return message


def show_time(value):
    """A requested time as a short line of text: 1.0 is shown as 1, other numbers keep every digit."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "" if value is None else str(value)
    return str(int(value)) if float(value).is_integer() and abs(value) < 1e15 else repr(float(value))


def read_time(text):
    """A typed time as a number, accepting the decimal comma; text that is not a number is kept as typed."""
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return text.strip()


class LineEditor(ttk.Frame):
    """A small multi-line text box, one value per line, with a hint underneath."""

    hint_key = ""
    rows = 4

    def __init__(self, parent, saved=None, on_change=None):
        super().__init__(parent)
        self.on_change = on_change
        self.columnconfigure(0, weight=1)
        self.text = tk.Text(self, height=self.rows, width=24, wrap="none", undo=True, exportselection=False)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="ew")
        scroll.grid(row=0, column=1, sticky="ns")
        # The hint wraps to the room the field really has: a longer caption (Italian) narrows this column.
        self.hint = ttk.Label(self, text=tr(self.hint_key), foreground=HINT, wraplength=240, justify="left")
        self.hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.bind("<Configure>", self._wrap_hint)
        self.text.insert("1.0", "\n".join(self.lines_from(saved)))
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.text.bind("<<Modified>>", self._modified)
        self.text.bind("<Tab>", self._next_field)
        self.text.bind("<Shift-Tab>", self._previous_field)

    def _wrap_hint(self, event):
        width = max(160, event.width - 6)
        if int(self.hint.cget("wraplength")) != width:
            self.hint.configure(wraplength=width)

    def lines_from(self, saved):
        raise NotImplementedError

    def focus_target(self):
        return self.text

    def _modified(self, _event):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            if self.on_change is not None:
                self.on_change()

    def _next_field(self, _event):
        self.text.tk_focusNext().focus_set()
        return "break"

    def _previous_field(self, _event):
        self.text.tk_focusPrev().focus_set()
        return "break"

    def raw_lines(self):
        """Typed lines without their line ends; empty lines after the last value are not values."""
        lines = [line.rstrip("\r") for line in self.text.get("1.0", "end-1c").split("\n")]
        while lines and not lines[-1].strip():
            lines.pop()
        return lines

    def set_lines(self, values):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(self.lines_from(values)))


class CodeListEditor(LineEditor):
    """Event codes, in the order of the tables. A code is read exactly as typed; an empty line is an empty code."""

    hint_key = "cr.hint.codes"
    rows = 3

    def lines_from(self, saved):
        if isinstance(saved, (list, tuple)):
            return [value if isinstance(value, str) else show_time(value) for value in saved]
        return ["1", "2"] if saved is None else []

    def values(self):
        return self.raw_lines()

    def codes(self):
        """Distinct non-empty codes, for the choice of the drawn cause."""
        return list(dict.fromkeys(line for line in self.raw_lines() if line.strip()))[:6]


class TimeListEditor(LineEditor):
    """Optional times at which the estimates are reported; blank lines are ignored."""

    hint_key = "cr.hint.times"
    rows = 5

    def lines_from(self, saved):
        return [show_time(value) for value in saved] if isinstance(saved, (list, tuple)) else []

    def values(self):
        return [read_time(line) for line in self.raw_lines() if line.strip()]
