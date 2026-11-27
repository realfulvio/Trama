import os
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from trama_qt.family import FamilySheetsDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class LinkedSheetsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.references = [("data", "Visits"), ("result", 0), ("result", 1), ("graph", 1)]
        captions = ["Data tables · Visits", "Results · First analysis", "Results · Second analysis",
                    "Graphs · Second analysis"]
        self.dialog = FamilySheetsDialog(None, captions, self.references, current=self.references[0])
        self.addCleanup(self.dialog.deleteLater)
        self.addCleanup(self.dialog.close)
        self.dialog.show()
        self.dialog.activateWindow()
        self.app.processEvents()

    def test_filter_and_keyboard_open_the_matching_sheet(self):
        dialog = self.dialog
        self.assertIs(dialog.focusWidget(), dialog.search)
        dialog.search.setText("  RESULTS  ")
        self.assertEqual(len(dialog._shown()), 2)
        self.assertEqual(dialog.entries.currentItem().data(Qt.ItemDataRole.UserRole), self.references[1])
        QTest.keyClick(dialog.search, Qt.Key.Key_Down)
        QTest.keyClick(dialog.search, Qt.Key.Key_Return)
        self.assertEqual(dialog.selected, self.references[2])

    def test_no_match_cannot_open_an_old_selection(self):
        dialog = self.dialog
        dialog.search.setText("Unrelated")
        self.assertFalse(dialog.open_button.isEnabled())
        self.assertFalse(dialog.empty.isHidden())
        dialog.accept()
        self.assertIsNone(dialog.selected)
        dialog.search.clear()
        self.assertEqual(len(dialog._shown()), len(self.references))
        self.assertTrue(dialog.open_button.isEnabled())
