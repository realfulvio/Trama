"""Worksheet joins in the Classica window and its calculation worker."""

from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

import pandas as pd

from analisi import worksheet_join as wj
from analisi.analysis_chain import ResultSource
from analisi.graph_language_smoke import drive_mapped_dialog
from tests.test_graph_i18n import TkCase


class JoinClassicaTests(TkCase):
    def setUp(self):
        from tramastat import App

        self.root.deiconify()
        self.app = App(self.root, standard_only=True)
        self.addCleanup(self.root.withdraw)
        self.addCleanup(self.app.worker.shutdown)
        self.addCleanup(self.app._clear, "")
        self.errors = []
        self.app.error = self.errors.append
        self.left = "Campioni $"
        self.right = "Misure à"
        self.app._add_tables({
            self.left: pd.DataFrame({"ID": [1, 2, 3], "X": [1, 2, 3]}),
            self.right: pd.DataFrame({"Key": [1, 2, 3], "Y": [10, 20, 30]}),
        })
        self.app.show("data", self.left)

    def wait(self):
        deadline = time.monotonic() + 10

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
                    dialog.destroy()

        drive_mapped_dialog(self.root, AnalysisDialog, verify, failures)
        launch()
        if failures:
            raise failures[0]

    def create_join(self):
        def create(dialog):
            self.assertIn(wj.METHOD, dialog.method_by_item.values())
            dialog.ok()

        self.drive(create, lambda: self.app.choose_analysis(wj.METHOD))
        self.wait()
        return self.app.runs[0]

    def test_edit_either_worksheet_updates_the_join_and_its_child(self):
        from tramastat import Run

        run = self.create_join()
        self.assertEqual(run.options[wj.RIGHT_SHEET], self.right)
        self.assertEqual(run.result.tables[wj.JOINED]["Y"].tolist(), [10, 20, 30])
        regression = Run("Linear regression", self.left, {"X": "X", "Y": "Y"},
                         source=ResultSource(run.uid, wj.JOINED))
        self.app.start_analysis(regression, self.app.input_frame(regression))
        self.wait()
        self.app.show("data", self.right)
        self.app.edit_cell(2, 1, "50")
        self.wait()
        self.assertEqual(run.result.tables[wj.JOINED]["Y"].tolist(), [10, 20, 50])
        self.assertAlmostEqual(regression.result.tables["Regression"].loc["Slope", "Value"], 20)
        self.app.show("data", self.left)
        self.app.edit_cell(2, 1, "5")
        self.wait()
        self.assertAlmostEqual(regression.result.tables["Regression"].loc["Slope", "Value"], 10)

        with TemporaryDirectory() as output:
            from analisi.data import save_project

            path = Path(output) / "joined.alab"
            save_project(path, self.app.tables)
            self.app.import_file(path)
            self.app.recalculate(1)
            self.wait()
            self.assertEqual(self.app.runs[0].options[wj.RIGHT_SHEET], self.right)
            self.assertAlmostEqual(self.app.runs[1].result.tables["Regression"].loc["Slope", "Value"], 10)

    def test_keep_missing_source_until_repaired_in_the_real_dialog(self):
        run = self.create_join()
        run.options[wj.RIGHT_SHEET] = "Foglio mancante $"
        self.app.show("result", 0)

        def repair(dialog):
            self.assertEqual(dialog.join.sheet.get(), "Foglio mancante $")
            with patch("tramastat.messagebox.showerror") as warning:
                self.assertFalse(dialog.validate())
            warning.assert_called_once()
            self.assertIs(dialog.initial_focus, dialog.join.sheet)
            dialog.join.sheet.current(0)
            dialog.join.sheet.event_generate("<<ComboboxSelected>>")
            dialog.ok()

        self.drive(repair, self.app.edit_analysis)
        self.wait()
        self.assertEqual(self.app.runs[0].options[wj.RIGHT_SHEET], self.right)
        self.assertEqual(self.app.runs[0].result.tables[wj.JOINED]["Y"].tolist(), [10, 20, 30])

    def test_locale_and_error_focus_for_the_second_key_pair(self):
        self.use("it")
        run = self.create_join()
        self.app.show("result", 0)

        def edit(dialog):
            editor = dialog.join
            self.assertEqual(editor.kind.get(), "Da sinistra")
            editor.add_pair()
            editor.pairs[1][2].set("Key")
            with patch("tramastat.messagebox.showerror") as warning:
                self.assertFalse(dialog.validate())
            self.assertIn("Key", warning.call_args.args[1])
            self.assertIs(dialog.initial_focus, editor.pairs[1][2])
            editor.pairs[1][3].invoke()
            editor.kind.current(2)
            self.assertTrue(dialog.validate())
            self.assertEqual(dialog.result[1][wj.JOIN_TYPE], wj.FULL)
            dialog.cancel()

        self.drive(edit, self.app.edit_analysis)
        self.assertIs(self.app.runs[0], run)
        self.assertEqual(run.options[wj.JOIN_TYPE], wj.DEFAULT_TYPE)

    def test_right_worksheet_conflict_keeps_results_stale_until_undo(self):
        run = self.create_join()
        complete = run.result
        self.app.show("data", self.right)
        self.app.edit_cell(2, 0, "2")
        self.wait()
        self.assertIs(run.result, complete)
        self.assertIn("The right worksheet repeats a key", self.app.stale_calculation_note(("result", 0)))
        self.app.apply_worksheet_history()
        self.wait()
        self.assertIsNone(self.app.stale_calculation_note(("result", 0)))
        self.assertEqual(run.result.tables[wj.JOINED]["Y"].tolist(), [10, 20, 30])
