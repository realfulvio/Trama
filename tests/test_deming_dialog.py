"""The real Analyze dialog for Deming regression: tabs, hidden fields, recipes, errors and EN/IT text."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import deming_dialog, i18n
from analisi.deming import (KNOWN_SDS, PAIRED, VARIANCE_RATIO, analyse_fit, project_points, read_settings)
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders, translate_message
from tests.test_graph_i18n import LanguageMixin, TkCase

METHOD = "Deming regression"
NAN = np.nan
FRAME = pd.DataFrame({"Dose": [0., 1, 2, 4, 7, 9], "A": [4., 3, 7, 7, 15, 17], "B $": [8., NAN, 6, 3, 1, 0],
                      "Short": [1., NAN, 2, NAN, NAN, NAN], "Flat": [3.] * 6})
LEGACY = {"X": "Dose", "Y": "A", "Y / X error variance": 1.0, "Parameter intervals": "None", "Identity line": False}


class DialogCase(TkCase):
    frame = FRAME

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
        AnalysisDialog(self.root, (self.frame if frame is None else frame).copy(),
                       current=(METHOD, recipe) if recipe else None, only=METHOD)
        self.root.withdraw()
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def attempt(dialog):
        with patch("tramastat.messagebox.showerror") as banner:
            ok = dialog.validate()
        return ok, banner.call_args.args[1] if banner.called else None

    @staticmethod
    def tabs(dialog):
        return [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]

    @staticmethod
    def shown(dialog, name):
        return any(widget.winfo_manager() == "grid" for widget in dialog.field_rows[name])

    @staticmethod
    def pick(dialog, *names):
        box = dialog.controls["Y series"][1]
        box.selection_clear(0, "end")
        columns = list(box.get(0, "end"))
        for name in names:
            box.selection_set(columns.index(name))

    @staticmethod
    def known(dialog, x_sd="2", y_sd="1"):
        dialog.controls["Uncertainty input"][1].set("Known SDs")
        dialog.controls["X error SD"][1].set(x_sd)
        dialog.controls["Y error SD"][1].set(y_sd)
        dialog.update()


class EnglishDialog(DialogCase):
    def test_pages_defaults_and_the_historical_recipe(self):
        def act(dialog, seen):
            seen["tabs"] = self.tabs(dialog)
            seen["captions"] = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
            seen["visible"] = {name: self.shown(dialog, name) for name in dialog.controls}
            seen["note"] = dialog.deming_sd_note.winfo_manager()
            seen["series_box"] = dialog.controls["Y series"][1].winfo_class()
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]
            seen["processed"] = dialog.processing_result

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Variables", "Uncertainty", "Output"])
        self.assertEqual(list(seen["captions"]), ["X", "Y", "Y series", "Uncertainty input", "Y / X error variance",
                                                  "X error SD", "Y error SD", "Show projections", "Parameter intervals",
                                                  "Confidence level (%)", "Identity line"])
        self.assertEqual(seen["captions"]["Y series"], "Y series")
        self.assertEqual({name for name, shown in seen["visible"].items() if not shown},
                         {"X error SD", "Y error SD", "Confidence level (%)"})
        self.assertEqual(seen["note"], "")
        self.assertEqual(seen["series_box"], "Listbox")
        self.assertTrue(seen["ok"])
        # Nothing of 0.93 reaches a recipe that does not use it, and the historical path runs as usual.
        self.assertEqual(seen["recipe"], LEGACY)
        self.assertIsNone(seen["processed"])

    def test_known_sds_show_the_sds_and_the_note_and_hide_the_ratio(self):
        def act(dialog, seen):
            self.known(dialog)
            seen["visible"] = {name: self.shown(dialog, name) for name in dialog.controls}
            seen["note"] = dialog.deming_sd_note.winfo_manager()
            dialog.controls["Uncertainty input"][1].set("Variance ratio")
            dialog.update()
            seen["back"] = self.shown(dialog, "Y / X error variance"), dialog.deming_sd_note.winfo_manager()

        seen = self.open(act)
        self.assertTrue(seen["visible"]["X error SD"] and seen["visible"]["Y error SD"])
        self.assertFalse(seen["visible"]["Y / X error variance"])
        self.assertEqual(seen["note"], "grid")
        self.assertEqual(seen["back"], (True, ""))

    def test_the_level_follows_the_interval_method(self):
        def act(dialog, seen):
            seen["off"] = self.shown(dialog, "Confidence level (%)")
            dialog.controls["Parameter intervals"][1].set("Jackknife (t)")
            dialog.update()
            seen["on"] = self.shown(dialog, "Confidence level (%)")

        seen = self.open(act)
        self.assertEqual((seen["off"], seen["on"]), (False, True))

    def test_the_new_recipe_keeps_what_the_user_chose_and_leaves_the_ratio_out(self):
        def act(dialog, seen):
            self.known(dialog, "2", "1")
            self.pick(dialog, "A", "B $")
            dialog.controls["Show projections"][1].set(True)
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]
            seen["processed"] = dialog.processing_result

        seen = self.open(act)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], {"X": "Dose", "Y": "A", "Y series": ["A", "B $"],
                                          "Uncertainty input": "Known SDs", "X error SD": 2.0, "Y error SD": 1.0,
                                          "Show projections": True, "Parameter intervals": "None",
                                          "Identity line": False})
        result = seen["processed"]
        self.assertEqual(list(result.tables["Deming regression"]["Series"]), ["A", "B $"])
        self.assertIn("Projected X", result.tables["Pairs"])

    def test_y_series_keeps_the_column_order_of_the_worksheet(self):
        def act(dialog, seen):
            self.pick(dialog, "B $", "A")
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["recipe"]["Y series"], ["A", "B $"])

    def test_a_single_y_with_projections_runs_the_analysis_in_the_dialog(self):
        def act(dialog, seen):
            dialog.controls["Show projections"][1].set(True)
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["processed"] = dialog.processing_result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["recipe"]["Show projections"], True)
        self.assertNotIn("Y series", seen["recipe"])
        pairs = seen["processed"].tables["Pairs"]
        self.assertEqual(list(pairs.columns)[-2:], ["Projected X", "Projected Y"])
        self.assertNotIn("Series", pairs)

    def test_errors_stay_in_the_dialog_on_their_field_and_page(self):
        def act(dialog, seen):
            self.known(dialog, "2", "0")
            seen["zero"] = self.attempt(dialog) + (self.tabs(dialog)[dialog.fields.index(dialog.fields.select())],
                                                   dialog.initial_focus is dialog.field_rows["Y error SD"][1])
            dialog.controls["Y error SD"][1].set("abc")
            seen["text"] = self.attempt(dialog)
            dialog.controls["Y error SD"][1].set("1e200")
            dialog.controls["X error SD"][1].set("1e-200")
            seen["range"] = self.attempt(dialog)
            self.known(dialog, "2", "1")
            self.pick(dialog, "A", "Short")
            seen["short"] = self.attempt(dialog) + (self.tabs(dialog)[dialog.fields.index(dialog.fields.select())],)
            self.pick(dialog, "Flat")
            seen["flat"] = self.attempt(dialog)
            self.pick(dialog, "A", "B $")
            seen["fixed"] = dialog.validate()
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertEqual(seen["zero"][:2], (False, "Y error SD must be finite and greater than 0."))
        self.assertEqual(seen["zero"][2], "Uncertainty")
        self.assertEqual(seen["text"], (False, "Y error SD must be a number."))
        self.assertEqual(seen["range"][0], False)
        self.assertIn("cannot be represented", seen["range"][1])
        self.assertEqual(seen["short"][:2], (False, 'Series "Short" has 2 complete pairs of X and Y; '
                                                    "at least 3 are needed."))
        self.assertEqual(seen["short"][2], "Variables")
        self.assertEqual(seen["flat"], (False, 'Series "Flat" cannot be fitted: X and Y must both vary, '
                                               "with a nonzero covariance."))
        self.assertTrue(seen["fixed"])

    def test_the_historical_checks_keep_their_fields(self):
        def act(dialog, seen):
            dialog.controls["Y / X error variance"][1].set("0")
            seen["ratio"] = self.attempt(dialog)
            dialog.controls["Y / X error variance"][1].set("1")
            dialog.controls["Parameter intervals"][1].set("Jackknife (t)")
            dialog.controls["Confidence level (%)"][1].set("100")
            seen["level"] = self.attempt(dialog)

        seen = self.open(act)
        self.assertEqual(seen["ratio"], (False, "Y / X error variance must be finite and greater than 0."))
        self.assertEqual(seen["level"], (False, "Confidence level (%) must be finite and strictly between 0 and 100."))

    def test_a_saved_recipe_reopens_with_its_values_and_is_saved_unchanged(self):
        saved = {"X": "Dose", "Y": "A", "Y series": ["A", "B $"], "Uncertainty input": "Known SDs",
                 "X error SD": 2.0, "Y error SD": 1.0, "Show projections": True, "Parameter intervals": "None",
                 "Identity line": True}

        def act(dialog, seen):
            seen["box"] = [dialog.controls["Y series"][1].get(i) for i in dialog.controls["Y series"][1].curselection()]
            seen["input"] = dialog.controls["Uncertainty input"][1].get()
            seen["sds"] = dialog.controls["X error SD"][1].get(), dialog.controls["Y error SD"][1].get()
            seen["ratio_shown"] = self.shown(dialog, "Y / X error variance")
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, recipe=saved)
        self.assertEqual(seen["box"], ["A", "B $"])
        self.assertEqual((seen["input"], seen["sds"], seen["ratio_shown"]), ("Known SDs", ("2.0", "1.0"), False))
        self.assertEqual(seen["recipe"], saved)

    def test_a_recipe_from_an_earlier_version_is_saved_exactly_as_it_was(self):
        old = {"X": "Dose", "Y": "B $", "Y / X error variance": 0.25, "Parameter intervals": "Jackknife (t)",
               "Confidence level (%)": 90.0, "Identity line": True}

        def act(dialog, seen):
            seen["input"] = dialog.controls["Uncertainty input"][1].get()
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, recipe=old)
        self.assertEqual(seen["input"], "Variance ratio")
        self.assertEqual(seen["recipe"], old)

    def test_a_decimal_comma_is_accepted_for_the_sds(self):
        def act(dialog, seen):
            self.known(dialog, "2,5", "1,25")
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual((seen["recipe"]["X error SD"], seen["recipe"]["Y error SD"]), (2.5, 1.25))


class ItalianDialog(DialogCase):
    def test_captions_tabs_choices_and_errors_are_italian_while_recipes_stay_canonical(self):
        self.use("it")

        def act(dialog, seen):
            seen["tabs"] = self.tabs(dialog)
            seen["captions"] = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
            self.known(dialog, "2", "0")
            seen["input_label"] = dialog.choice_bindings["Uncertainty input"].combobox.get()
            seen["input_value"] = dialog.controls["Uncertainty input"][1].get()
            seen["choices"] = dialog.choice_bindings["Uncertainty input"].combobox.cget("values")
            seen["zero"] = self.attempt(dialog)
            self.known(dialog, "2", "1")
            self.pick(dialog, "A", "Short")
            seen["short"] = self.attempt(dialog)
            seen["note"] = dialog.deming_sd_note.cget("text")
            self.pick(dialog, "A")
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Variabili", "Incertezza", "Risultati"])
        self.assertEqual(seen["captions"]["Y series"], "Serie Y")
        self.assertEqual(seen["captions"]["Uncertainty input"], "Specifica dell’incertezza")
        self.assertEqual(seen["captions"]["Show projections"], "Mostra le proiezioni")
        self.assertEqual(seen["captions"]["X error SD"], "SD dell’errore X")
        self.assertEqual((seen["input_label"], seen["input_value"]), ("SD note", "Known SDs"))
        self.assertEqual(seen["choices"], ("Rapporto tra le varianze", "SD note"))
        self.assertEqual(seen["zero"], (False, "SD dell’errore Y: deve essere un numero finito maggiore di 0."))
        self.assertEqual(seen["short"], (False, 'La serie "Short" ha 2 coppie complete di X e Y; '
                                                "ne servono almeno 3."))
        self.assertIn("SD dell’errore di misura", seen["note"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"]["Uncertainty input"], "Known SDs")


def triggers():
    """(call, field) for each message of the engine that carries a catalog entry."""
    frame = FRAME.copy()
    frame["Text"] = list("abcdef")
    frame["Blank"] = [NAN] * 6
    base = {"X": "Dose", "Y": "A", "Y / X error variance": 1.0}
    known = {**base, "Uncertainty input": "Known SDs", "X error SD": 2.0, "Y error SD": 1.0}
    many = {"X": "Dose", "Y": "A", "Y / X error variance": 1.0}

    def fit(options, data=frame):
        return lambda: analyse_fit(data, options)

    yield fit({**known, "Y error SD": 0}), "Y error SD"
    yield fit({key: value for key, value in known.items() if key != "X error SD"}), "X error SD"
    yield fit({**known, "X error SD": 1e-200, "Y error SD": 1e200}), "Y error SD"
    yield fit({**base, "Uncertainty input": "Bayes"}), "Uncertainty input"
    yield fit({**base, "Show projections": "yes"}), "Show projections"
    yield fit({**base, PAIRED: "yes"}), PAIRED
    yield fit({**base, "Y series": ["A"], PAIRED: True}), PAIRED
    yield fit({**base, "Y series": ["A"], "Parameter intervals": "Bootstrap"}), "Parameter intervals"
    yield fit({**base, "Y series": ["A"], "Parameter intervals": "Jackknife (t)", "Confidence level (%)": 100}), \
        "Confidence level (%)"
    yield fit({**base, "Y series": "A"}), "Y series"
    yield fit({**many, "Y series": [f"c{i}" for i in range(13)]}), "Y series"
    yield fit({**base, "Y series": ["A", "A"]}), "Y series"
    yield fit({**base, "Y series": ["Dose"]}), "Y series"
    yield fit({**base, "Y series": ["Nope"]}), "Y series"
    yield fit({**base, "X": "Nope", "Y series": ["A"]}), "X"
    yield fit({**base, "Y series": ["Short"]}), "Y series"
    yield fit({**base, "Y series": ["Flat"]}), "Y series"
    yield fit({**base, "Y series": ["Text"]}), "Y series"
    yield fit({**base, "Y series": ["Blank"]}), "Y series"
    yield (lambda: analyse_fit(pd.DataFrame({"x": [1e307, 2e307, -1e307, 0.0], "y": [-1e307, 1e307, 2e307, 5.0]}),
                               {"X": "x", "Y": "y", "Y / X error variance": 1.0, "Y series": ["y"],
                                "Show projections": True})), "Y series"
    yield fit({**base, "Show projections": True, "Y / X error variance": 0}), "Y / X error variance"
    yield fit({**{k: v for k, v in base.items() if k != "Y / X error variance"}, "Y series": ["A"]}), \
        "Y / X error variance"


class Catalog(LanguageMixin, unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        keys = [key for key in CATALOGS["en"] if key.startswith("deming.")]
        self.assertGreaterEqual(len(keys), 25)
        for key in keys:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)

    def test_every_engine_message_has_exactly_one_template_and_changes_in_italian(self):
        self.use("it")
        seen = set()
        for call, field in triggers():
            with self.assertRaises(FieldError) as raised:
                call()
            error = raised.exception
            self.assertEqual(error.field, field, str(error))
            keys = [key for key, pattern in i18n._message_patterns("deming.error.") if pattern.match(str(error))]
            self.assertEqual(len(keys), 1, (str(error), keys))
            self.assertNotEqual(deming_dialog.format_error(error, field), str(error), str(error))
            seen.add(keys[0])
        # Dialog-level messages, historical messages and defensive ones are exercised elsewhere.
        elsewhere = {"deming.error.number", "deming.error.finite", "deming.error.pairs", "deming.error.vary",
                     "deming.error.positive", "deming.error.series_range", "deming.error.series_data",
                     "deming.error.projected", "deming.error.series_projected"}
        every = {key for key in CATALOGS["en"] if key.startswith("deming.error.")}
        self.assertEqual(every - seen - elsewhere, set())

    def test_generic_and_historical_messages_translate(self):
        self.use("it")
        self.assertEqual(deming_dialog.format_error(ValueError("X error SD must be a number."), "X error SD"),
                         "SD dell’errore X: deve essere un numero.")
        self.assertEqual(deming_dialog.format_error(ValueError("Y / X error variance must be finite."),
                                                    "Y / X error variance"),
                         "Varianza dell’errore Y / X: deve essere finito.")
        self.assertEqual(
            deming_dialog.format_error(ValueError("Deming regression needs varying variables with nonzero "
                                                  "covariance."), None),
            "La regressione di Deming richiede variabili che variano, con covarianza diversa da zero.")
        self.assertEqual(translate_message('Series "x {y}" contains non-numeric or infinite data.', "deming.error."),
                         'La serie "x {y}" contiene dati non numerici o infiniti.')
        self.assertEqual(deming_dialog.format_error(FieldError("Show projections",
                                                               "The projected points are outside the representable "
                                                               "range."), "Show projections"),
                         "Mostra le proiezioni: I punti proiettati sono fuori dall’intervallo rappresentabile.")
        self.use("en")
        self.assertEqual(deming_dialog.format_error(FieldError("Y series", "Y series must be a list of column "
                                                                           "names."), "Y series"),
                         "Y series must be a list of column names.")

    def test_the_two_new_choices_are_translated_and_canonical_values_are_stable(self):
        self.assertEqual((VARIANCE_RATIO, KNOWN_SDS), ("Variance ratio", "Known SDs"))
        self.use("it")
        self.assertEqual((i18n.ui("Variance ratio"), i18n.ui("Known SDs")), ("Rapporto tra le varianze", "SD note"))
        self.assertEqual(i18n.ui("Uncertainty"), "Incertezza")

    def test_helpers_of_the_dialog(self):
        self.assertEqual(deming_dialog.visibility("Known SDs", "None"),
                         {"Y / X error variance": False, "X error SD": True, "Y error SD": True,
                          "Confidence level (%)": False})
        self.assertEqual(deming_dialog.visibility("Variance ratio", "Jackknife (t)")["Confidence level (%)"], True)
        self.assertFalse(deming_dialog.extended({"Y series": [], "Show projections": False}))
        self.assertTrue(deming_dialog.extended({"Y series": ["A"]}))
        options = {"Uncertainty input": "Variance ratio", "Y series": [], "Show projections": False, "X": "x"}
        self.assertEqual(deming_dialog.prune_options(dict(options), {}), {"X": "x"})
        self.assertEqual(deming_dialog.prune_options(dict(options), {"Y series": ["A"]}),
                         {"X": "x", "Y series": []})
        self.assertEqual(read_settings(FRAME, {"X": "Dose", "Y": "A", "Y / X error variance": 1.0}).ratio, 1.0)
        self.assertEqual(project_points([0.0], [1.0], 1.0, 0.0, 1.0)[0][0], 0.5)


if __name__ == "__main__":
    unittest.main()
