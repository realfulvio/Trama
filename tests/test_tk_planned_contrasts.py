"""Edit planned contrasts in the Classica Multifactor ANOVA dialog."""
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

import pandas as pd

from analisi import anova_planned_contrasts as planned
from analisi.anova_contrasts_tk import ContrastEditor
from analisi.data import save_project
from analisi.graph_language_smoke import drive_mapped_dialog
from analisi.workbench import analyse
from tests.test_anova_terms_dialog import FACTORS, FRAME, METHOD, DialogCase
from tests.test_graph_i18n import TkCase


class ClassicDialogTests(DialogCase):
    def test_editor_is_available_without_adding_keys_to_a_legacy_recipe(self):
        def action(dialog, seen):
            seen["caption"] = dialog.contrast_panel.button.cget("text")
            seen["ok"] = dialog.validate()
            seen["options"] = dialog.result[1]

        seen = self.drive(action)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["caption"], "Planned contrasts…")
        self.assertFalse(set(seen["options"]) & set(planned.KEYS))

    def test_saved_planned_contrasts_survive_the_classic_dialog(self):
        contrasts = [{"name": "A1 − A0", "weights": [{"levels": ["A1"], "coefficient": 1},
                                                    {"levels": ["A0"], "coefficient": -1}]}]
        current = {"Response": "Response", "Factors": FACTORS, "Interaction order": 2,
                   planned.FACTORS: ["A dose"], planned.CONTRASTS: contrasts,
                   planned.CORRECTION: "Bonferroni", planned.ALPHA: 0.1}

        def action(dialog, seen):
            seen["ok"] = dialog.validate()
            seen["options"] = dialog.result[1]

        seen = self.drive(action, current=current, factors=None)
        self.assertTrue(seen["ok"])
        for key in planned.KEYS:
            self.assertEqual(seen["options"][key], current[key])
        self.assertIsNot(seen["options"][planned.CONTRASTS], contrasts)

    def drive_editor(self, dialog, edit):
        errors = []

        def ready(editor):
            try:
                edit(editor)
            except Exception as error:
                errors.append(error)
            finally:
                if editor.winfo_exists():
                    editor.cancel()

        drive_mapped_dialog(dialog, ContrastEditor, ready, errors)
        dialog.contrast_panel.button.invoke()
        self.assertIs(dialog.grab_current(), dialog)
        if errors:
            raise errors[0]

    def test_create_and_calculate_a_contrast_with_fractions_in_italian(self):
        self.use("it")

        def action(dialog, seen):
            self.assertEqual(dialog.contrast_panel.button.cget("text"), "Contrasti pianificati…")

            def edit(editor):
                editor.factor_list.selection_clear(1, "end")
                editor.add_contrast()
                editor.name.set("Dose $ | A0 − A1")
                editor.coefficient.set("1/0")
                editor.ok()
                self.assertIsNone(editor.result)
                self.assertIs(editor.initial_focus, editor.coefficient_box)
                self.assertIn("A0 − A1", editor.problem.cget("text"))
                editor.coefficient.set("0,5")
                editor.show_weights(1)
                editor.coefficient.set("-1/2")
                self.assertIn("0", editor.total.cget("text"))
                editor.alpha.set("0,1")
                editor.correction_box.current(1)
                editor.duplicate()
                editor.move(-1)
                editor.remove_contrast()
                editor.update_idletasks()
                self.assertLessEqual(editor.winfo_rooty() + editor.winfo_height(), editor.winfo_screenheight())
                editor.ok()

            self.drive_editor(dialog, edit)
            self.assertTrue(dialog.validate())
            seen["options"] = dialog.result[1]

        options = self.drive(action)["options"]
        self.assertEqual(options[planned.FACTORS], ["A dose"])
        self.assertEqual(options[planned.ALPHA], 0.1)
        self.assertEqual(options[planned.CORRECTION], "Bonferroni")
        self.assertEqual(options[planned.CONTRASTS], [{
            "name": "Dose $ | A0 − A1", "weights": [
                {"levels": ["A0"], "coefficient": 0.5},
                {"levels": ["A1"], "coefficient": -0.5},
            ],
        }])
        table = analyse(METHOD, FRAME, options).tables[planned.SHEET]
        means = FRAME.groupby("A dose")["Response"].mean()
        self.assertAlmostEqual(table.loc[0, "Estimate"], 0.5 * (means["A0"] - means["A1"]), places=11)

    def test_repair_a_missing_level_and_cancel_an_editor_change(self):
        current = {"Response": "Response", "Factors": FACTORS, "Interaction order": 2,
                   planned.FACTORS: ["A dose"], planned.CONTRASTS: [{
                       "name": "Dose $", "weights": [{"levels": ["A0"], "coefficient": 1},
                                                      {"levels": ["A9"], "coefficient": -1}]}]}

        def action(dialog, seen):
            ok, error = self.rejected(dialog)
            self.assertFalse(ok)
            self.assertIn("A9", error)
            self.assertIs(dialog.initial_focus, dialog.contrast_panel.button)

            def cancel(editor):
                editor.remove_contrast()
                editor.cancel()

            self.drive_editor(dialog, cancel)
            self.assertEqual(dialog.contrast_panel.values()[planned.CONTRASTS], current[planned.CONTRASTS])

            def repair(editor):
                editor.ok()
                self.assertIsNone(editor.result)
                picker = editor.level_boxes["A dose"]
                self.assertIs(editor.initial_focus, picker)
                self.assertIn("A9", picker.get())
                picker.current(1)
                picker.event_generate("<<ComboboxSelected>>")
                editor.ok()

            self.drive_editor(dialog, repair)
            self.assertTrue(dialog.validate())
            seen["options"] = dialog.result[1]

        options = self.drive(action, current=current, factors=None)["options"]
        self.assertEqual(options[planned.CONTRASTS][0]["weights"][1]["levels"], ["A1"])
        self.assertEqual(current[planned.CONTRASTS][0]["weights"][1]["levels"], ["A9"])


class ClassicaContrastRecalculationTests(TkCase):
    def test_saved_contrast_reopens_and_undo_recovers_its_level(self):
        from tramastat import App, Run

        frame = pd.DataFrame({"Value": [10, 11, 12, 17, 20, 21, 22], "Dose": ["A", "A", "A", "B", "C", "C", "C"]})
        options = {"Response": "Value", "Factors": ["Dose"], "Interaction order": 1,
                   planned.FACTORS: ["Dose"], planned.CONTRASTS: [{
                       "name": "B − A", "weights": [{"levels": ["B"], "coefficient": 1},
                                                      {"levels": ["A"], "coefficient": -1}]}]}
        self.root.deiconify()
        app = App(self.root, standard_only=True)
        self.addCleanup(self.root.withdraw)
        self.addCleanup(app.worker.shutdown)
        self.addCleanup(app._clear, "")
        errors = []
        app.error = errors.append
        app._add_tables({"Experiment": frame})

        def wait():
            deadline = time.monotonic() + 10

            def check():
                if app.pending is None or time.monotonic() >= deadline:
                    self.root.quit()
                else:
                    self.root.after(10, check)

            self.root.after(0, check)
            self.root.mainloop()
            self.assertIsNone(app.pending)
            self.assertFalse(errors, errors)

        app.start_analysis(Run(METHOD, "Experiment", options), frame)
        wait()
        with TemporaryDirectory() as output:
            path = Path(output) / "planned.alab"
            save_project(path, app.tables)
            app.import_file(path)
            app.recalculate(0)
            wait()
        run = app.runs[0]
        self.assertEqual(run.options[planned.CONTRASTS], options[planned.CONTRASTS])
        self.assertAlmostEqual(run.result.tables[planned.SHEET].loc[0, "Estimate"], 6)
        complete = run.result
        app.show("data", "Experiment")
        app.edit_cell(3, 1, "D")
        wait()
        self.assertIs(run.result, complete)
        self.assertIn("has no level", app.stale_calculation_note(("result", 0)))
        app.apply_worksheet_history()
        wait()
        self.assertIsNone(app.stale_calculation_note(("result", 0)))
        self.assertAlmostEqual(run.result.tables[planned.SHEET].loc[0, "Estimate"], 6)


if __name__ == "__main__":
    unittest.main()
