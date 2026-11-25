"""Labels of the observations in the Graph Inspector: choose where the text of each point comes from.

The editor lives in the Inspector's own contract (``trama_qt.inspector``): it edits the draft style, the graph
previews every valid change with ``apply_style``, Apply stores the draft once and Cancel puts the confirmed style
back. The engine, the text rules, the limit and the identity of an observation are in ``analisi.observation_labels``
(and ``analisi.point_style``).

A series gets labels by choosing a source: the row titles or a column of the worksheet. Its look (color, position,
size, how many) belongs to the series. One observation can be shown or hidden on purpose: the observation is the one
selected in the "Single point" section (a click on the graph or the list there), so there is a single way to choose a
point. An observation setting that cannot be drawn stays in the list with its reason and can always be reset.
"""
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QWidget)

from analisi.i18n import tr
from analisi.observation_labels import (DEFAULT_LIMIT, LABELS, MAX_LIMIT, POSITIONS, ROW_TITLE, find_series_record,
                                        label_statuses, override_of, reason_text, resolve_origin, source_choices,
                                        text_at, with_override, with_series, without_override)
from analisi.point_style import PointStatus, point_map, support_reason

from . import theme
from .graph_format import Choice, _color_button

NONE = 0  # The first entry of the source list: no labels for this series.
MISSING = -1  # The recorded source is no longer in the worksheet: it stays on offer until another is chosen.
UNSUPPORTED = "unsupported"
POSITION_LABELS = {name: "label.position." + name for name in POSITIONS}
FOLLOW, SHOW, HIDE = "follow", "show", "hide"
MODE_LABELS = {FOLLOW: "label.point_follow", SHOW: "label.point_show", HIDE: "label.point_hide"}
LIST_ROWS = 4
SOURCE = "label"
OBSERVATION = "label:point"


def _muted(text=""):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class LabelEditor:
    """The "Data labels" section of the Inspector."""

    def __init__(self, host):
        self.host = host
        self.series = None
        self.choices = []  # (origin, caption) of the source entries, after the "No labels" one
        self.loading = False
        form = host._section("labels", tr("label.section"))
        self.form = form
        form.addRow(_muted(tr("label.hint")))
        self.reason = QLabel()
        self.reason.setObjectName("errorBanner")
        self.reason.setWordWrap(True)
        self.reason.setVisible(False)
        form.addRow(self.reason)

        self.source = QComboBox()
        self.source.setAccessibleName(tr("label.source"))
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source.setMinimumContentsLength(12)  # A long column name must never widen the panel.
        self.source.currentIndexChanged.connect(lambda _i: self._edited(SOURCE))
        form.addRow(tr("label.source"), self.source)

        self.show = QCheckBox(tr("label.show"))
        self.show.toggled.connect(lambda _on: self._edited(SOURCE))
        form.addRow(self.show)

        self.color = QLineEdit()
        # A color such as "#aa2288" must be readable whole at any display scale.
        self.color.setMinimumWidth(self.color.fontMetrics().horizontalAdvance("#aa2288") + 28)
        self.color.textEdited.connect(lambda _text: self._typed(SOURCE))
        self.color.editingFinished.connect(lambda: self._edited(SOURCE))
        self.color.row = QWidget()
        line = QHBoxLayout(self.color.row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.color, 1)
        pick = _color_button(self.color)
        pick.clicked.connect(lambda _=False: self._edited(SOURCE))
        line.addWidget(pick)
        form.addRow(tr("label.color"), self.color.row)

        self.position = Choice(POSITIONS, POSITION_LABELS)
        self.position.currentIndexChanged.connect(lambda _i: self._edited(SOURCE))
        form.addRow(tr("label.position"), self.position)
        self.size = QLineEdit()
        self.size.textEdited.connect(lambda _text: self._typed(SOURCE))
        self.size.editingFinished.connect(lambda: self._edited(SOURCE))
        form.addRow(tr("label.size"), self.size)
        self.limit = QLineEdit()
        self.limit.setPlaceholderText(str(DEFAULT_LIMIT))
        self.limit.textEdited.connect(lambda _text: self._typed(SOURCE))
        self.limit.editingFinished.connect(lambda: self._edited(SOURCE))
        form.addRow(tr("label.limit"), self.limit)
        host._message(form, SOURCE)
        host.messages[OBSERVATION] = host.messages[SOURCE]
        self.summary = _muted()
        form.addRow(self.summary)

        title = QLabel(tr("label.point"))
        title.setObjectName("sectionTitle")
        form.addRow(title)
        self.point_info = _muted(tr("label.point_none"))
        form.addRow(self.point_info)
        self.mode = Choice((FOLLOW, SHOW, HIDE), MODE_LABELS)
        self.mode.setAccessibleName(tr("label.point"))
        self.mode.currentIndexChanged.connect(lambda _i: self._edited(OBSERVATION))
        form.addRow(self.mode)

        title = QLabel(tr("label.observations"))
        title.setObjectName("sectionTitle")
        form.addRow(title)
        self.listing = QListWidget()
        self.listing.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.listing.setMinimumWidth(0)
        self.listing.setFixedHeight(self.listing.fontMetrics().height() * LIST_ROWS + 14)
        self.listing.setAccessibleName(tr("label.observations"))
        self.listing.currentRowChanged.connect(self._listed)
        self.listing.itemDoubleClicked.connect(lambda _item: self._goto())
        form.addRow(self.listing)
        self.reset_selected_button = QPushButton(theme.icon("undo-2", None, 16), tr("label.reset_selected"))
        self.reset_selected_button.clicked.connect(self.reset_selected)
        form.addRow(self.reset_selected_button)
        host._finish(form, "labels")
        self._enable()

    # -- state ---------------------------------------------------------------------------------------------
    @property
    def figure(self):
        return self.host.figure

    def _records(self):
        return list(self.host.draft.get(LABELS) or [])

    def _statuses(self):
        return label_statuses(self.figure)

    def _series_items(self):
        return [element["item"] for element in self.host.elements if element["kind"] == "series"]

    def _name(self, key):
        for element in self.host.elements:
            if element["kind"] == "series" and element["item"].key == key:
                return element["name"]
        return key.split(":", 2)[-1]

    def _reason(self, series):
        """Why ``series`` cannot show labels (a reason code), or None. Does not look at the style."""
        if series is None or series.kind not in {"scatter", "xy"}:
            return UNSUPPORTED
        reason = support_reason(series, self.figure)
        if reason is None and (point_map(series.artist) is None or point_map(series.artist).data is None):
            return "no_data"
        return reason

    def _reason_text(self, reason):
        return tr("label.reason." + reason, row=None, series="", column="")

    def _supported(self):
        return self.series is not None and self._reason(self.series) is None

    def _position(self):
        """The position of the record of the selected series in the draft, or None."""
        return find_series_record(self._records(), self.series.key) if self.series is not None else None

    def _record(self):
        position = self._position()
        return self._records()[position] if position is not None else None

    def _status(self):
        position = self._position()
        statuses = self._statuses()
        return statuses[position] if position is not None and position < len(statuses) else None

    def _selected(self):
        """The vertex selected in "Single point" when it belongs to the series shown here, else None."""
        points = getattr(self.host, "points", None)
        if points is None or points.series is not self.series or self.series is None:
            return None
        return points.vertex

    def _enable(self):
        supported = self._supported()
        record = supported and self._position() is not None
        self.source.setEnabled(supported)
        for widget in (self.show, self.color.row, self.position, self.size, self.limit):
            widget.setEnabled(record)
        self.mode.setEnabled(record and self._selected() is not None)
        self.listing.setEnabled(bool(self._flat()))
        self.reset_selected_button.setEnabled(self.listing.currentRow() >= 0)
        reason = None
        if not self._series_items():  # A box plot, a bar chart of groups, an empty graph.
            reason = UNSUPPORTED
        elif not supported:
            reason = self._reason(self.series)
        self.reason.setVisible(reason is not None)
        self.reason.setText(self._reason_text(reason) if reason else "")

    # -- loading -------------------------------------------------------------------------------------------
    def series_changed(self):
        """The Inspector selected another element, or reloaded: the sources and the fields follow it."""
        item = self.host.current
        self.series = item["item"] if item and item["kind"] == "series" else None
        self.loading = True
        try:
            self._fill_sources()
            self._load_fields()
            self._fill_listing()
            self._load_selection()
        finally:
            self.loading = False
        self._enable()

    def refresh(self):
        """A preview changed the style: the summary, the list and the selected observation follow.

        The fields are not rewritten: the user may be typing in one of them.
        """
        self.loading = True
        try:
            self._load_summary()
            self._fill_listing()
            self._load_selection()
        finally:
            self.loading = False
        self._enable()

    def selection_changed(self):
        """The point chosen in "Single point" changed."""
        self.loading = True
        try:
            self._load_selection()
        finally:
            self.loading = False
        self._enable()

    def _frame(self):
        pmap = point_map(self.series.artist) if self.series is not None else None
        return pmap.data if pmap is not None else None

    def _fill_sources(self):
        """The entries of the source list: no labels, the row titles and every column; a source that is gone too."""
        self.source.blockSignals(True)
        self.source.clear()
        self.choices = []
        self.source.addItem(tr("label.none"), NONE)
        frame = self._frame() if self._supported() else None
        if frame is not None:
            self.choices = source_choices(frame)
            for number, (origin, caption) in enumerate(self.choices, start=1):
                self.source.addItem(tr("label.row_title") if origin["kind"] == ROW_TITLE else caption, number)
        record = self._record()
        current = NONE
        if record is not None and frame is not None:
            current = self._entry_of(record["from"], frame)
            if current == MISSING:
                name = record["from"].get("name", "")
                self.source.addItem(tr("label.missing_item", name=name), MISSING)
        self.source.setCurrentIndex(max(0, self.source.findData(current)))
        self.source.blockSignals(False)

    def _entry_of(self, origin, frame):
        """The data of the source entry that reads what ``origin`` reads, or MISSING."""
        name, reason = resolve_origin(origin, frame)
        if reason:
            return MISSING
        for number, (choice, _caption) in enumerate(self.choices, start=1):
            if choice["kind"] == origin["kind"] and (origin["kind"] == ROW_TITLE or choice["name"] == str(name)):
                return number
        return MISSING

    def _load_fields(self):
        record = self._record() or {}
        self.show.setChecked(record.get("show", True))
        self.color.setText(record.get("color", ""))
        self.position.set(record.get("position", POSITIONS[0]))
        self.size.setText("" if "size" not in record else f"{record['size']:g}")
        self.limit.setText("" if "limit" not in record else str(record["limit"]))
        self._load_summary()

    def _load_summary(self):
        record, status = self._record(), self._status()
        if record is None or status is None:
            self.summary.setText("")
            return
        self.summary.setObjectName("muted")
        if status.state == "suspended":
            self.summary.setText(reason_text(status, record))
        elif status.omitted:
            self.summary.setText(tr("label.omitted", shown=status.shown, total=status.candidates,
                                    omitted=status.omitted, limit=status.limit))
        elif status.shown:
            self.summary.setText(tr("label.shown", shown=status.shown))
        else:
            self.summary.setText(tr("label.nothing"))

    def _load_selection(self):
        """The selected observation: what its label says and whether it was set on purpose."""
        self.mode.blockSignals(True)
        vertex, record, status = self._selected(), self._record(), self._status()
        mode, text = FOLLOW, tr("label.point_none")
        if vertex is not None and record is None:
            text = tr("label.point_first")
        elif vertex is not None and record is not None:
            pmap = point_map(self.series.artist)
            row = int(pmap.rows[vertex])
            label = text_at(self.series, record, vertex)
            text = tr("label.point_text", row=row, text=label) if label else tr("label.point_empty", row=row)
            forced = override_of(record, status, vertex)
            mode = FOLLOW if forced is None else SHOW if forced else HIDE
        self.point_info.setText(text)
        self.mode.set(mode)
        self.mode.blockSignals(False)

    def _flat(self):
        """``[(record position, override position)]`` of every observation setting of the draft."""
        return [(number, position) for number, record in enumerate(self._records())
                for position in range(len(record.get("observations", ())))]

    def _fill_listing(self):
        records, statuses = self._records(), self._statuses()
        keep = self.listing.currentRow()
        self.listing.blockSignals(True)
        self.listing.clear()
        for number, position in self._flat():
            record = records[number]
            item_record = record["observations"][position]
            point = None
            if number < len(statuses) and position < len(statuses[number].observations):
                point = statuses[number].observations[position]
            state = tr("label.state.show" if item_record["show"] else "label.state.hide")
            item = QListWidgetItem(tr("label.observation_item", row=item_record["source"]["row"],
                                      series=self._name(record["series"]), state=state))
            item.setData(Qt.ItemDataRole.UserRole, (number, position))
            item.setToolTip(item.text())
            if point is None:
                point = PointStatus("suspended", None, "no_series", item_record["source"]["row"])
            if not point.ok:
                item.setIcon(theme.icon("triangle-alert", "error" if point.state == "suspended" else "text2", 14))
                item.setToolTip(item.text() + "\n" + reason_text(point, record))
            self.listing.addItem(item)
        if 0 <= keep < self.listing.count():
            self.listing.setCurrentRow(keep)
        self.listing.blockSignals(False)

    # -- editing -------------------------------------------------------------------------------------------
    def _typed(self, source):
        if not self.loading:
            self.host._schedule(source)

    def _edited(self, source):
        if not self.loading:
            self.host._now(source)

    def write(self, style, source=SOURCE):
        """Write the fields of the selected series (or of its selected observation) into the candidate ``style``."""
        if not self._supported():
            return
        if source == OBSERVATION:
            self._write_observation(style)
        else:
            self._write_series(style)

    def _store(self, style, records):
        if records:
            style[LABELS] = records
        else:
            style.pop(LABELS, None)

    def _write_series(self, style):
        from .inspector import FieldProblem, _number

        records = list(style.get(LABELS) or [])
        entry = self.source.currentData()
        if entry == NONE:
            self._store(style, with_series(records, self.series.key, **{"from": None}))
            return
        origin = self._origin(entry, records)
        size, limit = self.size.text().strip(), self.limit.text().strip()
        number = None
        if limit:
            number = _number(limit, "label.error.limit")
            if number != int(number) or not 1 <= number <= MAX_LIMIT:
                raise FieldProblem(tr("label.error.limit", high=MAX_LIMIT))
        fields = {"from": origin, "show": None if self.show.isChecked() else False,
                  "color": self.color.text().strip() or None, "position": self.position.value(),
                  "size": _number(size, "graph.inspector.enter_size") if size else None,
                  "limit": None if number is None else int(number)}
        self._store(style, with_series(records, self.series.key, **fields))

    def _origin(self, entry, records):
        """The source record of an entry of the list; the one a record already has when its column is gone."""
        if entry == MISSING:
            position = find_series_record(records, self.series.key)
            return dict(records[position]["from"]) if position is not None else None
        return dict(self.choices[entry - 1][0])

    def _write_observation(self, style):
        vertex = self._selected()
        records = list(style.get(LABELS) or [])
        if vertex is None or find_series_record(records, self.series.key) is None:
            return
        mode = self.mode.value()
        self._store(style, with_override(records, self._status(), self.series.key, point_map(self.series.artist),
                                         vertex, None if mode == FOLLOW else mode == SHOW))

    def reset_selected(self):
        """Remove the setting chosen in the list of observations, whatever its state."""
        self.host._flush()
        row = self.listing.currentRow()
        flat = self._flat()
        if not 0 <= row < len(flat):
            return
        number, position = flat[row]
        candidate = deepcopy(self.host.draft)
        records = list(candidate.get(LABELS) or [])
        self._store(candidate, without_override(records, records[number]["series"], position))
        self.host._flag(OBSERVATION, None)
        if self.host._preview(candidate):  # refresh() runs with every successful preview
            self.listing.setCurrentRow(-1)
            self._enable()

    def _listed(self, row):
        if self.loading:
            return
        self._enable()
        flat, statuses = self._flat(), self._statuses()
        if 0 <= row < len(flat):
            number, position = flat[row]
            if number < len(statuses) and position < len(statuses[number].observations):
                point = statuses[number].observations[position]
                if not point.ok:
                    self.host.show_status(reason_text(point, self._records()[number]),
                                          error=point.state == "suspended")
                    return
        self.host.show_status("")

    def _goto(self):
        row = self.listing.currentRow()
        flat, statuses = self._flat(), self._statuses()
        if not 0 <= row < len(flat):
            return
        number, position = flat[row]
        if number >= len(statuses) or position >= len(statuses[number].observations):
            return
        point = statuses[number].observations[position]
        series = next((item for item in self._series_items() if item.key == self._records()[number]["series"]), None)
        if point.ok and series is not None:
            self.host.points.select(series, point.index)
