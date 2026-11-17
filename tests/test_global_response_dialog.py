"""The real Analyze dialog for Global fit custom equation, 0.70 response page (bands and predictions)."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analisi.global_custom_fit import GLOBAL_CUSTOM_EQUATION
from tests.test_graph_i18n import TkCase

DATA = Path(__file__).resolve().parent / "data" / "global_uncertainty"
RECIPE = json.loads((DATA / "recipes.json").read_text())["linear-shared"]
FRAME = pd.DataFrame(json.loads((DATA / "linear-shared.json").read_text()))
RESPONSE = ("Curve band", "Response level (%)", "Band drawing", "Predict responses", "Query X", "Query group",
            "Query interval", "Query replicate count", "Allow extrapolation")


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


class ResponseDialogTests(TkCase):
    def open(self, recipe, action):
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
        AnalysisDialog(self.root, FRAME.copy(), current=(GLOBAL_CUSTOM_EQUATION, copy.deepcopy(recipe)),
                       only=GLOBAL_CUSTOM_EQUATION)
        self.root.withdraw()
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def shown(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def test_legacy_recipe_stays_without_new_keys(self):
        def action(dialog, seen):
            tabs = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["tabs"] = tabs
            seen["hidden"] = [name for name in RESPONSE if not self.shown(dialog, name)]
            seen["band"] = dialog.controls["Curve band"][1].get()
            seen["accepted"] = dialog.validate()
            seen["options"] = dialog.result[1]

        seen = self.open(RECIPE, action)
        self.assertEqual(seen["tabs"][-1], "Response")
        self.assertEqual(seen["band"], "None")
        self.assertEqual(seen["hidden"], ["Response level (%)", "Band drawing", "Query X", "Query group",
                                          "Query interval", "Query replicate count", "Allow extrapolation"])
        self.assertTrue(seen["accepted"])
        self.assertEqual(set(seen["options"]), set(RECIPE))

    def test_visibility_follows_the_choices_and_values_stay_canonical(self):
        def action(dialog, seen):
            control = lambda name: dialog.controls[name][1]
            control("Curve band").set("Prediction")
            dialog.update_idletasks()
            seen["band_on"] = {name: self.shown(dialog, name) for name in RESPONSE}
            control("Curve band").set("None")
            control("Predict responses").set(True)
            dialog.update_idletasks()
            seen["queries_on"] = {name: self.shown(dialog, name) for name in RESPONSE}
            control("Query interval").set("Prediction")
            dialog.update_idletasks()
            seen["k_on"] = self.shown(dialog, "Query replicate count")
            seen["level_on"] = self.shown(dialog, "Response level (%)")
            seen["display"] = dialog.choice_bindings["Query interval"].combobox.get()
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in RESPONSE]
            seen["tab"] = dialog.fields.tab(dialog.fields.index("end") - 1, "text")
            control("Curve band").set("Confidence")
            control("Band drawing").set("Lines")
            control("Response level (%)").set("90,0")
            control("Query X").set("Query X")
            control("Query group").set("Query group")
            control("Query replicate count").set("Query k")
            control("Allow extrapolation").set(True)
            seen["accepted"] = dialog.validate()
            seen["options"] = dialog.result[1]

        self.use("it")
        seen = self.open(RECIPE, action)
        self.assertEqual(seen["band_on"]["Band drawing"], True)
        self.assertEqual(seen["band_on"]["Response level (%)"], True)
        self.assertFalse(any(seen["band_on"][name] for name in RESPONSE[4:]))
        self.assertEqual([name for name, shown in seen["queries_on"].items() if not shown],
                         ["Response level (%)", "Band drawing", "Query replicate count"])
        self.assertTrue(seen["k_on"] and seen["level_on"])
        self.assertEqual(seen["display"], "Predizione (nuove osservazioni)")
        self.assertEqual(seen["tab"], "Bande e previsioni")
        self.assertEqual(seen["captions"][:4], ["Banda della curva", "Livello della risposta (%)",
                                                "Disegno della banda", "Prevedi risposte"])
        self.assertTrue(seen["accepted"])
        options = seen["options"]
        expected = {"Curve band": "Confidence", "Response level (%)": 90.0, "Band drawing": "Lines",
                    "Predict responses": True, "Query X": "Query X", "Query group": "Query group",
                    "Query interval": "Prediction", "Query replicate count": "Query k", "Allow extrapolation": True}
        self.assertEqual({key: options[key] for key in expected}, expected)
        self.assertEqual(options["Confidence level (%)"], 95.0)
        self.assertEqual(options["Equation"], RECIPE["Equation"])

    def test_field_errors_focus_the_response_page(self):
        def action(dialog, seen):
            control = lambda name: dialog.controls[name][1]
            control("Curve band").set("Confidence")
            control("Predict responses").set(True)
            control("Query interval").set("Prediction")
            dialog.update_idletasks()
            results = []
            for name, value, field in (("Response level (%)", "100", "Response level (%)"),
                                       ("Response level (%)", "inf", "Response level (%)"),
                                       ("Response level (%)", "testo", "Response level (%)"),
                                       ("Query X", "", "Query X"), ("Query group", "", "Query group")):
                previous = control(name).get()
                control(name).set(value)
                with patch("tramastat.messagebox.showerror") as report:
                    accepted = dialog.validate()
                results.append((field, accepted, report.call_args.args[1],
                                dialog.fields.tab(dialog.fields.select(), "text"),
                                str(dialog.focus_get()) if dialog.focus_get() else ""))
                if name == "Response level (%)":
                    control(name).set("90")
                elif name == "Query X":
                    control(name).set("Query X")
                else:
                    control(name).set(previous or "Query group")
            seen["results"] = results
            control("Query replicate count").set("Query X")
            with patch("tramastat.messagebox.showerror") as report:
                seen["k_same"] = (dialog.validate(), report.call_args.args[1])
            control("Query replicate count").set("")
            seen["equation"] = dialog.controls["Equation"][1].values()
            seen["parameters"] = dialog.controls["Parameters"][1].values()
            seen["final"] = dialog.validate()
            dialog.update()
            seen["size"] = (dialog.winfo_width(), dialog.winfo_height())
            run = next(w for w in walk(dialog) if w.winfo_class() == "TButton" and w.cget("text") == "Run Analysis")
            seen["run_bottom"] = run.winfo_rooty() + run.winfo_height()
            dialog.fields.select(dialog.field_rows["Curve band"][1].master)
            dialog.update()
            note = dialog.global_response_note
            seen["note_overflow"] = (note.winfo_rooty() + note.winfo_height()
                                     - dialog.fields.winfo_rooty() - dialog.fields.winfo_height())

        seen = self.open(RECIPE, action)
        for field, accepted, message, tab, focus in seen["results"]:
            with self.subTest(field=field, message=message):
                self.assertFalse(accepted)
                self.assertIn(field, message)
                self.assertEqual(tab, "Response")
                self.assertTrue(focus)
        self.assertFalse(seen["k_same"][0])
        self.assertIn("Query replicate count", seen["k_same"][1])
        self.assertEqual(seen["equation"], RECIPE["Equation"])
        self.assertEqual([row["name"] for row in seen["parameters"]], ["A", "B"])
        self.assertTrue(seen["final"])
        self.assertLessEqual(seen["size"][1], 768)
        self.assertLessEqual(seen["run_bottom"], 768)
        self.assertLessEqual(seen["note_overflow"], 0)

    def test_stale_query_columns_do_not_block_when_predict_is_off(self):
        stale = dict(copy.deepcopy(RECIPE), **{"Predict responses": False, "Query X": "gone",
                                               "Query group": "gone too", "Query replicate count": "gone k",
                                               "Query interval": "Prediction"})

        def action(dialog, seen):
            seen["hidden"] = [name for name in RESPONSE[4:] if not self.shown(dialog, name)]
            with patch("tramastat.messagebox.showerror") as report:
                seen["accepted"] = dialog.validate()
            seen["reported"] = report.called
            seen["options"] = dialog.result[1]

        seen = self.open(stale, action)
        self.assertEqual(seen["hidden"], list(RESPONSE[4:]))
        self.assertTrue(seen["accepted"])
        self.assertFalse(seen["reported"])
        self.assertIs(seen["options"]["Predict responses"], False)
