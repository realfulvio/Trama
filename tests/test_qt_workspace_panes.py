import os
import unittest

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analisi.workbench import analyse
from analisi.xy_series import XY_METHOD
from trama_qt.window import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class WorkspacePaneFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        frame = pd.DataFrame({"X": [1., 2.], "Y": [2., 4.]})
        self.title, = self.window.project.add_tables({"Visits": frame})
        self.window.show_sheet("data", self.title)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.close_worksheet_notes()
        self.window.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def press(self, from_widget, step=1):
        modifier = Qt.KeyboardModifier.NoModifier if step > 0 else Qt.KeyboardModifier.ShiftModifier
        QTest.keyClick(from_widget, Qt.Key.Key_F6, modifier)
        self.app.processEvents()

    def test_pane_shortcuts_follow_sheet_notes_and_skip_a_hidden_navigator(self):
        window = self.window
        window.navigator.setFocus()
        self.press(window.navigator)
        self.assertIs(self.app.focusWidget(), window.sheet)
        self.press(window.sheet, -1)
        self.assertIs(self.app.focusWidget(), window.navigator)
        window.open_worksheet_notes()
        self.app.processEvents()
        notes = window.worksheet_notes
        notes.add_note()
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), notes.editor.notes)
        self.press(notes.editor.notes)
        self.assertIs(self.app.focusWidget(), window.navigator)
        self.press(window.navigator, -1)
        self.assertIs(self.app.focusWidget(), notes.editor.notes)
        window.nav_card.hide()
        self.press(notes.editor.notes)
        self.assertIs(self.app.focusWidget(), window.sheet)
        self.assertEqual(window.selected, ("data", self.title))

    def test_graph_canvas_and_inspector_are_distinct_panes(self):
        window = self.window
        options = {"X": "X", "Y columns": ["Y"], "Series style": {"Y": "Line and points"}}
        project = window.project
        run = project.candidate(self.title, XY_METHOD, options)
        project.add_result(run, analyse(XY_METHOD, project.tables[self.title].frame(), options))
        window.show_sheet("graph", 0)
        if window.inspector is None:
            window.actions["inspector"].trigger()
        self.app.processEvents()
        canvas = window.plot_tools.canvas
        window.navigator.setFocus()
        self.press(window.navigator)
        self.assertIs(self.app.focusWidget(), canvas)
        self.press(canvas)
        self.assertIs(self.app.focusWidget(), window.inspector.selector)
        self.press(window.inspector.selector, -1)
        self.assertIs(self.app.focusWidget(), canvas)
        self.assertEqual(window.selected, ("graph", 0))
