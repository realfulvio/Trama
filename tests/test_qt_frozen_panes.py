"""Fixed rows and columns in the Classica Qt worksheet and result tables (View → Freeze rows and columns…)."""
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from analisi.i18n import set_language
from analisi.reporting import Result
from trama_qt.classic_bar import MENUS
from trama_qt.frozen_panes import FreezeDialog, FrozenPane, column_boundaries
from trama_qt.project import Run
from trama_qt.window import MainWindow


def sheet_frame():
    """The 60 × 24 fixture of the delivery: ID, sample and M01…M22 = row·100 + column + 0.125."""
    rows = range(1, 61)
    data = {"ID": [f"R{row:03d}" for row in rows], "Campione": [f"Serie {(row - 1) % 4 + 1}" for row in rows]}
    for column in range(1, 23):
        data[f"M{column:02d}"] = [f"{row * 100 + column}.125" for row in rows]
    return pd.DataFrame(data)


A1_D4 = [["R001", "Serie 1", "101.125", "102.125"], ["R002", "Serie 2", "201.125", "202.125"],
         ["R003", "Serie 3", "301.125", "302.125"], ["R004", "Serie 4", "401.125", "402.125"]]


class FrozenPanesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-frozen-panes"])

    def setUp(self):
        set_language("en")
        self.window = MainWindow()
        self.window.error = lambda error: self.fail(str(error))
        self.window.resize(1280, 800)
        self.window.show()
        self.window.activateWindow()
        QTest.qWaitForWindowActive(self.window)
        self.window.project.add_tables({"Sheet": sheet_frame()})
        self.window.show_sheet("data", "Sheet")
        self.settle()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        set_language("en")
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def settle(self):
        for _ in range(3):
            self.app.processEvents()
            QTest.qWait(5)

    @property
    def view(self):
        return self.window.sheet

    def cell(self, address):
        column = ord(address[0]) - ord("A")
        return self.view.model().index(int(address[1:]) - 1, column)

    def freeze_from(self, address, *, rows=None, columns=None):
        """Freeze rows and columns… through the dialog, proposed from the active cell."""
        self.view.setCurrentIndex(self.cell(address))
        seen = {}

        def answer():
            dialog = next(widget for widget in QApplication.topLevelWidgets()
                          if isinstance(widget, FreezeDialog) and widget.isVisible())
            seen["proposal"] = dialog.rows.value(), dialog.columns.value()
            seen["boundary"] = dialog.boundary.text()
            seen["ok"] = dialog.ok.isEnabled() and dialog.ok.isDefault()
            if rows is not None:
                dialog.rows.setValue(rows)
            if columns is not None:
                dialog.columns.setValue(columns)
            QTest.keyClick(dialog.rows, Qt.Key.Key_Return)  # Enter confirms: Freeze is the default button.

        QTimer.singleShot(0, answer)
        self.window.actions["freeze_panes"].trigger()
        self.settle()
        return seen

    def type_into_current(self, text):
        """Typing starts the editor; the rest of the text goes to the editor that has the focus."""
        QTest.keyClicks(self.view, text[0])
        editor = self.window.focusWidget()
        QTest.keyClicks(editor, text[1:])
        return editor

    def visible(self, address):
        """True when the cell is fully on screen and not covered by another part of the table."""
        index = self.cell(address)
        view = self.view
        rect = view.visualRect(index)
        panes = view.frozen_panes
        width, height = panes.extent if panes is not None else (0, 0)
        screen = view.viewport().rect().adjusted(-width, -height, 0, 0)  # Fixed parts lie left of and above it.
        if not screen.contains(rect):
            return False
        return view.indexAt(rect.center()) == index

    def test_menu_entries_and_texts(self):
        self.assertIn("freeze_panes", dict(MENUS)["View"])
        self.assertIn("unfreeze_panes", dict(MENUS)["View"])
        set_language("it")
        window = MainWindow()
        self.addCleanup(window.close)
        self.assertEqual(window.actions["freeze_panes"].text(), "Fissa righe e colonne…")
        self.assertEqual(window.actions["unfreeze_panes"].text(), "Libera righe e colonne")

    def test_fixture_flow_keyboard_copy_edit_and_one_undo(self):
        seen = self.freeze_from("C3")
        self.assertEqual(seen["proposal"], (2, 2))
        self.assertTrue(seen["ok"])
        self.assertIn("Rows 1–2", seen["boundary"])
        panes = self.view.frozen_panes
        self.assertEqual((panes.rows, panes.columns, panes.fixed), (2, 2, (2, 2)))
        self.assertEqual(set(panes.parts), {"left", "top", "corner"})
        for part in panes.parts.values():
            self.assertIs(part.model(), self.view.model())
            self.assertIs(part.selectionModel(), self.view.selectionModel())  # One logical selection.

        for _ in range(27):
            QTest.keyClick(self.view, Qt.Key.Key_Down)
        for _ in range(13):
            QTest.keyClick(self.view, Qt.Key.Key_Right)
        self.settle()
        current = self.view.currentIndex()
        self.assertEqual((current.row(), current.column()), (29, 15))  # P30
        self.assertEqual(self.view.model().data(current), "3014.125")
        self.assertGreater(self.view.horizontalScrollBar().value(), 0)
        self.assertGreater(self.view.verticalScrollBar().value(), 0)
        for address in ("A1", "B1", "A2", "B2", "A30", "B30", "P1", "P2", "P30"):
            self.assertTrue(self.visible(address), address)
        self.assertFalse(self.visible("C3"))  # Scrolled away under the fixed part.
        # No cell is cut on its left at the boundary: it would show only the last digits of a number.
        self.assertIsNone(panes._straddle("h"))
        self.assertIsNone(panes._straddle("v"))
        for value in (37, 250, 133):
            self.view.horizontalScrollBar().setValue(value)
            self.view.verticalScrollBar().setValue(value)
            self.settle()
            self.assertIsNone(panes._straddle("h"), value)
            self.assertIsNone(panes._straddle("v"), value)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
        self.view.horizontalScrollBar().setValue(self.view.horizontalScrollBar().maximum())
        self.settle()
        for axis in ("h", "v"):  # At the very end a cut cell is covered.
            self.assertEqual(panes.masks[axis].isVisible(), panes._straddle(axis) is not None)
        for address in ("A1", "B2"):
            self.assertTrue(self.visible(address), address)

        self.view.select_block(0, 0, 3, 3)
        self.assertTrue(self.view.copy())
        lines = QGuiApplication.clipboard().text().replace("\r\n", "\n").rstrip("\n").split("\n")
        self.assertEqual([line.split("\t") for line in lines], A1_D4)  # Stored digits, each value once.

        self.view.setCurrentIndex(self.cell("C3"))
        editor = self.type_into_current("-47.625")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.settle()
        self.assertEqual(self.window.project.tables["Sheet"].frame().iloc[2, 2], "-47.625")
        self.window.undo()
        self.settle()
        self.assertEqual(str(self.window.project.tables["Sheet"].frame().iloc[2, 2]), "301.125")
        self.assertEqual((self.window.sheet.frozen_panes.rows, self.window.sheet.frozen_panes.columns), (2, 2))
        self.window.undo(redo=True)
        self.settle()
        self.assertEqual((self.window.sheet.frozen_panes.rows, self.window.sheet.frozen_panes.columns), (2, 2))

    def test_typing_in_a_fixed_cell_edits_it_in_place(self):
        self.freeze_from("C3")
        self.view.verticalScrollBar().setValue(400)
        self.view.horizontalScrollBar().setValue(500)
        self.settle()
        self.view.setCurrentIndex(self.cell("B2"))
        editor = self.type_into_current("Serie X")
        self.assertIsInstance(editor, QLineEdit)
        corner = self.view.frozen_panes.parts["corner"]
        self.assertIs(editor.parentWidget(), corner.viewport())
        self.assertTrue(corner.viewport().rect().contains(editor.geometry().center()))
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.settle()
        self.assertEqual(self.window.project.tables["Sheet"].frame().iloc[1, 1], "Serie X")
        self.assertEqual(self.view.currentIndex().row(), 2)  # Enter moves down, as in the free grid.
        self.assertIs(self.window.focusWidget(), self.view)

    def test_selection_crosses_both_boundaries_by_keyboard_and_mouse(self):
        self.freeze_from("C3")
        self.view.verticalScrollBar().setValue(200)
        self.view.horizontalScrollBar().setValue(300)
        self.settle()
        self.view.setCurrentIndex(self.cell("B2"))
        for key in (Qt.Key.Key_Right, Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Down):
            QTest.keyClick(self.view, key, Qt.KeyboardModifier.ShiftModifier)
        self.settle()
        self.assertEqual(self.view.box(), (1, 1, 3, 3))

        corner = self.view.frozen_panes.parts["corner"]
        start = corner.visualRect(self.cell("A1")).center()
        target_cell = self.view.indexAt(self.view.viewport().rect().center())
        target = self.view.visualRect(target_cell).center() - corner._origin()
        QTest.mousePress(corner.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(corner.viewport(), target)
        QTest.mouseRelease(corner.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
        self.settle()
        self.assertEqual(self.view.box(), (0, 0, target_cell.row(), target_cell.column()))
        self.assertIs(self.window.focusWidget(), self.view)

    def test_paste_across_the_boundaries_is_one_step(self):
        self.freeze_from("C3")
        QGuiApplication.clipboard().setText("1.5\t2.5\t3.5\n4.5\t5.5\t6.5\n7.5\t8.5\t9.5\n")
        self.view.setCurrentIndex(self.cell("B2"))
        self.view.paste()
        self.settle()
        frame = self.window.project.tables["Sheet"].frame()
        self.assertEqual(frame.iloc[1:4, 1:4].astype(str).values.tolist(),
                         [["1.5", "2.5", "3.5"], ["4.5", "5.5", "6.5"], ["7.5", "8.5", "9.5"]])
        self.window.undo()
        self.settle()
        frame = self.window.project.tables["Sheet"].frame()
        self.assertEqual(frame.iloc[1, 1], "Serie 2")
        self.assertEqual(str(frame.iloc[3, 3]), "402.125")

    def test_widths_heights_zoom_and_reorder_stay_aligned(self):
        self.freeze_from("C3")
        panes = self.view.frozen_panes
        self.view.setColumnWidth(1, 180)
        self.window.set_row_height(0, 40)
        self.window.zoom_table(1)
        self.settle()
        for part in panes.parts.values():
            for column in range(4):
                self.assertEqual(part.columnWidth(column), self.view.columnWidth(column))
            for row in range(4):
                self.assertEqual(part.rowHeight(row), self.view.rowHeight(row))
        corner, left, top = (panes.parts[name] for name in ("corner", "left", "top"))
        width = self.view.columnWidth(0) + self.view.columnWidth(1)
        height = self.view.rowHeight(0) + self.view.rowHeight(1)
        self.assertEqual(panes.extent, (width, height))
        self.assertEqual(corner.width(), self.view.verticalHeader().width())
        self.assertEqual(corner.height(), self.view.horizontalHeader().height())
        area = self.view.viewport().geometry()  # The fixed parts sit beside the scrolling cells, never over them.
        self.assertEqual((left.geometry().right() + 1, left.geometry().top()), (area.left(), area.top()))
        self.assertEqual((top.geometry().left(), top.geometry().bottom() + 1), (area.left(), area.top()))
        self.assertEqual(corner.geometry().bottomRight() + QPoint(1, 1), area.topLeft())
        self.assertEqual(corner.geometry().topLeft(), QPoint(self.view.frameWidth(), self.view.frameWidth()))

        self.view.setCurrentIndex(self.cell("D5"))
        self.window.move_rows(4, 5, 0)  # R005 becomes the first row: the fixed rows show the new order.
        self.settle()
        sheet = self.window.sheet
        self.assertEqual(sheet.model().data(sheet.model().index(0, 0)), "R005")
        self.assertEqual((sheet.frozen_panes.rows, sheet.frozen_panes.columns), (2, 2))
        self.assertTrue(sheet.currentIndex().isValid())

    def test_free_rows_only_columns_only_and_unfreeze(self):
        self.freeze_from("A4")
        self.assertEqual(set(self.view.frozen_panes.parts), {"top", "corner"})
        self.freeze_from("D1")
        self.assertEqual(set(self.view.frozen_panes.parts), {"left", "corner"})
        self.window.actions["unfreeze_panes"].trigger()
        self.settle()
        self.assertFalse(self.view.frozen_panes.parts)
        self.assertFalse(self.view.frozen_panes.active())
        self.view.setCurrentIndex(self.cell("P30"))
        self.assertEqual(self.view.indexAt(self.view.visualRect(self.cell("P30")).center()), self.cell("P30"))

    def test_narrow_window_keeps_one_scrolling_column_and_restores(self):
        self.freeze_from("I3")  # Eight fixed columns.
        panes = self.view.frozen_panes
        self.assertEqual(panes.fixed, (2, 8))
        self.window.resize(760, 600)
        self.settle()
        self.assertLess(panes.fixed[1], 8)
        self.assertGreaterEqual(self.view.viewport().width(), self.view.columnWidth(panes.fixed[1]))
        self.assertEqual(panes.columns, 8)  # The wish is kept.
        self.window.resize(1600, 900)
        self.settle()
        self.assertEqual(panes.fixed, (2, 8))

    def test_wish_follows_the_sheet_in_this_session_but_not_the_saved_file(self):
        self.window.project.add_tables({"Other": pd.DataFrame({"A": [1.0, 2.0]})})
        self.freeze_from("C3")
        self.window.show_sheet("data", "Other")
        self.settle()
        self.assertIsNone(self.window.sheet.frozen_panes)
        self.window.show_sheet("data", "Sheet")
        self.settle()
        self.assertEqual(self.window.sheet.frozen_panes.fixed, (2, 2))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixed.alab"
            self.window.project.save(path)
            self.window.project.dirty = False
            copy = Path(folder) / "reopened.alab"
            copy.write_bytes(path.read_bytes())
            self.window.open_path(copy)  # A new tab with the same data: the view starts free.
            self.settle()
            self.assertEqual(len(self.window.sessions), 2)
            self.window.show_sheet("data", "Sheet")
            self.settle()
            self.assertIsNone(self.window.sheet.frozen_panes)
            self.assertEqual(self.window.project.tables["Sheet"].frame().iloc[29, 15], "3014.125")

    def test_xy_groups_keep_the_boundary_whole(self):
        frame = pd.DataFrame({"X": [1.0, 2.0, 3.0], "Y [1]": [1.0, 2.0, 3.0], "Y [2]": [1.5, 2.5, 3.5],
                              "Y [3]": [1.25, 2.25, 3.25], "Z [1]": [4.0, 5.0, 6.0], "Z [2]": [4.5, 5.5, 6.5]})
        frame.attrs["table_format"] = "xy"
        self.window.project.add_tables({"XY": frame})
        self.window.show_sheet("data", "XY")
        self.settle()
        self.assertEqual(column_boundaries(self.view.model())[:4], [0, 1, 4, 6])
        seen = self.freeze_from("C2", columns=3)
        self.assertIn("would split group A", seen["boundary"])
        self.assertEqual(self.view.frozen_panes.columns, 4)
        seen = self.freeze_from("B2")
        self.assertEqual(seen["proposal"], (1, 1))
        self.assertEqual(self.view.frozen_panes.columns, 1)
        top, left = self.view.frozen_panes.parts["top"], self.view.frozen_panes.parts["left"]
        for column in range(1, 6):  # A small table fits the window: the fixed row still lines up with the columns.
            self.assertEqual(top.columnViewportPosition(column), self.view.columnViewportPosition(column))
        for row in range(1, 4):
            self.assertEqual(left.rowViewportPosition(row), self.view.rowViewportPosition(row))

    def test_unsupported_sheet_explains_in_the_dialog(self):
        frame = pd.DataFrame({"A": [1.0], "B": [2.0]})
        frame.attrs["table_format"] = "grouped"
        self.window.project.add_tables({"Grouped": frame})
        self.window.show_sheet("data", "Grouped")
        self.settle()
        seen = {}

        def answer():
            dialog = next(widget for widget in QApplication.topLevelWidgets()
                          if isinstance(widget, FreezeDialog) and widget.isVisible())
            seen["ok"] = dialog.ok.isEnabled()
            seen["text"] = dialog.boundary.text()
            dialog.reject()

        QTimer.singleShot(0, answer)
        self.window.actions["freeze_panes"].trigger()
        self.assertFalse(seen["ok"])
        self.assertIn("not supported yet", seen["text"])

    def test_result_table_scrolls_selects_and_copies(self):
        frame = pd.DataFrame({f"C{column}": [row + column / 1000 for row in range(80)] for column in range(12)})
        run = Run("Descriptive statistics", "Sheet", {})
        index, _ = self.window.project.add_result(run, Result({"Table": frame}))
        self.window.show_sheet("result", index)
        self.settle()
        view = self.window.result_tabs.currentWidget()
        view.setCurrentIndex(view.model().index(3, 2))
        QTimer.singleShot(0, lambda: QTest.keyClick(
            next(w for w in QApplication.topLevelWidgets() if isinstance(w, FreezeDialog) and w.isVisible()).rows,
            Qt.Key.Key_Return))
        self.window.actions["freeze_panes"].trigger()
        self.settle()
        panes = view.frozen_panes
        self.assertEqual(panes.fixed, (3, 2))
        self.assertTrue(all(isinstance(part, FrozenPane) for part in panes.parts.values()))
        view.scrollTo(view.model().index(79, 12))
        self.settle()
        corner = view.model().index(0, 0)
        self.assertEqual(view.indexAt(view.visualRect(corner).center()), corner)
        view.selectionModel().select(
            __import__("PySide6.QtCore", fromlist=["QItemSelection"]).QItemSelection(
                view.model().index(0, 0), view.model().index(5, 3)),
            view.selectionModel().SelectionFlag.ClearAndSelect)
        view.copy()
        lines = QGuiApplication.clipboard().text().rstrip("\n").split("\n")
        self.assertEqual(len(lines), 6)
        self.assertEqual([float(value) for value in lines[1].split("\t")[1:]], [1 + column / 1000 for column in range(3)])
        self.window.show_sheet("data", "Sheet")
        self.settle()
        self.window.show_sheet("result", index)
        self.settle()
        self.assertEqual(self.window.result_tabs.currentWidget().frozen_panes.fixed, (3, 2))


if __name__ == "__main__":
    unittest.main()
