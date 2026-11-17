"""Transactional Tk editors for axis guides (ticks/lines) and shaded axis bands."""
from copy import deepcopy
from math import isfinite
from sys import float_info
import tkinter as tk
from tkinter import simpledialog, ttk

from . import ui_theme
from .axis_guides import (
    BAND_HATCHES,
    DEFAULT_BAND_ALPHA,
    DEFAULT_GUIDE_COLOR,
    DEFAULT_GUIDE_FONT_SIZE,
    DEFAULT_GUIDE_SIDE,
    DEFAULT_GUIDE_STYLE,
    DEFAULT_GUIDE_WIDTH,
    GUIDE_AXES,
    GUIDE_SIDES,
    GUIDE_STYLES,
    MAX_BANDS,
    MAX_GUIDES_TOTAL,
    axis_supports_guides,
    is_native_plot_axes,
    new_guide_id,
    normalise_bands,
    normalise_guides,
    ulp_close,
    validate_axis_guides_domain,
)
from .data import decimal_comma
from .graph_dialog import ChoiceBinding, pick_color
from .i18n import tr, translate_message

ERROR_COLOR = "#b00020"
HINT_COLOR = "#506575"

AXIS_LABELS = {"x": "axis_guides.axis.x", "y": "axis_guides.axis.y"}
STYLE_LABELS = {
    "-": "axis_guides.style.solid",
    "--": "axis_guides.style.dashed",
    ":": "axis_guides.style.dotted",
    "-.": "axis_guides.style.dash_dot",
}
SIDE_LABELS = {"primary": "axis_guides.side.primary", "opposite": "axis_guides.side.opposite"}
HATCH_LABELS = {
    "": "axis_guides.hatch.none",
    "/": "axis_guides.hatch.slash",
    "\\": "axis_guides.hatch.backslash",
    "|": "axis_guides.hatch.pipe",
    "-": "axis_guides.hatch.dash",
    "+": "axis_guides.hatch.plus",
    "x": "axis_guides.hatch.cross",
    ".": "axis_guides.hatch.dot",
    "o": "axis_guides.hatch.circle",
}

_GUIDE_ERROR_FIELDS = (
    ("coordinate", "value"),
    ("same coordinate", "value"),
    ("logarithmic", "value"),
    ("categorical", "axis"),
    ("scale does not support", "axis"),
    ("label color", "label_color"),
    ("font size", "font_size"),
    ("width", "width"),
    ("line style", "style"),
    ("side", "side"),
    ("label", "label"),
    ("color", "color"),
    ("tick, a line", "tick"),
    ("axis must be", "axis"),
)

_BAND_ERROR_FIELDS = (
    ("lower limit must be smaller", "lower"),
    ("limits must be finite", "lower"),
    ("logarithmic", "lower"),
    ("categorical", "axis"),
    ("scale does not support", "axis"),
    ("opacity", "alpha"),
    ("hatch", "hatch"),
    ("color", "color"),
    ("axis must be", "axis"),
)


def translate_guide_error(error):
    text = str(error)
    translated = translate_message(text, "axis_guides.error.")
    if translated != text:
        return translated
    return translate_message(text, "graph.error.")


def _format_num(value):
    return f"{float(value):g}"


def _parse_float(text, field, message):
    cleaned = text.strip()
    if not cleaned or "_" in cleaned:
        raise _DialogFieldError(field, message)
    try:
        value = float(decimal_comma(cleaned))
    except (TypeError, ValueError, OverflowError):
        raise _DialogFieldError(field, message) from None
    if not isfinite(value) or abs(value) > float_info.max:
        raise _DialogFieldError(field, message)
    return value


class _DialogFieldError(ValueError):
    """Validation failure tied to a specific widget key."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def _map_engine_error(error, mapping, default_field):
    text = str(error)
    lower = text.casefold()
    field = default_field
    for fragment, target in mapping:
        if fragment in lower:
            field = target
            break
    return _DialogFieldError(field, translate_guide_error(text))


class _ScrolledBody:
    """Vertically scrolling body frame keeping footer buttons visible on 1024x768 screens."""

    def __init__(self, master, height):
        panel_bg = ttk.Style(master).lookup("TLabel", "background") or ui_theme.SURFACE
        self.outer = ttk.Frame(master)
        scroll = ttk.Scrollbar(self.outer, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.canvas = tk.Canvas(self.outer, highlightthickness=0, background=panel_bg,
                                yscrollcommand=scroll.set, height=height)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=(4, 4, 8, 4))
        window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")

        def resize(_event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"),
                                  width=max(360, self.body.winfo_reqwidth()))

        self.body.bind("<Configure>", resize)
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))

    def reveal(self, widget):
        self.canvas.update_idletasks()
        total = max(1, self.body.winfo_height())
        top = widget.winfo_rooty() - self.body.winfo_rooty()
        bottom = top + widget.winfo_height()
        first, last = self.canvas.yview()
        if top < first * total or bottom > last * total:
            self.canvas.yview_moveto(max(0.0, (top - 12) / total))


def _default_axis(axes, scale_overrides):
    scales = scale_overrides or {}
    for dim in GUIDE_AXES:
        if axis_supports_guides(axes, dim, scales.get(dim)):
            return dim
    return "y"


class _SingleRecordDialog(simpledialog.Dialog):
    """Base transactional form for editing a single axis guide or band."""

    def __init__(self, parent, axes, title, *, preview=None, scale_overrides=None, busy=None):
        self.axes = axes
        self.preview_callback = preview
        self.scale_overrides = dict(scale_overrides or {})
        self.busy_check = busy
        self.previewed = False
        self.accepted = False
        self.error_widget = None
        self.result = None
        super().__init__(parent, title)

    def _scales(self):
        return {
            "xscale": self.scale_overrides.get("x", self.axes.xaxis.get_scale()),
            "yscale": self.scale_overrides.get("y", self.axes.yaxis.get_scale()),
        }

    def buttonbox(self):
        footer = ttk.Frame(self, padding=(8, 4, 8, 8))
        footer.pack(side="bottom", fill="x", before=self.body_frame)
        self.problem = ttk.Label(footer, wraplength=420, justify="left", foreground=ERROR_COLOR)
        self.problem.pack(side="top", fill="x", pady=(0, 4))
        self.cancel_button = ttk.Button(footer, text=tr("axis_guides.btn.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.ok_button = ttk.Button(footer, text=tr("axis_guides.btn.ok"), style="Action.TButton", command=self.ok)
        self.ok_button.pack(side="right", padx=6)
        self.preview_button = ttk.Button(footer, text=tr("axis_guides.btn.preview"), command=self.preview)
        self.preview_button.pack(side="right")
        for button in (self.preview_button, self.ok_button, self.cancel_button):
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def show_error(self, error):
        self.problem.configure(text=translate_guide_error(error))
        field = getattr(error, "field", None)
        widget = self.widgets.get(field) if field else None
        self.error_widget = widget
        if widget is not None:
            self.scrolled.reveal(widget)
            self.update_idletasks()
            widget.focus_set()
            if isinstance(widget, ttk.Entry):
                widget.select_range(0, "end")
                widget.icursor("end")

    def validate(self):
        if self.busy_check and self.busy_check():
            self.problem.configure(text=tr("axis_guides.error.busy"))
            return False
        try:
            self.result = self.read_record()
        except _DialogFieldError as error:
            self.result = None
            self.show_error(error)
            return False
        return True

    def preview(self):
        if self.busy_check and self.busy_check():
            self.problem.configure(text=tr("axis_guides.error.busy"))
            return False
        try:
            record = self.read_record()
        except _DialogFieldError as error:
            self.show_error(error)
            return False
        if self.preview_callback is None:
            self.problem.configure(text="")
            return True
        try:
            self.preview_callback(record)
        except ValueError as error:
            self.show_error(_map_engine_error(error, self._error_mapping(), self._default_field()))
            return False
        self.previewed = True
        self.problem.configure(text="")
        return True

    def ok(self, event=None):
        if not self.winfo_exists():
            return None
        if not self.validate():
            return "break"
        self.withdraw()
        self.update_idletasks()
        try:
            self.apply()
        finally:
            self.cancel()
        return None

    def apply(self):
        self.accepted = True

    def cancel(self, event=None):
        if not self.accepted:
            if self.previewed and self.preview_callback is not None:
                self.preview_callback(None)
            self.result = None
        super().cancel(event)


class GuideEditorDialog(_SingleRecordDialog):
    """Form dialog for creating or editing a single canonical axis guide record."""

    def __init__(self, parent, axes, record=None, *, preview=None, scale_overrides=None, busy=None):
        self.is_new = record is None
        default_axis = _default_axis(axes, scale_overrides)
        self.record = deepcopy(record) if record is not None else {
            "id": new_guide_id(),
            "axis": default_axis,
            "value": 1.0 if (scale_overrides or {}).get(default_axis, getattr(axes, default_axis + "axis").get_scale()) == "log" else 0.0,
            "tick": False,
            "line": True,
            "label": "",
            "color": DEFAULT_GUIDE_COLOR,
            "width": DEFAULT_GUIDE_WIDTH,
            "style": DEFAULT_GUIDE_STYLE,
            "visible": True,
        }
        title = tr("axis_guides.guide.add_title" if self.is_new else "axis_guides.guide.edit_title")
        super().__init__(parent, axes, title, preview=preview, scale_overrides=scale_overrides, busy=busy)

    @staticmethod
    def _error_mapping():
        return _GUIDE_ERROR_FIELDS

    @staticmethod
    def _default_field():
        return "value"

    def body(self, master):
        self.body_frame = master
        master.pack_configure(fill="both", expand=True)
        height = max(220, min(420, self.winfo_screenheight() - 260))
        self.scrolled = _ScrolledBody(master, height)
        self.scrolled.outer.pack(fill="both", expand=True)
        form = self.scrolled.body
        form.columnconfigure(1, weight=1)
        self.fields, self.widgets, self.bindings = {}, {}, {}

        row = 0
        row = self._add_choice(form, row, "axis", GUIDE_AXES, AXIS_LABELS, self.record["axis"])
        row = self._add_entry(form, row, "value", _format_num(self.record["value"]))
        row = self._add_check(form, row, "tick", self.record.get("tick", False))
        row = self._add_check(form, row, "line", self.record.get("line", True))
        row = self._add_check(form, row, "visible", self.record.get("visible", True))
        row = self._add_entry(form, row, "label", self.record.get("label", ""), width=26)
        row = self._add_color(form, row, "color", self.record.get("color", DEFAULT_GUIDE_COLOR))
        row = self._add_entry(form, row, "width", _format_num(self.record.get("width", DEFAULT_GUIDE_WIDTH)), width=12)
        row = self._add_choice(form, row, "style", GUIDE_STYLES, STYLE_LABELS, self.record.get("style", DEFAULT_GUIDE_STYLE))
        row = self._add_choice(form, row, "side", GUIDE_SIDES, SIDE_LABELS, self.record.get("side", DEFAULT_GUIDE_SIDE))
        row = self._add_color(form, row, "label_color", self.record.get("label_color", ""))
        raw_font = self.record.get("font_size")
        row = self._add_entry(form, row, "font_size", "" if raw_font is None else _format_num(raw_font), width=12)
        ttk.Label(form, text=tr("axis_guides.note.decimal_hint"), foreground=HINT_COLOR,
                  wraplength=360, justify="left").grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))
        return self.widgets["value"]

    def _add_choice(self, form, row, key, choices, labels, initial):
        ttk.Label(form, text=tr(f"axis_guides.field.{key}")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        var = tk.StringVar(self, initial)
        box = ttk.Combobox(form, state="readonly", width=22)
        box.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
        self.fields[key], self.widgets[key] = var, box
        self.bindings[key] = ChoiceBinding(box, var, choices, labels)
        return row + 1

    def _add_entry(self, form, row, key, initial, width=16):
        ttk.Label(form, text=tr(f"axis_guides.field.{key}")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        var = tk.StringVar(self, initial)
        entry = ttk.Entry(form, textvariable=var, width=width)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        self.fields[key], self.widgets[key] = var, entry
        return row + 1

    def _add_color(self, form, row, key, initial):
        ttk.Label(form, text=tr(f"axis_guides.field.{key}")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        var = tk.StringVar(self, initial)
        entry = ttk.Entry(form, textvariable=var, width=16)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        button = ttk.Button(form, text=tr("graph.field.pick"), command=lambda v=var: pick_color(self, v))
        button.grid(row=row, column=2, padx=(6, 0), pady=3)
        self.fields[key], self.widgets[key] = var, entry
        return row + 1

    def _add_check(self, form, row, key, initial):
        var = tk.BooleanVar(self, bool(initial))
        check = ttk.Checkbutton(form, text=tr(f"axis_guides.field.{key}"), variable=var)
        check.grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
        self.fields[key], self.widgets[key] = var, check
        return row + 1

    def read_record(self):
        value = _parse_float(self.fields["value"].get(), "value", tr("axis_guides.error.guide_value"))
        width = _parse_float(self.fields["width"].get(), "width", tr("axis_guides.error.guide_width"))
        raw = {
            "id": self.record["id"],
            "axis": self.fields["axis"].get(),
            "value": value,
            "tick": bool(self.fields["tick"].get()),
            "line": bool(self.fields["line"].get()),
            "visible": bool(self.fields["visible"].get()),
            "label": self.fields["label"].get(),
            "color": self.fields["color"].get().strip(),
            "width": width,
            "style": self.fields["style"].get(),
        }
        side = self.fields["side"].get()
        if side != DEFAULT_GUIDE_SIDE or "side" in self.record:
            raw["side"] = side
        label_color = self.fields["label_color"].get().strip()
        if label_color:
            raw["label_color"] = label_color
        font_size_text = self.fields["font_size"].get().strip()
        if font_size_text:
            raw["font_size"] = _parse_float(font_size_text, "font_size", tr("axis_guides.error.guide_font_size"))
        try:
            canonical = normalise_guides([raw])[0]
            validate_axis_guides_domain(self.axes, [canonical], (), **self._scales())
        except ValueError as error:
            raise _map_engine_error(error, _GUIDE_ERROR_FIELDS, "value") from None
        return canonical


class BandEditorDialog(_SingleRecordDialog):
    """Form dialog for creating or editing a single canonical shaded band record."""

    def __init__(self, parent, axes, record=None, *, preview=None, scale_overrides=None, busy=None):
        self.is_new = record is None
        default_axis = _default_axis(axes, scale_overrides)
        is_log = (scale_overrides or {}).get(default_axis, getattr(axes, default_axis + "axis").get_scale()) == "log"
        self.record = deepcopy(record) if record is not None else {
            "id": new_guide_id(),
            "axis": default_axis,
            "lower": 1.0 if is_log else 0.0,
            "upper": 10.0 if is_log else 1.0,
            "color": "#ccddee",
            "alpha": DEFAULT_BAND_ALPHA,
            "hatch": "",
            "visible": True,
        }
        title = tr("axis_guides.band.add_title" if self.is_new else "axis_guides.band.edit_title")
        super().__init__(parent, axes, title, preview=preview, scale_overrides=scale_overrides, busy=busy)

    @staticmethod
    def _error_mapping():
        return _BAND_ERROR_FIELDS

    @staticmethod
    def _default_field():
        return "lower"

    def body(self, master):
        self.body_frame = master
        master.pack_configure(fill="both", expand=True)
        height = max(200, min(360, self.winfo_screenheight() - 260))
        self.scrolled = _ScrolledBody(master, height)
        self.scrolled.outer.pack(fill="both", expand=True)
        form = self.scrolled.body
        form.columnconfigure(1, weight=1)
        self.fields, self.widgets, self.bindings = {}, {}, {}

        row = 0
        for key, choices, labels, val in (
            ("axis", GUIDE_AXES, AXIS_LABELS, self.record["axis"]),
        ):
            ttk.Label(form, text=tr(f"axis_guides.field.{key}")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            var = tk.StringVar(self, val)
            box = ttk.Combobox(form, state="readonly", width=22)
            box.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
            self.fields[key], self.widgets[key] = var, box
            self.bindings[key] = ChoiceBinding(box, var, choices, labels)
            row += 1

        for key, initial in (
            ("lower", _format_num(self.record["lower"])),
            ("upper", _format_num(self.record["upper"])),
        ):
            ttk.Label(form, text=tr(f"axis_guides.field.{key}")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            var = tk.StringVar(self, initial)
            entry = ttk.Entry(form, textvariable=var, width=16)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self.fields[key], self.widgets[key] = var, entry
            row += 1

        ttk.Label(form, text=tr("axis_guides.field.color")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        color_var = tk.StringVar(self, self.record["color"])
        color_entry = ttk.Entry(form, textvariable=color_var, width=16)
        color_entry.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(form, text=tr("graph.field.pick"), command=lambda: pick_color(self, color_var)).grid(
            row=row, column=2, padx=(6, 0), pady=3)
        self.fields["color"], self.widgets["color"] = color_var, color_entry
        row += 1

        ttk.Label(form, text=tr("axis_guides.field.alpha")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        alpha_var = tk.StringVar(self, _format_num(self.record.get("alpha", DEFAULT_BAND_ALPHA)))
        alpha_entry = ttk.Entry(form, textvariable=alpha_var, width=12)
        alpha_entry.grid(row=row, column=1, sticky="ew", pady=3)
        self.fields["alpha"], self.widgets["alpha"] = alpha_var, alpha_entry
        row += 1

        ttk.Label(form, text=tr("axis_guides.field.hatch")).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        hatch_var = tk.StringVar(self, self.record.get("hatch", ""))
        hatch_box = ttk.Combobox(form, state="readonly", width=22)
        hatch_box.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
        self.fields["hatch"], self.widgets["hatch"] = hatch_var, hatch_box
        self.bindings["hatch"] = ChoiceBinding(hatch_box, hatch_var, BAND_HATCHES, HATCH_LABELS)
        row += 1

        vis_var = tk.BooleanVar(self, bool(self.record.get("visible", True)))
        vis_check = ttk.Checkbutton(form, text=tr("axis_guides.field.visible"), variable=vis_var)
        vis_check.grid(row=row, column=0, columnspan=3, sticky="w", pady=3)
        self.fields["visible"], self.widgets["visible"] = vis_var, vis_check
        return self.widgets["lower"]

    def read_record(self):
        lower = _parse_float(self.fields["lower"].get(), "lower", tr("axis_guides.error.band_bounds"))
        upper = _parse_float(self.fields["upper"].get(), "upper", tr("axis_guides.error.band_bounds"))
        alpha = _parse_float(self.fields["alpha"].get(), "alpha", tr("axis_guides.error.band_alpha"))
        raw = {
            "id": self.record["id"],
            "axis": self.fields["axis"].get(),
            "lower": lower,
            "upper": upper,
            "color": self.fields["color"].get().strip(),
            "alpha": alpha,
            "hatch": self.fields["hatch"].get(),
            "visible": bool(self.fields["visible"].get()),
        }
        try:
            canonical = normalise_bands([raw])[0]
            validate_axis_guides_domain(self.axes, (), [canonical], **self._scales())
        except ValueError as error:
            raise _map_engine_error(error, _BAND_ERROR_FIELDS, "lower") from None
        return canonical


class _BaseListDialog(simpledialog.Dialog):
    """Shared transactional list editor for axis guides and bands."""

    _max_items = 0
    _columns = ()

    def __init__(self, parent, axes, records, title, *, preview=None, scale_overrides=None, busy=None):
        self.axes = axes
        self.confirmed = deepcopy(list(records or []))
        self.records = deepcopy(self.confirmed)
        self.preview_callback = preview
        self.scale_overrides = dict(scale_overrides or {})
        self.busy_check = busy
        self.shown = None
        self.result = None
        super().__init__(parent, title)

    def _scales(self):
        return {
            "xscale": self.scale_overrides.get("x", self.axes.xaxis.get_scale()),
            "yscale": self.scale_overrides.get("y", self.axes.yaxis.get_scale()),
        }

    def _support_state(self):
        scales = self.scale_overrides or {}
        if not is_native_plot_axes(self.axes):
            return False, False, tr("axis_guides.note.unsupported_both")
        x_ok = axis_supports_guides(self.axes, "x", scales.get("x"))
        y_ok = axis_supports_guides(self.axes, "y", scales.get("y"))
        if not x_ok and not y_ok:
            return False, False, tr("axis_guides.note.unsupported_both")
        if not x_ok:
            return False, True, tr("axis_guides.note.unsupported_one", axis="X", other="Y")
        if not y_ok:
            return True, False, tr("axis_guides.note.unsupported_one", axis="Y", other="X")
        return True, True, ""

    def body(self, master):
        self.body_frame = master
        master.pack_configure(fill="both", expand=True)
        body = ttk.Frame(master, padding=8)
        body.pack(fill="both", expand=True)

        x_ok, y_ok, note = self._support_state()
        self._any_supported = x_ok or y_ok
        if note:
            ttk.Label(body, text=note, foreground=HINT_COLOR if self._any_supported else ERROR_COLOR,
                      wraplength=600, justify="left").pack(fill="x", pady=(0, 6))

        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table,
            columns=[col[0] for col in self._columns],
            show="headings",
            height=max(4, min(10, (self.winfo_screenheight() - 400) // 24)),
            selectmode="browse",
        )
        for key, label, width in self._columns:
            self.tree.heading(key, text=label if label == "#" else tr(label))
            self.tree.column(key, width=width, stretch=key == "label", anchor="w")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-Button-1>", lambda event: self.edit() if self.tree.identify_row(event.y) else None)
        self.tree.bind("<Delete>", lambda _event: self.remove())
        self.tree.bind("<Return>", lambda _event: self.edit() or "break")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.update_buttons())

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(6, 0))
        self.buttons = {}
        for key, command in (
            ("add", self.add),
            ("edit", self.edit),
            ("duplicate", self.duplicate),
            ("remove", self.remove),
            ("preview", self.preview),
        ):
            button = ttk.Button(buttons, text=tr(f"axis_guides.btn.{key}"), command=command)
            button.pack(side="left", padx=(0, 4))
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
            self.buttons[key] = button

        self.message = ttk.Label(body, wraplength=600, justify="left", foreground=ERROR_COLOR)
        self.message.pack(fill="x", pady=(6, 0))
        self.fill(0 if self.records else None)
        return self.tree

    def buttonbox(self):
        row = ttk.Frame(self, padding=(8, 4, 8, 8))
        row.pack(side="bottom", fill="x", before=self.body_frame)
        self.cancel_button = ttk.Button(row, text=tr("axis_guides.btn.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.apply_button = ttk.Button(row, text=tr("axis_guides.btn.apply"), style="Action.TButton", command=self.ok)
        self.apply_button.pack(side="right", padx=6)
        for button in (self.apply_button, self.cancel_button):
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
        self.bind("<Escape>", self.cancel)

    def selected_index(self):
        selected = self.tree.selection()
        return int(selected[0]) if selected else None

    def _select_row(self, index):
        if index is None or not self.records:
            return
        iid = str(max(0, min(index, len(self.records) - 1)))
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)

    def fill(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(self.records):
            self.tree.insert("", "end", iid=str(index), values=self._row_values(index, record))
        self._select_row(selected)
        self.update_buttons()

    def update_buttons(self):
        index = self.selected_index()
        full = len(self.records) >= self._max_items
        states = {
            "add": self._any_supported and not full,
            "edit": self._any_supported and index is not None,
            "duplicate": self._any_supported and index is not None and not full,
            "remove": index is not None,
            "preview": self._any_supported or bool(self.records),
        }
        for key, enabled in states.items():
            self.buttons[key].state(["!disabled"] if enabled else ["disabled"])

    def _validate_records(self):
        raise NotImplementedError

    def _find_problem_row(self):
        return None

    def _show_list_error(self, error):
        self.message.configure(text=translate_guide_error(error))
        row_index = self._find_problem_row()
        if row_index is not None:
            self._select_row(row_index)

    def show_preview(self, records):
        if self.preview_callback is None:
            return
        self.preview_callback(None if records is None else deepcopy(records))
        self.shown = None if records is None else deepcopy(records)
        self.message.configure(text="")

    def child_preview(self, index):
        def callback(record):
            if record is None:
                self.show_preview(self.shown)
                return
            candidate = deepcopy(self.records)
            if index is None:
                candidate.append(record)
            else:
                candidate[index] = record
            self._validate_list_candidate(candidate)
            if self.preview_callback is not None:
                self.preview_callback(candidate)
        return callback

    def preview(self):
        if self.busy_check and self.busy_check():
            self.message.configure(text=tr("axis_guides.error.busy"))
            return
        try:
            validated = self._validate_records()
            self.show_preview(validated)
        except ValueError as error:
            self._show_list_error(error)

    def refresh_preview(self):
        if self.shown is not None:
            try:
                validated = self._validate_records()
                self.show_preview(validated)
            except ValueError as error:
                self._show_list_error(error)

    def add(self):
        if (self.busy_check and self.busy_check()) or not self._any_supported or len(self.records) >= self._max_items:
            return
        dialog = self._editor_class(
            self,
            self.axes,
            preview=self.child_preview(None),
            scale_overrides=self.scale_overrides,
            busy=self.busy_check,
        )
        self.grab_set()
        if dialog.result is not None:
            self.records.append(dialog.result)
            self.fill(len(self.records) - 1)
            self.message.configure(text="")
            self.refresh_preview()
        self.tree.focus_set()

    def edit(self):
        if (self.busy_check and self.busy_check()) or not self._any_supported:
            return
        index = self.selected_index()
        if index is None:
            return
        dialog = self._editor_class(
            self,
            self.axes,
            self.records[index],
            preview=self.child_preview(index),
            scale_overrides=self.scale_overrides,
            busy=self.busy_check,
        )
        self.grab_set()
        if dialog.result is not None:
            self.records[index] = dialog.result
            self.fill(index)
            self.message.configure(text="")
            self.refresh_preview()
        self.tree.focus_set()

    def duplicate(self):
        if (self.busy_check and self.busy_check()) or not self._any_supported or len(self.records) >= self._max_items:
            return
        index = self.selected_index()
        if index is None:
            return
        copied = deepcopy(self.records[index])
        copied["id"] = new_guide_id()
        self.records.insert(index + 1, copied)
        self.fill(index + 1)
        self.message.configure(text="")
        self.refresh_preview()

    def remove(self):
        if self.busy_check and self.busy_check():
            return
        index = self.selected_index()
        if index is None:
            return
        del self.records[index]
        self.fill(index)
        self.message.configure(text="")
        self.refresh_preview()

    def ok(self, event=None):
        if not self.winfo_exists():
            return None
        return super().ok(event)

    def validate(self):
        if self.busy_check and self.busy_check():
            self.message.configure(text=tr("axis_guides.error.busy"))
            return False
        try:
            self.result = self._validate_records()
        except ValueError as error:
            self.result = None
            self._show_list_error(error)
            return False
        return True

    def apply(self):
        pass

    def cancel(self, event=None):
        if self.shown is not None and self.result is None:
            self.show_preview(None)
        super().cancel(event)


class AxisGuidesDialog(_BaseListDialog):
    """Manage additional ticks, labels, and reference grid lines for one graph."""

    _max_items = MAX_GUIDES_TOTAL
    _editor_class = GuideEditorDialog
    _columns = (
        ("number", "#", 32),
        ("axis", "axis_guides.col.axis", 44),
        ("value", "axis_guides.col.value", 88),
        ("tick", "axis_guides.col.tick", 54),
        ("line", "axis_guides.col.line", 54),
        ("label", "axis_guides.col.label", 180),
        ("side", "axis_guides.col.side", 76),
        ("visible", "axis_guides.col.visible", 60),
    )

    def __init__(self, parent, axes, records, *, preview=None, scale_overrides=None, busy=None):
        super().__init__(
            parent,
            axes,
            records,
            tr("axis_guides.guides.title"),
            preview=preview,
            scale_overrides=scale_overrides,
            busy=busy,
        )

    @staticmethod
    def _row_values(index, record):
        yes, no = tr("axis_guides.yes"), tr("axis_guides.no")
        side_key = SIDE_LABELS[record.get("side", DEFAULT_GUIDE_SIDE)]
        return (
            index + 1,
            record["axis"].upper(),
            _format_num(record["value"]),
            yes if record.get("tick", False) else no,
            yes if record.get("line", True) else no,
            record.get("label", ""),
            tr(side_key),
            yes if record.get("visible", True) else no,
        )

    def _validate_list_candidate(self, records):
        normalised = normalise_guides(records)
        validate_axis_guides_domain(self.axes, normalised, (), **self._scales())
        return normalised

    def _validate_records(self):
        return self._validate_list_candidate(self.records)

    def _find_problem_row(self):
        seen_ticks = {"x": [], "y": []}
        for index, record in enumerate(self.records):
            try:
                norm = normalise_guides([record])
                validate_axis_guides_domain(self.axes, norm, (), **self._scales())
            except ValueError:
                return index
            item = norm[0]
            if item["visible"] and item["tick"]:
                axis = item["axis"]
                if any(ulp_close(v, item["value"]) for v in seen_ticks[axis]):
                    return index
                seen_ticks[axis].append(item["value"])
        return None


class AxisBandsDialog(_BaseListDialog):
    """Manage shaded axis ranges for one graph."""

    _max_items = MAX_BANDS
    _editor_class = BandEditorDialog
    _columns = (
        ("number", "#", 32),
        ("axis", "axis_guides.col.axis", 44),
        ("lower", "axis_guides.col.lower", 80),
        ("upper", "axis_guides.col.upper", 80),
        ("color", "axis_guides.col.color", 90),
        ("alpha", "axis_guides.col.alpha", 64),
        ("hatch", "axis_guides.col.hatch", 110),
        ("visible", "axis_guides.col.visible", 60),
    )

    def __init__(self, parent, axes, records, *, preview=None, scale_overrides=None, busy=None):
        super().__init__(
            parent,
            axes,
            records,
            tr("axis_guides.bands.title"),
            preview=preview,
            scale_overrides=scale_overrides,
            busy=busy,
        )

    @staticmethod
    def _row_values(index, record):
        yes, no = tr("axis_guides.yes"), tr("axis_guides.no")
        hatch = record.get("hatch", "")
        return (
            index + 1,
            record["axis"].upper(),
            _format_num(record["lower"]),
            _format_num(record["upper"]),
            record["color"],
            _format_num(record.get("alpha", DEFAULT_BAND_ALPHA)),
            tr(HATCH_LABELS.get(hatch, "axis_guides.hatch.none")),
            yes if record.get("visible", True) else no,
        )

    def _validate_list_candidate(self, records):
        normalised = normalise_bands(records)
        validate_axis_guides_domain(self.axes, (), normalised, **self._scales())
        return normalised

    def _validate_records(self):
        return self._validate_list_candidate(self.records)

    def _find_problem_row(self):
        for index, record in enumerate(self.records):
            try:
                norm = normalise_bands([record])
                validate_axis_guides_domain(self.axes, (), norm, **self._scales())
            except ValueError:
                return index
        return None
