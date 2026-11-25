"""Linked tables in the Qt window: the commands, the dialogs, the one-step undo and the three sheets that show them."""
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi import linked_tables as lt
from analisi.i18n import active_language, set_language, tr
from tests.test_linked_tables import calculate, cells, put_on_graph, slope_record, written


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class QtLinkedTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.addCleanup(set_language, active_language())
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
        self.window.resize(1180, 768)
        self.window.show()
        self.addCleanup(self._close)
        self.window.open_path(written(self.folder))
        self.app.processEvents()
        self.project = self.window.project
        calculate(self.project)

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def show(self, kind, key=0):
        self.window.show_sheet(kind, key)
        self.app.processEvents()

    def texts(self, figure):
        return [child.get_text() for artist in figure.artists if isinstance(artist, lt.LinkedTableArtist)
                for child in artist._children if hasattr(child, "get_text") and child.get_text()]

    def table_ids(self, kind, key=0):
        records = ((self.project.runs[key].style or {}).get(lt.TABLES, []) if kind == "graph"
                   else self.project.layouts[key].tables)
        return [record["id"] for record in records]

    def select_cells(self, top, left, bottom, right, view=None):
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        view = view or self.window.sheet
        model = view.model()
        view.setCurrentIndex(model.index(top, left))
        view.selectionModel().select(QItemSelection(model.index(top, left), model.index(bottom, right)),
                                     QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.app.processEvents()

    # -- the commands -------------------------------------------------------------------------------
    def test_the_commands_follow_the_page_and_are_in_the_insert_menu_in_both_languages(self):
        window = self.window
        self.assertEqual(window.selected, ("data", "Misure"))
        self.assertFalse(window.actions["linked_table"].isEnabled())    # a worksheet holds no drawing
        self.select_cells(0, 0, 1, 1)
        self.assertTrue(window.actions["linked_table_selection"].isEnabled())
        self.show("graph")
        self.assertTrue(window.actions["linked_table"].isEnabled())
        self.assertFalse(window.actions["linked_table_selection"].isEnabled())  # nothing selected to copy
        self.show("layout")
        self.assertTrue(window.actions["linked_table"].isEnabled())
        listed = [action.text() for action in window.command_menus["Insert"].actions()]
        self.assertIn("Linked table…", listed)
        self.assertIn("Linked table from selection…", listed)
        self.assertEqual(tr("command.linked_table"), "Linked table…")
        set_language("it")
        self.assertEqual(tr("command.linked_table"), "Tabella collegata…")
        self.assertEqual(tr("command.linked_table_selection"), "Tabella collegata dalla selezione…")
        self.assertEqual(tr("linked_table.state.missing"), "Origine non disponibile")

    def test_a_worksheet_page_refuses_the_drawing_command_politely(self):
        self.window.show_sheet("data", "Misure")
        self.window.edit_linked_tables()
        self.assertEqual(self.errors, [tr("linked_table.native")])

    # -- the dialog ------------------------------------------------------------------------------------
    def big_project(self):
        frame = pd.DataFrame({"A": range(100), "B": [x * 2 for x in range(100)], "C": [x * 3 for x in range(100)]})
        title, = self.project.add_tables({"Grande": frame})
        return title

    def make_dialog(self, **options):
        from trama_qt.linked_tables import LinkedTableDialog
        dialog = LinkedTableDialog(self.window, self.project, **options)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_the_dialog_previews_the_range_and_refuses_a_rectangle_over_the_limit_before_reading_it(self):
        title = self.big_project()
        dialog = self.make_dialog()
        dialog.source.setCurrentIndex(next(i for i, c in enumerate(dialog.choices)
                                           if c["kind"] == "sheet" and c["sheet"] == title))
        ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        # The preview of the source stops at the preview limit, whatever the size of the sheet.
        self.assertLessEqual(dialog.picker.rowCount(), 200)
        dialog.last_row.setValue(3)
        dialog.last_column.setValue(2)
        self.assertTrue(ok.isEnabled())
        self.assertFalse(dialog.shown.pixmap().isNull())
        self.assertIn("3 × 2", dialog.range_size.text())
        with patch.object(dialog.project, "table_record", side_effect=AssertionError("a cell was read")):
            dialog.last_row.setValue(100)       # 100 rows: over the 60-row limit
            self.assertFalse(ok.isEnabled())
            self.assertTrue(dialog.problem.isVisible())
            self.assertIn("60", dialog.problem.text())
            with self.assertRaises(ValueError):
                dialog.build()
            dialog.accept()                     # refused too, with the reason, not accepted
            self.assertIsNone(dialog.result)
        dialog.last_row.setValue(5)
        self.assertTrue(ok.isEnabled())
        self.assertFalse(dialog.problem.isVisible())

    def test_a_dragged_rectangle_and_the_typed_one_are_the_same_range(self):
        from PySide6.QtWidgets import QTableWidgetSelectionRange
        title = self.big_project()
        dialog = self.make_dialog()
        dialog.source.setCurrentIndex(next(i for i, c in enumerate(dialog.choices)
                                           if c["kind"] == "sheet" and c["sheet"] == title))
        dialog.picker.clearSelection()
        dialog.picker.setRangeSelected(QTableWidgetSelectionRange(2, 1, 4, 2), True)
        self.assertEqual(dialog._box(), (2, 1, 4, 2))
        self.assertEqual((dialog.first_row.value(), dialog.last_row.value(),
                          dialog.first_column.value(), dialog.last_column.value()), (3, 5, 2, 3))
        dialog.first_row.setValue(1)
        self.assertEqual(dialog._box(), (0, 1, 4, 2))
        self.assertEqual({(r.topRow(), r.leftColumn(), r.bottomRow(), r.rightColumn())
                          for r in dialog.picker.selectedRanges()}, {(0, 1, 4, 2)})
        record = dialog.build()
        self.assertEqual(record["source"]["sheet"], title)
        self.assertEqual(len(record["source"]["rows"]), 5)

    def test_one_cell_linked_or_copy_and_the_look_options_reach_the_record(self):
        dialog = self.make_dialog()
        dialog.source.setCurrentIndex(next(i for i, c in enumerate(dialog.choices) if c["kind"] == "sheet"))
        dialog.copy.setChecked(True)
        dialog.headers.setCurrentIndex(dialog.headers.findData("none"))
        dialog.orientation.setCurrentIndex(dialog.orientation.findData("transposed"))
        dialog.font.setCurrentIndex(dialog.font.findData("serif"))
        dialog.size.setValue(12.5)
        dialog.grid.setChecked(False)
        dialog.x.setValue(40)
        dialog.y.setValue(60)
        dialog.accept()
        record = dialog.result
        self.assertEqual((record["mode"], record["headers"], record["orientation"], record["font"], record["size"],
                          record["grid"], record["position"]),
                         ("copy", "none", "transposed", "serif", 12.5, False, [.4, .6]))
        self.assertEqual(len(record["values"]["cells"]), 1)           # one cell is a table
        self.assertEqual(len(record["values"]["cells"][0]), 1)
        self.assertNotIn("source", record)

    def test_editing_keeps_the_source_unless_it_is_chosen_again_and_a_missing_source_can_be_moved(self):
        title = self.big_project()
        choice = next(c for c in self.project.table_source_choices() if c["kind"] == "sheet" and c["sheet"] == title)
        record = self.project.table_record(choice, (0, 0, 1, 1), mode="linked")
        keep = self.make_dialog(record=record)
        self.assertTrue(keep.keeping)
        self.assertFalse(keep.range_box.isEnabled())
        self.assertFalse(keep.kept.isHidden())
        self.assertIn(record["origin"], keep.kept.text())
        keep.x.setValue(70)
        moved = keep.build()
        self.assertEqual(moved["source"], record["source"])
        self.assertEqual(moved["id"], record["id"])
        self.assertEqual(moved["position"], [.7, record["position"][1]])
        keep.replace.setChecked(True)
        self.assertTrue(keep.range_box.isEnabled())
        self.assertFalse(keep.keeping)
        # The sheet is gone: the table is a state, and its window still opens to be moved or to be given a new source.
        put_on_graph(self.project, record)
        self.project.delete_sheet(("data", title))
        self.assertEqual([(m, s) for _, m, s, _ in cells(self.project)], [("linked", "missing")])
        gone = self.make_dialog(record=record)
        self.assertTrue(gone.keeping)
        gone.y.setValue(10)
        self.assertEqual(gone.build()["position"][1], .1)
        self.assertTrue(gone.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())

    def test_a_dialog_without_any_source_says_so(self):
        from trama_qt.linked_tables import LinkedTableDialog
        empty = type("Empty", (), {"table_source_choices": lambda self: [],
                                   "table_source_preview": lambda self, *a: ([], [], []),
                                   "table_specs": lambda self, records: []})()
        dialog = LinkedTableDialog(self.window, empty)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.problem.text(), tr("linked_table.no_source"))
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())

    # -- the window glue ---------------------------------------------------------------------------------
    def test_committing_tables_is_one_undo_step_on_a_graph_and_on_a_layout(self):
        window = self.window
        record = slope_record(self.project)
        copy = slope_record(self.project, mode="copy", position=(.5, .5))
        self.show("graph")
        window.commit_linked_tables(("graph", 0), [record, copy])
        self.assertEqual(self.errors, [])
        self.assertEqual(self.texts(self.project.runs[0].result.figure), ["2", "2"])
        self.assertEqual(self.table_ids("graph"), [record["id"], copy["id"]])
        window.undo()
        self.assertEqual(self.table_ids("graph"), [])
        self.assertEqual(self.texts(self.project.runs[0].result.figure), [])
        window.undo(redo=True)
        self.assertEqual(self.table_ids("graph"), [record["id"], copy["id"]])
        self.assertEqual(self.texts(self.project.runs[0].result.figure), ["2", "2"])
        self.show("layout")
        window.commit_linked_tables(("layout", 0), [record])
        self.assertEqual(self.table_ids("layout"), [record["id"]])
        window.undo()
        self.assertEqual(self.table_ids("layout"), [])
        window.undo(redo=True)
        self.assertEqual(self.table_ids("layout"), [record["id"]])
        window.commit_linked_tables(("layout", 0), [])
        self.assertEqual(self.table_ids("layout"), [])
        self.assertEqual(self.errors, [])

    def test_the_table_dialog_of_a_graph_adds_edits_and_removes_through_apply(self):
        from trama_qt.linked_tables import LinkedTablesDialog
        window = self.window
        record = slope_record(self.project)
        self.show("graph")
        outcomes = []

        def run(dialog):
            outcomes.append([r["id"] for r in dialog.records])
            dialog.records.append(record)
            dialog.fill(0)
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with patch.object(LinkedTablesDialog, "exec", run):
            window.edit_linked_tables()
        self.assertEqual(outcomes, [[]])
        self.assertEqual(self.table_ids("graph"), [record["id"]])
        self.assertIn(tr("linked_table.applied"), window.message.text())

        def removing(dialog):
            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertEqual(dialog.table.item(0, 3).text(), tr("linked_table.state_ok"))
            dialog.table.selectRow(0)
            dialog.remove()
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with patch.object(LinkedTablesDialog, "exec", removing):
            window.edit_linked_tables()
        self.assertEqual(self.table_ids("graph"), [])
        window.undo()
        self.assertEqual(self.table_ids("graph"), [record["id"]])

    def test_a_frozen_graph_is_not_offered_and_says_why(self):
        window = self.window
        self.assertEqual([ref for _, ref in window.linked_table_targets()], [("graph", 0), ("layout", 0)])
        self.project.set_sheet_frozen(("graph", 0), True)
        self.assertEqual([ref for _, ref in window.linked_table_targets()], [("layout", 0)])
        self.show("graph")
        window.edit_linked_tables()
        self.assertEqual(self.errors, [self.project.graph_format_problem(self.project.runs[0])])

    def test_the_selection_command_places_the_selected_cells_on_a_graph_or_a_layout(self):
        from trama_qt.linked_tables import LinkedTableDialog
        window = self.window
        window.show_sheet("data", "Misure")
        self.select_cells(1, 1, 2, 1)          # Risposta, rows 2 and 3: 3 and 5
        seen = []

        def run(dialog):
            seen.append((dialog.choices[dialog.source.currentIndex()]["label"], dialog._box(),
                         [dialog.place.itemText(i) for i in range(dialog.place.count())]))
            dialog.choose_target(("layout", 0))
            dialog.copy.setChecked(True)
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with patch.object(LinkedTableDialog, "exec", run):
            window.insert_linked_table_from_selection()
        self.assertEqual(self.errors, [])
        self.assertEqual(seen[0][:2], ("Misure", (1, 1, 2, 1)))
        self.assertEqual(len(seen[0][2]), 2)
        self.assertTrue(seen[0][2][0].startswith("Graph: ") and seen[0][2][1] == "Layout: Risultati in figura")
        record, = self.project.layouts[0].tables
        self.assertEqual(record["mode"], "copy")
        self.assertEqual(record["values"]["cells"], [["3"], ["5"]])
        self.assertEqual(window.selected, ("layout", 0))
        window.undo()
        self.assertEqual(self.table_ids("layout"), [])

    def test_a_result_selection_is_a_result_source_and_never_includes_the_row_titles_column(self):
        from trama_qt.linked_tables import LinkedTableDialog
        window = self.window
        window.open_sheet(("result", 0))
        self.app.processEvents()
        tabs = window.result_tabs
        names = [tabs.tabText(index) for index in range(tabs.count())]
        tabs.setCurrentIndex(names.index("Regression"))
        view = tabs.currentWidget()
        model = view.model()
        row = [model.data(model.index(r, 0)) for r in range(model.rowCount())].index("Slope")
        self.select_cells(row, 0, row, 0, view=view)    # the titles column only
        window.insert_linked_table_from_selection()
        self.assertEqual(self.errors, [tr("linked_table.row_titles")])
        self.errors.clear()
        self.select_cells(row, 1, row, 1, view=view)
        seen = []

        def run(dialog):
            seen.append(dialog.choices[dialog.source.currentIndex()])
            dialog.choose_target(("layout", 0))
            dialog.accept()
            return QDialog.DialogCode.Accepted

        with patch.object(LinkedTableDialog, "exec", run):
            window.insert_linked_table_from_selection()
        self.assertEqual(self.errors, [])
        self.assertEqual((seen[0]["kind"], seen[0]["table"], seen[0]["analysis"]),
                         ("result", "Regression", self.project.runs[0].uid))
        record, = self.project.layouts[0].tables
        self.assertEqual(record["source"]["rows"], ["Slope"])        # by key, not by position
        self.assertEqual(record["source"]["analysis"], self.project.runs[0].uid)
        self.assertEqual(self.project.linked_table_report()[0][2].cells, (("2",),))


if __name__ == "__main__":
    unittest.main()
