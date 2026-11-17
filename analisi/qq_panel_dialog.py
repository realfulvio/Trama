"""Dedicated Tk editor for independent formatting of Q–Q plot panels."""
from copy import deepcopy
from math import isfinite
import re
from sys import float_info
import tkinter as tk
from tkinter import simpledialog, ttk

from matplotlib.colors import to_hex
from matplotlib.ticker import Locator

from . import ui_theme
from .data import decimal_comma
from .graph_dialog import ChoiceBinding, pick_color
from .i18n import tr, translate_message
from .presentation import apply_style, capture_defaults, validated_style
from .qq_panels import (
    LINE_STYLES,
    MAX_LABEL_LENGTH,
    MAX_LINE_WIDTH,
    MAX_POINT_SIZE,
    MIN_LINE_WIDTH,
    MIN_POINT_SIZE,
    PANEL_KEY,
    POINT_MARKERS,
    POINTS_KEY,
    REFERENCE_KEY,
    TEXT_KEYS,
    panel_axes,
)

ERROR_COLOR = "#a02a2a"
HINT_COLOR = "#486075"
DEFAULT_POINT_HEX = "#2866ae"
DEFAULT_REF_HEX = "#bc4040"
HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")
AUTO = ""

PANEL_CHOICE_KEYS = {
    "normal": "qq.panels.panel.normal",
    "lognormal": "qq.panels.panel.lognormal",
}
POINT_MARKER_CHOICE_KEYS = {
    AUTO: "qq.panels.auto",
    "o": "graph.marker.circle",
    "s": "graph.marker.square",
    "D": "graph.marker.diamond",
    "^": "graph.marker.triangle_up",
    "v": "graph.marker.triangle_down",
    "+": "graph.marker.plus",
    "x": "graph.marker.cross",
}
LINE_STYLE_CHOICE_KEYS = {
    AUTO: "qq.panels.auto",
    "-": "graph.line.solid",
    "--": "graph.line.dashed",
    "-.": "graph.line.dash_dot",
    ":": "graph.line.dotted",
}


class _PanelFieldError(ValueError):
    """Validation failure tied to a specific panel, tab, and widget."""

    def __init__(self, panel_id, error_key, widget_key, message, *, tab_key="axes"):
        super().__init__(message)
        self.panel_id = panel_id
        self.tab_key = tab_key
        self.error_key = error_key
        self.widget_key = widget_key


def _parse_finite(text, error_message):
    cleaned = text.strip()
    if not cleaned or "_" in cleaned:
        raise ValueError(error_message)
    try:
        value = float(decimal_comma(cleaned))
    except (TypeError, ValueError, OverflowError):
        raise ValueError(error_message) from None
    if not isfinite(value) or abs(value) > float_info.max:
        raise ValueError(error_message)
    return value


def _parse_bounded(text, low, high, error_message):
    value = _parse_finite(text, error_message)
    if not (low <= value <= high):
        raise ValueError(error_message)
    return value


def _default_hex(defaults_section, key, fallback):
    if not defaults_section:
        return fallback
    raw = defaults_section.get(key)
    if key == "facecolors" and raw is not None and len(raw):
        return to_hex(raw[0][:3])
    if raw is not None:
        try:
            return to_hex(raw)
        except ValueError:
            pass
    return fallback


class QQPanelsDialog(simpledialog.Dialog):
    """Edit title, axis labels, limits, legend, points, and reference line per Q–Q panel with live preview."""

    def __init__(self, parent, figure, canvas, style, *, initial_panel=None):
        self.figure = figure
        self.canvas = canvas
        self.panels = panel_axes(figure)
        self.panel_ids = tuple(self.panels)
        if not self.panel_ids:
            raise ValueError("This graph has no Q–Q panels to format.")
        capture_defaults(figure)
        self.confirmed_style = deepcopy(style or {})
        self.last_valid_style = deepcopy(self.confirmed_style)
        self._validated_style = None
        self.result = None
        self._syncing_panel = False
        self._default_legend_visible = {
            pid: self.panels[pid]._tramastat_qq_defaults["legend_visible"]
            for pid in self.panel_ids
        }
        self._default_points_visible = {
            pid: (self.panels[pid]._tramastat_qq_defaults["points"] or {}).get("visible", True)
            for pid in self.panel_ids
        }
        self._has_reference = {
            pid: self.panels[pid]._tramastat_qq_defaults["reference_line"] is not None
            for pid in self.panel_ids
        }
        self._cleared_hidden_ref = {pid: False for pid in self.panel_ids}
        self._default_ref_visible = {
            pid: (self.panels[pid]._tramastat_qq_defaults["reference_line"] or {}).get("visible", True)
            for pid in self.panel_ids
        }
        self._default_point_hex = {
            pid: _default_hex(self.panels[pid]._tramastat_qq_defaults["points"], "facecolors", DEFAULT_POINT_HEX)
            for pid in self.panel_ids
        }
        self._default_ref_hex = {
            pid: _default_hex(self.panels[pid]._tramastat_qq_defaults["reference_line"], "color", DEFAULT_REF_HEX)
            for pid in self.panel_ids
        }
        self._panel_inputs = {
            pid: self._inputs_from_style(self.confirmed_style.get(PANEL_KEY, {}).get(pid, {}), pid)
            for pid in self.panel_ids
        }
        self.current_panel = initial_panel if initial_panel in self.panel_ids else self.panel_ids[0]
        self.vars = {}
        self.widgets = {}
        self.swatches = {}
        self.pickers = {}
        self.error_labels = {}
        self.buttons = {}
        self.tabs = {}
        self._tab_scrollers = {}
        super().__init__(parent, tr("qq.panels.dialog_title"))

    def _inputs_from_style(self, override, panel_id):
        axis_over = override.get("axis", {})
        points_over = override.get(POINTS_KEY, {})
        ref_over = override.get(REFERENCE_KEY, {})
        default_legend = getattr(self, "_default_legend_visible", {}).get(panel_id, True)
        default_points_vis = getattr(self, "_default_points_visible", {}).get(panel_id, True)
        default_ref_vis = getattr(self, "_default_ref_visible", {}).get(panel_id, True)
        return {
            "title": override.get("title", ""),
            "xlabel": override.get("xlabel", ""),
            "ylabel": override.get("ylabel", ""),
            "xmin": repr(float(axis_over["x"]["min"])) if "x" in axis_over and "min" in axis_over["x"] else "",
            "xmax": repr(float(axis_over["x"]["max"])) if "x" in axis_over and "max" in axis_over["x"] else "",
            "ymin": repr(float(axis_over["y"]["min"])) if "y" in axis_over and "min" in axis_over["y"] else "",
            "ymax": repr(float(axis_over["y"]["max"])) if "y" in axis_over and "max" in axis_over["y"] else "",
            "legend_visible": override.get("legend_visible", default_legend),
            "legend_explicit": "legend_visible" in override,
            "points_visible": points_over.get("visible", default_points_vis),
            "points_visible_explicit": "visible" in points_over,
            "points_empty_explicit": (POINTS_KEY in override and not points_over),
            "points_marker": points_over.get("marker", AUTO),
            "points_size": repr(float(points_over["size"])) if "size" in points_over else "",
            "points_color": points_over.get("color", ""),
            "points_alpha": repr(float(points_over["alpha"])) if "alpha" in points_over else "",
            "ref_visible": ref_over.get("visible", default_ref_vis),
            "ref_visible_explicit": "visible" in ref_over,
            "ref_empty_explicit": (REFERENCE_KEY in override and not ref_over),
            "ref_color": ref_over.get("color", ""),
            "ref_width": repr(float(ref_over["width"])) if "width" in ref_over else "",
            "ref_style": ref_over.get("style", AUTO),
            "ref_alpha": repr(float(ref_over["alpha"])) if "alpha" in ref_over else "",
        }

    def _make_scrollable_tab(self, tab_key, label_key):
        outer = ttk.Frame(self.notebook)
        self.notebook.add(outer, text=tr(label_key))
        scroll = ttk.Scrollbar(outer, orient="vertical")
        scroll.pack(side="right", fill="y")
        background = ttk.Style(self).lookup("TFrame", "background") or "#f4f6f8"
        scroller = tk.Canvas(outer, highlightthickness=0, yscrollcommand=scroll.set, background=background)
        scroller.pack(side="left", fill="both", expand=True)
        scroll.configure(command=scroller.yview)
        content = ttk.Frame(scroller, padding=(8, 8, 10, 8))
        content.columnconfigure(1, weight=1)
        window = scroller.create_window(0, 0, window=content, anchor="nw")
        content.bind("<Configure>", lambda _e, s=scroller: s.configure(scrollregion=s.bbox("all")))
        scroller.bind("<Configure>", lambda event, s=scroller, w=window: s.itemconfigure(w, width=event.width))
        self.tabs[tab_key] = outer
        self._tab_scrollers[tab_key] = (scroller, content)
        return content

    def _add_error_row(self, parent, row, key):
        err = ttk.Label(parent, foreground=ERROR_COLOR, wraplength=ui_theme.px(320), justify="left")
        err.grid(row=row, column=1, sticky="w")
        err.grid_remove()
        self.error_labels[key] = err
        return row + 1

    def _add_color_row(self, parent, row, key, label_key):
        ttk.Label(parent, text=tr(label_key)).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, sticky="ew", pady=3)
        holder.columnconfigure(1, weight=1)
        swatch = tk.Label(holder, width=3, relief="solid", borderwidth=1)
        swatch.grid(row=0, column=0, padx=(0, 6))
        var = self.vars[key] = tk.StringVar(self)
        entry = ttk.Entry(holder, textvariable=var, width=16)
        entry.grid(row=0, column=1, sticky="ew")
        pick = ttk.Button(holder, text=tr("qq.panels.choose_color"), command=lambda k=key: self._pick_panel_color(k))
        pick.grid(row=0, column=2, padx=(6, 0))
        self.widgets[key] = entry
        self.swatches[key] = swatch
        self.pickers[key] = pick
        var.trace_add("write", lambda *_, k=key: self._refresh_swatch(k))
        return self._add_error_row(parent, row + 1, key)

    def _pick_panel_color(self, key):
        var = self.vars[key]
        current = var.get().strip()
        fallback = (self._default_point_hex if key == "points_color" else self._default_ref_hex)[self.current_panel]
        proxy = tk.StringVar(self, value=current if HEX_RE.fullmatch(current) else fallback)
        pick_color(self, proxy)
        picked = proxy.get().strip()
        if picked and picked != current and HEX_RE.fullmatch(picked):
            var.set(picked)

    def _refresh_swatch(self, key):
        swatch = self.swatches.get(key)
        if swatch is None:
            return
        pid = self.current_panel
        fallback = (self._default_point_hex if key == "points_color" else self._default_ref_hex)[pid]
        raw = self.vars[key].get().strip()
        swatch.configure(background=raw if HEX_RE.fullmatch(raw) else fallback)

    def body(self, master):
        master.columnconfigure(0, weight=1)
        master.rowconfigure(1, weight=1)

        selector_row = ttk.Frame(master, padding=(0, 0, 0, 8))
        selector_row.grid(row=0, column=0, sticky="ew")
        selector_row.columnconfigure(1, weight=1)
        ttk.Label(selector_row, text=tr("qq.panels.panel_label"), style="DialogTitle.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        self.panel_var = tk.StringVar(self, value=self.current_panel)
        self.panel_box = ttk.Combobox(selector_row, state="readonly", width=28)
        self.panel_binding = ChoiceBinding(self.panel_box, self.panel_var, self.panel_ids, PANEL_CHOICE_KEYS)
        self.panel_box.grid(row=0, column=1, sticky="ew")
        self.panel_var.trace_add("write", self._on_panel_changed)
        self.widgets["panel"] = self.panel_box

        self.notebook = ttk.Notebook(master)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        # Tab 1: Panel & Axes
        axes_tab = self._make_scrollable_tab("axes", "qq.panels.tab.axes")
        row = 0
        for key in TEXT_KEYS:
            ttk.Label(axes_tab, text=tr(f"qq.panels.{key}")).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
            var = self.vars[key] = tk.StringVar(self)
            entry = ttk.Entry(axes_tab, textvariable=var, width=32)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self.widgets[key] = entry
            row = self._add_error_row(axes_tab, row + 1, key)

        for dim in ("x", "y"):
            err_key = f"{dim}range"
            ttk.Label(axes_tab, text=tr(f"qq.panels.{err_key}")).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=3
            )
            pair = ttk.Frame(axes_tab)
            pair.grid(row=row, column=1, sticky="ew", pady=3)
            pair.columnconfigure((0, 1), weight=1, uniform=err_key)
            for col, bound in enumerate(("min", "max")):
                name = f"{dim}{bound}"
                var = self.vars[name] = tk.StringVar(self)
                entry = ttk.Entry(pair, textvariable=var, width=14)
                entry.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
                self.widgets[name] = entry
            row = self._add_error_row(axes_tab, row + 1, err_key)

        self.vars["legend_visible"] = tk.BooleanVar(self)
        legend_check = ttk.Checkbutton(
            axes_tab, text=tr("qq.panels.show_legend"), variable=self.vars["legend_visible"]
        )
        legend_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 4))
        self.widgets["legend_visible"] = legend_check
        row += 1
        ttk.Label(
            axes_tab, text=tr("qq.panels.hint"), foreground=HINT_COLOR,
            wraplength=ui_theme.px(420), justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Tab 2: Points
        pts_tab = self._make_scrollable_tab("points", "qq.panels.tab.points")
        row = 0
        self.vars["points_visible"] = tk.BooleanVar(self)
        pts_check = ttk.Checkbutton(
            pts_tab,
            text=tr("qq.panels.points.visible"),
            variable=self.vars["points_visible"],
            command=self._sync_artist_controls,
        )
        pts_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 6))
        self.widgets["points_visible"] = pts_check
        row += 1

        ttk.Label(pts_tab, text=tr("qq.panels.points.marker")).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        self.vars["points_marker"] = tk.StringVar(self)
        marker_box = ttk.Combobox(pts_tab, state="readonly", width=24)
        self.marker_binding = ChoiceBinding(
            marker_box, self.vars["points_marker"], (AUTO, *POINT_MARKERS), POINT_MARKER_CHOICE_KEYS
        )
        marker_box.grid(row=row, column=1, sticky="ew", pady=3)
        self.widgets["points_marker"] = marker_box
        row += 1

        ttk.Label(pts_tab, text=tr("qq.panels.points.size")).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        self.vars["points_size"] = tk.StringVar(self)
        size_entry = ttk.Entry(pts_tab, textvariable=self.vars["points_size"], width=16)
        size_entry.grid(row=row, column=1, sticky="ew", pady=3)
        self.widgets["points_size"] = size_entry
        row = self._add_error_row(pts_tab, row + 1, "points_size")

        row = self._add_color_row(pts_tab, row, "points_color", "qq.panels.points.color")

        ttk.Label(pts_tab, text=tr("qq.panels.points.alpha")).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        self.vars["points_alpha"] = tk.StringVar(self)
        pts_alpha_entry = ttk.Entry(pts_tab, textvariable=self.vars["points_alpha"], width=16)
        pts_alpha_entry.grid(row=row, column=1, sticky="ew", pady=3)
        self.widgets["points_alpha"] = pts_alpha_entry
        row = self._add_error_row(pts_tab, row + 1, "points_alpha")

        ttk.Label(
            pts_tab, text=tr("qq.panels.points.hint"), foreground=HINT_COLOR,
            wraplength=ui_theme.px(420), justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Tab 3: Reference line
        ref_tab = self._make_scrollable_tab("reference", "qq.panels.tab.reference")
        row = 0
        self.ref_unavailable_label = ttk.Label(
            ref_tab, text=tr("qq.panels.ref.unavailable"), foreground=HINT_COLOR,
            wraplength=ui_theme.px(420), justify="left",
        )
        self.ref_unavailable_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 6))
        row += 1

        self.vars["ref_visible"] = tk.BooleanVar(self)
        ref_check = ttk.Checkbutton(
            ref_tab,
            text=tr("qq.panels.ref.visible"),
            variable=self.vars["ref_visible"],
            command=self._sync_artist_controls,
        )
        ref_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 6))
        self.widgets["ref_visible"] = ref_check
        row += 1

        row = self._add_color_row(ref_tab, row, "ref_color", "qq.panels.ref.color")

        ttk.Label(ref_tab, text=tr("qq.panels.ref.width")).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        self.vars["ref_width"] = tk.StringVar(self)
        width_entry = ttk.Entry(ref_tab, textvariable=self.vars["ref_width"], width=16)
        width_entry.grid(row=row, column=1, sticky="ew", pady=3)
        self.widgets["ref_width"] = width_entry
        row = self._add_error_row(ref_tab, row + 1, "ref_width")

        ttk.Label(ref_tab, text=tr("qq.panels.ref.style")).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        self.vars["ref_style"] = tk.StringVar(self)
        style_box = ttk.Combobox(ref_tab, state="readonly", width=24)
        self.ref_style_binding = ChoiceBinding(
            style_box, self.vars["ref_style"], (AUTO, *LINE_STYLES), LINE_STYLE_CHOICE_KEYS
        )
        style_box.grid(row=row, column=1, sticky="ew", pady=3)
        self.widgets["ref_style"] = style_box
        row += 1

        ttk.Label(ref_tab, text=tr("qq.panels.ref.alpha")).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        self.vars["ref_alpha"] = tk.StringVar(self)
        ref_alpha_entry = ttk.Entry(ref_tab, textvariable=self.vars["ref_alpha"], width=16)
        ref_alpha_entry.grid(row=row, column=1, sticky="ew", pady=3)
        self.widgets["ref_alpha"] = ref_alpha_entry
        row = self._add_error_row(ref_tab, row + 1, "ref_alpha")

        ttk.Label(
            ref_tab, text=tr("qq.panels.ref.hint"), foreground=HINT_COLOR,
            wraplength=ui_theme.px(420), justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Size scrollers so all controls and bottom buttons stay comfortably within 1024x768.
        max_h = max(180, self.winfo_screenheight() - ui_theme.px(290))
        max_w = max(340, self.winfo_screenwidth() - ui_theme.px(80))
        req_w = ui_theme.px(460)
        req_h = 0
        for _, content in self._tab_scrollers.values():
            content.update_idletasks()
            req_w = max(req_w, content.winfo_reqwidth())
            req_h = max(req_h, content.winfo_reqheight())
        for tab_key, (scroller, _) in self._tab_scrollers.items():
            scroller.configure(width=min(req_w, max_w), height=min(req_h, max_h))
            self._bind_scroll(tab_key)

        self._load_panel(self.current_panel)
        return self.widgets["title"]

    def _bind_scroll(self, tab_key):
        scroller, content = self._tab_scrollers[tab_key]

        def wheel(direction, canvas=scroller):
            canvas.yview_scroll(direction, "units")
            return "break"

        stack = [scroller, content]
        while stack:
            widget = stack.pop()
            widget.bind("<MouseWheel>", lambda event, fn=wheel: fn(-1 if event.delta > 0 else 1), add="+")
            widget.bind("<Button-4>", lambda _e, fn=wheel: fn(-1), add="+")
            widget.bind("<Button-5>", lambda _e, fn=wheel: fn(1), add="+")
            if not isinstance(widget, (ttk.Label, ttk.Frame, tk.Canvas)):
                widget.bind("<FocusIn>", lambda _e, w=widget, tk_key=tab_key: self._reveal(w, tk_key), add="+")
            stack.extend(widget.winfo_children())

    def _reveal(self, widget, tab_key=None):
        if tab_key is None:
            for key, (_, content) in self._tab_scrollers.items():
                if str(widget).startswith(str(content)):
                    tab_key = key
                    break
        if tab_key is None:
            return
        scroller, content = self._tab_scrollers[tab_key]
        scroller.update_idletasks()
        scroller.configure(scrollregion=scroller.bbox("all"))
        total = max(1, content.winfo_height())
        if widget.winfo_height() <= 0 or total <= scroller.winfo_height():
            return
        top = widget.winfo_rooty() - content.winfo_rooty()
        bottom = top + widget.winfo_height()
        first, last = scroller.yview()
        if top < first * total or bottom > last * total:
            scroller.yview_moveto(max(0.0, (top - 8) / total))

    def buttonbox(self):
        box = ttk.Frame(self, padding=(12, 6, 12, 12))
        self.buttons["preview"] = ttk.Button(box, text=tr("qq.panels.preview"), command=self.preview)
        self.buttons["preview"].pack(side="left")
        self.buttons["reset"] = ttk.Button(box, text=tr("qq.panels.reset_selected"), command=self.reset_selected)
        self.buttons["reset"].pack(side="left", padx=(6, 0))
        self.buttons["apply"] = ttk.Button(box, text=tr("qq.panels.apply"), style="Action.TButton", command=self.ok)
        self.buttons["apply"].pack(side="right", padx=(6, 0))
        self.buttons["cancel"] = ttk.Button(box, text=tr("qq.panels.cancel"), command=self.cancel)
        self.buttons["cancel"].pack(side="right")
        box.pack(fill="x")
        self.bind("<Escape>", self.cancel)
        self.bind("<Return>", lambda _e: self.ok())

    def _sync_artist_controls(self):
        pts_on = bool(self.vars["points_visible"].get())
        pts_state = "normal" if pts_on else "disabled"
        self.widgets["points_marker"].configure(state="readonly" if pts_on else "disabled")
        for key in ("points_size", "points_color", "points_alpha"):
            self.widgets[key].configure(state=pts_state)
        self.pickers["points_color"].configure(state=pts_state)

        has_ref = self._has_reference[self.current_panel]
        if has_ref:
            self.ref_unavailable_label.grid_remove()
            self.widgets["ref_visible"].configure(state="normal")
            ref_on = bool(self.vars["ref_visible"].get())
        else:
            self.ref_unavailable_label.grid()
            self.widgets["ref_visible"].configure(state="disabled")
            ref_on = False
        ref_state = "normal" if ref_on else "disabled"
        self.widgets["ref_style"].configure(state="readonly" if ref_on else "disabled")
        for key in ("ref_color", "ref_width", "ref_alpha"):
            self.widgets[key].configure(state=ref_state)
        self.pickers["ref_color"].configure(state=ref_state)

    def _save_current_inputs(self):
        pid = self.current_panel
        prev = self._panel_inputs[pid]
        legend_val = bool(self.vars["legend_visible"].get())
        pts_vis_val = bool(self.vars["points_visible"].get())
        ref_vis_val = bool(self.vars["ref_visible"].get())
        self._panel_inputs[pid] = {
            "title": self.vars["title"].get(),
            "xlabel": self.vars["xlabel"].get(),
            "ylabel": self.vars["ylabel"].get(),
            "xmin": self.vars["xmin"].get(),
            "xmax": self.vars["xmax"].get(),
            "ymin": self.vars["ymin"].get(),
            "ymax": self.vars["ymax"].get(),
            "legend_visible": legend_val,
            "legend_explicit": prev["legend_explicit"] or (legend_val != self._default_legend_visible[pid]),
            "points_visible": pts_vis_val,
            "points_visible_explicit": prev["points_visible_explicit"] or (pts_vis_val != self._default_points_visible[pid]),
            "points_empty_explicit": prev["points_empty_explicit"],
            "points_marker": self.vars["points_marker"].get(),
            "points_size": self.vars["points_size"].get(),
            "points_color": self.vars["points_color"].get(),
            "points_alpha": self.vars["points_alpha"].get(),
            "ref_visible": ref_vis_val,
            "ref_visible_explicit": (
                prev["ref_visible_explicit"]
                or (self._has_reference[pid] and ref_vis_val != self._default_ref_visible[pid])
            ),
            "ref_empty_explicit": prev["ref_empty_explicit"],
            "ref_color": self.vars["ref_color"].get(),
            "ref_width": self.vars["ref_width"].get(),
            "ref_style": self.vars["ref_style"].get(),
            "ref_alpha": self.vars["ref_alpha"].get(),
        }

    def _load_panel(self, panel_id):
        data = self._panel_inputs[panel_id]
        for key in (
            "title", "xlabel", "ylabel", "xmin", "xmax", "ymin", "ymax",
            "points_marker", "points_size", "points_color", "points_alpha",
            "ref_color", "ref_width", "ref_style", "ref_alpha",
        ):
            self.vars[key].set(data[key])
        for key in ("legend_visible", "points_visible", "ref_visible"):
            self.vars[key].set(data[key])
        self._refresh_swatch("points_color")
        self._refresh_swatch("ref_color")
        self._sync_artist_controls()

    def _clear_errors(self):
        for label in self.error_labels.values():
            label.configure(text="")
            label.grid_remove()

    def _on_panel_changed(self, *_):
        if self._syncing_panel:
            return
        new_panel = self.panel_var.get()
        if new_panel not in self.panel_ids or new_panel == self.current_panel:
            return
        self._save_current_inputs()
        self._clear_errors()
        self.current_panel = new_panel
        self._load_panel(new_panel)

    def _build_points_record(self, pid, raw):
        pts = {}
        active = bool(raw["points_visible"])
        if raw["points_visible_explicit"] or active != self._default_points_visible[pid]:
            pts["visible"] = active
        marker = raw["points_marker"]
        if marker in POINT_MARKERS:
            pts["marker"] = marker
        size_s = raw["points_size"].strip()
        if size_s:
            try:
                pts["size"] = _parse_bounded(size_s, MIN_POINT_SIZE, MAX_POINT_SIZE, tr("qq.panels.error.size"))
            except ValueError as err:
                if active:
                    raise _PanelFieldError(pid, "points_size", "points_size", str(err), tab_key="points") from None
        color_s = raw["points_color"].strip()
        if color_s:
            if HEX_RE.fullmatch(color_s):
                pts["color"] = color_s
            elif active:
                raise _PanelFieldError(pid, "points_color", "points_color", tr("qq.panels.error.color"), tab_key="points")
        alpha_s = raw["points_alpha"].strip()
        if alpha_s:
            try:
                pts["alpha"] = _parse_bounded(alpha_s, 0.0, 1.0, tr("qq.panels.error.alpha"))
            except ValueError as err:
                if active:
                    raise _PanelFieldError(pid, "points_alpha", "points_alpha", str(err), tab_key="points") from None
        if pts:
            return pts
        if raw["points_empty_explicit"] and not (size_s or color_s or alpha_s or marker):
            return {}
        return None

    def _build_reference_record(self, pid, raw):
        if not self._has_reference[pid]:
            if self._cleared_hidden_ref.get(pid):
                return None
            existing = self.confirmed_style.get(PANEL_KEY, {}).get(pid, {}).get(REFERENCE_KEY)
            return deepcopy(existing) if isinstance(existing, dict) else None
        ref = {}
        active = bool(raw["ref_visible"])
        if raw["ref_visible_explicit"] or active != self._default_ref_visible[pid]:
            ref["visible"] = active
        color_s = raw["ref_color"].strip()
        if color_s:
            if HEX_RE.fullmatch(color_s):
                ref["color"] = color_s
            elif active:
                raise _PanelFieldError(pid, "ref_color", "ref_color", tr("qq.panels.error.color"), tab_key="reference")
        width_s = raw["ref_width"].strip()
        if width_s:
            try:
                ref["width"] = _parse_bounded(width_s, MIN_LINE_WIDTH, MAX_LINE_WIDTH, tr("qq.panels.error.width"))
            except ValueError as err:
                if active:
                    raise _PanelFieldError(pid, "ref_width", "ref_width", str(err), tab_key="reference") from None
        line_style = raw["ref_style"]
        if line_style in LINE_STYLES:
            ref["style"] = line_style
        alpha_s = raw["ref_alpha"].strip()
        if alpha_s:
            try:
                ref["alpha"] = _parse_bounded(alpha_s, 0.0, 1.0, tr("qq.panels.error.alpha"))
            except ValueError as err:
                if active:
                    raise _PanelFieldError(pid, "ref_alpha", "ref_alpha", str(err), tab_key="reference") from None
        if ref:
            return ref
        if raw["ref_empty_explicit"] and not (color_s or width_s or line_style or alpha_s):
            return {}
        return None

    def _build_candidate(self):
        self._save_current_inputs()
        self._clear_errors()
        candidate = deepcopy(self.confirmed_style)
        preserved = {
            pid: deepcopy(rec)
            for pid, rec in self.confirmed_style.get(PANEL_KEY, {}).items()
            if pid not in self.panel_ids
        }
        panels_out = dict(preserved)
        order = (self.current_panel, *(pid for pid in self.panel_ids if pid != self.current_panel))
        for pid in order:
            raw = self._panel_inputs[pid]
            record = {}
            for key in TEXT_KEYS:
                text = raw[key]
                if text != "":
                    if len(text) > MAX_LABEL_LENGTH:
                        raise _PanelFieldError(pid, key, key, tr("qq.panels.error.label_length"), tab_key="axes")
                    record[key] = text
            axis_dict = {}
            for dim in ("x", "y"):
                err_key = f"{dim}range"
                low_s = raw[f"{dim}min"].strip()
                high_s = raw[f"{dim}max"].strip()
                if bool(low_s) != bool(high_s):
                    missing_widget = f"{dim}min" if not low_s else f"{dim}max"
                    raise _PanelFieldError(pid, err_key, missing_widget, tr("qq.panels.error.both_limits"), tab_key="axes")
                if low_s:
                    try:
                        low = _parse_finite(low_s, tr("qq.panels.error.number"))
                    except ValueError as err:
                        raise _PanelFieldError(pid, err_key, f"{dim}min", str(err), tab_key="axes") from None
                    try:
                        high = _parse_finite(high_s, tr("qq.panels.error.number"))
                    except ValueError as err:
                        raise _PanelFieldError(pid, err_key, f"{dim}max", str(err), tab_key="axes") from None
                    if low >= high or not isfinite(high - low):
                        raise _PanelFieldError(pid, err_key, f"{dim}min", tr("qq.panels.error.order"), tab_key="axes")
                    if Locator().nonsingular(low, high) != (low, high):
                        raise _PanelFieldError(pid, err_key, f"{dim}min", tr("qq.panels.error.nonsingular"), tab_key="axes")
                    axis_dict[dim] = {"min": low, "max": high}
            if axis_dict:
                record["axis"] = axis_dict
            if raw["legend_explicit"] or bool(raw["legend_visible"]) != self._default_legend_visible[pid]:
                record["legend_visible"] = bool(raw["legend_visible"])
            pts_rec = self._build_points_record(pid, raw)
            if pts_rec is not None:
                record[POINTS_KEY] = pts_rec
            ref_rec = self._build_reference_record(pid, raw)
            if ref_rec is not None:
                record[REFERENCE_KEY] = ref_rec
            if record:
                panels_out[pid] = record
        if panels_out:
            candidate[PANEL_KEY] = panels_out
        else:
            candidate.pop(PANEL_KEY, None)
        validated_style(candidate)
        return candidate

    def _show_field_error(self, error):
        if isinstance(error, _PanelFieldError):
            if error.panel_id != self.current_panel:
                self._syncing_panel = True
                try:
                    self._save_current_inputs()
                    self.current_panel = error.panel_id
                    self.panel_var.set(error.panel_id)
                    self._load_panel(error.panel_id)
                finally:
                    self._syncing_panel = False
            self.notebook.select(self.tabs[error.tab_key])
            label = self.error_labels[error.error_key]
            label.configure(text=str(error))
            label.grid()
            target = self.widgets[error.widget_key]
            self.update_idletasks()
            self._reveal(target, error.tab_key)
            if target.winfo_viewable():
                target.focus_force()
            else:
                target.focus_set()
            self.initial_focus = target
            return
        self.notebook.select(self.tabs["axes"])
        label = self.error_labels["title"]
        label.configure(text=translate_message(error))
        label.grid()
        target = self.widgets["title"]
        self.update_idletasks()
        self._reveal(target, "axes")
        if target.winfo_viewable():
            target.focus_force()
        else:
            target.focus_set()
        self.initial_focus = target

    def preview(self):
        try:
            candidate = self._build_candidate()
            apply_style(self.figure, candidate)
        except ValueError as error:
            self._show_field_error(error)
            return False
        self.last_valid_style = deepcopy(candidate)
        self.canvas.draw_idle()
        return True

    def reset_selected(self):
        pid = self.current_panel
        self._cleared_hidden_ref[pid] = True
        self._panel_inputs[pid] = self._inputs_from_style({}, pid)
        self._load_panel(pid)
        self._clear_errors()
        self.preview()

    def validate(self):
        try:
            candidate = self._build_candidate()
            apply_style(self.figure, candidate)
        except ValueError as error:
            self._show_field_error(error)
            return False
        self._validated_style = candidate
        self.last_valid_style = deepcopy(candidate)
        self.canvas.draw_idle()
        return True

    def apply(self):
        self.result = self._validated_style

    def cancel(self, event=None):
        if self.result is None:
            try:
                apply_style(self.figure, deepcopy(self.confirmed_style))
                self.canvas.draw_idle()
            except ValueError:
                pass
        super().cancel(event)
