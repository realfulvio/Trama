"""Worksheet navigation within data sets, including keys pressed in the cell editor."""
import unittest

import pandas as pd
try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 unavailable")
class WorksheetKeyboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["worksheet-input", "-platform", "offscreen"])

    def setUp(self):
        from analisi.i18n import active_language, set_language
        from trama_qt.window import MainWindow
        self.addCleanup(set_language, active_language())
        set_language("en")
        self.window = MainWindow()
        table = pd.DataFrame([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]],
                             columns=["X", "A [1]", "A [2]", "B [1]", "B [2]"])
        title, = self.window.project.add_tables({"Measurements": table})
        self.data = self.window.project.tables[title]
        self.data.table_format = "XY"
        self.window.show_sheet("data", title)
        self.window.show()
        self.view = self.window.sheet
        self.app.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def click_key(self, key, modifiers=None, target=None):
        QTest.keyClick(target or self.view, key, modifiers or Qt.KeyboardModifier.NoModifier)
        for _ in range(3):
            self.app.processEvents()

    def locate(self, row, column):
        self.view.setCurrentIndex(self.view.model().index(row, column))
        self.view.setFocus()

    def position(self):
        current = self.view.currentIndex()
        return current.row(), current.column()

    def test_forward_and_reverse_wrap_within_selected_series(self):
        self.locate(0, 3)
        for expected in [(0, 4), (1, 3), (1, 4)]:
            self.click_key(Qt.Key.Key_Return)
            self.assertEqual(self.position(), expected)
        for expected in [(1, 3), (0, 4), (0, 3), (0, 3)]:
            self.click_key(Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
            self.assertEqual(self.position(), expected)

    def test_ctrl_enter_and_single_x_move_vertically_tab_moves_across_series(self):
        self.locate(0, 1)
        self.click_key(Qt.Key.Key_Enter, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.position(), (1, 1))
        self.locate(0, 0)
        self.click_key(Qt.Key.Key_Return)
        self.assertEqual(self.position(), (1, 0))
        self.locate(0, 2)
        self.click_key(Qt.Key.Key_Tab)
        self.assertEqual(self.position(), (0, 3))
        self.click_key(Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.position(), (0, 2))

    def test_editor_commits_to_original_cell_then_moves(self):
        for column, modifier, destination, value in [
            (1, Qt.KeyboardModifier.NoModifier, (1, 2), "71"),
            (3, Qt.KeyboardModifier.ShiftModifier, (0, 4), "72"),
            (4, Qt.KeyboardModifier.ControlModifier, (2, 4), "73"),
        ]:
            with self.subTest(column=column):
                self.locate(1, column)
                self.click_key(Qt.Key.Key_F2)
                editor = self.view.findChild(QLineEdit, "worksheetEditor")
                self.assertIsNotNone(editor)
                editor.selectAll()
                QTest.keyClicks(editor, value)
                self.click_key(Qt.Key.Key_Return, modifier, editor)
                self.assertEqual(float(self.data.raw.iat[1, column]), float(value))
                self.assertEqual(self.position(), destination)

    def test_select_menu_order_and_full_series_by_keyboard(self):
        from trama_qt.strings import qt
        edit = self.window.command_menus["Edit"]
        menu, = [action.menu() for action in edit.actions() if action.text() == qt("qt.select_cells")]
        self.assertEqual(menu.actions(), [self.window.actions[key] for key in
                                         ("select_sheet_cells", "select_data_column", "select_data_row")])
        self.locate(1, 2)
        last_row, last_col = self.view.model().rowCount() - 1, self.view.model().columnCount() - 1
        self.click_key(Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.view.box(), (0, 1, last_row, 2))
        self.click_key(Qt.Key.Key_Space, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.view.box(), (1, 0, 1, last_col))
        self.window.actions["select_sheet_cells"].trigger()
        self.assertEqual(self.view.box(), (0, 0, last_row, last_col))
        self.locate(0, 0)
        self.window.actions["select_data_column"].trigger()
        self.assertEqual(self.view.box(), (0, 0, last_row, 0))

    def test_group_heading_selects_series_and_lower_heading_one_replicate(self):
        from PySide6.QtCore import QPoint
        header = self.view.horizontalHeader()
        col = 2
        x = header.sectionViewportPosition(col) + header.sectionSize(col) // 2
        for y, first in ((header.height() // 6, 1), (header.height() * 5 // 6, 2)):
            QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, QPoint(x, y))
            self.assertEqual(self.view.box(), (0, first, self.view.model().rowCount() - 1, 2))
        model = self.view.model()
        self.assertEqual(model.headerData(2, Qt.Orientation.Horizontal), "Group A\nA\nA:Y2")
        self.assertEqual(model.subcolumn_label(3), "B:Y1")

    def test_ctrl_a_in_editor_selects_text_without_selecting_sheet(self):
        self.locate(1, 1)
        self.click_key(Qt.Key.Key_F2)
        editor = self.view.findChild(QLineEdit, "worksheetEditor")
        editor.deselect()
        self.click_key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, editor)
        self.assertEqual(editor.selectedText(), editor.text())
        self.assertEqual(self.view.box(), (1, 1, 1, 1))
        self.click_key(Qt.Key.Key_Escape, target=editor)

    def test_italian_heading_and_tooltip_identify_the_same_replicate(self):
        from analisi.i18n import set_language
        set_language("it")
        model = self.view.model()
        for role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            self.assertEqual(model.headerData(2, Qt.Orientation.Horizontal, role), "Gruppo A\nA\nA:Y2")
