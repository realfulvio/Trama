"""Table views: the editable worksheet and the read-only result tables."""
import numpy as np
from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QModelIndex, QRect, QThread, Qt
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QGuiApplication, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QApplication, QDialog, QDialogButtonBox,
                               QFormLayout, QHeaderView, QLabel, QLineEdit, QMenu, QSpinBox, QStyledItemDelegate,
                               QTableView, QToolButton, QVBoxLayout)

from analisi.grid_data import clipboard_decimal_mark, clipboard_rows, copy_block, filter_clipboard_rows
from analisi.i18n import tr, ui
from analisi.worksheet_appearance import MAX_ROW_HEIGHT, MIN_ROW_HEIGHT

from . import theme
from .classic_bar import FILLED_SELECTION_COMMANDS, SELECTION_COMMANDS
from .models import FrameModel, display, last_filled
from .strings import qt
from .text_format import GRID_MENU


def add_text_menu(menu, host):
    """The Text commands as a submenu of a grid's selection menu."""
    submenu = menu.addMenu(tr("command.text_menu"))
    for key in GRID_MENU:
        if key == "|":
            submenu.addSeparator()
        else:
            submenu.addAction(host.actions[key])


def _setup(view):
    view.setFont(theme.table_font())  # Tabular figures: the digits of a column line up.
    view.setAlternatingRowColors(False)
    view.setWordWrap(False)
    view.setCornerButtonEnabled(True)
    view.verticalHeader().setDefaultSectionSize(26)
    view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    view.horizontalHeader().setDefaultSectionSize(112)
    view.horizontalHeader().setMinimumSectionSize(40)
    view.horizontalHeader().setHighlightSections(False)
    view.verticalHeader().setHighlightSections(False)


def _styled_height(view):
    """Row height the biggest explicit text size asks for (0 when no text style sets a size)."""
    model = view.model()
    styles = getattr(model, "text_styles", None)
    largest = styles.largest_size(0) if styles else 0
    if not largest:
        return 0
    font = QFont(view.font())
    font.setPointSizeF(largest * model.text_scale)
    return QFontMetrics(font).height() + 4


def fit_rows(view):
    """Uniform row height: the table font, or the largest text size a style asks for if that is taller."""
    height = view.fontMetrics().height() + 4
    if isinstance(view, FrameView):
        height = max(height, round(26 * view.model().text_scale))
    view.verticalHeader().setDefaultSectionSize(max(height, _styled_height(view)))


def set_table_appearance(view, preference, zoom):
    family, size = preference
    base = size if size is not None else 9.5
    font = theme.table_font(base * zoom / 100)
    if family:
        font.setFamily(family)
    previous = view.font().pointSizeF()
    ratio = font.pointSizeF() / previous if previous > 0 else 1
    view.setFont(font)
    heading = view.horizontalHeader()
    heading.setFont(font)
    view.verticalHeader().setFont(font)
    view.model().refresh_text(scale=zoom / 100)  # An explicit text size follows the table zoom.
    if isinstance(view, WorksheetView):
        widths = [view.columnWidth(column) for column in range(heading.count())]
        heading.setDefaultSectionSize(round(112 * font.pointSizeF() / 9.5))
        for column, width in enumerate(widths):
            view.setColumnWidth(column, round(width * ratio))
        view.apply_row_heights(zoom)
        heading.updateGeometry()
        heading.viewport().update()
    else:
        fit_rows(view)
        view._fit_columns()
    if view.currentIndex().isValid():
        view.scrollTo(view.currentIndex())


def selection_box(view):
    """The rectangle around the selected cells as (top, left, bottom, right), or the current cell."""
    # The selection ranges, not every selected index: a whole 50 000 × 20 sheet stays instant.
    ranges = [item for item in view.selectionModel().selection() if not item.isEmpty()] \
        if view.selectionModel() else []
    if not ranges:
        current = view.currentIndex()
        if not current.isValid():
            return None
        return current.row(), current.column(), current.row(), current.column()
    return (min(item.top() for item in ranges), min(item.left() for item in ranges),
            max(item.bottom() for item in ranges), max(item.right() for item in ranges))


def select_grid_cells(view, command, section=None):
    model = view.model()
    current = view.currentIndex()
    if command == "select_sheet_cells":
        view.selectAll()
    elif current.isValid() and command == "select_data_row":
        view.selectRow(current.row())
    elif command == "select_data_column":
        column = current.column() if section is None else section
        if not 0 <= column < model.columnCount() or not model.rowCount():
            return
        if isinstance(view, WorksheetView) and column < len(model.bands):
            first, end = model.bands[column][:2]
            view.select_block(0, first, model.rowCount() - 1, end - 1,
                              current_row=max(0, current.row()), current_col=column)
        else:
            view.selectColumn(column)
    elif current.isValid() and command in FILLED_SELECTION_COMMANDS:
        _, row_step, column_step = FILLED_SELECTION_COMMANDS[command]
        extend_filled_selection(view, current, row_step, column_step)


def extend_filled_selection(view, current, row_step, column_step):
    """Extend from the selected edge along the active row or column, up to the first gap."""
    if view.state() == QAbstractItemView.State.EditingState:
        return
    model = view.model()
    frame = model.frame
    row, column = current.row(), current.column()
    top, left, bottom, right = selection_box(view)
    row_labels = isinstance(model, FrameModel)
    first_data_column = int(row_labels)
    if not (row < len(frame) and column < len(frame.columns) + first_data_column):
        return
    if row_step:
        start = bottom if row_step > 0 else top
        values = (frame.index.to_numpy(copy=False) if column < first_data_column
                  else frame.iloc[:, column - first_data_column].to_numpy(copy=False))
        end = last_filled(values, start, row_step)
        if end == start:
            return
        top, bottom = min(top, end), max(bottom, end)
        target = model.index(end, column)
    else:
        start = right if column_step > 0 else left
        values = frame.iloc[row].to_numpy(dtype=object, copy=False)
        if row_labels:
            indexed = np.empty(len(values) + 1, dtype=object)
            indexed[0], indexed[1:] = frame.index[row], values
            values = indexed
        if not 0 <= start < len(values):
            return
        if view.horizontalHeader().hiddenSectionCount():
            visible = [index for index in range(len(values)) if not view.isColumnHidden(index)]
            if start not in visible:
                return
            end = visible[last_filled(values[visible], visible.index(start), column_step)]
        else:
            end = last_filled(values, start, column_step)
        if end == start:
            return
        left, right = min(left, end), max(right, end)
        target = model.index(row, end)
    selection = QItemSelection(model.index(top, left), model.index(bottom, right))
    view.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    view.scrollTo(target)


class WorksheetHeading(QHeaderView):
    """Draw the shared table, series and replicate headings over the worksheet columns."""

    def __init__(self, view):
        super().__init__(Qt.Orientation.Horizontal, view)
        self.view = view
        self.setSectionsClickable(True)
        self._group_pressed = False
        self.sectionClicked.connect(self._select_heading)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, event):
        self._group_pressed = (event.button() == Qt.MouseButton.LeftButton
                               and event.modifiers() == Qt.KeyboardModifier.NoModifier
                               and event.position().y() < self._line_height())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        column = self.logicalIndexAt(event.position().toPoint())
        model = self.model()
        if (event.button() == Qt.MouseButton.LeftButton and 0 <= column < len(model.bands)
                and model.bands[column][2].startswith("Group ") and not model.read_only):
            near_edge = self.sectionViewportPosition(column) + self.sectionSize(column) - event.position().x()
            if 4 < near_edge < self.sectionSize(column) - 4:
                tab = 2 if model.is_replicate(column) and event.position().y() >= 2 * self._line_height() else 1
                self.view.host.format_data_table(tab=tab, column=column)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _select_heading(self, column):
        model = self.model()
        if self._group_pressed and 0 <= column < len(model.bands):
            first, end = model.bands[column][:2]
            if end - first > 1:
                select_grid_cells(self.view, "select_data_column", column)

    def sizeHint(self):
        hint = super().sizeHint()
        model = self.model()
        hint.setHeight(self._line_height() * (3 if model is not None and model.roles else 2))
        return hint

    def _line_height(self):
        return self.fontMetrics().height() + 5

    def paintEvent(self, event):
        model = self.model()
        if model is None:
            super().paintEvent(event)
            return
        painter = QPainter(self.viewport())
        painter.fillRect(event.rect(), theme.color("header"))
        start = self.logicalIndexAt(max(0, event.rect().left()))
        if start < 0:
            return
        height = self._line_height()
        medium = self.font()
        bold = QFont(medium)
        bold.setBold(True)
        selected = self.view.selectionModel().selection()
        series = ("#0c9c92", "#e8795d", "#6757a3", "#c99a1c", "#3f7fb5", "#8a8f98")

        def draw(rect, label, active=False, *, title=False, stripe=None):
            painter.fillRect(rect, theme.color("tint" if active else "panel" if title else "header"))
            painter.setPen(theme.color("border"))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            if stripe is not None:
                painter.fillRect(rect.x() + 1, rect.y(), rect.width() - 1, 3, QColor(stripe))
            painter.setPen(theme.color("text"))
            painter.setFont(bold if active or (not title and rect.y() == 0) else medium)
            clip = rect.adjusted(4, 0, -4, 0)
            text = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, max(0, clip.width()))
            painter.drawText(clip, Qt.AlignmentFlag.AlignCenter, text)

        def includes(first, last):
            return any(first <= cells.right() and cells.left() <= last for cells in selected)

        column = start
        while column < self.count() and self.sectionViewportPosition(column) <= event.rect().right():
            if column >= len(model.bands):
                break
            first, stop, band, title = model.bands[column]
            left = self.sectionViewportPosition(first)
            width = self.sectionViewportPosition(stop - 1) + self.sectionSize(stop - 1) - left
            active = includes(first, stop - 1)
            stripe = series[(ord(band[-1]) - ord("A")) % len(series)] if band.startswith("Group ") else None
            draw(QRect(left, 0, width, height), model.band_label(first), active, stripe=stripe)
            draw(QRect(left, height, width, height), model.group_title(first), active, title=True)
            if model.roles:
                for subcolumn in range(max(first, start), stop):
                    left = self.sectionViewportPosition(subcolumn)
                    if left > event.rect().right():
                        break
                    active = includes(subcolumn, subcolumn)
                    rect = QRect(left, 2 * height, self.sectionSize(subcolumn), height)
                    draw(rect, model.subcolumn_label(subcolumn), active)
                    if active:
                        painter.fillRect(rect.x() + 1, rect.bottom() - 1, rect.width() - 1, 2, theme.color("accent"))
            column = stop
        for column in self.view.formula_columns:
            left = self.sectionViewportPosition(column)
            if not self.isSectionHidden(column):
                painter.fillRect(left, self.height() - 3, self.sectionSize(column), 3, theme.color("accent"))


class PasteSpecialDialog(QDialog):
    """Filter tabular clipboard rows before pasting at the selected cell."""

    def __init__(self, parent, rows, address):
        super().__init__(parent)
        self.rows = rows
        self.result_rows = None
        self.setWindowTitle(ui("Paste Special"))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("interface.paste_into", address=address)))
        layout.addWidget(QLabel(tr("interface.clipboard_size", rows=len(rows), columns=len(rows[0]))))
        form = QFormLayout()
        self.bounds = []
        for name, minimum, value in (("First row", 1, 1), ("Last row", 1, len(rows)), ("Rows to skip", 0, 0)):
            field = QSpinBox()
            field.setRange(minimum, len(rows))
            field.setValue(value)
            self.bounds.append(field)
            form.addRow(ui(name), field)
        layout.addLayout(form)
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.hide()
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ui("Paste"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        first, last, skip = (field.value() for field in self.bounds)
        try:
            self.result_rows = filter_clipboard_rows(self.rows, first=first, last=last, skip=skip)
        except ValueError as error:
            self.problem.setText(ui(str(error)))
            self.problem.show()
            self.bounds[1].setFocus()
            return
        super().accept()


class WorksheetRowHeader(QHeaderView):
    """Vertical numbered header supporting boundary height drag, contiguous block drag-reorder and menu."""

    GRIP_MARGIN = 4

    def __init__(self, view):
        super().__init__(Qt.Orientation.Vertical, view)
        self.view = view
        self.setSectionsClickable(True)
        self.setMouseTracking(True)
        self.setMinimumWidth(36)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._mode = None
        self._press_pos = None
        self._resize_row = None
        self._resize_start_height = 0
        self._move_range = None
        self._move_anchor_row = None
        self._drop_row = None

    def paintSection(self, painter, rect, row):
        selection = self.view.selectionModel()
        if selection is None or not selection.rowIntersectsSelection(row, QModelIndex()):
            super().paintSection(painter, rect, row)
            return
        painter.save()
        painter.fillRect(rect, theme.color("tint"))
        painter.fillRect(rect.right() - 1, rect.top(), 2, rect.height(), theme.color("accent"))
        painter.setPen(theme.color("border"))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        font = self.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(theme.color("text"))
        caption = self.model().headerData(row, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole)
        painter.drawText(rect.adjusted(1, 0, -2, 0), Qt.AlignmentFlag.AlignCenter, str(caption))
        painter.restore()

    def _data_rows(self):
        model = self.view.model()
        return len(model.frame) if model is not None else 0

    def _can_edit(self):
        model = self.view.model()
        return model is not None and not model.read_only

    def _can_reorder(self):
        return self._can_edit() and self.view.host.can_reorder_active_rows()

    def _resize_hit(self, y):
        data_rows = self._data_rows()
        if data_rows <= 0:
            return None
        row_at = self.logicalIndexAt(y)
        candidates = (row_at - 1, row_at) if 0 <= row_at < data_rows else (data_rows - 1,)
        for row in candidates:
            if 0 <= row < data_rows:
                bottom = self.sectionViewportPosition(row) + self.sectionSize(row)
                if abs(y - bottom) <= self.GRIP_MARGIN:
                    return row
        return None

    def _insertion_row(self, y):
        data_rows = self._data_rows()
        if data_rows <= 0:
            return 0
        if y <= self.sectionViewportPosition(0):
            return 0
        row = self.logicalIndexAt(max(0, y))
        if row < 0 or row >= data_rows:
            return data_rows
        top = self.sectionViewportPosition(row)
        return row if y < top + self.sectionSize(row) / 2 else min(data_rows, row + 1)

    def drop_line_y(self, drop_row):
        data_rows = self._data_rows()
        if data_rows <= 0:
            return None
        if drop_row < data_rows:
            y = self.sectionViewportPosition(drop_row)
        else:
            last = data_rows - 1
            y = self.sectionViewportPosition(last) + self.sectionSize(last)
        return max(1, min(self.viewport().height() - 2, y))

    def _clear_drag(self):
        self._mode = None
        self._press_pos = None
        self._resize_row = None
        self._resize_start_height = 0
        self._move_range = None
        self._move_anchor_row = None
        self._drop_row = None
        self.unsetCursor()
        self.viewport().update()
        self.view.viewport().update()

    def cancel_drag(self):
        if self._mode is None:
            return False
        if self._mode == "resize" and self._resize_row is not None:
            self.resizeSection(self._resize_row, self._resize_start_height)
        self._clear_drag()
        return True

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            y = int(event.position().y())
            if self._can_edit():
                hit = self._resize_hit(y)
                if hit is not None:
                    self._mode = "resize"
                    self._press_pos = event.position().toPoint()
                    self._resize_row = hit
                    self._resize_start_height = self.sectionSize(hit)
                    self.setCursor(Qt.CursorShape.SplitVCursor)
                    event.accept()
                    return
            row = self.logicalIndexAt(y)
            data_rows = self._data_rows()
            if (0 <= row < data_rows and self._can_reorder()
                    and not (event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier))):
                selection = self.view.selectionModel()
                box = self.view.box()
                if (box is not None and box[0] <= row <= box[2] < data_rows
                        and selection is not None and selection.isRowSelected(row, QModelIndex())):
                    self._move_range = (box[0], box[2] + 1)
                else:
                    self.view.selectRow(row)
                    self.view.setCurrentIndex(self.view.model().index(row, 0))
                    self._move_range = (row, row + 1)
                self._mode = "pending_move"
                self._press_pos = event.position().toPoint()
                self._move_anchor_row = row
                self._drop_row = None
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        y = int(event.position().y())
        if self._mode == "resize":
            zoom = getattr(self.view.host, "table_zoom", 100)
            min_px = max(MIN_ROW_HEIGHT, round(MIN_ROW_HEIGHT * zoom / 100))
            max_px = max(min_px, round(MAX_ROW_HEIGHT * zoom / 100))
            delta = y - self._press_pos.y()
            self.resizeSection(self._resize_row, max(min_px, min(max_px, self._resize_start_height + delta)))
            event.accept()
            return
        if self._mode == "pending_move":
            if (event.position().toPoint() - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                self._mode = "move"
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._drop_row = self._insertion_row(y)
                self.viewport().update()
                self.view.viewport().update()
            event.accept()
            return
        if self._mode == "move":
            bar = self.view.verticalScrollBar()
            if y < 16:
                bar.setValue(bar.value() - 1)
            elif y > self.viewport().height() - 16:
                bar.setValue(bar.value() + 1)
            self._drop_row = self._insertion_row(y)
            self.viewport().update()
            self.view.viewport().update()
            event.accept()
            return
        if self._can_edit() and self._resize_hit(y) is not None:
            self.setCursor(Qt.CursorShape.SplitVCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._mode is not None:
            mode = self._mode
            if mode == "resize":
                row, start_px = self._resize_row, self._resize_start_height
                final_px = self.sectionSize(row)
                self._clear_drag()
                if final_px != start_px:
                    zoom = getattr(self.view.host, "table_zoom", 100)
                    base_h = max(MIN_ROW_HEIGHT, min(MAX_ROW_HEIGHT, round(final_px * 100 / zoom)))
                    self.view.host.set_row_height(row, base_h)
                event.accept()
                return
            if mode == "pending_move":
                anchor = self._move_anchor_row
                self._clear_drag()
                if anchor is not None and anchor < self._data_rows():
                    self.view.selectRow(anchor)
                    self.view.setCurrentIndex(self.view.model().index(anchor, 0))
                event.accept()
                return
            if mode == "move":
                start, stop = self._move_range
                drop = self._drop_row
                self._clear_drag()
                if drop is not None and not (start <= drop <= stop):
                    self.view.host.move_rows(start, stop, drop)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.cancel_drag():
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._mode == "move" and self._drop_row is not None:
            y = self.drop_line_y(self._drop_row)
            if y is not None:
                painter = QPainter(self.viewport())
                painter.setPen(QPen(theme.color("accent_dark"), 3))
                painter.drawLine(0, y, self.viewport().width(), y)

    def _menu(self, position):
        row = self.logicalIndexAt(position)
        data_rows = self._data_rows()
        if not 0 <= row < data_rows:
            return
        model = self.view.model()
        selection = self.view.selectionModel()
        if selection is not None and not selection.isRowSelected(row, QModelIndex()):
            self.view.selectRow(row)
            self.view.setCurrentIndex(model.index(row, 0))
        self.view.host.update_actions()
        menu = QMenu(self)
        menu.addAction(self.view.host.actions["move_rows_up"])
        menu.addAction(self.view.host.actions["move_rows_down"])
        menu.addAction(self.view.host.actions["move_rows_first"])
        menu.addAction(self.view.host.actions["move_rows_last"])
        menu.addAction(self.view.host.actions["reset_row_height"])
        menu.addSeparator()
        menu.addAction(self.view.host.actions["insert_row"])
        menu.addAction(self.view.host.actions["delete_rows"])
        menu.exec(self.viewport().mapToGlobal(position))
        menu.deleteLater()


class WorksheetEditorDelegate(QStyledItemDelegate):
    """Keep the editor readable even in a manually shortened row."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        col = index.column()
        bands = index.model().bands
        if col and col < len(bands) and col == bands[col][0] and bands[col][2].startswith("Group "):
            painter.save()
            painter.setPen(theme.color("field_hover"))
            painter.drawLine(option.rect.topLeft(), option.rect.bottomLeft())
            painter.restore()

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.setObjectName("worksheetEditor")
            editor.setFont(index.data(Qt.ItemDataRole.FontRole) or option.font)
        return editor

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Qt queues the commit. Shift or Ctrl may already be released when closeEditor runs.
            editor.setProperty("worksheetEnterModifiers", event.modifiers().value)
        return super().eventFilter(editor, event)

    def updateEditorGeometry(self, editor, option, index):
        super().updateEditorGeometry(editor, option, index)
        if not isinstance(editor, QLineEdit):
            return
        rect = editor.geometry()
        available = editor.parentWidget().rect()
        height = min(available.height(), max(rect.height(), editor.sizeHint().height()))
        if height > rect.height():
            top = max(available.top(), min(rect.center().y() - height // 2, available.bottom() - height + 1))
            editor.setGeometry(rect.x(), top, rect.width(), height)


class WorksheetView(QTableView):
    """The data grid: typing, F2 and double click edit; Ctrl+C/X/V and Delete work on the selection."""

    def __init__(self, model, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.formula_columns = ()
        self._custom_height_rows = set()
        heading = WorksheetHeading(self)
        self.setHorizontalHeader(heading)
        self.setVerticalHeader(WorksheetRowHeader(self))
        self.setModel(model)
        _setup(self)
        self.setObjectName("classicWorksheet")
        self.addActions([host.actions[key] for key in SELECTION_COMMANDS])
        self.setItemDelegate(WorksheetEditorDelegate(self))
        fit_rows(self)
        self.format_corner = QToolButton(self)
        self.format_corner.setObjectName("worksheetFormatCorner")
        action = host.actions["format_data_table"]
        self.format_corner.setToolTip(action.toolTip())
        self.format_corner.clicked.connect(action.trigger)
        self.format_corner.setEnabled(action.isEnabled())
        action.enabledChanged.connect(self.format_corner.setEnabled)
        kind = model.dataset.table_format
        if "xy" in kind.casefold():
            self.format_corner.setText("XY")
            self.format_corner.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        else:
            self.format_corner.setIcon(theme.classic_icon("data"))
        self.format_corner.setAccessibleName(qt("qt.format_data_table"))
        self._title_settings = None
        self._title_columns = ()
        self._hidden_row_titles = set()
        model.modelReset.connect(self.apply_heading_format)
        self.apply_heading_format()
        self.selectionModel().selectionChanged.connect(self._selection_changed)
        model.headerDataChanged.connect(lambda *_: heading.updateGeometry())
        self.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.AnyKeyPressed
                             | QAbstractItemView.EditTrigger.DoubleClicked
                             | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.horizontalHeader().sectionDoubleClicked.connect(self.host.rename_column)
        heading.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        heading.customContextMenuRequested.connect(self._heading_menu)
        self.selectionModel().currentChanged.connect(lambda current, _: self.host.cell_changed(current))
        for sequence, handler in ((QKeySequence.StandardKey.Copy, self.copy),
                                  (QKeySequence.StandardKey.Cut, self.cut),
                                  (QKeySequence.StandardKey.Paste, self.paste)):
            action = QAction(self)
            action.setShortcut(sequence)
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            action.triggered.connect(handler)
            self.addAction(action)

    def updateGeometries(self):
        super().updateGeometries()
        if hasattr(self, "format_corner"):
            header, rows = self.horizontalHeader(), self.verticalHeader()
            height = max(1, header.height() - header._line_height())
            self.format_corner.setGeometry(rows.x(), header.y(), rows.width(), height)
            self.format_corner.raise_()

    def _selection_changed(self, *_):
        self.host.cell_changed(self.currentIndex())
        self.verticalHeader().viewport().update()
        self.horizontalHeader().viewport().update()
        self.host.update_actions()

    def apply_row_heights(self, zoom=100):
        header = self.verticalHeader()
        model = self.model()
        if model is None:
            return
        fit_rows(self)
        default_height = header.defaultSectionSize()
        data_rows = len(model.frame)
        wanted = {row: max(MIN_ROW_HEIGHT, round(height * zoom / 100))
                  for row, height in model.dataset.row_heights.items() if 0 <= row < data_rows}
        for row in self._custom_height_rows - wanted.keys():
            if row < model.rowCount():
                header.resizeSection(row, default_height)
        for row, height in wanted.items():
            header.resizeSection(row, height)
        self._custom_height_rows = set(wanted)

    def select_block(self, top, left, bottom, right, *, current_row=None, current_col=None):
        model = self.model()
        selection = self.selectionModel()
        if model is None or selection is None:
            return
        top = max(0, min(top, model.rowCount() - 1))
        bottom = max(top, min(bottom, model.rowCount() - 1))
        left = max(0, min(left, model.columnCount() - 1))
        right = max(left, min(right, model.columnCount() - 1))
        row_cur = top if current_row is None else max(top, min(bottom, current_row))
        col_cur = left if current_col is None else max(left, min(right, current_col))
        selection.select(QItemSelection(model.index(top, left), model.index(bottom, right)),
                         QItemSelectionModel.SelectionFlag.ClearAndSelect)
        selection.setCurrentIndex(model.index(row_cur, col_cur), QItemSelectionModel.SelectionFlag.NoUpdate)

    def box(self):
        return selection_box(self)

    def apply_heading_format(self):
        model = self.model()
        settings = model.dataset.worksheet_titles
        structure = tuple(model.column_tokens)
        changed = settings != self._title_settings or structure != self._title_columns
        heading = self.horizontalHeader()
        hidden = {column for column, (_, _, band, _) in enumerate(model.bands)
                  if band == "Row titles" and not settings.show_rows}
        for column in self._hidden_row_titles - hidden:
            if column < model.columnCount():
                self.setColumnHidden(column, False)
        for column in hidden:
            self.setColumnHidden(column, True)
        self._hidden_row_titles = hidden
        self._title_columns = structure
        for column, (first, stop, band, _) in enumerate(model.bands):
            if changed and settings.automatic_widths and not self.isColumnHidden(column):
                span = stop - first
                minimum = 76 if band == "Row titles" else 73 if span > 1 else 92 if model.roles else 105
                font = heading.font()
                font.setBold(True)
                metrics = QFontMetrics(font)
                title_width = max(metrics.horizontalAdvance(text) for text in
                                  (model.band_label(first), model.group_title(first))) + 16
                sub_width = metrics.horizontalAdvance(model.subcolumn_label(column)) + 16
                self.setColumnWidth(column, max(minimum, min(248, max(title_width // span, sub_width))))
        current = self.currentIndex()
        if current.isValid() and self.isColumnHidden(current.column()):
            visible = next((c for c in range(model.columnCount()) if not self.isColumnHidden(c)), None)
            if visible is not None:
                self.setCurrentIndex(model.index(current.row(), visible))
        self._title_settings = settings
        heading.viewport().update()

    def refresh_text(self, text_styles=None):
        """Draw the text styles again (undo, redo, a new format); selection and scrolling stay."""
        self.model().refresh_text(text_styles)
        self.apply_row_heights(round(self.model().text_scale * 100))

    def highlight_formula_columns(self, columns):
        if self.formula_columns != columns:
            self.formula_columns = columns
            self.horizontalHeader().viewport().update()
            self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        model = self.model()
        if model is None or not model.columnCount():
            return
        painter = QPainter(self.viewport())
        last = model.columnCount() - 1
        edge = max(0, self.columnViewportPosition(last) + self.columnWidth(last))
        if edge < self.viewport().width():
            blank = self.viewport().rect().adjusted(edge, 0, 0, 0)
            painter.fillRect(blank, theme.color("panel"))
            painter.setPen(theme.color("grid"))
            for x in range(edge, blank.right() + 1, 96):
                painter.drawLine(x, blank.top(), x, blank.bottom())
            start = self.rowAt(0)
            for row in range(max(0, start), model.rowCount()):
                y = self.rowViewportPosition(row) + self.rowHeight(row) - 1
                if y > blank.bottom():
                    break
                painter.drawLine(edge, y, blank.right(), y)
        if self.formula_columns:
            accent = theme.color("accent")
            accent.setAlpha(150)
            painter.setPen(accent)
            for column in self.formula_columns:
                if self.isColumnHidden(column):
                    continue
                left = self.columnViewportPosition(column)
                right = left + self.columnWidth(column) - 1
                painter.drawLine(left, 0, left, self.viewport().height())
                painter.drawLine(right, 0, right, self.viewport().height())
        selection = self.selectionModel()
        painter.setPen(QPen(theme.color("accent_dark"), 2))
        for cells in selection.selection():
            rect = self.visualRect(cells.topLeft()).united(self.visualRect(cells.bottomRight()))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        current = self.currentIndex()
        if current.isValid():
            rect = self.visualRect(current).adjusted(1, 1, -1, -1)
            painter.setPen(QPen(theme.color("text"), 2))
            painter.drawRect(rect)
        header = self.verticalHeader()
        if isinstance(header, WorksheetRowHeader) and header._mode == "move" and header._drop_row is not None:
            y = header.drop_line_y(header._drop_row)
            if y is not None:
                painter.setPen(QPen(theme.color("accent_dark"), 3))
                painter.drawLine(0, y, self.viewport().width(), y)

    def keyPressEvent(self, event):
        header = self.verticalHeader()
        if event.key() == Qt.Key.Key_Escape and isinstance(header, WorksheetRowHeader) and header.cancel_drag():
            event.accept()
            return
        if (event.text() == "=" and self.state() != QAbstractItemView.State.EditingState
                and not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                              | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier))
                and self.currentIndex().isValid() and not self.model().read_only
                and self.host.edit_formula_in_column(self.currentIndex().column())):
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.state() != QAbstractItemView.State.EditingState:
            self.clear()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.state() != QAbstractItemView.State.EditingState:
            self._advance_enter(event.modifiers())
            event.accept()
            return
        super().keyPressEvent(event)

    def _advance_enter(self, modifiers):
        current = self.currentIndex()
        if not current.isValid():
            return
        model = self.model()
        row, column = current.row(), current.column()
        first, end = (model.bands[column][:2] if column < len(model.bands) else (column, column + 1))
        step = -1 if modifiers & Qt.KeyboardModifier.ShiftModifier else 1
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            row += step
        elif first <= column + step < end:
            column += step
        else:
            row += step
            column = first if step > 0 else end - 1
        target = model.index(row, column)
        if target.isValid():
            self.setCurrentIndex(target)

    def closeEditor(self, editor, hint):
        if hint == QAbstractItemDelegate.EndEditHint.SubmitModelCache:
            modifiers = Qt.KeyboardModifier(editor.property("worksheetEnterModifiers") or 0)
            super().closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            self._advance_enter(modifiers)
            return
        super().closeEditor(editor, hint)

    def copy(self):
        box = self.box()
        model = self.model()
        if box is None:
            return False
        top, left, bottom, right = box
        right = min(right, len(model.frame.columns) - 1)
        if right < left:
            return False
        try:
            text = copy_block(model.frame, (top, left, bottom, right), model.excluded,
                              decimal_mark=clipboard_decimal_mark())
        except ValueError as error:
            self.host.error(error)
            return False
        clipboard = QGuiApplication.clipboard()
        windows = QGuiApplication.platformName() == "windows"
        expected = text.replace("\r\n", "\n")
        # Give a clipboard manager time to release the clipboard, even when Qt skips its own wait.
        for attempt in range(2 if windows else 1):
            if attempt:
                QThread.msleep(200)
            clipboard.setText(text)
            if windows and not clipboard.ownsClipboard():
                continue
            if clipboard.text().replace("\r\n", "\n") == expected:
                return True
        self.host.error(qt("qt.cell_clipboard_failed"))
        return False

    def cut(self):
        if self.copy():
            self.clear()

    def paste(self, *, transpose=False, special=False):
        text = QGuiApplication.clipboard().text()
        current = self.currentIndex()
        if not text or not current.isValid():
            return
        try:
            rows = clipboard_rows(text, transpose=transpose)
        except ValueError as error:
            self.host.error(error)
            return
        if special:
            header = self.model().headerData(current.column(), Qt.Orientation.Horizontal)
            dialog = PasteSpecialDialog(self, rows, f"{header} · {current.row() + 1}")
            try:
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                rows = dialog.result_rows
            finally:
                dialog.deleteLater()
        label = "Paste special" if special else "Paste transpose" if transpose else "Paste"
        self.host.paste_cells(current.row(), current.column(), rows, label=label)

    def clear(self):
        box = self.box()
        if box is not None:
            self.host.clear_cells(box)

    def _add_freeze_action(self, menu, column):
        model = self.model()
        if not model.read_only and model.dataset.can_freeze_worksheet_formula(column):
            menu.addAction(tr("worksheet.formula.freeze"),
                           lambda: self.host.freeze_worksheet_formula(column))

    def _can_series_column(self, column):
        model = self.model()
        if model is None or model.read_only or column < 0:
            return False
        if column == len(model.frame.columns):
            return model.grows_columns()
        if column > len(model.frame.columns):
            return False
        return column not in model.calculated and column not in model.locked and model.numeric[column]

    def _can_sort_column(self, column):
        model = self.model()
        if model is None or model.read_only or column < 0 or column >= len(model.frame.columns):
            return False
        if column in model.calculated:
            return False
        indices = model.dataset.source_indices
        if column >= len(indices) or indices[column] is None:
            return False
        return self.host.can_reorder_active_rows()

    def _heading_menu(self, position):
        heading = self.horizontalHeader()
        menu = QMenu(self)
        column = heading.logicalIndexAt(position)
        model = self.model()
        indices = model.dataset.source_indices
        if not model.read_only and 0 <= column < len(indices) and indices[column] is not None:
            menu.addAction(qt("qt.rename_column"), lambda: self.host.rename_column(column))
            if self.host.actions["variable_properties"].isEnabled():
                menu.addAction(tr("command.variable_properties"), lambda: self.host.edit_variable_properties(column))
        if self._can_series_column(column):
            menu.addAction(qt("qt.create_numeric_series"),
                           lambda: self.host.create_numeric_series(column=column, start_row=0, full_column=True))
        if self._can_sort_column(column):
            menu.addAction(qt("qt.sort_rows"), lambda: self.host.sort_rows(column=column))
        self._add_freeze_action(menu, column)
        if not menu.isEmpty():
            menu.exec(heading.viewport().mapToGlobal(position))
        menu.deleteLater()

    def _context_menu(self, position):
        index = self.indexAt(position)
        if index.isValid() and not self.selectionModel().isSelected(index):
            self.setCurrentIndex(index)
        menu = QMenu(self)
        for label, handler in ((tr("command.cut_cells"), self.cut), (tr("command.copy_cells"), self.copy),
                               (tr("ribbon.paste"), self.paste),
                               (ui("Paste Special…"), lambda: self.paste(special=True)),
                               (ui("Paste Transpose"), lambda: self.paste(transpose=True)),
                               (tr("command.clear_selected_cells"), self.clear)):
            menu.addAction(label, handler)
        menu.addSeparator()
        menu.addAction(qt("qt.insert_row"), self.host.insert_row)
        menu.addAction(qt("qt.delete_rows"), self.host.delete_rows)
        menu.addAction(qt("qt.insert_column"), self.host.insert_column)
        menu.addAction(self.host.actions["delete_columns"])
        menu.addAction(qt("qt.rename_column"), lambda: self.host.rename_column(self.currentIndex().column()))
        column = index.column() if index.isValid() else self.currentIndex().column()
        if self._can_series_column(column):
            menu.addAction(self.host.actions["create_numeric_series"])
        self._add_freeze_action(menu, self.columnAt(position.x()))
        menu.addSeparator()
        menu.addAction(tr("command.toggle_exclusion"), self.host.toggle_exclusion)
        menu.addSeparator()
        menu.addAction(self.host.actions["cell_background"])
        menu.addAction(self.host.actions["clear_cell_background"])
        menu.addAction(self.host.actions["number_format"])
        add_text_menu(menu, self.host)
        menu.exec(self.viewport().mapToGlobal(position))


class FrameView(QTableView):
    """A result table with copy (tab-separated, decimal point as in the classic grid)."""

    def __init__(self, frame, formatters=None, parent=None, *, backgrounds=None, number_formats=None,
                 text_styles=None, host=None, header_labels=None, result_display=None):
        super().__init__(parent)
        self.host = host
        self.setModel(FrameModel(frame, formatters, self, backgrounds=backgrounds, number_formats=number_formats,
                                 text_styles=text_styles, header_labels=header_labels, result_display=result_display))
        _setup(self)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        if self.model().text_styles:
            fit_rows(self)
        self._fit_columns()
        action = QAction(self)
        action.setShortcut(QKeySequence.StandardKey.Copy)
        action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        action.triggered.connect(self.copy)
        self.addAction(action)
        if host is not None:
            self.addActions([host.actions[key] for key in SELECTION_COMMANDS])
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._context_menu)

    def _context_menu(self, position):
        menu = QMenu(self)
        menu.addAction(tr("command.copy_cells"), self.copy)
        menu.addSeparator()
        for key in ("cell_background", "clear_cell_background", "number_format"):
            menu.addAction(self.host.actions[key])
        add_text_menu(menu, self.host)
        menu.exec(self.viewport().mapToGlobal(position))
        menu.deleteLater()

    def set_backgrounds(self, backgrounds):
        model = self.model()
        model.backgrounds = backgrounds
        if model.rowCount():
            model.dataChanged.emit(model.index(0, 0), model.index(model.rowCount() - 1, model.columnCount() - 1))

    def set_text_styles(self, text_styles):
        """Display only; the row height follows the largest size, the columns are fitted to the new fonts."""
        model = self.model()
        if text_styles == model.text_styles:
            return
        model.refresh_text(text_styles)
        fit_rows(self)
        self._fit_columns()

    def set_number_formats(self, number_formats):
        """Display only; the columns are fitted again to the new texts, the selection and scrolling stay."""
        model = self.model()
        if model.formats.formats == dict(number_formats or {}):
            return
        model.set_number_formats(number_formats)
        self._fit_columns()

    def _fit_columns(self):
        model = self.model()
        metrics = self.fontMetrics()
        scale = self.font().pointSizeF() / 9.5
        for column in range(model.columnCount()):
            title = str(model.headerData(column, Qt.Orientation.Horizontal) or "")
            widths = [metrics.horizontalAdvance(title)]
            for row in range(min(model.rowCount(), 100)):
                index = model.index(row, column)
                text = model.data(index) or ""
                font = model.data(index, Qt.ItemDataRole.FontRole)
                cell = QFontMetrics(font.resolve(self.font())) if font is not None else metrics
                widths.append(cell.horizontalAdvance(text))
            width = max(widths or [40]) + 24
            self.setColumnWidth(column, max(round(70 * scale), min(round(360 * scale), width)))

    def copy(self):
        box = selection_box(self)
        if box is None:
            return
        top, left, bottom, right = box
        model = self.model()
        lines = []
        if top == 0 and bottom == model.rowCount() - 1:
            lines.append("\t".join(model.plain_header(column) for column in range(left, right + 1)))
        for row in range(top, bottom + 1):
            # The stored numbers, not the number format on screen.
            lines.append("\t".join(model.plain_text(row, column) or "" for column in range(left, right + 1)))
        QGuiApplication.clipboard().setText("\n".join(lines) + "\n")


__all__ = ["WorksheetView", "FrameView", "display", "selection_box"]
