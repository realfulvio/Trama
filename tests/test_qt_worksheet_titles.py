"""The table-format dialog, worksheet position and view zoom use the same column identities."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog
from matplotlib.figure import Figure

from analisi.data import load_project
from analisi.i18n import active_language, set_language
from analisi.xy_series import X_DISTANCE, XY_METHOD, xy_series
from trama_qt.analysis_dialog import AnalysisDialog
from trama_qt.project import Run
from trama_qt.window import MainWindow, Page
from trama_qt.worksheet_titles import TableFormatDialog


class WorksheetTitlesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["table-format", "-platform", "offscreen"])

    def setUp(self):
        language = active_language()
        self.addCleanup(set_language, language)
        set_language("en")
        self.window = MainWindow()
        frame = pd.DataFrame([["First", 0, 2, 3, 6, 7], ["Second", 1, 3, 4, 7, 8]],
                             columns=["Row title", "X", "Control [1]", "Control [2]", "Treated [1]", "Treated [2]"])
        frame.attrs["table_format"] = "XY with replicates"
        self.title, = self.window.project.add_tables({"Time": frame})
        self.dataset = self.window.project.tables[self.title]
        self.window.show_sheet("data", self.title)
        self.window.resize(1100, 768)
        self.window.show()
        self.app.processEvents()
        self.view = self.window.sheet
        self.model = self.view.model()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def fill(self, dialog):
        def enter(view, row, text):
            model = view.model()
            self.assertTrue(model.setData(model.index(row, 0), text))
        enter(dialog.columns, 0, "Morning series")
        enter(dialog.subcolumns, 0, "Reading one")
        dialog.show_rows.setChecked(False)

    def apply(self):
        def accept(dialog):
            self.fill(dialog)
            return QDialog.DialogCode.Accepted
        with patch.object(TableFormatDialog, "exec", accept):
            self.window.actions["format_data_table"].trigger()
        self.app.processEvents()

    def test_menu_apply_undo_reopen_and_formula_keys(self):
        self.assertEqual(self.window.command_menus["Change"].actions()[0], self.window.actions["format_data_table"])
        self.dataset.set_formula("Difference", 'COL("Treated [1]") - COL("Control [1]")')
        before = self.dataset.frame()
        self.apply()
        self.assertTrue(self.view.isColumnHidden(0))
        self.assertEqual(self.model.group_title(3), "Morning series")
        self.assertEqual([self.model.subcolumn_label(c) for c in (2, 3, 4)], ["Reading one", "A:Y2", "Reading one"])
        self.assertEqual(self.model.headerData(3, Qt.Orientation.Horizontal), "Group A\nMorning series\nA:Y2")
        pd.testing.assert_frame_equal(before, self.dataset.frame(), check_flags=False)
        with TemporaryDirectory() as folder:
            filename = Path(folder) / "headings.alab"
            self.window.project.save(filename)
            restored = load_project(filename)[self.title]
            self.assertEqual(restored.worksheet_titles, self.dataset.worksheet_titles)
            self.assertEqual(restored.frame()["Difference"].tolist(), [4, 4])
        self.window.undo()
        self.assertFalse(self.view.isColumnHidden(0))
        self.assertEqual(self.model.group_title(2), "Control")
        self.window.undo(redo=True)
        self.assertEqual(self.model.group_title(2), "Morning series")
        self.assertTrue(self.view.isColumnHidden(0))

    def test_draft_cancel_and_independent_subtitles(self):
        self.apply()
        original = self.dataset.worksheet_titles
        dialog = TableFormatDialog(self.window, self.model, tab=2, column=4)
        self.assertEqual(dialog.tabs.currentIndex(), 2)
        dialog.shared.setChecked(False)
        grid = dialog.subcolumns.model()
        self.assertEqual([r[0] for r in grid.rows], ["A:Y1", "A:Y2", "B:Y1", "B:Y2"])
        self.assertEqual(grid.rows[0][1], "Reading one")
        self.assertEqual(grid.rows[2][1], "")
        grid.setData(grid.index(2, 0), "Evening")
        changed = dialog.settings()
        dialog.reject()
        self.assertEqual(self.dataset.worksheet_titles, original)
        self.window.project.set_worksheet_titles(self.title, changed)
        self.assertEqual(self.model.subcolumn_label(4), "Evening")
        dialog.show_subtitles.setChecked(False)
        self.window.project.set_worksheet_titles(self.title, dialog.settings())
        self.assertEqual(self.model.subcolumn_label(4), "B:Y1")
        dialog.deleteLater()

    def test_plot_titles_keep_recipe_columns_and_values(self):
        opt = {"X": "X", "Y columns": ["Control [1]", "Treated [2]"]}
        original = xy_series(self.dataset.frame(), opt)
        self.apply()
        after = xy_series(self.dataset.frame(), opt)
        axes = after.figure.axes[0]
        self.assertEqual([t.get_text() for t in axes.get_legend().get_texts()], ["Morning series [1]", "Treated [2]"])
        pd.testing.assert_frame_equal(original.tables["Series values"], after.tables["Series values"])

    def test_active_section_cell_and_zoom(self):
        self.apply()
        self.view.setCurrentIndex(self.model.index(1, 3))
        self.assertEqual(self.window.cell_label.text(), "Row 2 · A:Y2 · Morning series")
        self.view.select_block(0, 2, 1, 3, current_row=1, current_col=3)
        self.assertIn("Selection 2 × 2", self.window.cell_label.text())
        self.assertTrue(self.window.section_buttons["data"].isChecked())
        self.assertEqual(self.window.sheet_picker.toolTip(), "Time")
        self.assertTrue(self.window.zoom_bar.isVisible())
        self.window.zoom_slider.setValue(self.window.zoom_slider.value() + 1)
        self.assertEqual(self.window.table_zoom, 110)
        self.window.zoom_percent.click()
        self.assertEqual(self.window.table_zoom, 100)
        self.window.resize(800, 600)
        self.app.processEvents()
        self.assertEqual(self.window.section_buttons["data"].toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)

    def test_graph_zoom_preserves_axes_and_page_size(self):
        fig = Figure()
        ax = fig.add_subplot()
        ax.plot([0, 1], [2, 8])
        page = Page("")
        self.addCleanup(page.close)
        canvas = self.window._canvas(page, fig)
        page.resize(700, 400)
        page.show()
        self.app.processEvents()
        width = canvas.width()
        size = fig.get_size_inches().copy()
        limits = ax.get_xlim(), ax.get_ylim()
        page.figure_view.set_percent(150)
        self.app.processEvents()
        self.assertGreater(canvas.width(), 1.4 * width)
        self.assertGreater(page.figure_view.horizontalScrollBar().maximum(), 0)
        self.assertEqual(limits, (ax.get_xlim(), ax.get_ylim()))
        for expected, actual in zip(size, fig.get_size_inches(), strict=True):
            self.assertAlmostEqual(expected, actual, delta=.015)
        page.figure_view.set_percent(100)
        self.app.processEvents()
        self.assertEqual(canvas.width(), width)

    def change_replicates(self, count, *, blocked=False):
        result = []
        def check_dialog():
            dialog = self.app.activeModalWidget()
            try:
                self.assertIsInstance(dialog, TableFormatDialog)
                dialog.replicate_count.setValue(count)
                dialog.accept()
                if blocked:
                    self.assertTrue(dialog.isVisible())
                    self.assertIn("contains data", dialog.problem.text())
                    dialog.reject()
                result.append(True)
            except Exception as error:
                result.append(error)
                dialog.reject()
        QTimer.singleShot(0, check_dialog)
        self.window.actions["format_data_table"].trigger()
        self.assertEqual(result, [True])
        self.app.processEvents()

    def test_resize_replicates_preserves_coordinates_formulas_and_history(self):
        self.apply()
        self.dataset.set_formula("Difference", 'COL("Treated [1]") - COL("Control [1]")')
        self.view.model().reload()
        self.dataset.excluded = {(1, 4)}
        original = self.dataset.frame()
        old_ids = original.attrs["column_ids"]
        self.view.setCurrentIndex(self.model.index(0, 4))
        self.change_replicates(4)
        after = self.dataset.frame()
        self.assertEqual(after.columns.tolist(), [
            "Row title", "X", "Control [1]", "Control [2]", "Control [3]", "Control [4]",
            "Treated [1]", "Treated [2]", "Treated [3]", "Treated [4]", "Difference"])
        pd.testing.assert_frame_equal(original, after.loc[:, original.columns], check_flags=False)
        self.assertEqual(self.dataset.excluded, {(1, 6)})
        self.assertEqual(self.view.currentIndex().column(), 6)
        self.assertTrue(after[["Control [3]", "Control [4]", "Treated [3]", "Treated [4]"]].isna().all().all())
        self.assertEqual({name: after.attrs["column_ids"][name] for name in old_ids}, old_ids)
        with TemporaryDirectory() as folder:
            filename = Path(folder) / "replicates.alab"
            self.window.project.save(filename)
            loaded = load_project(filename)[self.title]
            self.assertEqual(loaded.columns, self.dataset.columns)
            self.assertEqual(loaded.worksheet_titles, self.dataset.worksheet_titles)
            self.assertEqual(self.window.project.worksheet_replicate_limits(self.title)[0], 4)
        self.window.undo()
        self.assertEqual(self.dataset.columns, tuple(original.columns))
        self.window.undo(redo=True)
        self.assertEqual(self.dataset.columns, tuple(after.columns))
        self.change_replicates(2)
        self.assertEqual(self.dataset.columns, tuple(original.columns))
        self.assertEqual(self.dataset.excluded, {(1, 4)})

    def test_horizontal_error_and_replicate_change_share_one_history_entry(self):
        def toggle():
            dialog = self.app.activeModalWidget()
            self.assertFalse(dialog.x_error.isChecked())
            dialog.x_error.setChecked(True)
            dialog.replicate_count.setValue(3)
            self.assertEqual(dialog.preview.horizontalHeaderItem(2).text(), "X\nError bar")
            dialog.accept()

        self.dataset.excluded = {(1, 4)}
        QTimer.singleShot(0, toggle)
        self.window.actions["format_data_table"].trigger()
        self.assertEqual(self.dataset.raw.columns.tolist(), [
            "Row title", "X", "X [Error]", "Control [1]", "Control [2]", "Control [3]",
            "Treated [1]", "Treated [2]", "Treated [3]"])
        self.assertEqual(self.dataset.excluded, {(1, 6)})
        self.assertEqual(self.model.default_subcolumn_label(2), "Error bar")
        with TemporaryDirectory() as folder:
            filename = Path(folder) / "x-error.alab"
            self.window.project.save(filename)
            loaded = load_project(filename)[self.title]
            self.assertEqual(loaded.raw.attrs["worksheet_roles"]["x"], ["X", "X [Error]"])
            frame = loaded.frame()
            fresh = AnalysisDialog(self.window, frame, current=(XY_METHOD, {}))
            self.assertEqual(fresh.options()[X_DISTANCE], "X [Error]")
            self.assertNotIn("X [Error]", fresh.options()["Y columns"])
            old = AnalysisDialog(self.window, frame, current=(XY_METHOD, {"X": "X", "Y columns": ["Control [1]"]}))
            self.assertFalse(old.options().get(X_DISTANCE))
            fresh.deleteLater()
            old.deleteLater()
        project = self.window.project
        self.window.undo()
        self.assertEqual(len(self.dataset.columns), 6)
        self.assertEqual(self.dataset.excluded, {(1, 4)})
        self.window.undo(redo=True)
        project.rename_column(self.title, 2, "Uncertainty")
        self.assertEqual(project.worksheet_x_error(self.title), ("X", "Uncertainty"))
        project.edit_cell(self.title, 0, 2, "0.5")
        with self.assertRaisesRegex(ValueError, "contains data"):
            project.set_worksheet_xy_structure(self.title, None, self.dataset.worksheet_titles, x_error=False)
        self.assertEqual(self.dataset.raw["Uncertainty"].iat[0], 0.5)
        project.edit_cell(self.title, 0, 2, "")
        project.set_worksheet_xy_structure(self.title, None, self.dataset.worksheet_titles, x_error=False)
        self.assertEqual(project.worksheet_x_error(self.title), ("X", None))
        self.assertEqual(project.worksheet_replicate_limits(self.title)[0], 3)

    def test_reduce_keeps_data_and_references(self):
        self.change_replicates(3)
        project = self.window.project
        name = "Control [3]"
        project.edit_cell(self.title, 0, self.dataset.columns.index(name), "0")
        self.window.reshow()
        self.change_replicates(2, blocked=True)
        self.assertEqual(self.dataset.raw[name].iat[0], 0)
        project.edit_cell(self.title, 0, self.dataset.columns.index(name), "")
        project.runs.append(Run("Linear regression", self.title, {"X": "X", "Y": name}))
        with self.assertRaisesRegex(ValueError, "Control"):
            project.set_worksheet_xy_structure(self.title, 2, self.dataset.worksheet_titles)
        self.assertIn(name, self.dataset.columns)
