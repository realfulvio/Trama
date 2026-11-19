"""Reshape long and wide in the Qt analysis dialog.

The editor replaces the generic fields of ``AnalysisDialog`` for this analysis: Direction, the ordered ID columns,
the Name and Value columns (Long to wide) or the ordered Measure columns with the two output names and Drop
missing values (Wide to long). Switching direction only hides the controls of the other direction, so whatever
was chosen there is still there when the user comes back. A Preview page shows the size of the result and its
first 25 rows and 12 columns; it runs the same checks as the calculation (``analisi.reshape_long_wide.preview``)
on a short timer, never on the whole matrix. The recipe keeps the canonical English keys and values of the
chosen direction only; captions and messages are translated.
"""
import re

import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QSizePolicy, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from analisi import reshape_long_wide as rl
from analisi.field_error import FieldError
from analisi.i18n import active_language, tr, translate_message

from . import theme

METHOD = rl.METHOD
FIELD_KEYS = {rl.DIRECTION: "reshape.field.direction", rl.ID_COLUMNS: "reshape.field.ids",
              rl.NAME_COLUMN: "reshape.field.name", rl.VALUE_COLUMN: "reshape.field.value",
              rl.MEASURE_COLUMNS: "reshape.field.measures", rl.OUTPUT_NAMES: "reshape.field.output_names",
              rl.OUTPUT_VALUES: "reshape.field.output_values", rl.DROP_MISSING: "reshape.field.drop"}
DIRECTION_KEYS = {rl.LONG_TO_WIDE: "reshape.choice.long_to_wide", rl.WIDE_TO_LONG: "reshape.choice.wide_to_long"}
_NUMBERS = ("count", "limit", "cells", "rows", "columns")
_QUOTED = re.compile(r'"([^"]*)"')
PREVIEW_DELAY_MS = 150


def _thousands(text):
    return text.replace(",", ".") if active_language() == "it" else text


def message(error):
    """An engine or dialog error of this analysis in the active language."""
    return translate_message(str(error), "reshape.error.", {name: _thousands for name in _NUMBERS})


def _number(value):
    return _thousands(f"{value:,}")


def _plural(key, count):
    return tr(f"{key}_one" if count == 1 else f"{key}_many", count=_number(count))


def _note(text):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _caption(field):
    label = QLabel(tr(FIELD_KEYS[field]))
    label.setWordWrap(True)
    label.setMinimumWidth(150)
    label.setMaximumWidth(230)
    return label


def _cell(value):
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return rl.level_name(value) if not isinstance(value, str) else value


class OrderedColumns(QWidget):
    """Checkable columns in a chosen order: checked columns are used from top to bottom; the arrows move the
    current column. ``changed`` callbacks run after every check or move."""

    def __init__(self, columns, selected, name, parent=None):
        super().__init__(parent)
        self.callbacks = []
        self.checked = []  # called with a column the user has just checked
        selected = [column for column in selected if column in columns]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.list = QListWidget()
        self.list.setObjectName(name)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setAccessibleName(name)
        for column in [*selected, *(column for column in columns if column not in selected)]:
            item = QListWidgetItem(column)
            item.setData(Qt.ItemDataRole.UserRole, column)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if column in selected else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.setFixedHeight(max(78, min(176, 24 * self.list.count() + 8)))
        self.list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.list.itemChanged.connect(self._item_changed)
        self.list.currentRowChanged.connect(lambda _row: self._buttons())
        layout.addWidget(self.list, 1, Qt.AlignmentFlag.AlignTop)
        arrows = QVBoxLayout()
        arrows.setSpacing(4)
        self.up, self.down = QToolButton(), QToolButton()
        for button, icon, key, step in ((self.up, "chevron-up", "reshape.caption.up", -1),
                                        (self.down, "chevron-down", "reshape.caption.down", 1)):
            button.setIcon(theme.icon(icon))
            button.setAutoRaise(True)
            button.setToolTip(tr(key))
            button.setAccessibleName(tr(key))
            button.clicked.connect(lambda _checked=False, step=step: self.move(step))
            arrows.addWidget(button)
        arrows.addStretch(1)
        layout.addLayout(arrows)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._buttons()

    def _buttons(self):
        row = self.list.currentRow()
        self.up.setEnabled(row > 0)
        self.down.setEnabled(0 <= row < self.list.count() - 1)
        item = self.list.currentItem()
        if item is not None:
            column = item.data(Qt.ItemDataRole.UserRole)
            self.up.setAccessibleName(tr("reshape.caption.move_up", column=column))
            self.down.setAccessibleName(tr("reshape.caption.move_down", column=column))

    def _item_changed(self, item):
        if item.checkState() == Qt.CheckState.Checked:
            for callback in self.checked:
                callback(item.data(Qt.ItemDataRole.UserRole))
        self._changed()

    def uncheck(self, column):
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == column and item.checkState() == Qt.CheckState.Checked:
                item.setCheckState(Qt.CheckState.Unchecked)  # itemChanged runs the callbacks

    def _changed(self):
        for callback in self.callbacks:
            callback()

    def move(self, step):
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        self.list.blockSignals(True)
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)
        self.list.blockSignals(False)
        self._buttons()
        self._changed()

    def values(self):
        return [self.list.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.list.count())
                if self.list.item(row).checkState() == Qt.CheckState.Checked]

    def set_values(self, columns):
        """Check exactly ``columns``, in this order, at the top of the list."""
        self.list.blockSignals(True)
        for position, column in enumerate(columns):
            for row in range(self.list.count()):
                if self.list.item(row).data(Qt.ItemDataRole.UserRole) == column:
                    self.list.insertItem(position, self.list.takeItem(row))
                    break
        for row in range(self.list.count()):
            item = self.list.item(row)
            checked = item.data(Qt.ItemDataRole.UserRole) in columns
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self._buttons()
        self._changed()

    def select(self, column):
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == column:
                self.list.setCurrentRow(row)
                return True
        return False

    def setFocus(self):  # noqa: N802 - Qt naming
        self.list.setFocus()


class ReshapeEditor:
    """Binds the fields of Reshape long and wide in an AnalysisDialog: pages, values, checks, focus, preview."""

    def __init__(self, dialog, pages, saved):
        self.dialog = dialog
        frame = dialog.data
        columns = [str(name) for name in frame.columns]
        numeric = [str(name) for name in frame.select_dtypes(include="number").columns]
        text = [name for name in columns if name not in numeric]
        chosen = saved.get(rl.DIRECTION) if saved.get(rl.DIRECTION) in rl.DIRECTIONS else rl.LONG_TO_WIDE
        ids = [name for name in saved.get(rl.ID_COLUMNS) or [] if isinstance(name, str)] or columns[:1]
        form = pages["variables"]

        self.direction = QComboBox()
        self.direction.setObjectName("reshapeDirection")
        for value in rl.DIRECTIONS:
            self.direction.addItem(tr(DIRECTION_KEYS[value]), value)
        self.direction.setCurrentIndex(self.direction.findData(chosen))
        form.addRow(_caption(rl.DIRECTION), self.direction)
        self.direction_note = _note("")
        form.addRow(self.direction_note)

        self.ids = OrderedColumns(columns, ids, "reshapeIdColumns")
        form.addRow(_caption(rl.ID_COLUMNS), self.ids)
        form.addRow(_note(tr("reshape.note.ids")))

        # Long to wide
        name = saved.get(rl.NAME_COLUMN) if chosen == rl.LONG_TO_WIDE else None
        value = saved.get(rl.VALUE_COLUMN) if chosen == rl.LONG_TO_WIDE else None
        name = name or next((column for column in text if column not in ids), None) or next(
            (column for column in columns if column not in ids), "")
        value = value or next((column for column in reversed(numeric) if column not in ids and column != name),
                              None) or next((column for column in reversed(columns)
                                             if column not in ids and column != name), "")
        self.name = self._columns(columns, name, "reshapeNameColumn")
        self.value = self._columns(columns, value, "reshapeValueColumn")
        self.wide_rows = [(_caption(rl.NAME_COLUMN), self.name), (_caption(rl.VALUE_COLUMN), self.value)]
        for caption, widget in self.wide_rows:
            form.addRow(caption, widget)

        # Wide to long
        measures = saved.get(rl.MEASURE_COLUMNS) if chosen == rl.WIDE_TO_LONG else None
        measures = [column for column in measures or [] if isinstance(column, str)] or [
            column for column in numeric if column not in ids]
        self.measures = OrderedColumns(columns, measures, "reshapeMeasureColumns")
        self.names = QLineEdit(str(saved.get(rl.OUTPUT_NAMES, rl.DEFAULT_NAMES)) if chosen == rl.WIDE_TO_LONG
                               else rl.DEFAULT_NAMES)
        self.names.setObjectName("reshapeOutputNames")
        self.values_name = QLineEdit(str(saved.get(rl.OUTPUT_VALUES, rl.DEFAULT_VALUES)) if chosen == rl.WIDE_TO_LONG
                                     else rl.DEFAULT_VALUES)
        self.values_name.setObjectName("reshapeOutputValues")
        self.drop = QCheckBox(tr(FIELD_KEYS[rl.DROP_MISSING]))
        self.drop.setObjectName("reshapeDropMissing")
        self.drop.setChecked(bool(saved.get(rl.DROP_MISSING, False)) if chosen == rl.WIDE_TO_LONG else False)
        measures_note, drop_note = _note(tr("reshape.note.measures")), _note(tr("reshape.note.drop"))
        self.long_rows = [(_caption(rl.MEASURE_COLUMNS), self.measures), (None, measures_note),
                          (_caption(rl.OUTPUT_NAMES), self.names), (_caption(rl.OUTPUT_VALUES), self.values_name),
                          (None, self.drop), (None, drop_note)]
        for caption, widget in self.long_rows:
            if caption is None:
                form.addRow(widget)
            else:
                form.addRow(caption, widget)

        self.summary = _note("")
        self.summary.setObjectName("reshapeSummary")
        form.addRow(self.summary)
        self.form = form
        self.fields = {rl.DIRECTION: self.direction, rl.ID_COLUMNS: self.ids, rl.NAME_COLUMN: self.name,
                       rl.VALUE_COLUMN: self.value, rl.MEASURE_COLUMNS: self.measures, rl.OUTPUT_NAMES: self.names,
                       rl.OUTPUT_VALUES: self.values_name, rl.DROP_MISSING: self.drop}
        self._build_preview()

        self.timer = QTimer(dialog)
        self.timer.setSingleShot(True)
        self.timer.setInterval(PREVIEW_DELAY_MS)
        self.timer.timeout.connect(lambda: self.refresh_preview(edited=True))
        self.direction.currentIndexChanged.connect(self._direction_changed)
        for widget in (self.name, self.value):
            widget.currentIndexChanged.connect(self.schedule)
        for widget in (self.names, self.values_name):
            widget.textChanged.connect(self.schedule)
        self.drop.toggled.connect(self.schedule)
        # A column has one role: checking it as an ID unchecks it as a measure, and the other way round.
        self.ids.checked.append(lambda column: self.measures.uncheck(column))
        self.measures.checked.append(lambda column: self.ids.uncheck(column))
        self.ids.callbacks.append(self.schedule)
        self.measures.callbacks.append(self.schedule)
        self._direction_changed()
        self.refresh_preview()

    @staticmethod
    def _columns(columns, current, name):
        box = QComboBox()
        box.setObjectName(name)
        box.setMinimumContentsLength(18)
        for column in columns:
            box.addItem(column, column)
        position = box.findData(current)
        if position < 0 and current:
            box.addItem(current, current)  # a column that is gone stays visible; the check names it
            position = box.count() - 1
        box.setCurrentIndex(max(position, 0))
        return box

    def _build_preview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        title = QLabel(tr("reshape.preview.title"))
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.preview_summary = _note("")
        self.preview_summary.setObjectName("reshapePreviewSummary")
        layout.addWidget(self.preview_summary)
        self.preview_error = QLabel()
        self.preview_error.setObjectName("errorBanner")
        self.preview_error.setWordWrap(True)
        self.preview_error.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_error.setVisible(False)
        layout.addWidget(self.preview_error)
        self.table = QTableWidget(0, 0)
        self.table.setObjectName("reshapePreview")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(110)
        layout.addWidget(self.table, 1)
        self.hidden_note = _note("")
        self.hidden_note.setObjectName("reshapePreviewHidden")
        layout.addWidget(self.hidden_note)
        layout.addWidget(_note(tr("reshape.preview.limit", rows=rl.PREVIEW_ROWS, columns=rl.PREVIEW_COLUMNS)))
        self.preview_page = page
        self.dialog.tabs.addTab(page, tr("reshape.tab.preview"))

    # -- state --------------------------------------------------------------------------------------
    def chosen(self):
        return self.direction.currentData()

    def _direction_changed(self, _index=None):
        wide = self.chosen() == rl.LONG_TO_WIDE
        for caption, widget in self.wide_rows:
            self.form.setRowVisible(widget, wide)
        for caption, widget in self.long_rows:
            self.form.setRowVisible(widget, not wide)
        for widget in (self.ids, self.measures):
            widget.list.doItemsLayout()  # item sizes measured while hidden are stale
        self.direction_note.setText(tr("reshape.note.long_to_wide" if wide else "reshape.note.wide_to_long"))
        self.schedule()

    def schedule(self, *_args):
        self.timer.start()

    def options(self):
        values = {rl.DIRECTION: self.chosen(), rl.ID_COLUMNS: self.ids.values()}
        if self.chosen() == rl.LONG_TO_WIDE:
            values[rl.NAME_COLUMN] = self.name.currentData() or ""
            values[rl.VALUE_COLUMN] = self.value.currentData() or ""
        else:
            values[rl.MEASURE_COLUMNS] = self.measures.values()
            values[rl.OUTPUT_NAMES] = self.names.text()
            values[rl.OUTPUT_VALUES] = self.values_name.text()
            values[rl.DROP_MISSING] = self.drop.isChecked()
        return values

    def check(self, options):
        """The checks of the calculation, on the keys and levels only (the matrix is built on the worker)."""
        rl.plan(self.dialog.data, options)

    # -- preview ------------------------------------------------------------------------------------
    def refresh_preview(self, *, edited=False):
        """Recount and redraw the preview. After an edit, a recipe that passes the checks clears the error banner
        of an earlier Run (the first preview leaves an engine error that reopened the dialog on screen)."""
        self.timer.stop()
        try:
            result = rl.preview(self.dialog.data, self.options())
        except (FieldError, ValueError, OverflowError) as error:
            text = tr("reshape.preview.error", message=message(error))
            self.preview_error.setText(text)
            self.preview_error.setVisible(True)
            self.preview_summary.setText("")
            self.summary.setText(text)
            self.hidden_note.setText("")
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.last_preview = None
            return None
        self.preview_error.setVisible(False)
        if edited:
            self.dialog.banner.setVisible(False)
        summary = tr("reshape.preview.summary", rows=_plural("reshape.preview.rows", result.rows),
                     columns=_plural("reshape.preview.columns", result.columns),
                     mapped=_number(result.mapped), missing=_number(result.missing))
        self.preview_summary.setText(summary)
        self.summary.setText(summary)
        notes = []
        if result.hidden_rows:
            notes.append(_plural("reshape.preview.hidden_rows", result.hidden_rows))
        if result.hidden_columns:
            notes.append(_plural("reshape.preview.hidden_columns", result.hidden_columns))
        self.hidden_note.setText(" ".join(notes) or tr("reshape.preview.complete"))
        table = result.table
        self.table.clear()
        self.table.setRowCount(len(table))
        self.table.setColumnCount(len(table.columns))
        self.table.setHorizontalHeaderLabels([str(name) for name in table.columns])
        for column, name in enumerate(table.columns):
            values = table[name].tolist()
            for row, value in enumerate(values):
                item = QTableWidgetItem(_cell(value))
                if not isinstance(value, str) and item.text():
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
        self.last_preview = result
        return result

    # -- errors -------------------------------------------------------------------------------------
    def focus(self, field, error=None):
        widget = self.fields.get(field)
        if widget is None:
            return False
        tabs = self.dialog.tabs
        for index in range(tabs.count()):
            scroll = tabs.widget(index)
            inner = scroll.widget() if hasattr(scroll, "widget") else None
            if inner is not None and inner.layout() is self.form:
                tabs.setCurrentIndex(index)
                scroll.ensureWidgetVisible(widget)
                break
        if isinstance(widget, OrderedColumns):
            for column in _QUOTED.findall(str(error or "")):
                if widget.select(column):
                    break
        widget.setFocus()
        return True


def attach(dialog, pages, saved):
    """The reshape editor when the dialog shows Reshape long and wide, else None."""
    if dialog.method != METHOD:
        return None
    return ReshapeEditor(dialog, pages, saved)


__all__ = ["METHOD", "OrderedColumns", "ReshapeEditor", "attach", "message"]
