"""The real Analyze dialog for Robust curve fit (0.73): fields, hidden scale, starting-value editor, errors."""
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analisi.robust_curve import ROBUST_CURVE
from analisi.robust_curve_dialog import InitialParameters, summary_text
from tests.test_graph_i18n import TkCase

DATA = Path(__file__).resolve().parent / "data" / "robust_curve_073"
CASE = next(case for case in json.loads((DATA / "fixtures" / "cases.json").read_text())
            if case["name"] == "line-Cauchy-1.0")
FRAME = pd.DataFrame(CASE["data"])
START = {"Intercept": 2.0, "Slope": 3.0}


class RobustDialogTests(TkCase):
    def open(self, action, recipe=None):
        from tramastat import AnalysisDialog

        seen = {}

        def drive():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, AnalysisDialog))
            try:
                dialog.update_idletasks()
                action(dialog, seen)
            except Exception:
                import traceback
                seen["error"] = traceback.format_exc()
            finally:
                dialog.result = seen.get("keep")
                dialog.cancel() if dialog.result is None else dialog.destroy()

        self.root.deiconify()
        self.root.geometry("1024x768+0+0")
        self.root.after(80, drive)
        AnalysisDialog(self.root, FRAME.copy(), current=(ROBUST_CURVE, recipe) if recipe else None, only=ROBUST_CURVE)
        self.root.withdraw()
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    def test_defaults_pages_and_columns(self):
        def act(dialog, seen):
            controls = dialog.controls
            self.assertEqual([dialog.fields.tab(i, "text") for i in range(3)], ["Variables", "Loss and scale", "Output"])
            self.assertEqual((controls["X"][1].get(), controls["Model"][1].get(), controls["Loss"][1].get()),
                             ("X", "Straight line", "Cauchy"))
            self.assertEqual(controls["Residual scale"][1].get(), "1.0")
            seen["keep"] = dialog.validate() and dialog.result
            seen["options"] = dialog.result[1]

        seen = self.open(act)
        options = seen["options"]
        self.assertEqual(options["Y columns"], ["Y"])
        self.assertEqual((options["Initial parameters"], options["Maximum evaluations"]), ({}, 20000))
        self.assertEqual((options["Low weight threshold"], options["Compare ordinary fit"]), (0.25, False))
        self.assertEqual(options["Graph display"], "Curve")

    def test_a_hidden_scale_is_ignored_under_pilot_mad_even_when_invalid(self):
        def act(dialog, seen):
            dialog.controls["Scale method"][1].set("Pilot MAD")
            dialog.controls["Residual scale"][1].set("garbage")
            dialog.update()
            self.assertFalse(dialog.field_rows["Residual scale"][1].winfo_manager())
            self.assertTrue(dialog.validate())
            seen["options"] = dialog.result[1]
            dialog.controls["Scale method"][1].set("Fixed")
            dialog.update()
            self.assertTrue(dialog.field_rows["Residual scale"][1].winfo_manager())
            with patch("tramastat.messagebox.showerror") as banner:
                self.assertFalse(dialog.validate())
            seen["message"] = banner.call_args.args[1]
            seen["focus"] = dialog.fields.select() == str(dialog.field_rows["Residual scale"][1].master)

        seen = self.open(act)
        self.assertEqual(seen["options"]["Scale method"], "Pilot MAD")
        self.assertNotEqual(seen["options"].get("Residual scale"), "garbage")
        self.assertIn("Residual scale", seen["message"])
        self.assertTrue(seen["focus"])

    def test_each_invalid_field_keeps_the_dialog_open_on_that_field(self):
        cases = (("Residual scale", "0", "greater than 0"), ("Maximum evaluations", "10", "from 50 to 100000"),
                 ("Low weight threshold", "1", "less than 1"), ("Residual scale", "1,5x", "must be a number"))

        def act(dialog, seen):
            seen["messages"] = []
            for field, value, _ in cases:
                dialog.controls[field][1].set(value)
                with patch("tramastat.messagebox.showerror") as banner:
                    self.assertFalse(dialog.validate(), field)
                seen["messages"].append(banner.call_args.args[1])
                self.assertEqual(dialog.fields.select(), str(dialog.field_rows[field][1].master))
                dialog.controls[field][1].set({"Residual scale": "1.0", "Maximum evaluations": "20000",
                                               "Low weight threshold": "0.25"}[field])

        seen = self.open(act)
        for (field, _, text), message in zip(cases, seen["messages"], strict=True):
            self.assertIn(text, message)
            self.assertIn(field, message)

    def test_the_starting_value_field_keeps_the_recipe_form(self):
        saved = {"X": "X", "Y columns": ["Y"], "Model": "Straight line", "Initial parameters": START}

        def act(dialog, seen):
            editor = dialog.field_rows["Initial parameters"][1]
            self.assertIsInstance(editor, InitialParameters)
            self.assertEqual(editor.values(), START)
            dialog.controls["Model"][1].set("One-phase decay")
            self.assertEqual(editor.values(), {})
            self.assertEqual(editor.summary.cget("text"), "Catalog starting values")
            dialog.controls["Model"][1].set("Straight line")
            seen["keep"] = dialog.validate() and dialog.result
            seen["options"] = dialog.result[1]

        seen = self.open(act, saved)
        self.assertEqual(seen["options"]["Initial parameters"], {})

    def test_summary_text(self):
        self.use("en")
        self.assertEqual(summary_text("Straight line", {}), "Catalog starting values")
        self.assertTrue(summary_text("Straight line", START).startswith("Custom: Intercept = 2, Slope = 3"))
        long = {f"p{i}": i for i in range(5)}
        self.assertTrue(summary_text("Straight line", long).endswith("…"))
        self.use("it")
        self.assertEqual(summary_text("Straight line", {}), "Valori iniziali del catalogo")
