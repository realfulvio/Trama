"""Italian text for Global fit custom equation, including the real scope control."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import i18n
from analisi.field_error import FieldError
from analisi.global_custom_dialog import translate_error
from analisi.global_custom_fit import GLOBAL_CUSTOM_EQUATION, global_custom_fit
from tests.test_graph_i18n import TkCase

BASE = pd.DataFrame({
    "X": [0., 1, 2, 0, 1, 2],
    "Y": [1., 2, 3, 2, 4, 6],
    "Group": ["A", "A", "A", "B", "B", "B"],
    "SD": [1., 1, 1, 2, 2, 2],
    "Note": ["text"] * 6,
})


def coefficient(name, start=1.0, lower=None, upper=None, *, fixed=False, shared=False):
    return {"name": name, "start": start, "lower": lower, "upper": upper, "fixed": fixed, "shared": shared}


def recipe(**extra):
    options = {
        "X": "X", "Y": "Y", "Group": "Group", "Equation": "A + B*X",
        "Parameters": [coefficient("A"), coefficient("B", shared=True)],
        "Series constraints": [], "Weighting": "Unweighted", "SD column": None,
        "Confidence level (%)": 95.0, "Curve points": 21,
    }
    options.update(extra)
    return options


def run(frame=BASE, **extra):
    return global_custom_fit(frame, recipe(**extra))


def constraint(series, **parameters):
    return {"series": series, "parameters": parameters}


# Sentences the public options rarely reach. They are the engine text, so the catalog must match them.
EXACT = (
    "The limits leave no usable interior starting value.",
    "The global fit exceeds the dense Jacobian budget. Use fewer rows or share more coefficients.",
    "The fit did not converge. Change the starting values or limits, or fix some coefficients.",
    "The residual sum of squares exceeds the numerical range.",
    "The covariance of the global fit exceeds the numerical range.",
    "The equation is not defined at the solution.",
    "Series 'A': specify overrides by coefficient.",
    "Global fitting needs at least two series with complete observations.",
)


def calls():
    yield lambda: run(Equation="__import__('os')")
    yield lambda: run(Equation="X.__class__")
    yield lambda: run(Group=None)
    yield lambda: run(**{"Confidence level (%)": float("nan")})
    yield lambda: run(**{"Curve points": float("inf")})
    yield lambda: run(Weighting="1/abs(Yfit)")
    yield lambda: run(**{"Series constraints": [constraint("Missing", A={"lower": 0})]})
    yield lambda: run(Parameters=[coefficient("B", fixed=True, shared=True)])
    yield lambda: run(**{"Series constraints": [constraint("A", B={"fixed": 1})]})
    yield lambda: run(**{"Series constraints": [
        constraint("A", B={"lower": 3}), constraint("B", B={"upper": 2})]})
    yield lambda: run(Equation="A+B+C*X", Parameters=[coefficient("A"), coefficient("B"), coefficient("C", shared=True)])
    for extra in (
            {"Parameters": "A,B"}, {"Parameters": [1]},
            {"Parameters": [coefficient("A"), coefficient("A", shared=True)]},
            {"Parameters": [coefficient("A", shared="yes"), coefficient("B", shared=True)]},
            {"Parameters": [coefficient("A", start="x"), coefficient("B", shared=True)]},
            {"Parameters": [coefficient("A", lower=2, upper=1), coefficient("B", shared=True)]},
            {"Parameters": [coefficient("A", start=5, upper=1), coefficient("B", shared=True)]},
            {"Parameters": [coefficient("A", lower="x"), coefficient("B", shared=True)]},
            {"X": "nope"}, {"Y": "X"}, {"Weighting": "Inverse variance (column)"},
            {"Weighting": "Inverse variance (column)", "SD column": "X"},
            {"Confidence level (%)": 0}, {"Curve points": 3},
            {"Equation": "A+B*X+C"}, {"Equation": "A+"}, {"Equation": ""},
            {"Series constraints": "no"}, {"Series constraints": ["no"]},
            {"Series constraints": [constraint("A"), constraint("A", A={"lower": 0})]},
            {"Series constraints": [{"series": "A", "parameters": []}]},
            {"Series constraints": [{"series": None, "parameters": {}}]},
            {"Series constraints": [constraint("A", Q={"lower": 1})]},
            {"Series constraints": [constraint("A", A={"nope": 1})]},
            {"Parameters": [coefficient("A", fixed=True), coefficient("B", shared=True)],
             "Series constraints": [constraint("A", A={"fixed": 1})]},
            {"Series constraints": [constraint("A", A={"lower": 3, "upper": 1})]},
            {"Series constraints": [constraint("A", A={"lower": "x"})]},
            {"Series constraints": [constraint("A", A={"fixed": 1, "initial": 1})]},
            {"Series constraints": [constraint("A", A={"fixed": 9, "upper": 1})]},
            {"Series constraints": [constraint("A", A={"initial": 9, "upper": 1})]},
            {"Series constraints": [constraint("A", B={"upper": 0.5}), constraint("B", B={"upper": 0.5})]},
            {"Series constraints": [constraint("A", A={"upper": 0.5})]}):
        yield lambda extra=extra: run(**extra)
    yield lambda: run(BASE.assign(X=["a", 1, 2, 0, 1, 2]))
    yield lambda: run(BASE.assign(Y=[np.inf, 2, 3, 2, 4, 6]))
    yield lambda: run(BASE.assign(SD=[0, 1, 1, 2, 2, 2]), Weighting="Inverse variance (column)", **{"SD column": "SD"})
    yield lambda: run(BASE.assign(Group=[1, 1, 1, "1", "1", "1"]))
    yield lambda: run(BASE.assign(Group="A"))
    wide = pd.concat([pd.DataFrame({"X": [0., 1], "Y": [1., 2], "Group": str(i)}) for i in range(13)], ignore_index=True)
    yield lambda: run(wide)
    one = pd.concat([
        pd.DataFrame({"X": [0.], "Y": [1.], "Group": "A"}),
        pd.DataFrame({"X": [0.], "Y": [1.], "Group": "B"})], ignore_index=True)
    yield lambda: run(one, Equation="A+B*X+C*X**2",
                      Parameters=[coefficient("A"), coefficient("B", shared=True), coefficient("C")])
    bad = BASE.copy()
    bad.loc[0, "X"] = -1
    yield lambda: run(bad, Equation="A+B*log(X)")
    rows = []
    for index in range(12):
        rows.append(pd.DataFrame({"X": np.linspace(0, 1, 7000), "Y": np.linspace(0, 1, 7000),
                                  "Group": chr(65 + index)}))
    budget = pd.concat(rows, ignore_index=True)
    yield lambda: run(budget, Parameters=[coefficient("A"), coefficient("B")])
    many = pd.concat([
        pd.DataFrame({"X": np.arange(50001.), "Y": np.arange(50001.), "Group": "A"}),
        pd.DataFrame({"X": np.arange(50000.), "Y": np.arange(50000.), "Group": "B"})], ignore_index=True)
    yield lambda: run(many)
    with patch("analisi.global_custom_fit.optimize.least_squares", side_effect=RuntimeError("stop")):
        yield lambda: run(Equation="C+A*exp(-K*X)", Parameters=[
            coefficient("C", fixed=True), coefficient("A"), coefficient("K", 0.4, shared=True)])


def messages():
    found = []
    for call in calls():
        try:
            call()
        except FieldError as error:
            found.append(str(error))
        except Exception as error:
            found.append(f"UNEXPECTED {type(error).__name__}: {error}")
    return found


class ItalianMessageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found = messages()

    def tearDown(self):
        i18n.set_language("en")

    def test_every_engine_message_is_translated(self):
        self.assertGreater(len(self.found), 40)
        self.assertFalse([text for text in self.found if text.startswith("UNEXPECTED")], self.found)
        i18n.set_language("it")
        missing = sorted({text for text in [*self.found, *EXACT] if translate_error(text) == text})
        self.assertEqual(missing, [])

    def test_english_and_unknown_text_stay_literal(self):
        i18n.set_language("en")
        self.assertEqual(translate_error(self.found[0]), self.found[0])
        self.assertEqual(translate_error("Injected worker failure"), "Injected worker failure")
        i18n.set_language("it")
        self.assertEqual(translate_error("Injected worker failure"), "Injected worker failure")
        text = translate_error("Group {x}: B: the starting value 2 lies outside its limits.")
        self.assertTrue(text.startswith("Gruppo {x}:"), text)
        self.assertIn("2", text)

    def test_group_column_message_is_not_parsed_as_a_series_prefix(self):
        i18n.set_language("it")
        text = translate_error("Group is required and must be an existing column different from X and Y.")
        self.assertTrue(text.startswith("Il gruppo"), text)
        other = translate_error("Group must be an existing column different from X and Y.")
        self.assertTrue(other.startswith("Il gruppo deve"), other)


class DialogLanguageTests(TkCase):
    def test_italian_controls_keep_canonical_values(self):
        from tramastat import AnalysisDialog
        from analisi import ui_theme

        # Geometry assertions use the same fonts and padding as the application.
        ui_theme.configure(self.root)
        self.use("it")
        frame = BASE.copy()
        seen = {}

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        dialog = None

        def drive():
            nonlocal dialog
            try:
                dialog = next(widget for widget in self.root.winfo_children() if isinstance(widget, AnalysisDialog))
                dialog.update_idletasks()
                seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
                table = dialog.controls["Parameters"][1]
                table.tree.selection_set("1")
                table.load_selection()
                seen["scope"] = table.scope.get()
                seen["scope_label"] = table.scope_binding.combobox.get()
                seen["tree_scope"] = table.tree.item("1", "values")[1]
                seen["weight"] = dialog.controls["Weighting"][1].get()
                seen["weight_label"] = dialog.choice_bindings["Weighting"].combobox.get()
                seen["group"] = dialog.field_rows["Group"][0].cget("text")
                seen["sd_visible"] = bool(dialog.field_rows["SD column"][1].winfo_manager())
                seen["labels"] = list(dialog.global_series.labels)
                table.tree.selection_set("0")
                table.load_selection()
                table.variables["lower"].set("0")
                dialog.controls["Confidence level (%)"][1].set("0")
                with patch("tramastat.messagebox.showerror") as report:
                    seen["rejected"] = dialog.validate()
                    seen["confidence_message"] = report.call_args.args[1]
                    seen["confidence_tab"] = dialog.fields.tab(dialog.fields.select(), "text")
                    dialog.controls["Confidence level (%)"][1].set("95")
                    editor = dialog.controls["Series constraints"][1]
                    editor.select_series("A")
                    editor.select_coefficient("B")
                    editor.variables["lower"].set("3")
                    editor.select_series("B")
                    editor.select_coefficient("B")
                    editor.variables["upper"].set("2")
                    seen["bounds"] = dialog.validate()
                    seen["bounds_message"] = report.call_args.args[1]
                    seen["bounds_tab"] = dialog.fields.tab(dialog.fields.select(), "text")
                editor.clear_all()
                dialog.controls["Weighting"][1].set("Inverse variance (column)")
                dialog.controls["SD column"][1].set("Note")
                with patch("tramastat.messagebox.showerror") as report:
                    seen["sd_blocked"] = dialog.validate()
                    seen["sd_message"] = report.call_args.args[1]
                    seen["sd_tab"] = dialog.fields.tab(dialog.fields.select(), "text")
                dialog.controls["Weighting"][1].set("Unweighted")
                dialog.update_idletasks()
                seen["sd_hidden"] = not bool(dialog.field_rows["SD column"][1].winfo_manager())
                seen["accepted"] = dialog.validate()
                if dialog.result:
                    seen["options"] = dialog.result[1]
                    dialog.result = None
                dialog.fields.select(dialog.field_rows["Series constraints"][1].master)
                dialog.update_idletasks()
                bottom = dialog.global_series.warning.winfo_rooty() + dialog.global_series.warning.winfo_height()
                page_bottom = dialog.fields.winfo_rooty() + dialog.fields.winfo_height()
                seen["series_overflow"] = bottom - page_bottom
                dialog.fields.select(dialog.field_rows["Parameters"][1].master)
                dialog.update_idletasks()
                bottom = table.unused.winfo_rooty() + table.unused.winfo_height()
                page_bottom = dialog.fields.winfo_rooty() + dialog.fields.winfo_height()
                seen["parameters_overflow"] = bottom - page_bottom
                buttons = [widget.cget("text") for widget in walk(dialog) if widget.winfo_class() == "TButton"]
                seen["buttons"] = buttons
                seen["size"] = (dialog.winfo_width(), dialog.winfo_height())
                run = next(widget for widget in walk(dialog) if widget.winfo_class() == "TButton"
                           and widget.cget("text") == i18n.ui("Run Analysis"))
                dialog.update()
                seen["run_viewable"] = bool(run.winfo_viewable())
                seen["run_mapped"] = bool(run.winfo_ismapped())
                seen["run_manager"] = run.winfo_manager()
                seen["run_y"] = run.winfo_rooty()
                seen["req"] = (dialog.winfo_reqwidth(), dialog.winfo_reqheight())
                seen["screen"] = (dialog.winfo_screenwidth(), dialog.winfo_screenheight())
                seen["dialog_mapped"] = bool(dialog.winfo_ismapped())
                seen["dialog_viewable"] = bool(dialog.winfo_viewable())
            except Exception:
                import traceback
                seen["error"] = traceback.format_exc()
            finally:
                if dialog is not None:
                    dialog.result = None
                    dialog.cancel()

        self.root.deiconify()
        self.root.geometry("1024x768+0+0")
        self.root.after(80, drive)
        AnalysisDialog(self.root, frame, current=(GLOBAL_CUSTOM_EQUATION, {}), only=GLOBAL_CUSTOM_EQUATION)
        self.assertNotIn("error", seen, seen.get("error"))
        self.assertEqual(seen["tabs"], ["Variabili", "Equazione", "Coefficienti", "Vincoli di serie", "Risultati",
                                        "Bande e previsioni"])
        self.assertEqual(seen["scope"], "Shared")
        self.assertEqual(seen["scope_label"], "Condiviso")
        self.assertEqual(seen["tree_scope"], "Condiviso")
        self.assertEqual(seen["weight"], "Unweighted")
        self.assertEqual(seen["weight_label"], "Senza pesi")
        self.assertEqual(seen["group"], "Gruppo")
        self.assertFalse(seen["sd_visible"])
        self.assertEqual(seen["labels"], ["A", "B"])
        self.assertFalse(seen["rejected"])
        self.assertIn("tra 0 e 100", seen["confidence_message"])
        self.assertEqual(seen["confidence_tab"], "Risultati")
        self.assertFalse(seen["bounds"])
        self.assertIn("non si sovrappongono", seen["bounds_message"])
        self.assertEqual(seen["bounds_tab"], "Vincoli di serie")
        self.assertFalse(seen["sd_blocked"])
        self.assertIn("Note", seen["sd_message"])
        self.assertEqual(seen["sd_tab"], "Variabili")
        self.assertTrue(seen["sd_hidden"])
        self.assertTrue(seen["accepted"])
        options = seen["options"]
        self.assertIsNone(options["SD column"])
        self.assertEqual(options["Weighting"], "Unweighted")
        self.assertEqual(options["Equation"], "A + B*X")
        self.assertFalse(options["Parameters"][0]["fixed"])
        self.assertFalse(options["Parameters"][0]["shared"])
        self.assertEqual(options["Parameters"][0]["lower"], 0.0)
        self.assertTrue(options["Parameters"][1]["shared"])
        self.assertFalse(options["Parameters"][1]["fixed"])
        self.assertEqual(options["Series constraints"], [])
        self.assertLessEqual(seen["series_overflow"], 2)
        self.assertLessEqual(seen["parameters_overflow"], 2)
        self.assertIn(i18n.ui("Run Analysis"), seen["buttons"])
        self.assertIn(i18n.ui("Cancel"), seen["buttons"])
        self.assertTrue(seen["run_viewable"], {key: seen[key] for key in (
            "size", "run_viewable", "run_mapped", "dialog_mapped", "dialog_viewable", "series_overflow",
            "parameters_overflow")})
        self.assertLessEqual(seen["size"][0], 1024)
        self.assertLessEqual(seen["size"][1], 768)
        self.assertIsNone(getattr(dialog, "result", None))


if __name__ == "__main__":
    unittest.main()
