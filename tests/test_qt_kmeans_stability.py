"""K-means stability in the Qt window, offscreen: dialog, checks before the worker, recalculation, cancel, projects.

Skipped when PySide6 (or the Qt platform libraries) are not installed.
"""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
import zipfile

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np
import pandas as pd

from analisi import kmeans_stability as ks
from analisi.field_error import FieldError
from analisi.i18n import set_language, translate_message

DATA = Path(__file__).resolve().parent / "data" / "kmeans_stability"
TITLE = "Tre gruppi $ sintetici"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def tick(dialog, name, values):
    control = dialog.controls[name][1]
    for row in range(control.count()):
        item = control.item(row)
        item.setCheckState(Qt.CheckState.Checked if item.text() in values else Qt.CheckState.Unchecked)


def fill(dialog, **values):
    for name, value in values.items():
        kind, control = dialog.controls[name]
        if isinstance(value, bool):
            control.setChecked(value)
        elif isinstance(value, list):
            tick(dialog, name, value)
        elif hasattr(control, "findData"):
            control.setCurrentIndex(control.findData(value))
        else:
            control.setText(str(value))


SMALL = {"Maximum k": 3, "Resamples": 8, "Seed": 33, "Report k": 3, "Show co-assignment matrix": True}


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class StabilityDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def dialog(self, frame=None, current=None):
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = pd.read_csv(DATA / "separated.csv") if frame is None else frame
        dialog = AnalysisDialog(None, frame, current=current or (ks.METHOD, {}))
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def listed(self, dialog, query):
        dialog.query.setText(query)
        return [dialog.methods.topLevelItem(group).child(row).data(0, Qt.ItemDataRole.UserRole)
                for group in range(dialog.methods.topLevelItemCount())
                for row in range(dialog.methods.topLevelItem(group).childCount())]

    def test_catalog_search_and_captions(self):
        dialog = self.dialog()
        self.assertEqual(dialog.method, ks.METHOD)
        self.assertEqual(self.listed(dialog, "stabil"), [ks.METHOD])
        self.assertIn(ks.METHOD, self.listed(dialog, "Clustering"))
        set_language("it")
        dialog = self.dialog()
        self.assertEqual(dialog.heading.text(), "Stabilità K-means")
        self.assertEqual(self.listed(dialog, "Stabilità"), [ks.METHOD])
        captions = {dialog.rows[name][0].text() for name in ("Resamples", "Sample fraction (%)", "Seed runs",
                                                              "Show co-assignment matrix", "Minimum k")}
        self.assertEqual(captions, {"Ricampionamenti", "Frazione campionata (%)", "Ripetizioni con altri semi",
                                    "Mostra la matrice di co-assegnazione", "k minimo"})

    def test_defaults_and_iteration_limit_only_for_hartigan_wong(self):
        dialog = self.dialog()
        options = dialog.options()
        self.assertEqual(options, {"Variables": ["Marker A", "Marker B"], "Minimum k": 2, "Maximum k": 4,
                                   "Standardize": True, "K-means algorithm": "Lloyd", "Seed": 42, "Resamples": 100,
                                   "Sample fraction (%)": 80.0, "Seed runs": 0, "Report k": 2,
                                   "Show co-assignment matrix": False})
        _caption, limit, form = dialog.rows["Hartigan–Wong iteration limit"]
        self.assertFalse(form.isRowVisible(limit))  # the row may sit on an options tab that is not current
        fill(dialog, **{"K-means algorithm": "Hartigan–Wong", "Hartigan–Wong iteration limit": 25})
        self.assertTrue(form.isRowVisible(limit))
        self.assertEqual(dialog.options()["Hartigan–Wong iteration limit"], 25)
        fill(dialog, **{"K-means algorithm": "Lloyd"})
        self.assertFalse(form.isRowVisible(limit))
        self.assertNotIn("Hartigan–Wong iteration limit", dialog.options())
        saved = (ks.METHOD, {**dialog.options(), "K-means algorithm": "Hartigan–Wong",
                             "Hartigan–Wong iteration limit": 7, "Resamples": 12, "Sample fraction (%)": 75.5})
        reopened = self.dialog(current=saved)
        _caption, limit, form = reopened.rows["Hartigan–Wong iteration limit"]
        self.assertTrue(form.isRowVisible(limit))
        self.assertEqual(reopened.options()["Hartigan–Wong iteration limit"], 7)
        self.assertEqual(reopened.options()["Sample fraction (%)"], 75.5)

    def test_field_errors_focus_the_control_and_the_same_dialog_recovers(self):
        dialog = self.dialog()
        fill(dialog, **{"Minimum k": 3, "Maximum k": 2})
        dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertTrue(dialog.banner.isVisible())
        self.assertIs(self.app.focusWidget(), dialog.controls["Maximum k"][1])
        fill(dialog, **{"Maximum k": 4, "Report k": 2, "Sample fraction (%)": "82,5"})
        dialog.accept()
        self.assertIsNone(dialog.result)  # Report k must now lie in 3–4
        self.assertIs(self.app.focusWidget(), dialog.controls["Report k"][1])
        fill(dialog, **{"Minimum k": 2})
        dialog.accept()
        self.assertEqual(dialog.result[1]["Sample fraction (%)"], 82.5)

    def test_budget_is_refused_in_the_dialog(self):
        dialog = self.dialog()
        with mock.patch.object(ks.engine, "kmeans", side_effect=AssertionError("no fit in the dialog")):
            fill(dialog, **{"Resamples": 2000})
            dialog.accept()
            self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("6000", dialog.banner.text())
        self.assertIs(self.app.focusWidget(), dialog.controls["Resamples"][1])
        fill(dialog, **{"Resamples": 1900, "Seed runs": 100})
        dialog.accept()
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), dialog.controls["Seed runs"][1])
        fill(dialog, **{"Show co-assignment matrix": True, "Seed runs": 0, "Resamples": 10})
        rows = pd.DataFrame(np.random.default_rng(2).normal(size=(201, 2)), columns=["Marker A", "Marker B"])
        large = self.dialog(rows)
        fill(large, **{"Show co-assignment matrix": True})
        large.accept()
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), large.controls["Show co-assignment matrix"][1])

    def test_engine_messages_in_italian(self):
        frame = pd.read_csv(DATA / "separated.csv")
        triggers = [{"Variables": ["Absent"]}, {"Maximum k": 13}, {"Seed runs": 101}, {"Sample fraction (%)": 20},
                    {"Standardize": "x"}, {"Resamples": 2000, "Maximum k": 4},
                    {"Maximum k": 4, "Resamples": 1950, "Seed runs": 100}, {"Variables": ["Marker A", "Marker A"]},
                    {"Maximum k": 12, "Sample fraction (%)": 50}]
        set_language("it")
        for trigger in triggers:
            options = {"Variables": ["Marker A", "Marker B"], **trigger}
            with self.subTest(trigger):
                with self.assertRaises(FieldError) as caught:
                    ks.prepare(frame, options)
                message = str(caught.exception)
                self.assertNotEqual(translate_message(message, ks.ERROR_PREFIX), message)
        dialog = self.dialog()
        fill(dialog, **{"Resamples": 2000})
        dialog.accept()
        self.assertTrue(dialog.banner.text().startswith("Questa richiesta richiede"), dialog.banner.text())
        reopened = self.dialog(current=(ks.METHOD, {}))
        from trama_qt.analysis_dialog import AnalysisDialog
        shown = AnalysisDialog(None, frame, current=(ks.METHOD, {}),
                               error="Resamples: enter a whole number from 5 to 2000.", error_field="Resamples")
        self.addCleanup(shown.deleteLater)
        self.assertEqual(shown.banner.text(), "Ricampionamenti: inserisci un numero intero da 5 a 2000.")
        self.assertIsNotNone(reopened)

    def test_dialog_fits_1024_by_768_in_light_and_dark(self):
        from trama_qt import theme
        try:
            for dark in (False, True):
                theme.apply(self.app, dark=dark)
                for language in ("en", "it"):
                    set_language(language)
                    dialog = self.dialog()
                    hint = dialog.minimumSizeHint()
                    self.assertLessEqual(hint.width(), 1024, (dark, language))
                    self.assertLessEqual(hint.height(), 768, (dark, language))
                    dialog.resize(1024, 700)
                    self.app.processEvents()
                    self.assertTrue(dialog.run_button.isVisible())
        finally:
            theme.apply(self.app)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class StabilityWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt.window import MainWindow
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.window = self.make_window(MainWindow)
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))

    def make_window(self, factory):
        window = factory()
        window.project.dirty = False
        window.show()
        self.app.processEvents()

        def close():
            window.project.dirty = False
            window.close()
            self.app.processEvents()
        self.addCleanup(close)
        return window

    def tearDown(self):
        set_language("en")

    def wait(self, window=None, timeout=120):
        window = window or self.window
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(window.job, "calculation still running")

    def open_fixture(self, window=None):
        window = window or self.window
        path = self.folder / "stabilita-kmeans.alab"
        path.write_bytes((DATA / "stabilita-kmeans.alab").read_bytes())
        window.open_path(path)
        self.wait(window)
        self.assertEqual(window.selected, ("data", TITLE))

    def through_dialog(self, command, values, *, run=True):
        """Run a window command; the dialog it opens is filled like a user would and Run (or Cancel) pressed."""
        from trama_qt.analysis_dialog import AnalysisDialog
        seen = []

        def exec_(dialog):
            seen.append(dialog)
            if dialog.method != ks.METHOD:
                dialog._picked(next(item for item in self._items(dialog) if item.data(0, Qt.ItemDataRole.UserRole)
                                    == ks.METHOD))
            fill(dialog, **values)
            if run:
                dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", exec_):
            command()
        return seen

    @staticmethod
    def _items(dialog):
        for group in range(dialog.methods.topLevelItemCount()):
            folder = dialog.methods.topLevelItem(group)
            for row in range(folder.childCount()):
                yield folder.child(row)

    def first_run(self):
        self.open_fixture()
        self.through_dialog(lambda: self.window.analyze(ks.METHOD), dict(SMALL, **{"Seed runs": 2}))
        self.wait()
        run = self.window.project.runs[-1]
        self.assertIsNone(run.calculation_error)
        return run

    def test_run_view_recalculate_and_use_as_data(self):
        window = self.window
        run = self.first_run()
        self.assertEqual(window.selected, ("graph", 0))  # a graph method opens on its figure
        self.assertEqual(len(run.result.figure.axes), 3)  # ARI panel, co-assignment and its colour bar
        self.assertEqual(run.options["Sample fraction (%)"], 80.0)
        self.assertNotIn("Hartigan–Wong iteration limit", run.options)
        assignments = run.result.tables["Assignment stability"]
        self.assertEqual(list(assignments.index), [r for r in range(1, 21) if r not in {6, 15}])

        # A cell that completes row 6 enters every sheet after the automatic recalculation.
        window.show_sheet("data", TITLE)
        window.edit_cell(TITLE, 5, 0, "-100")
        self.wait()
        run = window.project.runs[0]
        self.assertIsNone(run.calculation_error)
        self.assertEqual(len(run.result.tables["Assignment stability"]), 19)
        # Excluding a value removes that row again.
        window.show_sheet("data", TITLE)
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 1))
        window.toggle_exclusion()
        self.wait()
        rows = list(window.project.runs[0].result.tables["Assignment stability"].index)
        self.assertNotIn(1, rows)
        self.assertIn(6, rows)

        # Use result as data on Assignment stability gives an ordinary table.
        window.show_sheet("result", 0)
        window.result_tabs.setCurrentIndex(list(run.result.tables).index("Assignment stability"))
        window.use_result_as_data()
        self.assertEqual(window.selected[0], "data")
        table = window.project.tables[window.selected[1]].frame()
        self.assertEqual(list(table.columns), ["Worksheet row", "Reference cluster", "Agreement", "Valid resamples"])
        self.assertEqual(self.errors, [])

    def test_failed_recalculation_keeps_previous_result(self):
        window = self.window
        run = self.first_run()
        before = run.result
        window.show_sheet("data", TITLE)
        window.project.paste(TITLE, 0, 1, [["1"]] * 20, "Constant column")  # Marker B constant: cannot standardize
        window.refresh_runs(window.project.table_runs(TITLE))
        self.wait()
        run = window.project.runs[0]
        self.assertIs(run.result, before)
        self.assertIn("constant", run.calculation_error)

    def test_cancel_keeps_recipe_and_results(self):
        window = self.window
        run = self.first_run()
        options, result = dict(run.options), run.result
        window.show_sheet("graph", 0)
        heavy = {"Maximum k": 4, "Resamples": 1500, "Seed runs": 0, "Show co-assignment matrix": False}
        self.through_dialog(window.change_parameters, heavy)
        self.assertIsNotNone(window.job)
        deadline = time.monotonic() + .4
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        finished, total = window.job.control.progress()
        self.assertGreater(total, 1000)
        started = time.monotonic()
        window.cancel_calculation()
        self.wait()
        latency = time.monotonic() - started
        self.assertLess(latency, 5)
        run = window.project.runs[0]
        self.assertEqual(run.options, options)
        self.assertIs(run.result, result)
        self.assertEqual(len(window.project.runs), 1)
        # A new analysis cancelled while it runs adds nothing to the project.
        window.show_sheet("data", TITLE)
        self.through_dialog(lambda: window.analyze(ks.METHOD), heavy)
        window.cancel_calculation()
        self.wait()
        self.assertEqual(len(window.project.runs), 1)
        self.assertEqual(window.project.tables[TITLE].analyses[0][1], options)

    def test_new_analysis_cancelled_in_dialog_adds_nothing(self):
        self.open_fixture()
        self.through_dialog(lambda: self.window.analyze(ks.METHOD), {"Resamples": 2000}, run=True)
        self.assertIsNone(self.window.job)  # refused in the dialog: no worker
        self.assertEqual(self.window.project.runs, [])

    def test_exports_and_project_round_trip_in_other_language(self):
        from trama_qt.window import MainWindow
        window = self.window
        run = self.first_run()
        tables = {name: frame.copy() for name, frame in run.result.tables.items()}
        window.show_sheet("graph", 0)
        for suffix in ("png", "svg", "pdf"):
            target = self.folder / f"stability.{suffix}"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                window.export()
            self.assertGreater(target.stat().st_size, 1000, suffix)
        svg = (self.folder / "stability.svg").read_text(encoding="utf-8")
        self.assertIn("<path", svg)
        self.assertIn("<image", svg)  # the co-assignment heat map may be raster; lines and text stay vector
        window.show_sheet("result", 0)
        window.result_tabs.setCurrentIndex(list(run.result.tables).index("Co-assignment"))
        target = self.folder / "coassignment.csv"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
            window.export()
        csv = pd.read_csv(target, index_col=0)
        self.assertEqual(csv.shape, (18, 18))

        project = self.folder / "stability.alab"
        window.project.save(project)
        with zipfile.ZipFile(project) if zipfile.is_zipfile(project) else open(project, "rb") as handle:
            raw = handle.read("project.json") if isinstance(handle, zipfile.ZipFile) else handle.read()
        saved = json.loads(raw)
        method, options = saved["tables"][0]["analyses"][0]
        self.assertEqual(method, ks.METHOD)
        self.assertEqual(options, run.options)

        set_language("it")
        other = self.make_window(MainWindow)
        other.error = lambda error: self.errors.append(str(error))
        other.open_path(project)
        self.wait(other)
        other.open_sheet(("graph", 0))  # the graph first: the recipe is recalculated with the same settings
        self.wait(other)
        reopened = other.project.runs[0]
        self.assertIsNotNone(reopened.result)
        self.assertEqual(reopened.options, run.options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened.result.tables[name], frame, obj=name)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
