"""Reshape long and wide in the Qt window, offscreen: the editor, preview, errors, worker, chain, export, reopen.

Skipped when PySide6 (or the Qt platform libraries) are not installed.
"""
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np
import pandas as pd

from analisi.i18n import active_language, set_language

DATA = Path(__file__).resolve().parent / "data" / "reshape_long_wide"
METHOD = "Reshape long and wide"
WIDEN = {"Direction": "Long to wide", "ID columns": ["Sample $", "Rep"], "Name column": "Visit",
         "Value column": "Measure"}


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ReshapeEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.addCleanup(set_language, active_language())
        self.long = pd.read_csv(DATA / "long.csv", dtype={"Sample $": str})

    def dialog(self, frame=None, current=None, **kwargs):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, self.long if frame is None else frame, current=(METHOD, current or {}),
                                **kwargs)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_new_dialog_proposes_a_runnable_recipe_in_order(self):
        dialog = self.dialog()
        editor = dialog.reshape
        self.assertIsNotNone(editor)
        self.assertEqual(dialog.controls, {})  # no generic fields: the editor owns the page
        editor.ids.set_values(["Sample $", "Rep"])
        self.assertEqual(dialog.options(), WIDEN)
        editor.ids.list.setCurrentRow(1)
        editor.ids.move(-1)
        self.assertEqual(dialog.options()["ID columns"], ["Rep", "Sample $"])
        self.assertFalse(editor.ids.up.isEnabled())
        self.assertEqual([dialog.tabs.tabText(index) for index in range(dialog.tabs.count())], ["Variables", "Preview"])

    def test_switching_direction_keeps_both_sets_of_choices(self):
        wide = pd.read_csv(DATA / "wide.csv", dtype={"Sample $": str})
        dialog = self.dialog(wide)
        editor = dialog.reshape
        editor.ids.set_values(["Sample $", "Rep"])
        editor.direction.setCurrentIndex(editor.direction.findData("Wide to long"))
        editor.measures.set_values(["Fine à", "A | Start"])
        editor.names.setText("Visit $")
        editor.drop.setChecked(True)
        editor.direction.setCurrentIndex(editor.direction.findData("Long to wide"))
        editor.name.setCurrentIndex(editor.name.findData("A | Start"))
        self.assertEqual(set(dialog.options()), {"Direction", "ID columns", "Name column", "Value column"})
        self.assertFalse(editor.drop.isVisibleTo(dialog))
        editor.direction.setCurrentIndex(editor.direction.findData("Wide to long"))
        self.assertEqual(dialog.options(), {"Direction": "Wide to long", "ID columns": ["Sample $", "Rep"],
                                            "Measure columns": ["Fine à", "A | Start"], "Output names": "Visit $",
                                            "Output values": "Value", "Drop missing values": True})
        editor.direction.setCurrentIndex(editor.direction.findData("Long to wide"))
        self.assertEqual(dialog.options()["Name column"], "A | Start")

    def test_a_column_has_one_role(self):
        wide = pd.read_csv(DATA / "wide.csv", dtype={"Sample $": str})
        dialog = self.dialog(wide, {"Direction": "Wide to long", "ID columns": ["Sample $"],
                                    "Measure columns": ["Rep", "A | Start", "Fine à"]})
        editor = dialog.reshape
        rep = editor.ids.list.findItems("Rep", Qt.MatchFlag.MatchExactly)[0]
        rep.setCheckState(Qt.CheckState.Checked)  # as a click does
        self.assertEqual(dialog.options()["ID columns"], ["Sample $", "Rep"])
        self.assertEqual(dialog.options()["Measure columns"], ["A | Start", "Fine à"])
        editor.refresh_preview()
        self.assertFalse(editor.preview_error.isVisible())

    def test_saved_recipe_reopens_as_saved(self):
        recipe = {"Direction": "Wide to long", "ID columns": ["Rep", "Sample $"], "Measure columns": ["Fine à"],
                  "Output names": "Visit", "Output values": "Measure", "Drop missing values": True}
        wide = pd.read_csv(DATA / "wide.csv", dtype={"Sample $": str})
        dialog = self.dialog(wide, recipe)
        self.assertEqual(dialog.options(), recipe)
        dialog.show()
        self.app.processEvents()
        ids = dialog.reshape.ids.list  # rows reordered before the first show are laid out with the style
        rows = [ids.visualItemRect(ids.item(row)) for row in range(ids.count())]
        self.assertEqual(len({rect.height() for rect in rows}), 1)
        self.assertTrue(all(upper.bottom() < lower.top() for upper, lower in zip(rows, rows[1:])))
        self.assertGreaterEqual(rows[0].height(), ids.fontMetrics().height() + 4)

    def test_preview_shows_size_head_and_hidden_parts(self):
        frame = pd.DataFrame({"id": np.repeat(np.arange(40), 20), "lev": np.tile([f"L {n}" for n in range(20)], 40),
                              "v": np.arange(800.)})
        dialog = self.dialog(frame, {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev",
                                     "Value column": "v"})
        editor = dialog.reshape
        shown = editor.refresh_preview()
        self.assertEqual((editor.table.rowCount(), editor.table.columnCount()), (25, 12))
        self.assertEqual(editor.table.horizontalHeaderItem(1).text(), "L 0")
        self.assertEqual(editor.table.item(0, 1).text(), "0")
        self.assertEqual(shown.hidden_rows, 15)
        self.assertEqual(editor.preview_summary.text(),
                         "Result: 40 rows and 21 columns. Mapped cells: 800. Blank cells: 0.")
        self.assertEqual(editor.hidden_note.text(), "15 more rows are not shown. 9 more columns are not shown.")

    def test_italian_captions_and_messages(self):
        set_language("it")
        dialog = self.dialog(current=dict(WIDEN, **{"ID columns": ["Sample $"]}))
        editor = dialog.reshape
        self.assertEqual(dialog.heading.text(), "Rimodella lungo e largo")
        self.assertEqual(editor.direction.currentText(), "Da lungo a largo")
        self.assertEqual(editor.preview_error.text(),
                         'Non si può ancora eseguire: Le righe 1 e 3 hanno lo stesso ID e lo stesso livello '
                         '"A | Start". Aggiungi una colonna ID che le distingua, oppure togli una delle due righe.')
        editor.ids.set_values(["Sample $", "Rep"])
        editor.refresh_preview()
        self.assertEqual(editor.preview_summary.text(),
                         "Risultato: 4 righe e 4 colonne. Celle mappate: 8. Celle vuote: 1.")
        self.assertEqual(editor.hidden_note.text(), "L'anteprima mostra tutto il risultato.")

    def test_error_keeps_the_recipe_and_focuses_the_field(self):
        dialog = self.dialog(current=dict(WIDEN, **{"ID columns": ["Sample $"]}))
        dialog.show()
        self.app.processEvents()
        dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.isVisible())
        self.assertTrue(dialog.banner.text().startswith('Rows 1 and 3 have the same ID and level "A | Start".'))
        self.assertTrue(dialog.reshape.ids.list.hasFocus())
        self.assertEqual(dialog.options()["Name column"], "Visit")  # nothing was lost
        dialog.reshape.ids.set_values(["Sample $", "Rep"])
        self.assertTrue(dialog.reshape.timer.isActive())  # the debounced preview of the edit
        QTest.qWait(400)
        self.assertFalse(dialog.banner.isVisible())  # a fixed recipe clears the stale error
        dialog.accept()
        self.assertEqual(dialog.result, (METHOD, WIDEN))

    def test_engine_error_reopens_on_the_field(self):
        dialog = self.dialog(current=WIDEN, error='Column "Visit" is not in the table.', error_field="Name column")
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.banner.isVisible())
        self.assertTrue(dialog.reshape.name.hasFocus())


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class ReshapeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = MainWindow()
        self.window.project.dirty = False
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.window.error = lambda error: self.fail(f"error shown: {error}")
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def open_long(self):
        path = self.folder / "visite lunghe.csv"
        path.write_bytes((DATA / "long.csv").read_bytes())
        self.window.open_path(path)
        self.app.processEvents()
        return "visite lunghe"

    def calculate(self, title, method, options, source=None, frame=None):
        project = self.window.project
        frame = project.tables[title].frame(mask_excluded=True) if frame is None else frame
        candidate = project.candidate(title, method, options, source=source)
        self.window.calculate_candidate(candidate, frame, None)
        self.wait()
        run = project.runs[-1]
        self.assertIsNone(run.calculation_error)
        return len(project.runs) - 1

    def test_run_export_chain_save_and_reopen(self):
        from analisi.analysis_chain import ResultSource, result_frame
        window = self.window
        title = self.open_long()
        index = self.calculate(title, METHOD, WIDEN)
        run = window.project.runs[index]
        self.assertEqual(list(run.result.tables), ["Reshaped data", "Source map", "Settings"])
        self.assertEqual(window.project.tables[title].analyses[-1], (METHOD, WIDEN))

        # Export the open result table to CSV.
        window.open_sheet(("result", index))
        target = self.folder / "largo.csv"
        with mock.patch("trama_qt.window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            window.export()
        written = pd.read_csv(target, encoding="utf-8-sig", index_col=0, dtype={"Sample $": str})
        self.assertEqual(list(written.columns), ["Sample $", "Rep", "A | Start", "Fine à"])
        self.assertEqual(written["Sample $"].tolist(), ["001", "001", "002", "002"])

        # A live chain: descriptive statistics of the reshaped table, recalculated when a source cell changes.
        source = ResultSource(run.uid, "Reshaped data")
        chained = self.calculate(title, "Descriptive statistics", {"Variables": ["A | Start", "Fine à"]},
                                 source=source, frame=result_frame(run.result, "Reshaped data"))
        summary = window.project.runs[chained].result.tables["Summary"]
        self.assertAlmostEqual(float(summary.loc["A | Start", "Mean"]), (5 + 0 + 8 + 9) / 4)
        measure = list(window.project.tables[title].raw.columns).index("Measure")
        affected = window.project.paste(title, 0, measure, [["13"]])
        window.refresh_runs(affected)
        self.wait()
        summary = window.project.runs[chained].result.tables["Summary"]
        self.assertAlmostEqual(float(summary.loc["A | Start", "Mean"]), (13 + 0 + 8 + 9) / 4)

        # Save, reopen: the recipe, the link and the results come back.
        saved = self.folder / "rimodella.alab"
        window.project.save(saved)
        self.assertTrue(window.close_project())
        window.open_path(saved)
        self.app.processEvents()
        runs = window.project.runs
        reshaped = next(item for item in runs if item.method == METHOD)
        window.open_sheet(("result", runs.index(reshaped)))  # a reopened result is calculated when shown
        self.wait()
        self.assertEqual(reshaped.options, WIDEN)
        linked = next(item for item in runs if item.method == "Descriptive statistics")
        self.assertEqual(linked.source, ResultSource(reshaped.uid, "Reshaped data"))
        self.assertIsNotNone(reshaped.result)
        self.assertEqual(reshaped.result.tables["Reshaped data"]["A | Start"].tolist(), [13, 0, 8, 9])
        window.open_sheet(("result", runs.index(linked)))
        self.wait()
        self.assertAlmostEqual(float(linked.result.tables["Summary"].loc["A | Start", "Mean"]), 7.5)

        # Use Result as Data: an ordinary editable worksheet with the literal names and the "001" keys.
        window.open_sheet(("result", runs.index(reshaped)))
        new = window.project.use_result_as_data(reshaped, "Reshaped data")
        table = window.project.tables[new].raw
        self.assertEqual(list(table.columns), ["Sample $", "Rep", "A | Start", "Fine à"])
        self.assertEqual(table["Sample $"].tolist(), ["001", "001", "002", "002"])

    def test_cancel_keeps_the_previous_state(self):
        window = self.window
        title = self.open_long()
        project = window.project
        candidate = project.candidate(title, METHOD, WIDEN)
        frame = project.tables[title].frame(mask_excluded=True)
        window.calculate_candidate(candidate, frame, None)
        window.cancel_calculation()  # the poll sees the cancel: nothing is confirmed, even if the worker finished
        self.wait()
        self.assertEqual(project.runs, [])
        self.assertEqual(project.tables[title].analyses, [])


if __name__ == "__main__":
    unittest.main()
