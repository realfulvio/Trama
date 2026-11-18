"""The real Analyze dialog of the Permutation test for mean difference: pages, choices, notes and EN/IT messages."""
from unittest.mock import patch
import unittest

import numpy as np
import pandas as pd

from analisi import mean_permutation as mp
from analisi.i18n import CATALOGS, placeholders
from analisi.mean_permutation_dialog import caption, describe_error, parse_seed, preview_text, translate_error
from analisi.mean_permutation_text import EN, IT
from tests.test_graph_i18n import LanguageMixin, TkCase
from tests.test_mean_permutation import INDEPENDENT, frame_of

METHOD = mp.METHOD
SAMPLES = {"field": "Second", "row": "4", "value": "abc", "name": "Dose", "count": "25,001", "work": "108,902,402",
           "resamples": "1,001", "units": "50,000", "limit": "999"}
GROUPED_IT = {"count": "25.001", "work": "108.902.402", "resamples": "1.001", "units": "50.000"}


class CatalogTests(LanguageMixin, unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        self.assertEqual(set(EN), set(IT))
        for key in EN:
            self.assertEqual(CATALOGS["en"][key], EN[key], key)
            self.assertEqual(CATALOGS["it"][key], IT[key], key)
            self.assertEqual(placeholders(EN[key]), placeholders(IT[key]), key)
        self.assertEqual({key for key in EN if key.startswith("perm.field.")},
                         {mp.LABEL_KEYS[name] for name in mp.OPTIONS})
        self.assertEqual(set(mp.CHOICE_KEYS), {*mp.DESIGNS, *mp.ALTERNATIVES, *mp.MODES})

    def test_every_error_translates_back_from_its_english_message(self):
        self.use("it")
        for key, english in EN.items():
            if not key.startswith(mp.ERROR_PREFIX):
                continue
            with self.subTest(key=key):
                message, expected = english, IT[key]
                for name in placeholders(english):
                    message = message.replace("{%s}" % name, SAMPLES[name])
                    shown = "Secondo campione" if name == "field" else GROUPED_IT.get(name, SAMPLES[name])
                    expected = expected.replace("{%s}" % name, shown)
                self.assertEqual(translate_error(message), expected)

    def test_english_messages_stay_as_written(self):
        self.use("en")
        for key, english in EN.items():
            if key.startswith(mp.ERROR_PREFIX):
                self.assertEqual(translate_error(english), english)

    def test_engine_messages_are_in_the_catalog(self):
        """Every message the engine can raise translates; nothing falls back to English in Italian."""
        self.use("it")
        cases = [
            lambda: mp.check_options(INDEPENDENT, {"First": "First", "Second": "First"}),
            lambda: mp.check_options(INDEPENDENT, {"First": "First", "Second": "Nope"}),
            lambda: mp.check_options(INDEPENDENT, {"First": None, "Second": "Second"}),
            lambda: mp.check_options(INDEPENDENT, {"First": "First", "Second": "Second", "Method": "x"}),
            lambda: mp.check_options(INDEPENDENT, {"First": "First", "Second": "Second", "Keep draws": 1}),
            lambda: mp.check_options(INDEPENDENT, {"First": "First", "Second": "Second", "Seed": -1}),
            lambda: mp.check_options(INDEPENDENT, {"First": "First", "Second": "Second", "Resamples": 5}),
            lambda: mp.check_options(INDEPENDENT.assign(Second=["a", 1, 2, 3, 4]), {"First": "First",
                                                                                   "Second": "Second"}),
            lambda: mp.check_options(INDEPENDENT.assign(Second=[np.inf, 1, 2, 3, 4]), {"First": "First",
                                                                                      "Second": "Second"}),
            lambda: mp.check_options(INDEPENDENT.assign(Second=[2**60, 1, 2, 3, 4]), {"First": "First",
                                                                                     "Second": "Second"}),
            lambda: mp.check_options(frame_of([1.], [1., 2.]), {"First": "First", "Second": "Second"}),
            lambda: mp.check_options(frame_of([1.], [1., 2.]), {"First": "First", "Second": "Second",
                                                                "Design": "Paired"}),
            lambda: mp.check_options(frame_of(np.ones(25_001), np.ones(25_001)), {"First": "First",
                                                                                  "Second": "Second"}),
            lambda: mp.check_options(frame_of(np.ones(25_001), np.ones(25_001)), {"First": "First",
                                                                                  "Second": "Second",
                                                                                  "Design": "Paired"}),
            lambda: mp.check_options(frame_of(np.arange(20.), np.arange(20.)), {"First": "First",
                                                                                 "Second": "Second",
                                                                                 "Method": "Exact"}),
            lambda: mp.check_options(frame_of(np.arange(600.), [1., 2.]), {"First": "First", "Second": "Second",
                                                                           "Method": "Exact"}),
            lambda: mp.check_options(frame_of(np.arange(25_000.), np.arange(25_000.)),
                                     {"First": "First", "Second": "Second", "Resamples": 1001}),
            lambda: mp.check_options(frame_of([1e308, -1e308], [1e308, 0.]), {"First": "First",
                                                                              "Second": "Second"}),
        ]
        for number, call in enumerate(cases):
            with self.subTest(case=number):
                with self.assertRaises(ValueError) as raised:
                    call()
                english = str(raised.exception)
                shown = translate_error(raised.exception)
                self.assertNotEqual(shown, english, english)
        self.assertEqual(translate_error(ValueError("Seed must be a whole number.")), "Seme: inserisci un numero intero.")

    def test_banners_name_their_field_once(self):
        self.use("it")
        error = mp.FieldError("First", "Paired design needs at least 2 complete pairs; 1 found.")
        self.assertEqual(describe_error(error),
                         "Primo campione: Il disegno appaiato richiede almeno 2 coppie complete; trovate 1.")
        error = mp.FieldError("Second", "Second: choose a column different from First.")
        self.assertEqual(describe_error(error), "Secondo campione: scegli una colonna diversa dal primo campione.")
        self.use("en")
        self.assertEqual(describe_error(error), "Second: choose a column different from First.")
        self.assertEqual(caption("Keep draws"), "Keep draws")

    def test_seed_entry_and_previews(self):
        self.assertEqual(parse_seed(" 18446744073709551615 "), 2**64 - 1)
        self.assertEqual(parse_seed("-1"), -1)
        with self.assertRaises(ValueError):
            parse_seed("1.5")
        self.use("en")
        options = {"First": "First", "Second": "Second", "Design": "Independent", "Method": "Auto",
                   "Resamples": 9999, "Seed": 0}
        self.assertEqual(preview_text(INDEPENDENT, options),
                         "With these columns Auto enumerates all 126 assignments exactly: Resamples and Seed are "
                         "not used.")
        big = frame_of(np.arange(30.), np.arange(30.))
        self.assertIn("simulates", preview_text(big, options))
        self.assertIn("up to 200,000", preview_text(INDEPENDENT, {**options, "Second": "First"}))
        self.assertIn("all 126 assignments", preview_text(INDEPENDENT, {**options, "Method": "Exact"}))
        self.assertIn("Generator(PCG64(Seed))", preview_text(INDEPENDENT, {**options, "Method": "Monte Carlo"}))
        self.use("it")
        two_pairs = frame_of(np.arange(17.), np.arange(17.) + 1)
        self.assertEqual(preview_text(two_pairs, {**options, "Design": "Paired"}),
                         "Con queste colonne Automatico enumera esattamente tutte le 131.072 assegnazioni: "
                         "Repliche e Seme non sono usati.")


class DialogCase(TkCase):
    frame = INDEPENDENT

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
    def pick(dialog, field, value):
        """Choose a value the way the user does: through the translated label shown in the combobox."""
        binding = dialog.choice_bindings[field]
        binding.display.set(binding.labels[binding.values.index(value)])
        dialog.update_idletasks()

    @staticmethod
    def shown(dialog, field):
        return dialog.field_rows[field][0].winfo_manager() == "grid"


class EnglishDialogTests(DialogCase):
    def test_pages_captions_defaults_and_the_recipe(self):
        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
            seen["choices"] = {name: list(binding.labels) for name, binding in dialog.choice_bindings.items()}
            seen["notes"] = {key: note.cget("text") for key, note in dialog.permutation_notes.items()}
            seen["pages"] = {name: dialog.fields.tab(dialog.field_rows[name][0].master, "text")
                             for name in ("First", "Design", "Method")}
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["keep"] = dialog.result

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Data", "Test"])
        self.assertEqual(seen["pages"], {"First": "Data", "Design": "Data", "Method": "Test"})
        self.assertEqual(list(seen["captions"].values()), list(mp.OPTIONS))
        self.assertEqual(seen["choices"]["Alternative"],
                         ["Two-sided", "Greater (First > Second)", "Less (First < Second)"])
        self.assertIn("exchangeable", seen["notes"]["design"])
        self.assertIn("126 assignments", seen["notes"]["method"])
        self.assertIn("no confidence interval", seen["notes"]["tails"])
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["keep"], (METHOD, {
            "First": "First", "Second": "Second", "Design": "Independent", "Alternative": "Two-sided",
            "Method": "Auto", "Resamples": 9999, "Seed": 0, "Keep draws": False, "Show graph": True}))

    def test_exact_hides_and_ignores_the_simulation_fields(self):
        def act(dialog, seen):
            dialog.controls["Seed"][1].set("not a number")
            self.pick(dialog, "Method", "Exact")
            seen["hidden"] = not self.shown(dialog, "Seed") and not self.shown(dialog, "Resamples")
            seen["note"] = dialog.permutation_notes["method"].cget("text")
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["recipe"] = dialog.result[1] if seen["ok"] else None
            self.pick(dialog, "Method", "Monte Carlo")
            seen["back"] = self.shown(dialog, "Seed") and self.shown(dialog, "Resamples")
            seen["mc"] = dialog.permutation_notes["method"].cget("text")

        seen = self.open(act)
        self.assertTrue(seen["hidden"])
        self.assertEqual(seen["note"], "Exact enumerates all 126 assignments; Resamples and Seed are ignored.")
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["recipe"]["Method"], "Exact")
        self.assertEqual(seen["recipe"]["Resamples"], 9999)
        self.assertNotIn("Seed", seen["recipe"])
        self.assertTrue(seen["back"])
        self.assertIn("keeps the earlier draws", seen["mc"])

    def test_seed_errors_keep_the_dialog_open_on_the_seed(self):
        def act(dialog, seen):
            self.pick(dialog, "Method", "Monte Carlo")
            for text in ("1.5", "-1", "18446744073709551616", "18446744073709551615"):
                dialog.controls["Seed"][1].set(text)
                ok, message = self.attempt(dialog)
                seen[text] = ok, message, dialog.initial_focus is dialog.field_rows["Seed"][1]
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["1.5"], (False, "Seed must be a whole number.", True))
        self.assertEqual(seen["-1"][:2], (False, "Seed must be a whole number from 0 to 18446744073709551615."))
        self.assertTrue(seen["-1"][2])
        self.assertFalse(seen["18446744073709551616"][0])
        self.assertTrue(seen["18446744073709551615"][0])
        self.assertEqual(seen["recipe"]["Seed"], 2**64 - 1)

    def test_method_and_column_errors_name_their_field(self):
        frame = frame_of(np.arange(20.), np.arange(20.)).assign(Label=list("abcdefghijklmnopqrst"))

        def act(dialog, seen):
            self.pick(dialog, "Method", "Exact")
            seen["exact"] = self.attempt(dialog)
            seen["exact_focus"] = dialog.initial_focus is dialog.field_rows["Method"][1]
            self.pick(dialog, "Method", "Auto")
            seen["note"] = dialog.permutation_notes["method"].cget("text")
            dialog.controls["Second"][1].set("First")
            seen["same"] = self.attempt(dialog)
            dialog.controls["Second"][1].set("Label")
            seen["label"] = self.attempt(dialog)
            dialog.controls["Second"][1].set("Second")
            dialog.controls["Resamples"][1].set("12")
            seen["resamples"] = self.attempt(dialog)
            dialog.controls["Resamples"][1].set("199")
            seen["ok"] = self.attempt(dialog)

        seen = self.open(act, frame=frame)
        self.assertEqual(seen["exact"], (False, "Method: exact enumeration allows at most 200,000 assignments and "
                                                "these data have more. Choose Auto or Monte Carlo."))
        self.assertTrue(seen["exact_focus"])
        self.assertIn("simulates", seen["note"])
        self.assertEqual(seen["same"], (False, "Second: choose a column different from First."))
        self.assertEqual(seen["label"], (False, "Second: source row 1 is not a number (a)."))
        self.assertEqual(seen["resamples"], (False, "Resamples must be a whole number from 199 to 100,000."))
        self.assertEqual(seen["ok"], (True, None))

    def test_a_saved_recipe_reopens_with_its_values(self):
        recipe = {"First": "Second", "Second": "First", "Design": "Paired", "Alternative": "Less",
                  "Method": "Monte Carlo", "Resamples": 500, "Seed": 2**64 - 1, "Keep draws": True,
                  "Show graph": False}

        def act(dialog, seen):
            seen["values"] = {name: control.get() for name, (_, control) in dialog.controls.items()}
            seen["labels"] = {name: binding.display.get() for name, binding in dialog.choice_bindings.items()}
            seen["note"] = dialog.permutation_notes["design"].cget("text")
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["recipe"] = dialog.result[1] if seen["ok"] else None

        seen = self.open(act, recipe=recipe)
        self.assertEqual(seen["values"]["Seed"], "18446744073709551615")
        self.assertEqual(seen["labels"]["Alternative"], "Less (First < Second)")
        self.assertIn("Paired samples", seen["note"])
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual(seen["recipe"], recipe)


class ItalianDialogTests(DialogCase):
    def setUp(self):
        self.use("it")

    def test_captions_choices_notes_and_a_canonical_recipe(self):
        def act(dialog, seen):
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in dialog.controls]
            seen["choices"] = {name: list(binding.labels) for name, binding in dialog.choice_bindings.items()}
            self.pick(dialog, "Design", "Paired")
            self.pick(dialog, "Alternative", "Greater")
            seen["notes"] = {key: note.cget("text") for key, note in dialog.permutation_notes.items()}
            seen["ok"], seen["message"] = self.attempt(dialog)
            seen["recipe"] = dialog.result[1] if seen["ok"] else None

        seen = self.open(act, frame=frame_of([6., 7, 2, 4, 10, 11], [1., 5, 4, 4, 8, 3]))
        self.assertEqual(seen["tabs"], ["Dati", "Test"])
        self.assertEqual(seen["captions"], ["Primo campione", "Secondo campione", "Disegno", "Alternativa", "Metodo",
                                            "Repliche", "Seme", "Salva distribuzione nulla", "Mostra grafico"])
        self.assertEqual(seen["choices"], {
            "Design": ["Indipendenti", "Appaiati"],
            "Alternative": ["Bilaterale", "Maggiore (Primo > Secondo)", "Minore (Primo < Secondo)"],
            "Method": ["Automatico", "Esatto", "Monte Carlo"]})
        self.assertTrue(seen["notes"]["design"].startswith("Campioni appaiati"))
        self.assertEqual(seen["notes"]["method"], "Con queste colonne Automatico enumera esattamente tutte le 64 "
                                                  "assegnazioni: Repliche e Seme non sono usati.")
        self.assertTrue(seen["ok"], seen["message"])
        self.assertEqual((seen["recipe"]["Design"], seen["recipe"]["Alternative"], seen["recipe"]["Method"]),
                         ("Paired", "Greater", "Auto"))

    def test_messages_are_italian(self):
        frame = frame_of(np.arange(20.), np.arange(20.)).assign(Label=list("abcdefghijklmnopqrst"))

        def act(dialog, seen):
            self.pick(dialog, "Method", "Exact")
            seen["exact"] = self.attempt(dialog)
            self.pick(dialog, "Method", "Monte Carlo")
            dialog.controls["Seed"][1].set("x")
            seen["seed"] = self.attempt(dialog)
            dialog.controls["Seed"][1].set("-5")
            seen["range"] = self.attempt(dialog)
            dialog.controls["Seed"][1].set("5")
            dialog.controls["Second"][1].set("Label")
            seen["label"] = self.attempt(dialog)

        seen = self.open(act, frame=frame)
        self.assertEqual(seen["exact"], (False, "Metodo: l’enumerazione esatta ammette al massimo 200.000 assegnazioni "
                                                "e questi dati ne hanno di più. Scegli Automatico o Monte Carlo."))
        self.assertEqual(seen["seed"], (False, "Seme: inserisci un numero intero."))
        self.assertEqual(seen["range"], (False, "Seme deve essere un numero intero da 0 a 18446744073709551615."))
        self.assertEqual(seen["label"], (False, "Secondo campione: la riga 1 non è un numero (a)."))


if __name__ == "__main__":
    unittest.main()
