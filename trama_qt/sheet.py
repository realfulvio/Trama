"""Table views: the editable worksheet and the read-only result tables."""
from PySide6.QtCore import QRect, QThread, Qt
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
                               QHeaderView, QLabel, QMenu, QSpinBox, QTableView, QVBoxLayout)

from analisi.grid_data import clipboard_decimal_mark, clipboard_rows, copy_block, filter_clipboard_rows
from analisi.i18n import tr, ui

from . import theme
from .models import FrameModel, display
from .strings import qt


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


def selection_box(view):
    """The rectangle around the selected cells as (top, left, bottom, right), or the current cell."""
    indexes = view.selectionModel().selectedIndexes() if view.selectionModel() else []
    if not indexes:
        current = view.currentIndex()
        if not current.isValid():
            return None
        return current.row(), current.column(), current.row(), current.column()
    rows = [index.row() for index in indexes]
    columns = [index.column() for index in indexes]
    return min(rows), min(columns), max(rows), max(columns)


class WorksheetHeading(QHeaderView):
    """Draw the shared table, series and replicate headings over the worksheet columns."""

    def __init__(self, view):
        super().__init__(Qt.Orientation.Horizontal, view)
        self.view = view
        self.setSectionsClickable(True)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

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
            draw(QRect(left, 0, width, height), band, active, stripe=stripe)
            draw(QRect(left, height, width, height), title, active, title=True)
            if model.roles:
                for subcolumn in range(max(first, start), stop):
                    left = self.sectionViewportPosition(subcolumn)
                    if left > event.rect().right():
                        break
                    active = includes(subcolumn, subcolumn)
                    rect = QRect(left, 2 * height, self.sectionSize(subcolumn), height)
                    draw(rect, model.roles[subcolumn], active)
                    if active:
                        painter.fillRect(rect.x() + 1, rect.bottom() - 1, rect.width() - 1, 2, theme.color("accent"))
            column = stop


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


class WorksheetView(QTableView):
    """The data grid: typing, F2 and double click edit; Ctrl+C/X/V and Delete work on the selection."""

    def __init__(self, model, host, parent=None):
        super().__init__(parent)
        self.host = host
        heading = WorksheetHeading(self)
        self.setHorizontalHeader(heading)
        self.setModel(model)
        _setup(self)
        self.setObjectName("classicWorksheet")
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 4)
        self.verticalHeader().setMinimumWidth(36)
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        for column, (first, stop, band, title) in enumerate(model.bands):
            span = stop - first
            minimum = 76 if band == "Row titles" else 73 if span > 1 else 92 if model.roles else 105
            width = (max(heading.fontMetrics().horizontalAdvance(label) for label in (band, title)) + 16) // span
            self.setColumnWidth(column, max(minimum, min(248, width)))
        self.selectionModel().selectionChanged.connect(lambda *_: heading.viewport().update())
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

    def box(self):
        return selection_box(self)

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

    def keyPressEvent(self, event):
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
            current = self.currentIndex()
            if current.isValid():
                below = self.model().index(min(current.row() + 1, self.model().rowCount() - 1), current.column())
                self.setCurrentIndex(below)
                return
        super().keyPressEvent(event)

    def closeEditor(self, editor, hint):
        # Enter moves down, as in the classic grid and in spreadsheets.
        if hint == QAbstractItemDelegate.EndEditHint.SubmitModelCache:  # PySide6 has the enum on the delegate.
            hint = QAbstractItemDelegate.EndEditHint.NoHint
            super().closeEditor(editor, hint)
            current = self.currentIndex()
            if current.isValid() and current.row() + 1 < self.model().rowCount():
                self.setCurrentIndex(self.model().index(current.row() + 1, current.column()))
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

    def _heading_menu(self, position):
        heading = self.horizontalHeader()
        menu = QMenu(self)
        self._add_freeze_action(menu, heading.logicalIndexAt(position))
        if not menu.isEmpty():
            menu.exec(heading.viewport().mapToGlobal(position))
        menu.deleteLater()

    def _context_menu(self, position):
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
        menu.addAction(qt("qt.delete_columns"), self.host.delete_columns)
        menu.addAction(qt("qt.rename_column"), lambda: self.host.rename_column(self.currentIndex().column()))
        self._add_freeze_action(menu, self.columnAt(position.x()))
        menu.addSeparator()
        menu.addAction(tr("command.toggle_exclusion"), self.host.toggle_exclusion)
        menu.exec(self.viewport().mapToGlobal(position))


class FrameView(QTableView):
    """A result table with copy (tab-separated, decimal point as in the classic grid)."""

    def __init__(self, frame, formatters=None, parent=None):
        super().__init__(parent)
        self.setModel(FrameModel(frame, formatters, self))
        _setup(self)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self._fit_columns()
        action = QAction(self)
        action.setShortcut(QKeySequence.StandardKey.Copy)
        action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        action.triggered.connect(self.copy)
        self.addAction(action)

    def _fit_columns(self):
        model = self.model()
        metrics = self.fontMetrics()
        for column in range(model.columnCount()):
            title = str(model.headerData(column, Qt.Orientation.Horizontal) or "")
            texts = [model.data(model.index(row, column)) or "" for row in range(min(model.rowCount(), 100))]
            width = max([metrics.horizontalAdvance(text) for text in [title, *texts]] or [40]) + 24
            self.setColumnWidth(column, max(70, min(360, width)))

    def copy(self):
        box = selection_box(self)
        if box is None:
            return
        top, left, bottom, right = box
        model = self.model()
        lines = []
        if top == 0 and bottom == model.rowCount() - 1:
            lines.append("\t".join(str(model.headerData(column, Qt.Orientation.Horizontal) or "")
                                   for column in range(left, right + 1)))
        for row in range(top, bottom + 1):
            lines.append("\t".join(model.data(model.index(row, column)) or "" for column in range(left, right + 1)))
        QGuiApplication.clipboard().setText("\n".join(lines) + "\n")


__all__ = ["WorksheetView", "FrameView", "display", "selection_box"]
