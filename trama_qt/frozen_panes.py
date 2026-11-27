"""Fixed rows and columns: the first rows and columns of a table stay in view while the rest scrolls.

A view-only setting, like the zoom. The fixed parts are ``FrozenPane`` tables drawn over the edges of the main view:
they show the same model through the same selection model, so there is one selection, one current cell and one
clipboard. The main view answers ``visualRect``/``indexAt`` as the cells are drawn on screen (``FrozenPaneHooks`` in
``trama_qt/sheet.py``), which keeps keyboard moves, rectangular selections, editing and copy working across the
boundary. The wish is kept per sheet for the open session only; a project never stores it and Undo never touches it.
"""
import weakref

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
                               QHeaderView, QLabel, QSpinBox, QTableView, QVBoxLayout, QWidget)

from analisi.grid_headings import column_label
from analisi.i18n import active_language

from . import theme
from .sheet import WorksheetEditorDelegate, WorksheetHeading, WorksheetView

_ITALIAN = {
    "Freeze rows and columns…": "Fissa righe e colonne…",
    "Unfreeze rows and columns": "Libera righe e colonne",
    "Keep the first rows and columns of the table in view while the rest scrolls":
        "Tiene in vista le prime righe e colonne della tabella mentre il resto scorre",
    "Show every row and column scrolling again": "Fa scorrere di nuovo tutte le righe e colonne",
    "Freeze rows and columns": "Fissa righe e colonne",
    "Rows at the top": "Righe in alto",
    "Columns on the left": "Colonne a sinistra",
    "Freeze": "Fissa",
    "Cancel": "Annulla",
    "Only the view changes: the data, Undo and the saved project stay as they are. Zero leaves that side free.":
        "Cambia solo la vista: dati, Annulla e progetto salvato restano come sono. Zero lascia libero quel lato.",
    "Rows 1–{last} stay in view.": "Le righe 1–{last} restano in vista.",
    "Row 1 stays in view.": "La riga 1 resta in vista.",
    "Columns A–{last} stay in view.": "Le colonne A–{last} restano in vista.",
    "Column A stays in view.": "La colonna A resta in vista.",
    "group {letter}": "gruppo {letter}",
    "Column groups stay whole: {asked} columns would split {band}, so the boundary falls after column {last}.":
        "I gruppi di colonne restano interi: {asked} colonne dividerebbero il {band}, quindi il confine cade dopo la "
        "colonna {last}.",
    "Column groups stay whole: {asked} columns would split {band}, so no column stays fixed.":
        "I gruppi di colonne restano interi: {asked} colonne dividerebbero il {band}, quindi nessuna colonna resta "
        "fissa.",
    "The boundary falls at the end of {band}, after column {last}.":
        "Il confine cade alla fine del {band}, dopo la colonna {last}.",
    "Fixed rows and columns work on Column, Multiple variables and XY sheets and on result tables. "
    "This {kind} sheet is not supported yet.":
        "Righe e colonne fisse funzionano su fogli Colonne, Variabili multiple e XY e sulle tabelle dei risultati. "
        "Questo foglio {kind} non è ancora supportato.",
    "Fixed rows and columns need a table: open a worksheet or a result table.":
        "Righe e colonne fisse richiedono una tabella: apri un foglio dati o una tabella dei risultati.",
    "Fixed rows: {rows} · fixed columns: {columns}.": "Righe fisse: {rows} · colonne fisse: {columns}.",
    "Rows and columns scroll freely again.": "Righe e colonne scorrono di nuovo liberamente.",
    "The view is already free.": "La vista è già libera.",
    "The window is narrow: for now fixed rows {rows}, fixed columns {columns}; the rest comes back when there is "
    "room.":
        "La finestra è stretta: per ora righe fisse {rows}, colonne fisse {columns}; il resto torna quando c'è "
        "spazio.",
}


def t(text, **values):
    if active_language() == "it":
        text = _ITALIAN.get(text, text)
    return text.format(**values) if values else text


SUPPORTED_FORMATS = {"column", "multivariable"}


def supported_format(table_format):
    kind = (table_format or "").casefold()
    return kind in SUPPORTED_FORMATS or kind == "xy" or kind.startswith("xy ")


def column_boundaries(model):
    """Column counts that keep every heading group whole (all counts for a table without groups)."""
    count = model.columnCount()
    bands = getattr(model, "bands", None)
    if not bands:
        return list(range(count + 1))
    starts = {first for first, _stop, _band, _title in bands}
    return sorted(starts | set(range(len(bands), count + 1)))


def snap_columns(model, asked):
    """The valid boundary for ``asked`` fixed columns, and the group it would have split (or None)."""
    boundaries = column_boundaries(model)
    if asked in boundaries:
        return asked, None
    count = model.columnCount()
    below = max(value for value in boundaries if value < asked)
    above = min((value for value in boundaries if value > asked), default=count)
    if above >= count:
        chosen = below
    elif below == 0:
        chosen = above
    else:
        chosen = below if asked - below <= above - asked else above
    band = model.bands[asked][2] if asked < len(model.bands) else None
    return chosen, band


class FrozenPane(QTableView):
    """One fixed part of a table: same model, same selection, drawn over the main view."""

    def __init__(self, panes, rows, columns):
        main = panes.view
        super().__init__(main)
        self.panes = panes
        self.main = main
        self.fixed_rows = rows
        self.fixed_columns = columns
        self.setObjectName(main.objectName())
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Keys always reach the main view.
        self.setFrameShape(QTableView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setAutoScroll(False)
        self.setWordWrap(False)
        self.setShowGrid(main.showGrid())
        self.setCornerButtonEnabled(True)
        if isinstance(main, WorksheetView):
            self.setHorizontalHeader(WorksheetHeading(self))
            self.horizontalHeader().sectionDoubleClicked.connect(main.host.rename_column)
            self.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.horizontalHeader().customContextMenuRequested.connect(
                lambda position: main._heading_menu(position, self.horizontalHeader()))
        self.setModel(main.model())
        self.setSelectionModel(main.selectionModel())
        delegate = main.itemDelegate()
        self.setItemDelegate(WorksheetEditorDelegate(self) if isinstance(delegate, WorksheetEditorDelegate)
                             else type(delegate)(self))
        self.setSelectionMode(main.selectionMode())
        self.setEditTriggers(main.editTriggers())
        for header in (self.horizontalHeader(), self.verticalHeader()):
            header.setHighlightSections(False)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            header.setMinimumSectionSize(1)
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalHeader().setSectionsClickable(True)
        self.horizontalHeader().setSectionsClickable(True)
        if main.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu:
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._context_menu)

    # The main view keeps the geometry: the fixed parts ask it where a cell is on screen.
    def _origin(self):
        return self.viewport().mapTo(self.main, QPoint()) - self.main.viewport().mapTo(self.main, QPoint())

    def visualRect(self, index):
        rect = self.panes.visual_rect(index)
        return rect.translated(-self._origin()) if rect.isValid() else rect

    def indexAt(self, point):
        return self.panes.index_at(point + self._origin())

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible):
        pass  # The main view scrolls; this part follows it.

    def updateGeometries(self):
        super().updateGeometries()
        self.follow()

    def follow(self):
        """Scroll as the main view does along the axis that is not fixed (its range may start after zero)."""
        for own, main, fixed in ((self.horizontalScrollBar(), self.main.horizontalScrollBar(), self.fixed_columns),
                                 (self.verticalScrollBar(), self.main.verticalScrollBar(), self.fixed_rows)):
            value = 0 if fixed else main.value()
            if own.maximum() < value:
                own.setRange(0, value)
            if own.value() != value:
                own.setValue(value)

    def wheelEvent(self, event):
        self.main.wheelEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if self.main.state() != QAbstractItemView.State.EditingState or event.button() != Qt.MouseButton.LeftButton:
            self.main.setFocus()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.state() != QAbstractItemView.State.EditingState:
            self.main.setFocus()

    def _context_menu(self, position):
        index = QTableView.indexAt(self, position)
        if index.isValid() and not self.selectionModel().isSelected(index):
            self.selectionModel().setCurrentIndex(index, self.selectionModel().SelectionFlag.ClearAndSelect)
        self.main.customContextMenuRequested.emit(position + self._origin())

    def closeEditor(self, editor, hint):
        # As in the main grid: Enter moves down; Tab moves along the row.
        hints = QAbstractItemDelegate.EndEditHint
        moves = {hints.SubmitModelCache: (1, 0), hints.EditNextItem: (0, 1), hints.EditPreviousItem: (0, -1)}
        step = moves.get(hint) if isinstance(self.main, WorksheetView) else None
        super().closeEditor(editor, hints.NoHint if step else hint)
        self.main.setFocus()
        current = self.main.currentIndex()
        if step is None or not current.isValid():
            return
        model = self.main.model()
        row = min(max(0, current.row() + step[0]), model.rowCount() - 1)
        column = min(max(0, current.column() + step[1]), model.columnCount() - 1)
        self.main.setCurrentIndex(model.index(row, column))
        if step[1]:
            self.main.edit(self.main.currentIndex())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        if isinstance(self.main, WorksheetView):
            self._paint_marks(painter)
        painter.setPen(QPen(theme.color("accent_dark"), 2))
        area = self.viewport().rect()
        if self.fixed_columns:
            painter.drawLine(area.right(), area.top(), area.right(), area.bottom())
        if self.fixed_rows:
            painter.drawLine(area.left(), area.bottom(), area.right(), area.bottom())

    def _paint_marks(self, painter):
        """The marks the worksheet draws over its cells, for the part of it this pane covers."""
        model = self.model()
        if model is None or not model.columnCount():
            return
        last = model.columnCount() - 1
        edge = max(0, self.columnViewportPosition(last) + self.columnWidth(last))
        if edge < self.viewport().width():
            blank = self.viewport().rect().adjusted(edge, 0, 0, 0)
            painter.fillRect(blank, theme.color("panel"))
            painter.setPen(theme.color("grid"))
            for x in range(edge, blank.right() + 1, 96):
                painter.drawLine(x, blank.top(), x, blank.bottom())
            for row in range(max(0, self.rowAt(0)), model.rowCount()):
                y = self.rowViewportPosition(row) + self.rowHeight(row) - 1
                if y > blank.bottom():
                    break
                painter.drawLine(edge, y, blank.right(), y)
        accent = theme.color("accent")
        accent.setAlpha(150)
        painter.setPen(accent)
        for column in self.main.formula_columns:
            if not self.isColumnHidden(column):
                left = self.columnViewportPosition(column)
                right = left + self.columnWidth(column) - 1
                painter.drawLine(left, 0, left, self.viewport().height())
                painter.drawLine(right, 0, right, self.viewport().height())
        painter.setPen(QPen(theme.color("accent_dark"), 2))
        for cells in self.selectionModel().selection():
            rect = self.visualRect(cells.topLeft()).united(self.visualRect(cells.bottomRight()))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        current = self.currentIndex()
        if current.isValid():
            painter.setPen(QPen(theme.color("text"), 2))
            painter.drawRect(self.visualRect(current).adjusted(1, 1, -1, -1))

    @property
    def formula_columns(self):  # WorksheetHeading reads it from its view.
        return self.main.formula_columns


_GEOMETRY_EVENTS = (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.FontChange, QEvent.Type.LayoutRequest,
                    QEvent.Type.StyleChange)


class _Mask(QWidget):
    """Covers the sliver of a row or column cut by the boundary at the very end of the scroll range."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), theme.color("panel"))


class FrozenPanes(QObject):
    """The fixed rows and columns of one table view.

    The main view keeps only the scrolling cells in its viewport: its headers grow by the size of the fixed part
    (so Qt itself leaves room for it), its scroll bars start where the fixed part ends, and the fixed parts sit in
    that room. Nothing covers the scrolling cells, so scrolling stays a fast copy of the screen."""

    def __init__(self, view, notify=None):
        super().__init__(view)
        self.view = view
        self.notify = notify  # Called with a status text when the window is too small for the wish.
        self.rows = self.columns = 0  # The wish, counted in visual order.
        self.fixed = (0, 0)  # What fits now.
        self.extent = (0, 0)  # Pixels of the fixed columns and rows.
        self.natural = (0, 0)  # Row header width and column header height without the fixed part.
        self.parts = {}
        self._modes = (view.horizontalScrollMode(), view.verticalScrollMode())
        self._saved = None
        self._custom_rows = set()
        self._syncing = False
        self._told = None
        self._last = {"h": 0, "v": 0}  # Scroll values before the latest move: the direction of a snap.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.sync)
        self.masks = {"h": _Mask(view), "v": _Mask(view)}
        view.frozen_panes = self
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)
        horizontal, vertical = view.horizontalHeader(), view.verticalHeader()
        for header in (horizontal, vertical):
            header.sectionResized.connect(self._section_resized)
            header.sectionCountChanged.connect(self.schedule)
            header.geometriesChanged.connect(self.schedule)
        model = view.model()
        for signal in (model.modelReset, model.layoutChanged, model.rowsInserted, model.rowsRemoved,
                       model.columnsInserted, model.columnsRemoved, model.headerDataChanged):
            signal.connect(self.schedule)
        view.horizontalScrollBar().valueChanged.connect(lambda value: self._scrolled("h", value))
        view.verticalScrollBar().valueChanged.connect(lambda value: self._scrolled("v", value))

    # == the wish ===================================================================================
    def active(self):
        return self.fixed != (0, 0)

    def set(self, rows, columns):
        model = self.view.model()
        self.rows = max(0, min(int(rows), model.rowCount() - 1))
        self.columns = max(0, min(int(columns), model.columnCount() - 1))
        view = self.view
        if self.rows or self.columns:
            view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.sync()
        current = view.currentIndex()
        if current.isValid():
            view.scrollTo(current)

    def clear(self):
        self.rows = self.columns = 0
        self.sync()
        self.view.setHorizontalScrollMode(self._modes[0])
        self.view.setVerticalScrollMode(self._modes[1])
        current = self.view.currentIndex()
        if current.isValid():
            self.view.scrollTo(current)

    # == geometry ===================================================================================
    def schedule(self, *_):
        if self.rows or self.columns or self.parts:
            self._timer.start()

    def eventFilter(self, watched, event):
        if event.type() in _GEOMETRY_EVENTS:  # Only the view and its viewport are watched.
            self.schedule()
        return False

    def _fitting(self, header, asked, room, boundaries=None):
        """The largest count up to ``asked`` that still leaves one whole scrolling section in ``room`` pixels."""
        count = header.count()
        candidates = [value for value in (boundaries or range(asked + 1)) if 0 < value <= asked and value < count]
        for value in sorted(candidates, reverse=True):
            following = header.logicalIndex(value)
            if header.sectionPosition(following) + header.sectionSize(following) <= room:
                return value
        return 0

    def _span(self, header, count):
        """Pixels taken by the first ``count`` sections in visual order."""
        if count <= 0:
            return 0
        if count >= header.count():
            return header.length()
        return header.sectionPosition(header.logicalIndex(count))

    def sync(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            self._sync()
        finally:
            self._syncing = False

    def _sync(self):
        view = self.view
        horizontal, vertical = view.horizontalHeader(), view.verticalHeader()
        width, height = self.extent
        rows = self._fitting(vertical, self.rows, view.viewport().height() + height)
        columns = self._fitting(horizontal, self.columns, view.viewport().width() + width,
                                column_boundaries(view.model()))
        fixed = (rows, columns)
        if fixed != self.fixed:
            reduced = fixed != (self.rows, self.columns)
            self.fixed = fixed
            if not reduced:
                self._told = None
            elif self.notify is not None and view.isVisible() and self._told != fixed:
                self._told = fixed
                self.notify(t("The window is narrow: for now fixed rows {rows}, fixed columns {columns}; the rest "
                              "comes back when there is room.", rows=rows, columns=columns))
        self._apply_headers(self._span(horizontal, columns), self._span(vertical, rows))
        wanted = {}
        if rows or columns:
            wanted["corner"] = (True, True)
        if columns:
            wanted["left"] = (False, True)
        if rows:
            wanted["top"] = (True, False)
        for name in [name for name in self.parts if name not in wanted]:
            part = self.parts.pop(name)
            part.hide()
            part.deleteLater()
        for name in ("left", "top", "corner"):
            if name in wanted and name not in self.parts:
                self.parts[name] = FrozenPane(self, *wanted[name])
                self.parts[name].horizontalHeader().sectionResized.connect(self._pane_section_resized)
        area = view.viewport().geometry()
        width, height = self.extent
        row_header, column_header = self.natural
        places = {"corner": QRect(area.x() - width - row_header, area.y() - height - column_header,
                                  row_header + width, column_header + height),
                  "left": QRect(area.x() - width, area.y(), width, area.height()),
                  "top": QRect(area.x(), area.y() - height, area.width(), height)}
        for name, part in self.parts.items():
            self._copy_sections(part)
            corner = name == "corner"
            part.verticalHeader().setVisible(corner and bool(row_header))
            part.horizontalHeader().setVisible(corner and bool(column_header))
            part.verticalHeader().setFixedWidth(row_header)
            part.horizontalHeader().setFixedHeight(column_header)
            part.setGeometry(places[name])
            part.show()
            part.raise_()
        self._follow()

    def _apply_headers(self, width, height):
        """Grow the headers by the fixed part, so the viewport holds only the scrolling cells."""
        view = self.view
        vertical, horizontal = view.verticalHeader(), view.horizontalHeader()
        if self._saved is None:
            self._saved = {"v_hidden": vertical.isHidden(), "v_min": vertical.minimumWidth(),
                           "v_max": vertical.maximumWidth(), "v_sheet": vertical.styleSheet(),
                           "h_min": horizontal.minimumHeight(), "h_sheet": horizontal.styleSheet()}
        saved = self._saved
        old_width, old_height = self.extent
        padded = not isinstance(horizontal, WorksheetHeading)  # The worksheet heading draws its own lines.
        if saved["v_hidden"]:
            row_header = 0
        else:
            row_header = max(saved["v_min"], vertical.sizeHint().width() - old_width)
        column_header = max(saved["h_min"], horizontal.sizeHint().height() - (old_height if padded else 0))
        if (width, height) == self.extent and (row_header, column_header) == self.natural:
            return
        self.extent, self.natural = (width, height), (row_header, column_header)
        if saved["v_hidden"]:
            vertical.setMinimumWidth(width if width else saved["v_min"])
            vertical.setMaximumWidth(width if width else saved["v_max"])
            vertical.setVisible(bool(width))
        else:
            rule = f"QHeaderView::section:vertical {{ padding-right: {6 + width}px; }}" if width else ""
            vertical.setStyleSheet(saved["v_sheet"] + rule)
            vertical.setMinimumWidth(row_header + width if width else saved["v_min"])
        if padded:
            rule = f"QHeaderView::section:horizontal {{ padding-bottom: {3 + height}px; }}" if height else ""
            horizontal.setStyleSheet(saved["h_sheet"] + rule)
        horizontal.setMinimumHeight(column_header + height if height else saved["h_min"])
        view.updateGeometries()

    def after_geometries(self):
        """Qt has laid out the view again: the scroll ranges start after the fixed part."""
        width, height = self.extent
        for bar, start in ((self.view.horizontalScrollBar(), width), (self.view.verticalScrollBar(), height)):
            if bar.minimum() != start:
                bar.setRange(start, max(start, bar.maximum()))

    def _copy_sections(self, part):
        view = self.view
        part.setFont(view.font())
        for source, target in ((view.horizontalHeader(), part.horizontalHeader()),
                               (view.verticalHeader(), part.verticalHeader())):
            target.setFont(source.font())
            target.setDefaultSectionSize(source.defaultSectionSize())
        horizontal = view.horizontalHeader()
        for column in range(horizontal.count()):
            part.setColumnHidden(column, horizontal.isSectionHidden(column))
            part.horizontalHeader().resizeSection(column, horizontal.sectionSize(column))
        custom = set(getattr(view, "_custom_height_rows", ()))
        vertical = view.verticalHeader()
        if vertical.count() <= 2000:
            custom = set(range(vertical.count()))
        for row in custom | self._custom_rows:
            if row < vertical.count():
                part.verticalHeader().resizeSection(row, vertical.sectionSize(row))
        self._custom_rows = custom

    def _section_resized(self, index, _old, size):
        if self._syncing:
            return
        vertical = self.sender() is self.view.verticalHeader()
        for part in self.parts.values():
            (part.verticalHeader() if vertical else part.horizontalHeader()).resizeSection(index, size)
        if vertical:
            self._custom_rows.add(index)
        self.schedule()

    def _pane_section_resized(self, index, _old, size):
        if not self._syncing and self.view.columnWidth(index) != size:
            self.view.setColumnWidth(index, size)  # A fixed column widened from its own heading.

    # == scrolling ==================================================================================
    def _axis(self, axis):
        view = self.view
        if axis == "h":
            return view.horizontalScrollBar(), view.horizontalHeader()
        return view.verticalScrollBar(), view.verticalHeader()

    def _visual_at(self, header, content):
        """Visual index of the section that holds the content position (binary search: 50 000 rows stay quick)."""
        low, high = 0, header.count() - 1
        if high < 0 or content < 0 or content >= header.length():
            return -1
        while low < high:
            middle = (low + high + 1) // 2
            if header.sectionPosition(header.logicalIndex(middle)) <= content:
                low = middle
            else:
                high = middle - 1
        return low

    def _straddle(self, axis):
        """The first scrolling section when the viewport edge cuts it: (start, size, edge), otherwise None."""
        if not self.active():
            return None
        bar, header = self._axis(axis)
        content = bar.value()
        visual = self._visual_at(header, content)
        if visual < 0:
            return None
        logical = header.logicalIndex(visual)
        position = header.sectionPosition(logical)
        return None if position == content else (position, header.sectionSize(logical), content)

    def _scrolled(self, axis, value):
        # The first scrolling row or column starts at the boundary: a cell cut on its left would show only the last
        # digits of its number. Snap in the direction of the move; at the very end a mask covers the cut cell.
        straddle = self._straddle(axis)
        if straddle is not None:
            bar, _header = self._axis(axis)
            position, size, _edge = straddle
            target = position + size if value > self._last[axis] else position
            if bar.minimum() <= target <= bar.maximum() and target != value:
                bar.setValue(target)
                return
        self._last[axis] = value
        self._follow()

    def _follow(self, *_):
        for part in self.parts.values():
            part.follow()
        self._place_masks()

    def _place_masks(self):
        area = self.view.viewport().geometry()
        width, height = self.extent
        row_header, column_header = self.natural
        for axis, mask in self.masks.items():
            straddle = self._straddle(axis)
            if straddle is None:
                if not mask.isHidden():
                    mask.hide()
                continue
            position, size, edge = straddle
            cut = position + size - edge
            if axis == "h":
                rect = QRect(area.x(), area.y() - height - column_header, min(cut, area.width()),
                             area.height() + height + column_header)
            else:
                rect = QRect(area.x() - width - row_header, area.y(), area.width() + width + row_header,
                             min(cut, area.height()))
            if mask.geometry() != rect or mask.isHidden():
                mask.setGeometry(rect)
                mask.show()
                mask.raise_()

    # == what the main view asks ====================================================================
    def _frozen_row(self, row):
        return self.view.verticalHeader().visualIndex(row) < self.fixed[0]

    def _frozen_column(self, column):
        return self.view.horizontalHeader().visualIndex(column) < self.fixed[1]

    def visual_rect(self, index):
        """Where the cell is on screen, in main viewport coordinates (a fixed cell lies left of or above it)."""
        if not index.isValid():
            return QRect()
        horizontal, vertical = self.view.horizontalHeader(), self.view.verticalHeader()
        row, column = index.row(), index.column()
        if horizontal.isSectionHidden(column) or vertical.isSectionHidden(row):
            return QRect()
        width, height = self.extent
        x = (horizontal.sectionPosition(column) - width if self._frozen_column(column)
             else horizontal.sectionViewportPosition(column))
        y = vertical.sectionPosition(row) - height if self._frozen_row(row) else vertical.sectionViewportPosition(row)
        return QRect(x, y, horizontal.sectionSize(column), vertical.sectionSize(row))

    @staticmethod
    def _section_at(header, position, extent):
        if position >= 0:
            return header.logicalIndexAt(position)
        if position >= -extent:
            return header.logicalIndexAt(position + extent - header.offset())
        return -1

    def index_at(self, point):
        width, height = self.extent
        row = self._section_at(self.view.verticalHeader(), point.y(), height)
        column = self._section_at(self.view.horizontalHeader(), point.x(), width)
        if row < 0 or column < 0:
            return QModelIndex()
        return self.view.model().index(row, column)

    def pane_for(self, index):
        if not index.isValid():
            return None
        rows, columns = self._frozen_row(index.row()), self._frozen_column(index.column())
        name = "corner" if rows and columns else "top" if rows else "left" if columns else None
        return self.parts.get(name)

    @staticmethod
    def _scroll(bar, header, section, fixed, room, hint):
        """Bring a scrolling section into the viewport; a fixed one is always in view."""
        if header.visualIndex(section) < fixed:
            return
        position, size = header.sectionPosition(section), header.sectionSize(section)
        value = bar.value()
        hints = QAbstractItemView.ScrollHint
        if hint == hints.PositionAtTop:
            value = position
        elif hint == hints.PositionAtBottom:
            value = position + size - room
        elif hint == hints.PositionAtCenter:
            value = position - (room - size) // 2
        elif position < value:
            value = position
        elif position + size > value + room:
            value = min(position, position + size - room)
        bar.setValue(max(bar.minimum(), min(bar.maximum(), value)))

    def scroll_to(self, index, hint):
        if not index.isValid():
            return True
        view = self.view
        area = view.viewport().rect()
        self._scroll(view.horizontalScrollBar(), view.horizontalHeader(), index.column(), self.fixed[1],
                     area.width(), hint)
        self._scroll(view.verticalScrollBar(), view.verticalHeader(), index.row(), self.fixed[0],
                     area.height(), hint)
        return True


# == the window's commands ==========================================================================
class FreezeDialog(QDialog):
    """How many rows and columns to keep in view; proposed from the active cell."""

    def __init__(self, parent, view, *, unsupported=None):
        super().__init__(parent)
        self.view = view
        model = view.model()
        self.setWindowTitle(t("Freeze rows and columns"))
        layout = QVBoxLayout(self)
        note = QLabel(t("Only the view changes: the data, Undo and the saved project stay as they are. "
                        "Zero leaves that side free."))
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.rows = QSpinBox()
        self.rows.setRange(0, max(0, model.rowCount() - 1))
        self.columns = QSpinBox()
        self.columns.setRange(0, max(0, model.columnCount() - 1))
        current = view.currentIndex()
        if current.isValid():
            self.rows.setValue(view.verticalHeader().visualIndex(current.row()))
            self.columns.setValue(view.horizontalHeader().visualIndex(current.column()))
        form.addRow(t("Rows at the top"), self.rows)
        form.addRow(t("Columns on the left"), self.columns)
        layout.addLayout(form)
        self.boundary = QLabel()
        self.boundary.setObjectName("infoBanner")
        self.boundary.setWordWrap(True)
        layout.addWidget(self.boundary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(t("Freeze"))
        self.ok.setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.unsupported = unsupported
        if unsupported:
            for field in (self.rows, self.columns):
                field.setEnabled(False)
            self.ok.setEnabled(False)
        self.rows.valueChanged.connect(self._explain)
        self.columns.valueChanged.connect(self._explain)
        self._explain()
        theme.fit_dialog(self, 440, 300)

    def choice(self):
        columns, _band = snap_columns(self.view.model(), self.columns.value())
        return self.rows.value(), columns

    def _explain(self, *_):
        if self.unsupported:
            self.boundary.setText(self.unsupported)
            return
        model = self.view.model()
        asked = self.columns.value()
        columns, band = snap_columns(model, asked)
        lines = []
        rows = self.rows.value()
        if rows:
            lines.append(t("Row 1 stays in view.") if rows == 1 else t("Rows 1–{last} stay in view.", last=rows))
        if band is not None and columns:
            lines.append(t("Column groups stay whole: {asked} columns would split {band}, so the boundary falls "
                           "after column {last}.", asked=asked, band=_band_text(band), last=column_label(columns - 1)))
        elif band is not None:
            lines.append(t("Column groups stay whole: {asked} columns would split {band}, so no column stays fixed.",
                           asked=asked, band=_band_text(band)))
        elif columns:
            bands = getattr(model, "bands", None)
            if bands and columns - 1 < len(bands) and bands[columns - 1][1] - bands[columns - 1][0] > 1:
                lines.append(t("The boundary falls at the end of {band}, after column {last}.",
                               band=_band_text(bands[columns - 1][2]), last=column_label(columns - 1)))
            elif columns == 1:
                lines.append(t("Column A stays in view."))
            else:
                lines.append(t("Columns A–{last} stay in view.", last=column_label(columns - 1)))
        self.boundary.setText("\n".join(lines))
        self.boundary.setVisible(bool(lines))


def _band_text(band):
    if band.startswith("Group "):
        return t("group {letter}", letter=band[6:])
    return band


class PaneCommands:
    """Freeze rows and columns… / Unfreeze rows and columns, and the per-sheet wish for the open session."""

    def __init__(self, window):
        self.window = window
        self.wishes = weakref.WeakKeyDictionary()  # project → {sheet key: (rows, columns)}; never saved.

    def create_actions(self):
        self.window._action("freeze_panes", t("Freeze rows and columns…"), self.choose,
                            tip=t("Keep the first rows and columns of the table in view while the rest scrolls"))
        self.window._action("unfreeze_panes", t("Unfreeze rows and columns"), self.unfreeze,
                            tip=t("Show every row and column scrolling again"))

    def update(self, has_table):
        for key in ("freeze_panes", "unfreeze_panes"):
            self.window.actions[key].setEnabled(bool(has_table))

    def _target(self):
        """The table on screen and the key of its wish: the worksheet, or the result table in front."""
        window = self.window
        ref = window.selected
        if not ref or window.gallery is not None:
            return None, None
        if ref[0] == "data" and window.sheet is not None:
            return window.sheet, (window.project.sheet_key(ref), None)
        if ref[0] == "result" and window.result_tabs is not None and window.result_tabs.count():
            view = window.result_tabs.currentWidget()
            title = window.result_tabs.tabText(window.result_tabs.currentIndex())
            return view, (window.project.sheet_key(ref), getattr(view, "frozen_title", title))
        return None, None

    def _unsupported(self):
        ref = self.window.selected
        if ref and ref[0] == "data":
            table_format = self.window.project.tables[ref[1]].table_format
            if not supported_format(table_format):
                return t("Fixed rows and columns work on Column, Multiple variables and XY sheets and on result "
                         "tables. This {kind} sheet is not supported yet.", kind=table_format)
        return None

    def _store(self, key, wish):
        project = self.window.project
        try:
            wishes = self.wishes.setdefault(project, {})
        except TypeError:  # A project that cannot be weakly referenced: the wish lives with the view only.
            return
        if wish == (0, 0):
            wishes.pop(key, None)
        else:
            wishes[key] = wish

    def _panes(self, view):
        panes = getattr(view, "frozen_panes", None)
        if panes is None:
            panes = FrozenPanes(view, notify=self.window.status)
        return panes

    def choose(self):
        view, key = self._target()
        if view is None:
            self.window.status(t("Fixed rows and columns need a table: open a worksheet or a result table."))
            return
        dialog = FreezeDialog(self.window, view, unsupported=self._unsupported())
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            rows, columns = dialog.choice()
        finally:
            dialog.deleteLater()
        panes = self._panes(view)
        panes.set(rows, columns)
        self._store(key, (panes.rows, panes.columns))
        view.setFocus()
        if panes.rows or panes.columns:
            self.window.status(t("Fixed rows: {rows} · fixed columns: {columns}.", rows=panes.rows,
                                 columns=panes.columns))
        else:
            self.window.status(t("Rows and columns scroll freely again."))

    def unfreeze(self):
        view, key = self._target()
        panes = getattr(view, "frozen_panes", None) if view is not None else None
        if panes is None or not (panes.rows or panes.columns):
            self.window.status(t("The view is already free."))
            return
        panes.clear()
        self._store(key, (0, 0))
        view.setFocus()
        self.window.status(t("Rows and columns scroll freely again."))

    def attach(self, view, ref, table=None):
        """A table view was built again (sheet change, project tab, Undo): give it back the wish of this session."""
        project = self.window.project
        if table is not None:
            view.frozen_title = table
        try:
            wish = self.wishes.get(project, {}).get((project.sheet_key(ref), table))
        except TypeError:
            wish = None
        if wish:
            self._panes(view).set(*wish)


__all__ = ["FreezeDialog", "FrozenPane", "FrozenPanes", "PaneCommands", "column_boundaries", "snap_columns",
           "supported_format"]
