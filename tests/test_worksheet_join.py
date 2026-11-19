"""Join worksheets by key: engine, dispatcher, budgets and messages (no interface)."""
import threading
import tracemalloc
import unittest

import numpy as np
import pandas as pd

from analisi import i18n
from analisi.analysis_chain import ChainCancelled
from analisi.field_error import FieldError
from analisi.parallel_analyses import LOCAL_METHODS, precompute
from analisi.workbench import GROUPS, METHODS, analyse
from analisi import worksheet_join as wj
from analisi.worksheet_join_text import EN, IT


def options(**extra):
    base = {wj.RIGHT_SHEET: "Right", wj.LEFT_KEYS: ["ID"], wj.RIGHT_KEYS: ["Key"], wj.JOIN_TYPE: "Full",
            wj.CARDINALITY: wj.MANY_TO_MANY}
    base.update(extra)
    return base


def rows(table):
    return [[None if pd.isna(value) else value for value in row] for row in table.itertuples(index=False, name=None)]


def join(left, right, **extra):
    return wj.join_worksheets(left, right, options(**extra))


class Registration(unittest.TestCase):
    def test_catalog_and_dispatcher(self):
        self.assertIn(wj.METHOD, GROUPS["Data Processing"])
        self.assertEqual(METHODS[wj.METHOD], wj.OPTIONS)
        self.assertIn(wj.METHOD, LOCAL_METHODS)

    def test_precompute_never_takes_the_join(self):
        left = pd.DataFrame({"ID": [1]})
        jobs = [(key, wj.METHOD, left, options()) for key in range(3)]
        self.assertEqual(precompute(jobs), {})

    def test_missing_source_names_the_sheet(self):
        with self.assertRaises(FieldError) as caught:
            analyse(wj.METHOD, pd.DataFrame({"ID": [1]}), options(**{wj.RIGHT_SHEET: "Anagrafica | visite"}))
        self.assertEqual(caught.exception.field, wj.RIGHT_SHEET)
        self.assertIn('"Anagrafica | visite"', str(caught.exception))

    def test_dispatcher_passes_cancel(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ChainCancelled):
            analyse(wj.METHOD, pd.DataFrame({"ID": [1]}), options(), join_data=pd.DataFrame({"Key": [1]}),
                    cancel=cancel)


class Keys(unittest.TestCase):
    def test_typed_keys(self):
        left = pd.DataFrame({"ID": [1, True, "1", 2**53 + 1, " a", np.int16(7), np.float32(0.5)]}, dtype=object)
        right = pd.DataFrame({"Key": [1.0, 1, "1", float(2**53), "a", 7.0, 0.5], "V": list("abcdefg")},
                             dtype=object)
        result = join(left, right, **{wj.JOIN_TYPE: "Inner"})
        provenance = rows(result.tables[wj.PROVENANCE])
        self.assertEqual(provenance, [[1, 1, "Matched"], [1, 2, "Matched"], [3, 3, "Matched"],
                                      [6, 6, "Matched"], [7, 7, "Matched"]])

    def test_missing_keys_never_match(self):
        left = pd.DataFrame({"ID": [None, "", float("nan"), float("inf"), pd.NA, "x"]}, dtype=object)
        right = pd.DataFrame({"Key": [None, "", float("nan"), float("inf"), pd.NA, "x"]}, dtype=object)
        result = join(left, right)
        states = [row[2] for row in rows(result.tables[wj.PROVENANCE])]
        self.assertEqual(states, ["Left only"] * 5 + ["Matched"] + ["Right only"] * 5)
        metrics = dict(rows(result.tables[wj.DIAGNOSTICS]))
        self.assertEqual(metrics["Left rows with missing key"], 5)
        self.assertEqual(metrics["Right rows with missing key"], 5)

    def test_incomplete_composite_key_is_unmatched(self):
        left = pd.DataFrame({"A": [1, 1], "B": ["x", None]})
        right = pd.DataFrame({"A": [1, 1], "B": ["x", None], "V": [10, 20]})
        result = join(left, right, **{wj.LEFT_KEYS: ["A", "B"], wj.RIGHT_KEYS: ["A", "B"],
                                      wj.CARDINALITY: wj.ONE_TO_ONE})
        self.assertEqual(rows(result.tables[wj.PROVENANCE]),
                         [[1, 1, "Matched"], [2, None, "Left only"], [None, 2, "Right only"]])

    def test_unsupported_cell_type_is_a_field_error_on_its_pair(self):
        left = pd.DataFrame({"ID": [1], "When": [pd.Timestamp("2026-01-01")]})
        right = pd.DataFrame({"Key": [1], "When": [pd.Timestamp("2026-01-01")]})
        with self.assertRaises(wj.JoinKeyError) as caught:
            join(left, right, **{wj.LEFT_KEYS: ["ID", "When"], wj.RIGHT_KEYS: ["Key", "When"]})
        self.assertEqual((caught.exception.field, caught.exception.pair), (wj.LEFT_KEYS, 1))
        self.assertIn("row 1", str(caught.exception))

    def test_excluded_cells_arrive_blank(self):
        from analisi.data import Dataset
        dataset = Dataset(pd.DataFrame({"ID": [1, 2], "Y": [5.0, 6.0]}), excluded={(1, 0), (0, 1)})
        right = pd.DataFrame({"Key": [1, 2], "V": [10, 20]})
        result = join(dataset.frame(mask_excluded=True), right, **{wj.JOIN_TYPE: "Left"})
        self.assertEqual(rows(result.tables[wj.JOINED]), [[1, None, 10], [None, 6.0, None]])


class Shape(unittest.TestCase):
    def test_order_and_right_only_keys(self):
        left = pd.DataFrame({"ID": [3, 1, 2], "L": ["c", "a", "b"]}, index=[10, 10, -1])
        right = pd.DataFrame({"Key": [2, 9, 1, 2, 8], "R": ["b1", "z", "a", "b2", "y"]}, index=list("vwxyz"))
        result = join(left, right, **{wj.CARDINALITY: wj.ONE_TO_MANY})
        self.assertEqual(rows(result.tables[wj.JOINED]),
                         [[3, "c", None], [1, "a", "a"], [2, "b", "b1"], [2, "b", "b2"], [9, None, "z"],
                          [8, None, "y"]])
        self.assertEqual(rows(result.tables[wj.PROVENANCE]),
                         [[1, None, "Left only"], [2, 3, "Matched"], [3, 1, "Matched"], [3, 4, "Matched"],
                          [None, 2, "Right only"], [None, 5, "Right only"]])

    def test_index_does_not_change_the_result(self):
        left = pd.DataFrame({"ID": [1, 2, 2], "L": [1.5, 2.5, 3.5]})
        right = pd.DataFrame({"Key": [2, 1], "R": ["two", "one"]})
        plain = join(left, right)
        shuffled = join(left.set_axis(pd.MultiIndex.from_tuples([(1, "a"), (0, "b"), (1, "a")])),
                        right.set_axis(["q", "q"]))
        for name in (wj.JOINED, wj.PROVENANCE, wj.DIAGNOSTICS):
            pd.testing.assert_frame_equal(plain.tables[name], shuffled.tables[name])
        self.assertIsInstance(plain.tables[wj.JOINED].index, pd.RangeIndex)

    def test_suffixes_respect_existing_names(self):
        left = pd.DataFrame({"ID": [1], "Signal": [1], "Signal [right]": [2], "Note [right 2]": [3], "Note": [4]})
        right = pd.DataFrame({"Key": [1], "Signal": [5], "Note [right]": [6], "Note": [7], "Signal [right 2]": [8]})
        joined = join(left, right).tables[wj.JOINED]
        self.assertEqual(joined.columns.tolist(),
                         ["ID", "Signal", "Signal [right]", "Note [right 2]", "Note", "Signal [right 3]",
                          "Note [right]", "Note [right 3]", "Signal [right 2]"])
        self.assertEqual(rows(joined), [[1, 1, 2, 3, 4, 5, 6, 7, 8]])

    def test_schema_without_rows(self):
        left = pd.DataFrame({"ID": pd.Series([], dtype=float), "L": pd.Series([], dtype=object)})
        right = pd.DataFrame({"Key": [1], "R": ["x"]})
        for kind in wj.TYPES:
            result = join(left, right, **{wj.JOIN_TYPE: kind})
            self.assertEqual(result.tables[wj.JOINED].columns.tolist(), ["ID", "L", "R"])
            self.assertEqual(result.tables[wj.PROVENANCE].columns.tolist(), ["Left row", "Right row", "State"])
            self.assertEqual(len(result.tables[wj.JOINED]), 1 if kind == "Full" else 0)
        result = join(pd.DataFrame({"ID": [5]}), right, **{wj.JOIN_TYPE: "Inner"})
        self.assertTrue(result.tables[wj.JOINED].empty)
        self.assertEqual(dict(rows(result.tables[wj.DIAGNOSTICS]))["Unmatched right rows"], 1)

    def test_types_are_kept_with_blank_rows(self):
        big = 2**62 + 1
        left = pd.DataFrame({"ID": [1, 2], "Big": [big, 3], "Flag": [True, False]})
        right = pd.DataFrame({"Key": [1, 3], "Count": [big, 4]})
        joined = join(left, right).tables[wj.JOINED]
        self.assertEqual(joined["Big"].iloc[0], big)
        self.assertEqual(joined["Count"].iloc[0], big)
        self.assertEqual(str(joined["Big"].dtype), "Int64")
        self.assertEqual(joined["ID"].tolist(), [1, 2, 3])
        self.assertEqual(str(joined["Flag"].dtype), "boolean")

    def test_join_types(self):
        left = pd.DataFrame({"ID": [1, 2]})
        right = pd.DataFrame({"Key": [2, 3]})
        counts = {kind: len(join(left, right, **{wj.JOIN_TYPE: kind}).tables[wj.JOINED]) for kind in wj.TYPES}
        self.assertEqual(counts, {"Inner": 1, "Left": 2, "Full": 3})


class Validation(unittest.TestCase):
    def test_cardinality_checks_unmatched_keys(self):
        left = pd.DataFrame({"ID": [1, 5, 5]})
        right = pd.DataFrame({"Key": [1, 7, 7]})
        for rule, side in ((wj.ONE_TO_MANY, "left"), (wj.MANY_TO_ONE, "right"), (wj.ONE_TO_ONE, "left")):
            with self.assertRaises(FieldError) as caught:
                join(left, right, **{wj.CARDINALITY: rule, wj.JOIN_TYPE: "Inner"})
            self.assertEqual(caught.exception.field, wj.CARDINALITY)
            self.assertIn(f"The {side} worksheet repeats a key in rows 2 and 3.", str(caught.exception))
        join(left, right, **{wj.CARDINALITY: wj.MANY_TO_MANY})

    def test_budget_is_checked_before_expanding(self):
        left = pd.DataFrame({"ID": [1] * 2000})
        right = pd.DataFrame({"Key": [1] * 2000})
        tracemalloc.start()
        try:
            with self.assertRaises(FieldError) as caught:
                join(left, right, **{wj.JOIN_TYPE: "Inner"})
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(caught.exception.field, wj.JOIN_TYPE)
        self.assertIn("4,000,000 rows", str(caught.exception))
        self.assertLess(peak, 20_000_000)  # 4 million pairs were never materialized

    def test_cell_budget(self):
        wide = pd.DataFrame({f"C{index}": [index] * 4000 for index in range(250)})
        wide["ID"] = range(4000)
        right = pd.DataFrame({"Key": range(4000), **{f"R{index}": [0] * 4000 for index in range(251)}})
        with self.assertRaises(FieldError) as caught:
            join(wide, right, **{wj.LEFT_KEYS: ["ID"]})
        self.assertEqual(caught.exception.field, wj.JOIN_TYPE)
        self.assertIn("cells", str(caught.exception))

    def test_column_limit(self):
        left = pd.DataFrame({f"L{index}": [1] for index in range(300)})
        right = pd.DataFrame({f"R{index}": [1] for index in range(300)})
        with self.assertRaises(FieldError) as caught:
            join(left, right, **{wj.LEFT_KEYS: ["L0"], wj.RIGHT_KEYS: ["R0"]})
        self.assertEqual(caught.exception.field, wj.RIGHT_SHEET)

    def test_recipe_errors(self):
        left, right = pd.DataFrame({"ID": [1], "A": [1]}), pd.DataFrame({"Key": [1], "B": [1]})
        cases = [
            ({wj.LEFT_KEYS: []}, wj.LEFT_KEYS, None),
            ({wj.LEFT_KEYS: ["ID"] * 5, wj.RIGHT_KEYS: ["Key"] * 5}, wj.LEFT_KEYS, None),
            ({wj.LEFT_KEYS: ["ID", "A"]}, wj.RIGHT_KEYS, 1),
            ({wj.LEFT_KEYS: ["ID", "ID"], wj.RIGHT_KEYS: ["Key", "B"]}, wj.LEFT_KEYS, 1),
            ({wj.LEFT_KEYS: ["Nope"]}, wj.LEFT_KEYS, 0),
            ({wj.LEFT_KEYS: ["ID", "A"], wj.RIGHT_KEYS: ["Key", "Gone $"]}, wj.RIGHT_KEYS, 1),
            ({wj.JOIN_TYPE: "Outer"}, wj.JOIN_TYPE, None),
            ({wj.CARDINALITY: "Some"}, wj.CARDINALITY, None),
            ({wj.RIGHT_SHEET: ""}, wj.RIGHT_SHEET, None),
        ]
        for extra, field, pair in cases:
            with self.subTest(extra=extra), self.assertRaises(FieldError) as caught:
                join(left, right, **extra)
            self.assertEqual(caught.exception.field, field)
            self.assertEqual(getattr(caught.exception, "pair", None), pair)

    def test_defaults(self):
        recipe = options()
        del recipe[wj.JOIN_TYPE], recipe[wj.CARDINALITY]
        result = wj.join_worksheets(pd.DataFrame({"ID": [1, 2]}), pd.DataFrame({"Key": [1]}), recipe)
        self.assertEqual(len(result.tables[wj.JOINED]), 2)  # Left
        with self.assertRaises(FieldError):  # One-to-one
            wj.join_worksheets(pd.DataFrame({"ID": [1, 1]}), pd.DataFrame({"Key": [1]}), recipe)

    def test_cancel_between_rows(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ChainCancelled):
            wj.join_worksheets(pd.DataFrame({"ID": range(10)}), pd.DataFrame({"Key": range(10)}), options(),
                               cancel=cancel)


class Messages(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_catalog_pairs(self):
        self.assertEqual(set(EN), set(IT))
        for key in EN:
            self.assertEqual(i18n.placeholders(EN[key]), i18n.placeholders(IT[key]), key)

    def test_engine_messages_translate(self):
        left, right = pd.DataFrame({"ID": [1, 1]}), pd.DataFrame({"Key": [1]})
        raised = []
        for extra in ({wj.LEFT_KEYS: ["Nope"]}, {wj.CARDINALITY: wj.ONE_TO_ONE}, {wj.LEFT_KEYS: []},
                      {wj.JOIN_TYPE: "?"}, {wj.CARDINALITY: "?"}, {wj.LEFT_KEYS: ["ID", "ID"],
                                                                     wj.RIGHT_KEYS: ["Key", "Key"]}):
            with self.assertRaises(FieldError) as caught:
                join(left, right, **extra)
            raised.append(str(caught.exception))
        raised += [str(wj.missing_source("A $")), str(wj.missing_source(None)), str(wj.view_source("B")),
                   str(wj.same_source("C"))]
        with self.assertRaises(FieldError) as caught:
            join(pd.DataFrame({"ID": [1] * 400}), pd.DataFrame({"Key": [1] * 400}))
        raised.append(str(caught.exception))
        with self.assertRaises(FieldError) as caught:
            join(pd.DataFrame({"ID": [pd.Timestamp(0)]}), right)
        raised.append(str(caught.exception))
        i18n.set_language("it")
        for message in raised:
            with self.subTest(message=message):
                self.assertNotEqual(i18n.translate_message(message, "join.error."), message)


if __name__ == "__main__":
    unittest.main()
