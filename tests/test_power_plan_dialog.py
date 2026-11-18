"""Power and sample size dialog: which inputs are shown, what blocks, decimal commas and the Italian wording."""
import traceback
import unittest
from unittest.mock import patch

import pandas as pd

from analisi import power_plan as pp
from tests.test_graph_i18n import TkCase

FRAME = pd.DataFrame({"x": [1.0, 2.0, 3.0]})


class DialogCase(TkCase):
    def setUp(self):
        from analisi import ui_theme
        from tramastat import AnalysisDialog
        ui_theme.configure(self.root)
        self.AnalysisDialog = AnalysisDialog

    def drive(self, action, *, geometry="1024x768+0+0"):
        seen, holder = {}, []

        def step():
            try:
                dialog = next(w for w in self.root.winfo_children() if isinstance(w, self.AnalysisDialog))
                if dialog.grab_current() is not dialog:
                    self.root.after(10, step)
                    return
                holder.append(dialog)
                dialog.update_idletasks()
                action(dialog, seen)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                for dialog in holder:
                    dialog.result = None
                    dialog.cancel()

        self.root.deiconify()
        self.root.geometry(geometry)
        self.root.after(80, step)
        self.AnalysisDialog(self.root, FRAME, current=(pp.METHOD, {}), only=pp.METHOD)
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def put(dialog, **values):
        for name, value in values.items():
            dialog.controls[name][1].set(value)
        dialog.update()

    @staticmethod
    def shown(dialog):
        return {name for name, rows in dialog.field_rows.items() if rows[1].winfo_manager()}

    @staticmethod
    def rejected(dialog):
        with patch("tramastat.messagebox.showerror") as report:
            ok = dialog.validate()
        message = report.call_args.args[1] if report.call_args else ""
        return ok, message


class VisibilityTests(DialogCase):
    def test_inputs_follow_goal_design_and_effect_input(self):
        def action(dialog, seen):
            self.assertEqual([dialog.fields.tab(i, "text") for i in range(3)], ["Design", "Effect", "Curve"])
            first = self.shown(dialog)
            self.assertIn(pp.TARGET, first)
            self.assertIn(pp.STANDARDIZED_EFFECT, first)
            self.assertFalse({pp.SIZE, pp.ALLOCATION, pp.GROUPS, pp.MEAN_A, pp.GROUP_MEANS} & first)

            self.put(dialog, **{pp.DESIGN: "Independent t", pp.EFFECT_INPUT: pp.MEANS})
            shown = self.shown(dialog)
            self.assertTrue({pp.ALLOCATION, pp.MEAN_A, pp.MEAN_B, pp.COMMON_SD, pp.TARGET} <= shown)
            self.assertFalse({pp.STANDARDIZED_EFFECT, pp.SIZE, pp.NULL_MEAN, pp.GROUP_MEANS, pp.GROUPS} & shown)

            self.put(dialog, **{pp.GOAL: "Power"})
            shown = self.shown(dialog)
            self.assertIn(pp.SIZE, shown)
            self.assertNotIn(pp.TARGET, shown)

            self.put(dialog, **{pp.DESIGN: "One-sample t", pp.GOAL: "Sample size"})
            shown = self.shown(dialog)
            self.assertTrue({pp.MEAN_A, pp.NULL_MEAN, pp.COMMON_SD} <= shown)
            self.assertFalse({pp.MEAN_B, pp.ALLOCATION} & shown)

            self.put(dialog, **{pp.DESIGN: "Paired t"})
            shown = self.shown(dialog)
            self.assertTrue({pp.MEAN_A, pp.MEAN_B, pp.PAIRED_SD_INPUT, pp.DIFFERENCE_SD} <= shown)
            self.assertFalse({pp.SD_A, pp.SD_B, pp.CORRELATION, pp.COMMON_SD} & shown)
            self.put(dialog, **{pp.PAIRED_SD_INPUT: pp.MARGINAL_SD})
            shown = self.shown(dialog)
            self.assertTrue({pp.SD_A, pp.SD_B, pp.CORRELATION} <= shown)
            self.assertNotIn(pp.DIFFERENCE_SD, shown)

            self.put(dialog, **{pp.DESIGN: "One-way ANOVA"})
            shown = self.shown(dialog)
            self.assertTrue({pp.GROUP_MEANS, pp.COMMON_SD} <= shown)
            self.assertFalse({pp.GROUPS, pp.MEAN_A, pp.MEAN_B} & shown)

            self.put(dialog, **{pp.EFFECT_INPUT: pp.STANDARDIZED_EFFECT})
            shown = self.shown(dialog)
            self.assertTrue({pp.GROUPS, pp.STANDARDIZED_EFFECT} <= shown)
            self.assertFalse({pp.GROUP_MEANS, pp.COMMON_SD} & shown)

        self.drive(action)

    def test_the_allocation_note_follows_its_field(self):
        def action(dialog, seen):
            note = dialog.power_allocation_note
            self.assertFalse(note.winfo_manager())
            self.put(dialog, **{pp.DESIGN: "Independent t"})
            self.assertTrue(note.winfo_manager())
            self.put(dialog, **{pp.DESIGN: "Paired t"})
            self.assertFalse(note.winfo_manager())

        self.drive(action)


class ValidationTests(DialogCase):
    def test_hidden_inputs_never_block_the_calculation(self):
        def action(dialog, seen):
            self.put(dialog, **{pp.DESIGN: "Independent t", pp.EFFECT_INPUT: pp.MEANS, pp.MEAN_A: "5",
                                pp.MEAN_B: "7", pp.COMMON_SD: "4"})
            self.put(dialog, **{pp.EFFECT_INPUT: pp.STANDARDIZED_EFFECT, pp.MEAN_A: "junk", pp.COMMON_SD: "-1",
                                pp.STANDARDIZED_EFFECT: "0.5"})
            ok, message = self.rejected(dialog)
            seen["ok"], seen["message"] = ok, message
            seen["result"] = dialog.processing_result

        seen = self.drive(action)
        self.assertTrue(seen["ok"], seen["message"])
        self.assertAlmostEqual(seen["result"].tables[pp.METHOD]["Value"]["Effect size"], 0.5)

    def test_a_decimal_comma_is_a_decimal_mark_in_numbers_and_in_the_means_list(self):
        def action(dialog, seen):
            self.put(dialog, **{pp.DESIGN: "One-way ANOVA", pp.EFFECT_INPUT: pp.MEANS, pp.COMMON_SD: "4,5"})
            box = dialog.field_rows[pp.GROUP_MEANS][1].box
            box.delete("1.0", "end")
            box.insert("1.0", "12; 13,5\n15;16")
            dialog.update()
            seen["variable"] = dialog.controls[pp.GROUP_MEANS][1].get()
            ok, message = self.rejected(dialog)
            seen["ok"], seen["message"] = ok, message
            seen["result"] = dialog.processing_result

        seen = self.drive(action)
        self.assertEqual(seen["variable"], "12; 13,5\n15;16")
        self.assertTrue(seen["ok"], seen["message"])
        table = seen["result"].tables[pp.METHOD]["Value"]
        self.assertEqual(table["Group means"], "12; 13.5; 15; 16")
        self.assertEqual(table["Common SD"], 4.5)
        self.assertEqual(table["Groups"], 4)

    def test_the_means_box_and_its_variable_follow_each_other(self):
        def action(dialog, seen):
            variable = dialog.controls[pp.GROUP_MEANS][1]
            box = dialog.field_rows[pp.GROUP_MEANS][1].box
            self.put(dialog, **{pp.GROUP_MEANS: "1; 2; 3"})
            seen["from_variable"] = box.get("1.0", "end-1c")
            box.insert("end", "; 4")
            dialog.update()
            seen["from_box"] = variable.get()

        seen = self.drive(action)
        self.assertEqual(seen["from_variable"], "1; 2; 3")
        self.assertEqual(seen["from_box"], "1; 2; 3; 4")

    def test_errors_name_the_field_and_select_its_page(self):
        def action(dialog, seen):
            self.put(dialog, **{pp.DESIGN: "Independent t", pp.EFFECT_INPUT: pp.MEANS, pp.MEAN_A: "5",
                                pp.MEAN_B: "5", pp.COMMON_SD: "4"})
            seen["equal"] = self.rejected(dialog)
            seen["page"] = dialog.fields.select() == str(dialog.field_rows[pp.MEAN_A][1].master)
            self.put(dialog, **{pp.MEAN_B: "7", pp.ALLOCATION: "2-3"})
            seen["allocation"] = self.rejected(dialog)
            seen["allocation page"] = dialog.fields.select() == str(dialog.field_rows[pp.ALLOCATION][1].master)

        seen = self.drive(action)
        ok, message = seen["equal"]
        self.assertFalse(ok)
        self.assertIn("Mean A", message)
        self.assertIn("equals Mean B", message)
        self.assertTrue(seen["page"])
        ok, message = seen["allocation"]
        self.assertFalse(ok)
        self.assertIn("Allocation A:B", message)
        self.assertIn("2:3", message)
        self.assertTrue(seen["allocation page"])


class ItalianTests(DialogCase):
    def test_messages_and_captions_are_italian_with_literal_numbers(self):
        self.use("it")

        def action(dialog, seen):
            self.put(dialog, **{pp.DESIGN: "Independent t", pp.EFFECT_INPUT: pp.MEANS, pp.MEAN_A: "5",
                                pp.MEAN_B: "7", pp.COMMON_SD: "4", pp.ALLOCATION: "1:200"})
            seen["allocation"] = self.rejected(dialog)
            self.put(dialog, **{pp.ALLOCATION: "2:3", pp.GOAL: "Power", pp.SIZE: "41"})
            seen["multiple"] = self.rejected(dialog)
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(3)]

        seen = self.drive(action)
        ok, message = seen["allocation"]
        self.assertFalse(ok)
        self.assertIn("1 a 100", message)
        self.assertIn("due punti", message)
        self.assertNotIn("must be", message)
        ok, message = seen["multiple"]
        self.assertFalse(ok)
        self.assertIn("multiplo di 2", message)
        self.assertIn("40 o 42", message)
        self.assertEqual(seen["tabs"], ["Disegno", "Effetto", "Curva"])


if __name__ == "__main__":
    unittest.main()
