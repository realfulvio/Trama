"""Editor for the dendrograms, labels, matrix and color bar of a hierarchical graph.

Preview changes the canvas figure only. Apply returns a full graph style whose
``hierarchical`` section contains just the fields that differ from the renderer.
Cancel and Escape put that canvas back to the confirmed section. Blank boxes are
omitted, so the renderer value stays. Hiding a tree keeps its gridspec space.
"""
from copy import deepcopy
import math
import tkinter as tk
from tkinter import simpledialog, ttk

from .axis_guides_dialog import _ScrolledBody
from .data import decimal_comma
from .graph_dialog import ChoiceBinding, pick_color
from .hierarchical_style import (
    ASPECTS,
    CMAPS,
    COLORBAR_TITLE_POSITIONS,
    COLOR_MODES,
    LINE_STYLES,
    ORIENTATIONS,
    HierarchicalStyleError,
    apply_hierarchical_style,
    baseline_hierarchical_style,
    describe_hierarchical_artists,
    validate_hierarchical_style,
)
from .i18n import tr, translate_message

ERROR_COLOR = "#b00020"
COLOR_MODE_LABELS = {
    "analysis": "hierarchy.style.choice.analysis",
    "single": "hierarchy.style.choice.single",
    "cluster": "hierarchy.style.choice.cluster",
}
LINE_LABELS = {
    "solid": "hierarchy.style.choice.solid",
    "dashed": "hierarchy.style.choice.dashed",
    "dotted": "hierarchy.style.choice.dotted",
    "dashdot": "hierarchy.style.choice.dashdot",
}
ORIENTATION_LABELS = {
    "vertical": "hierarchy.style.choice.vertical",
    "horizontal": "hierarchy.style.choice.horizontal",
}
ASPECT_LABELS = {
    "auto": "hierarchy.style.choice.auto",
    "equal": "hierarchy.style.choice.equal",
}


def _merged(base, override):
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merged(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _same(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    return left == right


def _diff(canonical, baseline):
    """Drop values that already match the renderer capture. Empty groups disappear."""
    if not isinstance(canonical, dict):
        return deepcopy(canonical)
    baseline = baseline or {}
    kept = {}
    for key, value in canonical.items():
        current = baseline.get(key)
        if isinstance(value, dict):
            nested = _diff(value, current if isinstance(current, dict) else {})
            if nested:
                kept[key] = nested
        elif not _same(value, current):
            kept[key] = deepcopy(value)
    return kept


def _format_number(value):
    if value is None:
        return ""
    return f"{float(value):g}"


class HierarchicalStyleDialog(simpledialog.Dialog):
    """One editor for whichever of the row tree, column tree and heat map exist."""

    def __init__(self, parent, figure, canvas, style):
        described = describe_hierarchical_artists(figure)
        if not described:
            raise HierarchicalStyleError("figure", "This figure is not a native hierarchical clustering graph.")
        self.figure = figure
        self.canvas = canvas
        self.style = deepcopy(style or {})
        self._confirmed = deepcopy(self.style.get("hierarchical") or {})
        self.baseline = baseline_hierarchical_style(figure)
        self.effective = _merged(self.baseline, self._confirmed)
        self.described = described
        self.previewed = False
        self.touched = False
        self.accepted = False
        self._pending = None
        self.widgets = {}
        self.vars = {}
        self.pages = {}
        super().__init__(parent, tr("hierarchy.style.title"))

    def body(self, master):
        self.body_frame = master
        master.pack_configure(fill="both", expand=True)
        height = max(240, min(480, self.winfo_screenheight() - 280))
        self.scrolled = _ScrolledBody(master, height)
        self.scrolled.outer.pack(fill="both", expand=True)
        form = self.scrolled.body
        form.columnconfigure(0, weight=1)
        ttk.Label(form, text=tr("hierarchy.style.hint.blank"), wraplength=460, justify="left").grid(
            row=0, column=0, sticky="ew", pady=(0, 6))
        self.notebook = ttk.Notebook(form)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        form.rowconfigure(1, weight=1)
        self.tabs = {}
        self._tree_page("row")
        self._tree_page("column")
        self._heatmap_page()
        self._layout_page()
        focus = None
        for key in ("row", "column", "heatmap", "layout"):
            if self.pages[key]:
                self.notebook.select(self.tabs[key])
                focus = self._first_entry(self.tabs[key])
                break
            self.notebook.tab(self.tabs[key], state="disabled")
        for key, enabled in self.pages.items():
            if not enabled:
                self.notebook.tab(self.tabs[key], state="disabled")
        return focus

    def buttonbox(self):
        footer = ttk.Frame(self, padding=(8, 4, 8, 8))
        footer.pack(side="bottom", fill="x", before=self.body_frame)
        self.problem = ttk.Label(footer, wraplength=460, justify="left", foreground=ERROR_COLOR)
        self.problem.pack(side="top", fill="x", pady=(0, 4))
        self.cancel_button = ttk.Button(footer, text=tr("hierarchy.style.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.ok_button = ttk.Button(footer, text=tr("hierarchy.style.apply"), style="Action.TButton", command=self.ok)
        self.ok_button.pack(side="right", padx=6)
        self.preview_button = ttk.Button(footer, text=tr("hierarchy.style.preview"), command=self.preview)
        self.preview_button.pack(side="right")
        for button in (self.preview_button, self.ok_button, self.cancel_button):
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def _tree_page(self, key):
        tab = self._add_tab(key, tr(f"hierarchy.style.tab.{key}"))
        enabled = key in self.described
        self.pages[key] = enabled
        if not enabled:
            return
        ttk.Label(tab, text=tr("hierarchy.style.hint.hidden"), wraplength=440, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        branches = self._group(tab, 1, "hierarchy.style.group.branches")
        self._check(branches, f"{key}.visible", "hierarchy.style.field.visible", self._get(key, "visible"))
        self._choice(branches, f"{key}.color_mode", "hierarchy.style.field.color_mode",
                     self._get(key, "color_mode"), COLOR_MODES, COLOR_MODE_LABELS)
        self._color(branches, f"{key}.color", "hierarchy.style.field.color", self._get(key, "color"))
        self._color(branches, f"{key}.mixed_color", "hierarchy.style.field.mixed_color", self._get(key, "mixed_color"))
        self._entry(branches, f"{key}.palette", "hierarchy.style.field.palette",
                    ", ".join(self._get(key, "palette") or ()))
        ttk.Label(branches, text=tr("hierarchy.style.hint.palette"), wraplength=420, justify="left").grid(
            row=branches.grid_size()[1], column=0, columnspan=3, sticky="ew")
        self._entry(branches, f"{key}.width", "hierarchy.style.field.width", _format_number(self._get(key, "width")))
        self._choice(branches, f"{key}.line_style", "hierarchy.style.field.line_style",
                     self._get(key, "line_style"), LINE_STYLES, LINE_LABELS)
        self._entry(branches, f"{key}.alpha", "hierarchy.style.field.alpha", _format_number(self._get(key, "alpha")))
        if "legend_visible" in self.baseline[key]:
            self._check(branches, f"{key}.legend_visible", "hierarchy.style.field.legend_visible",
                        self._get(key, "legend_visible"))
        self._label_group(tab, 2, key, "hierarchy.style.group.labels")
        distance = self._group(tab, 3, "hierarchy.style.group.distance")
        ttk.Label(distance, text=tr("hierarchy.style.hint.distance"), wraplength=420, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        self._check(distance, f"{key}.distance.visible", "hierarchy.style.field.distance.visible",
                    self._get(key, "distance", "visible"))
        self._check(distance, f"{key}.distance.title_visible", "hierarchy.style.field.distance.title_visible",
                    self._get(key, "distance", "title_visible"))
        self._entry(distance, f"{key}.distance.minimum", "hierarchy.style.field.distance.minimum",
                    _format_number(self._get(key, "distance", "minimum")))
        self._entry(distance, f"{key}.distance.maximum", "hierarchy.style.field.distance.maximum",
                    _format_number(self._get(key, "distance", "maximum")))
        self._entry(distance, f"{key}.distance.step", "hierarchy.style.field.distance.step",
                    _format_number(self._get(key, "distance", "step")))
        self._check(distance, f"{key}.distance.reversed", "hierarchy.style.field.distance.reversed",
                    self._get(key, "distance", "reversed"))

    def _label_group(self, tab, row, key, caption):
        labels = self._group(tab, row, caption)
        ttk.Label(labels, text=tr("hierarchy.style.hint.labels"), wraplength=420, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        self._check(labels, f"{key}.labels.visible", "hierarchy.style.field.labels.visible",
                    self._get(key, "labels", "visible"))
        self._entry(labels, f"{key}.labels.rotation", "hierarchy.style.field.labels.rotation",
                    _format_number(self._get(key, "labels", "rotation")))
        self._entry(labels, f"{key}.labels.size", "hierarchy.style.field.labels.size",
                    _format_number(self._get(key, "labels", "size")))
        self._entry(labels, f"{key}.labels.family", "hierarchy.style.field.labels.family", self._get(key, "labels", "family"))
        self._check(labels, f"{key}.labels.bold", "hierarchy.style.field.labels.bold", self._get(key, "labels", "bold"))
        self._color(labels, f"{key}.labels.color", "hierarchy.style.field.labels.color",
                    self._get(key, "labels", "color"))
        self._entry(labels, f"{key}.labels.first", "hierarchy.style.field.labels.first",
                    "" if self._get(key, "labels", "first") is None else str(int(self._get(key, "labels", "first"))))
        self._entry(labels, f"{key}.labels.interval", "hierarchy.style.field.labels.interval",
                    "" if self._get(key, "labels", "interval") is None else str(int(self._get(key, "labels", "interval"))))

    def _heatmap_page(self):
        tab = self._add_tab("heatmap", tr("hierarchy.style.tab.heatmap"))
        enabled = "heatmap" in self.described
        self.pages["heatmap"] = enabled
        if not enabled:
            return
        ttk.Label(tab, text=tr("hierarchy.style.hint.colorbar"), wraplength=440, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        self._choice(tab, "heatmap.cmap", "hierarchy.style.field.cmap", self._get("heatmap", "cmap"), CMAPS, {})
        self._check(tab, "heatmap.reverse", "hierarchy.style.field.reverse", self._get("heatmap", "reverse"))
        self._entry(tab, "heatmap.minimum", "hierarchy.style.field.minimum",
                    _format_number(self._get("heatmap", "minimum")))
        self._entry(tab, "heatmap.maximum", "hierarchy.style.field.maximum",
                    _format_number(self._get("heatmap", "maximum")))
        self._check(tab, "heatmap.colorbar", "hierarchy.style.field.colorbar", self._get("heatmap", "colorbar"))
        self._entry(tab, "heatmap.title", "hierarchy.style.field.title", self._get("heatmap", "title") or "")
        title_positions = {key: f"hierarchy.style.choice.{key}" for key in COLORBAR_TITLE_POSITIONS}
        self._choice(tab, "heatmap.title_position", "hierarchy.style.field.title_position",
                     self._get("heatmap", "title_position"), COLORBAR_TITLE_POSITIONS, title_positions)
        for name in ("scale_labels", "scale_reverse"):
            self._check(tab, f"heatmap.{name}", f"hierarchy.style.field.{name}", self._get("heatmap", name))
        self._entry(tab, "heatmap.scale_size", "hierarchy.style.field.scale_size",
                    _format_number(self._get("heatmap", "scale_size")))
        self._entry(tab, "heatmap.scale_font", "hierarchy.style.field.scale_font", self._get("heatmap", "scale_font"))
        self._color(tab, "heatmap.scale_color", "hierarchy.style.field.scale_color", self._get("heatmap", "scale_color"))
        self._choice(tab, "heatmap.orientation", "hierarchy.style.field.orientation",
                     self._get("heatmap", "orientation"), ORIENTATIONS, ORIENTATION_LABELS)
        self._choice(tab, "heatmap.cell_aspect", "hierarchy.style.field.cell_aspect",
                     self._get("heatmap", "cell_aspect"), ASPECTS, ASPECT_LABELS)

        for key in ("row", "column"):
            if key in self.baseline and key not in self.described:
                self._label_group(tab, self._row(tab), key, f"hierarchy.style.group.{key}_labels")

    def _layout_page(self):
        tab = self._add_tab("layout", tr("hierarchy.style.tab.layout"))
        enabled = "heatmap" in self.described
        self.pages["layout"] = enabled
        if not enabled:
            return
        ttk.Label(tab, text=tr("hierarchy.style.hint.layout"), wraplength=440, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        self._entry(tab, "layout.row_tree_ratio", "hierarchy.style.field.row_tree_ratio",
                    _format_number(self._get("layout", "row_tree_ratio")))
        self._entry(tab, "layout.column_tree_ratio", "hierarchy.style.field.column_tree_ratio",
                    _format_number(self._get("layout", "column_tree_ratio")))
        if "row" not in self.described:
            self.widgets["layout.row_tree_ratio"].configure(state="disabled")
        if "column" not in self.described:
            self.widgets["layout.column_tree_ratio"].configure(state="disabled")

    def _add_tab(self, key, title):
        tab = ttk.Frame(self.notebook, padding=8)
        tab.columnconfigure(1, weight=1)
        self.notebook.add(tab, text=title)
        self.tabs[key] = tab
        return tab

    def _group(self, tab, row, caption):
        frame = ttk.LabelFrame(tab, text=tr(caption), padding=(8, 4))
        frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        frame.columnconfigure(1, weight=1)
        return frame

    def _row(self, master):
        return master.grid_size()[1]

    def _check(self, master, field, caption, value):
        variable = tk.BooleanVar(self, bool(value))
        widget = ttk.Checkbutton(master, text=tr(caption), variable=variable)
        widget.grid(row=self._row(master), column=0, columnspan=3, sticky="w", pady=2)
        self.vars[field] = variable
        self.widgets[field] = widget
        return widget

    def _entry(self, master, field, caption, value):
        row = self._row(master)
        ttk.Label(master, text=tr(caption)).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        variable = tk.StringVar(self, "" if value is None else str(value))
        widget = ttk.Entry(master, textvariable=variable, width=24)
        widget.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)
        self.vars[field] = variable
        self.widgets[field] = widget
        return widget

    def _choice(self, master, field, caption, value, values, labels):
        row = self._row(master)
        ttk.Label(master, text=tr(caption)).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        variable = tk.StringVar(self, "" if value is None else str(value))
        widget = ttk.Combobox(master, state="readonly", width=22)
        widget.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)
        ChoiceBinding(widget, variable, values, labels)
        self.vars[field] = variable
        self.widgets[field] = widget
        return widget

    def _color(self, master, field, caption, value):
        widget = self._entry(master, field, caption, value or "")
        widget.grid_configure(columnspan=1)
        ttk.Button(master, text=tr("hierarchy.style.pick"),
                   command=lambda variable=self.vars[field]: pick_color(self, variable)).grid(
            row=widget.grid_info()["row"], column=2, padx=(4, 0))
        return widget

    def _get(self, *path):
        node = self.effective
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    def _first_entry(self, tab):
        for child in tab.winfo_children():
            found = self._first_entry(child) if isinstance(child, ttk.LabelFrame) else None
            if found is not None:
                return found
            if isinstance(child, (ttk.Entry, ttk.Combobox, ttk.Checkbutton)):
                return child
        return None

    def _section_of(self, field):
        page = field.split(".", 1)[0]
        return "heatmap" if page in ("row", "column") and not self.pages.get(page) else page

    def read_override(self):
        """Canonical fields that differ from the renderer. Disabled pages are left out."""
        collected = {}
        if self.pages.get("row"):
            collected["row"] = self._read_tree("row")
        if self.pages.get("column"):
            collected["column"] = self._read_tree("column")
        if self.pages.get("heatmap"):
            for key in ("row", "column"):
                if key in self.baseline and key not in self.described:
                    collected[key] = {"labels": self._read_labels(key)}
            collected["heatmap"] = self._read_heatmap()
        if self.pages.get("layout"):
            layout = self._read_layout()
            if layout:
                collected["layout"] = layout
        canonical = validate_hierarchical_style(collected, figure=self.figure)
        return _diff(canonical, self.baseline)

    def _optional_text(self, field):
        variable = self.vars.get(field)
        if variable is None or str(self.widgets[field].cget("state")) == "disabled":
            return None
        text = variable.get().strip() if not isinstance(variable, tk.BooleanVar) else None
        return text

    def _read_float(self, field, *, required=False):
        text = self._optional_text(field)
        if text is None or text == "":
            if required:
                raise HierarchicalStyleError(field, "Enter a finite number.")
            return None
        try:
            number = float(decimal_comma(text))
        except (TypeError, ValueError):
            raise HierarchicalStyleError(field, "Enter a finite number.") from None
        return number

    def _read_int(self, field):
        text = self._optional_text(field)
        if not text:
            return None
        if not text.lstrip("+-").isdigit() or text in {"+", "-"}:
            raise HierarchicalStyleError(field, "Enter a whole number.")
        return int(text)

    def _put(self, target, field, value):
        if value is None:
            return
        key = field.split(".")[-1]
        target[key] = value

    def _read_tree(self, key):
        tree = {}
        self._put(tree, f"{key}.visible", bool(self.vars[f"{key}.visible"].get()))
        self._put(tree, f"{key}.color_mode", self.vars[f"{key}.color_mode"].get())
        for name in ("color", "mixed_color"):
            text = self._optional_text(f"{key}.{name}")
            if text:
                tree[name] = text
        palette = self._optional_text(f"{key}.palette")
        if palette:
            tree["palette"] = [part.strip() for part in palette.split(",")]
        width = self._read_float(f"{key}.width")
        if width is not None:
            tree["width"] = width
        self._put(tree, f"{key}.line_style", self.vars[f"{key}.line_style"].get())
        alpha = self._read_float(f"{key}.alpha")
        if alpha is not None:
            tree["alpha"] = alpha
        if f"{key}.legend_visible" in self.vars:
            tree["legend_visible"] = bool(self.vars[f"{key}.legend_visible"].get())
            tree["legend_title"] = self._get(key, "legend_title")
            tree["legend_entries"] = self._get(key, "legend_entries")
        tree["labels"] = self._read_labels(key)
        distance = {}
        self._put(distance, f"{key}.distance.visible", bool(self.vars[f"{key}.distance.visible"].get()))
        for name in ("minimum", "maximum", "step"):
            number = self._read_float(f"{key}.distance.{name}")
            if number is not None:
                distance[name] = number
        self._put(distance, f"{key}.distance.title_visible", bool(self.vars[f"{key}.distance.title_visible"].get()))
        self._put(distance, f"{key}.distance.reversed", bool(self.vars[f"{key}.distance.reversed"].get()))
        if distance:
            tree["distance"] = distance
        return tree

    def _read_labels(self, key):
        labels = {}
        self._put(labels, f"{key}.labels.visible", bool(self.vars[f"{key}.labels.visible"].get()))
        rotation = self._read_float(f"{key}.labels.rotation")
        if rotation is not None:
            labels["rotation"] = rotation
        size = self._read_float(f"{key}.labels.size")
        if size is not None:
            labels["size"] = size
        color = self._optional_text(f"{key}.labels.color")
        if color:
            labels["color"] = color
        first = self._read_int(f"{key}.labels.first")
        if first is not None:
            labels["first"] = first
        interval = self._read_int(f"{key}.labels.interval")
        if interval is not None:
            labels["interval"] = interval
        family = self._optional_text(f"{key}.labels.family")
        if family:
            labels["family"] = family
        labels["bold"] = bool(self.vars[f"{key}.labels.bold"].get())
        return labels

    def _read_heatmap(self):
        heat = {}
        self._put(heat, "heatmap.cmap", self.vars["heatmap.cmap"].get())
        self._put(heat, "heatmap.reverse", bool(self.vars["heatmap.reverse"].get()))
        minimum = self._read_float("heatmap.minimum")
        maximum = self._read_float("heatmap.maximum")
        if minimum is not None or maximum is not None:
            heat["minimum"] = minimum
            heat["maximum"] = maximum
        self._put(heat, "heatmap.colorbar", bool(self.vars["heatmap.colorbar"].get()))
        title = self._optional_text("heatmap.title")
        if title:
            heat["title"] = title
        for name in ("title_position", "scale_labels", "scale_reverse", "orientation"):
            self._put(heat, f"heatmap.{name}", self.vars[f"heatmap.{name}"].get())
        self._put(heat, "heatmap.scale_size", self._read_float("heatmap.scale_size"))
        for name in ("scale_font", "scale_color"):
            text = self._optional_text(f"heatmap.{name}")
            if text:
                heat[name] = text
        self._put(heat, "heatmap.cell_aspect", self.vars["heatmap.cell_aspect"].get())
        return heat

    def _read_layout(self):
        layout = {}
        for name in ("row_tree_ratio", "column_tree_ratio"):
            field = f"layout.{name}"
            if str(self.widgets[field].cget("state")) == "disabled":
                continue
            number = self._read_float(field)
            if number is not None:
                layout[name] = number
        return layout

    def _draw(self):
        canvas = self.canvas or getattr(self.figure, "canvas", None)
        if canvas is None:
            return
        draw = getattr(canvas, "draw_idle", None) or getattr(canvas, "draw", None)
        if draw is not None:
            draw()

    def show_error(self, error):
        self.problem.configure(text=translate_message(error, "hierarchy.style.error."))
        field = getattr(error, "field", None)
        widget = self.widgets.get(field)
        if widget is None or field is None:
            return
        section = self._section_of(field)
        tab = self.tabs.get(section)
        if tab is not None and self.pages.get(section):
            self.notebook.select(tab)
        self.update_idletasks()
        self.scrolled.reveal(widget)
        if widget.winfo_viewable():
            widget.focus_force()
        else:
            widget.focus_set()
        if isinstance(widget, ttk.Entry):
            widget.select_range(0, "end")
            widget.icursor("end")

    def preview(self):
        try:
            partial = self.read_override()
            apply_hierarchical_style(self.figure, partial)
        except HierarchicalStyleError as error:
            self.show_error(error)
            return False
        self._draw()
        self.previewed = True
        self.touched = True
        self.problem.configure(text="")
        return True

    def validate(self):
        try:
            self._pending = self.read_override()
        except HierarchicalStyleError as error:
            self.show_error(error)
            return False
        self.problem.configure(text="")
        return True

    def apply(self):
        apply_hierarchical_style(self.figure, self._pending)
        self._draw()
        result = deepcopy(self.style)
        result.pop("hierarchical", None)
        if self._pending:
            result["hierarchical"] = deepcopy(self._pending)
        self.result = result
        self.accepted = True
        self.touched = True

    def cancel(self, event=None):
        if self.previewed and not self.accepted:
            apply_hierarchical_style(self.figure, deepcopy(self._confirmed))
            self._draw()
            self.previewed = False
        super().cancel(event)
