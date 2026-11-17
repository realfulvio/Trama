"""Keyboard editor for the native lines, rectangles and ellipses of one graph.

``GraphShapesDialog`` keeps a draft list of canonical shape records; ``ShapeEditor`` edits one record.
Neither dialog touches ``run.style``: previews go through the ``preview`` callback supplied by the app
(which applies a candidate style to the figure), and the caller commits the dialog result on Apply.
"""
from copy import deepcopy
import tkinter as tk
from tkinter import simpledialog, ttk
import uuid

from . import ui_theme
from .data import decimal_comma
from .graph_dialog import ChoiceBinding, pick_color
from .graph_shapes import (ARROW_HEADS, ARROW_SIZE, ARROW_STYLES, HATCHES, KINDS, LAYERS, LINE_STYLES,
                           MAX_SHAPES, UNITS, on_axis_domain, validate_shape, validate_shapes)
from .i18n import tr

BACKGROUND = "#f4f6f8"
ERROR = "#b00020"
DEFAULT_SHAPE = {"kind": "line", "units": "axes", "points": [[.2, .3], [.8, .7]], "stroke": "#216a94",
                 "width": 1.5, "line_style": "solid", "fill": None, "alpha": 1.0, "layer": "above"}
CHOICES = {"kind": KINDS, "units": UNITS, "line_style": LINE_STYLES, "layer": LAYERS,
           "arrow_heads": ARROW_HEADS, "arrow_style": ARROW_STYLES, "hatch": HATCHES}
OPTION_DEFAULTS = {"arrow_heads": "none", "arrow_style": "open", "arrow_size": ARROW_SIZE, "hatch": "none"}
POINT_FIELDS = ("x1", "y1", "x2", "y2")
# Engine messages (English, raised by ``validate_shape``) mapped to the control and the catalog message.
ENGINE_ERRORS = (
    ("pattern color", "hatch_color", "shape.error.hatch_color"),
    ("arrowhead size", "arrow_size", "shape.error.arrow_size"),
    ("arrowhead style", "arrow_style", "shape.error.arrow_style"),
    ("for the arrowheads", "arrow_heads", "shape.error.arrow_heads"),
    ("fill pattern", "hatch", "shape.error.hatch"),
    ("Arrowhead settings require", "kind", "shape.error.kind"),
    ("shape kind", "kind", "shape.error.kind"),
    ("axes or data coordinates", "units", "shape.error.units"),
    ("finite X and Y", "x1", "shape.error.coordinates"),
    ("Plot fractions", None, "shape.error.fractions"),
    ("distinct endpoints", "x2", "shape.error.line_zero"),
    ("positive width and height", "x2", "shape.error.box_zero"),
    ("stroke color", "stroke", "shape.error.stroke"),
    ("stroke width", "width", "shape.error.width"),
    ("line style", "line_style", "shape.error.line_style"),
    ("fill", "fill", "shape.error.fill"),
    ("opacity", "alpha", "shape.error.alpha"),
    ("shape layer", "layer", "shape.error.layer"),
)


def new_shape_id():
    return str(uuid.uuid4())


def default_shape():
    return {"id": new_shape_id(), **deepcopy(DEFAULT_SHAPE)}


def format_number(value):
    return f"{value:g}"


class _ShapeFieldError(ValueError):
    """A validation problem that belongs to one control of ``ShapeEditor``."""

    def __init__(self, field, key):
        super().__init__(tr(key))
        self.field = field
        self.key = key


def _resolve_choice(binding, value, field):
    """The canonical value of one choice control: canonical values pass, this control's labels map back."""
    if value in binding.values:
        return value
    if value in binding.labels:
        return binding.values[binding.labels.index(value)]
    raise _ShapeFieldError(field, f"shape.error.{field}")


def _parse_number(text, field, key):
    try:
        value = float(decimal_comma(text.strip()))
    except (TypeError, ValueError):
        raise _ShapeFieldError(field, key) from None
    if value != value or value in (float("inf"), float("-inf")):
        raise _ShapeFieldError(field, key)
    return value


def _fraction_field(points):
    for name, value in zip(POINT_FIELDS, (*points[0], *points[1])):
        if not 0 <= value <= 1:
            return name
    return "x1"


def engine_field_error(error, points=None):
    """Map an engine ``ValueError`` to the control that caused it."""
    text = str(error)
    for fragment, field, key in ENGINE_ERRORS:
        if fragment.lower() in text.lower():
            return _ShapeFieldError(field or _fraction_field(points or [[0, 0], [0, 0]]), key)
    return _ShapeFieldError("x1", "shape.error.coordinates")


def describe_shape(record):
    (x1, y1), (x2, y2) = record["points"]
    kind = record["kind"]
    if kind == "line" and record.get("arrow_heads", "none") != "none":
        kind = "capped_line" if record.get("arrow_style") == "cap" else "arrow"
    return (tr(f"shape.option.{kind}"), tr(f"shape.option.{record['units']}"),
            tr(f"shape.option.{record['layer']}"),
            f"({format_number(x1)}; {format_number(y1)}) – ({format_number(x2)}; {format_number(y2)})")


class _Scrolled:
    """A vertically scrolling body for a dialog whose buttons stay packed at the bottom."""

    def __init__(self, master, height):
        self.outer = ttk.Frame(master)
        scroll = ttk.Scrollbar(self.outer, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.canvas = tk.Canvas(self.outer, highlightthickness=0, background=BACKGROUND, yscrollcommand=scroll.set,
                                height=height)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=(2, 2, 8, 2))
        window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")

        def resize(_event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"), width=self.body.winfo_reqwidth())

        self.body.bind("<Configure>", resize)
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))

    def reveal(self, widget):
        """Scroll so that ``widget`` is visible."""
        self.canvas.update_idletasks()
        total = max(1, self.body.winfo_height())
        top = widget.winfo_rooty() - self.body.winfo_rooty()
        bottom = top + widget.winfo_height()
        first, last = self.canvas.yview()
        if top < first * total or bottom > last * total:
            self.canvas.yview_moveto(max(0.0, (top - 12) / total))


class _PagedBody:
    """Preserve scrolling/focus behavior across separate appearance and position pages."""

    def __init__(self, master, height):
        self.outer = ttk.Notebook(master)
        self.pages, self.scrollers = {}, {}
        for name in ("appearance", "position"):
            page = self.pages[name] = ttk.Frame(self.outer)
            scrolled = self.scrollers[name] = _Scrolled(page, height)
            scrolled.outer.pack(fill="both", expand=True)
            self.outer.add(page, text=tr("shape.page." + name))

    @property
    def canvas(self):
        selected = self.outer.select()
        name = next(name for name, page in self.pages.items() if str(page) == selected)
        return self.scrollers[name].canvas

    def reveal(self, widget):
        for name, scrolled in self.scrollers.items():
            if str(widget).startswith(str(scrolled.body) + "."):
                if self.outer.select() != str(self.pages[name]):
                    self.outer.select(self.pages[name])
                    self.outer.update_idletasks()
                scrolled.reveal(widget)
                return


class ShapeEditor(simpledialog.Dialog):
    """Edit one shape record. ``result`` is the canonical record after OK, otherwise None.

    ``preview(record)`` shows a validated candidate on the graph and returns a warning or None; ``preview(None)``
    asks the parent to restore its own preview. The original record is never modified.
    """

    def __init__(self, parent, axes, record=None, *, preview=None):
        self.axes = axes
        self.new = record is None
        self.record = deepcopy(record) if record is not None else default_shape()
        self.preview_callback = preview
        self.previewed = False
        self.accepted = False
        self.result = None
        super().__init__(parent, tr("shape.add") if self.new else tr("shape.edit"))

    # Layout ---------------------------------------------------------------------------------------------------
    def body(self, master):
        self.configure(background=BACKGROUND)
        self.body_frame = master
        master.pack_configure(fill="both", expand=True)
        style = ttk.Style(self)
        panel_color = style.lookup("TLabel", "background") or BACKGROUND
        style.configure("Shape.Group.TLabelframe", background=panel_color, bordercolor="#d6e0e9",
                        lightcolor="#d6e0e9", darkcolor="#d6e0e9", borderwidth=1, relief="solid")
        style.configure("Shape.Group.TLabelframe.Label", background=panel_color, foreground="#244c69",
                        font=ui_theme.font(9, "bold"))
        height = max(220, min(350, self.winfo_screenheight() - 300))
        self.scrolled = _PagedBody(master, height)
        self.scrolled.outer.pack(fill="both", expand=True)
        self.notebook, self.pages = self.scrolled.outer, self.scrolled.pages
        self.fields, self.widgets, self.bindings = {}, {}, {}
        appearance = self.scrolled.scrollers["appearance"].body
        position = self.scrolled.scrollers["position"].body
        columns = 1 if self.winfo_screenwidth() < 900 else 2
        header = ttk.Frame(appearance)
        header.grid(row=0, column=0, columnspan=columns, sticky="ew", pady=(0, 6))
        self._choice(header, 0, "kind")

        def group(name, index):
            frame = ttk.LabelFrame(appearance, text=tr("shape.group." + name), padding=8,
                                   style="Shape.Group.TLabelframe")
            frame.grid(row=1 + index // columns, column=index % columns, sticky="nsew", padx=3, pady=3)
            return frame

        stroke, fill_form = group("stroke", 0), group("fill", 1)
        endings, order = group("endings", 2), group("order", 3)
        self._entry(stroke, 0, 1, "stroke", self.record["stroke"], width=14, label="shape.stroke")
        self.widgets["stroke_pick"] = ttk.Button(stroke, text=tr("graph.field.pick"),
                                                 command=lambda: pick_color(self, self.fields["stroke"]))
        self.widgets["stroke_pick"].grid(row=0, column=2, columnspan=2, sticky="w", padx=(6, 0))
        self._entry(stroke, 1, 1, "width", format_number(self.record["width"]), width=10, label="shape.width")
        self._choice(stroke, 2, "line_style")
        self._choice(endings, 0, "arrow_heads")
        self._choice(endings, 1, "arrow_style")
        self._entry(endings, 2, 1, "arrow_size", format_number(self.record.get("arrow_size", ARROW_SIZE)),
                    width=10, label="shape.arrow_size")
        fill = self.record["fill"]
        self._entry(fill_form, 0, 1, "fill", "" if fill is None else fill, width=14, label="shape.fill")
        self.widgets["fill_pick"] = ttk.Button(fill_form, text=tr("graph.field.pick"),
                                               command=lambda: pick_color(self, self.fields["fill"]))
        self.widgets["fill_pick"].grid(row=0, column=2, columnspan=2, sticky="w", padx=(6, 0))
        self._choice(fill_form, 1, "hatch")
        self._entry(fill_form, 2, 1, "hatch_color", self.record.get("hatch_color", ""), width=14,
                    label="shape.hatch_color")
        self.widgets["hatch_color_pick"] = ttk.Button(fill_form, text=tr("graph.field.pick"),
            command=lambda: pick_color(self, self.fields["hatch_color"]))
        self.widgets["hatch_color_pick"].grid(row=2, column=2, columnspan=2, sticky="w", padx=(6, 0))
        self.fill_hint = ttk.Label(fill_form, text=tr("shape.fill_hint"), foreground="#506575", wraplength=270,
                                   justify="left")
        self.fill_hint.grid(row=3, column=0, columnspan=4, sticky="w", pady=(0, 4))
        self._entry(order, 0, 1, "alpha", format_number(self.record["alpha"]), width=10, label="shape.alpha")
        self._choice(order, 1, "layer")
        form = position
        form.columnconfigure(1, weight=1)
        row = self._choice(form, 0, "units")
        ttk.Label(form, text=tr("shape.axis_hint"), foreground="#506575", wraplength=380, justify="left").grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(0, 4))
        row += 1
        (x1, y1), (x2, y2) = self.record["points"]
        for label, names, values in (("shape.point1", ("x1", "y1"), (x1, y1)),
                                     ("shape.point2", ("x2", "y2"), (x2, y2))):
            ttk.Label(form, text=tr(label)).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
            for column, (name, value) in enumerate(zip(names, values), 1):
                self._entry(form, row, column, name, format_number(value), width=10)
            row += 1
        self.fields["kind"].trace_add("write", lambda *_: self.sync_kind())
        self.fields["arrow_heads"].trace_add("write", lambda *_: self.sync_kind())
        self.fields["hatch"].trace_add("write", lambda *_: self.sync_kind())
        self.sync_kind()
        return self.widgets["kind"]

    def _choice(self, form, row, key):
        ttk.Label(form, text=tr(f"shape.{key}")).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
        variable = tk.StringVar(self, self.record.get(key, OPTION_DEFAULTS.get(key)))
        box = ttk.Combobox(form, state="readonly", width=26)
        box.grid(row=row, column=1, columnspan=3, sticky="w", pady=3)
        labels = {value: f"shape.option.{value}" for value in CHOICES[key]}
        self.fields[key], self.widgets[key] = variable, box
        box.bind("<FocusIn>", lambda event: self.scrolled.reveal(event.widget), add="+")
        self.bindings[key] = ChoiceBinding(box, variable, CHOICES[key], labels)
        return row + 1

    def _entry(self, form, row, column, key, value, *, width, label=None):
        if label:
            ttk.Label(form, text=tr(label)).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
        self.fields[key] = tk.StringVar(self, value)
        entry = ttk.Entry(form, textvariable=self.fields[key], width=width)
        entry.grid(row=row, column=column, sticky="w", padx=(0, 6), pady=3)
        entry.bind("<FocusIn>", lambda event: self.scrolled.reveal(event.widget), add="+")
        self.widgets[key] = entry
        return entry

    def buttonbox(self):
        footer = ttk.Frame(self, padding=(8, 4, 8, 8))
        # Packed before the body so that a short screen shrinks the scrolling body, never the buttons.
        footer.pack(side="bottom", fill="x", before=self.body_frame)
        self.problem = ttk.Label(footer, wraplength=420, justify="left", foreground=ERROR)
        self.problem.pack(side="top", fill="x", pady=(0, 4))
        self.cancel_button = ttk.Button(footer, text=tr("setup.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.ok_button = ttk.Button(footer, text=tr("language.ok"), style="Action.TButton", command=self.ok)
        self.ok_button.pack(side="right", padx=6)
        self.preview_button = ttk.Button(footer, text=tr("shape.preview"), command=self.preview)
        self.preview_button.pack(side="right")
        for button in (self.preview_button, self.ok_button, self.cancel_button):
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def sync_kind(self):
        try:
            kind = _resolve_choice(self.bindings["kind"], self.fields["kind"].get(), "kind")
            heads = _resolve_choice(self.bindings["arrow_heads"], self.fields["arrow_heads"].get(), "arrow_heads")
        except _ShapeFieldError:
            kind, heads = None, "none"
        state = ["!disabled"] if kind in ("rectangle", "ellipse") else ["disabled"]
        for key in ("fill", "fill_pick", "hatch"):
            self.widgets[key].state(state)
        try:
            hatch = _resolve_choice(self.bindings["hatch"], self.fields["hatch"].get(), "hatch")
        except _ShapeFieldError:
            hatch = "none"
        pattern_state = ["!disabled"] if kind in ("rectangle", "ellipse") and hatch != "none" else ["disabled"]
        for key in ("hatch_color", "hatch_color_pick"):
            self.widgets[key].state(pattern_state)
        self.widgets["arrow_heads"].state(["!disabled"] if kind == "line" else ["disabled"])
        active = kind == "line" and heads != "none"
        for key in ("arrow_style", "arrow_size"):
            self.widgets[key].state(["!disabled"] if active else ["disabled"])

    # Validation -----------------------------------------------------------------------------------------------
    def read_record(self):
        """The canonical record described by the controls; raises ``_ShapeFieldError``."""
        record = {"id": self.record["id"]}
        for key in ("kind", "units"):
            record[key] = _resolve_choice(self.bindings[key], self.fields[key].get(), key)
        values = [_parse_number(self.fields[name].get(), name, "shape.error.coordinates") for name in POINT_FIELDS]
        record["points"] = [values[:2], values[2:]]
        record["stroke"] = self.fields["stroke"].get().strip()
        record["width"] = _parse_number(self.fields["width"].get(), "width", "shape.error.width")
        record["line_style"] = _resolve_choice(self.bindings["line_style"], self.fields["line_style"].get(),
                                               "line_style")
        fill = self.fields["fill"].get().strip()
        # A line has no interior: its fill is always None, whatever the disabled field still shows.
        record["fill"] = None if record["kind"] == "line" or not fill else fill
        record["alpha"] = _parse_number(self.fields["alpha"].get(), "alpha", "shape.error.alpha")
        record["layer"] = _resolve_choice(self.bindings["layer"], self.fields["layer"].get(), "layer")
        if record["kind"] == "line":
            heads = _resolve_choice(self.bindings["arrow_heads"], self.fields["arrow_heads"].get(), "arrow_heads")
            values = {"arrow_heads": heads}
            if heads != "none":
                values["arrow_style"] = _resolve_choice(self.bindings["arrow_style"],
                                                        self.fields["arrow_style"].get(), "arrow_style")
                values["arrow_size"] = _parse_number(self.fields["arrow_size"].get(), "arrow_size", "shape.error.arrow_size")
            else:
                # Disabled inputs do not trap validation or overwrite confirmed settings.
                values.update({key: self.record[key] for key in ("arrow_style", "arrow_size") if key in self.record})
            record.update({key: value for key, value in values.items()
                           if key in self.record or value != OPTION_DEFAULTS[key]})
        else:
            hatch = _resolve_choice(self.bindings["hatch"], self.fields["hatch"].get(), "hatch")
            if "hatch" in self.record or hatch != "none":
                record["hatch"] = hatch
            if hatch == "none":
                if "hatch_color" in self.record:
                    record["hatch_color"] = self.record["hatch_color"]
            elif color := self.fields["hatch_color"].get().strip():
                record["hatch_color"] = color
        try:
            canonical = validate_shape(record)
        except ValueError as error:
            raise engine_field_error(error, record["points"]) from None
        if not on_axis_domain(self.axes, canonical):
            raise _ShapeFieldError("x1", "shape.error.axis_domain")
        return canonical

    def show_error(self, error):
        self.problem.configure(text=str(error))
        widget = self.widgets.get(error.field)
        if widget is not None:
            self.scrolled.reveal(widget)
            widget.focus_set()
            if isinstance(widget, ttk.Entry):
                widget.select_range(0, "end")
                widget.icursor("end")

    def validate(self):
        try:
            self.result = self.read_record()
        except _ShapeFieldError as error:
            self.result = None
            self.show_error(error)
            return False
        return True

    def preview(self):
        try:
            record = self.read_record()
        except _ShapeFieldError as error:
            self.show_error(error)
            return False
        if self.preview_callback is None:
            return True
        try:
            warning = self.preview_callback(record)
        except ValueError as error:
            self.problem.configure(text=str(error))
            return False
        self.previewed = True
        self.problem.configure(text=warning or "")
        return True

    def ok(self, event=None):
        # A closed editor has nothing left to confirm.
        if not self.winfo_exists():
            return None
        # Unlike ``simpledialog.Dialog.ok``, keep the focus on the field that failed validation.
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
        # ``ok`` also ends through ``cancel``: only a real Cancel/Esc drops the result and the candidate preview.
        if not self.accepted:
            if self.previewed and self.preview_callback is not None:
                self.preview_callback(None)
            self.result = None
        super().cancel(event)


class GraphShapesDialog(simpledialog.Dialog):
    """List, add, edit, duplicate, reorder and remove the shapes of one graph.

    ``records`` are the confirmed shapes (copied). ``preview(records)`` shows a candidate list on the graph and
    returns a warning or None; ``preview(None)`` restores the confirmed graph. ``result`` is the canonical list
    after Apply, otherwise None.
    """

    def __init__(self, parent, axes, records, *, preview=None):
        self.axes = axes
        self.confirmed = validate_shapes(deepcopy(list(records or [])))
        self.records = deepcopy(self.confirmed)
        self.preview_callback = preview
        self.shown = None  # The list currently previewed on the graph; None means the confirmed graph.
        self.result = None
        super().__init__(parent, tr("shape.title"))

    def body(self, master):
        self.configure(background=BACKGROUND)
        master.configure(background=BACKGROUND)
        self.body_frame = master
        master.pack_configure(fill="both", expand=True)
        body = ttk.Frame(master, padding=8)
        body.pack(fill="both", expand=True)
        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        columns = (("number", "#", 34), ("kind", "shape.kind", 100), ("units", "shape.units", 190),
                   ("layer", "shape.layer", 110), ("points", "shape.points", 220))
        self.tree = ttk.Treeview(table, columns=[key for key, _, _ in columns], show="headings",
                                 height=max(4, min(10, (self.winfo_screenheight() - 420) // 22)), selectmode="browse")
        for key, label, width in columns:
            self.tree.heading(key, text=label if key == "number" else tr(label))
            self.tree.column(key, width=width, stretch=key == "points", anchor="w")
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
        for key, command in (("add", self.add), ("edit", self.edit), ("duplicate", self.duplicate),
                             ("remove", self.remove), ("up", lambda: self.move(-1)), ("down", lambda: self.move(1)),
                             ("clear", self.clear), ("preview", self.preview)):
            button = ttk.Button(buttons, text=tr(f"shape.{key}"), command=command)
            button.pack(side="left", padx=(0, 4))
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
            self.buttons[key] = button
        self.message = ttk.Label(body, wraplength=600, justify="left", foreground=ERROR)
        self.message.pack(fill="x", pady=(6, 0))
        self.fill()
        return self.tree

    def buttonbox(self):
        row = ttk.Frame(self, padding=6)
        row.pack(side="bottom", fill="x", before=self.body_frame)
        self.cancel_button = ttk.Button(row, text=tr("setup.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.apply_button = ttk.Button(row, text=tr("graph.format.apply"), style="Action.TButton", command=self.ok)
        self.apply_button.pack(side="right", padx=6)
        for button in (self.apply_button, self.cancel_button):
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
        self.bind("<Escape>", self.cancel)

    # List -----------------------------------------------------------------------------------------------------
    def selected_index(self):
        selected = self.tree.selection()
        return int(selected[0]) if selected else None

    def fill(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(self.records):
            self.tree.insert("", "end", iid=str(index), values=(index + 1, *describe_shape(record)))
        if selected is not None and self.records:
            iid = str(max(0, min(selected, len(self.records) - 1)))
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
        self.update_buttons()

    def update_buttons(self):
        index = self.selected_index()
        full = len(self.records) >= MAX_SHAPES
        states = {"add": not full, "edit": index is not None, "duplicate": index is not None and not full,
                  "remove": index is not None, "up": bool(index), "clear": bool(self.records),
                  "down": index is not None and index < len(self.records) - 1, "preview": True}
        for key, enabled in states.items():
            self.buttons[key].state(["!disabled"] if enabled else ["disabled"])

    # Preview --------------------------------------------------------------------------------------------------
    def show_preview(self, records):
        """Draw ``records`` (or the confirmed graph for None) and report any warning."""
        if self.preview_callback is None:
            return None
        warning = self.preview_callback(None if records is None else deepcopy(records))
        self.shown = None if records is None else deepcopy(records)
        self.message.configure(text=warning or "")
        return warning

    def child_preview(self, index):
        """The preview callback handed to a ``ShapeEditor`` editing ``index`` (None appends)."""
        def preview(record):
            if record is None:
                return self.show_preview(self.shown)
            candidate = deepcopy(self.records)
            if index is None:
                candidate.append(record)
            else:
                candidate[index] = record
            if self.preview_callback is None:
                return None
            return self.preview_callback(validate_shapes(candidate))
        return preview

    def preview(self):
        try:
            records = validate_shapes(self.records)
        except ValueError as error:
            self.message.configure(text=str(error))
            return
        try:
            self.show_preview(records)
        except ValueError as error:
            self.message.configure(text=str(error))

    def refresh_preview(self):
        """After a change to the draft, keep an active preview in step with it."""
        if self.shown is not None:
            self.show_preview(self.records)

    # Actions --------------------------------------------------------------------------------------------------
    def limit_reached(self):
        if len(self.records) >= MAX_SHAPES:
            self.message.configure(text=tr("shape.error.limit"))
            return True
        return False

    def add(self):
        if self.limit_reached():
            return
        dialog = ShapeEditor(self, self.axes, preview=self.child_preview(None))
        self.grab_set()
        if dialog.result is not None:
            self.records.append(dialog.result)
            self.fill(len(self.records) - 1)
            self.refresh_preview()
        self.tree.focus_set()

    def edit(self):
        index = self.selected_index()
        if index is None:
            return
        dialog = ShapeEditor(self, self.axes, self.records[index], preview=self.child_preview(index))
        self.grab_set()
        if dialog.result is not None:
            self.records[index] = dialog.result
            self.fill(index)
            self.refresh_preview()
        self.tree.focus_set()

    def duplicate(self):
        index = self.selected_index()
        if index is None or self.limit_reached():
            return
        copy = deepcopy(self.records[index])
        copy["id"] = new_shape_id()
        self.records.insert(index + 1, copy)
        self.fill(index + 1)
        self.refresh_preview()

    def remove(self):
        index = self.selected_index()
        if index is None:
            return
        del self.records[index]
        self.fill(index)
        self.refresh_preview()

    def move(self, step):
        index = self.selected_index()
        if index is None or not 0 <= index + step < len(self.records):
            return
        self.records[index], self.records[index + step] = self.records[index + step], self.records[index]
        self.fill(index + step)
        self.refresh_preview()

    def clear(self):
        self.records = []
        self.fill()
        self.refresh_preview()

    # Transaction ----------------------------------------------------------------------------------------------
    def ok(self, event=None):
        # A dialog already closed by Cancel/Esc cannot be applied afterwards.
        if not self.winfo_exists():
            return None
        return super().ok(event)

    def validate(self):
        try:
            self.result = validate_shapes(self.records)
        except ValueError as error:
            self.result = None
            self.message.configure(text=str(error))
            return False
        return True

    def apply(self):
        pass

    def cancel(self, event=None):
        if self.shown is not None and self.result is None:
            self.show_preview(None)
        super().cancel(event)
