import os
import unittest
from unittest.mock import patch

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analisi.reporting import Result
from trama_qt.classic_bar import RESULT_TABLE_COMMANDS, SECTION_COMMANDS
from trama_qt.project import Run
from trama_qt.window import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ResultTableShortcutsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        frame = pd.DataFrame({"n": [2, 4]})
        self.title, = self.window.project.add_tables({"Observations": frame})
        tables = {f"Output {index}": frame.assign(result=index) for index in range(1, 12)}
        self.window.project.runs.append(Run("Descriptive statistics", self.title, {}, Result(tables)))
        self.window.show_sheet("result", 0)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_select_through_menu_or_shortcut_keeps_every_selector_current(self):
        window = self.window
        tabs = window.result_tabs
        actions = [window.actions[key] for key in RESULT_TABLE_COMMANDS]
        self.assertEqual(len(actions), 9)
        self.assertTrue(actions[0].isChecked())
        self.assertEqual(window.result_table_menu.actions(), actions)
        tabs.currentWidget().setFocus()
        QTest.keyClick(tabs.currentWidget(), Qt.Key.Key_9, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual((tabs.currentIndex(), window.status_results.currentIndex()), (8, 8))
        self.assertTrue(actions[8].isChecked())
        self.assertIs(self.app.focusWidget(), tabs.currentWidget())
        actions[1].trigger()
        self.assertEqual((tabs.currentIndex(), window.status_results.currentIndex()), (1, 1))
        self.assertTrue(actions[1].isChecked())
        self.assertFalse(actions[8].isChecked())
        window._pick_result_table(10)
        self.assertEqual(tabs.currentIndex(), 10)
        self.assertFalse(any(action.isChecked() for action in actions))

    def test_no_result_table_shortcuts_on_the_source_sheet(self):
        window = self.window
        window.show_sheet("data", self.title)
        self.app.processEvents()
        self.assertTrue(all(not window.actions[key].isEnabled() for key in RESULT_TABLE_COMMANDS))
        self.assertFalse(window.result_table_menu.menuAction().isEnabled())

    def test_section_navigation_uses_the_same_action_as_the_status_bar(self):
        window = self.window
        self.assertTrue(window.section_buttons["result"].isChecked())
        window.section_buttons["result"].click()
        self.assertTrue(window.section_buttons["result"].isChecked())
        for index, kind in enumerate(SECTION_COMMANDS, 1):
            button = window.section_buttons[kind]
            action = window.actions[f"section_{kind}"]
            self.assertIs(button.defaultAction(), action)
            self.assertIn(f"Alt+{index}", button.toolTip())
        self.assertFalse(window.section_buttons["layout"].isEnabled())
        table = window.result_tabs.currentWidget()
        table.setFocus()
        QTest.keyClick(table, Qt.Key.Key_1, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(window.selected, ("data", self.title))
        self.assertTrue(window.section_buttons["data"].isChecked())
        self.assertFalse(window.section_buttons["result"].isChecked())

    def test_section_highlight_survives_cancelled_navigation(self):
        window = self.window
        with patch.object(window, "settle_graph_draft", return_value=False):
            window.section_buttons["data"].click()
        self.assertEqual(window.selected, ("result", 0))
        self.assertTrue(window.section_buttons["result"].isChecked())
        self.assertFalse(window.section_buttons["data"].isChecked())
