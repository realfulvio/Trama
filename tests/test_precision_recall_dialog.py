"""Precision–recall creation and recipe editing through the Classica dialog."""

from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

import pandas as pd

from analisi import precision_recall as pr
from analisi.graph_language_smoke import drive_mapped_dialog
from tests.test_graph_i18n import TkCase


class PrecisionRecallDialogTests(TkCase):
    frame = pd.DataFrame({"Event": [" 01", "1", " 01"], "Signal A": [3, 2, 1], "Signal B": [1, 3, 2]})

    def drive(self, action, launch=None, current=None):
        from tramastat import AnalysisDialog

        errors = []

        def interact(dialog):
            try:
                action(dialog)
            except Exception as error:
                errors.append(error)
            finally:
                if dialog.winfo_exists():
                    dialog.destroy()

        drive_mapped_dialog(self.root, AnalysisDialog, interact, errors)
        result = launch() if launch else AnalysisDialog(self.root, self.frame, current=current).result
        if errors:
            self.fail(str(errors[0]))
        return result

    def test_find_and_run_in_italian_with_literal_labels_and_exact_seed(self):
        self.use("it")

        def create(dialog):
            dialog.query.set("precisione")
            self.assertIn(pr.METHOD, dialog.method_by_item.values())
            item = next(item for item, name in dialog.method_by_item.items() if name == pr.METHOD)
            dialog.methods.selection_set(item)
            dialog.select_method()
            self.assertEqual(dialog.controls[pr.OUTCOME][1].get(), "Event")
            self.assertEqual(dialog.controls[pr.SCORE][1].get(), "Signal A")
            for name in (pr.SECOND_DIRECTION, *pr.BOOTSTRAP_FIELDS):
                self.assertEqual(dialog.field_rows[name][1].winfo_manager(), "")
            dialog.controls[pr.POSITIVE][1].set(" 01")
            dialog.controls[pr.NEGATIVE][1].set("1")
            dialog.controls[pr.SECOND_SCORE][1].set("Signal B")
            dialog.controls[pr.BOOTSTRAP][1].set(True)
            for name in (pr.SECOND_DIRECTION, *pr.BOOTSTRAP_FIELDS):
                self.assertEqual(dialog.field_rows[name][1].winfo_manager(), "grid")
            direction = dialog.field_rows[pr.SECOND_DIRECTION][1]
            direction.current(1)
            direction.event_generate("<<ComboboxSelected>>")
            dialog.controls[pr.REPLICATES][1].set("198")
            with patch("tramastat.messagebox.showerror") as warning:
                self.assertFalse(dialog.validate())
            self.assertIn("10.000", warning.call_args.args[1])
            self.assertEqual(dialog.fields.select(), str(dialog.field_rows[pr.REPLICATES][1].master))
            self.assertIs(dialog.initial_focus, dialog.field_rows[pr.REPLICATES][1])
            dialog.controls[pr.REPLICATES][1].set("199")
            dialog.controls[pr.LEVEL][1].set("90,5")
            dialog.controls[pr.SEED][1].set(str(2**64 - 1))
            self.assertTrue(dialog.validate())

        method, options = self.drive(create)
        self.assertEqual(method, pr.METHOD)
        self.assertEqual(options, {
            "Outcome": "Event", "Positive": " 01", "Negative": "1", "Score": "Signal A",
            "Second score": "Signal B", "Direction": "Higher is positive", "Second direction": "Lower is positive",
            "Bootstrap CI": True, "Confidence level (%)": 90.5, "Bootstrap replicates": 199,
            "Bootstrap seed": 2**64 - 1,
        })
        result = pr.analyse(self.frame, options)
        first, second = result.tables["Summary"]["Average precision"]
        self.assertAlmostEqual(first, 5 / 6)
        self.assertEqual(second, 1.0)

    def test_saved_recipe_can_switch_off_bootstrap_and_second_score(self):
        options = {
            pr.OUTCOME: "Event", pr.POSITIVE: " 01", pr.NEGATIVE: "1", pr.SCORE: "Signal A",
            pr.SECOND_SCORE: "Signal B", pr.SECOND_DIRECTION: pr.LOWER,
            pr.BOOTSTRAP: True, pr.SEED: 2**64 - 1,
        }

        def edit(dialog):
            self.assertIn(pr.METHOD, dialog.method_by_item.values())
            self.assertEqual(dialog.controls[pr.SEED][1].get(), str(2**64 - 1))
            dialog.controls[pr.SECOND_SCORE][1].set("")
            dialog.controls[pr.BOOTSTRAP][1].set(False)
            self.assertTrue(dialog.validate())

        method, edited = self.drive(edit, current=(pr.METHOD, options))
        self.assertEqual(method, pr.METHOD)
        self.assertIsNone(edited[pr.SECOND_SCORE])
        self.assertFalse(edited[pr.BOOTSTRAP])
        self.assertTrue(edited.keys().isdisjoint((pr.SECOND_DIRECTION, *pr.BOOTSTRAP_FIELDS)))
        self.assertEqual(options[pr.SECOND_SCORE], "Signal B")

    def test_create_edit_save_and_recalculate_through_the_classica_window(self):
        from tramastat import App

        self.root.deiconify()
        app = App(self.root, standard_only=True)
        self.addCleanup(self.root.withdraw)
        self.addCleanup(app.worker.shutdown)
        self.addCleanup(app._clear, "")
        app._add_tables({"Experiment": self.frame})
        errors = []
        app.error = errors.append

        def wait_for_result():
            deadline = time.monotonic() + 10

            def poll():
                if app.pending is None or time.monotonic() >= deadline:
                    self.root.quit()
                else:
                    self.root.after(10, poll)

            self.root.after(0, poll)
            self.root.mainloop()
            self.assertIsNone(app.pending)
            self.assertFalse(errors, errors)
            result = app.runs[0].result
            self.assertIsNotNone(result)
            return result

        def create(dialog):
            dialog.controls[pr.POSITIVE][1].set(" 01")
            dialog.controls[pr.NEGATIVE][1].set("1")
            dialog.ok()

        self.drive(create, launch=lambda: app.choose_analysis(pr.METHOD))
        self.assertAlmostEqual(wait_for_result().tables["Summary"]["Average precision"][0], 5 / 6)
        uid = app.runs[0].uid
        app.show("graph", 0)

        def edit(dialog):
            dialog.controls[pr.SCORE][1].set("Signal B")
            dialog.controls[pr.DIRECTION][1].set(pr.LOWER)
            dialog.ok()

        self.drive(edit, launch=app.edit_analysis)
        self.assertEqual(wait_for_result().tables["Summary"]["Average precision"][0], 1.0)
        self.assertEqual(app.runs[0].options[pr.DIRECTION], pr.LOWER)
        self.assertEqual(app.runs[0].uid, uid)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "scores.alab"
            with patch("tramastat.filedialog.asksaveasfilename", return_value=str(path)):
                self.assertTrue(app.save())
            copied = path.with_name("reopen.alab")
            copied.write_bytes(path.read_bytes())
            self.assertTrue(app.open_document(copied))
            app.open_sheet(("result", 0))
            result = wait_for_result()
        self.assertEqual(result.tables["Summary"]["Average precision"][0], 1.0)
        self.assertEqual(app.runs[0].options[pr.DIRECTION], pr.LOWER)
        self.assertEqual(app.runs[0].options[pr.POSITIVE], " 01")
