"""Side panel that formats the displayed graph in place.

The panel edits a draft copy of the confirmed style. Every valid change is previewed on the live figure with
``apply_style``; the confirmed style (``run.style`` and ``Dataset.graph_styles``) changes only on Apply.
Cancel, Escape and leaving the graph restore the confirmed style. Keys that the panel does not manage
(reference lines, tick steps, fonts, ...) stay in the draft untouched.
"""
import tkinter as tk
from copy import deepcopy
from tkinter import ttk

from . import ui_theme
from .axis_guides import AXIS_BANDS, AXIS_GUIDES
from .graph_dialog import (LEGEND_LABELS, LINE_LABELS, MARKER_LABELS, SCALE_LABELS, ChoiceBinding, pick_color,
                           series_name)
from .graph_legend import LEGEND_OPTIONS_KEY
from .i18n import tr, translate_message
from .presentation import (LEGEND_LOCATIONS, LINE_STYLES, MARKERS, SCALES, active_series_fields, apply_style,
                           axis_has_numeric_ticks, capture_defaults, graph_groups, graph_series,
                           validate_graph_style, zero_baseline_axes)
from .xy_series import XY_METHOD

WIDTH = 300
AUTO = "Default"
AUTO_LABELS = {AUTO: "graph.choice.default"}
# Captions are catalog keys; the dictionary keys stay the style fields.
CAPTIONS = {key: "graph.inspector." + key
            for key in ("label", "color", "line_style", "width", "marker", "marker_size", "marker_color")}
PREVIEW_DELAY_MS = 350
ERROR = "#a02a2a"
HINT = "#506575"
TEXT_FIELDS = {"title": ("graph.field.title", 0), "xlabel": ("graph.field.xlabel", 1),
               "ylabel": ("graph.field.ylabel", 2)}
NUMBER_FIELDS = {"width", "marker_size"}
SECTION_KEYS = {"data": ("series",), "axes": ("xlabel", "ylabel", "xscale", "yscale"),
                "page": ("title", "grid", "legend", LEGEND_OPTIONS_KEY)}
QUIET_KEYS = {"Tab", "ISO_Left_Tab", "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
              "Left", "Right", "Up", "Down", "Home", "End", "Escape", "Return", "KP_Enter"}


class FieldProblem(ValueError):
    """An entry that cannot be read; the message is shown under the field."""


def _number(text, what="graph.inspector.enter_number"):
    try:
        return float(text.replace(",", ".")) if text.count(",") <= 1 else float(text)
    except ValueError as error:
        raise FieldProblem(tr(what)) from error


class GraphInspector(ttk.Frame):
    def __init__(self, parent, run, canvas, toolbar, *, confirmed, commit, closed, remember=None, element=None,
                 colors=None, qq_panels=None, hierarchical_style=None):
        """``confirmed()`` returns the saved style, ``commit(style)`` stores a validated one,
        ``closed()`` tells the owner that the user closed the panel and ``remember(key)`` keeps the selection.
        ``colors()`` opens the color and legend editor of a heat map; ``qq_panels()`` opens the Q–Q panel editor.
        ``hierarchical_style()`` opens the dendrogram and heat-map editor."""
        self._colors = colors
        self._qq_panels = qq_panels
        self._hierarchical_style = hierarchical_style
        self.width = ui_theme.px(WIDTH)
        super().__init__(parent, width=self.width, padding=0)
        self.pack_propagate(False)
        self.run, self.canvas, self.toolbar = run, canvas, toolbar
        self._xy = getattr(run, "method", None) == XY_METHOD
        self.figure = canvas.figure
        self._confirmed, self._commit, self._closed, self._remember = confirmed, commit, closed, remember
        self.figure_ok = bool(self.figure.axes)
        self.axes = self.figure.axes[0]
        capture_defaults(self.figure)
        self.defaults = self.axes._tramastat_defaults
        self.groups = graph_groups(self.axes)
        self.elements = self._elements()
        self.draft = deepcopy(self._confirmed() or {})
        self.vars, self.widgets, self.messages, self.errors, self.choices = {}, {}, {}, {}, {}
        self._due, self._after, self._busy = [], None, False
        self._element_key = element
        self._build()
        self._load()
        self._retag(self)
        self.bind("<Escape>", self._escape)
        self.bind("<FocusIn>", lambda event: self._reveal(event.widget))
        self._click = canvas.mpl_connect("button_press_event", self._clicked)

    # ----- construction -----------------------------------------------------------------------------------
    def _elements(self):
        names = [group.name for group in self.groups]
        elements = []
        for group in self.groups:
            name = group.name
            if names.count(name) > 1:
                # Same visible label, different source identity (for example the text 1 and the number 1).
                parts = group.key.split(":", 3)
                name = f"{name} ({parts[2]})" if len(parts) > 3 else f"{name} ({group.key})"
            elements.append({"kind": "group", "key": group.key, "name": name, "item": group})
        if not elements:
            elements = [{"kind": "series", "key": series.key, "name": series_name(series), "item": series}
                        for series in graph_series(self.axes)]
        return elements

    def _build(self):
        ttk.Label(self, text=tr("graph.inspector.title"), style="DialogTitle.TLabel", padding=(10, 8, 10, 2)).pack(fill="x")
        scroll = ttk.Scrollbar(self, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.scroller = tk.Canvas(self, highlightthickness=0, background=ui_theme.SURFACE, yscrollcommand=scroll.set)
        self.scroller.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.scroller.yview)
        self.body = ttk.Frame(self.scroller, padding=(8, 0, 4, 8))
        window = self.scroller.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: self.scroller.configure(scrollregion=self.scroller.bbox("all")))
        self.scroller.bind("<Configure>", lambda event: self.scroller.itemconfigure(window, width=event.width))
        self.body.columnconfigure(0, weight=1)
        if getattr(self.run.result, "style_warning", None):
            ttk.Label(self.body, text=tr("graph.inspector.review", warning=self.run.result.style_warning),
                      wraplength=self.width - 40, foreground=ERROR, justify="left").pack(fill="x", pady=(0, 6))
        if self._hierarchical_style is not None:
            self.hierarchical_button = ttk.Button(
                self.body, text=tr("hierarchy.style.button"), command=self._hierarchical_style)
            self.hierarchical_button.pack(fill="x", pady=(0, 6))
            self.widgets["hierarchical_style"] = self.hierarchical_button
        self._data_section()
        self._axes_section()
        self._page_section()
        # The footer is created last so that Tab visits the fields first, and packed first so that it keeps its space.
        footer = ttk.Frame(self, padding=(10, 6, 10, 8))
        footer.pack(side="bottom", fill="x", before=scroll)
        self.status = ttk.Label(footer, wraplength=self.width - 24, justify="left", foreground=ERROR)
        self.status.pack(side="top", fill="x", pady=(0, 4))
        self.apply_button = ttk.Button(footer, text=tr("graph.inspector.apply"), style="Action.TButton",
                                       command=self.apply)
        self.cancel_button = ttk.Button(footer, text=tr("graph.inspector.cancel"), command=self.cancel)
        self.cancel_button.pack(side="right")
        self.apply_button.pack(side="right", padx=(0, 6))
        for button in (self.apply_button, self.cancel_button):
            button.bind("<Return>", lambda event: event.widget.invoke() or "break")
        ttk.Separator(self).pack(side="bottom", fill="x", before=footer)

    def _section(self, name, title):
        frame = ttk.LabelFrame(self.body, text=title, padding=(8, 4), style="Inspector.TLabelframe")
        frame.pack(fill="x", pady=(0, 8))
        frame.columnconfigure(1, weight=1)
        self.widgets[name] = frame
        return frame

    def _finish_section(self, frame, name):
        row = frame.grid_size()[1]
        button = ttk.Button(frame, text=tr("graph.inspector.reset_section"), command=lambda: self.reset_section(name))
        button.grid(row=row, column=0, columnspan=3, sticky="e", pady=(6, 0))
        self.widgets[name + "_reset"] = button

    def _field(self, frame, source, caption, *, choices=(), width=14, check=None, pick=False, name=None, labels=None):
        """One labeled control followed by a hidden inline message. Returns the widgets of its rows.

        A combobox shows ``choices`` through ``labels`` while its variable keeps the canonical value."""
        row = frame.grid_size()[1]
        variable = self.vars[name or source] = tk.BooleanVar(self) if check else tk.StringVar(self)
        label = ttk.Label(frame, text=caption)
        if check:
            widget = ttk.Checkbutton(frame, text=check, variable=variable, style="Inspector.TCheckbutton",
                                   command=lambda: self._now(source))
            widget.grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
            label = None
        else:
            label.grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
            if choices:
                widget = ttk.Combobox(frame, state="readonly", width=width)
                self.choices[name or source] = ChoiceBinding(widget, variable, choices, labels or {})
                widget.bind("<<ComboboxSelected>>", lambda _e: self._now(source))
            else:
                widget = ttk.Entry(frame, textvariable=variable, width=width)
                widget.bind("<KeyRelease>", lambda e: self._typed(source, e))
                widget.bind("<Return>", lambda _e: self._now(source))
                widget.bind("<FocusOut>", lambda _e: self._now(source))
            widget.grid(row=row, column=1, sticky="ew", pady=2)
        button = None
        if pick:
            pick_text = tr("graph.field.pick")
            button = ttk.Button(frame, text=pick_text, width=max(6, len(pick_text)), command=lambda: self._pick(variable, source))
            button.grid(row=row, column=2, padx=(4, 0))
        message = ttk.Label(frame, wraplength=self.width - 50, foreground=ERROR, justify="left")
        message.grid(row=row + 1, column=0, columnspan=3, sticky="w")
        message.grid_remove()
        self.messages[source] = message
        return {"widget": widget, "message": message,
                "shown": [item for item in (label, widget, button) if item is not None]}

    def _data_section(self):
        frame = self._section("data", tr("graph.inspector.data"))
        self.element = tk.StringVar(self)
        ttk.Label(frame, text=tr("graph.inspector.element")).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        self.selector = ttk.Combobox(frame, textvariable=self.element, state="readonly" if self.elements else "disabled",
                                     values=[item["name"] for item in self.elements], width=18)
        self.selector.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        self.selector.bind("<<ComboboxSelected>>", lambda _e: self._select())
        self.widgets["selector"] = self.selector
        if not self.elements and self._colors is not None:
            # A heat map is one color mesh: no line or symbol controls, but its colors and legend are one click away.
            ttk.Label(frame, text=tr("graph.inspector.heat_hint"), foreground=HINT,
                      wraplength=self.width - 50, justify="left").grid(row=1, column=0, columnspan=3, sticky="w")
            self.colors_button = ttk.Button(frame, text=tr("graph.inspector.heat_colors"), command=self._colors)
            self.colors_button.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 2))
            self.widgets["colors"] = self.colors_button
        elif not self.elements:
            ttk.Label(frame, text=tr("graph.series.none"), foreground=HINT,
                      wraplength=self.width - 50, justify="left").grid(row=1, column=0, columnspan=3, sticky="w")
        elif self._xy:
            self.xy_hint_label = ttk.Label(frame, text=tr("graph.inspector.xy_hint"),
                                           foreground=HINT, wraplength=self.width - 50, justify="left")
            self.xy_hint_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.fields = {}
        for key, caption in CAPTIONS.items():
            choices = (AUTO, *LINE_STYLES) if key == "line_style" else (AUTO, *MARKERS) if key == "marker" else ()
            labels = {**AUTO_LABELS, **(LINE_LABELS if key == "line_style" else MARKER_LABELS)}
            self.fields[key] = self._field(frame, "element:" + key, tr(caption), choices=choices, labels=labels,
                                           pick=key in {"color", "marker_color"}, name="element:" + key)
        self.fields["visible"] = self._field(frame, "element:visible", "", check=tr("graph.inspector.show"),
                                             name="element:visible")
        ttk.Label(frame, text=tr("graph.inspector.blank_hint"), foreground=HINT, wraplength=self.width - 50,
                  justify="left").grid(row=frame.grid_size()[1], column=0, columnspan=3, sticky="w")
        self._finish_section(frame, "data")

    def _axes_section(self):
        frame = self._section("axes", tr("graph.inspector.axes"))
        for key, (caption, _) in tuple(TEXT_FIELDS.items())[1:]:
            self._field(frame, key, tr(caption))
        for dimension in ("x", "y"):
            numeric = axis_has_numeric_ticks(self.axes, dimension)
            zero = dimension in zero_baseline_axes(self.axes)
            scale = self._field(frame, dimension + "scale", tr("graph.inspector.scale", axis=dimension.upper()),
                                width=10, choices=("linear",) if zero else SCALES, name=dimension + "scale",
                                labels=SCALE_LABELS)
            self.widgets[dimension + "scale"] = scale["widget"]
            row = frame.grid_size()[1]
            ttk.Label(frame, text=tr("graph.inspector.range", axis=dimension.upper())).grid(row=row, column=0, sticky="w", pady=2)
            pair = ttk.Frame(frame)
            pair.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)
            pair.columnconfigure((0, 1), weight=1, uniform="range")
            source = dimension + "range"
            for column, bound in enumerate(("min", "max")):
                variable = self.vars[f"{dimension}{bound}"] = tk.StringVar(self)
                entry = ttk.Entry(pair, textvariable=variable, width=7)
                entry.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0))
                entry.bind("<KeyRelease>", lambda e, source=source: self._typed(source, e))
                entry.bind("<Return>", lambda _e, source=source: self._now(source))
                entry.bind("<FocusOut>", lambda _e, source=source: self._now(source))
                self.widgets[f"{dimension}{bound}"] = entry
            message = ttk.Label(frame, wraplength=self.width - 50, foreground=ERROR, justify="left")
            message.grid(row=row + 1, column=0, columnspan=3, sticky="w")
            message.grid_remove()
            self.messages[source] = message
            hint = tr("graph.inspector.automatic" if numeric else "graph.inspector.categorical")
            ttk.Label(frame, text=hint, foreground=HINT, wraplength=self.width - 50, justify="left").grid(row=row + 2, column=0, columnspan=3, sticky="w")
        if self._qq_panels is not None:
            row = frame.grid_size()[1]
            self.qq_panels_button = ttk.Button(frame, text=tr("qq.panels.button"), command=self._qq_panels)
            self.qq_panels_button.grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 2))
            self.widgets["qq_panels"] = self.qq_panels_button
        row = frame.grid_size()[1]
        self.axis_guides_button = ttk.Button(frame, text=tr("graph.guides.button"), command=self._edit_axis_guides)
        self.axis_guides_button.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(6, 2))
        self.widgets["axis_guides"] = self.axis_guides_button
        self.axis_bands_button = ttk.Button(frame, text=tr("graph.bands.button"), command=self._edit_axis_bands)
        self.axis_bands_button.grid(row=row + 1, column=0, columnspan=3, sticky="ew", pady=(0, 2))
        self.widgets["axis_bands"] = self.axis_bands_button
        self._finish_section(frame, "axes")

    def _page_section(self):
        frame = self._section("page", tr("graph.inspector.page"))
        self._field(frame, "title", tr("graph.field.title"))
        self._field(frame, "legend", tr("graph.inspector.legend"), choices=(AUTO, *LEGEND_LOCATIONS), width=12,
                    labels={**AUTO_LABELS, **LEGEND_LABELS})
        row = frame.grid_size()[1]
        self.legend_options_button = ttk.Button(frame, text=tr("legend_editor.button"), command=self._edit_legend_options)
        self.legend_options_button.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(4, 2))
        self.widgets["legend_options"] = self.legend_options_button
        self._field(frame, "grid", "", check=tr("graph.field.major_grid"))
        self._finish_section(frame, "page")

    def _retag(self, widget):
        """Let Escape, the mouse wheel and the other panel shortcuts reach every control."""
        widget.bindtags((str(self), *widget.bindtags()))
        for child in widget.winfo_children():
            self._retag(child)
        if widget is self:
            self.bind_class(str(self), "<MouseWheel>", self._wheel)
            self.bind_class(str(self), "<Button-4>", lambda e: self.scroller.yview_scroll(-1, "units"))
            self.bind_class(str(self), "<Button-5>", lambda e: self.scroller.yview_scroll(1, "units"))

    def _reveal(self, widget):
        """Scroll the panel so that a focused or flagged control is visible."""
        try:
            if not str(widget).startswith(str(self.body)):
                return
            self.update_idletasks()
            top = widget.winfo_rooty() - self.body.winfo_rooty()
            bottom = top + widget.winfo_height()
            shown_top = self.scroller.canvasy(0)
            shown_bottom = shown_top + self.scroller.winfo_height()
            if top < shown_top or bottom > shown_bottom:
                self.scroller.yview_moveto(max(0, (top - 24) / max(1, self.body.winfo_height())))
        except tk.TclError:
            pass

    def _wheel(self, event):
        self.scroller.yview_scroll(-1 if event.delta > 0 else 1, "units")

    # ----- reading and writing widgets --------------------------------------------------------------------
    @property
    def current(self):
        index = self.selector.current()
        return self.elements[index] if 0 <= index < len(self.elements) else None

    def _load(self):
        """Fill every widget from the draft; automatic values come from the analysis defaults."""
        texts = {key: self.defaults["texts"][index][1] for key, (_, index) in TEXT_FIELDS.items()}
        for key in TEXT_FIELDS:
            self.vars[key].set(self.draft.get(key, texts[key]))
        for dimension in ("x", "y"):
            baseline = self.defaults["axes"][dimension]["scale"]
            options = self.draft.get("axis", {}).get(dimension, {})
            self.vars[dimension + "scale"].set(self.draft.get(dimension + "scale", baseline))
            for bound in ("min", "max"):
                self.vars[f"{dimension}{bound}"].set("" if bound not in options else f"{options[bound]:g}")
        self.vars["legend"].set(self.draft.get("legend", AUTO))
        default_grid = any(self.defaults["axes"][d]["major_params"].get("gridOn", False) for d in "xy")
        self.vars["grid"].set(self.draft.get("grid", default_grid))
        if self.elements:
            keys = [item["key"] for item in self.elements]
            self.selector.current(keys.index(self._element_key) if self._element_key in keys else 0)
        self._load_element()
        self._refresh_states()

    def _load_element(self):
        item = self.current
        self._element_key = item["key"] if item else None
        if item and self._remember:
            self._remember(item["key"])
        options = self._style_options(self.draft, item) if item else {}
        series = bool(item) and item["kind"] == "series"
        allowed = item["item"].fields if series else {"color", "visible"}
        for key, field in self.fields.items():
            for widget in field["shown"]:
                widget.grid() if item and key in allowed else widget.grid_remove()
            variable = self.vars["element:" + key]
            if key == "visible":
                variable.set(options.get("visible", True))
                if item and not series:
                    field["widget"].configure(text=tr("graph.inspector.show_kind." + item["item"].kind))
            elif key == "marker":
                markers = {label: code for label, code in MARKERS.items()
                           if code != "none" or (item and item["item"].kind in {"line", "errorbar", "xy"})}
                self.choices["element:marker"].set_values((AUTO, *markers))
                variable.set(next((label for label, code in markers.items() if code == options.get("marker")), AUTO))
            elif key == "line_style":
                variable.set(options.get(key, AUTO))
            else:
                variable.set(options.get(key, ""))
        for source in [source for source in self.errors if source.startswith("element:")]:
            self._flag(source, None)

    @staticmethod
    def _style_options(style, item):
        bucket = "groups" if item["kind"] == "group" else "series"
        return style.get(bucket, {}).get(item["key"], {})

    def _refresh_states(self):
        for control in self._controls(self):
            control.state(["disabled" if self._busy else "!disabled"])
        if self._busy:
            return
        for dimension in ("x", "y"):
            numeric = axis_has_numeric_ticks(self.axes, dimension)
            zero = dimension in zero_baseline_axes(self.axes)
            for name in (dimension + "min", dimension + "max"):
                self.widgets[name].state(["!disabled" if numeric else "disabled"])
            adjustable = numeric and not zero and not (self._xy and dimension == "y")
            self.widgets[dimension + "scale"].state(["!disabled" if adjustable else "disabled"])
        item = self.current
        if item and item["kind"] == "series":
            series = item["item"]
            active_fields = active_series_fields(self.axes, series)
            for key, field in self.fields.items():
                if key in series.fields:
                    enabled = key in active_fields
                    for control in field["shown"]:
                        if isinstance(control, (ttk.Entry, ttk.Combobox, ttk.Button, ttk.Checkbutton)):
                            control.state(["!disabled" if enabled else "disabled"])
            if self._xy and hasattr(self, "xy_hint_label"):
                key_name = "graph.inspector.xy_inactive" if active_fields != series.fields else "graph.inspector.xy_hint"
                self.xy_hint_label.configure(text=tr(key_name))
        if not self.elements:
            self.selector.state(["disabled"])

    def _controls(self, widget):
        found = []
        for child in widget.winfo_children():
            if isinstance(child, (ttk.Entry, ttk.Combobox, ttk.Checkbutton, ttk.Button)):
                found.append(child)
            found.extend(self._controls(child))
        return found

    def set_busy(self, reason=None):
        """Disable the controls while an analysis runs; the draft and the preview stay as they are."""
        self._busy = bool(reason)
        self._refresh_states()
        self.status.configure(text=reason or "", foreground=HINT)

    # ----- updating the draft ------------------------------------------------------------------------------
    def _typed(self, source, event):
        if event.keysym not in QUIET_KEYS:
            self._schedule(source)

    def _schedule(self, source):
        if source not in self._due:
            self._due.append(source)
        if self._after is not None:
            self.after_cancel(self._after)
        self._after = self.after(PREVIEW_DELAY_MS, self._flush)

    def _cancel_schedule(self):
        if self._after is not None:
            self.after_cancel(self._after)
        self._after, self._due = None, []

    def _flush(self):
        due = self._due
        self._cancel_schedule()
        for source in due:
            self._update(source)

    def _now(self, source):
        if source in self._due:
            self._due.remove(source)
        if not self._due and self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        self._update(source)

    def _update(self, source):
        if self._busy or not self.winfo_exists():
            return
        candidate = deepcopy(self.draft)
        try:
            self._write(candidate, source)
            validate_graph_style(self.axes, candidate)
        except ValueError as error:
            from .axis_guides_dialog import translate_guide_error

            self._flag(source, translate_guide_error(error))
            return
        self._flag(source, None)
        if candidate != self.draft:
            self._preview(candidate)

    def _preview(self, candidate):
        previous = self.draft
        try:
            apply_style(self.figure, candidate)
        except ValueError as error:
            from .axis_guides_dialog import translate_guide_error
            from .graph_legend_dialog import translate_legend_error

            apply_style(self.figure, previous)
            self.canvas.draw_idle()
            msg = translate_legend_error(error)
            if msg == str(error):
                msg = translate_guide_error(error)
            self.status.configure(text=msg, foreground=ERROR)
            return False
        self.draft = candidate
        self.status.configure(text="")
        self.canvas.draw_idle()
        return True

    def _flag(self, source, message):
        label = self.messages.get(source)
        if message:
            self.errors[source] = message
            label.configure(text=message)
            label.grid()
        else:
            self.errors.pop(source, None)
            if label is not None:
                label.grid_remove()

    def _write(self, style, source):
        """Copy one source field into ``style``. A blank or automatic value removes its key."""
        if source in TEXT_FIELDS:
            default = self.defaults["texts"][TEXT_FIELDS[source][1]][1]
            value = self.vars[source].get()
            if value == default:
                style.pop(source, None)
            else:
                style[source] = value
        elif source in {"xrange", "yrange", "xscale", "yscale"}:
            self._write_axis(style, source[0], source[1:])
        elif source == "legend":
            value = self.vars["legend"].get()
            style.pop("legend", None) if value == AUTO else style.__setitem__("legend", value)
        elif source == "grid":
            style["grid"] = bool(self.vars["grid"].get())
        elif source.startswith("element:"):
            self._write_element(style, source[8:])

    def _write_axis(self, style, dimension, part):
        if part == "scale":
            scale = self.vars[dimension + "scale"].get()
            if scale == self.defaults["axes"][dimension]["scale"]:
                style.pop(dimension + "scale", None)
            else:
                style[dimension + "scale"] = scale
            return
        low, high = (self.vars[f"{dimension}{bound}"].get().strip() for bound in ("min", "max"))
        if bool(low) != bool(high):
            raise FieldProblem(tr("graph.inspector.both_limits"))
        options = style.setdefault("axis", {}).setdefault(dimension, {})
        if low:
            options["min"], options["max"] = (_number(low, "graph.inspector.enter_minimum"),
                                               _number(high, "graph.inspector.enter_maximum"))
        else:
            options.pop("min", None)
            options.pop("max", None)
        self._tidy_axis(style)

    @staticmethod
    def _tidy_axis(style):
        axis = style.get("axis", {})
        for dimension in [key for key, options in axis.items() if not options]:
            del axis[dimension]
        if not axis:
            style.pop("axis", None)

    def _write_element(self, style, field):
        item = self.current
        if item is None:
            return
        bucket = "groups" if item["kind"] == "group" else "series"
        options = style.setdefault(bucket, {}).setdefault(item["key"], {})
        variable = self.vars["element:" + field]
        if field == "visible":
            if variable.get():
                options.pop("visible", None)
            else:
                options["visible"] = False
        else:
            value = variable.get().strip()
            if not value or (field in {"marker", "line_style"} and value == AUTO):
                options.pop(field, None)
            elif field == "marker":
                options[field] = MARKERS[value]
            elif field == "line_style":
                options[field] = value
            elif field in NUMBER_FIELDS:
                options[field] = _number(value, "graph.inspector.enter_size")
            else:
                options[field] = value
        if not options:
            del style[bucket][item["key"]]
        if not style[bucket]:
            del style[bucket]

    def _pick(self, variable, source):
        pick_color(self, variable)
        self._now(source)

    def _edit_axis_guides(self):
        from .axis_guides_dialog import AxisGuidesDialog

        self._edit_guide_collection(AXIS_GUIDES, AxisGuidesDialog)

    def _edit_axis_bands(self):
        from .axis_guides_dialog import AxisBandsDialog

        self._edit_guide_collection(AXIS_BANDS, AxisBandsDialog)

    def _edit_legend_options(self):
        from .graph_legend_dialog import LegendEditorDialog

        if self._busy:
            return
        self._flush()
        base_draft = deepcopy(self.draft)

        def build_candidate(options):
            candidate = deepcopy(base_draft)
            if options:
                candidate[LEGEND_OPTIONS_KEY] = deepcopy(options)
            else:
                candidate.pop(LEGEND_OPTIONS_KEY, None)
            return candidate

        def preview(options):
            if options is None:
                apply_style(self.figure, base_draft)
                self.canvas.draw_idle()
                return
            candidate = build_candidate(options)
            try:
                validate_graph_style(self.axes, candidate)
                apply_style(self.figure, candidate)
            except ValueError:
                apply_style(self.figure, base_draft)
                self.canvas.draw_idle()
                raise
            self.canvas.draw_idle()

        dialog = LegendEditorDialog(
            self,
            self.figure,
            base_draft.get(LEGEND_OPTIONS_KEY, {}),
            preview=preview,
            busy=lambda: self._busy,
        )
        if dialog.result is not None:
            candidate = build_candidate(dialog.result)
            if candidate != self.draft:
                self._preview(candidate)
            else:
                self.canvas.draw_idle()

    def _edit_guide_collection(self, key, dialog_cls):
        if self._busy:
            return
        self._flush()
        base_draft = deepcopy(self.draft)

        def build_candidate(records):
            candidate = deepcopy(base_draft)
            if records:
                candidate[key] = deepcopy(records)
            else:
                candidate.pop(key, None)
            return candidate

        def preview(records):
            if records is None:
                apply_style(self.figure, base_draft)
                self.canvas.draw_idle()
                return
            candidate = build_candidate(records)
            try:
                validate_graph_style(self.axes, candidate)
                apply_style(self.figure, candidate)
            except ValueError:
                apply_style(self.figure, base_draft)
                self.canvas.draw_idle()
                raise
            self.canvas.draw_idle()

        dialog = dialog_cls(
            self,
            self.axes,
            base_draft.get(key, []),
            preview=preview,
            busy=lambda: self._busy,
        )
        if dialog.result is not None:
            candidate = build_candidate(dialog.result)
            if candidate != self.draft:
                self._preview(candidate)

    def _select(self):
        self._load_element()
        self._refresh_states()

    def select_group(self, key):
        """Select a group or series by key, as when the figure is clicked."""
        keys = [item["key"] for item in self.elements]
        if key in keys:
            self.selector.current(keys.index(key))
            self._select()
            return True
        return False

    def _clicked(self, event):
        if (self._busy or event.button != 1 or event.inaxes is not self.axes or not self.groups
                or (self.toolbar is not None and str(getattr(self.toolbar, "mode", "")))):
            return
        for group in reversed(self.groups):
            if any(artist.get_visible() and artist.contains(event)[0] for artist, _ in group.artists):
                self.select_group(group.key)
                return

    # ----- section reset, apply, cancel --------------------------------------------------------------------
    def reset_section(self, name):
        """Remove only the settings that belong to one section from the draft; automatic values return."""
        candidate = deepcopy(self.draft)
        keys = ("groups",) if name == "data" and self.groups else SECTION_KEYS[name]
        for key in keys:
            if key != "yscale" or not self._xy:
                candidate.pop(key, None)
        if name == "axes":
            for options in candidate.get("axis", {}).values():
                options.pop("min", None)
                options.pop("max", None)
            self._tidy_axis(candidate)
        self._cancel_schedule()
        prefixes = {"data": ("element:",), "axes": ("x", "y"), "page": ("title", "legend", "grid")}[name]
        for source in [source for source in self.errors if source.startswith(prefixes)]:
            self._flag(source, None)
        if candidate != self.draft:
            if not self._preview(candidate):
                return
        self._load()

    @property
    def has_draft(self):
        return bool(self._due or self.errors) or self.draft != (self._confirmed() or {})

    def apply(self):
        """Validate the draft and hand it to the owner. Returns False and keeps the panel open on a problem."""
        if self._busy:
            return False
        self._flush()
        if self.errors:
            self.status.configure(text=tr("graph.inspector.fix_fields"), foreground=ERROR)
            self._reveal(self.messages[next(iter(self.errors))])
            return False
        try:
            validate_graph_style(self.axes, self.draft)
            apply_style(self.figure, self.draft)
        except ValueError as error:
            from .axis_guides_dialog import translate_guide_error
            from .graph_legend_dialog import translate_legend_error

            msg = translate_legend_error(error)
            if msg == str(error):
                msg = translate_guide_error(error)
            self.status.configure(text=msg, foreground=ERROR)
            return False
        try:
            self._commit(deepcopy(self.draft))
        except ValueError as error:
            from .axis_guides_dialog import translate_guide_error
            from .graph_legend_dialog import translate_legend_error

            msg = translate_legend_error(error)
            if msg == str(error):
                msg = translate_guide_error(error)
            self.status.configure(text=msg, foreground=ERROR)
            return False
        self.status.configure(text=tr("graph.inspector.applied"), foreground=HINT)
        self.canvas.draw_idle()
        return True

    def discard(self):
        """Restore the confirmed style on the figure and in the panel without closing it."""
        self._cancel_schedule()
        confirmed = deepcopy(self._confirmed() or {})
        for source in list(self.errors):
            self._flag(source, None)
        self.draft = confirmed
        try:
            apply_style(self.figure, confirmed)
        except ValueError:
            pass
        self.canvas.draw_idle()
        self._load()
        self.status.configure(text="")

    def cancel(self, _event=None):
        self.discard()
        self._closed()

    def _escape(self, _event):
        self.cancel()
        return "break"

    def dispose(self):
        """Called when the page is rebuilt: restore the confirmed style and release the figure."""
        self._cancel_schedule()
        try:
            self.canvas.mpl_disconnect(self._click)
        except (AttributeError, ValueError):
            pass
        if self.figure.axes:
            try:
                apply_style(self.figure, deepcopy(self._confirmed() or {}))
            except ValueError:
                pass
