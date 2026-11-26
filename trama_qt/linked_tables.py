"""Insert → Linked table…: a table of worksheet or result cells drawn on a graph or on a layout page (Qt).

``LinkedTablesDialog`` lists the tables of one graph or layout and adds, edits and removes them;
``LinkedTableDialog`` makes one: the source, the rectangle (picked on a preview of the source or typed), Linked
or Copy, headers, orientation, font, grid and position, with a preview of the table as it will be drawn. The
records are the ones of ``analisi.linked_tables``; nothing here reads a cell beyond the preview of the source and
the rectangle that is chosen, and a rectangle over the limit is refused before any cell is read.
"""
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from analisi import linked_tables as lt
from analisi.i18n import tr, translate_message

from . import theme

PREVIEW_ROWS, PREVIEW_COLUMNS = 200, 40
HEADERS_LABEL = {value: f"linked_table.headers.{value}" for value in lt.HEADERS}
ORIENTATION_LABEL = {value: f"linked_table.orientation.{value}" for value in lt.ORIENTATIONS}


def preview_pixmap(spec, dpi=110):
    """The table of ``spec`` as it is drawn on a figure, on a white card."""
    width, height = lt.table_size(spec)
    pad = .08
    figure = Figure(figsize=(width + 2 * pad, height + 2 * pad), dpi=dpi, facecolor="#ffffff")
    record = {**spec.record, "position": [pad / (width + 2 * pad), pad / (height + 2 * pad)]}
    lt.draw_tables(figure, [lt.TableSpec(record, spec.resolved)])
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    pixels, (w, h) = bytes(canvas.buffer_rgba()), canvas.get_width_height()
    return QPixmap.fromImage(QImage(pixels, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy())


def choice_caption(choice):
    key = "linked_table.source.sheet" if choice["kind"] == "sheet" else "linked_table.source.result"
    return tr(key, name=choice["label"])


def same_source(choice, record):
    """Whether the source ``choice`` of the project is the one a linked record reads."""
    source = record.get("source")
    if source is None or source["kind"] != choice["kind"]:
        return False
    if choice["kind"] == "sheet":
        return source["sheet"] == choice["sheet"]
    return source["analysis"] == choice["analysis"] and source["table"] == choice["table"]


class LinkedTableDialog(QDialog):
    """One linked table. ``result`` is its record after OK; ``target`` the place chosen when ``targets`` is given.

    Editing a record keeps its source and range unless "Choose the source and range again" is ticked: a table
    whose source has gone can still be moved, restyled or turned into a different range of another source."""

    def __init__(self, parent, project, record=None, *, preset=None, targets=None):
        super().__init__(parent)
        self.project, self.record, self.result, self.target = project, record, None, None
        self.setWindowTitle(tr("linked_table.dialog.edit" if record is not None else "linked_table.dialog.add"))
        self.choices = project.table_source_choices()
        self._syncing = False
        outer = theme.scroll_body(self)
        form = QFormLayout()
        outer.addLayout(form)
        self.place, self.targets = None, [reference for _, reference in targets or ()]
        if targets:
            self.place = QComboBox()
            for index, (caption, _) in enumerate(targets):  # The item data is the index: Qt turns a tuple into a list.
                self.place.addItem(caption, index)
            form.addRow(tr("linked_table.place"), self.place)
        self.replace = None
        self.kept = QLabel()
        self.kept.setWordWrap(True)
        self.kept.setObjectName("muted")
        if record is not None:
            self.replace = QCheckBox(tr("linked_table.replace_source"))
            form.addRow(self.replace)
            form.addRow(self.kept)
            self.replace.toggled.connect(self._mode_changed)
        self.source = QComboBox()
        for choice in self.choices:
            self.source.addItem(choice_caption(choice), choice)
        self.source_row = form.addRow(tr("linked_table.source"), self.source)
        self.picker = QTableWidget()
        self.picker.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.picker.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.picker.setMinimumHeight(150)
        self.picker.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.picker.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.picker.setObjectName("linkedTablePicker")
        self.picker.itemSelectionChanged.connect(self._picked)
        self.range_hint = QLabel(tr("linked_table.range.hint"))
        self.range_hint.setObjectName("muted")
        self.range_hint.setWordWrap(True)
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.range_hint)
        column.addWidget(self.picker, 1)
        spins = QHBoxLayout()
        self.first_row, self.last_row = QSpinBox(), QSpinBox()
        self.first_column, self.last_column = QSpinBox(), QSpinBox()
        for caption, first, last in ((tr("linked_table.range.rows"), self.first_row, self.last_row),
                                     (tr("linked_table.range.columns"), self.first_column, self.last_column)):
            spins.addWidget(QLabel(caption))
            spins.addWidget(first)
            spins.addWidget(QLabel(tr("linked_table.range.to")))
            spins.addWidget(last)
            spins.addSpacing(12)
        spins.addStretch(1)
        for spin in (self.first_row, self.last_row, self.first_column, self.last_column):
            spin.setRange(1, 1)
            spin.valueChanged.connect(self._typed)
        column.addLayout(spins)
        self.range_size = QLabel()
        column.addWidget(self.range_size)
        self.range_box = QGroupBox(tr("linked_table.range"))
        QVBoxLayout(self.range_box).addWidget(box)
        outer.addWidget(self.range_box, 1)

        look = QFormLayout()
        outer.addLayout(look)
        self.linked = QRadioButton(tr("linked_table.mode.linked"))
        self.copy = QRadioButton(tr("linked_table.mode.copy"))
        modes = QWidget()
        mode_line = QVBoxLayout(modes)
        mode_line.setContentsMargins(0, 0, 0, 0)
        mode_line.addWidget(self.linked)
        mode_line.addWidget(self.copy)
        look.addRow(tr("linked_table.mode"), modes)
        from .graph_format import Choice
        self.headers = Choice(lt.HEADERS, HEADERS_LABEL, (record or {}).get("headers", "both"))
        look.addRow(tr("linked_table.headers"), self.headers)
        self.orientation = Choice(lt.ORIENTATIONS, ORIENTATION_LABEL, (record or {}).get("orientation", "normal"))
        look.addRow(tr("linked_table.orientation"), self.orientation)
        self.font = QComboBox()
        self.font.addItem(tr("linked_table.font.default"), None)
        for family in lt.FONT_FAMILIES:
            self.font.addItem(tr(f"linked_table.font.{family}"), family)
        self.font.setCurrentIndex(max(0, self.font.findData((record or {}).get("font"))))
        self.size = QDoubleSpinBox()
        self.size.setRange(*lt.SIZE_RANGE)
        self.size.setSingleStep(.5)
        self.size.setDecimals(1)
        self.size.setValue((record or {}).get("size", lt.DEFAULT_SIZE))
        font_line = QWidget()
        font_row = QHBoxLayout(font_line)
        font_row.setContentsMargins(0, 0, 0, 0)
        font_row.addWidget(self.font, 1)
        font_row.addWidget(QLabel(tr("linked_table.size")))
        font_row.addWidget(self.size)
        look.addRow(tr("linked_table.font"), font_line)
        self.grid = QCheckBox(tr("linked_table.grid"))
        self.grid.setChecked((record or {}).get("grid", True))
        look.addRow(self.grid)
        x, y = (record or {}).get("position", (.05, .05))
        self.x, self.y = QDoubleSpinBox(), QDoubleSpinBox()
        for spin, value in ((self.x, x), (self.y, y)):
            spin.setRange(0, 100)
            spin.setDecimals(1)
            spin.setSuffix(" %")
            spin.setValue(round(value * 100, 1))
        position = QWidget()
        position_row = QHBoxLayout(position)
        position_row.setContentsMargins(0, 0, 0, 0)
        for caption, spin in ((tr("linked_table.position.x"), self.x), (tr("linked_table.position.y"), self.y)):
            position_row.addWidget(QLabel(caption))
            position_row.addWidget(spin)
        position_row.addStretch(1)
        look.addRow(tr("linked_table.position"), position)

        self.shown = QLabel()
        self.shown.setObjectName("linkedTablePreview")
        scroll = QScrollArea()
        scroll.setWidget(self.shown)
        scroll.setMaximumHeight(150)
        scroll.setMinimumHeight(70)
        preview = QGroupBox(tr("linked_table.preview"))
        QVBoxLayout(preview).addWidget(scroll)
        outer.addWidget(preview)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        self.layout().addWidget(self.problem)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("language.ok"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout().addWidget(self.buttons)

        self.source.currentIndexChanged.connect(self._load_source)
        for signal in (self.headers.currentIndexChanged, self.orientation.currentIndexChanged,
                       self.font.currentIndexChanged, self.size.valueChanged, self.grid.toggled, self.x.valueChanged,
                       self.y.valueChanged, self.linked.toggled, self.copy.toggled):
            signal.connect(self._refresh)
        (self.copy if (record or {}).get("mode") == "copy" else self.linked).setChecked(True)
        self._start(preset)
        self.resize(720, 760)

    # -- the source and the range ----------------------------------------------------------------------
    def _start(self, preset):
        if not self.choices and (self.record is None or self.replace is not None and self.replace.isChecked()):
            self.problem.setText(tr("linked_table.no_source"))
            self.problem.setVisible(True)
        index = -1
        if preset is not None:
            index = next((i for i, choice in enumerate(self.choices) if same_source(choice, {"source": preset[0]})
                          or choice == preset[0]), -1)
        elif self.record is not None:
            index = next((i for i, choice in enumerate(self.choices) if same_source(choice, self.record)), -1)
        if index >= 0:
            self.source.setCurrentIndex(index)
        self._load_source(select=preset[1] if preset is not None else None)
        self._mode_changed()

    def choose_target(self, reference):
        """Select the place ``reference`` (a ``("graph", index)`` or ``("layout", index)``) when it is offered."""
        if self.place is not None and reference in self.targets:
            self.place.setCurrentIndex(self.targets.index(reference))

    @property
    def keeping(self):
        return self.record is not None and not self.replace.isChecked()

    def _mode_changed(self, *_):
        keeping = self.keeping
        for widget in (self.source, self.range_box, self.linked, self.copy):
            widget.setEnabled(not keeping)
        self.kept.setVisible(self.record is not None and keeping)
        if self.record is not None:
            self.kept.setText(tr("linked_table.kept_source", origin=self.record.get("origin", "")))
        self._refresh()

    def _load_source(self, *_, select=None):
        self._syncing = True
        try:
            self.picker.clear()
            self.picker.setRowCount(0)
            self.picker.setColumnCount(0)
            if not self.choices:
                return
            choice = self.choices[self.source.currentIndex()]
            try:
                rows, columns, cells = self.project.table_source_preview(choice, PREVIEW_ROWS, PREVIEW_COLUMNS)
            except ValueError as error:
                self._show(str(error))
                return
            self.picker.setRowCount(len(rows))
            self.picker.setColumnCount(len(columns))
            self.picker.setVerticalHeaderLabels(rows)
            self.picker.setHorizontalHeaderLabels(columns)
            for r, line in enumerate(cells):
                for c, text in enumerate(line):
                    item = QTableWidgetItem(text)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.picker.setItem(r, c, item)
            self.first_row.setRange(1, choice["rows"])
            self.last_row.setRange(1, choice["rows"])
            self.first_column.setRange(1, choice["columns"])
            self.last_column.setRange(1, choice["columns"])
            top, left, bottom, right = select or (0, 0, 0, 0)
            for spin, value in ((self.first_row, top), (self.last_row, bottom), (self.first_column, left),
                                (self.last_column, right)):
                spin.setValue(min(value, spin.maximum() - 1) + 1)
            self._select_range()
        finally:
            self._syncing = False
        self._refresh()

    def _box(self):
        """The rectangle of the spin boxes as (top, left, bottom, right), 0-based, in reading order."""
        rows = sorted((self.first_row.value(), self.last_row.value()))
        columns = sorted((self.first_column.value(), self.last_column.value()))
        return rows[0] - 1, columns[0] - 1, rows[1] - 1, columns[1] - 1

    def _select_range(self):
        top, left, bottom, right = self._box()
        self.picker.clearSelection()
        if top < self.picker.rowCount() and left < self.picker.columnCount():
            from PySide6.QtWidgets import QTableWidgetSelectionRange
            self.picker.setRangeSelected(QTableWidgetSelectionRange(
                top, left, min(bottom, self.picker.rowCount() - 1), min(right, self.picker.columnCount() - 1)), True)

    def _picked(self):
        if self._syncing:
            return
        ranges = self.picker.selectedRanges()
        if not ranges:
            return
        self._syncing = True
        try:
            for spin, value in ((self.first_row, min(r.topRow() for r in ranges)),
                                (self.last_row, max(r.bottomRow() for r in ranges)),
                                (self.first_column, min(r.leftColumn() for r in ranges)),
                                (self.last_column, max(r.rightColumn() for r in ranges))):
                spin.setValue(value + 1)
        finally:
            self._syncing = False
        self._refresh()

    def _typed(self, *_):
        if self._syncing:
            return
        self._syncing = True
        try:
            self._select_range()
        finally:
            self._syncing = False
        self._refresh()

    # -- the table -------------------------------------------------------------------------------------
    def _show(self, text):
        self.problem.setText(text)
        self.problem.setVisible(bool(text))

    def _look(self):
        record = {"headers": self.headers.value(), "orientation": self.orientation.value(),
                  "size": self.size.value(), "grid": self.grid.isChecked(),
                  "position": [self.x.value() / 100, self.y.value() / 100]}
        return record, self.font.currentData()

    def build(self):
        """The record the dialog describes, or ``ValueError`` with why it is not one yet."""
        look, font = self._look()
        if self.keeping:
            record = {key: value for key, value in self.record.items() if key != "font"}
            record.update(look)
            if font:
                record["font"] = font
            return lt.validate_table(record)
        if not self.choices:
            raise ValueError(tr("linked_table.no_source"))
        top, left, bottom, right = self._box()
        lt.check_size(bottom - top + 1, right - left + 1)  # Before any cell is read.
        return self.project.table_record(
            self.choices[self.source.currentIndex()], (top, left, bottom, right),
            mode="copy" if self.copy.isChecked() else "linked", position=look["position"], size=look["size"],
            headers=look["headers"], orientation=look["orientation"], grid=look["grid"], font=font,
            record_id=self.record["id"] if self.record is not None else None)

    def _refresh(self, *_):
        if self._syncing:
            return
        top, left, bottom, right = self._box()
        rows, columns = bottom - top + 1, right - left + 1
        self.range_size.setText(tr("linked_table.range.size", rows=rows, columns=columns, max_rows=lt.MAX_ROWS,
                                   max_columns=lt.MAX_COLUMNS, max_cells=lt.MAX_CELLS))
        too_large = rows > lt.MAX_ROWS or columns > lt.MAX_COLUMNS or rows * columns > lt.MAX_CELLS
        self.range_size.setProperty("textState", "error" if too_large and not self.keeping else "")
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        try:
            record = self.build()
            spec = self.project.table_specs([record])[0]
            self.shown.setPixmap(preview_pixmap(spec))
            self.shown.adjustSize()
        except ValueError as error:
            self.shown.clear()
            self._show(translate_message(error, "linked_table.error."))
            ok.setEnabled(False)
            return
        self._show("")
        ok.setEnabled(True)

    def accept(self):
        try:
            self.result = self.build()
        except ValueError as error:
            self._show(translate_message(error, "linked_table.error."))
            return
        if self.place is not None:
            self.target = self.targets[self.place.currentIndex()]
        super().accept()


class LinkedTablesDialog(QDialog):
    """The linked tables of one graph or layout. ``result`` is the new list of records after Apply."""

    def __init__(self, parent, project, records, *, owner, preset=None):
        super().__init__(parent)
        self.project, self.records, self.result, self.owner = project, deepcopy(list(records)), None, owner
        self.setWindowTitle(tr("linked_table.title"))
        outer = QVBoxLayout(self)
        caption = QLabel(owner)
        caption.setObjectName("muted")
        outer.addWidget(caption)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("linked_table.column.source"), tr("linked_table.column.mode"),
                                              tr("linked_table.column.position"), tr("linked_table.column.state")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit())
        self.table.itemSelectionChanged.connect(self._buttons)
        outer.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.add_button = QPushButton(tr("linked_table.add"))
        self.add_button.clicked.connect(self.add)
        self.edit_button = QPushButton(tr("linked_table.edit"))
        self.edit_button.clicked.connect(self.edit)
        self.remove_button = QPushButton(tr("linked_table.remove"))
        self.remove_button.clicked.connect(self.remove)
        for button in (self.add_button, self.edit_button, self.remove_button):
            button.setAutoDefault(False)
            row.addWidget(button)
        row.addStretch(1)
        outer.addLayout(row)
        buttons = QDialogButtonBox()
        buttons.addButton(tr("graph.format.apply"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        buttons.addButton(tr("setup.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.fill()
        self.resize(640, 340)
        self.preset = preset

    def showEvent(self, event):
        super().showEvent(event)
        if self.preset is not None:
            preset, self.preset = self.preset, None
            self.add(preset=preset)

    def fill(self, selected=None):
        specs = self.project.table_specs(self.records)
        self.table.setRowCount(len(self.records))
        for index, (record, spec) in enumerate(zip(self.records, specs, strict=True)):
            x, y = record["position"]
            state = spec.resolved.state
            cells = (record.get("origin", ""), tr(f"linked_table.mode.{record['mode']}_short"),
                     f"{x * 100:.0f}%, {y * 100:.0f}%",
                     tr("linked_table.state_ok") if state == "ok" else tr(f"linked_table.state.{state}"))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 3 and state != "ok":
                    item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(index, column, item)
        if selected is not None and self.records:
            self.table.selectRow(min(selected, len(self.records) - 1))
        self._buttons()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _buttons(self):
        chosen = self._selected() is not None
        self.edit_button.setEnabled(chosen)
        self.remove_button.setEnabled(chosen)
        self.add_button.setEnabled(len(self.records) < lt.MAX_TABLES)

    def add(self, *, preset=None):
        if len(self.records) >= lt.MAX_TABLES:
            return
        dialog = LinkedTableDialog(self, self.project, preset=preset)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.records.append(dialog.result)
            self.fill(len(self.records) - 1)

    def edit(self):
        index = self._selected()
        if index is None:
            return
        dialog = LinkedTableDialog(self, self.project, self.records[index])
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result is not None:
            self.records[index] = dialog.result
            self.fill(index)

    def remove(self):
        index = self._selected()
        if index is not None:
            del self.records[index]
            self.fill(index)

    def accept(self):
        self.result = self.records
        super().accept()


__all__ = ["LinkedTableDialog", "LinkedTablesDialog", "preview_pixmap"]
