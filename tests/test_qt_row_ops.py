"""Qt UI tests for vertical header row dragging, resizing, context menu, keyboard shortcuts and zoom."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from analisi.i18n import set_language
from analisi.worksheet_appearance import MIN_ROW_HEIGHT
from trama_qt.sheet import WorksheetRowHeader
from trama_qt.window import MainWindow


class QtRowOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-row-ops"])

    def setUp(self):
        set_language("en")
        self.window = MainWindow()
        self.addCleanup(self._cleanup)
        self.window.error = lambda err: self.fail(str(err))
        self.window.resize(960, 640)
        self.window.show()
        self.window.project.add_tables({
            "XY": pd.DataFrame({
                "Row title": ["A", "B1", "B2", "C", "D"],
                "X": [1.0, 2.0, 2.0, 4.0, 8.0],
                "Y": [3.0, 6.0, 6.0, 12.0, 24.0],
            })
        })
        self.window.show_sheet("data", "XY")
        self.app.processEvents()

    def _cleanup(self):
        set_language("en")
        self.window.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_click_selects_row_and_drag_block_moves_with_selection_following(self):
        view = self.window.sheet
        header = view.verticalHeader()
        self.assertIsInstance(header, WorksheetRowHeader)
        self.assertEqual(header.sectionResizeMode(0), header.ResizeMode.Fixed)

        # Click row 2 (index 1) center -> selects row 2
        y_row1 = header.sectionViewportPosition(1) + header.sectionSize(1) // 2
        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_row1))
        self.app.processEvents()
        self.assertEqual(view.box()[:3:2], (1, 1))

        # Select block rows 2-3 (indices 1..2), then drag from row 2 center past row 5 bottom
        view.select_block(1, 0, 2, view.model().columnCount() - 1, current_row=1, current_col=0)
        self.app.processEvents()
        y_start = header.sectionViewportPosition(1) + header.sectionSize(1) // 2
        y_end = header.sectionViewportPosition(4) + header.sectionSize(4) - 2
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_start))
        QTest.mouseMove(header.viewport(), QPoint(12, y_end))
        self.assertEqual(header._mode, "move")
        self.assertEqual(header._drop_row, 5)
        QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_end))
        self.app.processEvents()

        self.assertEqual(self.window.project.tables["XY"].raw["Row title"].tolist(), ["A", "C", "D", "B1", "B2"])
        # Selection followed the moved block (rows 4-5, indices 3..4)
        self.assertEqual(view.box()[0], 3)
        self.assertEqual(view.box()[2], 4)

    def test_boundary_drag_resizes_row_respects_zoom_and_resets(self):
        view = self.window.sheet
        header = view.verticalHeader()
        y_border = header.sectionViewportPosition(2) + header.sectionSize(2)
        start_h = header.sectionSize(2)

        # Boundary drag +24px -> zero recalcs, height stored at 100%
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_border))
        self.assertEqual(header._mode, "resize")
        QTest.mouseMove(header.viewport(), QPoint(12, y_border + 24))
        QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_border + 24))
        self.app.processEvents()

        expected_base = max(MIN_ROW_HEIGHT, start_h + 24)
        self.assertEqual(self.window.project.tables["XY"].row_heights, {2: expected_base})
        self.assertEqual(header.sectionSize(2), expected_base)

        # Zoom to 150% -> height scales proportionally
        self.window.zoom_table(1)  # 110
        self.window.zoom_table(1)  # 125
        self.window.zoom_table(1)  # 150
        self.assertEqual(self.window.table_zoom, 150)
        self.assertEqual(header.sectionSize(2), round(expected_base * 1.5))

        # Reset height via action -> restores automatic height
        view.selectRow(2)
        self.app.processEvents()
        self.assertTrue(self.window.actions["reset_row_height"].isEnabled())
        self.window.actions["reset_row_height"].trigger()
        self.app.processEvents()
        self.assertEqual(self.window.project.tables["XY"].row_heights, {})
        self.assertEqual(header.sectionSize(2), view.fontMetrics().height() + 4)

    def test_header_context_menu_and_shortcuts_in_italian_and_english(self):
        for lang, labels in (
            ("en", ("Move up", "Move down", "Reset height")),
            ("it", ("Sposta su", "Sposta giù", "Ripristina altezza")),
        ):
            set_language(lang)
            w = MainWindow()
            w.project.add_tables({"T": pd.DataFrame({"X": [1.0, 2.0, 3.0]})})
            w.show_sheet("data", "T")
            w.show()
            self.app.processEvents()
            try:
                header = w.sheet.verticalHeader()
                pos = QPoint(10, header.sectionViewportPosition(1) + header.sectionSize(1) // 2)
                seen = []

                def inspect_menu():
                    menu = self.app.activePopupWidget()
                    if isinstance(menu, QMenu):
                        seen.extend(a.text() for a in menu.actions() if not a.isSeparator())
                        menu.close()

                QTimer.singleShot(0, inspect_menu)
                header._menu(pos)
                self.app.processEvents()
                for expected in labels:
                    self.assertIn(expected, seen)

                # Keyboard move up / down via actions
                w.sheet.selectRow(1)
                self.app.processEvents()
                w.actions["move_rows_up"].trigger()
                self.app.processEvents()
                self.assertEqual(w.project.tables["T"].raw["X"].tolist(), [2.0, 1.0, 3.0])
                w.actions["move_rows_down"].trigger()
                self.app.processEvents()
                self.assertEqual(w.project.tables["T"].raw["X"].tolist(), [1.0, 2.0, 3.0])
            finally:
                w.project.dirty = False
                w.close()
                self.app.processEvents()

    def test_virtual_rows_do_not_drag_or_enable_move(self):
        view = self.window.sheet
        header = view.verticalHeader()
        # Click virtual row index 5 (row 6 in 1-based)
        y_virtual = header.sectionViewportPosition(5) + header.sectionSize(5) // 2
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_virtual))
        self.assertIsNone(header._mode)
        QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_virtual))
        view.selectRow(5)
        self.app.processEvents()
        self.assertFalse(self.window.actions["move_rows_up"].isEnabled())
        self.assertFalse(self.window.actions["move_rows_down"].isEnabled())
        self.assertFalse(self.window.actions["reset_row_height"].isEnabled())

    def test_escape_cancels_move_and_resize_drag(self):
        view = self.window.sheet
        header = view.verticalHeader()
        y_row1 = header.sectionViewportPosition(1) + header.sectionSize(1) // 2
        y_row3 = header.sectionViewportPosition(3) + header.sectionSize(3) // 2
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_row1))
        QTest.mouseMove(header.viewport(), QPoint(12, y_row3))
        self.assertEqual(header._mode, "move")
        QTest.keyClick(view, Qt.Key.Key_Escape)
        self.assertIsNone(header._mode)
        QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_row3))
        self.assertEqual(self.window.project.tables["XY"].raw["Row title"].tolist(), ["A", "B1", "B2", "C", "D"])

        # Escape cancels resize drag
        y_border = header.sectionViewportPosition(1) + header.sectionSize(1)
        orig_h = header.sectionSize(1)
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_border))
        QTest.mouseMove(header.viewport(), QPoint(12, y_border + 20))
        QTest.keyClick(header, Qt.Key.Key_Escape)
        self.assertIsNone(header._mode)
        self.assertEqual(header.sectionSize(1), orig_h)
        QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_border + 20))
        self.assertEqual(self.window.project.tables["XY"].row_heights, {})


if __name__ == "__main__":
    unittest.main()
