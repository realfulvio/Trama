"""Edit → Find in Cells… / Replace in Cells… (Classica Qt): search, scope, preview, one-step Undo, staleness."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from analisi.cell_search import (FORMULA, NUMBER, CellScan, SearchOptions, apply_replace, cell_name, plan_replace,
                                 worksheet_texts)
from analisi.data import Dataset
from analisi.i18n import set_language
from trama_qt import cell_search
from trama_qt.classic_bar import MENUS
from trama_qt.project import Project
from trama_qt.window import MainWindow

TITLE = "Celle"
ROWS = [
    ["A01", "Dose A", 1.234567890123, "Dose $"],
    ["A02", "dose a", 2.50, "invariato"],
    ["A03", "Controllo", 3.75, "preDose"],
    ["A04", "DOSE", 42.00, "dose"],
    ["A05", "Controllo", 5.25, "dosé"],
    ["A06", "ZZ", 6.50, "campione 42"],
]
EXPECTED = [
    ["A01", "serie A", 1.234567890123, "serie $"],
    ["A02", "serie a", 2.50, "invariato"],
    ["A03", "Controllo", 3.75, "preserie"],
    ["A04", "serie", 42.00, "serie"],
    ["A05", "Controllo", 5.25, "dosé"],
    ["A06", "ZZ", 6.50, "campione 42"],
]
# The cases of the hand-over package (casi.json): addresses are worksheet cells, A1 = first cell.
CASES = [
    ({"query": "dose"}, ["B1", "D1", "B2", "D3", "B4", "D4"], None),
    ({"query": "dose", "whole_cell": True}, ["B4", "D4"], None),
    ({"query": "dose", "case_sensitive": True}, ["B2", "D4"], None),
    ({"query": "dose", "selection": ["B1", "B2", "D4"]}, ["B1", "B2", "D4"], None),
    ({"query": "$"}, ["D1"], None),
    ({"query": "1.234567890123", "whole_cell": True}, ["C1"], []),
    ({"query": "42"}, ["C4", "D6"], ["D6"]),
]


def _frame(rows=ROWS):
    return pd.DataFrame(rows, columns=["ID", "Etichetta", "Valore", "Nota"]).astype(
        {"ID": "string", "Etichetta": "string", "Nota": "string"})


def _cell(address):
    return int(address[1:]) - 1, ord(address[0]) - 65


def _options(case):
    return SearchOptions(case["query"], case.get("case_sensitive", False), case.get("whole_cell", False))


def _write_fixture(path):
    doc = {
        "version": 2,
        "tables": [{
            "title": TITLE,
            "columns": ["ID", "Etichetta", "Valore", "Nota"],
            "kinds": ["text", "text", "numeric", "text"],
            "rows": ROWS,
            "formulas": [],
            "analyses": [["Descriptive statistics", {"Variables": ["Valore"]}]],
            "excluded": [],
            "table_format": "multivariable",
            "graph_styles": {},
        }],
        "layouts": [],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


class CellSearchEngineTests(unittest.TestCase):
    def test_package_cases(self):
        frame = _frame()
        dataset = Dataset(frame.copy(), table_format="multivariable")
        for case, expected, writeable in CASES:
            with self.subTest(case=case):
                options = _options(case)
                ranges = [(*_cell(a), *_cell(a)) for a in case["selection"]] if "selection" in case else None
                matches = CellScan(len(frame), 4, worksheet_texts(frame, options), options, ranges=ranges,
                                   chunk=2).run()
                self.assertEqual([cell_name(*cell) for cell in matches], expected)
                if writeable is not None:
                    plan = plan_replace(dataset, frame, matches, options, "x")
                    self.assertEqual([cell_name(row, column) for row, column, *_ in plan.changes], writeable)
                    self.assertEqual(plan.skipped[NUMBER], len(expected) - len(writeable))

    def test_replace_matches_expected_copy_and_keeps_dollar_literal(self):
        frame = _frame()
        dataset = Dataset(frame.copy(), table_format="multivariable")
        options = SearchOptions("dose")
        matches = CellScan(len(frame), 4, worksheet_texts(frame, options), options).run()
        plan = plan_replace(dataset, frame, matches, options, "serie")
        apply_replace(dataset, plan.changes)
        self.assertEqual(dataset.raw.astype(object).values.tolist(), EXPECTED)
        dollar = SearchOptions("serie")
        frame = dataset.frame()
        matches = CellScan(len(frame), 4, worksheet_texts(frame, dollar), dollar).run()
        apply_replace(dataset, plan_replace(dataset, frame, matches, dollar, r"$1\g<0>").changes)
        self.assertEqual(dataset.raw.iat[0, 3], r"$1\g<0> $")

    def test_empty_query_is_refused_and_empty_replacement_empties_the_cell(self):
        with self.assertRaises(ValueError):
            SearchOptions("").matcher()
        frame = _frame()
        dataset = Dataset(frame.copy(), table_format="multivariable")
        options = SearchOptions("dose", whole_cell=True)
        matches = CellScan(len(frame), 4, worksheet_texts(frame, options), options).run()
        apply_replace(dataset, plan_replace(dataset, frame, matches, options, "").changes)
        self.assertTrue(pd.isna(dataset.raw.iat[3, 1]) and pd.isna(dataset.raw.iat[3, 3]))

    def test_numbers_by_stored_value_and_by_screen_text(self):
        from analisi.worksheet_number_format import Renderer

        frame = pd.DataFrame({"V": [1.234567890123, 2.5]})
        renderer = Renderer({0: {"mode": "fixed", "digits": 2}})
        for query in ("1.234567890123", "1.23"):
            options = SearchOptions(query, whole_cell=True)
            texts = worksheet_texts(frame, options, renderer, str)
            self.assertEqual(CellScan(2, 1, texts, options).run(), [(0, 0)], query)

    def test_overlapping_ranges_visit_a_cell_once(self):
        frame = _frame()
        options = SearchOptions("dose")
        scan = CellScan(len(frame), 4, worksheet_texts(frame, options), options,
                        ranges=[(0, 0, 3, 3), (1, 1, 5, 3)], chunk=1)
        self.assertEqual([cell_name(*cell) for cell in scan.run()], ["B1", "D1", "B2", "D3", "B4", "D4"])


class QtCellSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-qt-cell-search"])

    def setUp(self):
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "celle.alab"
        _write_fixture(self.path)
        self.window = MainWindow()
        self.addCleanup(self._cleanup)
        self.errors = []
        self.window.error = lambda err: self.errors.append(str(err))
        self.window.resize(1024, 768)
        self.window.show()
        self.window.open_path(self.path)
        self._wait()
        self.window.open_sheet(("data", TITLE))
        self.app.processEvents()

    def _wait(self):
        for _ in range(300):
            self.app.processEvents()
            if self.window.job is None:
                return
            QTest.qWait(20)

    def _cleanup(self):
        set_language("en")
        if self.window.cell_search is not None:
            self.window.cell_search.close()
        self.window.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def panel(self, query, **options):
        self.window.open_cell_search(replace=options.pop("replace", False))
        panel = self.window.cell_search
        panel.query.setText(query)
        panel.case.setChecked(options.get("case", False))
        panel.whole.setChecked(options.get("whole", False))
        panel.scope.setCurrentIndex(1 if options.get("selection") else 0)
        return panel

    def step(self, panel, direction=1):
        panel.find(direction)
        panel.run_scan_now()
        current = self.window.sheet.currentIndex()
        return cell_name(current.row(), current.column())

    def values(self):
        return self.window.project.tables[TITLE].raw.astype(object).values.tolist()

    def test_menu_shortcuts_and_command_search(self):
        edit = dict(MENUS)["Edit"]
        self.assertIn("find_cells", edit)
        self.assertIn("replace_cells", edit)
        actions = self.window.actions
        self.assertEqual(actions["replace_cells"].shortcut().toString(), "Ctrl+H")
        self.assertEqual(actions["find_sheet"].shortcut().toString(), "Ctrl+F")
        self.assertEqual(actions["format_graph"].shortcut().toString(), "Ctrl+Shift+F")
        self.assertTrue(actions["find_cells"].isEnabled())
        from trama_qt.command_search import CommandSearchDialog
        dialog = CommandSearchDialog(self.window)
        self.addCleanup(dialog.deleteLater)
        dialog.query.setText("Find in Cells")
        captions = [dialog.results.topLevelItem(i).text(0) for i in range(dialog.results.topLevelItemCount())]
        self.assertTrue(any("Find in Cells" in caption for caption in captions), captions)

    def test_next_previous_count_position_and_wrap(self):
        panel = self.panel("dose")
        self.window.sheet.setCurrentIndex(self.window.sheet.model().index(0, 0))
        visited = [self.step(panel) for _ in range(6)]
        self.assertEqual(visited, ["B1", "D1", "B2", "D3", "B4", "D4"])
        self.assertIn("6 of 6", panel.position.text())
        self.assertEqual(self.step(panel), "B1")
        self.assertIn("continued from the beginning", panel.position.text())
        self.assertEqual(self.step(panel, -1), "D4")
        self.assertIn("continued from the end", panel.position.text())
        self.assertEqual(self.step(panel, -1), "B4")
        self.assertIn("Match 5 of 6 · cell B4", panel.position.text())

    def test_enter_goes_to_next_and_italian_texts(self):
        set_language("it")
        self.window.retranslate() if hasattr(self.window, "retranslate") else None
        panel = self.panel("dose")
        self.assertEqual(panel.windowTitle(), "Trova e sostituisci nelle celle")
        self.assertTrue(panel.next_button.isDefault())
        panel.query.setFocus()
        QTest.keyClick(panel.query, Qt.Key.Key_Return)
        panel.run_scan_now()
        self.assertIn("Corrispondenza 1 di 6", panel.position.text())

    def test_whole_cell_and_case(self):
        panel = self.panel("dose", whole=True)
        self.assertEqual([self.step(panel) for _ in range(2)], ["B4", "D4"])
        panel = self.panel("dose", case=True)
        self.window.sheet.setCurrentIndex(self.window.sheet.model().index(0, 0))
        self.assertEqual([self.step(panel) for _ in range(2)], ["B2", "D4"])

    def test_discontinuous_selection_scope_is_kept_while_moving(self):
        sheet = self.window.sheet
        model = sheet.model()
        selection = QItemSelection()
        for address in ("B1", "B2", "D4"):
            row, column = _cell(address)
            selection.select(model.index(row, column), model.index(row, column))
        sheet.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        sheet.selectionModel().setCurrentIndex(model.index(0, 0), QItemSelectionModel.SelectionFlag.NoUpdate)
        panel = self.panel("dose", selection=True)
        self.assertEqual([self.step(panel) for _ in range(4)], ["B1", "B2", "D4", "B1"])
        self.assertIn("of 3", panel.position.text())

    def test_numbers_found_by_stored_digits_with_two_decimals_on_screen(self):
        project = self.window.project
        project.set_table_number_format(TITLE, ["Valore"], {"mode": "fixed", "digits": 2})
        self.window.reshow()
        model = self.window.sheet.model()
        self.assertEqual(model.data(model.index(0, 2)), "1.23")
        panel = self.panel("1.234567890123", whole=True)
        self.assertEqual(self.step(panel), "C1")
        panel = self.panel("1.23", whole=True)
        self.assertEqual(self.step(panel), "C1")

    def test_results_are_search_only(self):
        self.window.open_sheet(("result", 0))
        self.window.recalculate()
        self._wait()
        self.window.show_sheet("result", 0)
        self.app.processEvents()
        self.assertIsNotNone(self.window.result_tabs)
        panel = self.panel("Valore")
        self.assertFalse(panel.replace_button.isEnabled())
        self.assertFalse(panel.replacement.isEnabled())
        self.assertIn("searched but not replaced", panel.notice.text())
        panel.find()
        panel.run_scan_now()
        self.assertIn("Match 1 of", panel.position.text())

    def test_replace_all_preview_apply_single_undo_and_one_recalculation(self):
        panel = self.panel("dose", replace=True)
        panel.replacement.setText("serie")
        previews = []
        recalculated = []

        def accept(dialog):
            table = dialog.table
            previews.append((dialog.plan, table.rowCount(), table.item(0, 0).text(), table.item(0, 2).text()))
            return QDialog.DialogCode.Accepted

        original = self.window.refresh_runs
        with patch.object(cell_search.ReplacePreviewDialog, "exec", accept), \
                patch.object(self.window, "refresh_runs",
                             side_effect=lambda *a, **k: (recalculated.append(a), original(*a, **k))):
            panel.replace_all()
            panel.run_scan_now()
        self._wait()
        (plan, rows, first, after), = previews
        self.assertEqual(len(plan.changes), 6)
        self.assertEqual((rows, first, after), (6, "B1", "serie A"))
        self.assertEqual(len(recalculated), 1)
        self.assertEqual(self.values(), EXPECTED)
        self.assertEqual(self.errors, [])
        self.window.undo()
        self._wait()
        self.assertEqual(self.values(), ROWS)
        self.window.undo(redo=True)
        self._wait()
        self.assertEqual(self.values(), EXPECTED)
        saved = Path(self.tmp.name) / "dopo.alab"
        self.window.project.save(saved)
        reopened = Project()
        reopened.load(saved)
        self.assertEqual(reopened.tables[TITLE].raw.astype(object).values.tolist(), EXPECTED)

    def test_preview_lists_exclusions_with_reason_and_keeps_excluded_flags(self):
        project = self.window.project
        project.set_formula(TITLE, "Copia", "=Nota")
        project.toggle_exclusion(TITLE, [(3, 3)])
        self.window.reshow()
        self._wait()
        panel = self.panel("dose", replace=True)
        panel.replacement.setText("serie")
        captured = []
        with patch.object(cell_search.ReplacePreviewDialog, "exec",
                          lambda dialog: captured.append((dialog.plan, dialog.skipped.text()))
                          or QDialog.DialogCode.Accepted):
            panel.replace_all()
            panel.run_scan_now()
        self._wait()
        plan, skipped = captured[0]
        self.assertEqual(plan.skipped[FORMULA], 2)  # Copia = Nota: E1 and E3 (D4 is excluded, so E4 is empty).
        self.assertIn("in calculated columns", skipped)
        dataset = project.tables[TITLE]
        self.assertIn((3, 3), dataset.excluded)
        self.assertEqual(dataset.raw.iat[3, 3], "serie")

    def test_apply_refused_when_the_sheet_changed_after_the_preview(self):
        panel = self.panel("dose", replace=True)
        panel.replacement.setText("serie")

        def edit_then_accept(dialog):
            self.window.edit_cell(TITLE, 0, 1, "Dose B")  # Changed while the preview is open.
            return QDialog.DialogCode.Accepted

        with patch.object(cell_search.ReplacePreviewDialog, "exec", edit_then_accept):
            panel.replace_all()
            panel.run_scan_now()
        self._wait()
        self.assertTrue(any("changed after the preview" in error for error in self.errors), self.errors)
        self.assertEqual(self.window.project.tables[TITLE].raw.iat[1, 1], "dose a")

    def test_switching_sheet_with_the_preview_open_applies_nothing(self):
        panel = self.panel("dose", replace=True)
        panel.replacement.setText("serie")
        other = next(ref for ref in self.window.sheet_refs.values() if ref != ("data", TITLE))

        def switch_then_accept(dialog):
            self.window.open_sheet(other)
            return QDialog.DialogCode.Accepted

        with patch.object(cell_search.ReplacePreviewDialog, "exec", switch_then_accept):
            panel.replace_all()
            panel.run_scan_now()
        self.assertTrue(any("changed after the preview" in error for error in self.errors), self.errors)
        self.assertEqual(self.values(), ROWS)
        self.assertFalse(self.window.project.dirty)

    def test_frozen_sheet_is_search_only(self):
        self.window.project.set_sheet_frozen(("data", TITLE), True)
        self.window.show_sheet("data", TITLE)
        panel = self.panel("dose")
        self.assertFalse(panel.replace_button.isEnabled())
        self.assertIn("frozen", panel.notice.text())
        self.assertEqual(self.step(panel), "B1")

    def test_stop_scan_changes_nothing(self):
        panel = self.panel("dose")
        panel.find()
        if panel.scan is not None:
            panel.stop_scan()
        self.assertIsNone(panel.scan)
        self.assertEqual(self.values(), ROWS)
        self.assertFalse(self.window.project.dirty)


if __name__ == "__main__":
    unittest.main()
