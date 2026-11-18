"""The real Analyze dialog for the Curve pipeline: fields, hidden fields, recipes, EN/IT captions and messages."""
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import curve_pipeline as cp
from analisi import i18n
from analisi.curve_pipeline_dialog import describe_error, translate_error
from analisi.curve_pipeline_text import EN, ERROR_PREFIX, IT
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders
from analisi.workbench import analyse
from tests.test_graph_i18n import LanguageMixin, TkCase

DATA = Path(__file__).resolve().parent / "data" / "curve_pipeline"
METHOD = cp.CURVE_METHOD
LEGACY_RECIPE = {"X": "X", "Y": "Y", "Method": "LOWESS", "LOWESS fraction": .6}
DIALOG_ONLY = {ERROR_PREFIX + name for name in ("typed_whole", "typed_number", "typed_finite", "typed_range", "pick")}
PIPELINE_FIELDS = (cp.OPERATION, cp.SMOOTHING, cp.BASELINE, cp.INITIAL, cp.HALF_WINDOW, cp.DEGREE)


def uniform():
    return pd.read_csv(DATA / "uniform.csv").assign(Y=lambda frame: frame["Clean"])[["X", "Y", "Impulse"]]


def irregular():
    return pd.read_csv(DATA / "irregular.csv")


class DialogCase(TkCase):
    frame = None

    def open(self, action, recipe=None, frame=None):
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
        AnalysisDialog(self.root, (uniform() if frame is None else frame).copy(),
                       current=(METHOD, recipe) if recipe else None, only=METHOD)
        self.root.withdraw()
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    @staticmethod
    def attempt(dialog):
        with patch("tramastat.messagebox.showerror") as banner:
            ok = dialog.validate()
        return ok, banner.call_args.args[1] if banner.called else None

    @staticmethod
    def notes_inside_the_page(dialog):
        """Every shown note ends above the bottom of the notebook, so nothing is clipped at 1024x768."""
        dialog.fields.select(1)
        dialog.update()
        page_bottom = dialog.fields.winfo_rooty() + dialog.fields.winfo_height()
        return [(note.winfo_rooty() + note.winfo_height()) <= page_bottom for note in dialog.curve_notes
                if note.winfo_manager()]

    @staticmethod
    def set_fields(dialog, values):
        for name, value in values:
            dialog.controls[name][1].set(value)
            dialog.update()


class EnglishDialogTests(DialogCase):
    def test_pages_defaults_and_the_pipeline_fields_of_a_new_analysis(self):
        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["names"] = list(dialog.controls)
            seen["captions"] = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
            seen["shown"] = {name for name in dialog.controls if self.placed(dialog, name)}
            seen["method"] = dialog.controls["Method"][1].get()
            seen["choices"] = {name: dialog.choice_bindings[name].values for name in ("Method", "Operation", "Smoothing")}
            seen["defaults"] = {name: dialog.controls[name][1].get() for name in PIPELINE_FIELDS}

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Variables", "Options"])
        self.assertEqual(seen["names"], ["X", "Y", "Method", "LOWESS fraction", *PIPELINE_FIELDS])
        self.assertEqual(seen["method"], "LOWESS")
        self.assertEqual(seen["shown"], {"X", "Y", "Method", "LOWESS fraction"})
        self.assertEqual(seen["choices"]["Method"], ("LOWESS", "Differentiate", "Cumulative integral", "Curve pipeline"))
        self.assertEqual(seen["choices"]["Operation"], ("Identity", "First difference", "Second difference",
                                                        "Cumulative trapezoid"))
        self.assertEqual(seen["choices"]["Smoothing"], ("None", "Savitzky–Golay"))
        self.assertEqual(seen["defaults"], {"Operation": "Identity", "Smoothing": "None", "Baseline": "0.0",
                                            "Initial integral": "0.0", "Half-window": "2", "Polynomial degree": "2"})
        self.assertEqual(seen["captions"]["Half-window"], "Half-window")
        self.assertEqual(seen["captions"]["Initial integral"], "Initial integral")

    def test_an_older_recipe_reopens_and_saves_unchanged(self):
        def act(dialog, seen):
            seen["method"] = dialog.controls["Method"][1].get()
            seen["fraction"] = dialog.controls["LOWESS fraction"][1].get()
            seen["shown"] = {name for name in dialog.controls if self.placed(dialog, name)}
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["result"] = dialog.result

        seen = self.open(act, dict(LEGACY_RECIPE))
        self.assertEqual((seen["method"], seen["fraction"]), ("LOWESS", "0.6"))
        self.assertEqual(seen["shown"], {"X", "Y", "Method", "LOWESS fraction"})
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["result"], (METHOD, LEGACY_RECIPE))

    def test_each_older_choice_saves_only_its_own_fields(self):
        def act(dialog, seen):
            seen["recipes"] = {}
            for choice in ("Differentiate", "Cumulative integral", "LOWESS"):
                dialog.controls["Method"][1].set(choice)
                dialog.update()
                self.assertTrue(self.attempt(dialog)[0])
                seen["recipes"][choice] = dialog.result[1]

        seen = self.open(act, dict(LEGACY_RECIPE))
        for choice, recipe in seen["recipes"].items():
            self.assertEqual(recipe, {**LEGACY_RECIPE, "Method": choice}, choice)

    def test_the_pipeline_shows_its_fields_by_operation_and_smoothing(self):
        def act(dialog, seen):
            shown = lambda: {name for name in dialog.controls if self.placed(dialog, name)}
            self.set_fields(dialog, (("Method", cp.PIPELINE),))
            seen["pipeline"] = shown()
            seen["notes"] = [bool(note.winfo_manager()) for note in dialog.curve_notes]
            self.set_fields(dialog, (("Operation", cp.CUMULATIVE),))
            seen["integral"] = shown()
            self.set_fields(dialog, (("Smoothing", cp.SAVITZKY_GOLAY), ("Operation", cp.FIRST)))
            seen["smoothed"] = shown()
            seen["smoothed_notes"] = [bool(note.winfo_manager()) for note in dialog.curve_notes]
            self.set_fields(dialog, (("Method", "Differentiate"),))
            seen["back"] = shown()
            seen["back_notes"] = [bool(note.winfo_manager()) for note in dialog.curve_notes]

        seen = self.open(act)
        base = {"X", "Y", "Method"}
        self.assertEqual(seen["pipeline"], base | {"Operation", "Smoothing"})
        self.assertEqual(seen["notes"], [True, False])
        self.assertEqual(seen["integral"], base | {"Operation", "Smoothing", "Baseline", "Initial integral"})
        self.assertEqual(seen["smoothed"], base | {"Operation", "Smoothing", "Half-window", "Polynomial degree"})
        self.assertEqual(seen["smoothed_notes"], [True, True])
        self.assertEqual(seen["back"], base | {"LOWESS fraction"})
        self.assertEqual(seen["back_notes"], [False, False])

    def test_a_pipeline_recipe_holds_only_the_fields_that_act(self):
        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Operation", cp.CUMULATIVE), ("Baseline", "3"),
                                     ("Initial integral", "2")))
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["integral"] = dialog.result
            seen["table"] = dialog.processing_result.tables["Curve"] if dialog.processing_result else None
            self.set_fields(dialog, (("Operation", cp.FIRST), ("Smoothing", cp.SAVITZKY_GOLAY), ("Half-window", "1"),
                                     ("Polynomial degree", "1")))
            seen["ok2"], seen["message2"] = self.attempt(dialog)
            seen["smoothed"] = dialog.result
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["integral"], (METHOD, {"X": "X", "Y": "Y", "Method": cp.PIPELINE,
                                                     "Operation": cp.CUMULATIVE, "Smoothing": "None",
                                                     "Baseline": 3.0, "Initial integral": 2.0}))
        self.assertIsNotNone(seen["table"])
        self.assertTrue(seen["ok2"], seen["message2"])
        self.assertEqual(seen["smoothed"], (METHOD, {"X": "X", "Y": "Y", "Method": cp.PIPELINE,
                                                     "Operation": cp.FIRST, "Smoothing": cp.SAVITZKY_GOLAY,
                                                     "Half-window": 1, "Polynomial degree": 1}))

    def test_the_dialog_result_is_the_engine_result_and_is_reused(self):
        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Operation", cp.FIRST), ("Smoothing", cp.SAVITZKY_GOLAY)))
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["recipe"] = dialog.result[1]
            seen["tables"] = dialog.processing_result.tables
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertTrue(seen["ok"], seen["message"])
        direct = analyse(METHOD, uniform(), seen["recipe"])
        pd.testing.assert_frame_equal(seen["tables"]["Curve"], direct.tables["Curve"])
        np.testing.assert_allclose(seen["tables"]["Curve"]["Value"], [7, 9, 11, 13], rtol=1e-12)

    def test_degree_five_with_half_window_two_keeps_the_dialog_open_on_the_degree(self):
        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Smoothing", cp.SAVITZKY_GOLAY),
                                     ("Polynomial degree", "5")))
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["exists"] = bool(dialog.winfo_exists())
            seen["page"] = dialog.fields.tab(dialog.fields.select(), "text")
            seen["focus"] = dialog.initial_focus is dialog.field_rows["Polynomial degree"][1]
            seen["viewable"] = dialog.field_rows["Polynomial degree"][1].winfo_viewable()
            self.set_fields(dialog, (("Polynomial degree", "2"),))
            seen["fixed"], seen["fixed_message"] = self.attempt(dialog)
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertFalse(seen["ok"])
        self.assertTrue(seen["exists"])
        self.assertEqual(seen["message"], "Polynomial degree must be a whole number from 0 to 4 for this half-window.")
        self.assertEqual(seen["page"], "Options")
        self.assertTrue(seen["focus"] and seen["viewable"])
        self.assertTrue(seen["fixed"], seen["fixed_message"])

    def test_an_uneven_grid_names_smoothing_and_turning_it_off_allows_the_second_difference(self):
        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Smoothing", cp.SAVITZKY_GOLAY)))
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["focus"] = dialog.initial_focus is dialog.field_rows["Smoothing"][1]
            self.set_fields(dialog, (("Smoothing", "None"), ("Operation", cp.SECOND)))
            seen["fixed"], seen["fixed_message"] = self.attempt(dialog)
            seen["values"] = dialog.processing_result.tables["Curve"]["Value"].tolist() if dialog.processing_result else None
            seen["keep"] = dialog.result

        seen = self.open(act, frame=irregular())
        self.assertFalse(seen["ok"])
        self.assertEqual(seen["message"], "Smoothing: Savitzky–Golay needs evenly spaced X values; the steps of block 1 "
                                          "differ from the median step by more than 1e-10 of it.")
        self.assertTrue(seen["focus"])
        self.assertTrue(seen["fixed"], seen["fixed_message"])
        self.assertEqual(seen["values"], [2, 2, 2])

    def test_typed_numbers_are_checked_on_their_own_field(self):
        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Operation", cp.CUMULATIVE), ("Baseline", "abc")))
            seen["baseline"] = self.attempt(dialog)
            seen["focus"] = dialog.initial_focus is dialog.field_rows["Baseline"][1]
            self.set_fields(dialog, (("Baseline", "1"), ("Initial integral", "inf")))
            seen["initial"] = self.attempt(dialog)
            self.set_fields(dialog, (("Initial integral", "0"), ("Operation", cp.IDENTITY), ("Smoothing", cp.SAVITZKY_GOLAY),
                                     ("Half-window", "2.5")))
            seen["window"] = self.attempt(dialog)
            self.set_fields(dialog, (("Half-window", "99"),))
            seen["range"] = self.attempt(dialog)
            self.set_fields(dialog, (("Half-window", "99999999999999999999"),))
            seen["huge"] = self.attempt(dialog)
            self.set_fields(dialog, (("Half-window", "2"), ("X", "")))
            seen["pick"] = self.attempt(dialog)
            self.set_fields(dialog, (("X", "X"),))
            # A value in a field that does not act is not read at all.
            self.set_fields(dialog, (("Smoothing", "None"),))
            seen["hidden"] = self.attempt(dialog)
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertEqual(seen["baseline"], (False, "Baseline must be a number."))
        self.assertTrue(seen["focus"])
        self.assertEqual(seen["initial"], (False, "Initial integral must be finite."))
        self.assertEqual(seen["window"], (False, "Half-window must be a whole number."))
        self.assertEqual(seen["range"], (False, "Half-window must be a whole number from 1 to 50."))
        self.assertEqual(seen["huge"], (False, "Half-window exceeds the supported integer range."))
        self.assertEqual(seen["pick"], (False, "Choose a column for X."))
        self.assertTrue(seen["hidden"][0], seen["hidden"])

    def test_both_notes_fit_in_the_page_at_1024_by_768(self):
        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Operation", cp.CUMULATIVE), ("Smoothing", cp.SAVITZKY_GOLAY)))
            seen["inside"] = self.notes_inside_the_page(dialog)

        seen = self.open(act)
        self.assertEqual(seen["inside"], [True, True])

    def test_going_back_keeps_what_was_typed(self):
        def act(dialog, seen):
            self.set_fields(dialog, (("LOWESS fraction", "0.35"), ("Method", cp.PIPELINE), ("Operation", cp.CUMULATIVE),
                                     ("Baseline", "7"), ("Smoothing", cp.SAVITZKY_GOLAY), ("Half-window", "3"),
                                     ("Method", "LOWESS")))
            seen["fraction"] = dialog.controls["LOWESS fraction"][1].get()
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["older"] = dialog.result[1]
            self.set_fields(dialog, (("Method", cp.PIPELINE),))
            seen["values"] = {name: dialog.controls[name][1].get() for name in PIPELINE_FIELDS}
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertEqual(seen["fraction"], "0.35")
        self.assertEqual(seen["older"], {"X": "X", "Y": "Y", "Method": "LOWESS", "LOWESS fraction": .35})
        self.assertEqual(seen["values"], {"Operation": "Cumulative trapezoid", "Smoothing": "Savitzky–Golay",
                                          "Baseline": "7", "Initial integral": "0.0", "Half-window": "3",
                                          "Polynomial degree": "2"})

    def test_a_saved_pipeline_recipe_reopens_with_its_values(self):
        recipe = {"X": "X", "Y": "Y", "Method": cp.PIPELINE, "Operation": cp.SECOND, "Smoothing": cp.SAVITZKY_GOLAY,
                  "Half-window": 1, "Polynomial degree": 1}

        def act(dialog, seen):
            seen["values"] = {name: dialog.controls[name][1].get() for name in ("Method", "Operation", "Smoothing",
                                                                               "Half-window", "Polynomial degree")}
            seen["shown"] = {name for name in dialog.controls if self.placed(dialog, name)}
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = dialog.result

        seen = self.open(act, recipe)
        self.assertEqual(seen["values"], {"Method": cp.PIPELINE, "Operation": cp.SECOND, "Smoothing": cp.SAVITZKY_GOLAY,
                                          "Half-window": "1", "Polynomial degree": "1"})
        self.assertEqual(seen["shown"], {"X", "Y", "Method", "Operation", "Smoothing", "Half-window", "Polynomial degree"})
        self.assertTrue(seen["ok"], seen["message"])


class ItalianDialogTests(DialogCase, LanguageMixin):
    def test_captions_choices_and_notes_are_italian_and_the_values_stay_canonical(self):
        self.use("it")

        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Operation", cp.CUMULATIVE), ("Smoothing", cp.SAVITZKY_GOLAY)))
            seen["captions"] = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
            seen["choices"] = {name: dialog.choice_bindings[name].labels for name in ("Method", "Operation", "Smoothing")}
            seen["shown"] = {name: dialog.choice_bindings[name].display.get() for name in ("Method", "Operation", "Smoothing")}
            seen["canonical"] = {name: dialog.controls[name][1].get() for name in ("Method", "Operation", "Smoothing")}
            seen["notes"] = [note.cget("text") for note in dialog.curve_notes]
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["recipe"] = dialog.result[1]
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertEqual(seen["captions"]["Operation"], "Operazione")
        self.assertEqual(seen["captions"]["Smoothing"], "Smussamento")
        self.assertEqual(seen["captions"]["Baseline"], "Riferimento")
        self.assertEqual(seen["captions"]["Initial integral"], "Integrale iniziale")
        self.assertEqual(seen["captions"]["Half-window"], "Semilarghezza")
        self.assertEqual(seen["captions"]["Polynomial degree"], "Grado del polinomio")
        self.assertEqual(seen["choices"]["Method"], ("LOWESS", "Deriva", "Integrale cumulativo", "Pipeline della curva"))
        self.assertEqual(seen["choices"]["Operation"], ("Identità", "Differenza prima", "Differenza seconda",
                                                        "Integrale cumulato (trapezi)"))
        self.assertEqual(seen["choices"]["Smoothing"], ("Nessuno", "Savitzky–Golay"))
        self.assertEqual(seen["shown"], {"Method": "Pipeline della curva", "Operation": "Integrale cumulato (trapezi)",
                                         "Smoothing": "Savitzky–Golay"})
        self.assertEqual(seen["canonical"], {"Method": cp.PIPELINE, "Operation": cp.CUMULATIVE,
                                             "Smoothing": cp.SAVITZKY_GOLAY})
        self.assertIn("blocchi", seen["notes"][0])
        self.assertIn("equidistanti", seen["notes"][1])
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["recipe"]["Method"], cp.PIPELINE)
        self.assertEqual(seen["recipe"]["Operation"], cp.CUMULATIVE)

    def test_both_italian_notes_fit_in_the_page_at_1024_by_768(self):
        self.use("it")

        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Operation", cp.CUMULATIVE), ("Smoothing", cp.SAVITZKY_GOLAY)))
            seen["inside"] = self.notes_inside_the_page(dialog)

        seen = self.open(act)
        self.assertEqual(seen["inside"], [True, True])

    def test_decimal_comma_and_italian_banners(self):
        self.use("it")

        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Operation", cp.CUMULATIVE), ("Baseline", "3,5"),
                                     ("Initial integral", "1,25")))
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["recipe"] = dialog.result[1] if dialog.result else None
            self.set_fields(dialog, (("Operation", cp.IDENTITY), ("Smoothing", cp.SAVITZKY_GOLAY),
                                     ("Polynomial degree", "5")))
            seen["degree"] = self.attempt(dialog)
            self.set_fields(dialog, (("Polynomial degree", "2"), ("Half-window", "x")))
            seen["window"] = self.attempt(dialog)
            self.set_fields(dialog, (("Half-window", "99999999999999999999"),))
            seen["huge"] = self.attempt(dialog)
            self.set_fields(dialog, (("Half-window", "2"), ("X", "")))
            seen["pick"] = self.attempt(dialog)
            self.set_fields(dialog, (("X", "X"), ("Smoothing", "None"), ("Baseline", "abc"), ("Operation", cp.CUMULATIVE)))
            seen["baseline"] = self.attempt(dialog)
            seen["keep"] = None

        seen = self.open(act)
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual((seen["recipe"]["Baseline"], seen["recipe"]["Initial integral"]), (3.5, 1.25))
        self.assertEqual(seen["degree"], (False, "Il grado del polinomio deve essere un numero intero da 0 a 4 per questa "
                                                 "semilarghezza."))
        self.assertEqual(seen["window"], (False, "Semilarghezza deve essere un numero intero."))
        self.assertEqual(seen["huge"], (False, "Semilarghezza supera l’intervallo degli interi supportato."))
        self.assertEqual(seen["pick"], (False, "Scegli una colonna per X."))
        self.assertEqual(seen["baseline"], (False, "Riferimento deve essere un numero."))

    def test_an_uneven_grid_is_reported_in_italian_on_the_smoothing_field(self):
        self.use("it")

        def act(dialog, seen):
            self.set_fields(dialog, (("Method", cp.PIPELINE), ("Smoothing", cp.SAVITZKY_GOLAY)))
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = None

        seen = self.open(act, frame=irregular())
        self.assertFalse(seen["ok"])
        self.assertEqual(seen["message"], "Smussamento: Savitzky–Golay richiede valori di X equidistanti; i passi del "
                                          "blocco 1 si discostano dal passo mediano per più di 1e-10 di esso.")


class Messages(LanguageMixin, unittest.TestCase):
    def triggers(self):
        """(call, field) for every message of the engine."""
        base = pd.DataFrame({"X": [0., 1, 2, 3, 4, 5], "Y": [1., 3, 2, 5, 4, 6]})
        options = {"X": "X", "Y": "Y", "Method": cp.PIPELINE}

        def call(frame, **changes):
            return lambda: analyse(METHOD, frame, {**options, **changes})

        gaps = pd.DataFrame({"X": [0., 1, 2, 3], "Y": [1., None, 3, None]})
        huge = pd.DataFrame({"X": [0., 1, 2], "Y": [1e308, -1e308, 1e308]})
        yield call(base, X="Q"), "X"
        yield call(base, Y="X"), "Y"
        yield call(base, Operation="Third"), "Operation"
        yield call(base, Smoothing="Gaussian"), "Smoothing"
        yield call(base, Operation=cp.CUMULATIVE, Baseline="x"), "Baseline"
        yield call(base, Operation=cp.CUMULATIVE, **{"Initial integral": float("inf")}), "Initial integral"
        yield call(base, Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": 0}), "Half-window"
        yield call(base, Smoothing=cp.SAVITZKY_GOLAY, **{"Polynomial degree": 5}), "Polynomial degree"
        yield call(base.assign(X=["0", "1", "two", "3", "4", "5"])), "X"
        yield call(base.assign(Y=[1, np.inf, 3, 4, 5, 6])), "Y"
        yield call(base.assign(Y=pd.to_datetime(["2024-01-01"] * 6))), "Y"
        yield call(base.assign(X=[0., 1, 1, 3, 4, 5])), "X"
        yield call(pd.DataFrame({"X": [0., 1], "Y": [None, None]})), "Y"
        yield call(gaps, Operation=cp.FIRST), "Operation"
        yield call(huge, Operation=cp.FIRST), "Operation"
        yield call(base, Smoothing=cp.SAVITZKY_GOLAY, **{"Half-window": 3}), "Half-window"
        yield call(pd.DataFrame({"X": [0, 1, 2, 3, 4.5, 6, 7.], "Y": range(7)}), Smoothing=cp.SAVITZKY_GOLAY), "Smoothing"
        yield call(pd.DataFrame({"X": np.zeros(cp.MAX_ROWS + 1), "Y": np.zeros(cp.MAX_ROWS + 1)})), "X"
        duplicated = pd.DataFrame(np.column_stack([base["X"], base["X"], base["Y"]]), columns=["X", "X", "Y"])
        yield call(duplicated), "X"

    @staticmethod
    def key_of(english):
        """The catalog key the translator picks for an English message: the first template, in order, that fits."""
        for key, template in EN.items():
            pattern = re.sub(r"\\\{\w+\\\}", ".+", re.escape(template))
            if key.startswith(ERROR_PREFIX) and re.fullmatch(pattern, english):
                return key

    def test_every_engine_message_has_an_italian_text_with_its_values_copied(self):
        used = set()
        for call, field in self.triggers():
            with self.assertRaises(FieldError) as caught:
                call()
            self.assertEqual(caught.exception.field, field, str(caught.exception))
            english = translate_error(caught.exception)
            self.assertEqual(english, str(caught.exception))
            self.use("it")
            italian = translate_error(caught.exception)
            self.use("en")
            self.assertNotEqual(italian, english, english)
            self.assertNotIn("{", italian)
            used.add(self.key_of(english))
        engine = {key for key in EN if key.startswith(ERROR_PREFIX)} - DIALOG_ONLY
        self.assertEqual(used, engine)

    def test_values_inside_messages_are_inserted_literally(self):
        self.use("it")
        text = translate_error(FieldError("X", "Column {x} has text instead of a number at row 3."))
        self.assertEqual(text, "La colonna {x} contiene testo al posto di un numero alla riga 3.")
        self.assertEqual(translate_error(FieldError("X", "The curve pipeline supports up to 200,000 worksheet rows; "
                                                           "this sheet has 200,001.")),
                         "La pipeline della curva accetta fino a 200.000 righe del foglio; questo foglio ne ha 200.001.")
        self.assertEqual(translate_error(FieldError("Operation", "No block has enough points for Second difference: "
                                                                 "the first difference needs two, the second "
                                                                 "difference three.")),
                         "Nessun blocco ha abbastanza punti per Differenza seconda: la differenza prima ne richiede "
                         "due, la differenza seconda tre.")

    def test_the_field_is_named_once_and_only_when_the_message_does_not(self):
        self.assertEqual(describe_error(FieldError("Smoothing", "Something went wrong.")), "Smoothing: Something went wrong.")
        self.assertEqual(describe_error(FieldError("Half-window", "Half-window must be a whole number from 1 to 50.")),
                         "Half-window must be a whole number from 1 to 50.")
        self.use("it")
        self.assertEqual(describe_error(FieldError("Half-window", "Half-window must be a whole number from 1 to 50.")),
                         "Semilarghezza deve essere un numero intero da 1 a 50.")
        self.assertEqual(describe_error(FieldError("Operation", "Unknown text")), "Operazione: Unknown text")

    def test_the_catalog_keys_exist_in_both_languages_with_the_same_placeholders(self):
        self.assertEqual(set(EN), set(IT))
        for key in EN:
            self.assertEqual(CATALOGS["en"][key], EN[key])
            self.assertEqual(CATALOGS["it"][key], IT[key])
            self.assertEqual(placeholders(EN[key]), placeholders(IT[key]), key)
            self.assertNotEqual(EN[key], IT[key], key)

    def test_captions_and_choices_have_an_italian_text(self):
        self.use("it")
        expected = {"Curve pipeline": "Pipeline della curva", "Identity": "Identità", "First difference": "Differenza prima",
                    "Second difference": "Differenza seconda", "Cumulative trapezoid": "Integrale cumulato (trapezi)",
                    "Smoothing": "Smussamento", "Savitzky–Golay": "Savitzky–Golay", "Initial integral": "Integrale iniziale",
                    "Half-window": "Semilarghezza", "Polynomial degree": "Grado del polinomio", "Operation": "Operazione",
                    "None": "Nessuno", "Baseline": "Riferimento"}
        for english, italian in expected.items():
            self.assertEqual(i18n.ui(english), italian, english)
        self.use("en")
        for english in expected:
            self.assertEqual(i18n.ui(english), english)


if __name__ == "__main__":
    unittest.main()
