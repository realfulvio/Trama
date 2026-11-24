"""Tk editor for saved graph presentation settings."""
from copy import deepcopy
import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog, ttk

from matplotlib.colors import to_hex

from .axis_breaks import AXIS_BREAKS, SUPPORT_ATTR, AxisBreakError, axis_breaks_reason
from .linked_axes import LINKED_AXES
from .axis_guides import AXIS_BANDS, AXIS_GUIDES
from .graph_annotations import ANNOTATIONS
from .graph_legend import LEGEND_OPTIONS_KEY
from .graph_shapes import SHAPES
from .presentation import (FONT_FAMILIES, LEGEND_LOCATIONS, LINE_STYLES, MARKERS, SCALES,
                           _check_math_text, _color, _number, _text, active_series_fields, apply_style,
                           axis_has_numeric_ticks, graph_series, validate_graph_style, zero_baseline_axes)
from .xy_series import (BAR_WIDTH, BARS, DRAW_STYLES, RECIPE_KEYS, SIDES, SCALES as XY_SCALES,
                        assign_colors, parse_bar_width, prune_options, xy_series)

from .i18n import active_language, tr, translate_message
from .probability_scale import FRACTION_SCALE, PERCENT_SCALE, PROBABILITY_SCALES
from .qq_panels import PANEL_KEY

# Captions are catalog keys; the dictionary keys stay the style fields.
AXIS_FIELDS = {
    "min": "graph.axis.min", "max": "graph.axis.max", "step": "graph.axis.step",
    "start": "graph.axis.start", "minor": "graph.axis.minor", "decimals": "graph.axis.decimals",
}
BREAK_OWNED_FIELDS = frozenset({"min", "max", "step", "start"})
FONT_FIELDS = {"title_size": "graph.field.font_title", "label_size": "graph.field.font_labels",
               "tick_size": "graph.field.font_ticks", "legend_size": "graph.field.font_legend"}
SERIES_LABELS = {key: "graph.series." + key
                 for key in ("label", "color", "line_style", "width", "marker", "marker_size", "marker_color")}
DEFAULT = "Analysis default"

# Display labels of canonical choice values, one map per kind of control. The controls keep and return
# the canonical value; a value without an entry (a font family, a series name) is shown literally.
SCALE_LABELS = {"linear": "graph.choice.linear", "log": "graph.choice.log",
                FRACTION_SCALE: "graph.choice.probability", PERCENT_SCALE: "graph.choice.probability_percent"}
RIGHT_SCALE_LABELS = {"Linear": "graph.choice.linear", "Log": "graph.choice.log"}
LEGEND_LABELS = {location: "graph.legend." + location.replace(" ", "_") for location in LEGEND_LOCATIONS}
FRAME_LABELS = {"open": "graph.frame.open", "box": "graph.frame.box"}
LINE_LABELS = {style: "graph.line." + style.replace("-", "_") for style in LINE_STYLES}
MARKER_LABELS = {"Circle": "graph.marker.circle", "Square": "graph.marker.square",
                 "Diamond": "graph.marker.diamond", "Triangle up": "graph.marker.triangle_up",
                 "Triangle down": "graph.marker.triangle_down", "Plus": "graph.marker.plus",
                 "Cross": "graph.marker.cross", "Star": "graph.marker.star", "No symbol": "graph.marker.none"}
DRAW_LABELS = {"Points": "graph.draw.points", "Line": "graph.draw.line", "Line and points": "graph.draw.line_points",
               "Step": "graph.draw.step", "Bars": "graph.draw.bars"}
SIDE_LABELS = {"Left": "graph.side.left", "Right": "graph.side.right"}
DEFAULT_LABELS = {DEFAULT: "graph.choice.analysis_default"}


SERIES_KINDS = {"line": ("Line", "graph.kind.line"), "errorbar": ("Error bars", "graph.kind.errorbar"),
                "scatter": ("Scatter", "graph.kind.scatter"), "bar": ("Bar", "graph.kind.bar")}


def series_name(series):
    """The selector text of a plot element: the kind is translated, the legend label stays literal."""
    english, key = SERIES_KINDS.get(series.kind, (None, None))
    parts = series.key.split(":", 2)
    caption = tr(key) if key else english
    if key is None or caption == english or len(parts) != 3:
        return series.name
    _, number, label = parts
    return f"{caption} · {label} ({number})" if label else f"{caption} {number}"


def choice_text(labels, value):
    key = labels.get(value)
    return tr(key) if key else value


class ChoiceBinding:
    """A read-only combobox that shows translated labels while ``variable`` keeps the canonical value.

    The labels are resolved by position within this control only, so two controls that share a caption
    never resolve through each other, and traces on ``variable`` always see the canonical value.
    """

    def __init__(self, combobox, variable, values, labels):
        self.combobox, self.variable, self.labels_by_value = combobox, variable, labels
        self.display = tk.StringVar(combobox)
        self._syncing = False
        combobox.configure(textvariable=self.display)
        variable.trace_add("write", self._show)
        self.display.trace_add("write", self._resolve)
        self.set_values(values)

    def set_values(self, values):
        self.values = tuple(values)
        self.labels = tuple(choice_text(self.labels_by_value, value) for value in self.values)
        self.combobox.configure(values=self.labels)
        self._show()

    def _show(self, *_):
        if self._syncing:
            return
        value = self.variable.get()
        self._syncing = True
        try:
            self.display.set(self.labels[self.values.index(value)] if value in self.values else value)
        finally:
            self._syncing = False

    def _resolve(self, *_):
        if self._syncing:
            return
        label = self.display.get()
        self._syncing = True
        try:
            self.variable.set(self.values[self.labels.index(label)] if label in self.labels else label)
        finally:
            self._syncing = False


def pick_color(parent, variable):
    try:
        initial = to_hex(variable.get())
    except ValueError:
        initial = "#2866ae"
    _, selected = colorchooser.askcolor(color=initial, parent=parent)
    if selected:
        variable.set(selected)


class _BreaksProblem(ValueError):
    """The axis breaks of this dialog cannot be drawn together with the other choices."""


class GraphFormatDialog(simpledialog.Dialog):
    def __init__(self, parent, axes, style, *, xy=None):
        self.axes = axes
        self.style = style
        self.xy = xy
        self.xy_update = None
        self.xy_result = None
        self.series = graph_series(axes)
        # Entries hold text; the visibility of an XY series stays a boolean.
        self.series_values = {
            key: {name: value if name == "visible" else str(value) for name, value in options.items()}
            for key, options in style.get("series", {}).items()
        }
        options = (xy or {}).get("options") or {}
        self._xy_style = dict(options.get("Series style") or {})
        self._xy_side = dict(options.get("Series side") or {})
        self._series_index = -1
        self._axis_guides = deepcopy(style.get(AXIS_GUIDES, []))
        self._axis_bands = deepcopy(style.get(AXIS_BANDS, []))
        self._axis_breaks = deepcopy(style.get(AXIS_BREAKS, {}))
        self._breaks_previewed = False
        self._legend_options = deepcopy(style.get(LEGEND_OPTIONS_KEY, {}))
        self._hierarchical = None
        self._guides_previewed = False
        self._legend_previewed = False
        self.error_widget = None
        self._pending_error_target = None
        super().__init__(parent, tr("graph.format.title"))

    def body(self, master):
        self.inputs, self.axis_fields, self.appearance, self.choices = {}, {}, {}, {}
        self._appearance_widgets, self._axis_widgets, self._right_widgets = {}, {}, {}
        self.notebook = ttk.Notebook(master, width=530)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)
        appearance = self._tab(tr("graph.format.appearance"))
        initial_focus = self._appearance_tab(appearance)
        self._axes_tab(self._tab(tr("graph.format.axes")))
        self._series_tab(self._tab(tr("graph.format.series")))
        self._references_tab(self._tab(tr("graph.format.references")))
        # Longer captions (Italian) widen the pane instead of squeezing the choices of the Axes tab.
        self.notebook.update_idletasks()
        needed = max(self.notebook.nametowidget(tab).winfo_reqwidth() for tab in self.notebook.tabs())
        if needed > 530:
            self.notebook.configure(width=needed)
        return initial_focus

    def _tab(self, name):
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text=name)
        return frame

    def _field(self, master, row, label, value="", choices=(), width=21, labels=None):
        """A captioned entry, or a read-only combobox of canonical ``choices`` shown through ``labels``."""
        ttk.Label(master, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        variable = tk.StringVar(self, value=value)
        if choices:
            widget = ttk.Combobox(master, state="readonly", width=width)
            self.choices[str(widget)] = ChoiceBinding(widget, variable, choices, labels or {})
        else:
            widget = ttk.Entry(master, textvariable=variable, width=width)
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        return variable, widget

    def _appearance_tab(self, tab):
        tab.columnconfigure(1, weight=1)
        initial_focus = None
        for row, (key, caption, value) in enumerate((
            ("title", "graph.field.title", self.axes.get_title()),
            ("xlabel", "graph.field.xlabel", self.axes.get_xlabel()),
            ("ylabel", "graph.field.ylabel", self.axes.get_ylabel()),
        )):
            self.inputs[key], entry = self._field(tab, row, tr(caption), self.style.get(key, value))
            self._appearance_widgets[key] = entry
            if initial_focus is None:
                initial_focus = entry
        for row, (key, caption, choices, labels) in enumerate((
            ("font_family", "graph.field.font_family", FONT_FAMILIES, {}),
            ("legend", "graph.field.legend_position", LEGEND_LOCATIONS, LEGEND_LABELS),
            ("frame", "graph.field.frame", ("open", "box"), FRAME_LABELS),
        ), start=3):
            self.appearance[key], self._appearance_widgets[key] = self._field(
                tab, row, tr(caption), self.style.get(key, DEFAULT), (DEFAULT, *choices),
                labels={**DEFAULT_LABELS, **labels})
        self.grid_lines = tk.BooleanVar(self, self.style.get("grid", any(
            line.get_visible() for line in self.axes.get_xgridlines() + self.axes.get_ygridlines())))
        self.minor_grid = tk.BooleanVar(self, self.style.get("grid_minor", False))
        ttk.Checkbutton(tab, text=tr("graph.field.major_grid"), variable=self.grid_lines).grid(
            row=6, column=0, sticky="w")
        ttk.Checkbutton(tab, text=tr("graph.field.minor_grid"), variable=self.minor_grid).grid(
            row=6, column=1, sticky="w")

        fonts = ttk.LabelFrame(tab, text=tr("graph.field.font_sizes"), padding=(8, 4))
        fonts.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        for column, (key, caption) in enumerate(FONT_FIELDS.items()):
            ttk.Label(fonts, text=tr(caption)).grid(row=0, column=column, padx=6, sticky="w")
            variable = self.appearance[key] = tk.StringVar(self, self.style.get(key, ""))
            entry = ttk.Entry(fonts, width=9, textvariable=variable)
            entry.grid(row=1, column=column, padx=6, pady=3, sticky="w")
            self._appearance_widgets[key] = entry
        ttk.Label(fonts, text=tr("graph.field.font_hint"), wraplength=490, justify="left").grid(
            row=2, column=0, columnspan=4, padx=6, sticky="w")
        from .hierarchical_style import describe_hierarchical_artists

        if describe_hierarchical_artists(self.axes.figure):
            ttk.Button(tab, text=tr("hierarchy.style.button"), command=self._edit_hierarchical).grid(
                row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))
        if "accent" in self.style:
            self.inputs["accent"], self._appearance_widgets["accent"] = self._field(
                tab, 8, tr("graph.field.accent"), to_hex(self.style["accent"], keep_alpha=True))
            ttk.Button(tab, text=tr("graph.field.pick"), command=lambda: self._pick_color(self.inputs["accent"])).grid(
                row=8, column=2, padx=(4, 0))
        from .graph_legend_dialog import legend_summary

        legend_row = 9 if "accent" in self.style else 8
        self.legend_button = ttk.Button(tab, text=tr("legend_editor.button"), command=self._edit_legend_options)
        self.legend_button.grid(row=legend_row, column=0, sticky="w", pady=(8, 0))
        self.legend_summary = ttk.Label(tab, text=legend_summary(self._legend_options), foreground="#506575")
        self.legend_summary.grid(row=legend_row, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 0))
        return initial_focus

    def _axes_tab(self, tab):
        self._axis_refreshers = {}
        for column, dimension in enumerate(("x", "y")):
            axis = getattr(self.axes, dimension + "axis")
            options = self.style.get("axis", {}).get(dimension, {})
            block = ttk.LabelFrame(tab, text=tr("graph.axis.block", axis=dimension.upper()), padding=(8, 4))
            block.grid(row=0, column=column, padx=(0 if column == 0 else 8, 0), sticky="nsew")
            tab.columnconfigure(column, weight=1, uniform="axis")
            block.columnconfigure(1, weight=1)
            scale_key = dimension + "scale"
            zero_baseline = dimension in zero_baseline_axes(self.axes)
            scale, widget = self._field(block, 0, tr("graph.axis.scale"), self.style.get(scale_key, axis.get_scale()),
                                        ("linear",) if zero_baseline else SCALES, width=13, labels=SCALE_LABELS)
            self.inputs[scale_key] = scale
            numeric = axis_has_numeric_ticks(self.axes, dimension)
            if not numeric or (zero_baseline and scale.get() == "linear"):
                widget.configure(state="disabled")
            fields = self.axis_fields[dimension] = {}
            widgets = self._axis_widgets[dimension] = {"scale": widget}
            for row, (key, caption) in enumerate(AXIS_FIELDS.items(), start=1):
                fields[key], widgets[key] = self._field(block, row, tr(caption), options.get(key, ""), width=10)

            def refresh(*_, scale=scale, widgets=widgets, numeric=numeric, dimension=dimension):
                broken = self._axis_breaks.get("axis") == dimension
                for key, entry in widgets.items():
                    if key == "scale":
                        continue
                    mode = scale.get()
                    disabled = (not numeric or (mode == "log" and key in {"step", "start"})
                                or (mode in PROBABILITY_SCALES and key not in {"min", "max"})
                                or (broken and key in BREAK_OWNED_FIELDS))
                    entry.configure(state="disabled" if disabled else "normal")

            scale.trace_add("write", refresh)
            self._axis_refreshers[dimension] = refresh
            refresh()
            if not numeric:
                ttk.Label(block, text=tr("graph.axis.categorical"), foreground="#506575").grid(
                    row=len(AXIS_FIELDS) + 1, column=0, columnspan=2, sticky="w")
        ttk.Label(tab, text=tr("graph.axis.hint"), wraplength=490, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        if self.xy is not None:
            options = self.xy.get("options") or {}
            block = ttk.LabelFrame(tab, text=tr("graph.axis.right"), padding=(8, 4))
            block.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            block.columnconfigure(1, weight=1)
            twin = self.axes.figure.axes[1] if len(self.axes.figure.axes) > 1 else None
            self.right_title, self._right_widgets["Right title"] = self._field(
                block, 0, tr("graph.axis.right_title"), options.get("Right title") or (twin.get_ylabel() if twin else ""))
            self.right_scale, self._right_widgets["Right scale"] = self._field(
                block, 1, tr("graph.axis.scale"), options.get("Right scale") or "Linear", XY_SCALES, width=13,
                labels=RIGHT_SCALE_LABELS)
            self.right_min, self._right_widgets["Right minimum"] = self._field(
                block, 2, tr("graph.axis.min"), "" if options.get("Right minimum") in (None, "") else str(options.get("Right minimum")), width=10)
            self.right_max, self._right_widgets["Right maximum"] = self._field(
                block, 3, tr("graph.axis.max"), "" if options.get("Right maximum") in (None, "") else str(options.get("Right maximum")), width=10)
        if getattr(self.axes, SUPPORT_ATTR, False):
            from .axis_breaks_dialog import breaks_summary

            block = ttk.LabelFrame(tab, text=tr("axis_breaks.title"), padding=(8, 4))
            block.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            block.columnconfigure(1, weight=1)
            self.breaks_button = ttk.Button(block, text=tr("axis_breaks.button"), command=self._edit_axis_breaks)
            self.breaks_button.grid(row=0, column=0, sticky="w")
            self.breaks_summary = ttk.Label(block, text=breaks_summary(self._axis_breaks), foreground="#506575")
            self.breaks_summary.grid(row=0, column=1, sticky="w", padx=(8, 0))
            self.breaks_note = ttk.Label(block, text="", foreground="#506575", wraplength=470, justify="left")
            self.breaks_note.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
            self._refresh_break_states()

    def _series_tab(self, tab):
        self.series_fields, self._series_widgets = {}, {}
        ttk.Label(tab, text=tr("graph.series.element")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.series_selector = ttk.Combobox(tab, values=[series_name(series) for series in self.series], width=40,
                                            state="readonly" if self.series else "disabled")
        self.series_selector.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 4))
        tab.columnconfigure(1, weight=1)
        for row, (key, caption) in enumerate(SERIES_LABELS.items(), start=1):
            choices = (DEFAULT, *LINE_STYLES) if key == "line_style" else (
                (DEFAULT, *MARKERS) if key == "marker" else ())
            labels = {**DEFAULT_LABELS, **(LINE_LABELS if key == "line_style" else MARKER_LABELS)}
            self.series_fields[key], self._series_widgets[key] = self._field(tab, row, tr(caption), choices=choices,
                                                                             labels=labels)
            if key in {"color", "marker_color"}:
                button = ttk.Button(tab, text=tr("graph.field.pick"), command=lambda key=key: pick_color(self, self.series_fields[key]))
                button.grid(row=row, column=2, padx=(4, 0))
                self._series_widgets[key + "_button"] = button
        self.draw_style = self.side = self.series_visible = self.bar_width = None
        next_row = len(SERIES_LABELS) + 1
        if self.xy is not None:
            # Step and Bars can hide a series; the box stays saved, and inactive, for the other draw styles.
            self.series_visible = tk.BooleanVar(self, True)
            self._series_widgets["visible"] = ttk.Checkbutton(tab, text=tr("graph.series.visible"),
                                                              variable=self.series_visible)
            self._series_widgets["visible"].grid(row=next_row, column=1, sticky="w", pady=3)
            self.draw_style, self._draw_widget = self._field(tab, next_row + 1, tr("graph.series.draw_style"),
                                                             choices=DRAW_STYLES, labels=DRAW_LABELS)
            self.draw_style.trace_add("write", self._refresh_series_states)
            self.side, self._side_widget = self._field(tab, next_row + 2, tr("graph.series.side"), choices=SIDES,
                                                       labels=SIDE_LABELS)
            # One width for every cluster of bars, in X units; blank is Auto. Shown only while a series is Bars.
            saved = (self.xy.get("options") or {}).get(BAR_WIDTH)
            self.bar_width, self._bar_width_widget = self._field(tab, next_row + 3, tr("graph.series.bar_width"),
                                                                 self._width_text(saved), width=10)
            self._bar_width_widget.grid_configure(sticky="w")
            self._bar_width_caption = tab.grid_slaves(row=next_row + 3, column=0)[0]
            self._bar_width_hint = ttk.Label(tab, text=tr("graph.series.bar_width_hint"), foreground="#506575")
            self._bar_width_hint.grid(row=next_row + 3, column=2, sticky="w", padx=(4, 0))
            next_row += 4
        hint = tr("graph.series.hint" if self.series else "graph.series.none")
        self.series_hint_label = ttk.Label(tab, text=hint, wraplength=490)
        self.series_hint_label.grid(row=next_row, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.series_selector.bind("<<ComboboxSelected>>", self._select_series)
        if self.series:
            self.series_selector.current(0)
        self._select_series()

    @staticmethod
    def _width_text(value):
        """A saved cluster width as the user reads it: the Italian interface shows a decimal comma."""
        if value in (None, ""):
            return ""
        text = f"{value:g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
        return text.replace(".", ",") if active_language() == "it" else text

    def _has_bars(self):
        """Whether a series of this dialog is drawn as Bars, counting the unsaved choice of the selected one."""
        styles = dict(self._xy_style)
        series = self.series[self._series_index] if 0 <= self._series_index < len(self.series) else None
        if series is not None and series.kind == "xy" and self.draw_style is not None and self.draw_style.get():
            styles[series.name] = self.draw_style.get()
        columns = (self.xy.get("options") or {}).get("Y columns") or []
        return any(styles.get(column) == BARS for column in columns)

    def _store_series(self):
        if self._series_index < 0:
            return
        series = self.series[self._series_index]
        options = {}
        for key in series.fields:
            if key == "visible":
                if self.series_visible is not None and not self.series_visible.get():
                    options[key] = False
                continue
            value = self.series_fields[key].get().strip()
            if value and (key not in {"marker", "line_style"} or value != DEFAULT):
                options[key] = MARKERS[value] if key == "marker" else value
        if options:
            self.series_values[series.key] = options
        else:
            self.series_values.pop(series.key, None)
        if self.xy is not None and series.kind == "xy" and self.draw_style is not None:
            self._xy_style[series.name] = self.draw_style.get() or "Points"
            self._xy_side[series.name] = self.side.get() or "Left"

    def _refresh_series_states(self, *_args):
        series = self.series[self._series_index] if 0 <= self._series_index < len(self.series) else None
        draw = self.draw_style.get() if (self.draw_style is not None and series and series.kind == "xy") else None
        active_fields = active_series_fields(self.axes, series, draw) if series else set()
        for key in self.series_fields:
            enabled = bool(series and key in active_fields)
            widget = self._series_widgets[key]
            state = "readonly" if key in {"marker", "line_style"} else "normal"
            widget.configure(state=state if enabled else "disabled")
            if key + "_button" in self._series_widgets:
                self._series_widgets[key + "_button"].configure(state="normal" if enabled else "disabled")
        if self.series_visible is not None:
            enabled = bool(series and "visible" in active_fields)
            self._series_widgets["visible"].state(["!disabled" if enabled else "disabled"])
        if self.bar_width is not None:
            shown = self._has_bars()
            for widget in (self._bar_width_caption, self._bar_width_widget, self._bar_width_hint):
                widget.grid() if shown else widget.grid_remove()
        if hasattr(self, "series_hint_label"):
            if not self.series:
                hint = tr("graph.series.none")
            elif series and series.kind == "xy" and active_fields != series.fields:
                hint = tr("graph.series.inactive_hint")
            else:
                hint = tr("graph.series.hint")
            self.series_hint_label.configure(text=hint)

    def _select_series(self, _event=None):
        self._store_series()
        self._series_index = self.series_selector.current()
        series = self.series[self._series_index] if self._series_index >= 0 else None
        options = self.series_values.get(series.key, {}) if series else {}
        for key, variable in self.series_fields.items():
            value = options.get(key, "")
            widget = self._series_widgets[key]
            if key == "marker":
                markers = {label: code for label, code in MARKERS.items()
                           if code != "none" or (series and series.kind in {"line", "errorbar", "xy"})}
                self.choices[str(widget)].set_values((DEFAULT, *markers))
                value = next((label for label, code in markers.items() if code == value), DEFAULT)
            elif key == "line_style":
                value = value or DEFAULT
            variable.set(value)
        if self.series_visible is not None:
            self.series_visible.set(options.get("visible", True) is not False)
        if self.draw_style is not None:
            active = series is not None and series.kind == "xy"
            state = "readonly" if active else "disabled"
            self._draw_widget.configure(state=state)
            self._side_widget.configure(state=state)
            if active:
                self.draw_style.set(self._xy_style.get(series.name, "Points"))
                self.side.set(self._xy_side.get(series.name, "Left"))
        self._refresh_series_states()

    def _references_tab(self, tab):
        ttk.Label(tab, text=tr("graph.references.hint"), justify="left", wraplength=490).pack(anchor="w")
        self.references = tk.Text(tab, width=54, height=8, wrap="none", padx=5, pady=5)
        self.references.pack(fill="both", expand=True, pady=(8, 0))
        for line in self.style.get("reference_lines", []):
            label = ", " + line["label"] if line.get("label") else ""
            self.references.insert("end", f"{line['axis'].upper()}, {line['value']}{label}\n")
        extra = ttk.Frame(tab)
        extra.pack(fill="x", pady=(10, 0))
        extra.columnconfigure(1, weight=1)
        self.guides_button = ttk.Button(extra, text=tr("graph.guides.button"), command=self._edit_axis_guides)
        self.guides_button.grid(row=0, column=0, sticky="w", pady=2)
        self.guides_summary = ttk.Label(extra, text="", foreground="#506575")
        self.guides_summary.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=2)
        self.bands_button = ttk.Button(extra, text=tr("graph.bands.button"), command=self._edit_axis_bands)
        self.bands_button.grid(row=1, column=0, sticky="w", pady=2)
        self.bands_summary = ttk.Label(extra, text="", foreground="#506575")
        self.bands_summary.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=2)
        self._refresh_guide_summaries()

    def _refresh_guide_summaries(self):
        for label, items in ((self.guides_summary, self._axis_guides), (self.bands_summary, self._axis_bands)):
            text = tr("graph.guides.summary_count", count=len(items)) if items else tr("graph.guides.summary_none")
            label.configure(text=text)

    def _refresh_legend_summary(self):
        from .graph_legend_dialog import legend_summary

        if hasattr(self, "legend_summary"):
            self.legend_summary.configure(text=legend_summary(self._legend_options))

    def _preview_legend_options(self, options):
        figure = getattr(self.axes, "figure", None)
        if figure is None:
            return
        try:
            base = self._read_style()
        except ValueError:
            base = deepcopy(self.style)
            for dim in ("x", "y"):
                if dim + "scale" in self.inputs:
                    base[dim + "scale"] = self.inputs[dim + "scale"].get()
        if options is None:
            candidate = base
        else:
            candidate = deepcopy(base)
            if options:
                candidate[LEGEND_OPTIONS_KEY] = deepcopy(options)
            else:
                candidate.pop(LEGEND_OPTIONS_KEY, None)
        try:
            apply_style(figure, candidate)
        except ValueError:
            apply_style(figure, base)
            raise
        self._legend_previewed = True
        canvas = getattr(figure, "canvas", None)
        if canvas is not None:
            canvas.draw_idle()

    def _edit_legend_options(self):
        from .graph_legend_dialog import LegendEditorDialog

        dialog = LegendEditorDialog(
            self,
            getattr(self.axes, "figure", None),
            self._legend_options,
            preview=self._preview_legend_options,
        )
        self.grab_set()
        if dialog.result is not None:
            self._legend_options = dialog.result
            self._refresh_legend_summary()
            if self._legend_previewed:
                self._preview_legend_options(self._legend_options)

    def _refresh_break_states(self):
        """The limits and the scale of an axis with breaks come from the segments, so those fields rest."""
        axis = self._axis_breaks.get("axis")
        for dimension, refresh in self._axis_refreshers.items():
            refresh()
            scale = self._axis_widgets[dimension].get("scale")
            if scale is not None and dimension == axis:
                scale.configure(state="disabled")
        if hasattr(self, "breaks_summary"):
            from .axis_breaks_dialog import breaks_summary

            from .axis_breaks_dialog import translate_breaks_error

            self.breaks_summary.configure(text=breaks_summary(self._axis_breaks))
            reason = axis_breaks_reason(self.axes.figure) if axis else None
            if reason:
                note = tr("axis_breaks.status.ignored", reason=translate_breaks_error(ValueError(reason)))
            else:
                note = tr("axis_breaks.axis_note", axis=axis.upper()) if axis else ""
            self.breaks_note.configure(text=note)

    def _preview_axis_breaks(self, record):
        """Draw ``record`` on the graph, ``None`` goes back to the look this dialog had before."""
        figure = getattr(self.axes, "figure", None)
        if figure is None:
            return
        try:
            base = self._read_style()
        except ValueError:
            base = deepcopy(self.style)
            for dim in ("x", "y"):
                if dim + "scale" in self.inputs:
                    base[dim + "scale"] = self.inputs[dim + "scale"].get()
        base.pop(AXIS_BREAKS, None)
        if record is None:
            candidate = deepcopy(base)
            if self._axis_breaks:
                candidate[AXIS_BREAKS] = deepcopy(self._axis_breaks)
        else:
            candidate = deepcopy(base)
            if record:
                candidate[AXIS_BREAKS] = deepcopy(record)
        try:
            apply_style(figure, candidate)
        except ValueError:
            apply_style(figure, self._breaks_fallback(base))
            raise
        reason = axis_breaks_reason(figure) if record else None
        if reason:
            apply_style(figure, self._breaks_fallback(base))
            raise ValueError(reason)
        self._breaks_previewed = True
        canvas = getattr(figure, "canvas", None)
        if canvas is not None:
            canvas.draw_idle()

    def _breaks_fallback(self, base):
        fallback = deepcopy(base)
        if self._axis_breaks:
            fallback[AXIS_BREAKS] = deepcopy(self._axis_breaks)
        return fallback

    def _edit_axis_breaks(self):
        from .axis_breaks_dialog import AxisBreaksDialog

        dialog = AxisBreaksDialog(
            self,
            self.axes,
            self._axis_breaks,
            preview=self._preview_axis_breaks,
            busy=None,
        )
        self.grab_set()
        if dialog.result is not None:
            self._axis_breaks = dialog.result
            self._refresh_break_states()

    def _preview_guides_or_bands(self, key, records):
        figure = getattr(self.axes, "figure", None)
        if figure is None:
            return
        try:
            base = self._read_style()
        except ValueError:
            base = deepcopy(self.style)
            for dim in ("x", "y"):
                if dim + "scale" in self.inputs:
                    base[dim + "scale"] = self.inputs[dim + "scale"].get()
        if records is None:
            candidate = base
        else:
            candidate = deepcopy(base)
            if records:
                candidate[key] = deepcopy(records)
            else:
                candidate.pop(key, None)
        try:
            apply_style(figure, candidate)
        except ValueError:
            apply_style(figure, base)
            raise
        self._guides_previewed = True
        canvas = getattr(figure, "canvas", None)
        if canvas is not None:
            canvas.draw_idle()

    def _scale_overrides(self):
        return {
            dim: self.inputs[dim + "scale"].get()
            for dim in ("x", "y")
            if dim + "scale" in self.inputs
        }

    def _edit_axis_guides(self):
        from .axis_guides_dialog import AxisGuidesDialog

        dialog = AxisGuidesDialog(
            self,
            self.axes,
            self._axis_guides,
            preview=lambda records: self._preview_guides_or_bands(AXIS_GUIDES, records),
            scale_overrides=self._scale_overrides(),
        )
        self.grab_set()
        if dialog.result is not None:
            self._axis_guides = dialog.result
            self._refresh_guide_summaries()

    def _edit_axis_bands(self):
        from .axis_guides_dialog import AxisBandsDialog

        dialog = AxisBandsDialog(
            self,
            self.axes,
            self._axis_bands,
            preview=lambda records: self._preview_guides_or_bands(AXIS_BANDS, records),
            scale_overrides=self._scale_overrides(),
        )
        self.grab_set()
        if dialog.result is not None:
            self._axis_bands = dialog.result
            self._refresh_guide_summaries()

    def _hierarchical_section(self):
        """The section edited in this dialog, otherwise the one the graph already confirmed."""
        if self._hierarchical is not None:
            return deepcopy(self._hierarchical) if self._hierarchical else None
        if self.style.get("hierarchical"):
            return deepcopy(self.style["hierarchical"])
        return None

    def _edit_hierarchical(self):
        from .hierarchical_style_dialog import HierarchicalStyleDialog

        current = deepcopy(self.style)
        if self._hierarchical is not None:
            current.pop("hierarchical", None)
            if self._hierarchical:
                current["hierarchical"] = deepcopy(self._hierarchical)
        dialog = HierarchicalStyleDialog(
            self, self.axes.figure, getattr(self.axes.figure, "canvas", None), current)
        if dialog.touched:
            self._guides_previewed = True
        if dialog.result is not None:
            self._hierarchical = deepcopy(dialog.result.get("hierarchical", {}))

    def cancel(self, event=None):
        if (self._guides_previewed or self._legend_previewed or self._breaks_previewed) and self.result is None:
            figure = getattr(self.axes, "figure", None)
            if figure is not None:
                try:
                    apply_style(figure, deepcopy(self.style))
                    canvas = getattr(figure, "canvas", None)
                    if canvas is not None:
                        canvas.draw_idle()
                except ValueError:
                    pass
        super().cancel(event)

    def buttonbox(self):
        box = ttk.Frame(self, padding=(8, 0, 8, 8))
        ttk.Button(box, text=tr("graph.format.reset"), command=self._reset).pack(side="left")
        ttk.Button(box, text=tr("graph.format.cancel"), command=self.cancel).pack(side="right")
        ttk.Button(box, text=tr("graph.format.apply"), style="Action.TButton", command=self.ok).pack(
            side="right", padx=(0, 6))
        self.bind("<Return>", self._return)
        self.bind("<Escape>", self.cancel)
        box.pack(fill="x")

    def _return(self, event):
        if event.widget is not self.references:
            self.ok()

    def _reset(self):
        style = {key: deepcopy(self.style[key]) for key in (ANNOTATIONS, SHAPES, PANEL_KEY, "points") if self.style.get(key)}
        section = self._hierarchical_section()
        if section:
            style["hierarchical"] = section
        if self.xy is not None:
            options = {key: value for key, value in self.xy["options"].items() if key not in RECIPE_KEYS}
            try:
                self._prepare_xy(style, options)
            except ValueError as error:
                messagebox.showerror(tr("graph.format.error_title"), translate_message(error), parent=self)
                return
        self.result = style
        self.cancel()

    def _read_style(self):
        style = {key: variable.get() for key, variable in self.inputs.items()
                 if key != "accent" or variable.get().strip()}
        # Linked secondary axes have no Tk editor: the saved record travels through Format Graph unchanged.
        for key in ("groups", ANNOTATIONS, SHAPES, PANEL_KEY, LINKED_AXES, "points"):
            if self.style.get(key):
                style[key] = deepcopy(self.style[key])
        section = self._hierarchical_section()
        if section:
            style["hierarchical"] = section
        style["grid"] = self.grid_lines.get()
        style["grid_minor"] = self.minor_grid.get()
        for key, variable in self.appearance.items():
            value = variable.get().strip()
            if value and value != DEFAULT:
                self._pending_error_target = (0, self._appearance_widgets.get(key), None)
                style[key] = float(value) if key in FONT_FIELDS else value
        axes = {}
        for dimension, fields in self.axis_fields.items():
            settings = {}
            scale = style[dimension + "scale"]
            for key, variable in fields.items():
                value = variable.get().strip()
                if (not value or (scale == "log" and key in {"step", "start"})
                        or (scale in PROBABILITY_SCALES and key not in {"min", "max"})):
                    continue
                self._pending_error_target = (1, self._axis_widgets[dimension].get(key), None)
                settings[key] = int(value) if key in {"minor", "decimals"} else float(value)
            if settings:
                axes[dimension] = settings
        if axes:
            style["axis"] = axes
        self._store_series()
        if self.series_values:
            series_keys = [item.key for item in self.series]
            parsed_series = {}
            for series, options in self.series_values.items():
                index = series_keys.index(series) if series in series_keys else None
                parsed_options = {}
                for key, value in options.items():
                    self._pending_error_target = (2, self._series_widgets.get(key), index)
                    parsed_options[key] = float(value) if key in {"width", "marker_size"} else value
                parsed_series[series] = parsed_options
            style["series"] = parsed_series
        refs = []
        self._pending_error_target = (3, self.references, None)
        for line in self.references.get("1.0", "end").splitlines():
            if not line.strip():
                continue
            cells = [cell.strip() for cell in line.split(",", 2)]
            if len(cells) < 2:
                raise ValueError(tr("graph.references.error"))
            refs.append({"axis": cells[0].lower(), "value": float(cells[1]), "label": cells[2] if len(cells) == 3 else ""})
        if refs:
            style["reference_lines"] = refs
        if self._axis_guides:
            style[AXIS_GUIDES] = deepcopy(self._axis_guides)
        if self._axis_bands:
            style[AXIS_BANDS] = deepcopy(self._axis_bands)
        if self._axis_breaks:
            style[AXIS_BREAKS] = deepcopy(self._axis_breaks)
        if self._legend_options:
            style[LEGEND_OPTIONS_KEY] = deepcopy(self._legend_options)
        if self.xy is not None:
            for key, var in (("Right minimum", self.right_min), ("Right maximum", self.right_max)):
                raw = var.get().strip()
                if raw:
                    self._pending_error_target = (1, self._right_widgets.get(key), None)
                    float(raw)
        self._pending_error_target = None
        return style

    def _locate_series_error(self):
        series_keys = [item.key for item in self.series]
        for series_key, options in self.series_values.items():
            index = series_keys.index(series_key) if series_key in series_keys else None
            for field in ("label", "color", "line_style", "width", "marker", "marker_size", "marker_color"):
                if field not in options:
                    continue
                val = options[field]
                try:
                    if field in {"color", "marker_color"}:
                        if not _color(val):
                            raise ValueError("Enter a valid color, for example #2866ae.")
                    elif field in {"width", "marker_size"}:
                        num = float(val)
                        if not _number(num) or not 0.1 <= num <= 72:
                            raise ValueError("Enter line widths and symbol sizes between 0.1 and 72 points.")
                    elif field == "line_style":
                        if val not in LINE_STYLES:
                            raise ValueError("Choose a valid line style.")
                    elif field == "marker":
                        if val not in MARKERS.values():
                            raise ValueError("Choose a valid symbol.")
                    elif field == "label":
                        if not _text(val) or val.startswith("_"):
                            raise ValueError("Invalid label.")
                        _check_math_text(val)
                except ValueError:
                    return 2, self._series_widgets.get(field), index
        return None

    def _focus_error(self, error):
        target = self._pending_error_target
        if target is None and (isinstance(error, (AxisBreakError, _BreaksProblem))) and hasattr(self, "breaks_button"):
            target = (1, self.breaks_button, None)
        if target is None:
            field_name = getattr(error, "field", None)
            if field_name in {"Right scale", "Right minimum", "Right maximum", "Right title"}:
                target = (1, self._right_widgets.get(field_name), None)
            elif field_name == "Y minimum":
                target = (1, self._axis_widgets.get("y", {}).get("min"), None)
            elif field_name in {"X scale", "Y scale"}:
                target = (1, self._axis_widgets.get(field_name[0].lower(), {}).get("scale"), None)
            elif field_name == BAR_WIDTH and self.bar_width is not None:
                target = (2, self._bar_width_widget, None)
            elif field_name == "Y columns" and self.draw_style is not None and getattr(error, "column", None):
                # A Bars series with a repeated X: show that series with its draw style.
                names = [item.name if item.kind == "xy" else None for item in self.series]
                index = names.index(error.column) if error.column in names else None
                target = (2, self._draw_widget, index)
            else:
                target = self._locate_series_error()
        if target is None:
            msg = str(error)
            if "reference" in msg.casefold():
                target = (3, self.references, None)
            elif "guide" in msg.casefold() or "tick" in msg.casefold() and "logarithmic" in msg.casefold():
                target = (3, getattr(self, "guides_button", self.references), None)
            elif "band" in msg.casefold():
                target = (3, getattr(self, "bands_button", self.references), None)
            elif "legend formatting" in msg.casefold() or "legend border" in msg.casefold() or "legend background" in msg.casefold() or "legend column" in msg.casefold() or "legend entry" in msg.casefold() or "legend title" in msg.casefold() or "legend frame" in msg.casefold():
                target = (0, getattr(self, "legend_button", self._appearance_widgets.get("legend")), None)
            elif any(word in msg.casefold() for word in ("font", "legend", "frame", "title", "label")):
                target = (0, self._appearance_widgets.get("title"), None)
            elif any(word in msg.casefold() for word in ("axis", "limit", "tick", "interval", "logarithm", "probability")):
                target = (1, self._axis_widgets.get("x", {}).get("min"), None)
        if target is not None:
            tab_index, widget, series_index = target
            self.notebook.select(tab_index)
            if series_index is not None and 0 <= series_index < len(self.series):
                self.series_selector.current(series_index)
                self._select_series()
            if widget is not None:
                self.error_widget = widget
                self.update_idletasks()
                widget.focus_set()

    def _xy_candidate(self, style):
        """Recipe update for a native XY series. Limits stay in sync with the left axis style."""
        options = dict(self.xy["options"])
        columns = list(options.get("Y columns") or [])
        options["Series style"] = {column: self._xy_style.get(column, "Points") for column in columns}
        options["Series side"] = {column: self._xy_side.get(column, "Left") for column in columns}
        if self._has_bars():
            width = parse_bar_width(self.bar_width.get())
            if width is None:
                options.pop(BAR_WIDTH, None)
            else:
                options[BAR_WIDTH] = width
        title = self.right_title.get().strip()
        if title:
            options["Right title"] = title
        else:
            options.pop("Right title", None)
        options["Right scale"] = self.right_scale.get() or "Linear"
        low, high = self.right_min.get().strip(), self.right_max.get().strip()
        if low or high:
            options["Right minimum"] = float(low) if low else ""
            options["Right maximum"] = float(high) if high else ""
        else:
            options.pop("Right minimum", None)
            options.pop("Right maximum", None)
        y_axis = style.get("axis", {}).get("y", {})
        if "min" in y_axis and "max" in y_axis:
            options["Y minimum"] = y_axis["min"]
            options["Y maximum"] = y_axis["max"]
        else:
            options.pop("Y minimum", None)
            options.pop("Y maximum", None)
        return options

    def _prepare_xy(self, style, options):
        options = prune_options(options)
        options["Series color"] = assign_colors(options["Y columns"], options.get("Series color"))
        result = xy_series(self.xy["frame"], options, left_scale=style.get("yscale", "linear"))
        apply_style(result.figure, style)
        self.xy_update, self.xy_result = options, result

    def _check_breaks(self, style):
        """Breaks chosen in this dialog must show on the graph. Saved ones that cannot show stay, with a reason."""
        if not style.get(AXIS_BREAKS) or style[AXIS_BREAKS] == self.style.get(AXIS_BREAKS):
            return
        reason = axis_breaks_reason(self.xy_result.figure)
        if reason:
            raise _BreaksProblem(reason)

    def validate(self):
        try:
            style = self._read_style()
            if self.xy is None:
                validate_graph_style(self.axes, style)
            else:
                # Let the left axis derive its label from the series that stay on it.
                if "ylabel" not in self.style and style["ylabel"] == self.axes.get_ylabel():
                    style.pop("ylabel")
                self._prepare_xy(style, self._xy_candidate(style))
                self._check_breaks(style)
            self.result = style
        except ValueError as error:
            from .axis_breaks_dialog import translate_breaks_error
            from .axis_guides_dialog import translate_guide_error
            from .graph_legend_dialog import translate_legend_error

            self._focus_error(error)
            # Mixed XY messages (Step and Bars) first, then the legend, guide and graph catalogs.
            msg = translate_message(str(error), "xy.error.")
            if msg == str(error):
                msg = translate_legend_error(error)
            if msg == str(error):
                msg = translate_guide_error(error)
            if msg == str(error):
                msg = translate_breaks_error(error)
            messagebox.showerror(tr("graph.format.error_title"), msg, parent=self)
            return False
        return True
