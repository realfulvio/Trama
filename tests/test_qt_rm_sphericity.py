"""Sphericity correction of Repeated measures ANOVA in the Qt window, offscreen: dialog, results, CSV, projects.

Skipped when PySide6 (or the Qt platform libraries) are not installed.
"""
import csv
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np
import pandas as pd

from analisi import rm_sphericity
from analisi.i18n import set_language
from analisi.workbench import analyse
from tests.test_rm_sphericity import CONDITION, METHOD, VISIT, long

TITLE = "Misure ripetute"
FIELD = "Sphericity correction"
CHOICES = ["None", "Geisser–Greenhouse", "Huynh-Feldt", "Lower bound"]
LEGACY = "Geisser–Greenhouse (one-way)"
FRAME = long()


def recipe(correction="Huynh-Feldt", factors=(VISIT, CONDITION)):
    return {"Response": "Response", "Factors": list(factors), "Subject": "Subject", FIELD: correction}


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


def choose(dialog, name, value):
    control = dialog.controls[name][1]
    control.setCurrentIndex(control.findData(value))


def captions(control):
    return [control.itemText(index) for index in range(control.count())]


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class SphericityDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        set_language("en")

    def dialog(self, frame=None, current=None, **kwargs):
        from trama_qt.analysis_dialog import AnalysisDialog
        dialog = AnalysisDialog(None, FRAME if frame is None else frame, current=current or (METHOD, {}), **kwargs)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_four_choices_with_none_first_and_the_recipe_keeps_the_english_value(self):
        dialog = self.dialog(current=(METHOD, recipe("None")))
        control = dialog.controls[FIELD][1]
        self.assertEqual([control.itemData(i) for i in range(control.count())], CHOICES)
        self.assertEqual(captions(control), CHOICES)
        for value in CHOICES[1:]:
            choose(dialog, FIELD, value)
            dialog.accept()
            self.assertEqual(dialog.result[1][FIELD], value)
            self.assertEqual(dialog.result[1]["Factors"], [VISIT, CONDITION])

    def test_italian_captions_for_the_row_the_choices_and_the_notes(self):
        set_language("it")
        dialog = self.dialog(current=(METHOD, recipe("None")))
        control = dialog.controls[FIELD][1]
        self.assertEqual(dialog.rows[FIELD][0].text(), "Correzione della sfericità")
        self.assertEqual(captions(control), ["Nessuno", "Geisser–Greenhouse", "Huynh–Feldt", "Limite inferiore"])
        self.assertEqual([control.itemData(i) for i in range(control.count())], CHOICES)
        choose(dialog, FIELD, "Huynh-Feldt")
        self.assertTrue(dialog.sphericity.note.text().startswith("Huynh–Feldt stima l’epsilon"))
        choose(dialog, FIELD, "Lower bound")
        self.assertTrue(dialog.sphericity.note.text().startswith("Il limite inferiore usa"))

    def test_the_note_follows_the_choice(self):
        dialog = self.dialog(current=(METHOD, recipe("None")))
        dialog.tabs.setCurrentIndex(dialog.tabs.count() - 1)  # the choice is on the Options page
        self.app.processEvents()
        starts = {"None": "No correction", "Geisser–Greenhouse": "Each effect gets its own Greenhouse–Geisser",
                  "Huynh-Feldt": "Huynh–Feldt estimates the epsilon", "Lower bound": "Lower bound uses the smallest"}
        for value, start in starts.items():
            choose(dialog, FIELD, value)
            self.assertTrue(dialog.sphericity.note.text().startswith(start), (value, dialog.sphericity.note.text()))
            self.assertTrue(dialog.sphericity.note.isVisible())
        self.assertNotIn("Huynh–Feldt correction", dialog.sphericity.note.text())
        choose(dialog, FIELD, "Geisser–Greenhouse")
        self.assertNotIn("no Huynh–Feldt", dialog.sphericity.note.text())

    def test_the_keyboard_reaches_and_changes_the_choice(self):
        dialog = self.dialog(current=(METHOD, recipe("None")))
        control = dialog.controls[FIELD][1]
        control.setFocus()
        seen = []
        for _ in range(3):
            QTest.keyClick(control, Qt.Key.Key_Down)
            seen.append(control.currentData())
        self.assertEqual(seen, CHOICES[1:])
        QTest.keyClick(control, Qt.Key.Key_Up)
        self.assertEqual(control.currentData(), "Huynh-Feldt")
        # The choice is in the tab chain of the Options page, after the Variables page controls.
        self.assertIs(dialog.rows[FIELD][1], control)
        self.assertTrue(control.focusPolicy() & Qt.FocusPolicy.TabFocus)

    def test_a_saved_one_way_recipe_keeps_its_value_and_is_named_as_saved(self):
        one = recipe(LEGACY, [VISIT])
        dialog = self.dialog(FRAME.query(f"{CONDITION} == 'Condition 1'"), current=(METHOD, one))
        control = dialog.controls[FIELD][1]
        self.assertEqual(control.currentData(), LEGACY)
        self.assertEqual(control.count(), 5)
        self.assertEqual(control.currentText(), "Geisser–Greenhouse (one-way, saved recipe)")
        self.assertTrue(dialog.sphericity.note.text().startswith("Saved recipe"))
        dialog.accept()
        self.assertEqual(dialog.result[1][FIELD], LEGACY)
        set_language("it")
        self.assertEqual(self.dialog(current=(METHOD, one)).controls[FIELD][1].currentText(),
                         "Geisser–Greenhouse (una via, ricetta salvata)")
        # A recipe without the choice offers four choices only, and a new dialog starts with None.
        self.assertEqual(self.dialog().controls[FIELD][1].count(), 4)
        self.assertEqual(self.dialog().controls[FIELD][1].currentData(), "None")

    def test_a_design_problem_is_refused_on_its_field_before_any_worker(self):
        broken = FRAME.drop(index=1)
        for language, start in (("en", "Subject S1 has no measurement"), ("it", "Soggetto: Il soggetto S1 non ha")):
            set_language(language)
            dialog = self.dialog(broken, current=(METHOD, recipe("Huynh-Feldt")))
            with mock.patch.object(rm_sphericity, "effect_epsilon", side_effect=AssertionError("fit in the dialog")):
                dialog.accept()
            self.app.processEvents()
            self.assertIsNone(dialog.result, language)
            self.assertTrue(dialog.banner.isVisible())
            self.assertTrue(dialog.banner.text().startswith(start), (language, dialog.banner.text()))
            self.assertIs(self.app.focusWidget(), dialog.controls["Subject"][1], language)
            # The same table is accepted without correction, where the engine keeps its plain value errors.
            choose(dialog, FIELD, "None")
            dialog.accept()
            self.assertIsNotNone(dialog.result, language)

    def test_the_other_field_errors_name_their_field_in_both_languages(self):
        cases = (
            ("legacy with two factors", FRAME, recipe(LEGACY), FIELD, "applies to a single Factor",
             "vale per un solo Fattore"),
            ("one level", FRAME.assign(**{VISIT: "same"}), recipe("Lower bound"), "Factors",
             "needs at least two levels", "richiede almeno due livelli"),
            ("blank response", FRAME.assign(Response=FRAME["Response"].where(FRAME.index != 5)), recipe("Huynh-Feldt"),
             "Response", "nothing is imputed", "non si imputa nulla"))
        for label, frame, current, field, english, italian in cases:
            for language, text in (("en", english), ("it", italian)):
                with self.subTest(case=label, language=language):
                    set_language(language)
                    dialog = self.dialog(frame, current=(METHOD, current))
                    dialog.accept()
                    self.app.processEvents()
                    self.assertIsNone(dialog.result)
                    self.assertIn(text, dialog.banner.text())
                    self.assertIs(self.app.focusWidget(), dialog.controls[field][1])

    def test_an_engine_error_reopens_on_the_field_in_the_active_language(self):
        message = ("Subject S9 has 2 measurements for Visit = Visit 1; Condition = Condition 1. Each subject needs "
                   "exactly one Response in each of the 9 combinations of Visit × Condition.")
        dialog = self.dialog(error=message, error_field="Subject", current=(METHOD, recipe()))
        self.assertEqual(dialog.banner.text(), message)
        self.assertIs(self.app.focusWidget(), dialog.controls["Subject"][1])
        set_language("it")
        shown = self.dialog(error=message, error_field="Subject", current=(METHOD, recipe()))
        self.assertTrue(shown.banner.text().startswith("Soggetto: Il soggetto S9 ha 2 misure per"), shown.banner.text())

    def test_dialog_fits_1024_by_768_in_light_and_dark_with_the_longest_note(self):
        from trama_qt import theme
        try:
            for dark in (False, True):
                theme.apply(self.app, dark=dark)
                for language in ("en", "it"):
                    set_language(language)
                    dialog = self.dialog(current=(METHOD, recipe("None")))
                    for value in CHOICES:
                        choose(dialog, FIELD, value)
                        hint = dialog.minimumSizeHint()
                        self.assertLessEqual(hint.width(), 1024, (dark, language, value))
                        self.assertLessEqual(hint.height(), 768, (dark, language, value))
                    dialog.resize(1024, 700)
                    self.app.processEvents()
                    self.assertTrue(dialog.run_button.isVisible())
                    note = dialog.sphericity.note
                    self.assertTrue(note.wordWrap())
                    self.assertLessEqual(note.sizeHint().width(), 1024)
        finally:
            theme.apply(self.app)


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class SphericityWindowTests(unittest.TestCase):
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
        self.errors = []
        self.window.error = lambda error: self.errors.append(str(error))
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
        set_language("en")

    def wait(self, timeout=120):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job, "calculation still running")

    def open_table(self, frame=FRAME):
        path = self.folder / f"{TITLE}.csv"
        frame.to_csv(path, index=False)
        self.window.open_path(path)
        self.app.processEvents()
        return TITLE

    def calculate(self, options, title=TITLE):
        from trama_qt.analysis_dialog import AnalysisDialog
        project = self.window.project
        frame = project.tables[title].frame(mask_excluded=True)
        candidate = project.candidate(title, METHOD, options)
        reopened = []  # a failed calculation reopens the dialog: never let a test wait on it
        refuse = lambda dialog: reopened.append(dialog) or QDialog.DialogCode.Rejected  # noqa: E731
        with mock.patch.object(AnalysisDialog, "exec", refuse):
            self.window.calculate_candidate(candidate, frame, None)
            self.wait()
        return len(project.runs) - 1, reopened

    def through_dialog(self, command, values):
        from trama_qt.analysis_dialog import AnalysisDialog

        def exec_(dialog):
            for name, value in values.items():
                choose(dialog, name, value)
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

        with mock.patch.object(AnalysisDialog, "exec", exec_):
            command()

    def export_csv(self, name):
        target = self.folder / f"{name}.csv"
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
            self.window.export()
        self.assertTrue(target.exists() and target.stat().st_size > 0, name)
        with open(target, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_run_read_export_edit_save_and_reopen_with_each_correction(self):
        window = self.window
        title = self.open_table()
        for correction in ("Huynh-Feldt", "Lower bound"):
            with self.subTest(correction=correction):
                index, reopened = self.calculate(recipe(correction))
                self.assertEqual(reopened, [])
                run = window.project.runs[index]
                self.assertIsNone(run.calculation_error)
                expected = analyse(METHOD, FRAME, recipe(correction)).tables
                self.assertEqual(list(run.result.tables), ["ANOVA", "Sphericity"])
                for name in expected:
                    pd.testing.assert_frame_equal(run.result.tables[name], expected[name], obj=name)
                sheet = run.result.tables["Sphericity"]
                self.assertEqual(list(sheet), rm_sphericity.ESTIMATED_COLUMNS)
                self.assertEqual(window.project.tables[title].analyses[-1], (METHOD, recipe(correction)))

                # The result sheets and their CSV carry the corrected degrees of freedom and p.
                window.open_sheet(("result", index))
                names = list(run.result.tables)
                window.result_tabs.setCurrentIndex(names.index("Sphericity"))
                rows = self.export_csv(f"sphericity-{correction}")
                self.assertEqual([row["Term"] for row in rows], list(sheet["Term"]))
                for row, (_, values) in zip(rows, sheet.iterrows(), strict=True):
                    for column in ("Applied epsilon", "F df1", "F df2", "p"):
                        np.testing.assert_allclose(float(row[column]), values[column], rtol=1e-9, err_msg=column)
                window.result_tabs.setCurrentIndex(names.index("ANOVA"))
                anova_rows = self.export_csv(f"anova-{correction}")
                self.assertEqual(list(anova_rows[0])[:1], ["Term"])
                corrected = [row for row in anova_rows if row["Term"] == VISIT][0]
                np.testing.assert_allclose(float(corrected["F df1"]), sheet.set_index("Term").loc[VISIT, "F df1"],
                                           rtol=1e-9)

        # Edit a measurement: every sheet is recalculated, the corrected p changes.
        index, _ = self.calculate(recipe("Huynh-Feldt"))
        before = window.project.runs[index].result.tables["Sphericity"].copy()
        window.open_sheet(("data", title))
        column = list(window.project.tables[title].raw.columns).index("Response")
        window.edit_cell(title, 4, column, "80")
        self.wait()
        run = window.project.runs[index]
        edited = FRAME.copy()
        edited.loc[4, "Response"] = 80
        fresh = analyse(METHOD, edited, recipe("Huynh-Feldt")).tables
        pd.testing.assert_frame_equal(run.result.tables["Sphericity"], fresh["Sphericity"])
        self.assertFalse(before["p"].equals(run.result.tables["Sphericity"]["p"]))

        # Save, close, reopen: recipe and sheets come back, in the other language too.
        kept = {name: frame.copy() for name, frame in run.result.tables.items()}
        saved = self.folder / "misure.alab"
        window.project.save(saved)
        set_language("it")
        self.assertTrue(window.close_project())
        window.open_path(saved)
        self.app.processEvents()
        window.open_sheet(("result", index))
        self.wait()
        reopened_run = window.project.runs[index]
        self.assertEqual(reopened_run.options, recipe("Huynh-Feldt"))
        for name in kept:
            pd.testing.assert_frame_equal(reopened_run.result.tables[name], kept[name], obj=name)
        self.assertEqual(self.errors, [])

    def test_the_dialog_switches_a_calculated_analysis_between_the_corrections(self):
        window = self.window
        self.open_table()
        index, _ = self.calculate(recipe("None"))
        self.assertEqual(list(window.project.runs[index].result.tables), ["ANOVA"])
        window.open_sheet(("result", index))
        for correction in ("Geisser–Greenhouse", "Huynh-Feldt", "Lower bound", "None"):
            self.through_dialog(window.change_parameters, {FIELD: correction})
            self.wait()
            run = window.project.runs[index]
            self.assertEqual(run.options[FIELD], correction)
            expected = analyse(METHOD, FRAME, recipe(correction)).tables
            self.assertEqual(list(run.result.tables), list(expected), correction)
            pd.testing.assert_frame_equal(run.result.tables["ANOVA"], expected["ANOVA"])
        self.assertEqual(self.errors, [])

    def test_a_design_error_from_the_worker_reopens_the_dialog_on_the_field(self):
        window = self.window
        self.open_table(FRAME.drop(index=1))
        for language, start in (("en", "Subject S1 has no measurement"), ("it", "Soggetto: Il soggetto S1 non ha")):
            set_language(language)
            _, reopened = self.calculate(recipe("Lower bound"))
            self.assertEqual(len(reopened), 1, language)
            self.assertTrue(reopened[0].banner.text().startswith(start), (language, reopened[0].banner.text()))
            self.assertEqual(reopened[0].error_field, "Subject")
        self.assertEqual(window.job, None)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
