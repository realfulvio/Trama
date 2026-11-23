"""Intraclass correlation through the Classica analysis dialog."""

from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

import pandas as pd

from analisi import icc
from analisi.graph_language_smoke import drive_mapped_dialog
from tests.test_graph_i18n import TkCase


class IccDialogTests(TkCase):
    a, b, c = "Rater A", "Rater B", "Rater C"
    frame = pd.DataFrame({
        "Subject ID": ["s1", "s2", "s3", "s4"],
        a: [1, 2, 4, 8], b: [3, 4, 6, 10], c: [5, 6, 8, 12],
    })

    def drive(self, action, launch=None, current=None, frame=None):
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
        data = self.frame if frame is None else frame
        result = launch() if launch else AnalysisDialog(self.root, data, current=current).result
        if errors:
            raise errors[0]
        return result

    def test_create_in_italian_and_keep_the_order_of_selection(self):
        self.use("it")

        def create(dialog):
            dialog.query.set("intraclasse")
            self.assertIn(icc.METHOD, dialog.method_by_item.values())
            item = next(key for key, name in dialog.method_by_item.items() if name == icc.METHOD)
            dialog.methods.selection_set(item)
            dialog.select_method()
            raters = dialog.controls[icc.RATERS][1]
            columns = raters.get(0, "end")
            for name in (self.c, self.a, self.b):
                raters.selection_set(columns.index(name))
                raters.event_generate("<<ListboxSelect>>")
            raters.selection_clear(columns.index(self.a))
            raters.event_generate("<<ListboxSelect>>")
            raters.selection_set(columns.index(self.a))
            raters.event_generate("<<ListboxSelect>>")
            self.assertIn(f"{self.c} → {self.b} → {self.a}", dialog.icc_summary.cget("text"))
            dialog.controls[icc.SUBJECT][1].set("Subject ID")
            dialog.controls[icc.DEFINITION][1].set(icc.CONSISTENCY)
            self.assertEqual(dialog.field_rows[icc.REPLICATES][1].winfo_manager(), "")
            dialog.controls[icc.BOOTSTRAP][1].set(True)
            self.assertEqual(dialog.field_rows[icc.REPLICATES][1].winfo_manager(), "grid")
            dialog.controls[icc.REPLICATES][1].set("5001")
            with patch("tramastat.messagebox.showerror") as warning:
                self.assertFalse(dialog.validate())
            self.assertIn("5.000", warning.call_args.args[1])
            self.assertIs(dialog.initial_focus, dialog.field_rows[icc.REPLICATES][1])
            dialog.controls[icc.REPLICATES][1].set("199")
            dialog.controls[icc.LEVEL][1].set("90,5")
            dialog.controls[icc.SEED][1].set(str(2**64 - 1))
            self.assertTrue(dialog.validate())

        method, options = self.drive(create)
        self.assertEqual(method, icc.METHOD)
        self.assertEqual(options, {
            "Raters": [self.c, self.b, self.a], "Subject": "Subject ID", "Definition": "Consistency",
            "Unit": "Single measure", "Bootstrap CI": True, "Confidence level (%)": 90.5,
            "Bootstrap replicates": 199, "Seed": 2**64 - 1, "Profile graph": True,
        })
        result = icc.analyse(self.frame, options)
        self.assertEqual(result.tables["ICC"]["Estimate"][0], 1.0)
        self.assertEqual([label.get_text() for label in result.figure.axes[0].get_xticklabels()],
                         [self.c, self.b, self.a])

    def test_saved_rater_order_survives_edit_without_bootstrap(self):
        options = {icc.RATERS: [self.c, self.a], icc.BOOTSTRAP: True, icc.SEED: 2**64 - 1}

        def edit(dialog):
            self.assertIn(icc.METHOD, dialog.method_by_item.values())
            self.assertEqual(dialog.controls[icc.SEED][1].get(), str(2**64 - 1))
            dialog.controls[icc.BOOTSTRAP][1].set(False)
            self.assertTrue(dialog.validate())

        method, edited = self.drive(edit, current=(icc.METHOD, options))
        self.assertEqual(method, icc.METHOD)
        self.assertEqual(edited[icc.RATERS], [self.c, self.a])
        self.assertFalse(edited[icc.BOOTSTRAP])
        self.assertTrue(edited.keys().isdisjoint(icc.BOOTSTRAP_FIELDS))

    def test_long_rater_summary_can_be_scrolled_to_the_end(self):
        names = [f"Rater {index:02} — laboratory method and measurement unit" for index in range(64)]
        frame = pd.DataFrame({name: [1, 2, 4, 8] for name in names})

        def verify(dialog):
            dialog.update_idletasks()
            summary = dialog.icc_summary
            self.assertIn(names[-1], summary.cget("text"))
            canvas = summary.master.master
            self.assertTrue(hasattr(canvas, "yview"), "The long ICC summary needs a scrollable page")
            self.assertLess(canvas.yview()[1], 1)
            canvas.yview_moveto(1)
            dialog.update_idletasks()
            self.assertEqual(canvas.yview()[1], 1)
            self.assertLessEqual(summary.winfo_rooty() + summary.winfo_height(),
                                 canvas.winfo_rooty() + canvas.winfo_height())

        self.drive(verify, current=(icc.METHOD, {icc.RATERS: names}), frame=frame)

    def test_create_edit_and_reopen_from_the_classica_window(self):
        from tramastat import App

        self.root.deiconify()
        app = App(self.root, standard_only=True)
        self.addCleanup(self.root.withdraw)
        self.addCleanup(app.worker.shutdown)
        self.addCleanup(app._clear, "")
        app._add_tables({"Experiment": self.frame})
        errors = []
        app.error = errors.append

        def result():
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
            run = app.runs[0]
            self.assertIsNotNone(run.result)
            return run

        def create(dialog):
            raters = dialog.controls[icc.RATERS][1]
            columns = raters.get(0, "end")
            for name in (self.c, self.a):
                raters.selection_set(columns.index(name))
                raters.event_generate("<<ListboxSelect>>")
            dialog.ok()

        self.drive(create, launch=lambda: app.choose_analysis(icc.METHOD))
        first = result()
        self.assertLess(first.result.tables["ICC"]["Estimate"][0], 1.0)
        self.assertEqual(first.options[icc.RATERS], [self.c, self.a])
        app.show("graph", 0)

        def edit(dialog):
            dialog.controls[icc.DEFINITION][1].set(icc.CONSISTENCY)
            dialog.ok()

        self.drive(edit, launch=app.edit_analysis)
        edited = result()
        self.assertEqual(edited.uid, first.uid)
        self.assertEqual(edited.result.tables["ICC"]["Estimate"][0], 1.0)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "ratings.alab"
            with patch("tramastat.filedialog.asksaveasfilename", return_value=str(path)):
                self.assertTrue(app.save())
            copied = path.with_name("reopen.alab")
            copied.write_bytes(path.read_bytes())
            self.assertTrue(app.open_document(copied))
            app.open_sheet(("graph", 0))
            reopened = result()
        self.assertEqual(reopened.options[icc.RATERS], [self.c, self.a])
        self.assertEqual(reopened.options[icc.DEFINITION], icc.CONSISTENCY)
        self.assertEqual(reopened.result.tables["ICC"]["Estimate"][0], 1.0)
        self.assertEqual([label.get_text() for label in reopened.result.figure.axes[0].get_xticklabels()],
                         [self.c, self.a])
