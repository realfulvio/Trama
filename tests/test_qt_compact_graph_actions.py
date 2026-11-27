"""Small graph windows keep each page command and the Inspector accessible."""
import os
import unittest

from PySide6.QtWidgets import QApplication, QToolButton
from PySide6.QtGui import QAction

from trama_qt.window import Page

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class CompactGraphActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_graph_tools_menu_keeps_actions_and_returns_focus_on_resize(self):
        page = Page("Response chart", "Graph")
        self.addCleanup(page.close)
        commands = [QAction(label, page) for label in (
            "Long annotation label", "Draw or arrange shapes", "Insert linked table", "Inspector",
        )]
        buttons = [page.command(action) for action in commands]
        page.finish_actions(graph_inspector=commands[-1])
        page.resize(850, 500)
        page.show()
        page.activateWindow()
        self.app.processEvents()
        buttons[0].setFocus()
        self.assertTrue(buttons[0].isVisible())
        self.assertFalse(page.compact_actions.isVisible())

        page.resize(325, 280)
        self.app.processEvents()
        self.assertFalse(buttons[0].isVisible())
        self.assertTrue(page.compact_actions.isVisible())
        self.assertEqual(page.graph_tools.menu().actions(), commands[:-1])
        self.assertIs(page.focusWidget(), page.graph_tools)
        tools = page.compact_actions.findChildren(QToolButton)
        self.assertTrue(any(tool.defaultAction() is commands[-1] for tool in tools))

        triggered = []
        commands[1].triggered.connect(lambda: triggered.append(True))
        page.graph_tools.menu().actions()[1].trigger()
        self.assertEqual(triggered, [True])
        page.resize(850, 500)
        self.app.processEvents()
        self.assertFalse(page.compact_actions.isVisible())
        self.assertIs(page.focusWidget(), buttons[0])
