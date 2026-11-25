"""Keyboard shortcuts of the window, listed from the real actions (F1)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from analisi.i18n import tr, ui

from .classic_bar import MENUS
from .strings import qt

# Cut, Copy and Paste are handled by the table itself, so their actions carry no shortcut of their own.
STANDARD = {"cut": QKeySequence.StandardKey.Cut, "copy": QKeySequence.StandardKey.Copy,
            "paste": QKeySequence.StandardKey.Paste}


def _shortcut(key, action):
    sequence = action.shortcut()
    if sequence.isEmpty() and key in STANDARD:
        sequence = QKeySequence(STANDARD[key])
    return sequence.toString(QKeySequence.SequenceFormat.NativeText)


class ShortcutsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle(qt("qt.shortcuts"))
        layout = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(qt("qt.shortcuts_filter"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([qt("qt.command"), qt("qt.shortcut")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setAlternatingRowColors(False)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)
        hint = QLabel(qt("qt.shortcuts_hint"))
        hint.setObjectName("muted")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        seen = set()
        for name, keys in MENUS:
            rows = []
            for key in keys:
                action = window.actions.get(key) if key != "|" else None
                shortcut = _shortcut(key, action) if action is not None else ""
                if not shortcut or key in seen:
                    continue
                seen.add(key)
                rows.append((action.text().replace("&&", "\0").replace("&", "").replace("\0", "&"), shortcut))
            if not rows:
                continue
            title = tr("theme.settings") if name == "Settings" else qt("qt.toolbar_help") if name == "Help" else ui(name)
            head = QTreeWidgetItem([title])
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = QFont(head.font(0))
            font.setBold(True)
            head.setFont(0, font)
            for column in (0, 1):
                head.setBackground(column, self.palette().alternateBase())
            self.tree.addTopLevelItem(head)
            for text, shortcut in rows:
                row = QTreeWidgetItem(head, [text, shortcut])
                row.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            head.setExpanded(True)
        self.resize(480, 560)

    def _apply_filter(self, text):
        text = text.strip().casefold()
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            shown = 0
            for j in range(head.childCount()):
                row = head.child(j)
                visible = not text or text in row.text(0).casefold() or text in row.text(1).casefold()
                row.setHidden(not visible)
                shown += visible
            head.setHidden(not shown)
