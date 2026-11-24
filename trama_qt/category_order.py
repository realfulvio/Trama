"""Reorder, rename, and merge the selected worksheet's category levels in the Qt interface."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from analisi.category_levels import LevelEditError, format_recipe_blockers
from analisi.i18n import tr
from .theme import fit_dialog, table_font


class _LevelsTableProxy:
    """Read-only adapter exposing ``item(row)``/``count()`` on column 0 for existing callers."""

    def __init__(self, table):
        self._table = table

    def count(self):
        return self._table.rowCount()

    def currentRow(self):
        return self._table.currentRow()

    def setCurrentRow(self, row):
        if 0 <= row < self._table.rowCount():
            self._table.setCurrentCell(row, 0)

    def item(self, row):
        return self._table.item(row, 0)


class CategoryOrderDialog(QDialog):
    def __init__(self, parent, column, draft, *, check_recipes=None, confirm_merge=None):
        super().__init__(parent)
        self.draft = draft
        self.check_recipes = check_recipes
        self.confirm_merge = confirm_merge
        self.plan = None
        self._rendering = False
        self._visible_tokens = []

        self.setWindowTitle(tr("command.category_order").removesuffix("…"))
        layout = QVBoxLayout(self)

        heading = QLabel(column)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        can_rename = getattr(draft, "can_rename", False)
        note_key = "category_levels.note" if can_rename else "category_levels.note_order_only"
        note = QLabel(tr(note_key) if hasattr(draft, "target_text") else tr("worksheet_order.note"))
        note.setWordWrap(True)
        layout.addWidget(note)

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("category_levels.search_placeholder"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(tr("category_levels.search_placeholder"))
        layout.addWidget(self.search)

        entries = QHBoxLayout()
        self.table = QTableWidget(0, 3)
        self.table.setFont(table_font())
        self.table.setHorizontalHeaderLabels([
            tr("category_levels.col.level"),
            tr("category_levels.col.count"),
            tr("category_levels.col.new_name"),
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.setMinimumHeight(8 * self.table.fontMetrics().lineSpacing())
        self.table.setAccessibleName(tr("command.category_order").removesuffix("…"))
        self.levels = _LevelsTableProxy(self.table)
        entries.addWidget(self.table, 1)

        controls = QVBoxLayout()
        self.up = QPushButton(tr("pdf.up"))
        self.down = QPushButton(tr("pdf.down"))
        self.reset = QPushButton(tr("worksheet_order.reset"))
        self.up.clicked.connect(lambda: self.move(-1))
        self.down.clicked.connect(lambda: self.move(1))
        self.reset.clicked.connect(self.restore)
        for button in (self.up, self.down, self.reset):
            controls.addWidget(button)
        controls.addStretch()
        entries.addLayout(controls)
        layout.addLayout(entries, 1)

        self.filter_hint = QLabel(tr("category_levels.filter_active_hint"))
        self.filter_hint.setObjectName("muted")
        self.filter_hint.setWordWrap(True)
        self.filter_hint.hide()
        layout.addWidget(self.filter_hint)

        self.problem = QLabel()
        self.problem.setObjectName("errorBanner")
        self.problem.setWordWrap(True)
        self.problem.hide()
        layout.addWidget(self.problem)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("graph.inspector.apply"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("setup.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.table.currentCellChanged.connect(lambda *_args: self.sync_buttons())
        self.table.itemChanged.connect(self._on_item_changed)
        self.search.textChanged.connect(self._on_filter_changed)

        for direction, step in (("Up", -1), ("Down", 1)):
            shortcut = QShortcut(QKeySequence(f"Alt+{direction}"), self.table)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda step=step: self.move(step))

        fit_dialog(self, 620, 420)
        self.render()
        self.table.setFocus()

    def _filter_query(self):
        return self.search.text().casefold()

    def _matches_filter(self, entry, query):
        if not query:
            return True
        if query in entry.display_label.casefold() or query in entry.raw_label.casefold():
            return True
        if hasattr(self.draft, "target_text"):
            return query in self.draft.target_text(entry.token).casefold()
        return False

    def _clear_problem(self):
        if self.problem.isVisible():
            self.problem.clear()
            self.problem.hide()

    def _show_problem(self, message):
        self.problem.setText(str(message))
        self.problem.show()

    def _commit_active_editor(self):
        editor = self.table.focusWidget()
        if editor is not None and self.table.viewport().isAncestorOf(editor):
            self.table.commitData(editor)
            self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def render(self, row=0, column=0):
        self._rendering = True
        try:
            query = self._filter_query()
            self.filter_hint.setVisible(bool(query))
            visible = []
            for entry in self.draft.levels:
                if hasattr(entry, "token"):
                    if self._matches_filter(entry, query):
                        visible.append(entry)
                else:
                    token, label = entry
                    if not query or query in str(label).casefold():
                        visible.append((token, label))

            self._visible_tokens = [item.token if hasattr(item, "token") else item[0] for item in visible]
            self.table.setRowCount(len(visible))
            can_rename = getattr(self.draft, "can_rename", False) and hasattr(self.draft, "target_text")

            for idx, item in enumerate(visible):
                if hasattr(item, "token"):
                    token = item.token
                    display_label = item.display_label
                    raw_label = item.raw_label
                    count_text = str(item.count)
                    target_text = self.draft.target_text(token)
                    ambiguous = item.ambiguous
                else:
                    token, display_label = item
                    raw_label = str(display_label)
                    count_text = "—"
                    target_text = raw_label
                    ambiguous = False

                level_item = QTableWidgetItem(display_label)
                level_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                level_item.setData(Qt.ItemDataRole.UserRole, token)
                if ambiguous:
                    level_item.setToolTip(f"{display_label} [{token}]")
                self.table.setItem(idx, 0, level_item)

                count_item = QTableWidgetItem(count_text)
                count_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                count_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(idx, 1, count_item)

                target_item = QTableWidgetItem(target_text)
                if can_rename:
                    target_item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
                    )
                else:
                    target_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                target_item.setData(Qt.ItemDataRole.UserRole, token)
                self.table.setItem(idx, 2, target_item)

            if self.table.rowCount() > 0:
                target_row = max(0, min(row, self.table.rowCount() - 1))
                target_col = max(0, min(column, 2))
                self.table.setCurrentCell(target_row, target_col)
        finally:
            self._rendering = False
        self.sync_buttons()

    def _on_filter_changed(self, _text):
        self._commit_active_editor()
        current_token = self._current_token()
        self.render()
        if current_token and current_token in self._visible_tokens:
            self.table.setCurrentCell(self._visible_tokens.index(current_token), max(0, self.table.currentColumn()))

    def _on_item_changed(self, item):
        if self._rendering or item.column() != 2 or not hasattr(self.draft, "set_target"):
            return
        token = item.data(Qt.ItemDataRole.UserRole)
        if token is None:
            return
        self._clear_problem()
        try:
            self.draft.set_target(token, item.text())
        except LevelEditError as error:
            self._show_problem(error)

    def _current_token(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._visible_tokens):
            return self._visible_tokens[row]
        return None

    def sync_buttons(self):
        filtered = bool(self._filter_query())
        row = self.table.currentRow()
        count = self.table.rowCount()
        self.up.setEnabled(not filtered and row > 0)
        self.down.setEnabled(not filtered and 0 <= row < count - 1)

    def move(self, step):
        if self._filter_query():
            return
        self._commit_active_editor()
        col = max(0, self.table.currentColumn())
        new_row = self.draft.move(self.table.currentRow(), step)
        self.render(new_row, col)

    def restore(self):
        self._commit_active_editor()
        current_token = self._current_token()
        self.draft.restore_automatic()
        row = 0
        if current_token:
            for idx, entry in enumerate(self.draft.levels):
                token = entry.token if hasattr(entry, "token") else entry[0]
                if token == current_token:
                    row = idx
                    break
        self.render(row, max(0, self.table.currentColumn()))

    def _focus_token(self, token, *, column=2):
        if token is None:
            return
        if token not in self._visible_tokens and self.search.text():
            self.search.clear()
        if token not in self._visible_tokens:
            return
        row = self._visible_tokens.index(token)
        target_col = column if getattr(self.draft, "can_rename", False) else 0
        item = self.table.item(row, target_col)
        if item is not None:
            self.table.setCurrentCell(row, target_col)
            self.table.scrollToItem(item)
            self.table.setFocus()
            if target_col == 2 and self.isVisible():
                self.table.editItem(item)

    def _default_confirm_merge(self, merges):
        lines = [tr("category_levels.merge.intro"), ""]
        for merge in merges:
            sources_text = ", ".join(
                f"«{entry.display_label}» ({entry.count})" for entry in merge.sources
            )
            lines.append(tr(
                "category_levels.merge.item",
                sources=sources_text,
                target=merge.target_label,
                total=merge.total_count,
            ))
        lines.extend(["", tr("category_levels.merge.question")])
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("category_levels.merge.title"))
        box.setText("\n".join(lines))
        confirm_button = box.addButton(tr("category_levels.merge.confirm"), QMessageBox.ButtonRole.AcceptRole)
        cancel_button = box.addButton(tr("setup.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec()
        return box.clickedButton() is confirm_button

    def accept(self):
        self._commit_active_editor()
        self._clear_problem()
        if not hasattr(self.draft, "validate"):
            super().accept()
            return
        try:
            plan = self.draft.validate()
        except LevelEditError as error:
            self._show_problem(error)
            self._focus_token(error.token, column=2)
            return

        if not plan.has_changes:
            self.plan = None
            super().accept()
            return

        if self.check_recipes is not None:
            blockers = self.check_recipes(plan)
            if blockers:
                self._show_problem(format_recipe_blockers(blockers))
                token = blockers[0].source_tokens[0] if blockers[0].source_tokens else None
                self._focus_token(token, column=2)
                return

        if plan.merges:
            confirmed = (
                self.confirm_merge(plan.merges)
                if self.confirm_merge is not None
                else self._default_confirm_merge(plan.merges)
            )
            if not confirmed:
                return

        self.plan = plan
        super().accept()
