"""Real Tk coverage of the ANCOVA dialog: tabs, translated choices, the control group list and the recipe."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import pandas as pd

from analisi import i18n
from analisi.ancova import ANCOVA
from tests.test_graph_i18n import TkCase, descendants


def frame():
    return pd.DataFrame({
        "Dose": [1., 2., 3., 4., 2., 3., 4., 5., 1.5, 2.5, 3.5, 4.5],
        "Effect": [2.1, 3.9, 6.2, 8.1, 5.0, 7.1, 8.8, 11.2, 6.3, 7.4, 9.1, 10.3],
        "Arm": ["Control"] * 4 + ["Low"] * 4 + ["High"] * 4,
        "Other": list("abcdabcdabcd"),
    })


COLUMNS = {"Response": "Effect", "Covariate": "Dose", "Group": "Arm"}
SAVED = {"Response": "Effect", "Covariate": "Dose", "Group": "Arm", "Slope model": "By group", "Reference X": 3.0,
         "Reference domain": "Common range", "Comparisons": "Against control", "Control group": "Low",
         "Adjustment": "Bonferroni", "Confidence level (%)": 90.0, "Graph": "Adjusted means"}


class AncovaDialogTests(TkCase):
    def drive(self, callback, *args, **kwargs):
        from tramastat import AnalysisDialog
        seen = {}

        def run():
            dialog = next(widget for widget in self.root.winfo_children() if isinstance(widget, AnalysisDialog))
            try:
                callback(dialog, seen)
            except BaseException as error:
                seen["error"] = error
            finally:
                dialog.cancel()

        self.root.deiconify()
        self.root.after(100, run)
        # A real message box would block the test forever: an unexpected error becomes a failed assertion instead.
        with patch("tramastat.messagebox.showerror", side_effect=lambda *a, **k: seen.setdefault("unexpected", a)):
            AnalysisDialog(self.root, *args, **kwargs)
        self.root.withdraw()
        if "error" in seen:
            raise seen["error"]
        return seen

    def test_tabs_captions_and_defaults_in_both_languages(self):
        for code, tabs, ok in (("en", ["Variables", "Model", "Comparisons"], "Run Analysis"),
                               ("it", ["Variabili", "Modello", "Confronti"], "Esegui analisi")):
            self.use(code)

            def inspect(dialog, seen):
                self.assertEqual([dialog.fields.tab(index, "text") for index in range(dialog.fields.index("end"))], tabs)
                labels = {widget.cget("text") for widget in descendants(dialog) if "text" in widget.keys()}
                self.assertIn(ok, labels)
                caption = {"en": "Covariate", "it": "Covariata"}[code]
                self.assertEqual(dialog.field_rows["Covariate"][0].cget("text"), caption)
                self.assertEqual(dialog.controls["Slope model"][1].get(), "Common")
                self.assertEqual(dialog.controls["Comparisons"][1].get(), "All pairs")
                # Control group belongs to Against control only; the adjustment is off for None.
                self.assertFalse(dialog.field_rows["Control group"][1].winfo_ismapped() and
                                 dialog.field_rows["Control group"][1].winfo_viewable())
                seen["tabs"] = tabs

            self.drive(inspect, frame(), only=ANCOVA)

    def test_canonical_values_roundtrip_through_translated_choices(self):
        snapshots = {}
        for code in ("en", "it"):
            self.use(code)

            def inspect(dialog, seen):
                combo = dialog.field_rows["Slope model"][1]
                self.assertEqual(combo.get(), "Per gruppo" if code == "it" else "By group")
                self.assertEqual(dialog.controls["Slope model"][1].get(), "By group")
                self.assertEqual(dialog.controls["Comparisons"][1].get(), "Against control")
                self.assertEqual(dialog.field_rows["Control group"][1].get(), "Low")
                self.assertEqual(dialog.controls["Reference X"][1].get(), "3.0")
                self.assertEqual(dialog.controls["Graph"][1].get(), "Adjusted means")
                self.assertTrue(dialog.validate())
                seen["result"] = deepcopy(dialog.result)

            snapshots[code] = self.drive(inspect, frame(), current=(ANCOVA, deepcopy(SAVED)), only=ANCOVA)["result"]
        self.assertEqual(snapshots["it"], snapshots["en"])
        method, options = snapshots["it"]
        self.assertEqual(method, ANCOVA)
        self.assertEqual(options, SAVED)
        self.assertIsInstance(options["Reference X"], float)

    def test_empty_reference_is_stored_as_null_and_text_as_a_number(self):
        self.use("en")

        def inspect(dialog, seen):
            self.assertEqual(dialog.controls["Reference X"][1].get(), "")
            self.assertTrue(dialog.validate(), seen.get("unexpected"))
            seen["empty"] = deepcopy(dialog.result[1])
            dialog.controls["Reference X"][1].set("3,5")
            self.assertTrue(dialog.validate(), seen.get("unexpected"))
            seen["comma"] = dialog.result[1]["Reference X"]

        seen = self.drive(inspect, frame(), current=(ANCOVA, dict(COLUMNS)), only=ANCOVA)
        self.assertIsNone(seen["empty"]["Reference X"])
        self.assertEqual(seen["comma"], 3.5)
        # Hidden fields are not part of the recipe.
        self.assertNotIn("Control group", seen["empty"])
        self.assertEqual(seen["empty"]["Adjustment"], "Holm")

    def test_control_group_list_follows_the_columns_and_the_comparison_mode(self):
        self.use("it")

        def inspect(dialog, seen):
            group = dialog.field_rows["Control group"][1]
            self.assertEqual(tuple(group["values"]), ("Control", "Low", "High"))
            dialog.controls["Group"][1].set("Other")
            self.assertEqual(tuple(group["values"]), ("a", "b", "c", "d"))
            dialog.controls["Group"][1].set("Arm")
            dialog.controls["Comparisons"][1].set("Against control")
            dialog.update_idletasks()
            self.assertEqual(dialog.field_rows["Control group"][1].grid_info() != {}, True)
            group.set("Nobody")
            with patch("tramastat.messagebox.showerror") as error:
                self.assertFalse(dialog.validate())
            message = error.call_args.args[1]
            self.assertIn('"Nobody"', message)
            self.assertIn("Gruppo di controllo", message)
            group.set("Low")
            self.assertTrue(dialog.validate())
            self.assertEqual(dialog.result[1]["Control group"], "Low")
            # Changing the group column drops a control that no longer exists.
            dialog.controls["Group"][1].set("Other")
            self.assertEqual(group.get(), "")
            dialog.controls["Comparisons"][1].set("None")
            # The four levels of Other do not share a range of Dose, so the reference needs the opt-in.
            dialog.controls["Reference domain"][1].set("Allow extrapolation")
            self.assertTrue(dialog.validate(), seen.get("unexpected"))
            self.assertNotIn("Control group", dialog.result[1])
            self.assertNotIn("Adjustment", dialog.result[1])

        self.drive(inspect, frame(), current=(ANCOVA, dict(COLUMNS)), only=ANCOVA)

    def test_field_errors_stay_in_the_dialog_with_their_translated_caption(self):
        self.use("it")

        def inspect(dialog, seen):
            dialog.controls["Covariate"][1].set("Effect")
            with patch("tramastat.messagebox.showerror") as error:
                self.assertFalse(dialog.validate())
            self.assertIn("Covariata", error.call_args.args[1])
            dialog.controls["Covariate"][1].set("Dose")
            dialog.controls["Confidence level (%)"][1].set("abc")
            with patch("tramastat.messagebox.showerror") as error:
                self.assertFalse(dialog.validate())
            self.assertIn("Il livello di confidenza (%) deve essere un numero.", error.call_args.args[1])
            dialog.controls["Confidence level (%)"][1].set("95")
            dialog.controls["Reference X"][1].set("abc")
            with patch("tramastat.messagebox.showerror") as error:
                self.assertFalse(dialog.validate())
            self.assertIn("X di riferimento", error.call_args.args[1])
            dialog.controls["Reference X"][1].set("99")
            with patch("tramastat.messagebox.showerror") as error:
                self.assertFalse(dialog.validate())
            self.assertIn("99", error.call_args.args[1])
            dialog.controls["Reference X"][1].set("")
            self.assertTrue(dialog.validate())
            self.assertIsNotNone(dialog.processing_result)
            self.assertEqual(set(dialog.processing_result.tables), {"ANCOVA model", "ANCOVA tests", "Adjusted means",
                                                                   "ANCOVA contrasts", "ANCOVA fitted"})

        self.drive(inspect, frame(), current=(ANCOVA, dict(COLUMNS)), only=ANCOVA)

    def test_the_method_is_found_by_its_translated_name(self):
        self.use("it")

        def inspect(dialog, seen):
            dialog.query.set("medie aggiustate")
            self.assertIn(ANCOVA, dialog.method_by_item.values())
            dialog.query.set("ancova")
            self.assertEqual(list(dialog.method_by_item.values()), [ANCOVA])
            item = next(iter(dialog.method_by_item))
            self.assertEqual(dialog.methods.item(item, "text"), i18n.ui(ANCOVA))
            self.assertEqual(dialog.method, ANCOVA)

        self.drive(inspect, frame(), current=(ANCOVA, {}))


if __name__ == "__main__":
    unittest.main()
