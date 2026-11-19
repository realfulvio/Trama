"""Format Graph on Qt: title, labels, fonts, axes, series and reference lines.

The dialog edits the same style dictionary as the classic one (``analisi.graph_dialog``) and validates
it with the engine, axis guides and bands included. Settings that have their own editor in the classic
window (axis breaks, legend formatting, annotations, shapes, Q–Q panels, dendrogram style) are kept unchanged.
"""
from copy import deepcopy

from matplotlib.colors import to_hex
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from analisi.axis_breaks import AXIS_BREAKS
from analisi.axis_guides import AXIS_BANDS, AXIS_GUIDES
from analisi.graph_annotations import ANNOTATIONS
from analisi.graph_legend import LEGEND_OPTIONS_KEY
from analisi.graph_shapes import SHAPES
from analisi.i18n import tr, translate_message
from analisi.presentation import (FONT_FAMILIES, LEGEND_LOCATIONS, LINE_STYLES, MARKERS, SCALES,
                                  active_series_fields, apply_style, axis_has_numeric_ticks, graph_series,
                                  validate_graph_style, zero_baseline_axes)
from analisi.probability_scale import FRACTION_SCALE, PERCENT_SCALE, PROBABILITY_SCALES
from analisi.qq_panels import PANEL_KEY
from .strings import qt
from analisi.xy_series import (DRAW_STYLES, RECIPE_KEYS, SCALES as XY_SCALES, SIDES, assign_colors,
                               prune_options, xy_series)

# Captions are catalog keys shared with the classic dialog (analisi/graph_dialog.py, which needs Tk).
AXIS_FIELDS = {"min": "graph.axis.min", "max": "graph.axis.max", "step": "graph.axis.step",
               "start": "graph.axis.start", "minor": "graph.axis.minor", "decimals": "graph.axis.decimals"}
FONT_FIELDS = {"title_size": "graph.field.font_title", "label_size": "graph.field.font_labels",
               "tick_size": "graph.field.font_ticks", "legend_size": "graph.field.font_legend"}
SERIES_LABELS = {key: "graph.series." + key
                 for key in ("label", "color", "line_style", "width", "marker", "marker_size", "marker_color")}
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
DRAW_LABELS = {"Points": "graph.draw.points", "Line": "graph.draw.line", "Line and points": "graph.draw.line_points"}
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


# Kept as they are: edited elsewhere (annotations) or by an editor that is not on Qt yet.
KEPT = ("groups", ANNOTATIONS, SHAPES, PANEL_KEY, AXIS_BREAKS, LEGEND_OPTIONS_KEY,
        "hierarchical")


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
    """Returns ``result`` (the new style); for a native XY graph also ``xy_update``/``xy_result``."""

    def __init__(self, parent, axes, style, *, xy=None):
        super().__init__(parent)
        self.setWindowTitle(tr("graph.format.title"))
        self.axes, self.style, self.xy = axes, style, xy
        self.result = self.xy_update = self.xy_result = None
        self.series = graph_series(axes)
        self.series_values = {key: {name: str(value) for name, value in options.items()}
                              for key, options in style.get("series", {}).items()}
        options = (xy or {}).get("options") or {}
        self.xy_style = dict(options.get("Series style") or {})
        self.xy_side = dict(options.get("Series side") or {})
        self.series_index = -1

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
        buttons = QDialogButtonBox()
        buttons.addButton(tr("graph.format.reset"), QDialogButtonBox.ButtonRole.ResetRole).clicked.connect(self.reset)
        buttons.addButton(tr("graph.format.apply"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(tr("graph.format.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.resize(620, 560)

    # -- tabs ----------------------------------------------------------------------------------------
    def _tab(self, title):
        page = QWidget()
        self.tabs.addTab(page, title)
        return page

    def _appearance(self):
        page = self._tab(tr("graph.format.appearance"))
        form = QFormLayout(page)
        self.texts = {}
        for key, caption, value in (("title", "graph.field.title", self.axes.get_title()),
                                    ("xlabel", "graph.field.xlabel", self.axes.get_xlabel()),
                                    ("ylabel", "graph.field.ylabel", self.axes.get_ylabel())):
            self.texts[key] = QLineEdit(str(self.style.get(key, value)))
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

    def _axes(self):
        page = self._tab(tr("graph.format.axes"))
        layout = QVBoxLayout(page)
        blocks = QHBoxLayout()
        layout.addLayout(blocks)
        self.scales, self.axis_fields, self.numeric = {}, {}, {}
        for dimension in ("x", "y"):
            axis = getattr(self.axes, dimension + "axis")
            options = self.style.get("axis", {}).get(dimension, {})
            box = QGroupBox(tr("graph.axis.block", axis=dimension.upper()))
            form = QFormLayout(box)
            zero = dimension in zero_baseline_axes(self.axes)
            scale = Choice(("linear",) if zero else SCALES, SCALE_LABELS,
                           self.style.get(dimension + "scale", axis.get_scale()))
            self.scales[dimension] = scale
            numeric = self.numeric[dimension] = axis_has_numeric_ticks(self.axes, dimension)
            scale.setEnabled(numeric and not (zero and scale.value() == "linear"))
            form.addRow(tr("graph.axis.scale"), scale)
            fields = self.axis_fields[dimension] = {}
            for key, caption in AXIS_FIELDS.items():
                fields[key] = QLineEdit("" if key not in options else str(options[key]))
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
            twin = self.axes.figure.axes[1] if len(self.axes.figure.axes) > 1 else None
            box = QGroupBox(tr("graph.axis.right"))
            form = QFormLayout(box)
            self.right = {
                "title": QLineEdit(options.get("Right title") or (twin.get_ylabel() if twin else "")),
                "scale": Choice(XY_SCALES, RIGHT_SCALE_LABELS, options.get("Right scale") or "Linear"),
                "min": QLineEdit("" if options.get("Right minimum") in (None, "") else str(options["Right minimum"])),
                "max": QLineEdit("" if options.get("Right maximum") in (None, "") else str(options["Right maximum"])),
            }
            for key, caption in (("title", "graph.axis.right_title"), ("scale", "graph.axis.scale"),
                                 ("min", "graph.axis.min"), ("max", "graph.axis.max")):
                form.addRow(tr(caption), self.right[key])
            layout.addWidget(box)
        if self.style.get(AXIS_BREAKS) or self.style.get(AXIS_GUIDES) or self.style.get(AXIS_BANDS):
            kept = QLabel(qt("qt.graph_kept"))
            kept.setWordWrap(True)
            kept.setObjectName("muted")
            layout.addWidget(kept)
        layout.addStretch(1)

    def _axis_states(self, dimension):
        mode = self.scales[dimension].value()
        broken = (self.style.get(AXIS_BREAKS) or {}).get("axis") == dimension
        for key, field in self.axis_fields[dimension].items():
            disabled = (not self.numeric[dimension] or (mode == "log" and key in {"step", "start"})
                        or (mode in PROBABILITY_SCALES and key not in {"min", "max"})
                        or (broken and key in {"min", "max", "step", "start"}))
            field.setEnabled(not disabled)

    def _series(self):
        page = self._tab(tr("graph.format.series"))
        form = QFormLayout(page)
        self.selector = QComboBox()
        self.selector.addItems([series_name(series) for series in self.series])
        self.selector.setEnabled(bool(self.series))
        form.addRow(tr("graph.series.element"), self.selector)
        self.series_fields = {}
        for key, caption in SERIES_LABELS.items():
            if key == "line_style":
                field = Choice((DEFAULT, *LINE_STYLES), {**DEFAULT_LABELS, **LINE_LABELS})
            elif key == "marker":
                field = Choice((DEFAULT, *MARKERS), {**DEFAULT_LABELS, **MARKER_LABELS})
            else:
                field = QLineEdit()
            self.series_fields[key] = field
            if key in {"color", "marker_color"}:
                row = QHBoxLayout()
                row.addWidget(field, 1)
                button = _color_button(field)
                field.button = button
                row.addWidget(button)
                form.addRow(tr(caption), row)
            else:
                form.addRow(tr(caption), field)
        self.draw = self.side = None
        if self.xy is not None:
            self.draw = Choice(DRAW_STYLES, DRAW_LABELS)
            self.side = Choice(SIDES, SIDE_LABELS)
            self.draw.currentIndexChanged.connect(self._series_states)
            form.addRow(tr("graph.series.draw_style"), self.draw)
            form.addRow(tr("graph.series.side"), self.side)
        self.series_hint = QLabel(tr("graph.series.hint" if self.series else "graph.series.none"))
        self.series_hint.setObjectName("muted")
        self.series_hint.setWordWrap(True)
        form.addRow(self.series_hint)
        self.selector.currentIndexChanged.connect(self._select_series)
        self._select_series()

    def _store_series(self):
        if not 0 <= self.series_index < len(self.series):
            return
        series = self.series[self.series_index]
        options = {}
        for key in series.fields:
            field = self.series_fields[key]
            if isinstance(field, Choice):
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

    def _select_series(self, *_):
        self._store_series()
        self.series_index = self.selector.currentIndex()
        series = self.series[self.series_index] if 0 <= self.series_index < len(self.series) else None
        options = self.series_values.get(series.key, {}) if series else {}
        for key, field in self.series_fields.items():
            value = options.get(key, "")
            if key == "marker":
                markers = [label for label, code in MARKERS.items()
                           if code != "none" or (series and series.kind in {"line", "errorbar", "xy"})]
                field.set_values((DEFAULT, *markers), {**DEFAULT_LABELS, **MARKER_LABELS})
                field.set(next((label for label in markers if MARKERS[label] == value), DEFAULT))
            elif key == "line_style":
                field.set(value or DEFAULT)
            else:
                field.setText(value)
        if self.draw is not None:
            active = series is not None and series.kind == "xy"
            self.draw.setEnabled(active)
            self.side.setEnabled(active)
            if active:
                self.draw.set(self.xy_style.get(series.name, "Points"))
                self.side.set(self.xy_side.get(series.name, "Left"))
        self._series_states()

    def _series_states(self, *_):
        series = self.series[self.series_index] if 0 <= self.series_index < len(self.series) else None
        draw = self.draw.value() if (self.draw is not None and series and series.kind == "xy") else None
        active = active_series_fields(self.axes, series, draw) if series else set()
        for key, field in self.series_fields.items():
            field.setEnabled(bool(series and key in active))
            if hasattr(field, "button"):
                field.button.setEnabled(bool(series and key in active))
        if not self.series:
            hint = tr("graph.series.none")
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
                    if name in {"width", "marker_size"}:
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
        title = self.right["title"].text().strip()
        if title:
            options["Right title"] = title
        else:
            options.pop("Right title", None)
        options["Right scale"] = self.right["scale"].value() or "Linear"
        low, high = self.right["min"].text().strip(), self.right["max"].text().strip()
        if low or high:
            options["Right minimum"] = float(low) if low else ""
            options["Right maximum"] = float(high) if high else ""
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

    def show_error(self, error):
        if not isinstance(error, str):
            from .axis_guides import translate_guide_error

            text = translate_message(error)
            error = text if text != str(error) else translate_guide_error(error)
        self.banner.setText(error)
        self.banner.setVisible(True)

    def accept(self):
        try:
            style = self.read_style()
            if self.xy is None:
                validate_graph_style(self.axes, style)
            else:
                if "ylabel" not in self.style and style["ylabel"] == self.axes.get_ylabel():
                    style.pop("ylabel")
                self._prepare_xy(style, self._xy_options(style))
        except ValueError as error:
            self.show_error(error)
            return
        self.result = style
        super().accept()

    def reset(self):
        """Back to the analysis defaults; drawings, annotations and panel settings stay."""
        style = {key: deepcopy(self.style[key]) for key in (ANNOTATIONS, SHAPES, PANEL_KEY, "hierarchical")
                 if self.style.get(key)}
        if self.xy is not None:
            options = {key: value for key, value in self.xy["options"].items() if key not in RECIPE_KEYS}
            try:
                self._prepare_xy(style, options)
            except ValueError as error:
                self.show_error(error)
                return
        self.result = style
        super().accept()


__all__ = ["GraphFormatDialog"]
