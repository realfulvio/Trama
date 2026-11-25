"""Formatting of single points in the Graph Inspector: pick an observation, give it a color, symbol or size.

The editor lives in the Inspector's own contract (``trama_qt.inspector``): it edits the draft style, the
graph previews every valid change with ``apply_style``, Apply stores the draft once and Cancel puts the confirmed
style back. The engine and the identity of a point are in ``analisi.point_style``.

A point is chosen on the graph (a click picks the nearest observation, and when several are within reach every
one of them is offered) or from the list of the observations of the selected series. The selection is marked with
a ring that is drawn on screen only. A point style that cannot be drawn stays in the list of formatted points
with its reason and can always be reset, whatever the state of the graph.
"""
from copy import deepcopy

import numpy as np
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
                               QPushButton, QWidget)

from analisi.i18n import tr
from analisi.point_style import (POINTS, PointStatus, clear_indicator, describe_point, drawn_vertices, find_record,
                                 nearest_points, point_map, point_statuses, reason_text, series_defaults,
                                 show_indicator, support_reason, with_point, without_record)
from analisi.presentation import MARKERS

from . import theme
from .graph_format import MARKER_LABELS, Choice, _color_button

INHERIT = "As series"
INHERIT_LABELS = {INHERIT: "point.inherit"}
MARKER_NAMES = {code: name for name, code in MARKERS.items() if code != "none"}
LIST_ROWS = 5
MAX_NEAR = 12  # Offered together when several observations are within reach of a click.
PICK_RADIUS = 9  # Logical pixels around a click.
UNSUPPORTED = "unsupported"


def _marker_text(code):
    name = MARKER_NAMES.get(code)
    return tr(MARKER_LABELS[name]) if name in MARKER_LABELS else str(code)


class ObservationModel(QAbstractListModel):
    """The drawn observations of one series, read on demand: ten thousand rows cost nothing to build."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series, self.vertices, self.styled = None, np.zeros(0, dtype=int), set()

    def reset(self, series, vertices, styled):
        self.beginResetModel()
        self.series, self.vertices, self.styled = series, np.asarray(vertices, dtype=int), set(styled)
        self.endResetModel()

    def set_styled(self, styled):
        styled = set(styled)
        if styled != self.styled:
            changed = self.styled ^ styled
            self.styled = styled
            for vertex in changed:
                row = self.row_of(vertex)
                if row >= 0:
                    self.dataChanged.emit(self.index(row), self.index(row))

    def rowCount(self, parent=QModelIndex()):  # noqa: B008 - Qt signature
        return 0 if parent.isValid() else len(self.vertices)

    def vertex(self, row):
        return int(self.vertices[row])

    def row_of(self, vertex):
        """The list row of a vertex (the vertices are in worksheet order), or -1."""
        row = int(np.searchsorted(self.vertices, vertex))
        return row if row < len(self.vertices) and int(self.vertices[row]) == vertex else -1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.series is None or role not in (Qt.ItemDataRole.DisplayRole,
                                                                       Qt.ItemDataRole.ToolTipRole):
            return None
        vertex = int(self.vertices[index.row()])
        text = describe_point(point_map(self.series.artist), vertex)
        return ("● " if vertex in self.styled else "") + text


class PointEditor:
    """The "Single point" section of the Inspector."""

    def __init__(self, host):
        self.host = host
        self.series = None
        self.vertex = None
        self.candidates = []
        self.loading = False
        self.model = ObservationModel()
        form = host._section("points", tr("point.section"))
        self.form = form
        form.addRow(self._muted(tr("point.hint")))
        self.reason = QLabel()
        self.reason.setObjectName("infoBanner")
        self.reason.setWordWrap(True)
        self.reason.setVisible(False)
        form.addRow(self.reason)

        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setUniformItemSizes(True)
        self.view.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._compact(self.view)
        self.view.setFixedHeight(self.view.fontMetrics().height() * LIST_ROWS + 14)
        self.view.setAccessibleName(tr("point.list"))
        self.view.selectionModel().currentChanged.connect(self._list_changed)
        form.addRow(tr("point.list"), self.view)

        self.near_label = self._muted("")
        self.near = QComboBox()
        self.near.setAccessibleName(tr("point.overlap_name"))
        self.near.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.near.setMinimumContentsLength(12)  # A long entry must never widen the panel.
        self.near.currentIndexChanged.connect(self._near_chosen)
        form.addRow(self.near_label)
        form.addRow(self.near)
        self.near.setVisible(False)
        self.near_label.setVisible(False)
        self.info = self._muted(tr("point.none_selected"))
        form.addRow(self.info)

        self.color = QLineEdit()
        self.color.textEdited.connect(lambda _text: host._schedule("point"))
        self.color.editingFinished.connect(lambda: host._now("point"))
        self.color.row = QWidget()
        line = QHBoxLayout(self.color.row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.color, 1)
        pick = _color_button(self.color)
        pick.clicked.connect(lambda _=False: host._now("point"))
        line.addWidget(pick)
        form.addRow(tr("graph.inspector.color"), self.color.row)
        self.marker = Choice((INHERIT, *MARKER_NAMES.values()), {**INHERIT_LABELS, **MARKER_LABELS})
        self.marker.currentIndexChanged.connect(lambda _i: host._now("point"))
        form.addRow(tr("graph.inspector.marker"), self.marker)
        self.size = QLineEdit()
        self.size.textEdited.connect(lambda _text: host._schedule("point"))
        self.size.editingFinished.connect(lambda: host._now("point"))
        form.addRow(tr("graph.inspector.marker_size"), self.size)
        host._message(form, "point")
        self.reset_point_button = QPushButton(theme.icon("undo-2", None, 16), tr("point.reset"))
        self.reset_point_button.clicked.connect(self.reset_point)
        form.addRow(self.reset_point_button)

        title = QLabel(tr("point.styled"))
        title.setObjectName("sectionTitle")
        form.addRow(title)
        self.styled = QListWidget()
        self._compact(self.styled)
        self.styled.setFixedHeight(self.styled.fontMetrics().height() * 4 + 14)
        self.styled.setAccessibleName(tr("point.styled"))
        self.styled.currentRowChanged.connect(self._styled_changed)
        self.styled.itemDoubleClicked.connect(lambda _item: self._goto_styled())
        form.addRow(self.styled)
        self.reset_selected_button = QPushButton(theme.icon("undo-2", None, 16), tr("point.reset_selected"))
        self.reset_selected_button.clicked.connect(self.reset_selected)
        form.addRow(self.reset_selected_button)
        host._finish(form, "points")
        self._enable()

    @staticmethod
    def _compact(view):
        """A list inside the 330 px panel: long rows are cut with an ellipsis, never scrolled sideways."""
        view.setTextElideMode(Qt.TextElideMode.ElideRight)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setMinimumWidth(0)

    @staticmethod
    def _muted(text):
        label = QLabel(text)
        label.setObjectName("muted")
        label.setWordWrap(True)
        return label

    # -- state ---------------------------------------------------------------------------------------------
    @property
    def figure(self):
        return self.host.figure

    def _records(self):
        return list(self.host.draft.get(POINTS) or [])

    def _statuses(self):
        return point_statuses(self.figure)

    def _series_items(self):
        return [element["item"] for element in self.host.elements if element["kind"] == "series"]

    def _reason(self, series):
        """Why ``series`` cannot be formatted point by point (a reason code), or None."""
        if series is None or series.kind not in {"scatter", "xy"}:
            return UNSUPPORTED
        return support_reason(series, self.figure)

    def _reason_text(self, reason):
        return tr("point.error.series") if reason == UNSUPPORTED else reason_text(PointStatus("suspended", None, reason))

    def _supported(self):
        return self.series is not None and self._reason(self.series) is None

    def _styled_vertices(self):
        key = self.series.key if self.series is not None else None
        return {status.index for record, status in zip(self._records(), self._statuses(), strict=False)
                if record["series"] == key and status.ok}

    def _record_position(self):
        if not self._supported() or self.vertex is None:
            return None
        return find_record(self._records(), self._statuses(), self.series.key, self.vertex)

    def _enable(self):
        supported = self._supported()
        selected = supported and self.vertex is not None
        self.view.setEnabled(supported)
        self.color.row.setEnabled(selected)
        self.marker.setEnabled(selected)
        self.size.setEnabled(selected and "marker_size" in self.series.fields)
        self.reset_point_button.setEnabled(self._record_position() is not None)
        self.styled.setEnabled(bool(self._records()))
        self.reset_selected_button.setEnabled(self.styled.currentRow() >= 0)
        reason = None
        if not self._series_items():  # A box plot, a bar chart of groups, an empty graph.
            reason = UNSUPPORTED
        elif not supported:
            reason = self._reason(self.series)
        self.reason.setVisible(reason is not None)
        self.reason.setText(self._reason_text(reason) if reason else "")

    # -- loading -------------------------------------------------------------------------------------------
    def series_changed(self, keep=False):
        """The Inspector selected another element: its observations replace the list.

        Nothing stays selected, unless ``keep`` asks to hold the selection of the same series (the panel reloaded
        a section, not the element).
        """
        item = self.host.current
        series = item["item"] if item and item["kind"] == "series" else None
        held = self.vertex if keep and series is self.series else None
        self.series = series
        self.vertex = None
        self.candidates = []
        clear_indicator(self.figure)
        vertices = drawn_vertices(series.artist) if self._supported() else []
        self.loading = True
        try:
            self.model.reset(series, vertices, self._styled_vertices())
            self._load_fields()
            self._fill_styled()
            self._fill_near()
        finally:
            self.loading = False
        self._enable()
        self._notify()
        if held is not None and self.model.row_of(held) >= 0:
            self.select(series, held)
        self.host.canvas.draw_idle()

    def refresh(self):
        """A preview changed the style: the marks of the list, the formatted points and the ring follow.

        The fields are not rewritten: the user may be typing in one of them.
        """
        self.loading = True
        try:
            self.model.set_styled(self._styled_vertices())
            self._load_placeholders()
            self._fill_styled()
        finally:
            self.loading = False
        self._show_ring()
        self._enable()

    def _load_placeholders(self):
        defaults = ("#2866ae", "o", 6.0)
        if self._supported():
            defaults = series_defaults(self.series, self.host.draft)
        self.color.setPlaceholderText(defaults[0])
        self.size.setPlaceholderText(f"{defaults[2]:g}")

    def _load_fields(self):
        """The fields show what the selected point has now; a blank field means "as the series"."""
        self._load_placeholders()
        position = self._record_position()
        record = self._records()[position] if position is not None else {}
        self.color.setText(record.get("color", ""))
        self.marker.set(MARKER_NAMES.get(record.get("marker"), INHERIT))
        self.size.setText("" if "marker_size" not in record else f"{record['marker_size']:g}")
        if self.vertex is None or not self._supported():
            self.info.setText(tr("point.none_selected"))
            return
        pmap = point_map(self.series.artist)
        self.info.setText(tr("point.selected", series=self._name(self.series), row=int(pmap.rows[self.vertex]),
                             x=f"{pmap.x[self.vertex]:.6g}", y=f"{pmap.y[self.vertex]:.6g}"))

    def _name(self, series):
        for element in self.host.elements:
            if element["item"] is series:
                return element["name"]
        return series.name

    def _fill_styled(self):
        records, statuses = self._records(), self._statuses()
        keep = self.styled.currentRow()
        self.styled.blockSignals(True)
        self.styled.clear()
        for number, record in enumerate(records):
            status = (statuses[number] if number < len(statuses)
                      else PointStatus("suspended", None, "no_series", record["source"]["row"]))
            item = QListWidgetItem(self._styled_text(record))
            item.setToolTip(item.text())
            if not status.ok:
                item.setIcon(theme.icon("triangle-alert", "error" if status.state == "suspended" else "text2", 14))
                item.setToolTip(item.text() + "\n" + reason_text(status, record))
            self.styled.addItem(item)
        if 0 <= keep < self.styled.count():
            self.styled.setCurrentRow(keep)
        self.styled.blockSignals(False)

    def _styled_text(self, record):
        series = next((item for item in self._series_items() if item.key == record["series"]), None)
        name = self._name(series) if series is not None else record["series"].split(":", 2)[-1]
        look = ", ".join(part for part in (record.get("color"),
                                           _marker_text(record["marker"]) if "marker" in record else None,
                                           f"{record['marker_size']:g} pt" if "marker_size" in record else None)
                         if part)
        return tr("point.styled_item", row=record["source"]["row"], series=name, look=look)

    # -- selection -----------------------------------------------------------------------------------------
    def select(self, series, vertex, *, scroll=True):
        """Select ``vertex`` of ``series``: the element, the list, the fields and the ring follow."""
        if series is not self.series:
            for number, element in enumerate(self.host.elements):
                if element["item"] is series:
                    self.host.selector.setCurrentIndex(number)  # The Inspector calls series_changed().
                    break
            if series is not self.series:
                return
        self.vertex = vertex
        self.loading = True
        try:
            row = self.model.row_of(vertex) if vertex is not None else -1
            if row >= 0:
                index = self.model.index(row)
                self.view.setCurrentIndex(index)
                if scroll:
                    self.view.scrollTo(index, QListView.ScrollHint.PositionAtCenter)
            else:
                self.view.setCurrentIndex(QModelIndex())
            self._load_fields()
        finally:
            self.loading = False
        self._show_ring()
        self.host._flag("point", None)
        self._enable()
        self._notify()
        self.host.canvas.draw_idle()

    def _notify(self):
        """The labels of the observations follow the selected point (they are edited in their own section)."""
        labels = getattr(self.host, "labels", None)
        if labels is not None:
            labels.selection_changed()

    def _show_ring(self):
        """The temporary ring around the selected point. It is never part of a save, export or layout."""
        if self.vertex is None or not self._supported() or not self.series.artist.get_visible():
            clear_indicator(self.figure)
            return
        position = self._record_position()
        size = self._records()[position].get("marker_size") if position is not None else None
        show_indicator(self.series, self.vertex, size if size is not None else series_defaults(self.series,
                                                                                                self.host.draft)[2])

    def _list_changed(self, current, _previous):
        if self.loading or not current.isValid() or self.series is None:
            return
        self.candidates = []
        self._fill_near()
        self.select(self.series, self.model.vertex(current.row()), scroll=False)

    def _fill_near(self, current=0):
        self.near.blockSignals(True)
        self.near.clear()
        found = self.candidates
        shown = len(found) > 1
        if shown:
            for series, vertex in found:
                self.near.addItem(f"{self._name(series)} · {describe_point(point_map(series.artist), vertex)}",
                                  (series, vertex))
            self.near.setCurrentIndex(current)
            self.near_label.setText(tr("point.overlap", count=len(found)))
        self.near.blockSignals(False)
        self.near.setVisible(shown)
        self.near_label.setVisible(shown)

    def _near_chosen(self, index):
        if self.loading or index < 0:
            return
        series, vertex = self.near.itemData(index)
        found = list(self.candidates)
        self.select(series, vertex)
        self.candidates = found  # The same choices stay on offer.
        self._fill_near(index)

    def click(self, event):
        """A click on the graph: choose the nearest observation. Returns True when a point was picked."""
        if event.x is None or event.y is None:
            return False
        ratio = getattr(self.host.canvas, "device_pixel_ratio", 1) or 1
        found = []
        for series in self._series_items():
            if self._reason(series) is not None:
                continue
            for vertex, distance in nearest_points(series, event.x, event.y, PICK_RADIUS * ratio):
                found.append((distance, series, vertex))
        if not found:
            return False
        found.sort(key=lambda item: item[0])
        found = found[:MAX_NEAR]
        _, series, vertex = found[0]
        self.select(series, vertex)
        self.candidates = [(item, number) for _, item, number in found]
        self._fill_near()
        return True

    # -- editing -------------------------------------------------------------------------------------------
    def write(self, style):
        """Write the fields of the selected point into the candidate ``style``."""
        if not self._supported() or self.vertex is None:
            return
        from .inspector import _number

        name = self.marker.value()
        size = self.size.text().strip()
        fields = {"color": self.color.text().strip() or None,
                  "marker": None if name == INHERIT else MARKERS[name],
                  "marker_size": _number(size, "graph.inspector.enter_size") if size else None}
        updated = with_point(style.get(POINTS) or [], self._statuses(), self.series.key,
                             point_map(self.series.artist), self.vertex, **fields)
        if updated:
            style[POINTS] = updated
        else:
            style.pop(POINTS, None)

    def reset_point(self):
        """Back to the series look for the selected observation."""
        self.host._flush()
        position = self._record_position()
        if position is not None and self._remove(position):
            self._load_fields()

    def reset_selected(self):
        """Remove the style of the record chosen in the list of formatted points, whatever its state."""
        self.host._flush()
        row = self.styled.currentRow()
        if 0 <= row < len(self._records()) and self._remove(row):
            self.styled.setCurrentRow(-1)
            self._load_fields()
            self._enable()

    def _remove(self, position):
        host = self.host
        candidate = deepcopy(host.draft)
        remaining = without_record(candidate.get(POINTS) or [], position)
        if remaining:
            candidate[POINTS] = remaining
        else:
            candidate.pop(POINTS, None)
        host._flag("point", None)
        return host._preview(candidate)  # refresh() runs with every successful preview

    def _styled_changed(self, row):
        if self.loading:
            return
        self._enable()
        records, statuses = self._records(), self._statuses()
        if 0 <= row < len(records) and row < len(statuses) and not statuses[row].ok:
            self.host.show_status(reason_text(statuses[row], records[row]), error=statuses[row].state == "suspended")
        else:
            self.host.show_status("")

    def _goto_styled(self):
        row = self.styled.currentRow()
        records, statuses = self._records(), self._statuses()
        if not 0 <= row < len(records) or row >= len(statuses) or not statuses[row].ok:
            return
        series = next((item for item in self._series_items() if item.key == records[row]["series"]), None)
        if series is not None:
            self.select(series, statuses[row].index)

    def dispose(self):
        clear_indicator(self.figure)
