"""Graph Inspector on Qt: a side panel that previews style changes on the live graph.

Same contract as the classic panel (``analisi.graph_inspector``): it edits a draft copy of the confirmed
style, previews every valid change with ``apply_style`` and hands the draft to ``commit`` only on Apply.
Cancel, closing the panel and leaving the graph restore the confirmed style. Keys it does not manage stay
in the draft untouched.
"""
from copy import deepcopy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from analisi.axis_breaks import AXIS_BREAKS
from analisi.hierarchical_style import describe_hierarchical_artists
from analisi.i18n import tr, translate_message
from analisi.presentation import (LEGEND_LOCATIONS, LINE_STYLES, MARKERS, SCALES, active_series_fields, apply_style,
                                  axis_has_numeric_ticks, capture_defaults, graph_groups, graph_series,
                                  validate_graph_style, zero_baseline_axes)
from analisi.xy_series import XY_METHOD

from .graph_format import LEGEND_LABELS, LINE_LABELS, MARKER_LABELS, SCALE_LABELS, Choice, _color_button, series_name

AUTO = "Default"
AUTO_LABELS = {AUTO: "graph.choice.default"}
CAPTIONS = {key: "graph.inspector." + key
            for key in ("label", "color", "line_style", "width", "marker", "marker_size", "marker_color")}
TEXT_FIELDS = {"title": 0, "xlabel": 1, "ylabel": 2}
NUMBER_FIELDS = {"width", "marker_size"}
SECTION_KEYS = {"data": ("series",), "axes": ("xlabel", "ylabel", "xscale", "yscale", AXIS_BREAKS),
                "page": ("title", "grid", "legend")}
PREVIEW_DELAY_MS = 350


class FieldProblem(ValueError):
    pass


def _number(text, what):
    try:
        return float(text.replace(",", ".")) if text.count(",") <= 1 else float(text)
    except ValueError as error:
        raise FieldProblem(tr(what)) from error


class GraphInspector(QFrame):
    def __init__(self, run, canvas, *, confirmed, commit, closed, element=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(330)  # Room for the rounded fields at 150% without a sideways scroll bar.
        self.run, self.canvas, self.figure = run, canvas, canvas.figure
        self._confirmed, self._commit, self._closed = confirmed, commit, closed
        self._xy = run.method == XY_METHOD
        self.axes = self.figure.axes[0]
        capture_defaults(self.figure)
        self.defaults = self.axes._tramastat_defaults
        self.groups = graph_groups(self.axes)
        self.elements = self._elements()
        self.draft = deepcopy(self._confirmed() or {})
        self.errors, self.messages, self.widgets = {}, {}, {}
        self._due = []
        self._loading = False
        self._element_key = element
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(PREVIEW_DELAY_MS)
        self.timer.timeout.connect(self._flush)
        self._build()
        self._load()
        self._click = canvas.mpl_connect("button_press_event", self._clicked)

    # -- construction ---------------------------------------------------------------------------------
    def _elements(self):
        names = [group.name for group in self.groups]
        elements = []
        for group in self.groups:
            name = group.name
            if names.count(name) > 1:
                parts = group.key.split(":", 3)
                name = f"{name} ({parts[2]})" if len(parts) > 3 else f"{name} ({group.key})"
            elements.append({"kind": "group", "key": group.key, "name": name, "item": group})
        if not elements:
            elements = [{"kind": "series", "key": series.key, "name": series_name(series), "item": series}
                        for series in graph_series(self.axes)]
        return elements

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        title = QLabel(tr("graph.inspector.title"))
        title.setObjectName("sectionTitle")
        outer.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 4, 0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        warning = getattr(self.run.result, "style_warning", None)
        if warning:
            label = QLabel(tr("graph.inspector.review", warning=warning))
            label.setObjectName("errorBanner")
            label.setWordWrap(True)
            self.body.addWidget(label)
        if describe_hierarchical_artists(self.figure):
            button = QPushButton(tr("hierarchy.style.button"))
            button.clicked.connect(self.edit_hierarchical)
            self.body.addWidget(button)
        self._data_section()
        self._axes_section()
        self._page_section()
        self.body.addStretch(1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.apply_button = QPushButton(tr("graph.inspector.apply"))
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply)
        self.cancel_button = QPushButton(tr("graph.inspector.cancel"))
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.cancel_button)
        outer.addLayout(buttons)

    def _section(self, name, title):
        box = QGroupBox(title)
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.body.addWidget(box)
        return form

    def _finish(self, form, name):
        reset = QPushButton(tr("graph.inspector.reset_section"))
        reset.clicked.connect(lambda: self.reset_section(name))
        form.addRow(reset)

    def _message(self, form, source):
        label = QLabel()
        label.setObjectName("errorBanner")
        label.setWordWrap(True)
        label.setVisible(False)
        form.addRow(label)
        self.messages[source] = label

    def _line(self, form, source, caption):
        field = QLineEdit()
        field.textEdited.connect(lambda _text: self._schedule(source))
        field.editingFinished.connect(lambda: self._now(source))
        form.addRow(caption, field)
        self.widgets[source] = field
        self._message(form, source)
        return field

    def _choice(self, form, source, caption, values, labels):
        field = Choice(values, labels)
        field.currentIndexChanged.connect(lambda _i: self._now(source))
        form.addRow(caption, field)
        self.widgets[source] = field
        self._message(form, source)
        return field

    def _data_section(self):
        form = self._section("data", tr("graph.inspector.data"))
        self.selector = QComboBox()
        self.selector.addItems([item["name"] for item in self.elements])
        self.selector.setEnabled(bool(self.elements))
        self.selector.currentIndexChanged.connect(lambda _i: self._select())
        form.addRow(tr("graph.inspector.element"), self.selector)
        if not self.elements:
            hint = QLabel(tr("graph.series.none"))
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            form.addRow(hint)
        elif self._xy:
            self.xy_hint = QLabel(tr("graph.inspector.xy_hint"))
            self.xy_hint.setObjectName("muted")
            self.xy_hint.setWordWrap(True)
            form.addRow(self.xy_hint)
        self.fields = {}
        for key, caption in CAPTIONS.items():
            source = "element:" + key
            if key == "line_style":
                field = self._choice(form, source, tr(caption), (AUTO, *LINE_STYLES), {**AUTO_LABELS, **LINE_LABELS})
            elif key == "marker":
                field = self._choice(form, source, tr(caption), (AUTO, *MARKERS), {**AUTO_LABELS, **MARKER_LABELS})
            else:
                field = QLineEdit()
                field.textEdited.connect(lambda _text, source=source: self._schedule(source))
                field.editingFinished.connect(lambda source=source: self._now(source))
                if key in {"color", "marker_color"}:
                    row = QWidget()
                    line = QHBoxLayout(row)
                    line.setContentsMargins(0, 0, 0, 0)
                    line.addWidget(field, 1)
                    button = _color_button(field)
                    button.clicked.connect(lambda _=False, source=source: self._now(source))
                    line.addWidget(button)
                    form.addRow(tr(caption), row)
                    field.row = row
                else:
                    form.addRow(tr(caption), field)
                self.widgets[source] = field
                self._message(form, source)
            self.fields[key] = field
        visible = QCheckBox(tr("graph.inspector.show"))
        visible.toggled.connect(lambda _on: self._now("element:visible"))
        form.addRow(visible)
        self.fields["visible"] = self.widgets["element:visible"] = visible
        self.messages["element:visible"] = QLabel()
        self.data_form = form
        hint = QLabel(tr("graph.inspector.blank_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._finish(form, "data")

    def _axes_section(self):
        form = self._section("axes", tr("graph.inspector.axes"))
        self._line(form, "xlabel", tr("graph.field.xlabel"))
        self._line(form, "ylabel", tr("graph.field.ylabel"))
        for dimension in ("x", "y"):
            zero = dimension in zero_baseline_axes(self.axes)
            self._choice(form, dimension + "scale", tr("graph.inspector.scale", axis=dimension.upper()),
                         ("linear",) if zero else SCALES, SCALE_LABELS)
            row = QWidget()
            pair = QHBoxLayout(row)
            pair.setContentsMargins(0, 0, 0, 0)
            source = dimension + "range"
            for bound in ("min", "max"):
                field = QLineEdit()
                field.textEdited.connect(lambda _text, source=source: self._schedule(source))
                field.editingFinished.connect(lambda source=source: self._now(source))
                pair.addWidget(field)
                self.widgets[dimension + bound] = field
            form.addRow(tr("graph.inspector.range", axis=dimension.upper()), row)
            self._message(form, source)
            hint = QLabel(tr("graph.inspector.automatic" if axis_has_numeric_ticks(self.axes, dimension)
                             else "graph.inspector.categorical"))
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            form.addRow(hint)
        self._finish(form, "axes")

    def _page_section(self):
        form = self._section("page", tr("graph.inspector.page"))
        self._line(form, "title", tr("graph.field.title"))
        self._choice(form, "legend", tr("graph.inspector.legend"), (AUTO, *LEGEND_LOCATIONS),
                     {**AUTO_LABELS, **LEGEND_LABELS})
        grid = QCheckBox(tr("graph.field.major_grid"))
        grid.toggled.connect(lambda _on: self._now("grid"))
        form.addRow(grid)
        self.widgets["grid"] = grid
        self._finish(form, "page")

    # -- loading --------------------------------------------------------------------------------------
    @property
    def current(self):
        index = self.selector.currentIndex()
        return self.elements[index] if 0 <= index < len(self.elements) else None

    def _load(self):
        self._loading = True
        try:
            for key, index in TEXT_FIELDS.items():
                self.widgets[key].setText(str(self.draft.get(key, self.defaults["texts"][index][1])))
            for dimension in ("x", "y"):
                self.widgets[dimension + "scale"].set(
                    self.draft.get(dimension + "scale", self.defaults["axes"][dimension]["scale"]))
                options = self.draft.get("axis", {}).get(dimension, {})
                for bound in ("min", "max"):
                    self.widgets[dimension + bound].setText("" if bound not in options else f"{options[bound]:g}")
            self.widgets["legend"].set(self.draft.get("legend", AUTO))
            default_grid = any(self.defaults["axes"][d]["major_params"].get("gridOn", False) for d in "xy")
            self.widgets["grid"].setChecked(bool(self.draft.get("grid", default_grid)))
            if self.elements:
                keys = [item["key"] for item in self.elements]
                self.selector.setCurrentIndex(keys.index(self._element_key) if self._element_key in keys else 0)
            self._load_element()
        finally:
            self._loading = False
        self._refresh_states()

    def _load_element(self):
        loading, self._loading = self._loading, True
        try:
            item = self.current
            self._element_key = item["key"] if item else None
            bucket = "groups" if item and item["kind"] == "group" else "series"
            options = self.draft.get(bucket, {}).get(item["key"], {}) if item else {}
            series = bool(item) and item["kind"] == "series"
            allowed = item["item"].fields if series else {"color", "visible"}
            for key, field in self.fields.items():
                shown = bool(item) and key in allowed
                widget = getattr(field, "row", field)
                widget.setVisible(shown)
                label = self.data_form.labelForField(widget)
                if label is not None:
                    label.setVisible(shown)
                if key == "visible":
                    field.setChecked(options.get("visible", True))
                    if item and not series:
                        field.setText(tr("graph.inspector.show_kind." + item["item"].kind))
                elif key == "marker":
                    markers = [label for label, code in MARKERS.items()
                               if code != "none" or (item and item["item"].kind in {"line", "errorbar", "xy"})]
                    field.set_values((AUTO, *markers), {**AUTO_LABELS, **MARKER_LABELS})
                    field.set(next((label for label in markers if MARKERS[label] == options.get("marker")), AUTO))
                elif key == "line_style":
                    field.set(options.get(key, AUTO))
                else:
                    field.setText(str(options.get(key, "")))
            for source in [source for source in self.errors if source.startswith("element:")]:
                self._flag(source, None)
        finally:
            self._loading = loading

    def _refresh_states(self):
        for dimension in ("x", "y"):
            numeric = axis_has_numeric_ticks(self.axes, dimension)
            zero = dimension in zero_baseline_axes(self.axes)
            broken = self.draft.get(AXIS_BREAKS, {}).get("axis") == dimension
            for bound in ("min", "max"):
                self.widgets[dimension + bound].setEnabled(numeric and not broken)
            self.widgets[dimension + "scale"].setEnabled(
                numeric and not zero and not broken and not (self._xy and dimension == "y"))
        item = self.current
        if item and item["kind"] == "series":
            series = item["item"]
            active = active_series_fields(self.axes, series)
            for key, field in self.fields.items():
                if key in series.fields:
                    getattr(field, "row", field).setEnabled(key in active)
            if self._xy and hasattr(self, "xy_hint"):
                self.xy_hint.setText(tr("graph.inspector.xy_inactive" if active != series.fields
                                        else "graph.inspector.xy_hint"))

    # -- editing ---------------------------------------------------------------------------------------
    def edit_hierarchical(self):
        from .hierarchical_style import HierarchicalStyleDialog

        self._flush()
        dialog = HierarchicalStyleDialog(self, self.figure, self.draft.get("hierarchical"))
        if dialog.exec() != HierarchicalStyleDialog.DialogCode.Accepted:
            return
        candidate = deepcopy(self.draft)
        if dialog.result:
            candidate["hierarchical"] = dialog.result
        else:
            candidate.pop("hierarchical", None)
        if candidate != self.draft:
            self._preview(candidate)

    def _schedule(self, source):
        if self._loading:
            return
        if source not in self._due:
            self._due.append(source)
        self.timer.start()

    def _now(self, source):
        if self._loading:
            return
        if source in self._due:
            self._due.remove(source)
        if not self._due:
            self.timer.stop()
        self._update(source)

    def _flush(self):
        due, self._due = self._due, []
        self.timer.stop()
        for source in due:
            self._update(source)

    def _update(self, source):
        candidate = deepcopy(self.draft)
        try:
            self._write(candidate, source)
            validate_graph_style(self.axes, candidate)
        except ValueError as error:
            self._flag(source, translate_message(error))
            return
        self._flag(source, None)
        if candidate != self.draft:
            self._preview(candidate)

    def _preview(self, candidate):
        try:
            apply_style(self.figure, candidate)
        except ValueError as error:
            apply_style(self.figure, self.draft)
            self.canvas.draw_idle()
            self.show_status(translate_message(error), error=True)
            return False
        self.draft = candidate
        self.show_status("")
        self.canvas.draw_idle()
        return True

    def show_status(self, text, *, error=False):
        self.status.setObjectName("errorBanner" if error and text else "muted")
        self.status.setText(text)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _flag(self, source, message):
        label = self.messages.get(source)
        if message:
            self.errors[source] = message
            if label is not None:
                label.setText(message)
                label.setVisible(True)
        else:
            self.errors.pop(source, None)
            if label is not None:
                label.setVisible(False)

    def _write(self, style, source):
        if source in TEXT_FIELDS:
            default = self.defaults["texts"][TEXT_FIELDS[source]][1]
            value = self.widgets[source].text()
            if value == default:
                style.pop(source, None)
            else:
                style[source] = value
        elif source in {"xrange", "yrange", "xscale", "yscale"}:
            self._write_axis(style, source[0], source[1:])
        elif source == "legend":
            value = self.widgets["legend"].value()
            if value == AUTO:
                style.pop("legend", None)
            else:
                style["legend"] = value
        elif source == "grid":
            style["grid"] = self.widgets["grid"].isChecked()
        elif source.startswith("element:"):
            self._write_element(style, source[8:])

    def _write_axis(self, style, dimension, part):
        if part == "scale":
            scale = self.widgets[dimension + "scale"].value()
            if scale == self.defaults["axes"][dimension]["scale"]:
                style.pop(dimension + "scale", None)
            else:
                style[dimension + "scale"] = scale
            return
        low, high = (self.widgets[dimension + bound].text().strip() for bound in ("min", "max"))
        if bool(low) != bool(high):
            raise FieldProblem(tr("graph.inspector.both_limits"))
        options = style.setdefault("axis", {}).setdefault(dimension, {})
        if low:
            options["min"] = _number(low, "graph.inspector.enter_minimum")
            options["max"] = _number(high, "graph.inspector.enter_maximum")
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
        widget = self.fields[field]
        if field == "visible":
            if widget.isChecked():
                options.pop("visible", None)
            else:
                options["visible"] = False
        else:
            value = widget.value() if isinstance(widget, Choice) else widget.text().strip()
            if not value or (field in {"marker", "line_style"} and value == AUTO):
                options.pop(field, None)
            elif field == "marker":
                options[field] = MARKERS[value]
            elif field in NUMBER_FIELDS:
                options[field] = _number(value, "graph.inspector.enter_size")
            else:
                options[field] = value
        if not options:
            del style[bucket][item["key"]]
        if not style[bucket]:
            del style[bucket]

    def _select(self):
        if self._loading:
            return
        self._load_element()
        self._refresh_states()

    def select_group(self, key):
        keys = [item["key"] for item in self.elements]
        if key in keys:
            self.selector.setCurrentIndex(keys.index(key))
            return True
        return False

    def _clicked(self, event):
        toolbar = getattr(self.canvas, "toolbar", None)
        if (event.button != 1 or event.inaxes is not self.axes or not self.groups
                or (toolbar is not None and str(getattr(toolbar, "mode", "")))):
            return
        for group in reversed(self.groups):
            if any(artist.get_visible() and artist.contains(event)[0] for artist, _ in group.artists):
                self.select_group(group.key)
                return

    # -- reset, apply, cancel -----------------------------------------------------------------------
    def reset_section(self, name):
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
        self._due = []
        self.timer.stop()
        prefixes = {"data": ("element:",), "axes": ("x", "y"), "page": ("title", "legend", "grid")}[name]
        for source in [source for source in self.errors if source.startswith(prefixes)]:
            self._flag(source, None)
        if candidate != self.draft and not self._preview(candidate):
            return
        self._load()

    @property
    def has_draft(self):
        return bool(self._due or self.errors) or self.draft != (self._confirmed() or {})

    def apply(self):
        self._flush()
        if self.errors:
            self.show_status(tr("graph.inspector.fix_fields"), error=True)
            return False
        try:
            validate_graph_style(self.axes, self.draft)
            apply_style(self.figure, self.draft)
            self._commit(deepcopy(self.draft))
        except ValueError as error:
            self.show_status(translate_message(error), error=True)
            return False
        self.show_status(tr("graph.inspector.applied"))
        self.canvas.draw_idle()
        return True

    def discard(self):
        self._due = []
        self.timer.stop()
        for source in list(self.errors):
            self._flag(source, None)
        self.draft = deepcopy(self._confirmed() or {})
        try:
            apply_style(self.figure, self.draft)
        except ValueError:
            pass
        self.canvas.draw_idle()
        self._load()
        self.show_status("")

    def cancel(self):
        self.discard()
        self._closed()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
            return
        super().keyPressEvent(event)

    def dispose(self):
        """The page is being rebuilt: restore the confirmed style and stop listening to the canvas."""
        self.timer.stop()
        try:
            self.canvas.mpl_disconnect(self._click)
        except (AttributeError, ValueError):
            pass
        if self.figure.axes:
            try:
                apply_style(self.figure, deepcopy(self._confirmed() or {}))
            except ValueError:
                pass
