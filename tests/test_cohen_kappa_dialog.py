"""The real Analyze dialog for Cohen's kappa: pages, the order editor, hidden fields, EN/IT messages and recipes."""
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import cohen_kappa as engine
from analisi import i18n
from analisi.cohen_kappa import (BOOTSTRAP, FIRST, INTERVAL, LEVEL, ORDER, RESAMPLES, SECOND, SEED, SHOW_GRAPH,
                                 WEIGHTING)
from analisi.cohen_kappa_dialog import (STALE, CategoryOrderEditor, caption, choice, defaults, describe_error,
                                        preview, read_typed, translate_error)
from analisi.cohen_kappa_text import ERROR_PREFIX, ERRORS, INTERFACE
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders, translate_message
from tests.test_graph_i18n import LanguageMixin, TkCase

DATA = Path(__file__).resolve().parent / "data" / "cohen_kappa"
RATINGS = pd.read_csv(DATA / "ratings.csv")
METHOD = engine.METHOD
LEVELS = ["Mild", "Moderate $", "Severe"]
RECIPE = {FIRST: "Rater A", SECOND: "Rater B", WEIGHTING: "Quadratic", ORDER: LEVELS, INTERVAL: "None",
          LEVEL: 95.0, RESAMPLES: 1999, SEED: 0, SHOW_GRAPH: True}

SAMPLES = {"field": "Category order", "first": "First rating", "weighting": "Linear", "name": "Moderate $",
           "row": "4", "value": "inf", "column": "Rater {A}", "text": "1", "minimum": "2", "count": "50,001",
           "limit": "50,000", "low": "199", "high": "20,000", "position": "2", "names": '"Severe" and 3 more'}
CONVERTED_IT = {"field": "Ordine delle categorie", "first": "Primo valutatore", "weighting": "Lineare",
                "count": "50.001", "limit": "50.000", "high": "20.000"}


def triggers():
    """(call, field) for every message the engine can raise, through the same check the dialog runs."""
    base = {FIRST: "A", SECOND: "B"}
    frame = pd.DataFrame({"A": ["x", "y", "z", "x"], "B": ["x", "y", "y", "z"]})

    def check(data=frame, **changes):
        return lambda: engine.check_options(data, {**base, **changes})

    duplicated = frame.copy()
    duplicated.columns = ["A", "A"]
    boot = {INTERVAL: BOOTSTRAP}
    yield check(**{FIRST: None}), FIRST
    yield check(**{SECOND: "Nope"}), SECOND
    yield check(duplicated), FIRST
    yield check(**{SECOND: "A"}), SECOND
    yield check(**{WEIGHTING: "linear"}), WEIGHTING
    yield check(**boot, **{LEVEL: 100}), LEVEL
    yield check(**boot, **{RESAMPLES: 5}), RESAMPLES
    yield check(**boot, **{SEED: -1}), SEED
    yield check(**{SHOW_GRAPH: "on"}), SHOW_GRAPH
    yield check(**{ORDER: "x, y, z"}), ORDER
    yield check(**{ORDER: ["x", None]}), ORDER
    yield check(**{WEIGHTING: "Linear"}), ORDER
    yield check(**{ORDER: ["x", "x", "y", "z"]}), ORDER
    yield check(**{ORDER: ["x", "y", "z", "w"]}), ORDER
    yield check(**{ORDER: ["x", "y"]}), ORDER
    yield check(pd.DataFrame({"A": [1.0, np.inf], "B": [1.0, 2.0]})), FIRST
    yield check(pd.DataFrame({"A": ["x", "y"], "B": ["x", {"y": 1}]})), SECOND
    yield check(pd.DataFrame({"A": [1, 2], "B": ["1", 2]})), SECOND
    yield check(pd.DataFrame({"A": [True, False], "B": ["False", True]})), SECOND
    yield check(pd.DataFrame({"A": ["x", None], "B": ["x", "y"]})), FIRST
    yield check(pd.DataFrame({"A": np.zeros(50_001), "B": np.zeros(50_001)})), FIRST
    yield check(pd.DataFrame({"A": np.arange(21), "B": np.arange(21)})), FIRST


class CatalogTests(LanguageMixin, unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        keys = [key for key in CATALOGS["en"] if key.startswith("kappa.")]
        self.assertEqual(len(keys), len(INTERFACE) - 1 + len(ERRORS))
        for key in keys:
            self.assertTrue(CATALOGS["it"].get(key), key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)
        for key in ERRORS:
            names = i18n._PLACEHOLDER.findall(CATALOGS["en"][ERROR_PREFIX + key])
            self.assertEqual(len(names), len(set(names)), key)
        self.assertEqual(CATALOGS["it"]["interface.Cohen's kappa"], "Concordanza tra valutatori (kappa di Cohen)")
        self.assertEqual(i18n.ui("Cohen's kappa"), "Cohen's kappa")

    def test_the_method_name_is_translated_for_the_menus(self):
        self.use("it")
        self.assertEqual(i18n.ui("Cohen's kappa"), "Concordanza tra valutatori (kappa di Cohen)")

    def test_every_template_translates_back_from_its_english_message(self):
        self.use("it")
        for key in ERRORS:
            english, italian = CATALOGS["en"][ERROR_PREFIX + key], CATALOGS["it"][ERROR_PREFIX + key]
            for name in placeholders(english):
                english = english.replace("{%s}" % name, SAMPLES[name])
                italian = italian.replace("{%s}" % name, CONVERTED_IT.get(name, SAMPLES[name]))
            self.assertEqual(translate_error(english), italian, key)

    def test_english_messages_stay_as_written(self):
        for key, (english, _) in ERRORS.items():
            message = english.format(**SAMPLES)
            self.assertEqual(translate_error(message), message, key)

    def test_each_engine_message_names_one_template_and_changes_in_italian(self):
        self.use("it")
        seen = set()
        for call, field in triggers():
            with self.assertRaises(FieldError) as raised:
                call()
            error = raised.exception
            self.assertEqual(error.field, field, str(error))
            self.assertNotEqual(translate_error(error), str(error), str(error))
            keys = [key for key, pattern in i18n._message_patterns(ERROR_PREFIX) if pattern.match(str(error))]
            self.assertEqual(len(keys), 1, (str(error), keys))
            seen.add(keys[0][len(ERROR_PREFIX):])
        self.assertEqual(set(ERRORS) - seen, set(), "messages no screen reaches")

    def test_worksheet_text_stays_literal_and_counts_use_dots(self):
        self.use("it")
        self.assertEqual(translate_error('Category order: "{Grave} & $x$" appears more than once.'),
                         'Ordine delle categorie: "{Grave} & $x$" compare più di una volta.')
        self.assertEqual(translate_error("Cohen's kappa reads up to 50,000 complete pairs; found 61,234."),
                         "Il kappa di Cohen legge fino a 50.000 coppie complete; trovate 61.234.")
        self.assertEqual(translate_error("Category order: Quadratic weights need an order that lists every "
                                         "category once."),
                         "Ordine delle categorie: con i pesi «Quadratico» serve un ordine che elenchi ogni "
                         "categoria una sola volta.")

    def test_the_field_is_named_once_and_only_when_the_message_does_not(self):
        self.assertEqual(describe_error(FieldError(SEED, "Seed must be a whole number from 0 to 9.")),
                         "Seed must be a whole number from 0 to 9.")
        self.assertEqual(describe_error(FieldError(FIRST, "Worksheet column names must be unique.")),
                         "First rating: Worksheet column names must be unique.")
        self.assertEqual(describe_error(ValueError("Something else."), SECOND), "Second rating: Something else.")
        self.use("it")
        self.assertEqual(describe_error(FieldError(SEED, "Seed must be a whole number from 0 to 9.")),
                         "Seme deve essere un numero intero da 0 a 9.")
        self.assertEqual(describe_error(FieldError(FIRST, "Worksheet column names must be unique.")),
                         "Primo valutatore: I nomi delle colonne del foglio devono essere univoci.")
        self.assertEqual(caption(ORDER), "Ordine delle categorie")
        self.assertEqual(caption("Unlisted"), "Unlisted")
        self.assertEqual(choice("Bootstrap percentile"), "Bootstrap percentile")
        self.assertEqual(choice("Unweighted"), "Non pesato")

    def test_messages_outside_the_catalog_use_the_common_interface_catalog(self):
        self.use("it")
        self.assertEqual(translate_message("Cohen's kappa", ERROR_PREFIX), "Cohen's kappa")
        self.assertEqual(translate_error(ValueError("Select at least one column for Predictors.")),
                         i18n.ui("Select at least one column for Predictors."))

    def test_typed_fields_and_defaults(self):
        self.assertEqual(read_typed(" 1999 "), 1999)
        self.assertEqual(read_typed("95,5"), 95.5)
        self.assertEqual(read_typed("1e3"), 1000.0)
        self.assertEqual(read_typed("abc"), "abc")
        self.assertEqual(read_typed(""), "")
        self.assertEqual(defaults(RATINGS), {FIRST: "Rater A", SECOND: "Rater B"})
        self.assertEqual(defaults(RATINGS[["Rater A"]]), {})

    def test_the_preview_explains_why_the_categories_are_unknown(self):
        self.assertEqual(preview(RATINGS, "Rater A", "Rater B"), (LEVELS, ""))
        self.assertEqual(preview(RATINGS, "Rater A", "Rater A"),
                         (None, "Choose a column different from First rating for Second rating."))
        self.use("it")
        self.assertEqual(preview(RATINGS, "Rater A", ""), (None, "Scegli una colonna per Secondo valutatore."))


class EditorTests(TkCase):
    def editor(self, saved=()):
        editor = CategoryOrderEditor(self.root, saved)
        self.addCleanup(editor.destroy)
        return editor

    def test_move_propose_restore_and_clear(self):
        editor = self.editor(["Severe", "Gone", "Mild"])
        self.assertEqual(editor.values(), ["Severe", "Gone", "Mild"])
        self.assertEqual(str(editor.buttons["propose"].cget("state")), "disabled")
        editor.set_observed(["Mild", "Moderate", "Severe"])
        self.assertEqual(editor.notes(), ["Not in the order yet: Moderate", "Not in the complete pairs: Gone"])
        self.assertEqual(str(editor.listbox.itemcget(1, "foreground")), STALE)
        editor.move(1)  # nothing selected: nothing moves
        self.assertEqual(editor.values(), ["Severe", "Gone", "Mild"])
        editor.listbox.selection_set(2)
        editor.move(-1)
        self.assertEqual(editor.values(), ["Severe", "Mild", "Gone"])
        self.assertEqual(editor.selected(), 1)
        editor.move(-1)
        editor.move(-1)  # already first
        self.assertEqual(editor.values(), ["Mild", "Severe", "Gone"])
        editor.propose()
        self.assertEqual(editor.values(), ["Mild", "Severe", "Moderate"])
        self.assertEqual(editor.notes(), [])
        self.assertEqual(str(editor.note.winfo_manager()), "")
        editor.restore()
        self.assertEqual(editor.values(), ["Severe", "Gone", "Mild"])
        editor.clear()
        self.assertEqual(editor.values(), [])
        self.assertIn("Empty: automatic order, Unweighted only.", editor.hint.cget("text"))
        editor.set_weighting("Linear")
        self.assertEqual(editor.notes(), ["Linear and Quadratic weights need an order that lists every category once."])
        self.assertNotIn("Empty: automatic order", editor.hint.cget("text"))
        editor.set_observed(None, "Choose a column for Second rating.")
        self.assertEqual(editor.notes()[0], "Choose a column for Second rating.")
        self.assertEqual(str(editor.buttons["propose"].cget("state")), "disabled")

    def test_a_saved_order_that_is_not_a_list_starts_empty(self):
        self.assertEqual(self.editor("Mild, Severe").values(), [])
        self.assertEqual(self.editor((1, "b")).values(), ["1", "b"])

    def test_the_keys_and_the_italian_labels(self):
        for sequence in ("<Alt-Up>", "<Alt-Down>", "<Control-Up>", "<Control-Down>"):
            self.assertTrue(self.editor().listbox.bind(sequence), sequence)
        self.use("it")
        editor = self.editor(["a"])
        self.assertEqual([editor.buttons[key].cget("text") for key in ("up", "down", "propose", "restore", "clear")],
                         ["Su", "Giù", "Proponi", "Ripristina", "Svuota"])
        editor.set_observed(["a", "b"])
        self.assertEqual(editor.notes(), ["Non ancora nell’ordine: b"])


class DialogCase(TkCase):
    frame = RATINGS.assign(Score=np.arange(len(RATINGS)) % 3)

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
    def page(dialog):
        return dialog.fields.tab(dialog.fields.select(), "text")

    @staticmethod
    def shown(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())


class EnglishDialogTests(DialogCase):
    def test_pages_defaults_hidden_fields_and_the_recipe(self):
        def act(dialog, seen):
            controls = dialog.controls
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["page"] = self.page(dialog)
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in controls]
            seen["defaults"] = {name: controls[name][1].get() for name in (FIRST, SECOND, WEIGHTING, INTERVAL)}
            seen["editor"] = type(controls[ORDER][1])
            seen["observed"] = controls[ORDER][1].observed
            seen["hidden"] = [self.shown(dialog, name) for name in (LEVEL, RESAMPLES, SEED)]
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["tabs"], ["Ratings", "Interval and graph"])
        self.assertEqual(seen["page"], "Ratings")
        self.assertEqual(seen["captions"], ["First rating", "Second rating", "Weighting", "Category order",
                                            "Confidence interval", "Confidence level (%)", "Resamples", "Seed",
                                            "Show graph"])
        self.assertEqual(seen["defaults"], {FIRST: "Rater A", SECOND: "Rater B", WEIGHTING: "Unweighted",
                                            INTERVAL: "None"})
        self.assertIs(seen["editor"], CategoryOrderEditor)
        self.assertEqual(seen["observed"], LEVELS)
        self.assertEqual(seen["hidden"], [False, False, False])
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], {**RECIPE, WEIGHTING: "Unweighted", ORDER: []})

    def test_a_wrong_order_keeps_the_error_on_its_field_until_it_is_corrected(self):
        def act(dialog, seen):
            editor = dialog.controls[ORDER][1]
            seen["note"] = editor.note.cget("text")
            dialog.fields.select(1)
            seen["wrong"] = self.attempt(dialog)
            seen["page"] = self.page(dialog)
            seen["focus"] = dialog.initial_focus is editor.listbox
            seen["again"] = self.attempt(dialog)
            editor.propose()
            seen["proposed"] = editor.values()
            seen["fixed"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, recipe={**RECIPE, ORDER: ["Severe", "Mild"]})
        self.assertEqual(seen["note"], "Not in the order yet: Moderate $")
        self.assertEqual(seen["wrong"], (False, 'Category order: list every category once; missing "Moderate $".'))
        self.assertEqual(seen["page"], "Ratings")
        self.assertTrue(seen["focus"])
        self.assertEqual(seen["again"], seen["wrong"])
        self.assertEqual(seen["proposed"], ["Severe", "Mild", "Moderate $"])
        self.assertEqual(seen["fixed"], (True, None))
        self.assertEqual(seen["recipe"][ORDER], ["Severe", "Mild", "Moderate $"])
        self.assertEqual(seen["recipe"][WEIGHTING], "Quadratic")

    def test_weighted_kappa_needs_the_order_and_the_note_says_so(self):
        def act(dialog, seen):
            editor = dialog.controls[ORDER][1]
            dialog.controls[WEIGHTING][1].set("Linear")
            dialog.update()
            seen["note"] = editor.note.cget("text")
            seen["wrong"] = self.attempt(dialog)
            seen["focus"] = dialog.initial_focus is editor.listbox
            editor.propose()
            editor.listbox.selection_clear(0, "end")
            editor.listbox.selection_set(0)
            editor.listbox.focus_force()
            dialog.update()
            editor.listbox.event_generate("<Alt-Down>", when="now")
            dialog.update()
            seen["moved"] = editor.values()
            seen["ok"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertEqual(seen["note"], "Linear and Quadratic weights need an order that lists every category once.")
        self.assertEqual(seen["wrong"], (False, "Category order: Linear weights need an order that lists every "
                                                "category once."))
        self.assertTrue(seen["focus"])
        self.assertEqual(seen["moved"], ["Moderate $", "Mild", "Severe"])
        self.assertEqual(seen["ok"], (True, None))
        self.assertEqual(seen["recipe"][ORDER], ["Moderate $", "Mild", "Severe"])

    def test_the_same_column_twice_names_the_second_rating(self):
        def act(dialog, seen):
            dialog.controls[SECOND][1].set("Rater A")
            dialog.update()
            seen["note"] = dialog.controls[ORDER][1].note.cget("text")
            seen["wrong"] = self.attempt(dialog)
            seen["focus"] = dialog.initial_focus is dialog.field_rows[SECOND][1]
            dialog.controls[SECOND][1].set("Score")
            dialog.update()
            seen["observed"] = dialog.controls[ORDER][1].observed

        seen = self.open(act)
        self.assertEqual(seen["note"], "Choose a column different from First rating for Second rating.")
        self.assertEqual(seen["wrong"], (False, "Choose a column different from First rating for Second rating."))
        self.assertTrue(seen["focus"])
        # Numbers and text are different categories: the numbers come first in the automatic order.
        self.assertEqual(seen["observed"], ["0", "1", "2", "Mild", "Moderate $", "Severe"])

    def test_hidden_bootstrap_fields_are_kept_and_read_only_when_shown(self):
        def act(dialog, seen):
            controls = dialog.controls
            controls[RESAMPLES][1].set("lots")
            controls[SEED][1].set("-1")
            seen["hidden_ok"] = dialog.validate()
            seen["hidden_recipe"] = dict(dialog.result[1])
            controls[INTERVAL][1].set(BOOTSTRAP)
            dialog.update()
            seen["shown"] = [self.shown(dialog, name) for name in (LEVEL, RESAMPLES, SEED)]
            dialog.fields.select(0)
            seen["resamples"] = self.attempt(dialog)
            seen["page"] = self.page(dialog)
            seen["focus"] = dialog.initial_focus is dialog.field_rows[RESAMPLES][1]
            controls[RESAMPLES][1].set("500")
            seen["seed"] = self.attempt(dialog)
            controls[SEED][1].set("42")
            controls[LEVEL][1].set("90,5")
            with patch.object(engine, "bootstrap", side_effect=AssertionError("resampled in the dialog")):
                seen["ok"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act)
        self.assertTrue(seen["hidden_ok"])
        self.assertEqual((seen["hidden_recipe"][RESAMPLES], seen["hidden_recipe"][SEED]), ("lots", -1))
        self.assertEqual(seen["shown"], [True, True, True])
        self.assertEqual(seen["resamples"], (False, "Resamples must be a whole number from 199 to 20,000."))
        self.assertEqual(seen["page"], "Interval and graph")
        self.assertTrue(seen["focus"])
        self.assertEqual(seen["seed"], (False, f"Seed must be a whole number from 0 to {2 ** 64 - 1}."))
        self.assertEqual(seen["ok"], (True, None))
        self.assertEqual({name: seen["recipe"][name] for name in (INTERVAL, LEVEL, RESAMPLES, SEED)},
                         {INTERVAL: BOOTSTRAP, LEVEL: 90.5, RESAMPLES: 500, SEED: 42})

    def test_a_saved_recipe_reopens_with_its_order_and_restore_brings_it_back(self):
        def act(dialog, seen):
            editor = dialog.controls[ORDER][1]
            seen["values"] = editor.values()
            seen["weighting"] = dialog.controls[WEIGHTING][1].get()
            editor.clear()
            editor.restore()
            seen["restored"] = editor.values()
            seen["ok"] = dialog.validate()
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        order = ["Severe", "Moderate $", "Mild"]
        seen = self.open(act, recipe={**RECIPE, ORDER: order, SHOW_GRAPH: False})
        self.assertEqual(seen["values"], order)
        self.assertEqual(seen["weighting"], "Quadratic")
        self.assertEqual(seen["restored"], order)
        self.assertTrue(seen["ok"])
        self.assertEqual(seen["recipe"], {**RECIPE, ORDER: order, SHOW_GRAPH: False})

    def test_a_value_that_is_not_a_category_is_reported_on_its_column(self):
        frame = pd.DataFrame({"A": [1.0, 2.0, np.inf, 1.0], "B": [1.0, 2.0, 2.0, 1.0]})

        def act(dialog, seen):
            seen["note"] = dialog.controls[ORDER][1].note.cget("text")
            seen["wrong"] = self.attempt(dialog)
            seen["focus"] = dialog.initial_focus is dialog.field_rows[FIRST][1]

        seen = self.open(act, frame=frame)
        message = 'Source row 3: the value inf in column "A" is not a finite number.'
        self.assertEqual(seen["note"], f"First rating: {message}")
        self.assertEqual(seen["wrong"], (False, f"First rating: {message}"))
        self.assertTrue(seen["focus"])


class ItalianDialogTests(DialogCase):
    def test_captions_choices_and_messages_in_italian_with_a_canonical_recipe(self):
        self.use("it")

        def act(dialog, seen):
            controls = dialog.controls
            seen["tabs"] = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
            seen["captions"] = [dialog.field_rows[name][0].cget("text") for name in controls]
            seen["weighting"] = (dialog.field_rows[WEIGHTING][1].get(), dialog.field_rows[WEIGHTING][1].cget("values"))
            seen["interval"] = dialog.field_rows[INTERVAL][1].cget("values")
            seen["wrong"] = self.attempt(dialog)
            controls[ORDER][1].propose()
            seen["ok"] = self.attempt(dialog)
            seen["keep"] = dialog.result
            seen["recipe"] = dialog.result[1]

        seen = self.open(act, recipe={**RECIPE, ORDER: ["Severe", "Moderate $"]})
        self.assertEqual(seen["tabs"], ["Valutazioni", "Intervallo e grafico"])
        self.assertEqual(seen["captions"], ["Primo valutatore", "Secondo valutatore", "Pesi", "Ordine delle categorie",
                                            "Intervallo di confidenza", "Livello di confidenza (%)", "Repliche",
                                            "Seme", "Mostra grafico"])
        self.assertEqual(seen["weighting"], ("Quadratico", ("Non pesato", "Lineare", "Quadratico")))
        self.assertEqual(seen["interval"], ("Nessuno", "Bootstrap percentile"))
        self.assertEqual(seen["wrong"], (False, 'Ordine delle categorie: elenca ogni categoria una sola volta; '
                                                'mancano "Mild".'))
        self.assertEqual(seen["ok"], (True, None))
        self.assertEqual(seen["recipe"], {**RECIPE, ORDER: ["Severe", "Moderate $", "Mild"]})


if __name__ == "__main__":
    unittest.main()
