"""K-means stability through Classica's real dialog and calculation worker."""

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from unittest.mock import patch

import pandas as pd

from analisi import kmeans_stability as ks
from analisi import kmeans_options
from analisi.data import save_project
from analisi.graph_language_smoke import drive_mapped_dialog
from tests.test_graph_i18n import TkCase

DATA = Path(__file__).parent / "data" / "kmeans_stability" / "separated.csv"
TITLE = "Tre gruppi $"


class StabilityClassicaTests(TkCase):
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

    def test_budget_and_algorithm_fields_are_checked_before_the_worker(self):
        self.use("it")

        def check(dialog):
            self.assertIn(ks.METHOD, dialog.method_by_item.values())
            algorithm = dialog.controls[ks.ALGORITHM][1]
            limit = dialog.field_rows[ks.MAX_ITERATIONS][1]
            self.assertEqual(limit.winfo_manager(), "")
            algorithm.set(kmeans_options.HARTIGAN)
            self.assertEqual(limit.winfo_manager(), "grid")
            algorithm.set(kmeans_options.LLOYD)
            self.assertEqual(limit.winfo_manager(), "")
            for field, text in ((ks.RESAMPLES, "2000"), (ks.MAX_K, "3,5"), (ks.MAX_K, "9" * 5000)):
                variable = dialog.controls[field][1]
                before = variable.get()
                variable.set(text)
                with patch("tramastat.messagebox.showerror") as warning:
                    self.assertFalse(dialog.validate())
                self.assertIs(dialog.initial_focus, dialog.field_rows[field][1])
                caption = "ricampionamenti" if field == ks.RESAMPLES else "k massimo"
                self.assertIn(caption, warning.call_args.args[1].casefold())
                variable.set(before)
            dialog.controls[ks.RESAMPLES][1].set(" 8 ")
            dialog.controls[ks.FRACTION][1].set("82,5")
            self.assertTrue(dialog.validate())
            options = dialog.result[1]
            self.assertEqual(options[ks.FRACTION], 82.5)
            self.assertEqual(options[ks.RESAMPLES], 8)
            self.assertNotIn(ks.MAX_ITERATIONS, options)
            dialog.result = None

        with patch.object(ks.engine, "kmeans", side_effect=AssertionError("Fit in the analysis dialog")):
            self.drive(check, lambda: self.app.choose_analysis(ks.METHOD))

    def create(self):
        def run(dialog):
            dialog.controls[ks.MAX_K][1].set("3")
            dialog.controls[ks.RESAMPLES][1].set("8")
            dialog.controls[ks.REPORT_K][1].set("3")
            dialog.controls[ks.COASSIGNMENT][1].set(True)
            dialog.ok()

        self.drive(run, lambda: self.app.choose_analysis(ks.METHOD))
        self.wait()
        return self.app.runs[0]

    def test_save_reload_and_undo_after_a_failed_recalculation(self):
        run = self.create()
        expected = ks.analysis(self.app.tables[TITLE].frame(mask_excluded=True), run.options)
        self.assertEqual(list(run.result.tables), list(expected.tables))
        for name, table in expected.tables.items():
            pd.testing.assert_frame_equal(run.result.tables[name], table)

        with TemporaryDirectory() as output:
            path = Path(output) / "stability.alab"
            save_project(path, self.app.tables)
            self.app.import_file(path)
            self.app.recalculate(0)
            self.wait()
        run = self.app.runs[0]
        self.assertEqual(run.options[ks.ALGORITHM], kmeans_options.LLOYD)
        pd.testing.assert_frame_equal(run.result.tables[ks.COASSIGN_SHEET], expected.tables[ks.COASSIGN_SHEET])
        previous = run.result
        self.app.show("data", TITLE)
        self.app.current_grid.select_block(0, 0, 0, 0)
        with patch.object(self.root, "clipboard_get", return_value="\n".join(["1"] * len(self.frame))):
            self.app.paste_selection()
        self.wait()
        self.assertIs(run.result, previous)
        self.assertIn("is constant", self.app.stale_calculation_note(("result", 0)))
        self.app.apply_worksheet_history()
        self.wait()
        self.assertIsNone(self.app.stale_calculation_note(("result", 0)))
        pd.testing.assert_frame_equal(run.result.tables[ks.SUMMARY], expected.tables[ks.SUMMARY])

    def test_progress_and_cancel_leave_a_confirmed_analysis_untouched(self):
        run = self.create()
        previous = run.result
        started = threading.Event()

        def cancellable(_frame, _options, *, cancel, progress):
            progress(1, 1200)
            started.set()
            if not cancel.wait(10):
                raise AssertionError("Cancellation did not reach the worker")
            ks.check_cancel(cancel)

        def edit(dialog):
            dialog.controls[ks.RESAMPLES][1].set("75")
            dialog.ok()

        self.app.show("result", 0)
        with patch.object(ks, "analysis", side_effect=cancellable):
            self.drive(edit, self.app.edit_analysis)
            self.assertTrue(started.wait(5))
            self.assertEqual(self.app.calculation.progress(), (1, 1200))
            self.assertEqual(self.app.cancel_button.winfo_manager(), "pack")
            self.app.cancel_button.invoke()
            self.wait()
        self.assertIs(self.app.runs[0], run)
        self.assertIs(run.result, previous)
        self.assertEqual(run.options[ks.RESAMPLES], 8)
