"""The real Analyze dialog for Ordinal logistic regression: pages, the order editor, errors in both languages."""
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import i18n, ordinal_logit as ol
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders
from analisi.ordinal_logit_dialog import OrderEditor, caption, describe_error, merged, number, translate_error
from analisi.workbench import analyse
from tests.test_graph_i18n import LanguageMixin, TkCase

DATA = Path(__file__).resolve().parent / "data" / "ordinal_logit"
STAGES = pd.read_csv(DATA / "stages.csv")
METHOD = ol.ORDINAL_LOGIT
RECIPE = {"Response": "Stage", "Predictors": ["Treatment"], "Categorical predictors": [],
          "Category order": ["Low", "Medium", "High"], "Confidence level (%)": 95.0, "Profiles": [],
          "Show graph": False}

SAMPLES = {"limit": "40,000", "count": "40,001", "minimum": "3", "label": "Mid", "name": "Dose", "row": "4",
           "added": '"New"', "removed": '"Old"', "parameters": "6", "profile": "Control", "names": '"High"',
           "position": "2", "value": "'x'"}


def small(**changes):
    return pd.DataFrame({"y": list("abcabcabcabc"), "x": np.arange(12.), "z": [1., 0, 2, 0, 1, 3, 1, 0, 2, 2, 1, 0]},
                        ).assign(**changes)


def call(frame, **overrides):
    return lambda: ol.check_options(frame, {**RECIPE, "Response": "y", "Predictors": ["x"],
                                           "Category order": [], **overrides})


def triggers():
    """(call, field) for every message the engine can raise before the fit."""
    base, rng = small(), np.random.default_rng(3)
    wide = pd.DataFrame({"y": rng.choice(list("abc"), ol.MAX_ROWS + 1), "x": rng.random(ol.MAX_ROWS + 1)})
    many = pd.DataFrame({"y": [str(i % 13) for i in range(130)], "x": np.arange(130.)})
    levels = pd.DataFrame({"y": rng.choice(list("abc"), 600), "g": [f"L{i % 26:02d}" for i in range(600)]})
    duplicated = base.copy()
    duplicated.columns = ["y", "y", "z"]
    ok = {"Dose": 0.0}

    def profile(values, name="p"):
        return call(base, Profiles=[{"Name": name, "Values": values}])

    yield call(base, Response=None), "Response"
    yield call(base, Response="nope"), "Response"
    yield call(duplicated), "Response"
    yield call(base, Predictors=[]), "Predictors"
    yield call(base, Predictors="x"), "Predictors"
    yield call(base, Predictors=["nope"]), "Predictors"
    yield call(base, Predictors=["x", "x"]), "Predictors"
    yield call(base, Predictors=["y"]), "Predictors"
    yield call(base, **{"Categorical predictors": "x"}), "Categorical predictors"
    yield call(base, **{"Categorical predictors": ["z"]}), "Categorical predictors"
    yield call(base, **{"Confidence level (%)": 120}), "Confidence level (%)"
    yield call(base, **{"Show graph": "yes"}), "Show graph"
    yield call(base, **{"Show graph": True}), "Profiles"
    yield call(base, Profiles="p"), "Profiles"
    yield call(base, Profiles=["p"]), "Profiles"
    yield call(base, Profiles=[{"Name": "", "Values": {"x": 1}}]), "Profiles"
    yield call(base, Profiles=[{"Name": "p", "Values": {"x": 1}}] * 2), "Profiles"
    yield call(base, Profiles=[{"Name": str(i), "Values": {"x": 1}} for i in range(13)]), "Profiles"
    yield call(base, Profiles=[{"Name": "p", "Values": {}}]), "Profiles"
    yield call(base, Profiles=[{"Name": "p", "Values": {"x": 1, "other": 2}}]), "Profiles"
    yield call(base, Profiles=[{"Name": "p", "Values": {"x": "high"}}]), "Profiles"
    yield call(base.assign(s=base["z"]), Predictors=["x", "z"], **{"Categorical predictors": ["z"],
               "Profiles": [{"Name": "p", "Values": {"x": 1, "z": "9"}}]}), "Profiles"
    yield call(base.assign(x=[1.0, "a"] * 6)), "Predictors"
    yield call(base.assign(y=pd.Series([(1, 2)] * 12, dtype=object))), "Response"
    yield call(base.assign(y=[1., 2, np.inf] * 4)), "Response"
    yield call(base.assign(x=np.nan)), "Response"
    yield call(wide), "Response"
    yield call(many), "Response"
    yield call(base.assign(y=["a", "b"] * 6)), "Response"
    yield call(base.assign(y=pd.Series([1, "1", 2] * 4, dtype=object))), "Response"
    yield call(base, **{"Category order": "abc"}), "Category order"
    yield call(base, **{"Category order": ["a", "b", "b", "c"]}), "Category order"
    yield call(base, **{"Category order": ["a", "b"]}), "Category order"
    yield call(base, **{"Category order": ["a", "b", "c", "d"]}), "Category order"
    yield call(levels, Predictors=["g"], **{"Categorical predictors": ["g"]}), "Predictors"
    yield call(base.assign(**{"g [q]": base["x"], "g": list("pq") * 6}), Predictors=["g", "g [q]"],
               **{"Categorical predictors": ["g"]}), "Predictors"
    yield call(base.assign(x=2.0)), "Predictors"
    yield call(base.assign(w=base["x"] * 2), Predictors=["x", "w"]), "Predictors"
    yield call(base.assign(w=1 - base["x"]), Predictors=["x", "w"]), "Predictors"
    yield call(base.head(4), Predictors=["x", "z"]), "Predictors"
    yield call(base.assign(g="same"), Predictors=["g"], **{"Categorical predictors": ["g"]}), "Predictors"
    yield profile({"Dose": 0.0}), "Profiles"


class CatalogTests(LanguageMixin, unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        keys = [key for key in CATALOGS["en"] if key.startswith("ord.")]
        self.assertGreaterEqual(len(keys), 55)
        for key in keys:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)

    def test_every_template_translates_back_from_its_english_message(self):
        self.use("it")
        for key, english in CATALOGS["en"].items():
            if not key.startswith("ord.error."):
                continue
            message, expected = english, CATALOGS["it"][key]
            for name in placeholders(english):
                message = message.replace("{%s}" % name, SAMPLES[name])
                expected = expected.replace("{%s}" % name, number(SAMPLES[name]) if name in {
                    "limit", "count", "parameters", "minimum"} else SAMPLES[name])
            self.assertEqual(translate_error(message), expected, key)

    def test_english_messages_stay_as_written(self):
        for key, english in CATALOGS["en"].items():
            if key.startswith("ord.error."):
                message = english.format(**SAMPLES) if "{" in english else english
                self.assertEqual(translate_error(message), message, key)

    def test_a_message_of_the_engine_names_one_template_and_changes_in_italian(self):
        self.use("it")
        seen = set()
        for trigger, field in triggers():
            with self.assertRaises(FieldError) as raised:
                trigger()
            error = raised.exception
            self.assertEqual(error.field, field, str(error))
            self.assertNotEqual(translate_error(error), str(error), str(error))
            keys = [key for key, pattern in i18n._message_patterns("ord.error.") if pattern.match(str(error))]
            self.assertEqual(len(keys), 1, (str(error), keys))
            seen.add(keys[0])
        every = {key for key in CATALOGS["en"] if key.startswith("ord.error.")}
        estimation = {"ord.error." + name for name in ("separation", "converge", "covariance", "thresholds", "range")}
        dialog_only = {"ord.error.predictors_none"}  # raised by the dialog before the engine is asked
        self.assertEqual(every - seen - estimation - dialog_only, set(), "messages the triggers do not reach")

    def test_italian_counts_use_dots_and_worksheet_text_stays_literal(self):
        self.use("it")
        self.assertEqual(number("40,000"), "40.000")
        error = FieldError("Response", 'Choose an existing column for Response: "{Misura} & $x$" is not in the worksheet.')
        self.assertEqual(translate_error(error),
                         'Scegli una colonna esistente per Risposta: "{Misura} & $x$" non è nel foglio.')

    def test_the_shared_level_message_and_the_field_name(self):
        self.use("it")
        self.assertEqual(describe_error(ValueError("Confidence level (%) must be a number."), "Confidence level (%)"),
                         "Il livello di confidenza (%) deve essere un numero.")
        self.assertEqual(caption("Category order"), "Ordine delle categorie")
        self.assertEqual(caption("Predictors"), "Predittori")
        self.use("en")
        self.assertEqual(describe_error(FieldError("Predictors", "A constant column.")), "Predictors: A constant column.")
        self.assertEqual(describe_error(FieldError("Predictors", "Predictors cannot include Stage.")),
                         "Predictors cannot include Stage.")


class MergeTests(unittest.TestCase):
    def test_new_categories_follow_their_predecessor_and_vanished_ones_leave(self):
        self.assertEqual(merged(["Low", "Medium", "High"], ["Low", "Medium", "High"]), ["Low", "Medium", "High"])
        self.assertEqual(merged(["High", "Low"], ["High", "Medium", "Low"]), ["High", "Medium", "Low"])
        self.assertEqual(merged(["High", "Medium", "Low"], ["Low", "Medium"]), ["Medium", "Low"])
        self.assertEqual(merged([], ["a", "b"]), ["a", "b"])
        self.assertEqual(merged(["c", "a"], ["a", "b", "c", "d"]), ["c", "d", "a", "b"])
        self.assertEqual(merged(["b", "a"], ["z", "a", "b"]), ["z", "b", "a"])


class EditorTests(TkCase):
    def editor(self, saved=()):
        editor = OrderEditor(self.root, saved)
        self.addCleanup(editor.destroy)
        return editor

    def test_the_first_sync_proposes_the_order_unless_one_was_saved(self):
        fresh = self.editor()
        fresh.sync(["High", "Low", "Medium"], "Stage")
        self.assertEqual(fresh.values(), ["High", "Low", "Medium"])
        saved = self.editor(["Low", "Medium", "High"])
        saved.sync(["High", "Low", "Medium"], "Stage")
        self.assertEqual(saved.values(), ["Low", "Medium", "High"])

    def test_up_down_and_reset(self):
        editor = self.editor()
        editor.sync(["a", "b", "c"], "y")
        editor.listbox.selection_set(2)
        editor.move(-1)
        self.assertEqual(editor.values(), ["a", "c", "b"])
        self.assertEqual(editor.listbox.curselection(), (1,))
        editor.move(-1)
        editor.move(-1)  # already first: nothing moves
        self.assertEqual(editor.values(), ["c", "a", "b"])
        editor.reset()
        self.assertEqual(editor.values(), ["a", "b", "c"])
        editor.listbox.selection_clear(0, "end")
        editor.move(1)  # nothing selected
        self.assertEqual(editor.values(), ["a", "b", "c"])
        self.assertEqual(editor.listbox.get(0), "1. a")

    def test_a_new_response_starts_from_its_own_order_and_a_predictor_keeps_the_arrangement(self):
        editor = self.editor()
        editor.sync(["a", "b", "c"], "y")
        editor.listbox.selection_set(0)
        editor.move(1)
        self.assertEqual(editor.values(), ["b", "a", "c"])
        editor.sync(["a", "b", "c", "d"], "y")        # a predictor with fewer blanks adds a category
        self.assertEqual(editor.values(), ["b", "a", "c", "d"])
        editor.sync(["a", "c", "d"], "y")             # and a vanished one leaves
        self.assertEqual(editor.values(), ["a", "c", "d"])
        editor.sync(["x", "y"], "other")
        self.assertEqual(editor.values(), ["x", "y"])

    def test_a_saved_order_that_no_longer_matches_is_kept_and_explained(self):
        editor = self.editor(["Low", "Medium", "High"])
        editor.sync(["Low", "Critical", "High"], "Stage")
        self.assertEqual(editor.values(), ["Low", "Medium", "High"])
        note = editor.note.cget("text")
        self.assertIn('"Critical"', note)
        self.assertIn('"Medium"', note)
        editor.sync(["Low", "Critical", "High", "Extra"], "Stage")  # a stale order is still never repaired silently
        self.assertEqual(editor.values(), ["Low", "Medium", "High"])
        editor.reset()
        self.assertEqual(editor.values(), ["Low", "Critical", "High", "Extra"])
        self.assertNotIn("Critical", editor.note.cget("text"))

    def test_the_note_and_the_buttons_follow_the_state(self):
        editor = self.editor()
        self.assertEqual(editor.note.cget("text"), "Choose the response and the predictors to read its categories.")
        editor.sync(["only"], "y")
        self.assertTrue(editor.buttons["up"].instate(["disabled"]))
        editor.sync(["only", "two"], "other")
        self.assertFalse(editor.buttons["down"].instate(["disabled"]))
        self.assertIn("Up and Down", editor.note.cget("text"))


class DialogCase(TkCase):
    frame = STAGES

    def open(self, action, recipe=None, frame=None, method=METHOD):
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
                       current=(method, recipe) if recipe else None, only=method)
        self.root.withdraw()
        self.assertNotIn("error", seen, seen.get("error"))
        return seen

    @staticmethod
    def attempt(dialog):
        with patch("tramastat.messagebox.showerror") as banner:
            ok = dialog.validate()
        return ok, banner.call_args.args[1] if banner.called else None

    @staticmethod
    def choose(dialog, field, names):
        box = dialog.controls[field][1]
        box.selection_clear(0, "end")
        for index, name in enumerate(box.get(0, "end")):
            if name in names:
                box.selection_set(index)
        box.event_generate("<<ListboxSelect>>")
        dialog.update()


class EnglishDialogTests(DialogCase):
    def test_pages_defaults_and_the_recipe(self):
        def act(dialog, seen):
            controls = dialog.controls
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = {name: dialog.field_rows[name][0].cget("text") for name in controls}
            seen["pages"] = {name: dialog.fields.tab(self.page(dialog, name), "text") for name in controls}
            controls["Response"][1].set("Stage")
            self.choose(dialog, "Predictors", ["Treatment"])
            seen["order"] = controls["Category order"][1].values()
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Variables", "Options", "Profiles"])
        self.assertEqual(list(seen["captions"].values()),
                         ["Response", "Predictors", "Categorical predictors", "Category order",
                          "Confidence level (%)", "Profiles", "Show graph"])
        self.assertEqual(seen["pages"], {"Response": "Variables", "Predictors": "Variables",
                                         "Categorical predictors": "Variables", "Category order": "Variables",
                                         "Confidence level (%)": "Options", "Profiles": "Profiles",
                                         "Show graph": "Profiles"})
        self.assertEqual(seen["order"], ["High", "Low", "Medium"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], {**RECIPE, "Category order": ["High", "Low", "Medium"]})

    @staticmethod
    def page(dialog, name):
        page = dialog.field_rows[name][1].master
        while page.master is not dialog.fields:
            page = page.master
        return page

    def test_moving_a_category_reaches_the_recipe_and_the_fit(self):
        def act(dialog, seen):
            dialog.controls["Response"][1].set("Stage")
            self.choose(dialog, "Predictors", ["Treatment"])
            editor = dialog.controls["Category order"][1]
            seen["proposed"] = editor.values()
            editor.listbox.selection_set(2)
            editor.move(-1)
            editor.move(-1)
            seen["order"] = editor.values()
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertEqual(seen["proposed"], ["High", "Low", "Medium"])
        self.assertEqual(seen["order"], ["Medium", "High", "Low"])
        recipe = seen["keep"][1]
        result = analyse(METHOD, STAGES, recipe)
        self.assertEqual(list(result.tables["Thresholds"]["Lower category"]), ["Medium", "High"])

    def test_a_stale_order_stops_on_its_field_with_the_note_and_the_keyboard(self):
        recipe = {**RECIPE, "Category order": ["Low", "Medium", "High", "Critical"]}

        def act(dialog, seen):
            seen["note"] = dialog.controls["Category order"][1].note.cget("text")
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["page"] = dialog.fields.tab(dialog.fields.select(), "text")
            seen["focus"] = dialog.initial_focus is dialog.controls["Category order"][1].focus_target()
            dialog.controls["Category order"][1].reset()
            seen["fixed"] = dialog.validate()
            seen["keep"] = dialog.result

        seen = self.open(act, recipe)
        self.assertIn('"Critical"', seen["note"])
        self.assertFalse(seen["ok"])
        self.assertTrue(seen["message"].startswith("Category order must list") or "Category order" in seen["message"])
        self.assertIn('"Critical"', seen["message"])
        self.assertEqual(seen["page"], "Variables")
        self.assertTrue(seen["focus"])
        self.assertTrue(seen["fixed"])
        self.assertEqual(seen["keep"][1]["Category order"], ["High", "Low", "Medium"])

    def test_a_new_level_in_the_worksheet_is_not_absorbed_silently(self):
        frame = STAGES.copy()
        frame.loc[0, "Stage"] = "Critical"

        def act(dialog, seen):
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["note"] = dialog.controls["Category order"][1].note.cget("text")

        seen = self.open(act, RECIPE, frame)
        self.assertFalse(seen["ok"])
        self.assertIn('"Critical"', seen["message"])
        self.assertIn("New", seen["note"])
        self.assertIn('"Critical"', seen["note"])

    def test_profiles_follow_the_predictors_and_the_graph_needs_one(self):
        def act(dialog, seen):
            dialog.controls["Response"][1].set("Stage")
            self.choose(dialog, "Predictors", ["Treatment"])
            editor = dialog.controls["Profiles"][1]
            seen["predictors"] = editor.predictors
            editor.label.set("Treated")
            editor.inputs["Treatment"].set("1")
            editor.add()
            dialog.controls["Show graph"][1].set(True)
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertEqual(seen["predictors"], ["Treatment"])
        self.assertTrue(seen["ok"])
        recipe = seen["keep"][1]
        self.assertEqual(recipe["Profiles"], [{"Name": "Treated", "Values": {"Treatment": 1.0}}])
        self.assertIs(recipe["Show graph"], True)
        result = analyse(METHOD, STAGES, recipe)
        self.assertIsNotNone(result.figure)

        def graph_without_profile(dialog, seen):
            dialog.controls["Response"][1].set("Stage")
            self.choose(dialog, "Predictors", ["Treatment"])
            dialog.controls["Show graph"][1].set(True)
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["page"] = dialog.fields.tab(dialog.fields.select(), "text")

        seen = self.open(graph_without_profile)
        self.assertFalse(seen["ok"])
        self.assertEqual(seen["page"], "Profiles")
        self.assertIn("profile", seen["message"].lower())

    def test_a_selection_without_predictors_and_a_bad_level_name_their_fields(self):
        def act(dialog, seen):
            dialog.controls["Response"][1].set("Stage")
            seen["none"] = self.attempt(dialog)
            self.choose(dialog, "Predictors", ["Treatment"])
            dialog.controls["Confidence level (%)"][1].set("abc")
            seen["level"] = self.attempt(dialog)
            dialog.controls["Confidence level (%)"][1].set("99,5")
            seen["comma"] = dialog.validate()
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertFalse(seen["none"][0])
        self.assertIn("Predictors", seen["none"][1])
        self.assertFalse(seen["level"][0])
        self.assertIn("Confidence level (%)", seen["level"][1])
        self.assertTrue(seen["comma"])
        self.assertEqual(seen["keep"][1]["Confidence level (%)"], 99.5)


class SharedFieldTests(DialogCase):
    """Other analyses also have a field called Profiles: they keep their own editor and record keys."""

    def test_cox_profiles_keep_label_and_values(self):
        frame = pd.DataFrame({"Time": [1.0, 2.0, 3.0, 4.0], "Event": [1, 0, 1, 1], "Arm": ["A", "B", "A", "B"]})

        def act(dialog, seen):
            editor = dialog.controls["Profiles"][1]
            seen["keys"] = (editor.label_key, editor.values_key)
            seen["order"] = "Category order" in dialog.controls

        seen = self.open(act, frame=frame, method="Cox regression")
        self.assertEqual(seen["keys"], ("Label", "Values"))
        self.assertFalse(seen["order"])


class ItalianDialogTests(DialogCase):
    def test_captions_hints_and_errors_are_italian_and_the_recipe_stays_english(self):
        self.use("it")

        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
            editor = dialog.controls["Category order"][1]
            seen["hint"] = editor.note.cget("text")
            seen["buttons"] = [button.cget("text") for button in editor.buttons.values()]
            dialog.controls["Response"][1].set("Stage")
            seen["move"] = editor.note.cget("text")
            seen["none"] = self.attempt(dialog)
            self.choose(dialog, "Predictors", ["Treatment"])
            dialog.controls["Confidence level (%)"][1].set("120")
            seen["level"] = self.attempt(dialog)
            dialog.controls["Confidence level (%)"][1].set("95")
            seen["profiles_hint"] = dialog.controls["Profiles"][1].note.cget("text")
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Variabili", "Opzioni", "Profili"])
        self.assertEqual(seen["captions"], ["Risposta", "Predittori", "Predittori categorici", "Ordine delle categorie",
                                            "Livello di confidenza (%)", "Profili", "Mostra grafico"])
        self.assertTrue(seen["hint"].startswith("Scegli la risposta"))
        self.assertIn("Su e Giù", seen["move"])
        self.assertEqual(seen["buttons"], ["Su", "Giù", "Ripristina"])
        self.assertFalse(seen["none"][0])
        self.assertIn("predittori", seen["none"][1].lower())
        self.assertIn("Il livello di confidenza", seen["level"][1])
        self.assertIn("Fino a 12 profili", seen["profiles_hint"])
        self.assertTrue(seen["ok"])
        recipe = seen["keep"][1]
        self.assertEqual(recipe, {**RECIPE, "Category order": ["High", "Low", "Medium"]})

    def test_a_stale_order_is_explained_in_italian(self):
        self.use("it")
        recipe = {**RECIPE, "Category order": ["Low", "Medium", "High", "Critical"]}

        def act(dialog, seen):
            seen["note"] = dialog.controls["Category order"][1].note.cget("text")
            seen["ok"], seen["message"] = self.attempt(dialog)

        seen = self.open(act, recipe)
        self.assertIn("Non più usate", seen["note"])
        self.assertFalse(seen["ok"])
        self.assertIn("Critical", seen["message"])
        self.assertIn("categorie", seen["message"])


if __name__ == "__main__":
    unittest.main()
