"""Edit the headings of an existing data table without changing recipe column keys."""
from dataclasses import replace

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView, QLabel,
                               QSpinBox, QTableView, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from analisi.i18n import tr, ui
from .strings import qt
from .theme import fit_dialog


class TitleList(QAbstractTableModel):
    def __init__(self, rows, parent):
        super().__init__(parent)
        self.rows = rows

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 1

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole:
            return qt("qt.heading_title") if orientation == Qt.Orientation.Horizontal else self.rows[section][0]
        return None

    def data(self, index, role):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self.rows[index.row()][1]
        return None

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsEditable if index.isValid() else Qt.ItemFlag.NoItemFlags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole or len(str(value)) > 512:
            return False
        self.rows[index.row()][1] = str(value)
        self.dataChanged.emit(index, index, [role, Qt.ItemDataRole.DisplayRole])
        return True


class TableFormatDialog(QDialog):
    def __init__(self, parent, model, *, tab=0, column=0, update_structure=None, replicate_limits=None, x_block=None):
        super().__init__(parent)
        self.source = model
        self.update_structure = update_structure
        self.x_block = x_block
        self.x_error = None
        self.affected_runs = None
        self.replicate_count = None
        self.initial_count = None
        self.original = model.dataset.worksheet_titles
        self.title_groups = model.title_columns
        self.replicates = model.replicate_columns
        self.common = dict(self.original.common)
        self.individual = dict(self.original.individual)
        self.setWindowTitle(qt("qt.format_data_table").rstrip("…"))
        fit_dialog(self, 510, 390)
        QShortcut(QKeySequence("F1"), self, parent.show_shortcuts)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        options = QWidget()
        form = QFormLayout(options)
        kind = model.dataset.table_format
        family = "XY" if kind.casefold().startswith("xy") else ui(kind)
        form.addRow(qt("qt.table_kind"), QLabel(family))
        self.show_rows = self.check("qt.heading_rows", self.original.show_rows)
        self.show_rows.setEnabled(any(band == "Row titles" for _, _, band, _ in model.bands))
        self.show_rows.setChecked(self.show_rows.isEnabled() and self.original.show_rows)
        form.addRow(self.show_rows)
        self.widths = self.check("qt.heading_widths", self.original.automatic_widths)
        form.addRow(self.widths)
        if x_block is not None:
            self.x_error = self.check("qt.x_error_column", bool(x_block[1]))
            self.x_error.setToolTip(qt("qt.x_error_column_hint"))
            form.addRow(self.x_error)
        if replicate_limits is not None:
            self.initial_count, maximum = replicate_limits
            self.replicate_count = QSpinBox()
            self.replicate_count.setRange(2, maximum)
            self.replicate_count.setValue(self.initial_count)
            form.addRow(qt("qt.replicate_count"), self.replicate_count)
            note = QLabel(qt("qt.replicate_count_note"))
            note.setWordWrap(True)
            form.addRow(note)
        self.preview = QTableWidget()
        self.preview.setAccessibleName(tr("setup.preview_title"))
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        form.addRow(QLabel(tr("setup.preview_title")))
        form.addRow(self.preview)
        self.tabs.addTab(options, qt("qt.table_format_tab"))
        columns = QWidget()
        col_layout = QVBoxLayout(columns)
        self.columns = self.grid(columns)
        self.columns.setModel(TitleList([[model.band_label(c), model.group_title(c)] for c in self.title_groups],
                                        self.columns))
        col_layout.addWidget(self.columns)
        self.tabs.addTab(columns, qt("qt.column_titles"))
        self.tabs.setTabEnabled(1, bool(self.title_groups))

        subcolumns = QWidget()
        sub_layout = QVBoxLayout(subcolumns)
        self.show_subtitles = self.check("qt.show_subtitles", self.original.show_subtitles)
        self.shared = self.check("qt.shared_subtitles", self.original.shared)
        sub_layout.addWidget(self.show_subtitles)
        sub_layout.addWidget(self.shared)
        self.subcolumns = self.grid(subcolumns)
        sub_layout.addWidget(self.subcolumns)
        self.tabs.addTab(subcolumns, qt("qt.subcolumn_titles"))
        self.tabs.setTabEnabled(2, bool(self.replicates))
        self.subrows = []
        self.shared_mode = self.shared.isChecked()
        self.populate_subcolumns()
        self.shared.toggled.connect(self.switch_mode)
        self.tabs.currentChanged.connect(self.refresh_preview)
        self.show_rows.toggled.connect(lambda: self.refresh_preview(0))
        self.refresh_preview(0)
        self.tabs.setCurrentIndex(tab if self.tabs.isTabEnabled(tab) else 0)
        if 0 <= column < len(model.bands):
            start = model.bands[column][0]
            if start in self.title_groups:
                self.columns.selectRow(self.title_groups.index(start))
            if column in self.replicates:
                key = self.rep_key(column, self.shared_mode)
                self.subcolumns.selectRow(self.subrows.index(key))
        if self.tabs.currentIndex() in (1, 2):
            (self.columns if self.tabs.currentIndex() == 1 else self.subcolumns).setFocus()
        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        layout.addWidget(self.problem)
        if self.replicate_count is not None:
            self.replicate_count.valueChanged.connect(self.problem.hide)
            self.replicate_count.valueChanged.connect(lambda: self.refresh_preview(0))
        if self.x_error is not None:
            self.x_error.toggled.connect(self.problem.hide)
            self.x_error.toggled.connect(lambda: self.refresh_preview(0))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        count = self.replicate_count.value() if self.replicate_count is not None else None
        changed_count = count if count != self.initial_count else None
        checked = self.x_error.isChecked() if self.x_error is not None else None
        changed_error = checked if self.x_block and checked != bool(self.x_block[1]) else None
        if changed_count is not None or changed_error is not None:
            try:
                self.affected_runs = self.update_structure(changed_count, changed_error, self.settings())
            except ValueError as error:
                self.problem.setText(ui(str(error)))
                self.problem.show()
                self.tabs.setCurrentIndex(0)
                control = self.x_error if changed_error is not None else self.replicate_count
                control.setFocus()
                return
        super().accept()

    @staticmethod
    def check(key, value):
        box = QCheckBox(qt(key))
        box.setChecked(value)
        return box

    @staticmethod
    def grid(parent):
        view = QTableView(parent)
        view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        view.setAlternatingRowColors(True)
        view.setAccessibleName(qt("qt.heading_title"))
        return view

    def rep_key(self, column, shared):
        if shared:
            return str(column - self.source.bands[column][0] + 1)
        return self.source.column_tokens[column]

    def populate_subcolumns(self):
        rows = []
        seen = set()
        self.subrows = []
        values = self.common if self.shared_mode else self.individual
        for column in self.replicates:
            key = self.rep_key(column, self.shared_mode)
            if key in seen:
                continue
            seen.add(key)
            rows.append([self.source.subcolumn_key(column), values.get(key, "")])
            self.subrows.append(key)
        previous = self.subcolumns.model()
        self.subcolumns.setModel(TitleList(rows, self.subcolumns))
        if previous is not None:
            previous.deleteLater()

    def store_subcolumns(self):
        values = self.common if self.shared_mode else self.individual
        for key, (_, value) in zip(self.subrows, self.subcolumns.model().rows, strict=True):
            if value:
                values[key] = value
            else:
                values.pop(key, None)

    def switch_mode(self, shared):
        self.store_subcolumns()
        if not shared and not self.individual:
            seen = set()
            for c in self.replicates:
                key = self.rep_key(c, True)
                if key not in seen and key in self.common:
                    self.individual[self.rep_key(c, False)] = self.common[key]
                seen.add(key)
        self.shared_mode = shared
        self.populate_subcolumns()

    def refresh_preview(self, tab):
        if tab != 0:
            return
        draft = self.settings()
        model = self.source
        columns = []
        x, error = self.x_block or (None, None)
        with_error = self.x_error is not None and self.x_error.isChecked()
        for column, (first, stop, band, _) in enumerate(model.bands):
            name = model.frame.columns[column]
            if (band == "Row titles" and not draft.show_rows) or name == error and not with_error:
                continue
            if self.replicate_count is None or not model.is_replicate(column):
                columns.append((column, column, None))
            elif column == first:
                for index in range(self.replicate_count.value()):
                    source = first + index if first + index < stop else None
                    columns.append((first, source, index + 1))
            if name == x and with_error and error is None:
                columns.append((column, None, None))
            if len(columns) >= 12:
                break
        columns = columns[:12]
        rows = min(4, len(model.frame))
        self.preview.clearContents()
        self.preview.setColumnCount(len(columns))
        self.preview.setRowCount(rows)
        headings = []
        for i, (column, source, replica) in enumerate(columns):
            first, _, band, default = model.bands[column]
            title = (tr("setup.row_titles") if band == "Row titles" else
                     draft.columns.get(model.column_tokens[column], default))
            if model.is_replicate(column):
                replica = replica or column - first + 1
                if draft.shared:
                    subtitle = draft.common.get(str(replica), "")
                else:
                    subtitle = draft.individual.get(model.column_tokens[source], "") if source is not None else ""
                key = (model.default_subcolumn_label(source) if source is not None
                       else f"{band.removeprefix('Group ')}:Y{replica}")
                title = f"{title}\n{subtitle if draft.show_subtitles and subtitle else key}"
            if band == "X" and (source is None or model.roles[column] == "Error"):
                title = f"{title}\n{qt('qt.x_error_heading')}"
            headings.append(title)
            if source is not None:
                for row in range(rows):
                    value = model.data(model.index(row, source), Qt.ItemDataRole.DisplayRole)
                    self.preview.setItem(row, i, QTableWidgetItem(str(value or "")))
        self.preview.setHorizontalHeaderLabels(headings)
        self.preview.resizeColumnsToContents()

    def settings(self):
        self.store_subcolumns()
        columns = dict(self.original.columns)
        for column, (_, value) in zip(self.title_groups, self.columns.model().rows, strict=True):
            first, stop, _, default = self.source.bands[column]
            if value == self.source.group_title(column):
                continue
            for token in self.source.column_tokens[first:stop]:
                if value == default:
                    columns.pop(token, None)
                else:
                    columns[token] = value
        return replace(self.original, columns=columns, common=self.common.copy(), individual=self.individual.copy(),
                       show_rows=self.show_rows.isChecked() if self.show_rows.isEnabled() else self.original.show_rows,
                       automatic_widths=self.widths.isChecked(), show_subtitles=self.show_subtitles.isChecked(),
                       shared=self.shared_mode)
