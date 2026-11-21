"""Paired proportions: English and Italian captions, and every engine message reaches the Italian dialog."""
import unittest

import pandas as pd

from analisi import i18n
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders, set_language, translate_message
from analisi.paired_proportions import (AFTER, AFTER_NEGATIVE, AFTER_POSITIVE, BEFORE, CHOICE_KEYS, COUNT_MATRIX,
                                        ERROR_PREFIX, FORMAT, GRAPH, LABEL_KEYS, LEVEL, NEGATIVE, OBSERVATIONS,
                                        PAIRED_PROPORTIONS, POSITIVE, TAB_KEYS, TEST)
from analisi.workbench import analyse


def raised(frame, options):
    try:
        analyse(PAIRED_PROPORTIONS, frame, options)
    except FieldError as error:
        return error
    raise AssertionError("A FieldError was expected.")


def failure(frame, **options):
    base = {FORMAT: OBSERVATIONS, BEFORE: "Before", AFTER: "After", NEGATIVE: "off", POSITIVE: "on"}
    return raised(frame, {**base, **options})


def counts(**cells):
    frame = pd.DataFrame({"After negative": [4, 2], "After positive": [9, 2]}).astype(object)
    for key, value in cells.items():
        column, row = key.split("_")
        frame.loc[int(row), column.replace("-", " ")] = value
    return frame


class PairedLanguageTests(unittest.TestCase):
    def tearDown(self):
        set_language("en")

    def test_every_caption_choice_tab_and_note_exists_in_both_languages(self):
        keys = {*LABEL_KEYS.values(), *CHOICE_KEYS.values(), *TAB_KEYS.values(), "paired.hint",
                "paired.note.observations", "paired.note.matrix"}
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(key, CATALOGS["en"])
                self.assertTrue(CATALOGS["it"][key])
                if key not in {"paired.field.test", "paired.choice.mid_p"}:
                    self.assertNotEqual(CATALOGS["it"][key], CATALOGS["en"][key])

    def test_every_error_has_the_same_placeholders_in_both_languages(self):
        keys = [key for key in CATALOGS["en"] if key.startswith(ERROR_PREFIX)]
        self.assertGreaterEqual(len(keys), 20)
        for key in keys:
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)

    def test_the_method_name_is_translated_in_the_picker(self):
        set_language("it")
        self.assertEqual(i18n.ui(PAIRED_PROPORTIONS), "Proporzioni appaiate")
        set_language("en")
        self.assertEqual(i18n.ui(PAIRED_PROPORTIONS), PAIRED_PROPORTIONS)

    def test_every_engine_message_is_found_in_the_catalog_and_translated(self):
        wide = pd.DataFrame({"Before": ["off", "on"], "After": ["on", "on"]})
        cases = {
            "format": failure(wide, **{FORMAT: "Long"}),
            "test": failure(wide, **{TEST: "Fisher"}),
            "level": failure(wide, **{LEVEL: 100}),
            "graph": failure(wide, **{GRAPH: "yes"}),
            "choose": failure(wide, **{BEFORE: None}),
            "exists": failure(wide, **{BEFORE: "Nope"}),
            "unique": failure(pd.DataFrame([["off", "on", "on"]], columns=["Before", "After", "After"])),
            "different": failure(wide, **{AFTER: "Before"}),
            "code_type": failure(wide, **{NEGATIVE: ["x"]}),
            "code_empty": failure(wide, **{NEGATIVE: " "}),
            "same_code": failure(wide, **{NEGATIVE: "on"}),
            "boolean": failure(pd.DataFrame({"Before": [True], "After": ["on"]})),
            "unknown": failure(pd.DataFrame({"Before": ["pending"], "After": ["on"]})),
            "no_pairs": failure(pd.DataFrame({"Before": ["off"], "After": [None]})),
        }
        matrix = {FORMAT: COUNT_MATRIX, AFTER_NEGATIVE: "After negative", AFTER_POSITIVE: "After positive"}
        for name, frame, changes in (
                ("different_counts", counts(), {AFTER_POSITIVE: "After negative"}),
                ("two_rows", counts().iloc[:1], {}),
                ("extra_row", pd.concat([counts(), pd.DataFrame({"After negative": [1], "After positive": [None]})],
                                        ignore_index=True), {}),
                ("blank", counts(**{"After-negative_1": ""}), {}),
                ("counts", counts(**{"After-positive_0": "x"}), {}),
                ("range", counts(**{"After-positive_0": "1e400"}), {}),
                ("zero", pd.DataFrame({"After negative": [0, 0], "After positive": [0, 0]}), {}),
                ("limit", pd.DataFrame({"After negative": [10 ** 7, 0], "After positive": [1, 0]}), {})):
            cases[name] = raised(frame, {**matrix, **changes})
        for name, error in cases.items():
            with self.subTest(name=name):
                set_language("en")
                english = str(error)
                self.assertEqual(translate_message(english, ERROR_PREFIX), english)
                set_language("it")
                italian = translate_message(english, ERROR_PREFIX, {"field": lambda value: value.upper()})
                self.assertNotEqual(italian, english, f"{name} is not in the catalog")
                self.assertNotRegex(italian, r"\{[a-z_]+\}")
                self.assertIn(f"paired.error.{name}", CATALOGS["it"])

    def test_cell_values_in_a_message_are_copied_literally(self):
        error = failure(pd.DataFrame({"Before": ["{field} {row} $x$"], "After": ["on"]}))
        set_language("it")
        text = translate_message(str(error), ERROR_PREFIX)
        self.assertIn("{field} {row} $x$", text)
        self.assertIn("riga origine 1", text)

    def test_field_names_in_a_code_message_become_the_dialog_captions(self):
        error = failure(pd.DataFrame({"Before": ["off"], "After": ["on"]}), **{NEGATIVE: " "})
        set_language("it")
        text = translate_message(str(error), ERROR_PREFIX, {"field": lambda name: i18n.tr(LABEL_KEYS.get(name, name))})
        self.assertEqual(text, "Inserisci un codice per Valore negativo.")

    def test_the_italian_limit_message_uses_the_italian_thousands_separator(self):
        self.assertIn("10.000.000", CATALOGS["it"]["paired.error.limit"])
        self.assertIn("10,000,000", CATALOGS["en"]["paired.error.limit"])


if __name__ == "__main__":
    unittest.main()
