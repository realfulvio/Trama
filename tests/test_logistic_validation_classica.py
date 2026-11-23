"""Logistic cross-validation through Classica's real dialog and worker."""

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from unittest.mock import patch

import pandas as pd

from analisi import logistic_validation as lv
from analisi.data import save_project
from analisi.graph_language_smoke import drive_mapped_dialog
from tests.test_graph_i18n import TkCase

DATA = Path(__file__).parent / "data" / "logistic_validation" / "logistic.csv"
TITLE = "Validazione $"


class LogisticValidationClassicaTests(TkCase):
    def setUp(self):
        from tramastat import App

        self.root.deiconify()
        self.frame = pd.read_csv(DATA)
        self.app = App(self.root, standard_only=True)
        self.addCleanup(self.root.withdraw)
        self.addCleanup(self.app.worker.shutdown)
        self.addCleanup(self.app._clear, "")
        self.errors = []
        self.app.error = self.errors.append
        self.app._add_tables({TITLE: self.frame})
        self.app.show("data", TITLE)

    def wait(self):
        deadline = time.monotonic() + 15

        def poll():
            if self.app.pending is None or time.monotonic() >= deadline:
                self.root.quit()
            else:
                self.root.after(10, poll)

        self.root.after(0, poll)
        self.root.mainloop()
        self.assertIsNone(self.app.pending)
        self.assertFalse(self.errors, self.errors)

    def drive(self, action, launch):
        from tramastat import AnalysisDialog

        failures = []

        def verify(dialog):
            try:
                action(dialog)
            except Exception as error:
                failures.append(error)
            finally:
                if dialog.winfo_exists():
                    dialog.cancel()

        drive_mapped_dialog(self.root, AnalysisDialog, verify, failures)
        launch()
        if failures:
            raise failures[0]

    @staticmethod
    def fill(dialog):
        dialog.controls[lv.RESPONSE][1].set("Outcome")
        predictors = dialog.controls[lv.PREDICTORS][1]
        predictors.selection_clear(0, "end")
        predictors.selection_set(list(predictors.get(0, "end")).index("X"))
        dialog.controls[lv.FOLD_COLUMN][1].set("Fold ID")
        dialog.controls[lv.FOLDS][1].set("2")

    def test_bad_fold_stays_in_the_italian_dialog_and_can_be_corrected(self):
        self.use("it")

        def check(dialog):
            self.fill(dialog)
            dialog.controls[lv.FOLDS][1].set("3")
            with patch("tramastat.messagebox.showerror") as warning:
                self.assertFalse(dialog.validate())
            self.assertIn("fold 3", warning.call_args.args[1].casefold())
            self.assertIs(dialog.initial_focus, dialog.field_rows[lv.FOLD_COLUMN][1])
            dialog.controls[lv.FOLDS][1].set("2")
            dialog.controls[lv.THRESHOLD][1].set("0,25")
            self.assertTrue(dialog.validate())
            options = dialog.result[1]
            self.assertEqual(options, {
                lv.RESPONSE: "Outcome", lv.PREDICTORS: ["X"], lv.CATEGORIES: [],
                lv.FOLDS: 2, lv.SEED: 0, lv.FOLD_COLUMN: "Fold ID", lv.THRESHOLD: 0.25,
                lv.BINS: 10, lv.VIEW: lv.CALIBRATION_VIEW,
            })
            dialog.result = None

        with patch.object(lv, "fit_fold", side_effect=AssertionError("Fit in the analysis dialog")):
            self.drive(check, lambda: self.app.choose_analysis(lv.METHOD))

    def create(self):
        def run(dialog):
            self.fill(dialog)
            dialog.controls[lv.VIEW][1].set(lv.ALL_VIEWS)
            dialog.ok()

        self.drive(run, lambda: self.app.choose_analysis(lv.METHOD))
        self.wait()
        return self.app.runs[0]

    def test_saved_predictions_and_recalculating_after_a_fold_edit(self):
        run = self.create()
        self.assertEqual(len(run.result.figure.axes), 3)
        table = run.result.tables[lv.VALIDATION]
        self.assertAlmostEqual(table["Brier score"].iloc[0], 0.1875)
        self.assertAlmostEqual(table["ROC AUC"].iloc[0], 0.75)
        predictions = run.result.tables[lv.PREDICTIONS].copy(deep=True)

        with TemporaryDirectory() as output:
            path = Path(output) / "validation.alab"
            save_project(path, self.app.tables)
            self.app.import_file(path)
            self.app.recalculate(0)
            self.wait()
        run = self.app.runs[0]
        self.assertEqual(run.options[lv.FOLD_COLUMN], "Fold ID")
        pd.testing.assert_frame_equal(run.result.tables[lv.PREDICTIONS], predictions)

        self.app.show("data", TITLE)
        previous = run.result
        self.app.edit_cell(0, 0, "9")
        self.wait()
        self.assertIs(run.result, previous)
        self.assertIn("fold code 9", self.app.stale_calculation_note(("result", 0)))
        self.app.apply_worksheet_history()
        self.wait()
        self.assertIsNone(self.app.stale_calculation_note(("result", 0)))
        pd.testing.assert_frame_equal(run.result.tables[lv.PREDICTIONS], predictions)

    def test_cancel_between_folds_keeps_the_confirmed_analysis(self):
        run = self.create()
        previous = run.result
        second = threading.Event()
        release = threading.Event()
        original_fit = lv.fit_fold

        def fit(plan, fold):
            if fold == 2:
                second.set()
                if not release.wait(10):
                    raise AssertionError("The test did not release the second fold")
            return original_fit(plan, fold)

        def edit(dialog):
            dialog.controls[lv.THRESHOLD][1].set("0.75")
            dialog.ok()

        self.app.show("result", 0)
        with patch.object(lv, "fit_fold", side_effect=fit):
            try:
                self.drive(edit, self.app.edit_analysis)
                self.assertTrue(second.wait(5))
                self.assertEqual(self.app.calculation.progress(), (1, 2))
                self.assertEqual(self.app.cancel_button.winfo_manager(), "pack")
                self.app.cancel_button.invoke()
            finally:
                release.set()
            self.wait()
        self.assertIs(self.app.runs[0], run)
        self.assertIs(run.result, previous)
        self.assertEqual(run.options[lv.THRESHOLD], 0.5)
