"""Precision–recall curve in the Qt window, offscreen: dialog, live sample count, checks before the worker,
recalculation, exclusion, undo, cancel, exports and a project round trip in the other language.

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
    from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QFileDialog
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import pandas as pd

from analisi import precision_recall as pr
from analisi.field_error import FieldError
from analisi.i18n import set_language, translate_message

CSV = Path(__file__).resolve().parent / "data" / "precision_recall" / "scores.csv"
COLUMNS = {"Outcome": "Event", "Positive": "case", "Negative": "control", "Score": "Signal A",
           "Second score": "Signal B", "Second direction": "Lower is positive"}


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def fill(dialog, **values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if isinstance(control, QCheckBox):
            control.setChecked(bool(value))
        elif hasattr(control, "findData"):
            position = control.findData(value)
            assert position >= 0, (name, value)
            control.setCurrentIndex(position)
        else:
            control.setText(str(value))


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class PrecisionRecallDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def dialog(self, frame=None, current=None, **extra):
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = pd.read_csv(CSV) if frame is None else frame
        dialog = AnalysisDialog(None, frame, current=current or (pr.METHOD, {}), **extra)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def listed(self, dialog, query):
        dialog.query.setText(query)
        return [dialog.methods.topLevelItem(group).child(row).data(0, Qt.ItemDataRole.UserRole)
                for group in range(dialog.methods.topLevelItemCount())
                for row in range(dialog.methods.topLevelItem(group).childCount())]

    def settle(self, dialog):
        dialog.precision.timer.stop()
        dialog.precision.summarize()
        self.app.processEvents()

    def test_catalog_search_and_captions(self):
        dialog = self.dialog()
        self.assertEqual(self.listed(dialog, "precision"), [pr.METHOD])
        group = dialog.methods.topLevelItem(0)
        self.assertEqual(group.text(0), "Group Comparison")
        set_language("it")
        dialog = self.dialog()
        self.assertEqual(dialog.heading.text(), "Curva precisione–richiamo")
        self.assertEqual(self.listed(dialog, "precisione"), [pr.METHOD])
        captions = {name: dialog.rows[name][0].text() for name in
                    ("Outcome", "Positive", "Negative", "Score", "Second score", "Direction", "Second direction",
                     "Bootstrap CI")}
        self.assertEqual(captions, {"Outcome": "Esito", "Positive": "Positiva", "Negative": "Negativa",
                                    "Score": "Punteggio", "Second score": "Secondo punteggio",
                                    "Direction": "Direzione", "Second direction": "Direzione del secondo punteggio",
                                    "Bootstrap CI": "IC bootstrap"})
        direction = dialog.controls["Direction"][1]
        self.assertEqual([direction.itemText(i) for i in range(direction.count())],
                         ["Più alto è positivo", "Più basso è positivo"])
        self.assertEqual(direction.currentData(), "Higher is positive")  # the recipe keeps the English value

    def test_labels_sit_beside_the_outcome_on_the_variables_page(self):
        dialog = self.dialog()
        variables = dialog.tabs.widget(0).widget().layout()
        for name in ("Outcome", "Positive", "Negative", "Score", "Second score"):
            self.assertIs(dialog.rows[name][2], variables, name)
        for name in ("Direction", "Second direction", "Bootstrap CI"):
            self.assertIsNot(dialog.rows[name][2], variables, name)

    def test_defaults_and_conditional_fields(self):
        dialog = self.dialog()
        fill(dialog, **{"Outcome": "Event", "Positive": "case", "Negative": "control", "Score": "Signal A",
                        "Second score": ""})
        self.assertEqual(dialog.options(), {"Outcome": "Event", "Positive": "case", "Negative": "control",
                                            "Score": "Signal A", "Second score": None,
                                            "Direction": "Higher is positive", "Bootstrap CI": False})
        _caption, second, form = dialog.rows["Second direction"]
        self.assertFalse(form.isRowVisible(second))
        _caption, seed, form = dialog.rows["Bootstrap seed"]
        self.assertFalse(form.isRowVisible(seed))
        fill(dialog, **{"Second score": "Signal B", "Bootstrap CI": True, "Bootstrap seed": 2**64 - 1,
                        "Confidence level (%)": "90,5"})
        self.assertTrue(dialog.rows["Second direction"][2].isRowVisible(second))
        self.assertTrue(form.isRowVisible(seed))
        options = dialog.options()
        self.assertEqual((options["Bootstrap seed"], options["Bootstrap replicates"],
                          options["Confidence level (%)"]), (2**64 - 1, 1999, 90.5))
        reopened = self.dialog(current=(pr.METHOD, options))
        self.assertEqual(reopened.options(), options)
        self.assertTrue(reopened.rows["Bootstrap seed"][2].isRowVisible(reopened.rows["Bootstrap seed"][1]))
        reopened.accept()
        self.assertEqual(reopened.result, (pr.METHOD, options))

    def test_live_count_and_prevalence(self):
        dialog = self.dialog()
        self.settle(dialog)
        self.assertIn("Enter the exact label", dialog.precision.info.text())  # the labels are explicit, no guess
        fill(dialog, **COLUMNS)
        self.settle(dialog)
        self.assertEqual(dialog.precision.info.text(),
                         "Common samples: 8 · Positives: 3 · Negatives: 5 · Prevalence: 0.375\n"
                         "Rows left out for blank cells: 2.")
        fill(dialog, **{"Second score": ""})
        self.settle(dialog)
        self.assertIn("Common samples: 9 ", dialog.precision.info.text())
        set_language("it")
        dialog = self.dialog()
        fill(dialog, **COLUMNS)
        self.settle(dialog)
        self.assertEqual(dialog.precision.info.text(),
                         "Campioni comuni: 8 · Positivi: 3 · Negativi: 5 · Prevalenza: 0,375\n"
                         "Righe escluse per celle vuote: 2.")
        fill(dialog, **{"Positive": "x"})
        self.settle(dialog)
        self.assertIn("non è né Positivo", dialog.precision.info.text())
        self.assertFalse(dialog.banner.isVisible())  # the live line never raises the error banner

    def test_large_worksheets_are_counted_on_run(self):
        frame = pd.DataFrame({"Event": ["case", "control"], "Signal A": [1.0, 2.0]})
        with mock.patch("trama_qt.precision_recall.PREVIEW_ROWS", 1):
            dialog = self.dialog(frame)
            self.settle(dialog)
        self.assertEqual(dialog.precision.info.text(), "The sample count appears when you press Run.")

    def test_errors_focus_the_field_before_any_worker(self):
        frame = pd.read_csv(CSV)
        dialog = self.dialog(frame)
        fill(dialog, **{**COLUMNS, "Bootstrap CI": True})
        with mock.patch.object(pr, "bootstrap", side_effect=AssertionError("no resampling in the dialog")):
            fill(dialog, Positive="")
            dialog.accept()
            self.app.processEvents()
            self.assertIsNone(dialog.result)
            self.assertIn("Enter the exact label of the positive rows.", dialog.banner.text())
            self.assertIs(self.app.focusWidget(), dialog.controls["Positive"][1])
            fill(dialog, Positive="Case")
            dialog.accept()
            self.assertIn('"case" in row 1', dialog.banner.text())
            self.assertIs(self.app.focusWidget(), dialog.controls["Outcome"][1])
            fill(dialog, Positive="case", **{"Bootstrap replicates": 10})
            dialog.accept()
            self.assertIs(self.app.focusWidget(), dialog.controls["Bootstrap replicates"][1])
            self.assertIn("from 199 to 10,000", dialog.banner.text())
            fill(dialog, **{"Bootstrap replicates": 199})
            dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_error_in_a_tab_that_is_not_shown_selects_that_tab(self):
        dialog = self.dialog()
        fill(dialog, **{**COLUMNS, "Bootstrap CI": True, "Bootstrap replicates": 5})
        dialog.tabs.setCurrentIndex(0)
        dialog.accept()
        self.assertEqual(dialog.tabs.currentIndex(), 1)  # the Options page holds the replicates

    def test_engine_messages_in_italian(self):
        frame = pd.read_csv(CSV)
        triggers = [{"Score": "Event"}, {"Second score": "Signal A"}, {"Positive": ""}, {"Negative": "case"},
                    {"Direction": "x"}, {"Outcome": "Absent"}, {"Positive": "zz", "Negative": "control"},
                    {"Bootstrap CI": True, "Bootstrap replicates": 10}, {"Bootstrap CI": True, "Bootstrap seed": -1},
                    {"Bootstrap CI": True, "Confidence level (%)": 100}, {"Bootstrap CI": "yes"}]
        set_language("it")
        for trigger in triggers:
            with self.subTest(trigger):
                with self.assertRaises(FieldError) as caught:
                    pr.check_options(frame, {**COLUMNS, **trigger})
                message = str(caught.exception)
                self.assertNotEqual(translate_message(message, pr.ERROR_PREFIX), message)
        infinite = frame.copy()
        infinite.loc[0, "Signal A"] = float("inf")
        single = pd.DataFrame({"Event": ["case"] * 3, "Signal A": [1.0, 2.0, 3.0]})
        none = pd.DataFrame({"Event": ["case"], "Signal A": [None]})
        big = pd.DataFrame({"Event": ["case", "control"] * 2001, "Signal A": range(4002)})
        text = frame.astype({"Signal A": object})
        text.loc[2, "Signal A"] = "n/a"
        bad = [(infinite, {}), (single, {"Second score": None}), (single.assign(Event="control"), {"Second score": None}),
               (none, {"Second score": None}), (text, {}),
               (big, {"Second score": None, "Bootstrap CI": True, "Bootstrap replicates": 10_000}),
               (frame.assign(**{"Signal A": [True] * 10}), {})]
        for data, change in bad:
            with self.assertRaises(FieldError) as caught:
                pr.check_options(data, {**COLUMNS, **change})
            message = str(caught.exception)
            self.assertNotEqual(translate_message(message, pr.ERROR_PREFIX), message, message)
        shown = self.dialog(current=(pr.METHOD, COLUMNS), error="Bootstrap replicates must be a whole number from "
                            "199 to 10,000.", error_field="Bootstrap replicates")
        self.assertEqual(shown.banner.text(),
                         "Valore di Repliche bootstrap: inserisci un intero da 199 a 10.000.")
        reused = self.dialog(current=(pr.METHOD, COLUMNS), error='Column "Event" is already used for Outcome. '
                             "Choose a different column for Score.", error_field="Score")
        self.assertEqual(reused.banner.text(),
                         'La colonna "Event" è già usata per Esito. Scegli una colonna diversa per Punteggio.')

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
class PrecisionRecallWindowTests(unittest.TestCase):
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
            if dialog.method != pr.METHOD:
                dialog.method = pr.METHOD
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
        self.through_dialog(lambda: self.window.analyze(pr.METHOD), {**COLUMNS, **values})
        self.wait()
        run = self.window.project.runs[-1]
        self.assertIsNone(run.calculation_error)
        return run

    def test_run_edit_exclude_and_undo(self):
        window = self.window
        run = self.first_run()
        self.assertEqual(window.selected, ("graph", 0))
        tables = run.result.tables
        self.assertEqual(list(tables), ["Summary", "Thresholds: Signal A", "Thresholds: Signal B", "Comparison",
                                        "Settings", "Excluded rows"])
        self.assertEqual(tables["Excluded rows"]["Source row"].tolist(), [9, 10])
        self.assertEqual(tables["Summary"]["N"].tolist(), [8, 8])
        # Completing row 10 (Event) and row 9 (Signal B) recalculates: ten common samples, no exclusions.
        window.show_sheet("data", self.title)
        window.edit_cell(self.title, 9, 1, "control")
        self.wait()
        window.edit_cell(self.title, 8, 3, "0.3")
        self.wait()
        run = window.project.runs[0]
        self.assertEqual(run.result.tables["Summary"]["N"].tolist(), [10, 10])
        self.assertNotIn("Excluded rows", run.result.tables)
        # Excluding Signal A of row 1 leaves that row out of both curves.
        window.show_sheet("data", self.title)
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 2))
        window.toggle_exclusion()
        self.wait()
        run = window.project.runs[0]
        self.assertEqual(run.result.tables["Excluded rows"]["Source row"].tolist(), [1])
        self.assertEqual(run.result.tables["Summary"]["N"].tolist(), [9, 9])
        window.undo()
        self.wait()
        self.assertNotIn("Excluded rows", window.project.runs[0].result.tables)
        self.assertEqual(self.errors, [])

    def test_failed_recalculation_keeps_the_previous_result(self):
        window = self.window
        run = self.first_run()
        before = run.result
        window.show_sheet("data", self.title)
        window.edit_cell(self.title, 1, 1, "typo")
        self.wait()
        run = window.project.runs[0]
        self.assertIs(run.result, before)
        self.assertIn('"typo" in row 2', run.calculation_error)

    def test_cancel_returns_to_the_last_confirmed_result(self):
        window = self.window
        run = self.first_run()
        options, result = dict(run.options), run.result
        started = []

        def slow(plan, cancel=None, **_):
            started.append(True)
            while not cancel.is_set():
                time.sleep(.01)
            pr.check_cancel(cancel)

        window.show_sheet("graph", 0)
        with mock.patch.object(pr, "bootstrap", side_effect=slow):
            self.through_dialog(window.change_parameters, {"Bootstrap CI": True})
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
        run = self.first_run(**{"Bootstrap CI": True, "Bootstrap replicates": 499, "Bootstrap seed": 9})
        tables = {name: frame.copy() for name, frame in run.result.tables.items()}
        self.assertIn("AP lower", tables["Summary"])
        window.show_sheet("graph", 0)
        for suffix in ("png", "svg", "pdf"):
            target = self.folder / f"curva.{suffix}"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                window.export()
            self.assertGreater(target.stat().st_size, 1000, suffix)
        self.assertIn("<path", (self.folder / "curva.svg").read_text(encoding="utf-8"))
        window.show_sheet("result", 0)
        window.result_tabs.setCurrentIndex(list(run.result.tables).index("Thresholds: Signal A"))
        target = self.folder / "soglie.csv"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")) as chooser:
            window.export()
        self.assertEqual(chooser.call_args.args[2], "Thresholds_ Signal A.csv")
        self.assertEqual(len(pd.read_csv(target)), 7)

        project = self.folder / "precisione richiamo.alab"
        window.project.save(project)
        with zipfile.ZipFile(project) if zipfile.is_zipfile(project) else open(project, "rb") as handle:
            raw = handle.read("project.json") if isinstance(handle, zipfile.ZipFile) else handle.read()
        method, options = json.loads(raw)["tables"][0]["analyses"][0]
        self.assertEqual(method, pr.METHOD)
        self.assertEqual(options, run.options)
        self.assertEqual(options["Direction"], "Higher is positive")

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
