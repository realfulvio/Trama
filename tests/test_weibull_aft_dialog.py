"""The real Analyze dialog for Weibull AFT regression: pages, hidden fields, editors, EN/IT messages and recipes."""
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import i18n
from analisi import weibull_aft as engine
from analisi import weibull_aft_workbench as workbench
from analisi.competing_risks_dialog import TimeListEditor
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders, translate_message
from analisi.weibull_aft_dialog import TimesEditor, caption, describe_error, translate_error
from analisi.weibull_aft_text import ERRORS, ERROR_PREFIX
from tests.test_graph_i18n import LanguageMixin, TkCase

DATA = Path(__file__).resolve().parent / "data" / "weibull_aft"
METHOD = workbench.WEIBULL_AFT
FOLLOW_UP = pd.read_csv(DATA / "follow-up.csv")
RECIPE = {"Time": "Time", "Event": "Status", "Event value": "event", "Censor value": "censored",
          "Predictors": ["Treatment"], "Categorical predictors": [], "Shape mode": "Estimated ML",
          "Confidence level (%)": 95.0, "Profiles": [], "Times": [], "Show graph": False}

SAMPLES = {"field": "Show graph", "graph": "Show graph", "role": "Time", "first": "Time", "name": "Dose", "value": "3", "row": "4",
           "limit": "40,000", "count": "40,001", "shown": "abc", "term": "Dose [B]", "low": "0.05", "high": "50",
           "position": "2", "previous": "5", "number": "2", "predictor": "Dose", "levels": "A, B"}
CAPTIONS_IT = {"field": "Mostra il grafico", "graph": "Mostra il grafico", "role": "Tempo", "first": "Tempo"}
GROUPED_IT = {"limit": "40.000", "count": "40.001"}
# Defensive messages: the screens in front of them (identification, conditioning, finiteness) catch every input
# that could reach them.
DEFENSIVE = {"diverged", "not_converged", "information", "not_finite"}


def cohort(n=60, seed=3):
    rng = np.random.default_rng(seed)
    group = rng.choice(["A", "B", "C"], n)
    time = rng.weibull(1.5, n) * np.exp(1 + 0.5 * (group == "B"))
    return pd.DataFrame({"t": time, "d": rng.integers(0, 2, n) | (np.arange(n) < 3), "x": rng.normal(10, 2, n),
                         "g": group, "flag": np.where(np.arange(n) % 2, "yes", "no")})


def options(**changes):
    return {"Time": "t", "Event": "d", "Event value": "1", "Censor value": "0", "Predictors": ["x", "g"],
            "Categorical predictors": ["g"], "Shape mode": "Estimated ML", **changes}


def triggers():
    """(call, field) for every message the engine can raise, through the same check the dialog runs."""
    base = cohort()
    status = FOLLOW_UP.assign(Status=lambda f: f["Status"])

    def check(frame, **changes):
        return lambda: engine.check_options(frame, options(**changes))

    def follow(frame=None, **changes):
        recipe = {**RECIPE, "Shape mode": "Fixed", "Shape": 1.5, **changes}
        return lambda: engine.check_options(status if frame is None else frame, recipe)

    def fit(frame, **changes):
        return lambda: engine.run(frame, options(**changes))

    duplicated = base.copy()
    duplicated.columns = ["t", "t", "x", "g", "flag"]
    huge = pd.DataFrame({"t": np.ones(40_001), "d": 1, "x": 0.0})
    wide = pd.DataFrame({"t": np.arange(1.0, 301), "d": 1, "g": np.arange(300) % 30})
    one_level = base.assign(g="A")
    flat = base.assign(x=4.0)
    near = base.assign(near=lambda f: f["x"] * 2 + 1e-9 * np.arange(len(f)))
    ill = base.assign(near=lambda f: f["x"] * 2 + 1e-5 * np.random.default_rng(5).normal(size=len(f)))
    hidden = base.assign(t=[np.nan] * 3 + list(base["t"][3:]), d=[1] * 3 + [0] * (len(base) - 3))
    only_b = base.assign(d=(base["g"] == "B").astype(int))
    censored = base.assign(d=lambda f: np.where(f["g"] == "C", 0, f["d"]))
    overflow = pd.DataFrame({"t": np.full(30, 1e305), "d": [1] * 6 + [0] * 24})
    nine = base.assign(**{f"v{i}": np.random.default_rng(i).normal(size=len(base)) for i in range(9)})
    profile = {"Name": "P", "Values": {"x": 10, "g": "A"}}

    yield check(base, Time=None), "Time"
    yield check(base, Time="nope"), "Time"
    yield check(duplicated), "Time"
    yield check(base, Event="t"), "Event"
    yield check(base, Predictors=["t"]), "Predictors"
    yield check(base, Predictors=["d"]), "Predictors"
    yield check(base, Predictors="x"), "Predictors"
    yield check(base, **{"Categorical predictors": ["flag"]}), "Categorical predictors"
    yield check(base, Predictors=["x", "x"]), "Predictors"
    yield check(nine, Predictors=[f"v{i}" for i in range(9)], **{"Categorical predictors": []}), "Predictors"
    yield check(huge, Predictors=["x"], **{"Categorical predictors": []}), "Time"
    yield check(base.assign(x=["a"] * len(base)), **{"Categorical predictors": ["g"]}), "Predictors"
    yield check(base.assign(x=[True, False] * 30), **{"Categorical predictors": ["g"]}), "Predictors"
    yield check(base.assign(x=np.inf)), "Predictors"
    yield check(base.assign(t=np.nan)), "Time"
    yield check(base.assign(t=[0.0] + list(base["t"][1:]))), "Time"
    yield check(base.assign(d=0)), "Event"
    yield check(base.assign(d="?")), "Event"
    yield check(base.assign(d=[2] + list(base["d"][1:]))), "Event"
    yield check(base, **{"Event value": None}), "Event value"
    yield check(base, **{"Censor value": ""}), "Censor value"
    yield check(base, **{"Event value": "yes"}), "Event value"
    yield check(base, **{"Censor value": "1"}), "Censor value"
    yield check(base.assign(d=base["d"].astype(complex))), "Event"
    yield check(wide, Time="t", Event="d", Predictors=["g"], **{"Categorical predictors": ["g"]}), "Predictors"
    yield check(one_level), "Categorical predictors"
    yield check(base.assign(Intercept=base["x"]), Predictors=["Intercept"], **{"Categorical predictors": []}), "Predictors"
    yield check(flat, Predictors=["x"], **{"Categorical predictors": []}), "Predictors"
    yield check(near, Predictors=["x", "near"], **{"Categorical predictors": []}), "Predictors"
    yield check(base.assign(x2=base["x"] * 3), Predictors=["x", "x2"], **{"Categorical predictors": []}), "Predictors"
    yield check(censored), "Predictors"
    yield check(only_b, Predictors=["g"]), "Predictors"
    yield check(hidden), "Event"
    yield fit(ill, Predictors=["x", "near"], **{"Categorical predictors": []}), "Predictors"
    yield check(base.assign(d=lambda f: np.where(f["g"] == "A", 1, f["d"]).astype(int).clip(0, 1)
                            * (f["g"] != "C")), Predictors=["g"]), "Predictors"
    yield check(base, **{"Shape mode": "Maybe"}), "Shape mode"
    yield check(base, **{"Shape mode": "Fixed", "Shape": 0}), "Shape"
    yield check(base, **{"Confidence level (%)": 100}), "Confidence level (%)"
    yield check(base, **{"Show graph": "yes"}), "Show graph"
    yield check(base, **{"Show graph": True}), "Profiles"
    yield check(base, Profiles="P"), "Profiles"
    yield check(base, Profiles=[profile] * 13), "Profiles"
    yield check(base, Profiles=[5]), "Profiles"
    yield check(base, Profiles=[{"Name": "", "Values": {}}]), "Profiles"
    yield check(base, Profiles=[profile, profile]), "Profiles"
    yield check(base, Profiles=[{"Name": "P", "Values": {"x": 1, "g": "A", "z": 1}}]), "Profiles"
    yield check(base, Profiles=[{"Name": "P", "Values": {"x": 1}}]), "Profiles"
    yield check(base, Profiles=[{"Name": "P", "Values": {"x": "high", "g": "A"}}]), "Profiles"
    yield check(base, Profiles=[{"Name": "P", "Values": {"x": 1, "g": "Z"}}]), "Profiles"
    yield check(base, Times="5"), "Times"
    yield check(base, Profiles=[profile], Times=[-1]), "Times"
    yield check(base, Profiles=[profile], Times=[3, 2]), "Times"
    yield check(base, Profiles=[{**profile, "Name": f"P{i}"} for i in range(12)],
                Times=list(np.arange(1.0, 420))), "Times"
    yield fit(base, **{"Shape mode": "Fixed", "Shape": 0.05}), None
    yield fit(base.assign(t=1.0), Predictors=[], **{"Categorical predictors": []}), "Shape mode"
    yield fit(overflow, Predictors=[], **{"Shape mode": "Fixed", "Shape": 0.05, "Categorical predictors": []}), "Time"
    yield follow(Predictors=["Time"]), "Predictors"


class CatalogTests(LanguageMixin, unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        keys = [key for key in CATALOGS["en"] if key.startswith("weibull.")]
        self.assertGreaterEqual(len(keys), 75)
        for key in keys:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)
        self.assertEqual(CATALOGS["it"]["interface.Weibull AFT regression"], "Regressione Weibull AFT")
        self.assertEqual(i18n.ui("Weibull AFT regression"), "Weibull AFT regression")

    def test_the_method_name_is_translated_for_the_menus(self):
        self.use("it")
        self.assertEqual(i18n.ui("Weibull AFT regression"), "Regressione Weibull AFT")

    def test_every_template_translates_back_from_its_english_message(self):
        self.use("it")
        for key in ERRORS:
            english, italian = CATALOGS["en"][ERROR_PREFIX + key], CATALOGS["it"][ERROR_PREFIX + key]
            for name in placeholders(english):
                english = english.replace("{%s}" % name, SAMPLES[name])
                italian = italian.replace("{%s}" % name, (CAPTIONS_IT | GROUPED_IT).get(name, SAMPLES[name]))
            self.assertEqual(translate_error(english), italian, key)

    def test_english_messages_stay_as_written(self):
        for key, (english, _) in ERRORS.items():
            message = english.format(**SAMPLES)
            self.assertEqual(translate_error(message), message, key)

    def test_a_message_of_the_engine_names_one_template_and_changes_in_italian(self):
        self.use("it")
        seen = set()
        for call, field in triggers():
            if field is None:
                call()
                continue
            with self.assertRaises(FieldError) as raised:
                call()
            error = raised.exception
            self.assertEqual(error.field, field, str(error))
            self.assertNotEqual(translate_error(error), str(error), str(error))
            keys = [key for key, pattern in i18n._message_patterns(ERROR_PREFIX) if pattern.match(str(error))]
            self.assertEqual(len(keys), 1, (str(error), keys))
            seen.add(keys[0][len(ERROR_PREFIX):])
        self.assertEqual(set(ERRORS) - seen - DEFENSIVE, set(), "messages no screen reaches")
        self.assertEqual(seen & DEFENSIVE, set())

    def test_italian_counts_use_dots_and_worksheet_text_stays_literal(self):
        self.use("it")
        self.assertEqual(translate_error('Choose an existing column for Time: "{Misura} & $x$" is not in the worksheet.'),
                         'Scegli una colonna esistente per Tempo: "{Misura} & $x$" non è nel foglio.')
        self.assertEqual(translate_error("Weibull AFT regression reads up to 40,000 rows; this worksheet has 41,000."),
                         "La regressione Weibull AFT legge fino a 40.000 righe; questo foglio ne ha 41.000.")

    def test_the_field_is_named_once_and_only_when_the_message_does_not(self):
        self.assertEqual(describe_error(FieldError("Time", 'Column "x" must be numeric.')),
                         'Time: Column "x" must be numeric.')
        self.assertEqual(describe_error(FieldError("Shape", "Shape must be a number from 0.05 to 50.")),
                         "Shape must be a number from 0.05 to 50.")
        self.use("it")
        self.assertEqual(describe_error(FieldError("Shape", "Shape must be a number from 0.05 to 50.")),
                         "Forma deve essere un numero da 0.05 a 50.")
        self.assertEqual(describe_error(FieldError("Predictors", "The Time column cannot also be a predictor.")),
                         "Predittori: La colonna del tempo non può essere anche un predittore.")
        self.assertEqual(caption("Shape mode"), "Modalità della forma")
        self.assertEqual(caption("Unlisted"), "Unlisted")

    def test_messages_of_shared_dialog_fields_use_the_common_catalog(self):
        self.use("it")
        self.assertEqual(translate_message("Weibull AFT regression", ERROR_PREFIX), "Weibull AFT regression")
        self.assertEqual(translate_error(ValueError("Select at least one column for Predictors.")),
                         i18n.ui("Select at least one column for Predictors."))


class DialogCase(TkCase):
    frame = FOLLOW_UP.assign(Dose=np.arange(16) % 5 + 1.0)

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
    def type_into(editor, text):
        editor.text.delete("1.0", "end")
        editor.text.insert("1.0", text)

    @staticmethod
    def attempt(dialog):
        with patch("tramastat.messagebox.showerror") as banner:
            ok = dialog.validate()
        return ok, banner.call_args.args[1] if banner.called else None

    @staticmethod
    def choose(dialog, label, names):
        box = dialog.controls[label][1]
        box.selection_clear(0, "end")
        listed = [box.get(i) for i in range(box.size())]
        for name in names:
            box.selection_set(listed.index(name))
        box.event_generate("<<ListboxSelect>>")
        dialog.update()

    @staticmethod
    def page(dialog):
        return dialog.fields.tab(dialog.fields.select(), "text")

    def prepare(self, dialog, predictors=("Treatment",), **changes):
        controls = dialog.controls
        for name, value in {"Time": "Time", "Event": "Status", "Event value": "event", "Censor value": "censored",
                            **changes}.items():
            controls[name][1].set(value)
        self.choose(dialog, "Predictors", list(predictors))


class EnglishDialogTests(DialogCase):
    def test_pages_defaults_and_the_recipe(self):
        def act(dialog, seen):
            controls = dialog.controls
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in controls]
            seen["defaults"] = {name: controls[name][1].get() for name in
                                ("Time", "Event value", "Censor value", "Shape mode", "Shape", "Confidence level (%)")}
            seen["kinds"] = type(controls["Times"][1]), type(controls["Profiles"][1]).__name__
            seen["shape_shown"] = bool(dialog.field_rows["Shape"][1].winfo_manager())
            self.prepare(dialog)
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Data", "Model", "Predicted survival"])
        self.assertEqual(seen["captions"], ["Time", "Event", "Event value", "Censor value", "Predictors",
                                            "Categorical predictors", "Shape mode", "Shape", "Confidence level (%)",
                                            "Profiles", "Times", "Show graph"])
        self.assertEqual(seen["defaults"], {"Time": "Time", "Event value": "1", "Censor value": "0",
                                            "Shape mode": "Estimated ML", "Shape": "1.5",
                                            "Confidence level (%)": "95.0"})
        self.assertEqual(seen["kinds"], (TimesEditor, "ProfileEditor"))
        self.assertTrue(issubclass(TimesEditor, TimeListEditor))
        self.assertFalse(seen["shape_shown"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], RECIPE)

    def test_a_wrong_role_keeps_the_error_until_the_column_is_corrected(self):
        def act(dialog, seen):
            self.prepare(dialog, ["Dose"], Time="Status", Event="Treatment", **{"Event value": "1", "Censor value": "0"})
            seen["wrong"] = self.attempt(dialog)
            seen["page"] = self.page(dialog)
            seen["focus"] = dialog.initial_focus is dialog.field_rows["Time"][1]
            seen["again"] = self.attempt(dialog)
            dialog.controls["Time"][1].set("Time")
            seen["fixed"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]
            dialog.controls["Event value"][1].set("event")
            seen["code"] = self.attempt(dialog)
            seen["code_focus"] = dialog.initial_focus is dialog.field_rows["Event value"][1]

        seen = self.open(act)
        self.assertEqual(seen["wrong"], (False, 'Time: Column "Status" contains non-numeric or infinite data.'))
        self.assertEqual(seen["page"], "Data")
        self.assertTrue(seen["focus"])
        self.assertEqual(seen["again"], seen["wrong"])
        self.assertEqual(seen["fixed"], (True, None))
        self.assertEqual((seen["recipe"]["Time"], seen["recipe"]["Event"]), ("Time", "Treatment"))
        self.assertEqual(seen["code"], (False, 'Event value must be a number because column "Treatment" is numeric.'))
        self.assertTrue(seen["code_focus"])

    def test_shape_belongs_to_the_fixed_mode_and_a_hidden_shape_is_neither_checked_nor_saved(self):
        def act(dialog, seen):
            self.prepare(dialog)
            dialog.controls["Shape"][1].set("nonsense")
            seen["estimated"] = dialog.validate()
            seen["estimated_recipe"] = dict(dialog.result[1])
            dialog.controls["Shape mode"][1].set("Fixed")
            dialog.update()
            seen["shown"] = bool(dialog.field_rows["Shape"][1].winfo_manager())
            seen["fixed"] = self.attempt(dialog)
            seen["page"] = self.page(dialog)
            seen["focus"] = dialog.initial_focus is dialog.field_rows["Shape"][1]
            dialog.controls["Shape"][1].set("51")
            seen["range"] = self.attempt(dialog)
            dialog.controls["Shape"][1].set("2,5")
            seen["comma"] = dialog.validate()
            seen["recipe"] = dialog.result[1]
            dialog.controls["Shape mode"][1].set("Estimated ML")
            dialog.update()
            seen["hidden"] = not dialog.field_rows["Shape"][1].winfo_manager()

        seen = self.open(act)
        self.assertTrue(seen["estimated"])
        self.assertNotIn("Shape", seen["estimated_recipe"])
        self.assertTrue(seen["shown"] and seen["hidden"])
        self.assertEqual(seen["fixed"], (False, "Shape must be a number."))
        self.assertEqual(seen["page"], "Model")
        self.assertTrue(seen["focus"])
        self.assertEqual(seen["range"], (False, "Shape must be a number from 0.05 to 50."))
        self.assertTrue(seen["comma"])
        self.assertEqual((seen["recipe"]["Shape mode"], seen["recipe"]["Shape"]), ("Fixed", 2.5))

    def test_profiles_follow_the_predictors_and_categories_come_from_the_worksheet(self):
        frame = pd.DataFrame({"Time": [1., 2, 3, 4, 5, 6], "Event": [1, 1, 1, 0, 1, 1], "Dose": [1., 2, 3, 4, 5, 6],
                              "Arm": list("ABCABC")})

        def act(dialog, seen):
            editor = dialog.controls["Profiles"][1]
            seen["before"] = editor.note.cget("text")
            self.choose(dialog, "Predictors", ["Dose", "Arm"])
            self.choose(dialog, "Categorical predictors", ["Arm"])
            seen["inputs"] = list(editor.inputs)
            seen["levels"] = tuple(editor.inputs["Arm"].get() for _ in [0]), list(
                next(w for w in editor.values_frame.winfo_children() if w.winfo_class() == "TCombobox").cget("values"))
            editor.label.set("Low dose")
            editor.inputs["Dose"].set("2,5")
            editor.inputs["Arm"].set("B")
            editor.add()
            seen["profiles"] = editor.values()
            dialog.controls["Event"][1].set("Event")
            seen["ok"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1] if dialog.result else None

        seen = self.open(act, frame=frame)
        self.assertEqual(seen["before"], "Choose the predictors on the Variables tab first.")
        self.assertEqual(seen["inputs"], ["Dose", "Arm"])
        self.assertEqual(seen["levels"][1], ["A", "B", "C"])
        self.assertEqual(seen["profiles"], [{"Name": "Low dose", "Values": {"Dose": 2.5, "Arm": "B"}}])
        self.assertEqual(seen["ok"], (True, None))
        self.assertEqual(seen["recipe"]["Profiles"], seen["profiles"])
        self.assertEqual(seen["recipe"]["Categorical predictors"], ["Arm"])

    def test_the_times_keep_what_is_typed_and_a_bad_time_selects_its_page(self):
        def act(dialog, seen):
            self.prepare(dialog)
            self.type_into(dialog.controls["Times"][1], "0\n\n1,5\n  2\nabc\n")
            seen["parsed"] = dialog.controls["Times"][1].values()
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["page"] = self.page(dialog)
            self.type_into(dialog.controls["Times"][1], "3\n2")
            seen["order"] = self.attempt(dialog)
            self.type_into(dialog.controls["Times"][1], "0\n2\n4")
            dialog.controls["Show graph"][1].set(True)
            seen["needs_profile"] = self.attempt(dialog)
            seen["profile_page"] = self.page(dialog)

        seen = self.open(act)
        self.assertEqual(seen["parsed"], [0.0, 1.5, 2.0, "abc"])
        self.assertFalse(seen["ok"])
        self.assertEqual(seen["message"], "Times: value 4 (abc) must be a finite number of 0 or more.")
        self.assertEqual(seen["page"], "Predicted survival")
        self.assertEqual(seen["order"][1], "Times: values must be strictly increasing; value 2 (2) does not follow 3.")
        self.assertEqual(seen["needs_profile"], (False, "Profiles: Show graph needs at least one profile."))
        self.assertEqual(seen["profile_page"], "Predicted survival")

    def test_the_dialog_checks_the_recipe_without_fitting_it(self):
        def act(dialog, seen):
            self.prepare(dialog)
            with patch.object(engine, "fit_weibull", side_effect=AssertionError("fitted in the dialog")), \
                    patch.object(engine, "maximise", side_effect=AssertionError("fitted in the dialog")):
                seen["ok"] = dialog.validate()
            seen["processing"] = dialog.processing_result
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertTrue(seen["ok"])
        self.assertIsNone(seen["processing"])

    def test_a_saved_recipe_reappears_unchanged(self):
        recipe = {**RECIPE, "Shape mode": "Fixed", "Shape": 2.5, "Confidence level (%)": 90.0,
                  "Profiles": [{"Name": "Treated", "Values": {"Treatment": 1}}], "Times": [0.0, 2.5, 4.0],
                  "Show graph": True}

        def act(dialog, seen):
            seen["lines"] = dialog.controls["Times"][1].raw_lines()
            seen["profiles"] = dialog.controls["Profiles"][1].values()
            seen["shape"] = dialog.controls["Shape"][1].get(), bool(dialog.field_rows["Shape"][1].winfo_manager())
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, recipe)
        self.assertEqual(seen["lines"], ["0", "2.5", "4"])
        self.assertEqual(seen["profiles"], recipe["Profiles"])
        self.assertEqual(seen["shape"], ("2.5", True))
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["recipe"], recipe)


class ItalianDialogTests(DialogCase):
    def test_captions_choices_and_hints_are_italian_while_the_recipe_stays_canonical(self):
        self.use("it")

        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
            mode = dialog.choice_bindings["Shape mode"]
            seen["mode"] = mode.combobox.cget("values"), mode.combobox.get()
            mode.display.set("Fissa")
            dialog.update()
            seen["canonical"] = dialog.controls["Shape mode"][1].get()
            seen["texts"] = [child.cget("text") for page in dialog.fields.winfo_children()
                             for child in page.winfo_children() if child.winfo_class() == "TLabel"]
            self.prepare(dialog)
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Dati", "Modello", "Sopravvivenza prevista"])
        self.assertEqual(seen["captions"], ["Tempo", "Evento", "Valore dell’evento", "Valore di censura", "Predittori",
                                            "Predittori categoriali", "Modalità della forma", "Forma",
                                            "Livello di confidenza (%)", "Profili", "Tempi", "Mostra il grafico"])
        self.assertEqual(seen["mode"], (("Stimata (massima verosimiglianza)", "Fissa"),
                                        "Stimata (massima verosimiglianza)"))
        self.assertEqual(seen["canonical"], "Fixed")
        self.assertTrue(any(text.startswith("Un rapporto dei tempi maggiore di 1") for text in seen["texts"]))
        self.assertTrue(any(text.startswith("I codici sono letti") for text in seen["texts"]))
        self.assertEqual((seen["recipe"]["Shape mode"], seen["recipe"]["Shape"]), ("Fixed", 1.5))
        self.assertEqual(seen["recipe"]["Event"], "Status")

    def test_the_banner_is_italian_names_the_field_and_keeps_worksheet_text_literal(self):
        self.use("it")

        def act(dialog, seen):
            self.prepare(dialog, ["Dose"], Time="Status", Event="Treatment", **{"Event value": "1", "Censor value": "0"})
            seen["role"] = self.attempt(dialog)
            self.prepare(dialog, ["Dose"], Event="Time")
            seen["different"] = self.attempt(dialog)
            self.prepare(dialog, **{"Censor value": "event"})
            seen["same"] = self.attempt(dialog)
            self.prepare(dialog)
            dialog.controls["Shape mode"][1].set("Fixed")
            dialog.controls["Shape"][1].set("0")
            seen["shape"] = self.attempt(dialog)
            dialog.controls["Shape mode"][1].set("Estimated ML")
            self.type_into(dialog.controls["Times"][1], "-1")
            seen["times"] = self.attempt(dialog)
            self.type_into(dialog.controls["Times"][1], "")
            dialog.controls["Show graph"][1].set(True)
            seen["graph"] = self.attempt(dialog)

        seen = self.open(act)
        self.assertEqual(seen["role"], (False, 'Tempo: La colonna "Status" contiene dati non numerici o infiniti.'))
        self.assertEqual(seen["different"], (False, "Scegli colonne diverse per Tempo e Evento."))
        self.assertEqual(seen["same"], (False, "Valore di censura: I valori di evento e di censura devono essere "
                                               "diversi."))
        self.assertEqual(seen["shape"], (False, "Forma deve essere un numero da 0.05 a 50."))
        self.assertEqual(seen["times"], (False, "Tempi: il valore 1 (-1) deve essere un numero finito pari ad "
                                                "almeno 0."))
        self.assertEqual(seen["graph"], (False, "Profili: Mostra il grafico richiede almeno un profilo."))


if __name__ == "__main__":
    unittest.main()
