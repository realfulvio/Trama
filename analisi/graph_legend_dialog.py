"""Shared transactional Tk dialog for native Matplotlib legend formatting."""
from copy import deepcopy
from math import isfinite
from sys import float_info
import tkinter as tk
from tkinter import simpledialog, ttk

from .axis_guides_dialog import ERROR_COLOR, HINT_COLOR, _ScrolledBody
from .data import decimal_comma
from .graph_dialog import ChoiceBinding, pick_color
from .graph_legend import (
    MAX_LEGEND_BORDER_WIDTH,
    MAX_LEGEND_COLUMNS,
    MAX_LEGEND_TEXT_LENGTH,
    collect_legend_entries,
    is_non_native_figure,
    validate_legend_options,
)
from .i18n import tr, translate_message

FRAME_DEFAULT = "Analysis default"
FRAME_SHOWN = "shown"
FRAME_HIDDEN = "hidden"
FRAME_CHOICES = (FRAME_DEFAULT, FRAME_SHOWN, FRAME_HIDDEN)
FRAME_LABELS = {
    FRAME_DEFAULT: "legend_editor.frame.default",
    FRAME_SHOWN: "legend_editor.frame.shown",
    FRAME_HIDDEN: "legend_editor.frame.hidden",
}

_ENGINE_ERROR_FIELDS = (
    ("title", "title"),
    ("column", "columns"),
    ("frame setting", "frame"),
    ("background color", "facecolor"),
    ("border color", "edgecolor"),
    ("border width", "width"),
    ("opacity", "alpha"),
    ("entry order", "reverse"),
)


class _LegendFieldError(ValueError):
    """Validation error tied to a specific widget key inside ``LegendEditorDialog``."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def translate_legend_error(error):
    """Translate engine or legend-dialog errors into the active UI language."""
    text = str(error)
    translated = translate_message(text, "legend_editor.error.")
    if translated != text:
        return translated
    return translate_message(text, "graph.error.")


def legend_summary(options):
    """Return a translated short summary string for the Format Graph button row."""
    return tr("legend_editor.summary_custom") if options else tr("legend_editor.summary_none")


def _parse_optional_int(raw_text, field, message):
    cleaned = raw_text.strip()
    if not cleaned:
        return None
    if not cleaned.isdigit() and not (cleaned.startswith(("+", "-")) and cleaned[1:].isdigit()):
        raise _LegendFieldError(field, message)
    try:
        value = int(cleaned)
    except (ValueError, OverflowError):
        raise _LegendFieldError(field, message) from None
    if not (1 <= value <= MAX_LEGEND_COLUMNS):
        raise _LegendFieldError(field, message)
    return value


def _parse_optional_float(raw_text, field, low, high, message):
    cleaned = raw_text.strip()
    if not cleaned:
        return None
    if "_" in cleaned:
        raise _LegendFieldError(field, message)
    try:
        value = float(decimal_comma(cleaned))
    except (TypeError, ValueError, OverflowError):
        raise _LegendFieldError(field, message) from None
    if not isfinite(value) or abs(value) > float_info.max or not (low <= value <= high):
        raise _LegendFieldError(field, message)
    return value


class LegendEditorDialog(simpledialog.Dialog):
    """Transactional editor for legend title, layout, frame, order, and per-entry labels."""

    def __init__(self, parent, figure, options=None, *, preview=None, busy=None):
        self.figure = figure
        self.initial_options = deepcopy(options or {})
        self.preview_callback = preview
        self.busy_check = busy
        self.non_native = is_non_native_figure(figure)
        self.entries = [] if self.non_native else collect_legend_entries(figure)
        self.default_title = self._detect_default_title()
        self.previewed = False
        self.accepted = False
        self.error_widget = None
        self.result = None
        super().__init__(parent, tr("legend_editor.dialog_title"))

    def _detect_default_title(self):
        if not self.entries:
            return ""
        legend = self.entries[0].legend
        snapshot = getattr(legend, "_tramastat_legend_snapshot", None)
        if snapshot is not None:
            return snapshot.get("title", "")
        return legend.get_title().get_text()

    def body(self, master):
        self.body_frame = master
        master.pack_configure(fill="both", expand=True)
        height = max(220, min(420, self.winfo_screenheight() - 280))
        self.scrolled = _ScrolledBody(master, height)
        self.scrolled.outer.pack(fill="both", expand=True)
        form = self.scrolled.body
        form.columnconfigure(1, weight=1)

        self.fields = {}
        self.widgets = {}
        self.error_labels = {}
        self.bindings = {}
        self.entry_vars = {}
        self.entry_widgets = {}
        self._title_overridden = "title" in self.initial_options
        self._preserved_hidden_labels = {
            key: value
            for key, value in self.initial_options.get("labels", {}).items()
            if key not in {entry.key for entry in self.entries}
        }

        row = 0
        if self.non_native:
            ttk.Label(
                form,
                text=tr("legend_editor.hint.non_native"),
                foreground=ERROR_COLOR,
                wraplength=410,
                justify="left",
            ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
            row += 1

        general = ttk.LabelFrame(form, text=tr("legend_editor.section.general"), padding=(8, 6))
        general.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        general.columnconfigure(1, weight=1)
        row += 1

        g_row = 0
        initial_title = self.initial_options.get("title", self.default_title)
        g_row = self._add_entry(general, g_row, "title", tr("legend_editor.field.title"), initial_title, width=26)
        initial_cols = "" if "columns" not in self.initial_options else str(self.initial_options["columns"])
        g_row = self._add_entry(general, g_row, "columns", tr("legend_editor.field.columns"), initial_cols, width=10)
        g_row = self._add_check(
            general,
            g_row,
            "reverse",
            tr("legend_editor.field.reverse"),
            bool(self.initial_options.get("reverse", False)),
        )

        frame_box = ttk.LabelFrame(form, text=tr("legend_editor.section.frame"), padding=(8, 6))
        frame_box.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        frame_box.columnconfigure(1, weight=1)
        row += 1

        f_row = 0
        if "frame" not in self.initial_options:
            initial_frame = FRAME_DEFAULT
        elif self.initial_options["frame"]:
            initial_frame = FRAME_SHOWN
        else:
            initial_frame = FRAME_HIDDEN
        f_row = self._add_choice(
            frame_box, f_row, "frame", tr("legend_editor.field.frame"), FRAME_CHOICES, FRAME_LABELS, initial_frame
        )
        f_row = self._add_color(
            frame_box, f_row, "facecolor", tr("legend_editor.field.facecolor"), self.initial_options.get("facecolor", "")
        )
        f_row = self._add_color(
            frame_box, f_row, "edgecolor", tr("legend_editor.field.edgecolor"), self.initial_options.get("edgecolor", "")
        )
        initial_width = "" if "width" not in self.initial_options else f"{self.initial_options['width']:g}"
        f_row = self._add_entry(frame_box, f_row, "width", tr("legend_editor.field.width"), initial_width, width=12)
        initial_alpha = "" if "alpha" not in self.initial_options else f"{self.initial_options['alpha']:g}"
        f_row = self._add_entry(frame_box, f_row, "alpha", tr("legend_editor.field.alpha"), initial_alpha, width=12)

        entries_box = ttk.LabelFrame(form, text=tr("legend_editor.section.entries"), padding=(8, 6))
        entries_box.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        entries_box.columnconfigure(1, weight=1)
        row += 1

        if self.entries:
            e_row = 0
            saved_labels = self.initial_options.get("labels", {})
            for entry in self.entries:
                field_key = f"label:{entry.key}"
                ttk.Label(
                    entries_box,
                    text=entry.display_name,
                    wraplength=170,
                    justify="left",
                ).grid(row=e_row, column=0, sticky="w", padx=(0, 8), pady=2)
                var = tk.StringVar(self, saved_labels.get(entry.key, ""))
                widget = ttk.Entry(entries_box, textvariable=var, width=24)
                widget.grid(row=e_row, column=1, sticky="ew", pady=2)
                err = ttk.Label(entries_box, wraplength=390, foreground=ERROR_COLOR, justify="left")
                err.grid(row=e_row + 1, column=0, columnspan=2, sticky="w")
                err.grid_remove()
                self.entry_vars[entry.key] = var
                self.entry_widgets[entry.key] = widget
                self.widgets[field_key] = widget
                self.error_labels[field_key] = err
                e_row += 2
        else:
            ttk.Label(
                entries_box,
                text=tr("legend_editor.hint.no_legend"),
                foreground=HINT_COLOR,
                wraplength=390,
                justify="left",
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Label(
            form,
            text=tr("legend_editor.hint.literal"),
            foreground=HINT_COLOR,
            wraplength=410,
            justify="left",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 0))

        self._bind_wheel(self.scrolled.outer)
        return self.widgets["title"]

    def _add_error_row(self, parent, row, key, columnspan=3):
        err = ttk.Label(parent, wraplength=390, foreground=ERROR_COLOR, justify="left")
        err.grid(row=row, column=0, columnspan=columnspan, sticky="w")
        err.grid_remove()
        self.error_labels[key] = err
        return row + 1

    def _add_entry(self, parent, row, key, caption, initial, *, width=16):
        ttk.Label(parent, text=caption).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        var = tk.StringVar(self, initial)
        widget = ttk.Entry(parent, textvariable=var, width=width)
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        self.fields[key] = var
        self.widgets[key] = widget
        return self._add_error_row(parent, row + 1, key)

    def _add_color(self, parent, row, key, caption, initial):
        ttk.Label(parent, text=caption).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        var = tk.StringVar(self, initial)
        widget = ttk.Entry(parent, textvariable=var, width=16)
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        button = ttk.Button(parent, text=tr("graph.field.pick"), command=lambda v=var: pick_color(self, v))
        button.grid(row=row, column=2, padx=(6, 0), pady=3)
        self.fields[key] = var
        self.widgets[key] = widget
        return self._add_error_row(parent, row + 1, key)

    def _add_choice(self, parent, row, key, caption, choices, labels, initial):
        ttk.Label(parent, text=caption).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        var = tk.StringVar(self, initial)
        widget = ttk.Combobox(parent, state="readonly", width=20)
        widget.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
        self.fields[key] = var
        self.widgets[key] = widget
        self.bindings[key] = ChoiceBinding(widget, var, choices, labels)
        return self._add_error_row(parent, row + 1, key)

    def _add_check(self, parent, row, key, caption, initial):
        var = tk.BooleanVar(self, bool(initial))
        widget = ttk.Checkbutton(parent, text=caption, variable=var)
        widget.grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
        self.fields[key] = var
        self.widgets[key] = widget
        return self._add_error_row(parent, row + 1, key)

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", lambda e: self.scrolled.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        widget.bind("<Button-4>", lambda _e: self.scrolled.canvas.yview_scroll(-1, "units"))
        widget.bind("<Button-5>", lambda _e: self.scrolled.canvas.yview_scroll(1, "units"))
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def buttonbox(self):
        footer = ttk.Frame(self, padding=(8, 4, 8, 8))
        footer.pack(side="bottom", fill="x", before=self.body_frame)
        self.problem = ttk.Label(footer, wraplength=420, justify="left", foreground=ERROR_COLOR)
        self.problem.pack(side="top", fill="x", pady=(0, 4))
        self.reset_button = ttk.Button(footer, text=tr("legend_editor.btn.reset"), command=self.reset_fields)
        self.reset_button.pack(side="left")
        self.cancel_button = ttk.Button(footer, text=tr("legend_editor.btn.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.apply_button = ttk.Button(
            footer, text=tr("legend_editor.btn.apply"), style="Action.TButton", command=self.ok
        )
        self.apply_button.pack(side="right", padx=6)
        self.preview_button = ttk.Button(footer, text=tr("legend_editor.btn.preview"), command=self.preview)
        self.preview_button.pack(side="right")
        if self.non_native:
            self.preview_button.state(["disabled"])
            self.apply_button.state(["disabled"])
        for button in (self.reset_button, self.preview_button, self.apply_button, self.cancel_button):
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
        self.bind("<Return>", self._on_return)
        self.bind("<Escape>", self.cancel)

    def _on_return(self, _event):
        if not self.non_native:
            self.ok()

    def clear_errors(self):
        self.error_widget = None
        self.problem.configure(text="")
        for label in self.error_labels.values():
            label.configure(text="")
            label.grid_remove()

    def show_error(self, field, message):
        self.clear_errors()
        translated = translate_legend_error(message)
        label = self.error_labels.get(field)
        if label is not None:
            label.configure(text=translated)
            label.grid()
        else:
            self.problem.configure(text=translated)
        widget = self.widgets.get(field)
        self.error_widget = widget
        if widget is not None:
            self.scrolled.reveal(widget)
            self.update_idletasks()
            widget.focus_set()
            if isinstance(widget, ttk.Entry):
                widget.select_range(0, "end")
                widget.icursor("end")

    def read_options(self):
        """Read and validate form fields into a canonical ``legend_options`` dictionary."""
        if self.non_native:
            raise _LegendFieldError("title", tr("legend_editor.error.non_native"))

        options = {}
        title_value = self.fields["title"].get()
        if len(title_value) > MAX_LEGEND_TEXT_LENGTH:
            raise _LegendFieldError("title", tr("legend_editor.error.title"))
        if title_value != self.default_title or self._title_overridden:
            options["title"] = title_value

        columns = _parse_optional_int(self.fields["columns"].get(), "columns", tr("legend_editor.error.columns"))
        if columns is not None:
            options["columns"] = columns

        frame_choice = self.fields["frame"].get()
        if frame_choice == FRAME_SHOWN:
            options["frame"] = True
        elif frame_choice == FRAME_HIDDEN:
            options["frame"] = False

        for color_key, err_key in (("facecolor", "legend_editor.error.facecolor"),
                                   ("edgecolor", "legend_editor.error.edgecolor")):
            raw_color = self.fields[color_key].get().strip()
            if raw_color:
                try:
                    validate_legend_options({color_key: raw_color})
                except ValueError as error:
                    raise _LegendFieldError(color_key, translate_legend_error(error)) from error
                options[color_key] = raw_color

        width = _parse_optional_float(
            self.fields["width"].get(), "width", 0.0, MAX_LEGEND_BORDER_WIDTH, tr("legend_editor.error.width")
        )
        if width is not None:
            options["width"] = width

        alpha = _parse_optional_float(
            self.fields["alpha"].get(), "alpha", 0.0, 1.0, tr("legend_editor.error.alpha")
        )
        if alpha is not None:
            options["alpha"] = alpha

        if bool(self.fields["reverse"].get()):
            options["reverse"] = True

        labels = dict(self._preserved_hidden_labels)
        for entry in self.entries:
            val = self.entry_vars[entry.key].get()
            if not val:
                continue
            if len(val) > MAX_LEGEND_TEXT_LENGTH or val.startswith("_"):
                raise _LegendFieldError(f"label:{entry.key}", tr("legend_editor.error.entry_label"))
            labels[entry.key] = val
        if labels:
            options["labels"] = labels

        try:
            return validate_legend_options(options)
        except ValueError as error:
            text = str(error).casefold()
            target = "title"
            for fragment, field in _ENGINE_ERROR_FIELDS:
                if fragment in text:
                    target = field
                    break
            raise _LegendFieldError(target, translate_legend_error(error)) from error

    def reset_fields(self):
        """Reset all legend formatting fields to analysis defaults (pre-preview baseline)."""
        self.clear_errors()
        self._title_overridden = False
        self._preserved_hidden_labels = {}
        self.fields["title"].set(self.default_title)
        self.fields["columns"].set("")
        self.fields["frame"].set(FRAME_DEFAULT)
        self.fields["facecolor"].set("")
        self.fields["edgecolor"].set("")
        self.fields["width"].set("")
        self.fields["alpha"].set("")
        self.fields["reverse"].set(False)
        for var in self.entry_vars.values():
            var.set("")
        if self.preview_callback is not None and (self.previewed or self.initial_options):
            try:
                self.preview_callback({})
                self.previewed = True
            except ValueError as error:
                self.problem.configure(text=translate_legend_error(error))

    def preview(self):
        if self.busy_check and self.busy_check():
            self.problem.configure(text=tr("legend_editor.error.busy"))
            return False
        try:
            options = self.read_options()
        except _LegendFieldError as error:
            self.show_error(error.field, str(error))
            return False
        if self.preview_callback is not None:
            try:
                self.preview_callback(options)
            except ValueError as error:
                self.show_error("title", str(error))
                return False
            self.previewed = True
        self.clear_errors()
        return True

    def validate(self):
        if self.busy_check and self.busy_check():
            self.problem.configure(text=tr("legend_editor.error.busy"))
            return False
        try:
            self.result = self.read_options()
        except _LegendFieldError as error:
            self.result = None
            self.show_error(error.field, str(error))
            return False
        self.clear_errors()
        return True

    def ok(self, event=None):
        if not self.winfo_exists():
            return None
        if not self.validate():
            return "break"
        self.withdraw()
        self.update_idletasks()
        try:
            self.accepted = True
        finally:
            self.cancel()
        return None

    def cancel(self, event=None):
        if not self.accepted:
            if self.previewed and self.preview_callback is not None:
                self.preview_callback(None)
            self.result = None
        super().cancel(event)
