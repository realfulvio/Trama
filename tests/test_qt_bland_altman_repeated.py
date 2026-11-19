"""Bland–Altman for repeated pairs in the Qt window, offscreen: dialog, checks before the worker, recalculation,
exclusion, undo, cancel, exports and a project round trip in the other language.

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

import pandas as pd

from analisi import bland_altman_repeated as bar
from analisi.field_error import FieldError
from analisi.i18n import set_language, translate_message

DATA = Path(__file__).resolve().parent / "data" / "bland_altman_repeated"
CSV = DATA / "glicemia ripetuta.csv"
COLUMNS = {"Subject": "Paziente #", "Occasion": "Visita |", "First": "Metodo A (mg/dl)",
           "Second": "Metodo B (mg/dl)"}


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def fill(dialog, **values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if hasattr(control, "findData"):
            position = control.findData(value)
            assert position >= 0, (name, value)
            control.setCurrentIndex(position)
        else:
            control.setText(str(value))


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class RepeatedAgreementDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def dialog(self, frame=None, current=None, **extra):
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = pd.read_csv(CSV) if frame is None else frame
        dialog = AnalysisDialog(None, frame, current=current or (bar.METHOD, {}), **extra)
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
        self.assertEqual(self.listed(dialog, "repeated pairs"), [bar.METHOD])
        set_language("it")
        dialog = self.dialog()
        self.assertEqual(dialog.heading.text(), "Bland–Altman per coppie ripetute")
        self.assertEqual(self.listed(dialog, "coppie ripetute"), [bar.METHOD])
        captions = {name: dialog.rows[name][0].text() for name in ("Subject", "Occasion", "First", "Mode",
                                                                     "Coverage", "Confidence intervals", "Graph")}
        self.assertEqual(captions["Occasion"], "Occasione")
        self.assertEqual(captions["Mode"], "Modalità")
        self.assertEqual(captions["Coverage"], "Copertura (%)")
        self.assertEqual(captions["Subject"], "Soggetto")
        mode = dialog.controls["Mode"][1]
        self.assertEqual([mode.itemText(i) for i in range(mode.count())], ["Differenza", "Logaritmo del rapporto"])
        self.assertEqual(mode.currentData(), "Difference")  # the recipe keeps the English value

    def test_defaults_and_bootstrap_fields_only_with_the_bootstrap(self):
        dialog = self.dialog()
        fill(dialog, **COLUMNS)
        self.assertEqual(dialog.options(), {**COLUMNS, "Mode": "Difference", "Coverage": 95.0,
                                            "Confidence intervals": "None", "Graph": "Pairs"})
        _caption, seed, form = dialog.rows["Seed"]
        self.assertFalse(form.isRowVisible(seed))
        fill(dialog, **{"Confidence intervals": "Subject bootstrap", "Seed": 4294967295, "Coverage": "90,5"})
        self.assertTrue(form.isRowVisible(seed))
        options = dialog.options()
        self.assertEqual((options["Seed"], options["Bootstrap replicates"], options["Confidence level (%)"],
                          options["Coverage"]), (4294967295, 2000, 95.0, 90.5))
        reopened = self.dialog(current=(bar.METHOD, options))
        _caption, seed, form = reopened.rows["Seed"]
        self.assertTrue(form.isRowVisible(seed))
        self.assertEqual(reopened.options(), options)

    def test_occasion_is_optional(self):
        dialog = self.dialog()
        fill(dialog, **{**COLUMNS, "Occasion": ""})
        self.assertIsNone(dialog.options()["Occasion"])
        dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_errors_focus_the_field_before_any_worker(self):
        frame = pd.read_csv(CSV)
        frame.loc[1, "Visita |"] = 1  # P-01 twice at visit 1
        dialog = self.dialog(frame)
        fill(dialog, **COLUMNS)
        with mock.patch.object(bar, "bootstrap", side_effect=AssertionError("no resampling in the dialog")):
            dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("rows 1 and 2", dialog.banner.text())
        self.assertIs(self.app.focusWidget(), dialog.controls["Occasion"][1])
        fill(dialog, **{"Occasion": "", "Mode": "Log ratio"})
        dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_engine_messages_in_italian(self):
        frame = pd.read_csv(CSV)
        triggers = [{"Second": "Metodo A (mg/dl)"}, {"Subject": "Metodo A (mg/dl)"}, {"Occasion": "Paziente #"},
                    {"Coverage": 100}, {"Mode": "x"}, {"Subject": "Absent"},
                    {"Confidence intervals": "Subject bootstrap", "Bootstrap replicates": 10},
                    {"Confidence intervals": "Subject bootstrap", "Seed": -1}]
        set_language("it")
        for trigger in triggers:
            with self.subTest(trigger):
                with self.assertRaises(FieldError) as caught:
                    bar.check_options(frame, {**COLUMNS, **trigger})
                message = str(caught.exception)
                self.assertNotEqual(translate_message(message, bar.ERROR_PREFIX), message)
        duplicated = frame.copy()
        duplicated.loc[1, "Visita |"] = 1
        bad = [(duplicated, {}), (frame.assign(**{"Metodo B (mg/dl)": 0}), {"Mode": "Log ratio"}),
               (frame.head(3), {}), (frame.iloc[[0, 3, 6, 7]], {})]
        for data, change in bad:
            with self.assertRaises(FieldError) as caught:
                bar.check_options(data, {**COLUMNS, **change})
            message = str(caught.exception)
            self.assertNotEqual(translate_message(message, bar.ERROR_PREFIX), message, message)
        shown = self.dialog(current=(bar.METHOD, COLUMNS), error="Coverage must be a number greater than 0 and "
                            "less than 100.", error_field="Coverage")
        self.assertEqual(shown.banner.text(), "Copertura (%) deve essere un numero maggiore di 0 e minore di 100.")

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
        finally:
            theme.apply(self.app)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class RepeatedAgreementWindowTests(unittest.TestCase):
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

    def tearDown(self):
        set_language("en")

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

    def wait(self, window=None, timeout=120):
        window = window or self.window
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(window.job, "calculation still running")

    def through_dialog(self, command, values):
        from trama_qt.analysis_dialog import AnalysisDialog

        def exec_(dialog):
            if dialog.method != bar.METHOD:
                dialog.method = bar.METHOD
                dialog.configure_fields()
            fill(dialog, **values)
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", exec_):
            command()

    def first_run(self, **values):
        self.window.open_path(CSV)
        self.wait()
        self.title = self.window.selected[1]
        self.through_dialog(lambda: self.window.analyze(bar.METHOD), {**COLUMNS, **values})
        self.wait()
        run = self.window.project.runs[-1]
        self.assertIsNone(run.calculation_error)
        return run

    def test_run_edit_exclude_and_undo(self):
        window = self.window
        run = self.first_run()
        self.assertEqual(window.selected, ("graph", 0))
        tables = run.result.tables
        self.assertEqual(list(tables), ["Agreement", "Subjects", "Pairs", "Excluded rows"])
        self.assertEqual(tables["Excluded rows"]["Source row"].tolist(), [5])
        self.assertEqual(tables["Agreement"].iloc[0]["Pairs"], 14)
        # Completing row 5 recalculates: one more pair, no exclusions.
        window.show_sheet("data", self.title)
        window.edit_cell(self.title, 4, 2, "123")
        self.wait()
        run = window.project.runs[0]
        self.assertEqual(run.result.tables["Agreement"].iloc[0]["Pairs"], 15)
        self.assertNotIn("Excluded rows", run.result.tables)
        # Excluding First of row 1 lists it as an excluded pair.
        window.show_sheet("data", self.title)
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 2))
        window.toggle_exclusion()
        self.wait()
        run = window.project.runs[0]
        self.assertEqual(run.result.tables["Excluded rows"]["Source row"].tolist(), [1])
        self.assertEqual(run.result.tables["Pairs"]["Source row"].iloc[0], 2)
        window.undo()
        self.wait()
        self.assertNotIn("Excluded rows", window.project.runs[0].result.tables)
        self.assertEqual(self.errors, [])

    def test_failed_recalculation_keeps_the_previous_result(self):
        window = self.window
        run = self.first_run(Mode="Log ratio")
        before = run.result
        window.show_sheet("data", self.title)
        window.edit_cell(self.title, 0, 3, "-1")
        self.wait()
        run = window.project.runs[0]
        self.assertIs(run.result, before)
        self.assertIn("positive values", run.calculation_error)

    def test_cancel_returns_to_the_last_confirmed_result(self):
        window = self.window
        run = self.first_run()
        options, result = dict(run.options), run.result
        started = []

        def slow(plan, cancel=None, **_):
            started.append(True)
            while not cancel.is_set():
                time.sleep(.01)
            bar.check_cancel(cancel)

        window.show_sheet("graph", 0)
        with mock.patch.object(bar, "bootstrap", side_effect=slow):
            self.through_dialog(window.change_parameters, {"Confidence intervals": "Subject bootstrap"})
            self.assertIsNotNone(window.job)
            end = time.monotonic() + 10
            while not started and time.monotonic() < end:
                self.app.processEvents()
                time.sleep(.01)
            window.cancel_calculation()
            self.wait()
        run = window.project.runs[0]
        self.assertEqual(run.options, options)
        self.assertIs(run.result, result)
        self.assertEqual(len(window.project.runs), 1)

    def test_exports_and_project_round_trip_in_italian(self):
        from trama_qt.window import MainWindow
        window = self.window
        run = self.first_run(**{"Confidence intervals": "Subject bootstrap", "Bootstrap replicates": 499,
                                "Seed": 9})
        tables = {name: frame.copy() for name, frame in run.result.tables.items()}
        window.show_sheet("graph", 0)
        for suffix in ("png", "svg", "pdf"):
            target = self.folder / f"accordo.{suffix}"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                window.export()
            self.assertGreater(target.stat().st_size, 1000, suffix)
        self.assertIn("<path", (self.folder / "accordo.svg").read_text(encoding="utf-8"))
        window.show_sheet("result", 0)
        window.result_tabs.setCurrentIndex(list(run.result.tables).index("Pairs"))
        target = self.folder / "coppie.csv"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
            window.export()
        self.assertEqual(pd.read_csv(target)["Source row"].tolist(), [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])

        project = self.folder / "accordo ripetuto.alab"
        window.project.save(project)
        with zipfile.ZipFile(project) if zipfile.is_zipfile(project) else open(project, "rb") as handle:
            raw = handle.read("project.json") if isinstance(handle, zipfile.ZipFile) else handle.read()
        method, options = json.loads(raw)["tables"][0]["analyses"][0]
        self.assertEqual(method, bar.METHOD)
        self.assertEqual(options, run.options)
        self.assertEqual(options["Mode"], "Difference")

        set_language("it")
        other = self.make_window(MainWindow)
        other.error = lambda error: self.errors.append(str(error))
        other.open_path(project)
        self.wait(other)
        other.open_sheet(("graph", 0))
        self.wait(other)
        reopened = other.project.runs[0]
        self.assertIsNotNone(reopened.result)
        self.assertEqual(reopened.options, run.options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened.result.tables[name], frame, obj=name)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
