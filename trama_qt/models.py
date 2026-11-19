"""Virtual table models: a worksheet (editable) and a result table (read-only)."""
import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QBrush, QFont

from analisi.data import EDITABLE_PRISM_FIXED_VALUES, EDITABLE_PRISM_XY

from . import theme

SPARE_ROWS = 50


def display(value):
    """The cell text of the classic grid: blank for missing values, ten significant digits."""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (float, np.floating)):
        return f"{value:.10g}"
    return str(value)


def column_label(index):
    """A, B, …, Z, AA, AB… (the spreadsheet letters of the classic grid)."""
    label = ""
    while index >= 0:
        index, letter = divmod(index, 26)
        label = chr(65 + letter) + label
        index -= 1
    return label


def _numeric(series):
    return pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype)


class WorksheetModel(QAbstractTableModel):
    """A data table as the window shows it: source columns, calculated columns, then room to type."""

    def __init__(self, dataset, edit, *, read_only=False, parent=None):
        super().__init__(parent)
        self.dataset = dataset
        self.edit = edit
        self.read_only = read_only
        self.reload()

    def reload(self):
        """Read the table again. Same shape: cells change in place, so selection and the current cell stay."""
        before = (self.rowCount(), self.columnCount()) if hasattr(self, "frame") else None
        try:
            frame = self.dataset.frame()
        except Exception:  # A formula that cannot be evaluated still shows the source cells.
            frame = self.dataset.raw.copy()
        reset = before is None
        if reset or before != self._shape(frame):
            self.beginResetModel()
            reset = True
        self.frame = frame
        self.source_columns = len(self.dataset.raw.columns)
        self.numeric = [_numeric(frame.iloc[:, index]) for index in range(len(frame.columns))]
        self.locked = set(self.dataset.locked_columns)
        if reset:
            self.endResetModel()
        elif self.rowCount() and self.columnCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    def _shape(self, frame):
        rows = len(frame) + (SPARE_ROWS if self.grows_rows() else 0)
        columns = len(frame.columns) + (1 if self.grows_columns() else 0)
        return rows, columns

    def grows_rows(self):
        fixed = self.dataset.table_format == EDITABLE_PRISM_XY or self.dataset.table_format in EDITABLE_PRISM_FIXED_VALUES
        return not self.read_only and not fixed

    def grows_columns(self):
        return self.grows_rows() and not self.dataset.formulas

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.frame) + (SPARE_ROWS if self.grows_rows() else 0)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.frame.columns) + (1 if self.grows_columns() else 0)

    def in_frame(self, row, column):
        return row < len(self.frame) and column < len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, column = index.row(), index.column()
        inside = self.in_frame(row, column)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return display(self.frame.iat[row, column]) if inside else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            numeric = column < len(self.numeric) and self.numeric[column]
            horizontal = Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft
            return int(horizontal | Qt.AlignmentFlag.AlignVCenter)
        excluded = (row, column) in self.dataset.excluded
        if role == Qt.ItemDataRole.ForegroundRole:
            if excluded:
                return QBrush(theme.color("error"))
            if column >= self.source_columns:
                return QBrush(theme.color("accent_dark"))
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            if column >= self.source_columns and column < len(self.frame.columns):
                return QBrush(theme.color("panel2"))
            return None
        if role == Qt.ItemDataRole.FontRole and excluded:
            font = QFont()
            font.setItalic(True)
            font.setStrikeOut(True)
            return font
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        name = str(self.frame.columns[section]) if section < len(self.frame.columns) else ""
        return f"{column_label(section)}\n{name}"

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.read_only or not index.isValid():
            return base
        column = index.column()
        if column >= self.source_columns and column < len(self.frame.columns):
            return base  # Calculated column.
        if column in self.locked:
            return base
        if column >= len(self.frame.columns) and not self.grows_columns():
            return base
        if index.row() >= len(self.frame) and not self.grows_rows():
            return base
        return base | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if str(value) == self.data(index):
            return False
        # Applied after the editor closes: the edit can grow or reload the table.
        row, column, text = index.row(), index.column(), str(value)
        QTimer.singleShot(0, lambda: self.edit(row, column, text))
        return True


class FrameModel(QAbstractTableModel):
    """A read-only result table; the row labels become the first column, as in the classic grid."""

    def __init__(self, frame, formatters=None, parent=None):
        super().__init__(parent)
        self.frame = frame
        self.index_title = str(frame.index.name or "Row") if not isinstance(frame.index, pd.MultiIndex) \
            else " / ".join(str(name or "") for name in frame.index.names) or "Row"
        self.formatters = formatters or {}
        self.numeric = [_numeric(frame.iloc[:, index]) for index in range(len(frame.columns))]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns) + 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, column = index.row(), index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                label = self.frame.index[row]
                return " · ".join(display(part) for part in label) if isinstance(label, tuple) else display(label)
            name = self.frame.columns[column - 1]
            formatter = self.formatters.get(name, display)
            return formatter(self.frame.iat[row, column - 1])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            numeric = column > 0 and self.numeric[column - 1]
            horizontal = Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft
            return int(horizontal | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.BackgroundRole and row % 2:
            return QBrush(theme.color("panel2"))
        if role == Qt.ItemDataRole.ForegroundRole and column == 0:
            return QBrush(theme.color("text2"))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role != Qt.ItemDataRole.DisplayRole or orientation == Qt.Orientation.Vertical:
            return None
        return self.index_title if section == 0 else str(self.frame.columns[section - 1])
