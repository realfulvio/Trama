"""Virtual table models: a worksheet (editable) and a result table (read-only)."""
import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont

from analisi.data import EDITABLE_LEGACY_FIXED_VALUES, EDITABLE_LEGACY_XY
from analisi.grid_headings import column_label, heading_bands
from analisi.worksheet_appearance import text_on_background
from analisi.worksheet_number_format import Renderer, edit_text
from analisi.worksheet_text import ALIGN, BOLD, COLOR, FONT, ITALIC, SIZE, UNDERLINE, TextStyles

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


def _numeric(series):
    return pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype)


_ALIGNMENTS = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
               "right": Qt.AlignmentFlag.AlignRight}


class TextStyleRoles:
    """Font, colour and alignment roles of the cells whose text has a style, shared by both table models.

    A style only changes how a cell is drawn: the number it shows, edits and copies is untouched. A font
    returned here sets just the attributes the style names, so the rest comes from the table font (and its
    zoom) through ``QFont.resolve``. ``text_scale`` carries the table zoom for an explicit size."""

    text_styles = TextStyles()
    text_scale = 1.0

    def _style(self, key, row):
        return self.text_styles.style_at(key, row) if self.text_styles else {}

    def cell_style(self, column, row):
        """The text style attributes of a cell (empty when everything is inherited): what a print or an export reads."""
        raise NotImplementedError

    def styled_font(self, style, excluded=False):
        """The font role of a cell: the style's attributes, plus the marks of an excluded value."""
        if not style and not excluded:
            return None
        cache = self.__dict__.setdefault("_font_cache", {})
        key = (tuple(style.items()), excluded, self.text_scale)
        font = cache.get(key)
        if font is None:
            font = cache[key] = QFont()
            if FONT in style:
                font.setFamily(style[FONT])
            if SIZE in style:
                font.setPointSizeF(style[SIZE] * self.text_scale)
            if style.get(BOLD):
                font.setBold(True)
            if style.get(ITALIC) or excluded:
                font.setItalic(True)
            if style.get(UNDERLINE):
                font.setUnderline(True)
            if excluded:
                font.setStrikeOut(True)
        return font

    def styled_alignment(self, style, numeric):
        horizontal = _ALIGNMENTS.get(style.get(ALIGN)) or (
            Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft)
        return int(horizontal | Qt.AlignmentFlag.AlignVCenter)

    def styled_color(self, style):
        return QBrush(QColor(style[COLOR])) if COLOR in style else None

    def refresh_text(self, text_styles=None, scale=None):
        """Read the text styles again (or the zoom): the roles of every cell change, the cells themselves not."""
        if text_styles is not None:
            self.text_styles = text_styles
        if scale is not None:
            self.text_scale = scale
        if self.rowCount() and self.columnCount():
            roles = [Qt.ItemDataRole.FontRole, Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.TextAlignmentRole]
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1), roles)


class WorksheetModel(TextStyleRoles, QAbstractTableModel):
    """A data table as the window shows it, with calculated columns in worksheet order."""

    def __init__(self, dataset, edit, *, read_only=False, parent=None):
        super().__init__(parent)
        self.dataset = dataset
        self.edit = edit
        self.read_only = read_only
        self.pending = []  # Typed cells waiting for the editor to close (see ``setData``).
        self.reload()

    def reload(self):
        """Read the table again. Same shape: cells change in place, so selection and the current cell stay."""
        before = (self.rowCount(), self.columnCount()) if hasattr(self, "frame") else None
        try:
            frame = self.dataset.frame()
        except Exception:  # A formula that cannot be evaluated still shows the source cells.
            frame = self.dataset.raw.reindex(columns=self.dataset.columns)
        reset = before is None
        if reset or before != self._shape(frame):
            self.beginResetModel()
            reset = True
        self.frame = frame
        self.source_columns = len(self.dataset.raw.columns)
        self.calculated = {column for column, name in enumerate(frame.columns) if name in self.dataset.formulas}
        names = [f"ƒx   {name}" if column in self.calculated else str(name)
                 for column, name in enumerate(frame.columns)]
        self.bands, self.roles = heading_bands(frame, names, self.source_columns, self.dataset.table_format,
                                               calculated=self.calculated)
        self.numeric = [_numeric(frame.iloc[:, index]) for index in range(len(frame.columns))]
        locks = set(self.dataset.locked_columns)
        self.locked = {column for column, source in enumerate(self.dataset.source_indices) if source in locks}
        self.excluded = self.dataset.worksheet_excluded
        self.formats = Renderer(self.dataset.displayed_number_formats)
        self.text_styles = self.dataset.text_styles
        if reset:
            self.endResetModel()
        elif self.rowCount() and self.columnCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    def cell_style(self, column, row):
        return self._style(self.frame.columns[column], row) if 0 <= column < len(self.frame.columns) else {}

    def refresh_backgrounds(self):
        if self.rowCount() and self.columnCount():
            roles = [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole]
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1), roles)

    def refresh_formats(self):
        """Read the number formats again; selection, current cell and scrolling stay where they are."""
        self.formats = Renderer(self.dataset.displayed_number_formats)
        if self.rowCount() and self.columnCount():
            roles = [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole]
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1), roles)

    def _shape(self, frame):
        rows = len(frame) + (SPARE_ROWS if self.grows_rows() else 0)
        columns = len(frame.columns) + (1 if self.grows_columns() else 0)
        return rows, columns

    def grows_rows(self):
        fixed = self.dataset.table_format == EDITABLE_LEGACY_XY or self.dataset.table_format in EDITABLE_LEGACY_FIXED_VALUES
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
            if not inside:
                return ""
            value = self.frame.iat[row, column]
            if self.formats and (text := self.formats.text(column, value)) is not None:
                # The cell shows the format; its editor starts from the stored, unrounded number.
                return text if role == Qt.ItemDataRole.DisplayRole else edit_text(value)
            return display(value)
        style = self._style(self.frame.columns[column], row) if inside else {}
        if role == Qt.ItemDataRole.TextAlignmentRole:
            numeric = column < len(self.numeric) and self.numeric[column]
            return self.styled_alignment(style, numeric)
        excluded = (row, column) in self.excluded
        background = self.dataset.cell_backgrounds.get((row, self.frame.columns[column])) if inside else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if brush := self.styled_color(style):
                return brush
            if background:
                return QBrush(QColor(text_on_background(background)))
            if excluded:
                return QBrush(theme.color("error"))
            if column in self.calculated or column >= len(self.frame.columns):
                return QBrush(theme.color("accent_dark"))
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            if background:
                return QBrush(QColor(background))
            if column in self.calculated:
                return QBrush(theme.color("panel2"))
            if not inside:
                return QBrush(theme.color("panel"))
            return None
        if role == Qt.ItemDataRole.FontRole:
            return self.styled_font(style, excluded)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        if section < len(self.bands):
            _, _, band, title = self.bands[section]
            role = self.roles[section] if self.roles else ""
            return "\n".join(filter(None, (band, title, role)))
        return column_label(section)

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.read_only or not index.isValid():
            return base
        column = index.column()
        if column in self.calculated:
            return base  # Calculated column.
        if column in self.locked:
            return base
        if column >= len(self.frame.columns) and not self.grows_columns():
            return base
        if index.row() >= len(self.frame) and not self.grows_rows():
            return base
        return base | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not (self.flags(index) & Qt.ItemFlag.ItemIsEditable):
            return False
        if str(value) == self.data(index, Qt.ItemDataRole.EditRole):
            return False
        # Applied after the editor closes: the edit can grow or reload the table.
        self.pending.append((index.row(), index.column(), str(value)))
        QTimer.singleShot(0, self.flush_edits)
        return True

    def flush_edits(self):
        """Apply the typed cells now (the window calls this before it leaves the project tab)."""
        pending, self.pending = self.pending, []
        for row, column, text in pending:
            self.edit(row, column, text)


class FrameModel(TextStyleRoles, QAbstractTableModel):
    """A read-only result table; the row labels become the first column, as in the classic grid."""

    def __init__(self, frame, formatters=None, parent=None, *, backgrounds=None, number_formats=None,
                 text_styles=None):
        super().__init__(parent)
        self.text_styles = text_styles or TextStyles()
        self.frame = frame
        self.index_title = str(frame.index.name or "Row") if not isinstance(frame.index, pd.MultiIndex) \
            else " / ".join(str(name or "") for name in frame.index.names) or "Row"
        self.formatters = formatters or {}
        self.backgrounds = backgrounds or {}
        self.formats = Renderer(number_formats)
        self.numeric = [_numeric(frame.iloc[:, index]) for index in range(len(frame.columns))]

    def cell_style(self, column, row):
        return self._style(column, row)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns) + 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, column = index.row(), index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if (column and self.formats and self.frame.columns[column - 1] not in self.formatters
                    and (text := self.formats.text(column, self.frame.iat[row, column - 1])) is not None):
                return text  # A column formatted by its analysis (ROC thresholds) keeps that renderer.
            return self.plain_text(row, column)
        style = self._style(column, row)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            numeric = column > 0 and self.numeric[column - 1]
            return self.styled_alignment(style, numeric)
        if role == Qt.ItemDataRole.FontRole:
            return self.styled_font(style)
        background = self.backgrounds.get((row, column))
        if background and role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(QColor(background))
        if role == Qt.ItemDataRole.ForegroundRole and (brush := self.styled_color(style)):
            return brush
        if background and role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(QColor(text_on_background(background)))
        if role == Qt.ItemDataRole.BackgroundRole and row % 2:
            return QBrush(theme.color("panel2"))
        if role == Qt.ItemDataRole.ForegroundRole and column == 0:
            return QBrush(theme.color("text2"))
        return None

    def plain_text(self, row, column):
        """The text without a number format: what Copy writes, so the clipboard keeps the stored digits."""
        if column == 0:
            label = self.frame.index[row]
            return " · ".join(display(part) for part in label) if isinstance(label, tuple) else display(label)
        name = self.frame.columns[column - 1]
        formatter = self.formatters.get(name, display)
        return formatter(self.frame.iat[row, column - 1])

    def set_number_formats(self, number_formats):
        self.formats = Renderer(number_formats)
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1),
                                  [Qt.ItemDataRole.DisplayRole])

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role != Qt.ItemDataRole.DisplayRole or orientation == Qt.Orientation.Vertical:
            return None
        return self.index_title if section == 0 else str(self.frame.columns[section - 1])
