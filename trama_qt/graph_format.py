"""Format Graph on Qt: title, labels, fonts, axes, series and reference lines.

The dialog edits the same style dictionary as the classic one (``analisi.graph_dialog``) and validates
it with the engine, legend formatting, axis guides, bands and breaks included. Annotations and shapes have
their own dialogs, as do dendrograms and clustered heat maps. Q–Q panel settings are preserved.
"""
from copy import deepcopy

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from PySide6.QtCore import QLocale, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget)

from analisi.axis_breaks import AXIS_BREAKS, SUPPORT_ATTR, axis_breaks_reason
from analisi.axis_guides import AXIS_BANDS, AXIS_GUIDES
from analisi.category_graphs import (AS_GRAPH, BAR_BASELINE, BAR_DIRECTION, BAR_DIRECTIONS,
                                     BAR_SPACING_DEFAULTS, BAR_SPACING_MAXIMUMS, BOTH_INTERVALS,
                                     GROUPED_BAR_SPACING, GROUPED_SERIES_COMPATIBLE_STYLES, HORIZONTAL_BARS,
                                     INTERVAL_DIRECTIONS, VERTICAL_BARS,
                                     LOWER_INTERVAL, RELATIVE_PLACEMENTS, SERIES_DRAW_STYLES, SERIES_INTERVAL_DIRECTION,
                                     SERIES_PLACEMENT, SERIES_STYLE, STACK_PREVIOUS, UPPER_INTERVAL,
                                     STACKED_PLACEMENTS, BARS as GROUPED_BARS,
                                     LINE_SYMBOLS as GROUPED_LINE_SYMBOLS, SYMBOLS as GROUPED_SYMBOLS,
                                     category_graph, grouped_series_names, prune_series_styles, series_interval_directions,
                                     series_placements, transpose_grouped_bar_style)
from analisi.field_error import FieldError
from analisi.graph_annotations import ANNOTATIONS
from analisi.grouped_series_catalog import translate_grouped_error
from analisi.linked_tables import TABLES
from analisi.graph_legend import LEGEND_OPTIONS_KEY
from analisi.graph_shapes import SHAPES
from analisi.observation_labels import LABELS
from analisi.point_style import POINTS
from analisi.hierarchical_style import describe_hierarchical_artists
from analisi.linked_axes import LINKED_AXES, linked_axes_reasons
from analisi.i18n import active_language, tr, translate_message
from analisi.presentation import (FONT_FAMILIES, GROUPED_PREFIX, INTERVAL_STYLE_FIELDS, LEGEND_LOCATIONS, LINE_STYLES, MARKERS, SCALES,
                                  active_series_fields, apply_style, axis_has_numeric_ticks, graph_series,
                                  validate_graph_style, zero_baseline_axes)
from analisi.probability_scale import FRACTION_SCALE, PERCENT_SCALE, PROBABILITY_SCALES
from analisi.qq_panels import PANEL_KEY
from analisi.series_layers import XY_SERIES_ORDER
from analisi.xy_series import (BAR_WIDTH, BARS, DRAW_STYLES, RECIPE_KEYS, SCALES as XY_SCALES, SIDES, STEP,
                               assign_colors, parse_bar_width, prune_options, xy_series)

from .graph_axis_click import right_y_axes
from .theme import fit_dialog

# Captions are catalog keys shared with the classic dialog (analisi/graph_dialog.py, which needs Tk).
AXIS_FIELDS = {"min": "graph.axis.min", "max": "graph.axis.max", "step": "graph.axis.step",
               "start": "graph.axis.start", "minor": "graph.axis.minor", "decimals": "graph.axis.decimals"}
FONT_FIELDS = {"title_size": "graph.field.font_title", "label_size": "graph.field.font_labels",
               "tick_size": "graph.field.font_ticks", "legend_size": "graph.field.font_legend"}
SERIES_LABELS = {key: "graph.series." + key
                 for key in ("label", "color", "line_style", "width", "marker", "marker_size", "marker_color",
                             "interval_color", "interval_width", "interval_caps")}
SERIES_COLOR_FIELDS = {"color", "marker_color", "interval_color"}
SERIES_NUMBER_FIELDS = {"width", "marker_size", "interval_width", "interval_caps"}
DEFAULT = "Analysis default"
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
               STEP: "graph.draw.step", BARS: "graph.draw.bars"}
GROUPED_DRAW_LABELS = {
    AS_GRAPH: "grouped.draw.as_graph",
    GROUPED_BARS: "grouped.draw.bars",
    GROUPED_SYMBOLS: "grouped.draw.symbols",
    GROUPED_LINE_SYMBOLS: "grouped.draw.line_symbols",
}
GROUPED_PLACEMENT_LABELS = {
    AS_GRAPH: "grouped.draw.as_graph",
    **{mode: f"grouped.placement.{key}"
       for mode, key in zip(RELATIVE_PLACEMENTS, ("beside", "overlay", "stack", "gap"), strict=True)},
}
GROUPED_INTERVAL_LABELS = {
    AS_GRAPH: "grouped.draw.as_graph",
    BOTH_INTERVALS: "grouped.interval.both",
    UPPER_INTERVAL: "grouped.interval.upper",
    LOWER_INTERVAL: "grouped.interval.lower",
}
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


# Kept as they are: edited by their own dialogs (annotations, shapes) or not editable on Qt yet.
KEPT = ("groups", ANNOTATIONS, SHAPES, PANEL_KEY, "hierarchical", POINTS, LABELS, TABLES, XY_SERIES_ORDER)


class Choice(QComboBox):
    """A combobox that shows translated captions and returns the canonical value."""

    def __init__(self, values, labels, value=None):
        super().__init__()
        self.set_values(values, labels)
        self.set(value)

    def set_values(self, values, labels):
        current = self.value() if self.count() else None
        self.blockSignals(True)
        self.clear()
        for value in values:
            self.addItem(choice_text(labels, value), value)
        self.blockSignals(False)
        if current is not None:
            self.set(current)

    def set(self, value):
        index = self.findData(value)
        self.setCurrentIndex(index if index >= 0 else 0)

    def value(self):
        return self.currentData()


def _color_button(field):
    button = QPushButton(tr("graph.field.pick"))

    def pick():
        try:
            initial = QColor(to_hex(field.text().strip() or "#2866ae", keep_alpha=False))
        except ValueError:
            initial = QColor("#2866ae")
        color = QColorDialog.getColor(initial, field.window())
        if color.isValid():
            field.setText(color.name())

    button.clicked.connect(pick)
    return button


class GraphFormatDialog(QDialog):
    """Returns ``result`` (the new style); for XY / Grouped also ``*_update`` and ``*_result``."""

    def __init__(self, parent, axes, style, *, xy=None, grouped=None, initial_axis=None):
        super().__init__(parent)
        self.setWindowTitle(tr("graph.format.title"))
        self.axes, self.style, self.xy, self.grouped = axes, deepcopy(style), xy, grouped
        self.result = self.xy_update = self.xy_result = None
        self.grouped_update = self.grouped_result = None
        self.series = graph_series(axes)
        self.series_values = deepcopy(style.get("series", {}))
        options = (xy or {}).get("options") or {}
        self.xy_style = dict(options.get("Series style") or {})
        self.xy_side = dict(options.get("Series side") or {})
        grouped_meta = getattr(axes, "_tramastat_grouped", None) or getattr(axes, "_tramastat_grouped_context", None)
        grouped_options = (grouped or {}).get("options") or {}
        self.grouped_meta = grouped_meta
        self._grouped_present = self.grouped is not None or grouped_meta is not None
        self._grouped_layout = grouped_options.get("Placement of groups") or (grouped_meta or {}).get("layout")
        self._grouped_global_style = (
            grouped_options.get("Graph style")
            or (grouped_meta or {}).get("global_style")
            or (GROUPED_BARS if self._grouped_present else None)
        )
        self._grouped_stacked = self._grouped_layout in STACKED_PLACEMENTS
        self._grouped_incompatible_style = (
            self._grouped_present
            and not self._grouped_stacked
            and self._grouped_global_style not in GROUPED_SERIES_COMPATIBLE_STYLES
        )
        self._grouped_editable = (
            self.grouped is not None
            and not self._grouped_stacked
            and not self._grouped_incompatible_style
        )
        self.grouped_style_map = dict(grouped_options.get(SERIES_STYLE) or {})
        self.grouped_placement_map = dict(grouped_options.get(SERIES_PLACEMENT) or {})
        self.grouped_interval_map = dict(grouped_options.get(SERIES_INTERVAL_DIRECTION) or {})
        self._grouped_has_intervals = any(
            grouped_options.get(key) not in (None, "None") for key in ("Interval", "Summary error")
        )
        self.series_index = -1
        self.axis_breaks = deepcopy(style.get(AXIS_BREAKS) or {})
        self.linked_axes = deepcopy(style.get(LINKED_AXES) or {})

        outer = QVBoxLayout(self)
        self.banner = QLabel()
        self.banner.setObjectName("errorBanner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        outer.addWidget(self.banner)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self._appearance()
        self._axes()
        self._series()
        self._references()
        self.spacing_controls = {}
        self.spacing_enabled = None
        self.bar_direction = None
        self.bar_baseline = None
        if self.grouped is not None and self._grouped_global_style == GROUPED_BARS:
            self._bar_arrangement(grouped_options)
        if self.preview_canvas is not None:
            self._update_grouped_preview()
        buttons = QDialogButtonBox()
        buttons.addButton(tr("graph.format.reset"), QDialogButtonBox.ButtonRole.ResetRole).clicked.connect(self.reset)
        if self.grouped is not None:
            self.preview_button = buttons.addButton(tr("graph.format.preview"), QDialogButtonBox.ButtonRole.ActionRole)
            self.preview_button.setObjectName("formatPreviewButton")
            self.preview_button.setToolTip(tr("graph.format.preview_hint"))
            self.preview_button.clicked.connect(self.preview)
        apply_button = buttons.addButton(tr("graph.format.apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(tr("graph.format.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        apply_button.setAutoDefault(True)
        apply_button.setDefault(True)
        fit_dialog(self, 920 if self.grouped is not None else 620, 560)
        if hasattr(parent, "show_shortcuts"):
            QShortcut(QKeySequence("F1"), self, parent.show_shortcuts)
        if initial_axis == "right" and self.right is not None:
            field = self.right["min"]
            self._focus(1, field)
            # Scroll after the dialog has laid out the axes page at its on-screen size.
            QTimer.singleShot(0, self, lambda: self.tabs.widget(1).ensureWidgetVisible(field))
        elif initial_axis and self.axis_breaks.get("axis") == initial_axis and self.breaks_button is not None:
            self._focus(1, self.breaks_button)
            QTimer.singleShot(0, self, lambda: self.tabs.widget(1).ensureWidgetVisible(self.breaks_button))
        elif initial_axis in self.axis_fields:
            field = self.axis_fields[initial_axis]["min"]
            if field.isEnabled():
                self._focus(1, field)
            else:
                self._focus(0, self.texts[f"{initial_axis}label"])

    # -- tabs ----------------------------------------------------------------------------------------
    def _tab(self, title):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        return page

    def _appearance(self):
        page = self._tab(tr("graph.format.appearance"))
        form = QFormLayout(page)
        self.texts = {}
        for key, caption, value in (("title", "graph.field.title", self.axes.get_title()),
                                    ("xlabel", "graph.field.xlabel", self.axes.get_xlabel()),
                                    ("ylabel", "graph.field.ylabel", self.axes.get_ylabel())):
            self.texts[key] = QLineEdit(str(self.style.get(key, value)))
            self.texts[key].setAccessibleName(tr(caption))
            form.addRow(tr(caption), self.texts[key])
        self.choices = {}
        for key, caption, values, labels in (
                ("font_family", "graph.field.font_family", FONT_FAMILIES, {}),
                ("legend", "graph.field.legend_position", LEGEND_LOCATIONS, LEGEND_LABELS),
                ("frame", "graph.field.frame", ("open", "box"), FRAME_LABELS)):
            self.choices[key] = Choice((DEFAULT, *values), {**DEFAULT_LABELS, **labels}, self.style.get(key, DEFAULT))
            form.addRow(tr(caption), self.choices[key])
        grids = QHBoxLayout()
        self.grid = QCheckBox(tr("graph.field.major_grid"))
        self.grid.setChecked(bool(self.style.get("grid", any(
            line.get_visible() for line in self.axes.get_xgridlines() + self.axes.get_ygridlines()))))
        self.grid_minor = QCheckBox(tr("graph.field.minor_grid"))
        self.grid_minor.setChecked(bool(self.style.get("grid_minor", False)))
        grids.addWidget(self.grid)
        grids.addWidget(self.grid_minor)
        grids.addStretch(1)
        form.addRow("", grids)
        fonts = QGroupBox(tr("graph.field.font_sizes"))
        grid = QGridLayout(fonts)
        self.fonts = {}
        for column, (key, caption) in enumerate(FONT_FIELDS.items()):
            grid.addWidget(QLabel(tr(caption)), 0, column)
            field = self.fonts[key] = QLineEdit("" if key not in self.style else str(self.style[key]))
            field.setMaximumWidth(90)
            grid.addWidget(field, 1, column)
        hint = QLabel(tr("graph.field.font_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        grid.addWidget(hint, 2, 0, 1, len(FONT_FIELDS))
        form.addRow(fonts)
        self.accent = None
        if "accent" in self.style:
            self.accent = QLineEdit(to_hex(self.style["accent"], keep_alpha=True))
            row = QHBoxLayout()
            row.addWidget(self.accent, 1)
            row.addWidget(_color_button(self.accent))
            form.addRow(tr("graph.field.accent"), row)
        self.legend_options = deepcopy(self.style.get(LEGEND_OPTIONS_KEY) or {})
        row = QHBoxLayout()
        button = QPushButton(tr("legend_editor.button"))
        button.clicked.connect(self.edit_legend)
        row.addWidget(button)
        self.legend_summary = QLabel()
        self.legend_summary.setObjectName("muted")
        row.addWidget(self.legend_summary, 1)
        form.addRow("", row)
        self._legend_summary()
        if describe_hierarchical_artists(self.axes.figure):
            button = QPushButton(tr("hierarchy.style.button"))
            button.clicked.connect(self.edit_hierarchical)
            form.addRow("", button)

    def _legend_summary(self):
        from .legend import legend_summary

        self.legend_summary.setText(legend_summary(self.legend_options))

    def edit_legend(self):
        from .legend import LegendEditor

        dialog = LegendEditor(self, self.axes.figure, self.legend_options)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.legend_options = dialog.result
            self._legend_summary()

    def edit_hierarchical(self):
        from .hierarchical_style import HierarchicalStyleDialog

        dialog = HierarchicalStyleDialog(self, self.axes.figure, self.style.get("hierarchical"))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.result:
                self.style["hierarchical"] = dialog.result
            else:
                self.style.pop("hierarchical", None)

    def _axes(self):
        page = self._tab(tr("graph.format.axes"))
        layout = QVBoxLayout(page)
        blocks = QHBoxLayout()
        layout.addLayout(blocks)
        self.scales, self.axis_fields, self.numeric, self.scale_enabled = {}, {}, {}, {}
        for dimension in ("x", "y"):
            axis = getattr(self.axes, dimension + "axis")
            options = self.style.get("axis", {}).get(dimension, {})
            box = QGroupBox(tr("graph.axis.block", axis=dimension.upper()))
            form = QFormLayout(box)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            zero = dimension in zero_baseline_axes(self.axes)
            scale = Choice(("linear",) if zero else SCALES, SCALE_LABELS,
                           self.style.get(dimension + "scale", axis.get_scale()))
            self.scales[dimension] = scale
            numeric = self.numeric[dimension] = axis_has_numeric_ticks(self.axes, dimension)
            self.scale_enabled[dimension] = numeric and not (zero and scale.value() == "linear")
            form.addRow(tr("graph.axis.scale"), scale)
            fields = self.axis_fields[dimension] = {}
            for key, caption in AXIS_FIELDS.items():
                fields[key] = QLineEdit("" if key not in options else str(options[key]))
                fields[key].setAccessibleName(f"{box.title()}: {tr(caption)}")
                form.addRow(tr(caption), fields[key])
            if not numeric:
                note = QLabel(tr("graph.axis.categorical"))
                note.setObjectName("muted")
                note.setWordWrap(True)
                form.addRow(note)
            scale.currentIndexChanged.connect(lambda _=0, dimension=dimension: self._axis_states(dimension))
            self._axis_states(dimension)
            blocks.addWidget(box)
        hint = QLabel(tr("graph.axis.hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.right = None
        if self.xy is not None:
            options = self.xy.get("options") or {}
            twin = right_y_axes(self.axes)
            box = QGroupBox(tr("graph.axis.right"))
            form = QFormLayout(box)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            self.right = {
                "title": QLineEdit(options.get("Right title") or (twin.get_ylabel() if twin else "")),
                "scale": Choice(XY_SCALES, RIGHT_SCALE_LABELS, options.get("Right scale") or "Linear"),
                "min": QLineEdit("" if options.get("Right minimum") in (None, "") else str(options["Right minimum"])),
                "max": QLineEdit("" if options.get("Right maximum") in (None, "") else str(options["Right maximum"])),
            }
            for key, caption in (("title", "graph.axis.right_title"), ("scale", "graph.axis.scale"),
                                 ("min", "graph.axis.min"), ("max", "graph.axis.max")):
                self.right[key].setAccessibleName(f"{box.title()}: {tr(caption)}")
                form.addRow(tr(caption), self.right[key])
            layout.addWidget(box)
        self.breaks_summary = None
        self.breaks_button = None
        if getattr(self.axes, SUPPORT_ATTR, False):
            box = QGroupBox(tr("axis_breaks.title"))
            grid = QGridLayout(box)
            self.breaks_button = QPushButton(tr("axis_breaks.button"))
            self.breaks_button.clicked.connect(self.edit_breaks)
            grid.addWidget(self.breaks_button, 0, 0)
            self.breaks_summary = QLabel()
            grid.addWidget(self.breaks_summary, 0, 1)
            self.breaks_note = QLabel()
            self.breaks_note.setObjectName("muted")
            self.breaks_note.setWordWrap(True)
            grid.addWidget(self.breaks_note, 1, 0, 1, 2)
            grid.setColumnStretch(1, 1)
            layout.addWidget(box)
        self._linked_box(layout)
        self._break_states()
        layout.addStretch(1)

    def _linked_box(self, layout):
        box = QGroupBox(tr("linked_axes.title"))
        grid = QGridLayout(box)
        self.linked_button = QPushButton(tr("linked_axes.button"))
        self.linked_button.clicked.connect(self.edit_linked)
        grid.addWidget(self.linked_button, 0, 0)
        self.linked_summary = QLabel()
        grid.addWidget(self.linked_summary, 0, 1)
        self.linked_note = QLabel()
        self.linked_note.setObjectName("muted")
        self.linked_note.setWordWrap(True)
        grid.addWidget(self.linked_note, 1, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        layout.addWidget(box)
        for choice in self.scales.values():
            choice.currentIndexChanged.connect(lambda _=0: self._linked_states())
        self._linked_states()

    def _scale_values(self):
        return {dimension: choice.value() for dimension, choice in self.scales.items()}

    def _linked_conflicts(self):
        """The axes that cannot take a linked axis with the scales, breaks and series sides chosen in this dialog."""
        from .linked_axes import available_conflicts

        right = None
        if self.xy is not None:
            self._store_series()
            columns = self.xy["options"].get("Y columns") or ()
            right = any(self.xy_side.get(column) == "Right" for column in columns)
        return available_conflicts(self.axes, scales=self._scale_values(), breaks=bool(self.axis_breaks),
                                   right=right)

    def _linked_states(self):
        from .linked_axes import conflict_note, linked_summary

        conflicts = self._linked_conflicts()
        self.linked_summary.setText(linked_summary(self.linked_axes))
        self.linked_note.setText(conflict_note(conflicts))
        self.linked_button.setEnabled(len(conflicts) < 2 or bool(self.linked_axes))

    def edit_linked(self):
        from .linked_axes import LinkedAxesDialog

        dialog = LinkedAxesDialog(self, self.axes, self.linked_axes, conflicts=self._linked_conflicts(),
                                  scales=self._scale_values())
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.linked_axes = dialog.result
            self._linked_states()

    def _check_linked(self, style, figure=None):
        """Linked axes chosen here must show on the graph; saved ones that cannot show stay, with the note."""
        record, saved = style.get(LINKED_AXES) or {}, self.style.get(LINKED_AXES) or {}
        changed = [dimension for dimension, item in record.items() if item != saved.get(dimension)]
        if not changed:
            return
        if figure is not None:
            reasons = linked_axes_reasons(figure)
        else:
            reasons = {dimension: message for dimension, message in self._linked_conflicts().items()}
        for dimension in changed:
            if dimension in reasons:
                self.tabs.setCurrentIndex(1)
                raise ValueError(reasons[dimension])

    def _break_states(self):
        """The limits and the scale of an axis with breaks come from its segments, so those fields rest."""
        for dimension in self.scales:
            self._axis_states(dimension)
        if self.breaks_summary is not None:
            from .axis_breaks import breaks_summary, translate_breaks_error

            axis = self.axis_breaks.get("axis")
            self.breaks_summary.setText(breaks_summary(self.axis_breaks))
            reason = axis_breaks_reason(self.axes.figure) if axis else None
            if reason:
                note = tr("axis_breaks.status.ignored", reason=translate_breaks_error(ValueError(reason)))
            else:
                note = tr("axis_breaks.axis_note", axis=axis.upper()) if axis else ""
            self.breaks_note.setText(note)

    def edit_breaks(self):
        from .axis_breaks import AxisBreaksDialog

        dialog = AxisBreaksDialog(self, self.axes, self.axis_breaks)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.axis_breaks = dialog.result
            self._break_states()

    def _axis_states(self, dimension):
        mode = self.scales[dimension].value()
        broken = self.axis_breaks.get("axis") == dimension
        self.scales[dimension].setEnabled(self.scale_enabled[dimension] and not broken)
        for key, field in self.axis_fields[dimension].items():
            disabled = (not self.numeric[dimension] or (mode == "log" and key in {"step", "start"})
                        or (mode in PROBABILITY_SCALES and key not in {"min", "max"})
                        or (broken and key in {"min", "max", "step", "start"}))
            field.setEnabled(not disabled)

    def _series(self):
        title = tr("graph.format.series")
        self.series_scroll = None
        if self.grouped is not None:
            page = QWidget()
            self.tabs.addTab(page, title)
            columns = QHBoxLayout(page)
            self.series_scroll = QScrollArea()
            self.series_scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.series_scroll.setWidgetResizable(True)
            left_host = QWidget()
            form = QFormLayout(left_host)
            self.series_scroll.setWidget(left_host)
            columns.addWidget(self.series_scroll, 1)
        else:
            columns = None
            form = QFormLayout(self._tab(title))
        self.selector = QComboBox()
        self.selector.addItems([
            series.name if series.key.startswith(GROUPED_PREFIX) else series_name(series) for series in self.series
        ])
        self.selector.setEnabled(bool(self.series))
        form.addRow(tr("graph.series.element"), self.selector)
        self.series_fields = {}
        for key, caption in SERIES_LABELS.items():
            if key in INTERVAL_STYLE_FIELDS and not self._grouped_present:
                continue
            if key == "line_style":
                field = Choice((DEFAULT, *LINE_STYLES), {**DEFAULT_LABELS, **LINE_LABELS})
            elif key == "marker":
                field = Choice((DEFAULT, *MARKERS), {**DEFAULT_LABELS, **MARKER_LABELS})
            else:
                field = QLineEdit()
            self.series_fields[key] = field
            if key in INTERVAL_STYLE_FIELDS:
                field.setAccessibleName(tr(caption))
                field.setToolTip(tr("grouped.interval." + key.removeprefix("interval_") + "_hint"))
                field.editingFinished.connect(self._update_grouped_preview)
            if key in SERIES_COLOR_FIELDS:
                row = QHBoxLayout()
                row.addWidget(field, 1)
                button = _color_button(field)
                field.button = button
                row.addWidget(button)
                form.addRow(tr(caption), row)
            else:
                form.addRow(tr(caption), field)
        self.draw = self.side = self.bar_width = None
        self.grouped_draw = self.grouped_place = self.grouped_note = self.preview_canvas = None
        self.grouped_interval = None
        if self.xy is not None or self._grouped_present:
            visible_box = QCheckBox(tr("graph.series.visible"))
            visible_box.setObjectName("seriesVisible")
            self.series_fields["visible"] = visible_box
            form.addRow(visible_box)
        if self.xy is not None:
            self.draw = Choice(DRAW_STYLES, DRAW_LABELS)
            self.side = Choice(SIDES, SIDE_LABELS)
            self.draw.currentIndexChanged.connect(self._series_states)
            form.addRow(tr("graph.series.draw_style"), self.draw)
            form.addRow(tr("graph.series.side"), self.side)
            saved_width = self.xy["options"].get(BAR_WIDTH)
            text = "" if saved_width in (None, "") else str(saved_width)
            if active_language() == "it":
                text = text.replace(".", ",")
            self.bar_width = QLineEdit(text)
            self.bar_width.setPlaceholderText(tr("graph.series.bar_width_hint"))
            form.addRow(tr("graph.series.bar_width"), self.bar_width)
            self.series_form = form
        if self._grouped_present:
            self.grouped_draw = Choice(SERIES_DRAW_STYLES, GROUPED_DRAW_LABELS)
            self.grouped_draw.setObjectName("groupedSeriesDrawing")
            self.grouped_draw.currentIndexChanged.connect(self._on_grouped_draw_changed)
            form.insertRow(1, tr("grouped.series.drawing"), self.grouped_draw)
            if self.grouped is not None:
                self.grouped_place = Choice((AS_GRAPH, *RELATIVE_PLACEMENTS), GROUPED_PLACEMENT_LABELS)
                self.grouped_place.setObjectName("groupedSeriesPlacement")
                self.grouped_place.currentIndexChanged.connect(self._change_grouped_placement)
                form.insertRow(2, tr("grouped.series.placement"), self.grouped_place)
                self.grouped_interval = Choice((AS_GRAPH, *INTERVAL_DIRECTIONS), GROUPED_INTERVAL_LABELS)
                self.grouped_interval.setObjectName("groupedSeriesIntervalDirection")
                caption = tr("grouped.series.interval_direction")
                self.grouped_interval.setAccessibleName(caption)
                self.grouped_interval.currentIndexChanged.connect(self._change_grouped_interval)
                form.insertRow(3, caption, self.grouped_interval)
                QWidget.setTabOrder(self.selector, self.grouped_draw)
                QWidget.setTabOrder(self.grouped_draw, self.grouped_place)
                QWidget.setTabOrder(self.grouped_place, self.grouped_interval)
                QWidget.setTabOrder(self.grouped_interval, self.series_fields["label"])
            self.grouped_note = QLabel()
            self.grouped_note.setObjectName("infoBanner")
            self.grouped_note.setWordWrap(True)
            self.grouped_note.setVisible(False)
            form.insertRow(4 if self.grouped_interval is not None else 2, self.grouped_note)
        self.series_hint = QLabel(tr("graph.series.hint" if self.series else "graph.series.none"))
        self.series_hint.setObjectName("muted")
        self.series_hint.setWordWrap(True)
        form.addRow(self.series_hint)
        if self.grouped is not None:
            self.preview_group = QGroupBox(tr("graph.format.preview"))
            self.series_columns = columns
            preview_layout = QVBoxLayout(self.preview_group)
            self.preview_canvas = FigureCanvasQTAgg(Figure(figsize=(4.4, 3.0), dpi=76))
            self.preview_canvas.setObjectName("groupedPreviewCanvas")
            self.preview_canvas.setMinimumSize(320, 240)
            preview_layout.addWidget(self.preview_canvas, 1)
            columns.addWidget(self.preview_group, 1)
        self.selector.currentIndexChanged.connect(self._select_series)
        self._select_series()

    def _bar_arrangement(self, options):
        page = self._tab(tr("grouped.spacing.tab"))
        self.spacing_tab = self.tabs.count() - 1
        columns = QHBoxLayout(page)
        panel = QVBoxLayout()
        columns.addLayout(panel)
        direction = QFormLayout()
        panel.addLayout(direction)
        self.bar_direction = Choice(
            BAR_DIRECTIONS, {VERTICAL_BARS: "grouped.bars.vertical", HORIZONTAL_BARS: "grouped.bars.horizontal"},
            options.get(BAR_DIRECTION, VERTICAL_BARS),
        )
        caption = tr("grouped.bars.direction")
        self.bar_direction.setAccessibleName(caption)
        self.bar_direction.setToolTip(tr("grouped.bars.direction_hint"))
        self.bar_direction.currentIndexChanged.connect(self._update_grouped_preview)
        direction.addRow(caption, self.bar_direction)
        baseline = options.get(BAR_BASELINE)
        text = str(baseline) if baseline else ""
        if active_language() == "it":
            text = text.replace(".", ",")
        self.bar_baseline = QLineEdit(text)
        baseline_label = tr("grouped.bars.baseline")
        self.bar_baseline.setAccessibleName(baseline_label)
        self.bar_baseline.setPlaceholderText(tr("grouped.bars.baseline_default"))
        self.bar_baseline.setEnabled(not self._grouped_stacked)
        self.bar_baseline.setToolTip(tr(
            "grouped.bars.baseline_graph" if self._grouped_stacked else "grouped.bars.baseline_hint"
        ))
        self.bar_baseline.editingFinished.connect(self._update_grouped_preview)
        direction.addRow(baseline_label, self.bar_baseline)
        values = options.get(GROUPED_BAR_SPACING)
        settings = QGroupBox(tr("grouped.spacing.custom"))
        settings.setObjectName("groupedBarSpacing")
        settings.setCheckable(True)
        settings.setChecked(values is not None)
        self.spacing_enabled = settings
        panel.addWidget(settings)
        panel.addStretch(1)
        form = QFormLayout(settings)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        hint = QLabel(tr("grouped.spacing.hint"))
        hint.setWordWrap(True)
        form.addRow(hint)
        redraw = QTimer(self)
        redraw.setInterval(120)
        redraw.setSingleShot(True)
        redraw.timeout.connect(self._update_grouped_preview)
        for key, default in BAR_SPACING_DEFAULTS.items():
            caption = tr(f"grouped.spacing.{key}")
            field = self.spacing_controls[key] = QDoubleSpinBox()
            field.setAccessibleName(caption)
            field.setLocale(QLocale(active_language()))
            field.setDecimals(2)
            field.setRange(0., BAR_SPACING_MAXIMUMS[key])
            field.setSuffix(" %")
            field.setKeyboardTracking(False)
            field.setValue(default if values is None else values[key])
            field.valueChanged.connect(lambda _: redraw.start())
            form.addRow(caption, field)
        settings.toggled.connect(self._update_grouped_preview)

        def place_preview(index):
            target = columns if index == self.spacing_tab else self.series_columns
            if target.indexOf(self.preview_group) < 0:
                target.addWidget(self.preview_group, 1)

        self.tabs.currentChanged.connect(place_preview)

    def _effective_grouped_draw(self, series):
        if series is None or not series.key.startswith(GROUPED_PREFIX):
            return self._grouped_global_style
        if self.grouped_draw is not None and 0 <= self.series_index < len(self.series) and self.series[self.series_index] is series:
            chosen = self.grouped_draw.value() or AS_GRAPH
        else:
            chosen = self.grouped_style_map.get(series.name, AS_GRAPH)
        return self._grouped_global_style if chosen == AS_GRAPH else chosen

    def _on_grouped_draw_changed(self, *_):
        if not 0 <= self.series_index < len(self.series):
            return
        series = self.series[self.series_index]
        if self._grouped_editable and series.key.startswith(GROUPED_PREFIX):
            chosen = self.grouped_draw.value() or AS_GRAPH
            if chosen == AS_GRAPH:
                self.grouped_style_map.pop(series.name, None)
            else:
                self.grouped_style_map[series.name] = chosen
            marker_field = self.series_fields.get("marker")
            if marker_field is not None:
                eff = self._effective_grouped_draw(series)
                markers = [label for label, code in MARKERS.items()
                           if code != "none" or eff == GROUPED_LINE_SYMBOLS]
                current_marker = marker_field.value()
                marker_field.set_values((DEFAULT, *markers), {**DEFAULT_LABELS, **MARKER_LABELS})
                marker_field.set(current_marker if current_marker in (DEFAULT, *markers) else DEFAULT)
        self._series_states()
        self._update_grouped_preview()

    def _change_grouped_placement(self):
        if not self.grouped_place.isEnabled() or self.series_index <= 0:
            return
        name = self.series[self.series_index].name
        value = self.grouped_place.value()
        if value == AS_GRAPH:
            self.grouped_placement_map.pop(name, None)
        else:
            self.grouped_placement_map[name] = value
        self._series_states()
        self._update_grouped_preview()

    def _change_grouped_interval(self):
        if not self.grouped_interval.isEnabled() or self.series_index < 0:
            return
        name = self.series[self.series_index].name
        direction = self.grouped_interval.value()
        if direction == AS_GRAPH:
            self.grouped_interval_map.pop(name, None)
        else:
            self.grouped_interval_map[name] = direction
        self._update_grouped_preview()

    def _has_bars(self):
        styles = dict(self.xy_style)
        if self.draw is not None and 0 <= self.series_index < len(self.series):
            series = self.series[self.series_index]
            if series.kind == "xy":
                styles[series.name] = self.draw.value()
        return any(styles.get(name) == BARS for name in self.xy["options"].get("Y columns", ()))

    def _store_series(self):
        if not 0 <= self.series_index < len(self.series):
            return
        series = self.series[self.series_index]
        options = dict(self.series_values.get(series.key, {}))
        for key in series.fields:
            field = self.series_fields.get(key)
            if field is None:
                continue
            options.pop(key, None)
            if key == "visible":
                if not field.isChecked():
                    options[key] = False
            elif isinstance(field, Choice):
                value = field.value()
                if value != DEFAULT:
                    options[key] = MARKERS[value] if key == "marker" else value
            else:
                value = field.text().strip()
                if value:
                    options[key] = value
        if options:
            self.series_values[series.key] = options
        else:
            self.series_values.pop(series.key, None)
        if self.draw is not None and series.kind == "xy":
            self.xy_style[series.name] = self.draw.value() or "Points"
            self.xy_side[series.name] = self.side.value() or "Left"
        if self.grouped_draw is not None and self._grouped_editable and series.key.startswith(GROUPED_PREFIX):
            chosen = self.grouped_draw.value() or AS_GRAPH
            if chosen == AS_GRAPH:
                self.grouped_style_map.pop(series.name, None)
            else:
                self.grouped_style_map[series.name] = chosen

    def _select_series(self, *_):
        self._store_series()
        self.series_index = self.selector.currentIndex()
        series = self.series[self.series_index] if 0 <= self.series_index < len(self.series) else None
        options = self.series_values.get(series.key, {}) if series else {}
        for key, field in self.series_fields.items():
            value = options.get(key, "")
            if key == "visible":
                field.setChecked(options.get(key, True))
            elif key == "marker":
                allow_none = bool(
                    series and (
                        series.kind in {"line", "errorbar", "xy"}
                        or (series.key.startswith(GROUPED_PREFIX)
                            and self._effective_grouped_draw(series) == GROUPED_LINE_SYMBOLS)
                    )
                )
                markers = [label for label, code in MARKERS.items() if code != "none" or allow_none]
                field.set_values((DEFAULT, *markers), {**DEFAULT_LABELS, **MARKER_LABELS})
                field.set(next((label for label in markers if MARKERS[label] == value), DEFAULT))
            elif key == "line_style":
                field.set(value or DEFAULT)
            else:
                field.setText(str(value))
        if self.draw is not None:
            active = series is not None and series.kind == "xy"
            self.draw.setEnabled(active)
            self.side.setEnabled(active)
            if active:
                self.draw.set(self.xy_style.get(series.name, "Points"))
                self.side.set(self.xy_side.get(series.name, "Left"))
        if self.grouped_draw is not None:
            is_grouped = series is not None and series.key.startswith(GROUPED_PREFIX)
            can_edit = self._grouped_editable and is_grouped
            self.grouped_draw.blockSignals(True)
            self.grouped_draw.setEnabled(can_edit)
            self.grouped_draw.set(self.grouped_style_map.get(series.name, AS_GRAPH) if is_grouped else AS_GRAPH)
            self.grouped_draw.blockSignals(False)
            if self.grouped_place is not None:
                self.grouped_place.blockSignals(True)
                self.grouped_place.setEnabled(can_edit and self.series_index > 0)
                self.grouped_place.set(self.grouped_placement_map.get(series.name, AS_GRAPH) if is_grouped else AS_GRAPH)
                self.grouped_place.setToolTip(
                    tr("grouped.placement.previous", name=self.series[self.series_index - 1].name)
                    if is_grouped and self.series_index > 0 else tr("grouped.placement.first")
                )
                self.grouped_place.blockSignals(False)
            if self.grouped_interval is not None:
                self.grouped_interval.blockSignals(True)
                self.grouped_interval.setEnabled(can_edit and self._grouped_has_intervals)
                chosen = self.grouped_interval_map.get(series.name, AS_GRAPH) if is_grouped else AS_GRAPH
                self.grouped_interval.set(chosen)
                self.grouped_interval.setToolTip(tr(
                    "grouped.series.interval_hint" if self._grouped_has_intervals else "grouped.series.interval_inactive"
                ))
                self.grouped_interval.blockSignals(False)
        self._series_states()

    def _series_states(self, *_):
        series = self.series[self.series_index] if 0 <= self.series_index < len(self.series) else None
        if self.draw is not None and series and series.kind == "xy":
            draw = self.draw.value()
        elif self.grouped_draw is not None and series and series.key.startswith(GROUPED_PREFIX):
            draw = self.grouped_draw.value()
        else:
            draw = None
        active = active_series_fields(self.axes, series, draw) if series else set()
        if self.bar_width is not None:
            self.series_form.setRowVisible(self.bar_width, self._has_bars())
        for key, field in self.series_fields.items():
            field.setEnabled(bool(series and key in active))
            if hasattr(field, "button"):
                field.button.setEnabled(bool(series and key in active))
        if self.grouped_note is not None:
            if self._grouped_stacked:
                self.grouped_note.setText(tr("grouped.series.unavailable_stacked"))
                self.grouped_note.setVisible(True)
            elif self._grouped_incompatible_style:
                self.grouped_note.setText(tr("grouped.series.unavailable_style"))
                self.grouped_note.setVisible(True)
            elif STACK_PREVIOUS in self.grouped_placement_map.values():
                self.grouped_note.setText(tr("grouped.placement.stacks_note"))
                self.grouped_note.setVisible(True)
            else:
                self.grouped_note.clear()
                self.grouped_note.setVisible(False)
        if not self.series:
            hint = tr("graph.series.none")
        elif self._grouped_editable and series and series.key.startswith(GROUPED_PREFIX):
            hint = tr("grouped.series.hint_available")
        elif series and series.kind == "xy" and active != series.fields:
            hint = tr("graph.series.inactive_hint")
        else:
            hint = tr("graph.series.hint")
        self.series_hint.setText(hint)

    def _references(self):
        page = self._tab(tr("graph.format.references"))
        layout = QVBoxLayout(page)
        hint = QLabel(tr("graph.references.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        lines = []
        for line in self.style.get("reference_lines", []):
            label = ", " + line["label"] if line.get("label") else ""
            lines.append(f"{line['axis'].upper()}, {line['value']}{label}")
        self.references = QPlainTextEdit("\n".join(lines))
        layout.addWidget(self.references, 1)
        extra = QGridLayout()
        self.guide_records = {AXIS_GUIDES: deepcopy(self.style.get(AXIS_GUIDES, [])),
                              AXIS_BANDS: deepcopy(self.style.get(AXIS_BANDS, []))}
        self.guide_summaries = {}
        for row, (key, caption) in enumerate(((AXIS_GUIDES, "graph.guides.button"),
                                              (AXIS_BANDS, "graph.bands.button"))):
            button = QPushButton(tr(caption))
            button.clicked.connect(lambda _=False, key=key: self.edit_guides(key))
            extra.addWidget(button, row, 0)
            self.guide_summaries[key] = QLabel()
            self.guide_summaries[key].setObjectName("muted")
            extra.addWidget(self.guide_summaries[key], row, 1)
        extra.setColumnStretch(1, 1)
        layout.addLayout(extra)
        self._guide_summaries()

    def _guide_summaries(self):
        for key, label in self.guide_summaries.items():
            items = self.guide_records[key]
            label.setText(tr("graph.guides.summary_count", count=len(items)) if items
                          else tr("graph.guides.summary_none"))

    def edit_guides(self, key):
        from .axis_guides import AxisBandsDialog, AxisGuidesDialog

        overrides = {dimension: choice.value() for dimension, choice in self.scales.items()}
        dialog = (AxisGuidesDialog if key == AXIS_GUIDES else AxisBandsDialog)(
            self, self.axes, self.guide_records[key], overrides)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.guide_records[key] = dialog.result
            self._guide_summaries()

    # -- reading ------------------------------------------------------------------------------------
    def _focus(self, tab, widget=None):
        self.tabs.setCurrentIndex(tab)
        if widget is not None:
            scroll = self.series_scroll if tab == 2 and self.series_scroll is not None else self.tabs.widget(tab)
            scroll.ensureWidgetVisible(widget)
            widget.setFocus()
            if isinstance(widget, QLineEdit):
                widget.selectAll()

    def read_style(self):
        style = {key: field.text() for key, field in self.texts.items()}
        for dimension, scale in self.scales.items():
            style[dimension + "scale"] = scale.value()
        if self.accent is not None and self.accent.text().strip():
            style["accent"] = self.accent.text().strip()
        for key in KEPT:
            if self.style.get(key):
                style[key] = deepcopy(self.style[key])
        if self.axis_breaks:
            style[AXIS_BREAKS] = deepcopy(self.axis_breaks)
        if self.linked_axes:
            style[LINKED_AXES] = deepcopy(self.linked_axes)
        if self.legend_options:
            style[LEGEND_OPTIONS_KEY] = deepcopy(self.legend_options)
        for key, records in self.guide_records.items():
            style.pop(key, None)
            if records:
                style[key] = deepcopy(records)
        style["grid"] = self.grid.isChecked()
        style["grid_minor"] = self.grid_minor.isChecked()
        for key, choice in self.choices.items():
            if choice.value() != DEFAULT:
                style[key] = choice.value()
        for key, field in self.fonts.items():
            text = field.text().strip()
            if text:
                try:
                    style[key] = float(text.replace(",", "."))
                except ValueError:
                    self._focus(0, field)
                    raise ValueError(tr("graph.field.font_hint")) from None
        axes = {}
        for dimension, fields in self.axis_fields.items():
            settings = {}
            for key, field in fields.items():
                text = field.text().strip()
                if not text or not field.isEnabled():
                    continue
                try:
                    settings[key] = int(text) if key in {"minor", "decimals"} else float(text.replace(",", "."))
                except ValueError:
                    self._focus(1, field)
                    raise ValueError(f"{tr(AXIS_FIELDS[key])} ({dimension.upper()}): {text}") from None
            if settings:
                axes[dimension] = settings
        if axes:
            style["axis"] = axes
        self._store_series()
        if self.series_values:
            parsed = {}
            for key, options in self.series_values.items():
                values = {}
                for name, value in options.items():
                    if name in SERIES_NUMBER_FIELDS:
                        try:
                            value = float(str(value).replace(",", "."))
                        except ValueError:
                            self._focus(2, self.series_fields[name])
                            raise ValueError(f"{tr(SERIES_LABELS[name])}: {value}") from None
                    values[name] = value
                parsed[key] = values
            style["series"] = parsed
        references = []
        for line in self.references.toPlainText().splitlines():
            if not line.strip():
                continue
            cells = [cell.strip() for cell in line.split(",", 2)]
            try:
                if len(cells) < 2:
                    raise ValueError
                references.append({"axis": cells[0].lower(), "value": float(cells[1]),
                                   "label": cells[2] if len(cells) == 3 else ""})
            except ValueError:
                self._focus(3, self.references)
                raise ValueError(tr("graph.references.error")) from None
        if references:
            style["reference_lines"] = references
        return style

    def _xy_options(self, style):
        options = dict(self.xy["options"])
        columns = list(options.get("Y columns") or [])
        options["Series style"] = {column: self.xy_style.get(column, "Points") for column in columns}
        options["Series side"] = {column: self.xy_side.get(column, "Left") for column in columns}
        if self._has_bars():
            width = parse_bar_width(self.bar_width.text())
            if width is None:
                options.pop(BAR_WIDTH, None)
            else:
                options[BAR_WIDTH] = width
        title = self.right["title"].text().strip()
        if title:
            options["Right title"] = title
        else:
            options.pop("Right title", None)
        options["Right scale"] = self.right["scale"].value() or "Linear"
        low, high = self.right["min"].text().strip(), self.right["max"].text().strip()
        if low or high:
            for key, text in (("min", low), ("max", high)):
                try:
                    options["Right minimum" if key == "min" else "Right maximum"] = (
                        float(text.replace(",", ".")) if text else "")
                except ValueError:
                    self._focus(1, self.right[key])
                    raise ValueError(f'{tr(AXIS_FIELDS[key])}: {text}') from None
        else:
            options.pop("Right minimum", None)
            options.pop("Right maximum", None)
        y_axis = style.get("axis", {}).get("y", {})
        if "min" in y_axis and "max" in y_axis:
            options["Y minimum"], options["Y maximum"] = y_axis["min"], y_axis["max"]
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

    def _grouped_options(self):
        options = dict(self.grouped["options"])
        styles = {name: val for name, val in self.grouped_style_map.items() if val and val != AS_GRAPH}
        if styles:
            options[SERIES_STYLE] = styles
        else:
            options.pop(SERIES_STYLE, None)
        names = grouped_series_names(self.grouped["frame"], options)
        options.pop(SERIES_PLACEMENT, None)
        placements = series_placements({SERIES_PLACEMENT: self.grouped_placement_map})
        if placements := {name: placements[name] for name in names if name in placements}:
            options[SERIES_PLACEMENT] = placements
        options.pop(SERIES_INTERVAL_DIRECTION, None)
        directions = series_interval_directions({SERIES_INTERVAL_DIRECTION: self.grouped_interval_map})
        if directions := {name: directions[name] for name in names if name in directions}:
            options[SERIES_INTERVAL_DIRECTION] = directions
        options.pop(GROUPED_BAR_SPACING, None)
        if self.spacing_enabled is not None and self.spacing_enabled.isChecked():
            options[GROUPED_BAR_SPACING] = {key: field.value() for key, field in self.spacing_controls.items()}
        options.pop(BAR_DIRECTION, None)
        if self.bar_direction is not None and self.bar_direction.value() == HORIZONTAL_BARS:
            options[BAR_DIRECTION] = HORIZONTAL_BARS
        options.pop(BAR_BASELINE, None)
        if self.bar_baseline is not None and self.bar_baseline.isEnabled() and self.bar_baseline.text().strip():
            try:
                baseline = float(self.bar_baseline.text().strip().replace(",", "."))
            except ValueError:
                raise FieldError(BAR_BASELINE, "Enter a finite starting value for the bars.") from None
            if baseline:
                options[BAR_BASELINE] = baseline
        return prune_series_styles(options, names)

    def _grouped_style(self, style, options):
        for key, default in (("xlabel", self.axes.get_xlabel()), ("ylabel", self.axes.get_ylabel())):
            if key not in self.style and style.get(key) == default:
                style.pop(key)
        previous = self.grouped["options"].get(BAR_DIRECTION, VERTICAL_BARS)
        if options.get(BAR_DIRECTION, VERTICAL_BARS) != previous:
            return transpose_grouped_bar_style(style)
        return style

    def _grouped_changed(self, options):
        old = {k: v for k, v in (self.grouped["options"].get(SERIES_STYLE) or {}).items() if v and v != AS_GRAPH}
        new = {k: v for k, v in (options.get(SERIES_STYLE) or {}).items() if v and v != AS_GRAPH}
        previous = self.grouped["options"]
        return old != new or any(previous.get(key, {}) != options.get(key, {})
                                 for key in (SERIES_PLACEMENT, GROUPED_BAR_SPACING, SERIES_INTERVAL_DIRECTION,
                                             BAR_DIRECTION, BAR_BASELINE))

    def _prepare_grouped(self, style, options):
        result = category_graph(self.grouped["frame"], options, grouped=True)
        apply_style(result.figure, style)
        self.grouped_update, self.grouped_result = options, result

    def _render_grouped_preview(self, style, options):
        if self.preview_canvas is None:
            return
        result = category_graph(self.grouped["frame"], options, grouped=True)
        apply_style(result.figure, style)
        canvas = self.preview_canvas
        dpi = canvas.figure._original_dpi
        result.figure._original_dpi = dpi
        result.figure.set_dpi(dpi * canvas.device_pixel_ratio)
        result.figure.set_size_inches(canvas.width() / dpi, canvas.height() / dpi, forward=False)
        result.figure.set_canvas(canvas)
        canvas.figure = result.figure
        canvas.draw_idle()

    def _update_grouped_preview(self):
        if self.preview_canvas is None or self.grouped is None or not hasattr(self, "references"):
            return
        try:
            options = self._grouped_options()
            self._render_grouped_preview(self._grouped_style(self.read_style(), options), options)
        except (ValueError, FieldError):
            pass

    def preview(self):
        """Validate current edits and refresh the embedded preview canvas without committing."""
        try:
            options = self._grouped_options()
            self._render_grouped_preview(self._grouped_style(self.read_style(), options), options)
        except ValueError as error:
            self.show_error(error)
            return False
        self.banner.setVisible(False)
        return True

    def _focus_xy_error(self, error):
        field = getattr(error, "field", None)
        if field == BAR_WIDTH:
            self._focus(2, self.bar_width)
        elif field in ("X scale", "Y scale"):
            self._focus(1, self.scales[field[0].lower()])
        elif field == "Y minimum":
            self._focus(1, self.axis_fields["y"]["min"])
        elif field in ("Right scale", "Right minimum", "Right maximum"):
            self._focus(1, self.right[{"Right scale": "scale", "Right minimum": "min", "Right maximum": "max"}[field]])
        elif field == "Y columns" and getattr(error, "column", None):
            for index, series in enumerate(self.series):
                if series.kind == "xy" and series.name == error.column:
                    self.selector.setCurrentIndex(index)
                    break
            self._focus(2, self.draw)

    def show_error(self, error):
        if isinstance(error, FieldError) and self.xy is not None:
            self._focus_xy_error(error)
        elif isinstance(error, FieldError) and self.grouped_draw is not None:
            if error.field == GROUPED_BAR_SPACING and self.spacing_enabled is not None:
                self._focus(self.spacing_tab, self.spacing_enabled)
            elif error.field == BAR_DIRECTION and self.bar_direction is not None:
                self._focus(self.spacing_tab, self.bar_direction)
            elif error.field == BAR_BASELINE and self.bar_baseline is not None:
                self._focus(self.spacing_tab, self.bar_baseline)
            elif error.field == SERIES_PLACEMENT and self.grouped_place is not None:
                self._focus(2, self.grouped_place if self.grouped_place.isEnabled() else self.selector)
            elif error.field == SERIES_INTERVAL_DIRECTION and self.grouped_interval is not None:
                self._focus(2, self.grouped_interval if self.grouped_interval.isEnabled() else self.selector)
            elif error.field in (SERIES_STYLE, "Placement of groups", "Graph style"):
                self._focus(2, self.grouped_draw)
        if not isinstance(error, str):
            from .axis_breaks import translate_breaks_error
            from .axis_guides import translate_guide_error
            from .linked_axes import translate_linked_error

            from .legend import translate_legend_error

            for translate in (translate_message, lambda value: translate_message(value, "xy.error."),
                              translate_grouped_error, translate_legend_error, translate_guide_error,
                              translate_breaks_error, translate_linked_error):
                text = translate(error)
                if text != str(error):
                    break
            error = text
        self.banner.setText(error)
        self.banner.setVisible(True)

    def accept(self):
        try:
            style = self.read_style()
            if self.grouped is not None:
                options = self._grouped_options()
                style = self._grouped_style(style, options)
                if self._grouped_changed(options):
                    self._prepare_grouped(style, options)
                    if style.get(AXIS_BREAKS) and style[AXIS_BREAKS] != self.style.get(AXIS_BREAKS):
                        reason = axis_breaks_reason(self.grouped_result.figure)
                        if reason:
                            from .axis_breaks import translate_breaks_error

                            self.tabs.setCurrentIndex(1)
                            raise ValueError(translate_breaks_error(ValueError(reason)))
                    self._check_linked(style, self.grouped_result.figure)
                else:
                    self.grouped_update = self.grouped_result = None
                    validate_graph_style(self.axes, style)
                    self._check_linked(style)
            elif self.xy is None:
                validate_graph_style(self.axes, style)
                self._check_linked(style)
            else:
                if "ylabel" not in self.style and style["ylabel"] == self.axes.get_ylabel():
                    style.pop("ylabel")
                self._prepare_xy(style, self._xy_options(style))
                # Breaks chosen here must show on the graph; saved ones that cannot show stay, with the note.
                if style.get(AXIS_BREAKS) and style[AXIS_BREAKS] != self.style.get(AXIS_BREAKS):
                    reason = axis_breaks_reason(self.xy_result.figure)
                    if reason:
                        from .axis_breaks import translate_breaks_error

                        self.tabs.setCurrentIndex(1)
                        raise ValueError(translate_breaks_error(ValueError(reason)))
                self._check_linked(style, self.xy_result.figure)
        except ValueError as error:
            self.show_error(error)
            return
        self.result = style
        super().accept()

    def reset(self):
        """Back to the analysis defaults; drawings, annotations and panel settings stay."""
        style = {key: deepcopy(self.style[key])
                 for key in (ANNOTATIONS, SHAPES, PANEL_KEY, "hierarchical", POINTS, LABELS, TABLES)
                 if self.style.get(key)}
        if self.grouped is not None:
            options = dict(self.grouped["options"])
            reset_drawing = options.pop(SERIES_STYLE, None)
            reset_placement = options.pop(SERIES_PLACEMENT, None)
            reset_spacing = options.pop(GROUPED_BAR_SPACING, None)
            reset_intervals = options.pop(SERIES_INTERVAL_DIRECTION, None)
            reset_direction = options.pop(BAR_DIRECTION, None) == HORIZONTAL_BARS
            reset_baseline = options.pop(BAR_BASELINE, None)
            if reset_direction:
                style = transpose_grouped_bar_style(style)
            if reset_drawing or reset_placement or reset_spacing or reset_intervals or reset_direction or reset_baseline:
                try:
                    self._prepare_grouped(style, options)
                except ValueError as error:
                    self.show_error(error)
                    return
        elif self.xy is not None:
            options = {key: value for key, value in self.xy["options"].items() if key not in RECIPE_KEYS}
            try:
                self._prepare_xy(style, options)
            except ValueError as error:
                self.show_error(error)
                return
        self.result = style
        super().accept()


__all__ = ["GraphFormatDialog"]
