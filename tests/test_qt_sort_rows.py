"""Qt UI tests for Edit -> Sort rows, column header context menu, quick actions, staleness, and selection."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analisi.i18n import set_language
from analisi.worksheet_row_identity import current_spans, row_of
from analisi.worksheet_sort import DESCENDING
from tests.test_worksheet_sort import _synthetic_sort_fixture_bytes
from trama_qt import theme
from trama_qt.sort_rows_dialog import SortRowsDialog
from trama_qt.window import MainWindow


class QtSortRowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-test-qt-sort"])
        theme.load_fonts()
        theme.apply(cls.app)

    def setUp(self):
        self.addCleanup(lambda: set_language("en"))
        set_language("it")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ordine-righe.alab"
        self.path.write_bytes(_synthetic_sort_fixture_bytes())
        self.window = MainWindow()
        self.addCleanup(self._cleanup)
        self.window.resize(1024, 768)
        self.window.show()
        self.window.open_path(self.path)
        self._wait()
        self.project = self.window.project
        self.window.show_sheet("data", "Ordine delle osservazioni")
        self.app.processEvents()

    def _wait(self):
        for _ in range(200):
            self.app.processEvents()
            if self.window.job is None:
                return
            QTest.qWait(20)

    def _cleanup(self):
        self.window.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_actions_enabling_menu_and_frozen_guard(self):
        self.assertEqual(self.window.actions["sort_rows"].text(), "Ordina righe…")
        self.assertEqual(self.window.actions["sort_by_x"].text(), "Ordina per X")
        self.assertEqual(self.window.actions["sort_by_row_title"].text(), "Ordina per titolo di riga")
        self.assertTrue(self.window.actions["sort_rows"].isEnabled())
        self.assertTrue(self.window.actions["sort_by_x"].isEnabled())
        self.assertTrue(self.window.actions["sort_by_row_title"].isEnabled())

        # Header check excludes calculated formula columns and allows source columns.
        title = "Ordine delle osservazioni"
        self.project.set_formula(title, "Calc", "=X * 2")
        self.window.reshow()
        self.app.processEvents()
        self.assertTrue(self.window.sheet._can_sort_column(1))
        self.assertFalse(self.window.sheet._can_sort_column(4))

        # Freeze disables sort actions and header sort.
        self.project.set_sheet_frozen(("data", title), True)
        self.window.update_actions()
        self.assertFalse(self.window.actions["sort_rows"].isEnabled())
        self.assertFalse(self.window.actions["sort_by_x"].isEnabled())
        self.assertFalse(self.window.actions["sort_by_row_title"].isEnabled())
        self.assertFalse(self.window.sheet._can_sort_column(1))

    def test_quick_actions_not_applicable_when_absent(self):
        import pandas as pd

        title, = self.project.add_tables({"Custom": pd.DataFrame({"Alpha": [2.0, 1.0], "Beta": [5.0, 6.0]})})
        self.window.show_sheet("data", title)
        self.app.processEvents()
        self.assertTrue(self.window.actions["sort_rows"].isEnabled())
        self.assertFalse(self.window.actions["sort_by_x"].isEnabled())
        self.assertFalse(self.window.actions["sort_by_row_title"].isEnabled())

    def test_reverse_rows_preserves_selection_and_is_undoable(self):
        title = "Ordine delle osservazioni"
        rows = self.project.tables[title]
        original = rows.raw["Campione"].tolist()
        self.window.sheet.select_block(0, 0, 1, 3, current_row=1, current_col=2)
        action = self.window.actions["reverse_rows"]
        self.assertEqual(action.text(), "Inverti ordine delle righe")
        self.assertTrue(action.isEnabled())
        action.trigger()
        self._wait()
        self.assertEqual(rows.raw["Campione"].tolist(), list(reversed(original)))
        self.assertEqual(row_of(current_spans(rows.raw), "base:1"), 7)
        self.assertEqual(self.window.sheet.box(), (5, 0, 6, 3))
        self.assertEqual(self.window.sheet.currentIndex().row(), 5)
        self.window.undo()
        self._wait()
        self.assertEqual(rows.raw["Campione"].tolist(), original)
        self.window.undo(redo=True)
        self._wait()
        self.assertEqual(rows.raw["Campione"].tolist(), list(reversed(original)))
        self.project.set_sheet_frozen(("data", title), True)
        self.window.update_actions()
        self.assertFalse(action.isEnabled())

    def test_move_selected_rows_to_edges_preserves_row_metadata(self):
        title = "Ordine delle osservazioni"
        rows = self.project.tables[title]
        self.window.sheet.select_block(2, 0, 3, 3, current_row=3, current_col=2)
        first = self.window.actions["move_rows_first"]
        last = self.window.actions["move_rows_last"]
        self.assertTrue(first.isEnabled())
        first.trigger()
        self._wait()
        self.assertEqual(rows.raw["Campione"].tolist()[:2], ["B-1", "A-2"])
        self.assertEqual(self.window.sheet.box(), (0, 0, 1, 3))
        self.assertFalse(first.isEnabled())
        self.assertTrue(last.isEnabled())
        last.trigger()
        self._wait()
        self.assertEqual(rows.raw["Campione"].tolist(), ["Z-1", "A-1", "VUOTO", "D", "B-2", "B-1", "A-2"])
        self.assertEqual(self.window.sheet.currentIndex().row(), 6)
        self.assertFalse(last.isEnabled())
        self.assertEqual(row_of(current_spans(rows.raw), "base:4"), 7)
        self.assertIn((6, 2), rows.excluded)
        self.assertEqual(rows.row_heights[6], 40)
        self.project.save(self.path)
        self.window.close_project()
        self.window.open_path(self.path)
        self._wait()
        reopened = self.window.project.tables[title]
        self.assertEqual(reopened.raw["Campione"].iloc[-1], "A-2")
        self.assertIn((6, 2), reopened.excluded)

    def test_dialog_cancel_stale_guard_selection_following_and_undo_redo(self):
        title = "Ordine delle osservazioni"
        ds = self.project.tables[title]
        view = self.window.sheet

        # Cancel leaves sheet untouched.
        dialog = SortRowsDialog(self.window, self.project, title, ds, initial_column=1)
        dialog.reject()
        dialog.deleteLater()
        self.assertEqual(ds.raw["Campione"].tolist(), ["Z-1", "A-1", "B-1", "A-2", "VUOTO", "D", "B-2"])

        # Mutate project while dialog is open -> accept must block and report error instead of writing.
        stale_dialog = SortRowsDialog(self.window, self.project, title, ds, initial_column=1)
        self.project.edit_cell(title, 0, 1, "9")
        stale_dialog.accept()
        self.assertFalse(stale_dialog.problem.isHidden())
        self.assertNotEqual(stale_dialog.result(), SortRowsDialog.DialogCode.Accepted)
        self.assertFalse(stale_dialog.ok_button.isEnabled())
        self.assertIsNone(stale_dialog.plan)
        stale_dialog.reject()
        stale_dialog.deleteLater()
        self.project.undo()

        # Select cell at tracked row 3 ("A-2"), col 3 -> Sort by X ascending moves cursor to row 2, col 3.
        self.window.sheet.select_block(3, 3, 3, 3, current_row=3, current_col=3)
        self.window.sort_by_x()
        self._wait()
        self.assertEqual(ds.raw["Campione"].tolist(), ["D", "A-1", "A-2", "B-1", "B-2", "Z-1", "VUOTO"])
        self.assertEqual(self.window.sheet.currentIndex().row(), 2)
        self.assertEqual(self.window.sheet.currentIndex().column(), 3)

        # Undo restores row order and active data; Redo reapplies.
        self.window.undo()
        self._wait()
        self.assertEqual(ds.raw["Campione"].tolist(), ["Z-1", "A-1", "B-1", "A-2", "VUOTO", "D", "B-2"])
        self.window.undo(redo=True)
        self._wait()
        self.assertEqual(ds.raw["Campione"].tolist(), ["D", "A-1", "A-2", "B-1", "B-2", "Z-1", "VUOTO"])

        # Multi-row selection stays contiguous when rows remain adjacent after X descending.
        self.window.sheet.select_block(1, 0, 2, 1, current_row=2, current_col=1)
        dlg = SortRowsDialog(self.window, self.project, title, ds, initial_column=1)
        dlg.descending_radio.setChecked(True)
        dlg.accept()
        plan = dlg.plan
        dlg.deleteLater()
        self.assertEqual(plan.direction, DESCENDING)
        self.window._apply_row_sort(title, plan=plan)
        self._wait()
        box = self.window.sheet.box()
        self.assertEqual(box, (3, 0, 4, 1))
        self.assertEqual(self.window.sheet.currentIndex().row(), 4)

        # Quick sort by row title restores alphabetical folded order.
        self.window.sort_by_row_title()
        self._wait()
        self.assertEqual(ds.raw["Campione"].tolist(), ["A-1", "A-2", "B-1", "B-2", "D", "Z-1", "VUOTO"])


if __name__ == "__main__":
    unittest.main()
