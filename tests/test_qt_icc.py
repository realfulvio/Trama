"""Intraclass correlation in the Qt window, offscreen: dialog, checks before the worker, recalculation, exclusion,
undo, cancel, exports and a project round trip in the other language.

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

from analisi import icc
from analisi.field_error import FieldError
from analisi.i18n import set_language, translate_message

DATA = Path(__file__).resolve().parent / "data" / "icc"
CSV = DATA / "valutatori.csv"
A, B, C = "Valutatore A (mg/dl)", "Valutatore B (mg/dl)", "Valutatore C | mg/dl"
SUBJECT = "Soggetto #"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def tick(dialog, *names):
    """Tick the rater columns in this order (and untick every other one)."""
    _kind, control = dialog.controls["Raters"]
    for position in range(control.count()):
        control.item(position).setCheckState(Qt.CheckState.Unchecked)
    for name in names:
        for position in range(control.count()):
            if control.item(position).text() == name:
                control.item(position).setCheckState(Qt.CheckState.Checked)


def fill(dialog, **values):
    for name, value in values.items():
        _kind, control = dialog.controls[name]
        if name == "Raters":
            tick(dialog, *value)
        elif hasattr(control, "findData"):
            position = control.findData(value)
            assert position >= 0, (name, value)
            control.setCurrentIndex(position)
        elif hasattr(control, "setChecked"):
            control.setChecked(bool(value))
        else:
            control.setText(str(value))


RECIPE = {"Raters": [A, B, C], "Subject": SUBJECT}


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class IccDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def dialog(self, frame=None, current=None, **extra):
        from trama_qt.analysis_dialog import AnalysisDialog
        frame = pd.read_csv(CSV) if frame is None else frame
        dialog = AnalysisDialog(None, frame, current=current or (icc.METHOD, {}), **extra)
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
        self.assertEqual(self.listed(dialog, "intraclass"), [icc.METHOD])
        set_language("it")
        dialog = self.dialog()
        self.assertEqual(dialog.heading.text(), "Correlazione intraclasse")
        self.assertEqual(self.listed(dialog, "intraclasse"), [icc.METHOD])
        captions = {name: dialog.rows[name][0].text() for name in ("Raters", "Subject", "Definition", "Unit",
                                                                     "Bootstrap CI", "Profile graph")}
        self.assertEqual(captions, {"Raters": "Valutatori", "Subject": "Soggetto", "Definition": "Definizione",
                                    "Unit": "Unità", "Bootstrap CI": "IC bootstrap",
                                    "Profile graph": "Grafico dei profili"})
        definition, unit = dialog.controls["Definition"][1], dialog.controls["Unit"][1]
        self.assertEqual([definition.itemText(i) for i in range(definition.count())],
                         ["Accordo assoluto", "Coerenza"])
        self.assertEqual([unit.itemText(i) for i in range(unit.count())], ["Misura singola", "Media dei valutatori"])
        self.assertEqual((definition.currentData(), unit.currentData()), ("Absolute agreement", "Single measure"))

    def test_defaults_order_of_selection_and_bootstrap_fields(self):
        dialog = self.dialog()
        fill(dialog, Raters=[C, A], Subject=SUBJECT)
        self.assertEqual(dialog.options(), {"Raters": [C, A], "Subject": SUBJECT, "Definition": "Absolute agreement",
                                            "Unit": "Single measure", "Bootstrap CI": False, "Profile graph": True})
        _caption, seed, form = dialog.rows["Seed"]
        self.assertFalse(form.isRowVisible(seed))
        fill(dialog, **{"Bootstrap CI": True, "Seed": 18446744073709551615, "Bootstrap replicates": 500,
                        "Definition": "Consistency", "Unit": "Mean of raters"})
        self.assertTrue(form.isRowVisible(seed))
        options = dialog.options()
        self.assertEqual((options["Seed"], options["Bootstrap replicates"], options["Confidence level (%)"],
                          options["Raters"]), (18446744073709551615, 500, 95.0, [C, A]))
        reopened = self.dialog(current=(icc.METHOD, options))
        self.assertTrue(reopened.rows["Seed"][2].isRowVisible(reopened.rows["Seed"][1]))
        self.assertEqual(reopened.options(), options)  # the order of the raters survives a round trip

    def test_summary_follows_the_selection_in_both_languages(self):
        dialog = self.dialog()
        self.assertEqual(dialog.icc.summary.text(), "Choose at least two rater columns.")
        fill(dialog, Raters=[B, A, C])
        self.assertEqual(dialog.icc.summary.text().splitlines(), [
            "11 complete subjects · 3 raters · incomplete rows left out: 1",
            f"Order of the raters: {B} → {A} → {C}", "Absolute agreement, Single measure"])
        fill(dialog, Definition="Consistency", Unit="Mean of raters")
        self.assertEqual(dialog.icc.summary.text().splitlines()[-1], "Consistency, Mean of raters")
        fill(dialog, Raters=[A, B])
        self.assertTrue(dialog.icc.summary.text().startswith("12 complete subjects · 2 raters"))
        set_language("it")
        dialog = self.dialog()
        fill(dialog, Raters=[A, B], Unit="Mean of raters")
        self.assertEqual(dialog.icc.summary.text().splitlines(), [
            "12 soggetti completi · 2 valutatori · righe incomplete escluse: 0",
            f"Ordine dei valutatori: {A} → {B}", "Accordo assoluto, Media dei valutatori"])

    def test_optional_subject_and_accept(self):
        dialog = self.dialog()
        fill(dialog, Raters=[A, B, C])
        self.assertIsNone(dialog.options()["Subject"])
        dialog.accept()
        self.assertIsNotNone(dialog.result)
        self.assertEqual(dialog.result[1]["Raters"], [A, B, C])

    def test_errors_focus_the_field_before_any_worker(self):
        dialog = self.dialog()
        fill(dialog, Raters=[A, B], **{"Bootstrap CI": True, "Bootstrap replicates": 50})
        with mock.patch.object(icc, "bootstrap", side_effect=AssertionError("no resampling in the dialog")):
            dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("whole number from 199 to 5,000", dialog.banner.text())
        self.assertIs(dialog.focusWidget(), dialog.controls["Bootstrap replicates"][1])
        fill(dialog, **{"Bootstrap replicates": 199})
        dialog.accept()
        self.assertIsNotNone(dialog.result)

    def test_one_rater_is_refused_and_the_list_gets_the_focus(self):
        dialog = self.dialog()
        fill(dialog, Raters=[A])
        dialog.accept()
        self.app.processEvents()
        self.assertIsNone(dialog.result)
        self.assertIn("at least two columns", dialog.banner.text())
        self.assertIs(dialog.focusWidget(), dialog.controls["Raters"][1])

    def test_engine_messages_in_italian(self):
        frame = pd.read_csv(CSV)
        triggers = [{"Raters": [A]}, {"Raters": [A, A]}, {"Raters": [A, "Assente"]}, {"Subject": A},
                    {"Definition": "x"}, {"Unit": "x"}, {"Bootstrap CI": True, "Confidence level (%)": 100},
                    {"Bootstrap CI": True, "Bootstrap replicates": 10}, {"Bootstrap CI": True, "Seed": -1},
                    {"Bootstrap CI": 3}]
        set_language("it")
        for trigger in triggers:
            with self.subTest(trigger):
                with self.assertRaises(FieldError) as caught:
                    icc.check_options(frame, {**RECIPE, **trigger})
                message = str(caught.exception)
                self.assertNotEqual(translate_message(message, icc.ERROR_PREFIX), message)
        for data in (frame.head(2), frame.assign(**{A: ["x"] * 12}), frame.assign(**{A: [1e200] * 12})):
            with self.assertRaises(FieldError) as caught:
                icc.check_options(data, RECIPE)
            self.assertNotEqual(translate_message(str(caught.exception), icc.ERROR_PREFIX), str(caught.exception))
        shown = self.dialog(current=(icc.METHOD, RECIPE), error="Choose at least two columns for Raters.",
                            error_field="Raters")
        self.assertEqual(shown.banner.text(), "Scegli almeno due colonne per Valutatori.")
        overlap = self.dialog(current=(icc.METHOD, RECIPE), error="Subject must be a column other than the Raters.",
                              error_field="Subject")
        self.assertEqual(overlap.banner.text(), "Soggetto deve essere una colonna diversa dai Valutatori.")

    def test_dialog_fits_1024_by_768_in_light_and_dark(self):
        from trama_qt import theme
        try:
            for dark in (False, True):
                theme.apply(self.app, dark=dark)
                for language in ("en", "it"):
                    set_language(language)
                    dialog = self.dialog()
                    fill(dialog, Raters=[A, B, C], **{"Bootstrap CI": True})
                    hint = dialog.minimumSizeHint()
                    self.assertLessEqual(hint.width(), 1024, (dark, language))
                    self.assertLessEqual(hint.height(), 768, (dark, language))
        finally:
            theme.apply(self.app)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class IccWindowTests(unittest.TestCase):
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
            if dialog.method != icc.METHOD:
                dialog.method = icc.METHOD
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
        self.through_dialog(lambda: self.window.analyze(icc.METHOD), {**RECIPE, **values})
        self.wait()
        run = self.window.project.runs[-1]
        self.assertIsNone(run.calculation_error)
        return run

    def test_run_edit_exclude_and_undo(self):
        window = self.window
        run = self.first_run()
        self.assertEqual(window.selected, ("graph", 0))
        tables = run.result.tables
        self.assertEqual(list(tables), ["ICC", "ANOVA components", "Subjects", "Settings", "Excluded rows"])
        self.assertEqual(tables["Excluded rows"]["Source row"].tolist(), [5])
        self.assertEqual(tables["ICC"].iloc[0]["N"], 11)
        # Completing row 5 recalculates: one more subject, no exclusions.
        window.show_sheet("data", self.title)
        window.edit_cell(self.title, 4, 3, "97.5")
        self.wait()
        run = window.project.runs[0]
        self.assertEqual(run.result.tables["ICC"].iloc[0]["N"], 12)
        self.assertNotIn("Excluded rows", run.result.tables)
        # Excluding one cell of row 1 leaves the whole row out.
        window.show_sheet("data", self.title)
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 2))
        window.toggle_exclusion()
        self.wait()
        run = window.project.runs[0]
        self.assertEqual(run.result.tables["Excluded rows"]["Source row"].tolist(), [1])
        self.assertEqual(run.result.tables["Subjects"]["Source row"].iloc[0], 2)
        self.assertEqual(run.result.tables["ICC"].iloc[0]["N"], 11)
        window.undo()
        self.wait()
        self.assertNotIn("Excluded rows", window.project.runs[0].result.tables)
        self.assertEqual(self.errors, [])

    def test_failed_recalculation_keeps_the_previous_result(self):
        window = self.window
        run = self.first_run()
        before = run.result
        window.show_sheet("data", self.title)
        window.edit_cell(self.title, 0, 1, "1e101")
        self.wait()
        run = window.project.runs[0]
        self.assertIs(run.result, before)
        self.assertIn("outside −1e100 to 1e100 in row 1", run.calculation_error)

    def test_cancel_returns_to_the_last_confirmed_result(self):
        window = self.window
        run = self.first_run()
        options, result = dict(run.options), run.result
        started = []

        def slow(plan, cancel=None, **_):
            started.append(True)
            while not cancel.is_set():
                time.sleep(.01)
            icc.check_cancel(cancel)

        window.show_sheet("graph", 0)
        with mock.patch.object(icc, "bootstrap", side_effect=slow):
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
        run = self.first_run(**{"Bootstrap CI": True, "Bootstrap replicates": 499, "Seed": 9,
                                "Raters": [C, A, B], "Unit": "Mean of raters"})
        tables = {name: frame.copy() for name, frame in run.result.tables.items()}
        window.show_sheet("graph", 0)
        for suffix in ("png", "svg", "pdf"):
            target = self.folder / f"icc.{suffix}"
            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                window.export()
            self.assertGreater(target.stat().st_size, 1000, suffix)
        self.assertIn("<path", (self.folder / "icc.svg").read_text(encoding="utf-8"))
        window.show_sheet("result", 0)
        window.result_tabs.setCurrentIndex(list(run.result.tables).index("Subjects"))
        target = self.folder / "soggetti.csv"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
            window.export()
        self.assertEqual(pd.read_csv(target)["Source row"].tolist(), [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12])

        project = self.folder / "valutatori.alab"
        window.project.save(project)
        with zipfile.ZipFile(project) if zipfile.is_zipfile(project) else open(project, "rb") as handle:
            raw = handle.read("project.json") if isinstance(handle, zipfile.ZipFile) else handle.read()
        method, options = json.loads(raw)["tables"][0]["analyses"][0]
        self.assertEqual(method, icc.METHOD)
        self.assertEqual(options, run.options)
        self.assertEqual(options["Raters"], [C, A, B])  # the order of selection is part of the recipe
        self.assertEqual((options["Definition"], options["Unit"]), ("Absolute agreement", "Mean of raters"))

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
