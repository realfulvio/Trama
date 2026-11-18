"""The real Analyze dialog for Negative binomial regression: captions, choices, hidden alpha, EN/IT messages."""
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import i18n
from analisi import nb2_regression as nb
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders
from analisi.nb2_dialog import caption, describe_error, translate_error
from tests.test_graph_i18n import LanguageMixin, TkCase

DATA = Path(__file__).resolve().parent / "data" / "nb2_regression"
METHOD = nb.NB2
BATCHES = pd.read_csv(DATA / "batches.csv")
RECIPE = {"Response": "Count", "Predictors": ["Dose", "Batch"], "Categorical predictors": ["Batch"],
          "Exposure": "Exposure", "Dispersion mode": "Fixed", "Dispersion alpha": 0.8, "Confidence level (%)": 90.0,
          "Residual plot": True}

SAMPLES = {"field": "Dispersion alpha", "column": "Count", "row": "4", "value": "2.5", "rows": "50,001",
           "count": "33", "term": "Batch [B]", "alpha": "1e-06", "reason": "nearly singular"}
SHOWN_IT = {"field": "Alfa di dispersione", "rows": "50.001", "reason": "quasi singolare"}


def counts():
    return pd.read_csv(DATA / "counts.csv", keep_default_na=False).replace("", np.nan)


def options(**changes):
    return {"Response": "Count", "Predictors": ["Treatment"], "Categorical predictors": [], "Exposure": "Exposure",
            "Dispersion mode": "Fixed", "Dispersion alpha": 0.5, "Confidence level (%)": 95.0,
            "Residual plot": False, **changes}


def triggers():
    """(call, field) for every message a worksheet or a recipe can raise, before and during the fit."""
    base = counts()

    def check(frame=base, **changes):
        return lambda: nb.check_options(frame, options(**changes))

    def run(frame=base, **changes):
        return lambda: nb.analysis(frame, options(**changes))

    ml = {"Dispersion mode": "Estimated ML"}
    big = pd.DataFrame({"Count": np.ones(50_001), "Treatment": np.arange(50_001.0)})
    wide = pd.DataFrame({"Count": np.arange(200.0) % 7, "Treatment": np.arange(200.0),
                         "Batch": [f"L{i % 40:02d}" for i in range(200)]})
    collide = base.assign(**{"Batch [B]": np.arange(len(base), dtype=float)})
    separated = base.copy()
    separated.loc[separated["Treatment"] == 1, "Count"] = 0
    heavy_counts = np.zeros(1000)
    heavy_counts[0] = heavy_counts[-1] = 10_000
    heavy = pd.DataFrame({"Count": heavy_counts, "Treatment": np.r_[np.zeros(500), np.ones(500)]})

    yield check(Response=None), "Response"
    yield check(Response="nope"), "Response"
    yield check(Predictors="Treatment"), "Predictors"
    yield check(Predictors=["Treatment", "Treatment"]), "Predictors"
    yield check(**{"Dispersion alpha": "abc"}), "Dispersion alpha"
    yield check(**{"Dispersion alpha": float("inf")}), "Dispersion alpha"
    yield check(Predictors=[]), "Predictors"
    yield check(Predictors=["Count"]), "Predictors"
    yield check(**{"Categorical predictors": ["Batch"]}), "Categorical predictors"
    yield check(Exposure="Count"), "Exposure"
    yield check(**{"Dispersion mode": "Bayes"}), "Dispersion mode"
    yield check(**{"Dispersion alpha": 0.0}), "Dispersion alpha"
    yield check(**{"Confidence level (%)": 100.0}), "Confidence level (%)"
    yield check(**{"Residual plot": "yes"}), "Residual plot"
    yield check(base.assign(Treatment=base["Treatment"] + 1j)), "Predictors"
    yield check(base.assign(Count=base["Count"] + 0.5)), "Response"
    yield check(base.assign(Treatment="x")), "Predictors"
    yield check(base.assign(Exposure=-1.0)), "Exposure"
    yield check(base.assign(Count=np.nan)), "Response"
    yield check(big, Exposure=None), "Response"
    yield check(base.assign(Count=0)), "Response"
    yield check(base.assign(Batch="A"), Predictors=["Treatment", "Batch"],
                **{"Categorical predictors": ["Batch"]}), "Categorical predictors"
    yield check(wide, Exposure=None, Predictors=["Treatment", "Batch"],
                **{"Categorical predictors": ["Batch"]}), "Categorical predictors"
    yield check(base.iloc[:2]), "Predictors"
    yield check(base.assign(Double=2 * base["Treatment"]), Predictors=["Treatment", "Double"]), "Predictors"
    yield check(collide, Predictors=["Batch", "Batch [B]"], **{"Categorical predictors": ["Batch"]}), "Predictors"
    yield run(separated), "Predictors"
    yield run(separated, **ml), "Dispersion mode"
    yield run(pd.read_csv(DATA / "poisson-boundary.csv"), **ml), "Dispersion mode"
    yield run(heavy, Exposure=None, **ml), "Dispersion mode"

    def patched(owner, target, value, **changes):
        def call():
            with patch.object(owner, target, return_value=value):
                nb.analysis(base, options(**changes))
        return call

    # An information matrix that cannot be inverted: forced, since the supported data always give a usable one.
    yield patched(nb, "_alpha_curvature", 1.0, **ml), "Dispersion mode"
    yield patched(nb.np.linalg, "eigvalsh", np.array([-1.0, 1.0])), "Predictors"


class CatalogTests(LanguageMixin, unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        keys = [key for key in CATALOGS["en"] if key.startswith("nb2.")]
        self.assertGreaterEqual(len(keys), 50)
        for key in keys:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)

    def test_every_template_translates_back_from_its_english_message(self):
        self.use("it")
        for key, english in CATALOGS["en"].items():
            if not key.startswith("nb2.error."):
                continue
            message, expected = english, CATALOGS["it"][key]
            for name in placeholders(english):
                message = message.replace("{%s}" % name, SAMPLES[name])
                expected = expected.replace("{%s}" % name, SHOWN_IT.get(name, SAMPLES[name]))
            self.assertEqual(translate_error(message), expected, key)

    def test_english_messages_stay_as_written(self):
        for key, english in CATALOGS["en"].items():
            if key.startswith("nb2.error."):
                message = english.format(**SAMPLES)
                self.assertEqual(translate_error(message), message, key)

    def test_each_engine_message_names_its_field_and_one_template(self):
        self.use("it")
        seen = set()
        for call, field in triggers():
            with self.assertRaises(FieldError) as raised:
                call()
            error = raised.exception
            self.assertEqual(error.field, field, str(error))
            self.assertNotEqual(translate_error(error), str(error), str(error))
            keys = [key for key, pattern in i18n._message_patterns("nb2.error.") if pattern.match(str(error))]
            self.assertEqual(len(keys), 1, (str(error), keys))
            seen.add(keys[0])
        # Messages of the dialog itself (an empty list) and defensive guards that no supported worksheet reaches.
        unreachable = {"nb2.error.select", "nb2.error.parameters", "nb2.error.ml_finite", "nb2.error.solve",
                       "nb2.error.limit", "nb2.error.range", "nb2.error.fitted"}
        every = {key for key in CATALOGS["en"] if key.startswith("nb2.error.")}
        self.assertEqual(every - seen, unreachable)

    def test_italian_counts_use_dots_and_worksheet_text_stays_literal(self):
        self.use("it")
        self.assertEqual(translate_error("The model would use 50,001 complete rows; the limit is 50,000."),
                         "Il modello userebbe 50.001 righe complete; il limite è 50.000.")
        self.assertEqual(translate_error('Response "{Conta} & $x$" needs whole counts of 0 or more (row 3: -1).'),
                         'La risposta "{Conta} & $x$" richiede conteggi interi pari ad almeno 0 (riga 3: -1).')

    def test_the_field_is_named_once_and_only_when_the_message_does_not(self):
        self.assertEqual(describe_error(FieldError("Exposure", 'Column "x" is not in the table.')),
                         'Exposure: Column "x" is not in the table.')
        self.assertEqual(describe_error(FieldError("Dispersion alpha", "Dispersion alpha must be finite.")),
                         "Dispersion alpha must be finite.")
        self.assertEqual(describe_error(ValueError("Select at least one column for Predictors."), "Predictors"),
                         "Select at least one column for Predictors.")
        self.use("it")
        self.assertEqual(describe_error(FieldError("Dispersion alpha", "Dispersion alpha must be finite.")),
                         "Alfa di dispersione: inserisci un numero finito.")
        self.assertEqual(describe_error(FieldError("Exposure", 'Column "x" is not in the table.')),
                         'Esposizione: La colonna "x" non è nella tabella.')
        self.assertEqual(describe_error(ValueError("Select at least one column for Predictors."), "Predictors"),
                         "Seleziona almeno una colonna per Predittori.")
        self.assertEqual(caption("Dispersion mode"), "Dispersione")
        self.assertEqual(caption("Unlisted"), "Unlisted")


class DialogCase(TkCase):
    frame = BATCHES

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
    def select(dialog, label, names):
        box = dialog.controls[label][1]
        box.selection_clear(0, "end")
        for index in range(box.size()):
            if box.get(index) in names:
                box.selection_set(index)

    @staticmethod
    def attempt(dialog):
        with patch("tramastat.messagebox.showerror") as banner:
            ok = dialog.validate()
        return ok, banner.call_args.args[1] if banner.called else None

    @staticmethod
    def page(dialog):
        return dialog.fields.tab(dialog.fields.select(), "text")

    @staticmethod
    def shown(dialog, label):
        return bool(dialog.field_rows[label][1].winfo_manager())

    @staticmethod
    def mode_box(dialog):
        return dialog.choice_bindings["Dispersion mode"].combobox


class EnglishDialogTests(DialogCase):
    def test_captions_defaults_and_the_canonical_recipe(self):
        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
            seen["choices"] = self.mode_box(dialog).cget("values")
            seen["alpha"] = self.shown(dialog, "Dispersion alpha")
            self.select(dialog, "Predictors", ["Dose"])
            dialog.controls["Exposure"][1].set("Exposure")
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Variables", "Options"])
        self.assertEqual(seen["captions"], ["Response", "Predictors", "Categorical predictors", "Exposure",
                                            "Dispersion mode", "Dispersion alpha", "Confidence level (%)",
                                            "Residual plot"])
        self.assertEqual(tuple(seen["choices"]), ("Estimated ML", "Fixed"))
        self.assertFalse(seen["alpha"])
        self.assertTrue(seen["ok"])
        # Estimated ML keeps the parseable hidden alpha, exactly as Robust curve fit keeps its hidden scale.
        self.assertEqual(seen["recipe"], {"Response": "Count", "Predictors": ["Dose"], "Categorical predictors": [],
                                          "Exposure": "Exposure", "Dispersion mode": "Estimated ML",
                                          "Dispersion alpha": 0.5, "Confidence level (%)": 95.0,
                                          "Residual plot": False})

    def test_fixed_shows_alpha_and_a_bad_alpha_selects_the_options_page(self):
        def act(dialog, seen):
            self.select(dialog, "Predictors", ["Dose"])
            dialog.controls["Dispersion mode"][1].set("Fixed")
            dialog.update()
            seen["alpha"] = self.shown(dialog, "Dispersion alpha")
            dialog.fields.select(0)
            dialog.controls["Dispersion alpha"][1].set("abc")
            seen["text"] = self.attempt(dialog)
            seen["page"] = self.page(dialog)
            seen["focus"] = dialog.initial_focus is dialog.field_rows["Dispersion alpha"][1]
            dialog.controls["Dispersion alpha"][1].set("0")
            seen["range"] = self.attempt(dialog)
            dialog.controls["Dispersion alpha"][1].set("0,8")
            seen["comma"] = dialog.validate()
            seen["value"] = dialog.result[1]["Dispersion alpha"]

        seen = self.open(act)
        self.assertTrue(seen["alpha"])
        self.assertEqual(seen["text"], (False, "Dispersion alpha must be a number."))
        self.assertEqual(seen["page"], "Options")
        self.assertTrue(seen["focus"])
        self.assertEqual(seen["range"], (False, "Dispersion alpha must be from 0.000001 to 1000."))
        self.assertTrue(seen["comma"])
        self.assertEqual(seen["value"], 0.8)

    def test_a_hidden_unusable_alpha_is_left_out_and_never_blocks(self):
        def act(dialog, seen):
            self.select(dialog, "Predictors", ["Dose"])
            dialog.controls["Dispersion alpha"][1].set("abc")
            seen["ok"] = dialog.validate()
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertTrue(seen["ok"])
        self.assertNotIn("Dispersion alpha", seen["recipe"])
        self.assertEqual(seen["recipe"]["Dispersion mode"], "Estimated ML")

    def test_data_errors_name_and_focus_their_field(self):
        def act(dialog, seen):
            seen["empty"] = self.attempt(dialog)
            self.select(dialog, "Predictors", ["Dose"])
            self.select(dialog, "Categorical predictors", ["Batch"])
            seen["categories"] = self.attempt(dialog)
            seen["focus"] = dialog.initial_focus is dialog.controls["Categorical predictors"][1]
            seen["page"] = self.page(dialog)
            self.select(dialog, "Categorical predictors", [])
            dialog.controls["Exposure"][1].set("Dose")
            seen["exposure"] = self.attempt(dialog)

        seen = self.open(act)
        self.assertEqual(seen["empty"], (False, "Select at least one column for Predictors."))
        self.assertEqual(seen["categories"], (False, "Categorical predictors must be chosen among the predictors."))
        self.assertTrue(seen["focus"])
        self.assertEqual(seen["page"], "Variables")
        self.assertEqual(seen["exposure"],
                         (False, "Exposure must be a column distinct from the response and the predictors."))

    def test_a_saved_recipe_reopens_with_its_choices(self):
        def act(dialog, seen):
            seen["mode"] = self.mode_box(dialog).get(), dialog.controls["Dispersion mode"][1].get()
            seen["alpha"] = self.shown(dialog, "Dispersion alpha"), dialog.controls["Dispersion alpha"][1].get()
            box = dialog.controls["Categorical predictors"][1]
            seen["categories"] = [box.get(i) for i in box.curselection()]
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, RECIPE)
        self.assertEqual(seen["mode"], ("Fixed", "Fixed"))
        self.assertEqual(seen["alpha"], (True, "0.8"))
        self.assertEqual(seen["categories"], ["Batch"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], RECIPE)


class ItalianDialogTests(DialogCase):
    def setUp(self):
        super().setUp()
        self.use("it")

    def test_captions_and_choices_are_italian_and_the_recipe_stays_english(self):
        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
            box = self.mode_box(dialog)
            seen["choices"] = tuple(box.cget("values"))
            seen["shown"] = box.get()
            box.set("Fissa")
            box.event_generate("<<ComboboxSelected>>")
            dialog.update()
            seen["alpha"] = self.shown(dialog, "Dispersion alpha")
            self.select(dialog, "Predictors", ["Dose"])
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Variabili", "Opzioni"])
        self.assertEqual(seen["captions"], ["Risposta", "Predittori", "Predittori categorici", "Esposizione",
                                            "Dispersione", "Alfa di dispersione", "Livello di confidenza (%)",
                                            "Grafico dei residui"])
        self.assertEqual(seen["choices"], ("Stimata (ML)", "Fissa"))
        self.assertEqual(seen["shown"], "Stimata (ML)")
        self.assertTrue(seen["alpha"])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"]["Dispersion mode"], "Fixed")
        self.assertEqual(seen["recipe"]["Dispersion alpha"], 0.5)

    def test_field_errors_are_italian(self):
        def act(dialog, seen):
            seen["empty"] = self.attempt(dialog)
            self.select(dialog, "Predictors", ["Dose", "Count"])
            seen["response"] = self.attempt(dialog)
            self.select(dialog, "Predictors", ["Dose"])
            dialog.controls["Dispersion mode"][1].set("Fixed")
            dialog.controls["Dispersion alpha"][1].set("abc")
            seen["alpha"] = self.attempt(dialog)
            seen["page"] = self.page(dialog)

        seen = self.open(act)
        self.assertEqual(seen["empty"], (False, "Seleziona almeno una colonna per Predittori."))
        self.assertEqual(seen["response"], (False, "Predittori: La risposta non può essere anche un predittore."))
        self.assertEqual(seen["alpha"], (False, "Alfa di dispersione: inserisci un numero."))
        self.assertEqual(seen["page"], "Opzioni")


if __name__ == "__main__":
    unittest.main()
