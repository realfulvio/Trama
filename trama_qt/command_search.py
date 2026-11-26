"""Find and run the actual actions in the Classica Qt window."""

import unicodedata

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .shortcuts_dialog import shortcut_text
from .strings import qt
from .theme import fit_dialog


def _search_text(text):
    return "".join(char for char in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(char))


def action_caption(text):
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


class CommandSearchDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle(qt("qt.search"))
        self.actions = window.actions
        self.locations = {}
        for menu in window.command_menus.values():
            for action in menu.actions():
                if action.isSeparator():
                    continue
                parent = action_caption(menu.title())
                if action.menu() is None:
                    self.locations.setdefault(action, []).append(parent)
                else:
                    location = parent + " → " + action_caption(action.text())
                    for child in action.menu().actions():
                        if not child.isSeparator():
                            self.locations.setdefault(child, []).append(location)

        layout = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setAccessibleName(qt("qt.search_command"))
        self.query.setPlaceholderText(qt("qt.search_placeholder"))
        self.query.setClearButtonEnabled(True)
        self.query.installEventFilter(self)
        self.query.textChanged.connect(lambda _: self.refresh(keep_selection=False))
        layout.addWidget(self.query)

        self.results = QTreeWidget()
        self.results.setAccessibleName(qt("qt.search_results"))
        self.results.setHeaderLabels([qt("qt.command"), qt("qt.search_menu"),
                                      qt("qt.shortcut"), qt("qt.search_status")])
        self.results.setRootIsDecorated(False)
        self.results.setIndentation(0)
        self.results.installEventFilter(self)
        header = self.results.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.results.itemActivated.connect(lambda *_: self.run_current())
        self.results.currentItemChanged.connect(self._selection_changed)
        layout.addWidget(self.results, 1)

        self.notice = QLabel()
        self.notice.setObjectName("muted")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setAutoDefault(False)
        self.run_button = buttons.addButton(qt("qt.search_run"), QDialogButtonBox.ButtonRole.ActionRole)
        self.run_button.clicked.connect(self.run_current)
        self.run_button.setDefault(True)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        fit_dialog(self, 700, 450)

        self._refresh_timer = QTimer(self, singleShot=True)
        self._refresh_timer.timeout.connect(self.refresh)
        for action in self.actions.values():
            action.changed.connect(self._refresh_if_visible)

    def open_search(self):
        fit_dialog(self, 700, 450)
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.query.setFocus()
        self.query.selectAll()

    def _refresh_if_visible(self):
        if self.isVisible():
            self._refresh_timer.start(0)

    def _current_key(self):
        selected = self.results.currentItem()
        return selected.data(0, Qt.ItemDataRole.UserRole) if selected is not None else None

    def refresh(self, *, keep_selection=True):
        query = _search_text(self.query.text()).split()
        previous = self._current_key() if keep_selection else None
        rows = []
        for key, action in self.actions.items():
            name = action_caption(action.text())
            if not name or not action.isVisible():
                continue
            menus = " · ".join(self.locations.get(action, ()))
            shortcut = shortcut_text(key, action)
            normalized = _search_text(name)
            searchable = _search_text(f"{name} {menus} {shortcut}")
            if not all(term in searchable for term in query):
                continue
            rank = (normalized != " ".join(query), not action.isEnabled(), normalized, menus)
            rows.append((rank, key, name, menus, shortcut))

        self.results.clear()
        selection = None
        for _rank, key, name, menus, shortcut in sorted(rows):
            state = "" if self.actions[key].isEnabled() else qt("qt.search_unavailable")
            item = QTreeWidgetItem([name, menus, shortcut, state])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.results.addTopLevelItem(item)
            if key == previous:
                selection = item
        self.results.setCurrentItem(selection or self.results.topLevelItem(0))
        self._selection_changed()

    def _selection_changed(self, *_):
        action = self.actions.get(self._current_key())
        enabled = action is not None and action.isEnabled() and action.isVisible()
        self.run_button.setEnabled(enabled)
        if action is None:
            message = qt("qt.search_no_match")
        elif not enabled:
            message = qt("qt.search_not_here")
        else:
            message = ""
        self.notice.setText(message)
        self.notice.setVisible(bool(message))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if watched in (self.query, self.results) and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.run_current()
                return True
            if (watched is self.query and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up)
                    and self.results.currentItem() is not None):
                self.results.setFocus(Qt.FocusReason.TabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def run_current(self):
        action = self.actions.get(self._current_key())
        if not self.isVisible() or action is None or not action.isEnabled() or not action.isVisible():
            return
        self.accept()
        self.query.clear()
        action.trigger()
