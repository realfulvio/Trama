"""Real Tk budget defaults, inactive fields, canonical values and translated errors."""
import traceback
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import i18n
from analisi.spearman_exact_budget import FIELD, EXTENDED, STANDARD
from tests.test_graph_i18n import TkCase


class SpearmanBudgetDialog(TkCase):
    def drive(self, action, current=None):
        from tramastat import AnalysisDialog
        from analisi import ui_theme
        ui_theme.configure(self.root)
        seen = {}
        frame = pd.DataFrame({"X": np.arange(18.), "Y": np.arange(18.)})
        def step():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, AnalysisDialog))
            if dialog.grab_current() is not dialog:
                self.root.after(10, step)
                return
            try:
                action(dialog, seen)
            except Exception:
                seen["error"] = traceback.format_exc()
            finally:
                dialog.result = None
                dialog.cancel()
        self.root.deiconify()
        self.root.after(80, step)
        AnalysisDialog(self.root, frame, current=current, only="Correlation")
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    def test_new_default_extended_and_missing_recipe_field_standard(self):
        def action(dialog, seen):
            seen["budget"] = dialog.controls[FIELD][1].get()
        self.assertEqual(self.drive(action)["budget"], EXTENDED)
        self.assertEqual(self.drive(action, ("Correlation", {"Detailed results": True}))["budget"], STANDARD)

    def test_italian_choices_canonical_visibility_and_limit_error(self):
        original = i18n.active_language()
        self.addCleanup(i18n.set_language, original)
        i18n.set_language("it")
        def action(dialog, seen):
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Detailed results"][1].set(True)
            dialog.controls["Method"][1].set("Spearman")
            dialog.controls["Spearman p values"][1].set("Exact")
            dialog.update()
            seen["placed"] = bool(dialog.field_rows[FIELD][1].winfo_manager())
            seen["label"] = dialog.field_rows[FIELD][0].cget("text")
            seen["display"] = dialog.field_rows[FIELD][1].get()
            with patch("tramastat.messagebox.showerror") as report:
                seen["valid"] = dialog.validate()
                seen["message"] = report.call_args.args[1]
            dialog.controls["Spearman p values"][1].set("Approximate")
            dialog.update()
            seen["hidden"] = not bool(dialog.field_rows[FIELD][1].winfo_manager())
            seen["approx"] = dialog.validate()
            seen["options"] = dict(dialog.result[1])
        seen = self.drive(action)
        self.assertTrue(seen["placed"])
        self.assertEqual(seen["label"], "Risorse per Spearman esatto")
        self.assertEqual(seen["display"], "Esteso (17 coppie)")
        self.assertFalse(seen["valid"])
        self.assertIn("17", seen["message"])
        self.assertIn("coppie", seen["message"])
        self.assertTrue(seen["hidden"])
        self.assertTrue(seen["approx"])
        self.assertNotIn(FIELD, seen["options"])
