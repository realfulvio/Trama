"""Navigator commands, persistent frozen output, and worksheet notes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from matplotlib.figure import Figure
import pandas as pd

from analisi.analysis_chain import ResultSource
from analisi.figure_export import export_figure, export_pdf_bundle
from analisi.info import InfoSheet
from analisi.presentation import Layout
from analisi.reporting import Result
from analisi.worksheet_join import METHOD as JOIN, RIGHT_SHEET
from trama_qt.project import Project

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox
except ImportError:
    QApplication = None


def sample_project():
    project = Project()
    project.add_tables({"Measurements": pd.DataFrame({"X": [1., 2., 3.], "Y": [2., 4., 6.]}),
                        "Other": pd.DataFrame({"X": [1., 2., 3.]})})
    return project


def result_graph():
    figure = Figure(figsize=(4, 3))
    axes = figure.add_subplot()
    axes.plot([1, 2, 3], [2, 4, 6])
    axes.set_title("Snapshot chart")
    table = pd.DataFrame({"Slope": pd.array([2., pd.NA], dtype="Float64")},
                         index=pd.MultiIndex.from_tuples([("A", 1), ("B", 2)], names=["Series", "Fit"]))
    return Result({"Report": table}, figure)


class ProjectSheetOperations(unittest.TestCase):
    def setUp(self):
        self.project = sample_project()
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_rename_keeps_join_recipe_layout_and_undo(self):
        p = self.project
        note = InfoSheet("Calibration", table="Measurements", fields=(("Factor", "2"),))
        p.update_info_sheets({note.uid: note})
        p.edit_cell("Measurements", 0, 1, "7")
        run = p.candidate("Measurements", "Linear regression", {})
        p.add_result(run, result_graph())
        join = p.candidate("Other", JOIN, {RIGHT_SHEET: "Measurements"})
        p.add_result(join, None)
        p.put_layout(Layout("Figures", 1, [run.reference]))
        renamed = p.rename_sheet(("data", "Measurements"), "Calibration $ – 1")
        self.assertEqual(p.info_sheets[note.uid].table, renamed[1])
        self.assertEqual(run.reference, (renamed[1], 0))
        self.assertEqual(p.layouts[0].panels, [run.reference])
        self.assertEqual(p.tables["Other"].analyses[0][1][RIGHT_SHEET], renamed[1])
        title, _ = p.undo()
        self.assertEqual(title, renamed[1])
        self.assertEqual(p.tables[renamed[1]].raw.loc[0, "Y"], 2)

    def test_duplicate_and_delete_keep_layout_slots_and_single_view(self):
        p = self.project
        first = p.candidate("Measurements", "Linear regression", {})
        original = p.candidate("Measurements", "Linear regression", {})
        p.add_result(first, result_graph())
        p.add_result(original, result_graph())
        p.put_layout(Layout("Figures", 1, [original.reference]))
        with self.assertRaisesRegex(ValueError, "layout"):
            p.delete_sheet(("graph", 1), peer_visible=True)
        _, duplicate = p.duplicate_sheet(("result", 1))
        self.assertNotEqual(p.runs[duplicate].uid, original.uid)
        self.assertTrue(p.sheet_state(("graph", duplicate))["hidden"])
        p.delete_sheet(("graph", 0), peer_visible=True)
        self.assertTrue(p.sheet_state(("graph", 0))["hidden"])
        p.delete_sheet(("result", 0))
        self.assertEqual(original.reference, ("Measurements", 0))
        self.assertEqual(p.layouts[0].panels, [original.reference])
        self.assertEqual(p.runs[1].slot, 1)
        copied = p.duplicate_sheet(("data", "Measurements"))
        self.assertEqual(len(p.tables[copied[1]].analyses), 0)
        pd.testing.assert_frame_equal(p.tables["Measurements"].raw, p.tables[copied[1]].raw)

    def test_info_copy_keeps_constants_inactive_until_enabled(self):
        p = self.project
        original = InfoSheet("Calibration", (("Factor", "2"),), notes="Text", table="Measurements")
        p.update_info_sheets({original.uid: original})
        _, uid = p.duplicate_sheet(("info", original.uid))
        copied = p.info_sheets[uid]
        self.assertEqual(copied.fields, original.fields)
        self.assertEqual(copied.notes, original.notes)
        self.assertFalse(copied.use_constants)
        self.assertEqual(p.tables["Measurements"].info["factor"], "2")

    def test_frozen_formula_keeps_the_info_value_across_save(self):
        from dataclasses import replace

        p = self.project
        note = InfoSheet("Calibration", fields=(("Factor", "2"),), table="Measurements")
        p.update_info_sheets({note.uid: note})
        p.set_formula("Measurements", "Adjusted", '=Y * INFO("Factor")')
        target = ("data", "Measurements")
        p.set_sheet_frozen(target, True)
        p.change_info(replace(note, fields=(("Factor", "3"),)))
        path = self.folder / "frozen-formula.alab"
        p.save(path)
        reopened = Project()
        reopened.load(path)
        self.assertEqual(list(reopened.tables["Measurements"].frame()["Adjusted"]), [4, 8, 12])
        reopened.set_sheet_frozen(target, False)
        self.assertEqual(list(reopened.tables["Measurements"].frame()["Adjusted"]), [6, 12, 18])

    def test_note_attachments_follow_their_graph_and_layout_on_family_copy(self):
        from analisi.family_workflow import duplicate_family

        p = self.project
        graph = p.candidate("Measurements", "Linear regression", {})
        p.add_result(graph, result_graph())
        p.put_layout(Layout("Figures", 1, [graph.reference], panel_size="both"))
        notes = [
            InfoSheet("Graph remark", notes="First", floating=True, use_constants=False,
                      worksheet=p.sheet_key(("graph", 0))),
            InfoSheet("Layout remark", notes="Second", floating=True, use_constants=False,
                      worksheet=p.sheet_key(("layout", 0))),
        ]
        p.update_info_sheets({note.uid: note for note in notes})
        p.sync_links(persist=True)
        bundle = duplicate_family(p.tables, p.layouts, p.info_sheets.values(), ("graph", graph.reference),
                                  name="Measurements copy")
        self.assertEqual({note.notes for note in bundle.infos}, {"First", "Second"})
        copied = p.apply_family(bundle)
        graph_note = next(note for note in p.info_sheets.values() if note.notes == "First" and note.uid != notes[0].uid)
        self.assertEqual(graph_note.worksheet, p.sheet_key(copied))
        self.assertEqual(p.layouts[-1].panel_size, "both")
        layout_note = next(note for note in p.info_sheets.values() if note.notes == "Second" and note.uid != notes[1].uid)
        self.assertEqual(layout_note.worksheet, p.sheet_key(("layout", 1)))

    def test_persistent_name_highlight_order_lock_and_cached_output(self):
        p = self.project
        first = p.candidate("Measurements", "Linear regression", {})
        result = result_graph()
        p.add_result(first, result)
        child = p.candidate("Measurements", "Linear regression", {}, source=ResultSource(first.uid, "Report"))
        p.add_result(child, None)
        p.rename_sheet(("result", 0), "Calibrated result $")
        p.rename_sheet(("graph", 0), "Calibrated chart")
        p.highlight_sheet(("graph", 0), "green")
        p.move_sheet(("data", "Other"), [("data", "Measurements"), ("data", "Other")], -1)
        p.set_sheet_frozen(("data", "Other"), True)
        p.set_sheet_frozen(("result", 0), True)
        with self.assertRaisesRegex(ValueError, "frozen"):
            p.edit_cell("Other", 0, 0, "7")
        self.assertFalse(p.plan_refresh([first]).selected)
        self.assertEqual(p.plan_refresh([child]).selected, [child.uid])
        p.edit_cell("Measurements", 0, 1, "7")
        for path in (self.folder / "project.alab", self.folder / "recovery.alab"):
            if path.stem == "project":
                p.save(path)
            else:
                path.write_bytes(p.snapshot().to_bytes())
            reopened = Project()
            reopened.load(path)
            self.assertEqual(reopened.sheet_title(("graph", 0)), "Calibrated chart")
            self.assertEqual(reopened.sheet_title(("result", 0)), "Calibrated result $")
            self.assertEqual(reopened.sheet_state(("graph", 0))["highlight"], "green")
            self.assertEqual(reopened.sheet_state(("data", "Other"))["position"], 0)
            self.assertTrue(reopened.sheet_locked(("data", "Other")))
            self.assertTrue(reopened.sheet_locked(("graph", 0)))
            source = reopened.runs[0]
            pd.testing.assert_frame_equal(source.result.tables["Report"], result.tables["Report"])
            self.assertIsNotNone(source.result.figure._trama_frozen_pdf)
            path = self.folder / "export.pdf"
            export_figure(source.result.figure, path, {"format": "pdf", "width_mm": 80})
            export_pdf_bundle([source.result.figure, source.result.figure], path, {"width_mm": 80})
            import pypdfium2 as pdfium
            with pdfium.PdfDocument(path) as exported:
                self.assertEqual(len(exported), 2)
                page = exported[0]
                try:
                    self.assertIn("Snapshot chart", page.get_textpage().get_text_range())
                finally:
                    page.close()
            affected = reopened.set_sheet_frozen(("result", 0), False)
            self.assertEqual(affected, [source])
            self.assertEqual(reopened.plan_refresh(affected).selected, [source.uid, reopened.runs[1].uid])


@unittest.skipIf(QApplication is None, "PySide6 required")
class NavigatorSheetActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from trama_qt.window import MainWindow

        self.window = MainWindow()
        self.addCleanup(self.close_window)
        self.window.project.add_tables({title: data.raw for title, data in sample_project().tables.items()})
        self.window.show_sheet("data", "Measurements")
        self.window.show()
        self.window.error = lambda error: self.fail(str(error))
        self.app.processEvents()

    def close_window(self):
        self.window.project.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_context_targets_clicked_sheet_before_switching(self):
        w = self.window
        other = next(item for item in w.navigator.findItems("Other", Qt.MatchFlag.MatchRecursive)
                     if item.data(0, Qt.ItemDataRole.UserRole))
        w._navigator_menu(w.navigator.visualItemRect(other).center())
        menu = self.app.activePopupWidget()
        self.assertIsInstance(menu, QMenu)
        self.assertEqual(w.selected, ("data", "Measurements"))
        action = next(action for action in menu.actions() if action.text() == w.actions["sheet_rename"].text())
        with patch.object(QInputDialog, "getText", return_value=("Renamed", True)):
            action.trigger()
        self.assertIn("Renamed", w.project.tables)
        self.assertEqual(w.selected, ("data", "Measurements"))
        menu.close()

    def test_freeze_changes_model_editability_and_note_is_floating(self):
        w = self.window
        w.actions["sheet_freeze"].trigger()
        self.assertTrue(w.sheet.model().read_only)
        self.assertFalse(w.actions["insert_column"].isEnabled())
        w.actions["sheet_freeze"].trigger()
        self.assertFalse(w.sheet.model().read_only)
        w.actions["sheet_notes"].trigger()
        self.app.processEvents()
        notes = w.worksheet_notes
        self.assertTrue(notes.isVisible())
        self.assertTrue(w.sheet.isVisible())
        notes.add_note()
        notes.editor.notes.setPlainText("Stored when leaving the sheet")
        w.show_sheet("data", "Other")
        self.assertIsNone(w.worksheet_notes)
        note, = w.project.info_sheets.values()
        self.assertTrue(note.floating)
        self.assertEqual(note.table, "Measurements")
        self.assertEqual(note.notes, "Stored when leaving the sheet")

    def test_delete_uses_confirmation_and_keeps_other_tab_open(self):
        w = self.window
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            w._worksheet_command(("data", "Other"), "delete")
        self.assertIn("Other", w.project.tables)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            w._worksheet_command(("data", "Other"), "delete")
        self.assertNotIn("Other", w.project.tables)
        self.assertEqual(w.selected, ("data", "Measurements"))


if __name__ == "__main__":
    unittest.main()
