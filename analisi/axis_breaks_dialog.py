"""Transactional Tk editor for axis breaks: the axis, the gap and two or three numeric segments."""
from copy import deepcopy
from math import isfinite
from sys import float_info
import tkinter as tk
from tkinter import simpledialog, ttk

from .axis_breaks import DEFAULT_GAP, AxisBreakError, normalise_axis_breaks, suggest_axis_breaks
from .axis_guides_dialog import ERROR_COLOR, HINT_COLOR, _ScrolledBody
from .data import decimal_comma
from .graph_dialog import ChoiceBinding
from .i18n import tr, translate_message

AXIS_CHOICES = ("", "x", "y")
AXIS_LABELS = {"": "axis_breaks.axis.none", "x": "axis_breaks.axis.x", "y": "axis_breaks.axis.y"}
COLUMNS = ("low", "high", "share", "major_step")
ROWS = 3


def translate_breaks_error(error):
    """The message of an engine or dialog error in the active language."""
    return translate_message(str(error), "axis_breaks.error.")


def breaks_summary(record):
    """One line for the button that opens the editor."""
    if not record:
        return tr("axis_breaks.summary_none")
    return tr("axis_breaks.summary", axis=record["axis"].upper(), count=len(record["segments"]))


def _text(value):
    return "" if value is None else f"{value:g}"


def _typed(text, *, blank=""):
    """The number typed in a field. Anything else is passed on as text, so the engine names the problem."""
    cleaned = text.strip()
    if not cleaned:
        return blank
    if "_" in cleaned:
        return cleaned
    try:
        value = float(decimal_comma(cleaned))
    except (TypeError, ValueError, OverflowError):
        return cleaned
    return value if isfinite(value) and abs(value) <= float_info.max else cleaned


class AxisBreaksDialog(simpledialog.Dialog):
    """Edit the ``axis_breaks`` record of a graph. ``result`` is ``{}`` for "no breaks", a record, or None if cancelled.

    ``preview(record)`` draws a candidate on the graph (``{}`` shows it without breaks, ``None`` goes back to the
    confirmed look) and raises ``ValueError`` when the graph cannot show it. The preview is undone on Cancel.
    """

    def __init__(self, parent, axes, record, *, preview=None, busy=None):
        self.axes = axes
        self.record = deepcopy(record) or {}
        self.preview_callback = preview
        self.busy_check = busy
        self.previewed = False
        self.accepted = False
        self.error_widget = None
        self.result = None
        super().__init__(parent, tr("axis_breaks.title"))

    # ----- form ---------------------------------------------------------------------------------------------
    def body(self, master):
        self.body_frame = master
        master.pack_configure(fill="both", expand=True)
        self.scrolled = _ScrolledBody(master, max(240, min(430, self.winfo_screenheight() - 300)))
        self.scrolled.outer.pack(fill="both", expand=True)
        form = self.scrolled.body
        form.columnconfigure(5, weight=1)
        self.widgets, self.vars = {}, {}
        segments = self.record.get("segments") or []

        ttk.Label(form, text=tr("axis_breaks.field.axis")).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.axis = tk.StringVar(self, self.record.get("axis", ""))
        box = ttk.Combobox(form, state="readonly", width=20)
        box.grid(row=0, column=1, columnspan=4, sticky="w", pady=3)
        self._axis_binding = ChoiceBinding(box, self.axis, AXIS_CHOICES, AXIS_LABELS)
        self.widgets["axis"] = box

        ttk.Label(form, text=tr("axis_breaks.field.count")).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.count = tk.StringVar(self, str(len(segments) if len(segments) in (2, 3) else 3))
        counts = ttk.Frame(form)
        counts.grid(row=1, column=1, columnspan=4, sticky="w", pady=3)
        for column, number in enumerate(("2", "3")):
            button = ttk.Radiobutton(counts, text=tr(f"axis_breaks.count.{number}"), value=number, variable=self.count)
            button.grid(row=0, column=column, padx=(0, 12))
            self.widgets["count" if number == "2" else "count3"] = button

        ttk.Label(form, text=tr("axis_breaks.field.gap")).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        self.gap = tk.StringVar(self, _text(self.record.get("gap", DEFAULT_GAP)))
        entry = ttk.Entry(form, textvariable=self.gap, width=9)
        entry.grid(row=2, column=1, sticky="w", pady=3)
        self.widgets["gap"] = entry
        ttk.Label(form, text=tr("axis_breaks.hint.gap"), foreground=HINT_COLOR).grid(
            row=2, column=2, columnspan=3, sticky="w", padx=(8, 0))

        for column, name in enumerate(COLUMNS, start=1):
            ttk.Label(form, text=tr(f"axis_breaks.col.{name}")).grid(row=3, column=column, sticky="w", padx=(0, 6),
                                                                      pady=(8, 0))
        for row in range(ROWS):
            ttk.Label(form, text=tr("axis_breaks.row", row=row + 1)).grid(row=4 + row, column=0, sticky="w",
                                                                           padx=(0, 8), pady=2)
            segment = segments[row] if row < len(segments) else {}
            for column, name in enumerate(COLUMNS, start=1):
                variable = self.vars[(row, name)] = tk.StringVar(self, _text(segment.get(name)))
                variable.trace_add("write", self._changed)
                entry = ttk.Entry(form, textvariable=variable, width=11)
                entry.grid(row=4 + row, column=column, sticky="w", padx=(0, 6), pady=2)
                self.widgets[f"segments.{row}.{name}"] = entry
        self.total = ttk.Label(form, text="")
        self.total.grid(row=4 + ROWS, column=0, columnspan=5, sticky="w", pady=(4, 0))
        self.suggest_button = ttk.Button(form, text=tr("axis_breaks.btn.suggest"), command=self.suggest)
        self.suggest_button.grid(row=5 + ROWS, column=0, columnspan=3, sticky="w", pady=(6, 0))
        for index, key in enumerate(("axis_breaks.note.scale", "axis_breaks.note.limits", "axis_breaks.note.numbers")):
            ttk.Label(form, text=tr(key), foreground=HINT_COLOR, wraplength=460, justify="left").grid(
                row=6 + ROWS + index, column=0, columnspan=6, sticky="w", pady=(8 if index == 0 else 3, 0))
        self.axis.trace_add("write", self._axis_changed)
        self.count.trace_add("write", self._count_changed)
        self.gap.trace_add("write", self._changed)
        self._refresh_states()
        return self.widgets["axis"]

    def buttonbox(self):
        footer = ttk.Frame(self, padding=(8, 4, 8, 8))
        footer.pack(side="bottom", fill="x", before=self.body_frame)
        self.problem = ttk.Label(footer, wraplength=460, justify="left", foreground=ERROR_COLOR)
        self.problem.pack(side="top", fill="x", pady=(0, 4))
        self.cancel_button = ttk.Button(footer, text=tr("axis_breaks.btn.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.ok_button = ttk.Button(footer, text=tr("axis_breaks.btn.ok"), style="Action.TButton", command=self.ok)
        self.ok_button.pack(side="right", padx=6)
        self.preview_button = ttk.Button(footer, text=tr("axis_breaks.btn.preview"), command=self.preview)
        self.preview_button.pack(side="right")
        for button in (self.preview_button, self.ok_button, self.cancel_button, self.suggest_button):
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    # ----- state --------------------------------------------------------------------------------------------
    def _rows(self):
        return int(self.count.get() or 3)

    def _refresh_states(self):
        on = bool(self.axis.get())
        rows = self._rows()
        for key, widget in self.widgets.items():
            if key == "axis":
                continue
            widget.state(["!disabled" if on else "disabled"])
        for row in range(ROWS):
            for name in COLUMNS:
                self.widgets[f"segments.{row}.{name}"].state(["!disabled" if on and row < rows else "disabled"])
        self.suggest_button.state(["!disabled" if on else "disabled"])
        self._changed()

    def _changed(self, *_):
        if not hasattr(self, "total"):
            return
        try:
            shares = [float(decimal_comma(self.vars[(row, "share")].get().strip())) for row in range(self._rows())]
        except ValueError:
            self.total.configure(text="")
            return
        total = sum(shares)
        self.total.configure(text=tr("axis_breaks.total", total=f"{total:g}"),
                             foreground=HINT_COLOR if abs(total - 100) <= 1e-8 else ERROR_COLOR)

    def _fill(self, record):
        self.record = record
        for row in range(ROWS):
            segment = record["segments"][row] if row < len(record["segments"]) else {}
            for name in COLUMNS:
                self.vars[(row, name)].set(_text(segment.get(name)))
        self.gap.set(_text(record["gap"]))

    def suggest(self):
        axis = self.axis.get()
        record = suggest_axis_breaks(self.axes, axis, self._rows()) if axis else None
        if record is None:
            self.problem.configure(text=tr("axis_breaks.error.no_suggestion"))
            return
        self.problem.configure(text="")
        self._fill(record)

    def _axis_changed(self, *_):
        self._refresh_states()
        if self.axis.get():
            record = suggest_axis_breaks(self.axes, self.axis.get(), self._rows())
            if record is not None:
                self._fill(record)

    def _count_changed(self, *_):
        self._refresh_states()
        blank = any(not self.vars[(row, name)].get().strip() for row in range(self._rows()) for name in ("low", "high", "share"))
        if self.axis.get() and blank:
            self.suggest()

    # ----- reading ------------------------------------------------------------------------------------------
    def read_record(self):
        """The canonical record typed in the form, ``{}`` for no breaks. Raises ``AxisBreakError``."""
        axis = self.axis.get()
        if not axis:
            return {}
        saved = self.record.get("segments", ()) if axis == self.record.get("axis") else ()
        segments = []
        for row in range(self._rows()):
            segment = {name: _typed(self.vars[(row, name)].get()) for name in ("low", "high", "share")}
            segment["major_step"] = _typed(self.vars[(row, "major_step")].get(), blank=None)
            if row < len(saved):
                for key in ("minor_ticks", "major_origin", "tick_labels", "tick_format"):
                    if key in saved[row] and (key != "major_origin" or segment["major_step"] is not None):
                        segment[key] = saved[row][key]
            segments.append(segment)
        return normalise_axis_breaks({"axis": axis, "gap": _typed(self.gap.get()), "segments": segments})

    def show_error(self, error):
        self.problem.configure(text=translate_breaks_error(error))
        field = getattr(error, "field", None)
        if isinstance(error, AxisBreakError) and error.name in ("minor_ticks", "major_origin"):
            field = f"segments.{error.row}.major_step"
        widget = self.widgets.get("count" if field == "segments" else field)
        self.error_widget = widget
        if widget is not None:
            self.scrolled.reveal(widget)
            self.update_idletasks()
            widget.focus_set()
            if isinstance(widget, ttk.Entry):
                widget.select_range(0, "end")
                widget.icursor("end")

    def _busy(self):
        if self.busy_check and self.busy_check():
            self.problem.configure(text=tr("axis_breaks.error.busy"))
            return True
        return False

    def _try(self, draw):
        """Read the form and, when ``draw``, show it on the graph. Returns the record, or None after showing why."""
        if self._busy():
            return None
        try:
            record = self.read_record()
            if draw and self.preview_callback is not None:
                self.preview_callback(record)
                self.previewed = True
        except ValueError as error:
            if not hasattr(error, "field"):
                error = AxisBreakError(None, "axis", str(error))
            self.show_error(error)
            return None
        self.problem.configure(text="")
        return record

    # ----- buttons ------------------------------------------------------------------------------------------
    def preview(self):
        return self._try(True) is not None

    def validate(self):
        record = self._try(True)
        self.result = record
        return record is not None

    def ok(self, event=None):
        if not self.winfo_exists():
            return None
        if not self.validate():
            return "break"
        self.withdraw()
        self.update_idletasks()
        self.accepted = True
        self.cancel()
        return None

    def cancel(self, event=None):
        if not self.accepted:
            if self.previewed and self.preview_callback is not None:
                self.preview_callback(None)
            self.result = None
        super().cancel(event)
