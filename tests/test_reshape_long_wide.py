"""Reshape long and wide: the published fixtures, keys, levels, blanks, limits, types, round trips and cancel."""
import csv
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from analisi import reshape_long_wide as rl
from analisi.analysis_chain import ChainCancelled, result_frame
from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.field_error import FieldError
from analisi.workbench import GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "reshape_long_wide"
METHOD = "Reshape long and wide"
WIDEN = {"Direction": "Long to wide", "ID columns": ["Sample $", "Rep"], "Name column": "Visit",
         "Value column": "Measure"}
LENGTHEN = {"Direction": "Wide to long", "ID columns": ["Sample $", "Rep"], "Measure columns": ["A | Start", "Fine à"],
            "Output names": "Visit", "Output values": "Measure", "Drop missing values": False}


def run(frame, options, **kwargs):
    return analyse(METHOD, frame, options, **kwargs).tables


def sheet(name):
    """The fixture as the window reads it: CSV import, then the masked worksheet."""
    return Dataset(load_tables(DATA / name)[Path(name).stem]).frame(mask_excluded=True)


def blank(value):
    return value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value))


def cells(table):
    return [[None if blank(value) else value for value in row] for row in table.itertuples(index=False, name=None)]


class Fixtures(unittest.TestCase):
    def test_published_cases_on_the_imported_sheets(self):
        cases = json.loads((DATA / "casi.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                tables = run(sheet(case["csv"]), case["options"])
                for name, expected in case["tables"].items():
                    table = tables[name]
                    self.assertEqual(len(table), expected["count"])
                    self.assertEqual(list(table.columns)[:len(expected["columns"])], expected["columns"])
                    for position, row in enumerate(expected["rows"]):
                        for column, value in row.items():
                            actual = table.iloc[position][column]
                            if value is None:
                                self.assertTrue(blank(actual), (name, position, column, actual))
                            else:
                                self.assertEqual(actual, value, (name, position, column))

    def test_catalog_entry(self):
        self.assertIn(METHOD, GROUPS["Data Processing"])
        self.assertEqual(METHODS[METHOD], rl.OPTIONS)
        self.assertEqual(GROUPS["Data Processing"].index(METHOD), GROUPS["Data Processing"].index("Reshape replicates") + 1)


class LongToWide(unittest.TestCase):
    def test_keys_keep_their_type_and_text_is_literal(self):
        table = run(sheet("long.csv"), WIDEN)["Reshaped data"]
        self.assertEqual(table["Sample $"].tolist(), ["001", "001", "002", "002"])
        self.assertTrue(pd.api.types.is_string_dtype(table["Sample $"]))
        self.assertEqual(list(table.columns), ["Sample $", "Rep", "A | Start", "Fine à"])

    def test_levels_and_rows_follow_first_appearance(self):
        frame = pd.DataFrame({"id": ["b", "a", "b", "a", "c"], "lev": ["Z", "y", "y", "Z", "x"],
                              "v": [1., 2., 3., 4., 5.]})
        tables = run(frame, {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev",
                             "Value column": "v"})
        table = tables["Reshaped data"]
        self.assertEqual(list(table.columns), ["id", "Z", "y", "x"])
        self.assertEqual(cells(table), [["b", 1., 3., None], ["a", 4., 2., None], ["c", None, None, 5.]])
        # Unobserved combinations are blank and have no map row; every measure has one.
        self.assertEqual(len(tables["Source map"]), 5)
        settings = dict(zip(tables["Settings"]["Setting"], tables["Settings"]["Value"]))
        self.assertEqual(settings["Combinations never observed"], 4)
        self.assertEqual(settings["Blank cells"], 4)

    def test_levels_are_not_normalised(self):
        frame = pd.DataFrame({"id": [1, 1, 1, 1], "lev": ["Città", "citta", "CITTÀ", "-1"], "v": [1, 2, 3, 4]})
        table = run(frame, {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev",
                            "Value column": "v"})["Reshaped data"]
        self.assertEqual(list(table.columns), ["id", "Città", "citta", "CITTÀ", "-1"])

    def test_numeric_levels_use_their_shortest_form(self):
        frame = pd.DataFrame({"id": [1, 1, 1], "lev": [1.0, 2.5, 10.0], "v": [1, 2, 3]})
        table = run(frame, {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev",
                            "Value column": "v"})["Reshaped data"]
        self.assertEqual(list(table.columns), ["id", "1", "2.5", "10"])

    def test_a_number_and_a_text_with_the_same_name_are_an_error(self):
        frame = pd.DataFrame({"id": [1, 1, 2], "lev": pd.Series([1, "1", 1], dtype=object), "v": [1., 2., 3.]})
        with self.assertRaises(FieldError) as raised:
            run(frame, {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev", "Value column": "v"})
        self.assertEqual(raised.exception.field, "Name column")
        self.assertEqual(str(raised.exception), 'Rows 1 and 2 give the same column name "1" from different values: '
                                                '1 and "1".')

    def test_a_level_named_like_a_key_is_an_error(self):
        frame = pd.DataFrame({"Subject": ["s1", "s1"], "lev": ["Before", "Subject"], "v": [1., 2.]})
        with self.assertRaises(FieldError) as raised:
            run(frame, {"Direction": "Long to wide", "ID columns": ["Subject"], "Name column": "lev",
                        "Value column": "v"})
        self.assertEqual(raised.exception.field, "Name column")
        self.assertIn('"Subject" (row 2)', str(raised.exception))

    def test_duplicates_show_both_rows_even_with_a_blank_measure(self):
        frame = pd.DataFrame({"id": ["a", "b", "a"], "lev": ["x", "x", "x"], "v": [1., 2., None]})
        with self.assertRaises(FieldError) as raised:
            run(frame, {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev", "Value column": "v"})
        self.assertEqual(raised.exception.field, "ID columns")
        self.assertTrue(str(raised.exception).startswith('Rows 1 and 3 have the same ID and level "x".'))

    def test_large_integer_keys_and_values_stay_exact(self):
        big = 2 ** 62
        frame = pd.DataFrame({"plate": np.array([big + 1, big + 1, big + 2], dtype=np.int64),
                              "well": ["A1", "A1", "A1"], "lev": ["x", "y", "x"],
                              "v": np.array([big + 5, 7, 9], dtype=np.int64)})
        tables = run(frame, {"Direction": "Long to wide", "ID columns": ["plate", "well"], "Name column": "lev",
                             "Value column": "v"})
        table = tables["Reshaped data"]
        self.assertEqual(table["plate"].tolist(), [big + 1, big + 2])
        self.assertEqual(table["x"].tolist(), [big + 5, 9])
        self.assertEqual(table["y"].iloc[0], 7)
        self.assertTrue(blank(table["y"].iloc[1]))
        self.assertEqual(str(table["y"].dtype), "Int64")  # a float could not hold big + 5 exactly

    def test_blank_key_names_the_row_and_empty_rows_are_skipped(self):
        frame = pd.DataFrame({"id": ["a", None, "b", None], "lev": ["x", "x", "x", None], "v": [1., 2., 3., None]})
        with self.assertRaises(FieldError) as raised:
            run(frame, {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev", "Value column": "v"})
        self.assertEqual((raised.exception.field, str(raised.exception)),
                         ("ID columns", 'Row 2 has no value in ID column "id".'))
        tables = run(frame.drop(index=1), {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev",
                                           "Value column": "v"})
        self.assertEqual(cells(tables["Reshaped data"]), [["a", 1.], ["b", 3.]])
        self.assertEqual(tables["Source map"]["Source row"].tolist(), [1, 2])

    def test_blank_level_is_an_error_on_name_column(self):
        frame = pd.DataFrame({"id": ["a", "b"], "lev": ["x", ""], "v": [1., 2.]})
        with self.assertRaises(FieldError) as raised:
            run(frame, {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev", "Value column": "v"})
        self.assertEqual((raised.exception.field, str(raised.exception)),
                         ("Name column", 'Row 2 has no value in the name column "lev".'))

    def test_excluded_values_stay_blank_and_mapped(self):
        dataset = Dataset(pd.DataFrame({"id": ["a", "a"], "lev": ["x", "y"], "v": [1, 2]}))
        dataset.excluded.add((1, 2))
        tables = run(dataset.frame(mask_excluded=True), {"Direction": "Long to wide", "ID columns": ["id"],
                                                         "Name column": "lev", "Value column": "v"})
        self.assertEqual(cells(tables["Reshaped data"]), [["a", 1, None]])
        self.assertEqual(tables["Source map"]["Result column"].tolist(), ["x", "y"])
        self.assertEqual(dataset.raw["v"].tolist(), [1, 2])  # the source is never written

    def test_roles_must_be_distinct(self):
        frame = pd.DataFrame({"a": [1], "b": ["x"], "c": [2.]})
        for options, field in (({"ID columns": ["a", "a"], "Name column": "b", "Value column": "c"}, "ID columns"),
                               ({"ID columns": ["a"], "Name column": "a", "Value column": "c"}, "Name column"),
                               ({"ID columns": ["a"], "Name column": "b", "Value column": "a"}, "Value column"),
                               ({"ID columns": ["a"], "Name column": "b", "Value column": "b"}, "Value column"),
                               ({"ID columns": [], "Name column": "b", "Value column": "c"}, "ID columns"),
                               ({"ID columns": ["zz"], "Name column": "b", "Value column": "c"}, "ID columns"),
                               ({"ID columns": ["a"], "Name column": "", "Value column": "c"}, "Name column")):
            with self.subTest(options=options), self.assertRaises(FieldError) as raised:
                run(frame, {"Direction": "Long to wide", **options})
            self.assertEqual(raised.exception.field, field)
        with self.assertRaises(FieldError) as raised:
            run(frame, {"Direction": "Sideways"})
        self.assertEqual(raised.exception.field, "Direction")


class WideToLong(unittest.TestCase):
    def test_mixed_measure_types_are_kept(self):
        frame = pd.DataFrame({"id": ["001", "002"], "n": [5, 0], "label": ["5", "x"],
                              "ok": [True, False]})
        tables = run(frame, {"Direction": "Wide to long", "ID columns": ["id"], "Measure columns": ["n", "label", "ok"]})
        values = tables["Reshaped data"]["Value"].tolist()
        self.assertEqual(values, [5, "5", True, 0, "x", False])
        self.assertEqual([type(value) for value in values[:3]], [int, str, bool])
        settings = dict(zip(tables["Settings"]["Setting"], tables["Settings"]["Value"]))
        self.assertEqual([settings[f"Measure type {n}"] for n in (1, 2, 3)], ["Numeric", "Text", "Numeric"])
        self.assertEqual(settings["Values type"], "Mixed")

    def test_drop_missing_keeps_zero_false_and_text(self):
        frame = pd.DataFrame({"id": [1, 2], "a": pd.Series([0, None], dtype=object),
                              "b": pd.Series([False, ""], dtype=object), "c": pd.Series(["x", " "], dtype=object)})
        tables = run(frame, {"Direction": "Wide to long", "ID columns": ["id"], "Measure columns": ["a", "b", "c"],
                             "Drop missing values": True})
        self.assertEqual(cells(tables["Reshaped data"]),
                         [[1, "a", 0], [1, "b", False], [1, "c", "x"], [2, "c", " "]])
        self.assertEqual(tables["Source map"][["Source row", "Source column", "Result row"]].values.tolist(),
                         [[1, "a", 1], [1, "b", 2], [1, "c", 3], [2, "c", 4]])

    def test_order_is_source_rows_then_measure_order(self):
        frame = pd.DataFrame({"id": ["r1", "r2"], "B": [1, 2], "A": [3, 4]})
        table = run(frame, {"Direction": "Wide to long", "ID columns": ["id"],
                            "Measure columns": ["A", "B"]})["Reshaped data"]
        self.assertEqual(cells(table), [["r1", "A", 3], ["r1", "B", 1], ["r2", "A", 4], ["r2", "B", 2]])

    def test_ambiguous_keys_show_both_rows(self):
        frame = pd.DataFrame({"Subject": ["s1", "s2", "s1"], "Arm": ["L", "L", "R"], "v": [1., 2., 3.]})
        options = {"Direction": "Wide to long", "ID columns": ["Subject"], "Measure columns": ["v"]}
        with self.assertRaises(FieldError) as raised:
            run(frame, options)
        self.assertEqual((raised.exception.field, str(raised.exception)),
                         ("ID columns", "Rows 1 and 3 have the same ID. Add an ID column that tells them apart."))
        table = run(frame, {**options, "ID columns": ["Subject", "Arm"]})["Reshaped data"]
        self.assertEqual(len(table), 3)

    def test_output_names_are_checked_against_the_keys(self):
        frame = pd.DataFrame({"Subject": ["s1"], "Variable": ["x"], "v": [1.]})
        base = {"Direction": "Wide to long", "ID columns": ["Subject", "Variable"], "Measure columns": ["v"]}
        for options, field, text in (
                ({}, "Output names", 'The name "Variable" is already used by an ID column.'),
                ({"Output names": "Name", "Output values": "Subject"}, "Output values",
                 'The name "Subject" is already used by an ID column.'),
                ({"Output names": "Same", "Output values": "Same"}, "Output values",
                 "The column of names and the column of values need different names."),
                ({"Output names": "  "}, "Output names", "Enter a name for the column of names.")):
            with self.subTest(options=options), self.assertRaises(FieldError) as raised:
                run(frame, {**base, **options})
            self.assertEqual((raised.exception.field, str(raised.exception)), (field, text))
        with self.assertRaises(FieldError) as raised:
            run(frame, {"Direction": "Wide to long", "ID columns": ["Subject"], "Measure columns": ["Subject", "v"]})
        self.assertEqual(raised.exception.field, "Measure columns")

    def test_names_with_separators_are_literal(self):
        frame = pd.DataFrame({"id | key": ["1 | 2"], "$ cost": [3.], "a | b": [4.]})
        tables = run(frame, {"Direction": "Wide to long", "ID columns": ["id | key"],
                             "Measure columns": ["$ cost", "a | b"]})
        self.assertEqual(cells(tables["Reshaped data"]), [["1 | 2", "$ cost", 3.], ["1 | 2", "a | b", 4.]])


class RoundTrips(unittest.TestCase):
    def test_wide_long_wide_is_identity_with_explicit_types(self):
        wide = sheet("wide.csv")
        back = run(run(wide, LENGTHEN)["Reshaped data"], WIDEN)["Reshaped data"]
        pd.testing.assert_frame_equal(back, wide.reset_index(drop=True), check_dtype=True)

    def test_long_wide_long_restores_complete_tables_only(self):
        long = sheet("long.csv")
        back = run(run(long, WIDEN)["Reshaped data"], LENGTHEN)["Reshaped data"]
        pd.testing.assert_frame_equal(back, long, check_dtype=True)
        # A combination that was never observed comes back as an explicit blank row: the long table cannot tell
        # "absent" from "present but blank" once it has been widened.
        partial = long.drop(index=3).reset_index(drop=True)
        back = run(run(partial, WIDEN)["Reshaped data"], LENGTHEN)["Reshaped data"]
        self.assertEqual(len(back), len(long))
        self.assertTrue(blank(back.iloc[3]["Measure"]))
        dropped = run(run(partial, WIDEN)["Reshaped data"], {**LENGTHEN, "Drop missing values": True})
        self.assertEqual(len(dropped["Reshaped data"]), len(partial))

    def test_mixed_column_round_trip_in_project_and_csv(self):
        frame = pd.DataFrame({"Code": pd.array(["001", "002"], dtype="string"), "Count": [5, 7],
                              "Label": pd.array(["5", "x"], dtype="string")})
        table = run(frame, {"Direction": "Wide to long", "ID columns": ["Code"],
                            "Measure columns": ["Count", "Label"]})["Reshaped data"]
        self.assertEqual(table["Value"].tolist(), [5, "5", 7, "x"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mixed.alab"
            save_project(path, {"Long": Dataset(result_frame(analyse(
                METHOD, frame, {"Direction": "Wide to long", "ID columns": ["Code"],
                                "Measure columns": ["Count", "Label"]}), "Reshaped data"))})
            reopened = load_project(path)["Long"].raw
            self.assertEqual(reopened["Code"].tolist(), ["001", "001", "002", "002"])
            self.assertEqual(reopened["Value"].tolist(), [5, "5", 7, "x"])  # the .alab keeps the mixed column
            csv_path = Path(folder) / "long.csv"
            table.to_csv(csv_path, index=False)
            with csv_path.open(encoding="utf-8", newline="") as stream:
                written = list(csv.reader(stream))
            self.assertEqual(written[1:], [["001", "Count", "5"], ["001", "Label", "5"],
                                           ["002", "Count", "7"], ["002", "Label", "x"]])
            # CSV has no types: the number 5 and the text "5" read back the same (see the guide).
            imported = next(iter(load_tables(csv_path).values()))
            self.assertEqual(imported["Code"].tolist(), ["001", "001", "002", "002"])
            self.assertEqual(imported["Value"].tolist(), ["5", "5", "7", "x"])

    def test_recipe_round_trip_in_project(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recipe.alab"
            dataset = Dataset(sheet("long.csv"))
            dataset.analyses = [(METHOD, dict(WIDEN))]
            save_project(path, {"Long $": dataset})
            reopened = load_project(path)["Long $"]
            self.assertEqual(reopened.analyses, [(METHOD, WIDEN)])
            pd.testing.assert_frame_equal(run(reopened.frame(mask_excluded=True), WIDEN)["Reshaped data"],
                                          run(sheet("long.csv"), WIDEN)["Reshaped data"])


class SyntheticProject(unittest.TestCase):
    def test_example_project_opens_and_recalculates_the_chain(self):
        from analisi.analysis_chain import ResultSource
        example = Path(__file__).resolve().parents[1] / "docs" / "examples" / "rimodella-visite.alab"
        tables = load_project(example)
        dataset = tables["reshape visits"]
        self.assertEqual(dataset.analyses[0], (METHOD, WIDEN | {"ID columns": ["Sample $", "Rep"]}))
        self.assertEqual(dataset.excluded, {(4, 3)})
        source = dataset.analysis_sources[1]
        self.assertIsInstance(source, ResultSource)
        self.assertEqual(source.table, "Reshaped data")
        reshaped = analyse(METHOD, dataset.frame(mask_excluded=True), dataset.analyses[0][1])
        self.assertEqual(cells(reshaped.tables["Reshaped data"]),
                         [["001", 1, 5, 6], ["001", 2, 0, None], ["002", 1, None, 7], ["002", 2, 9, 11]])
        graph = analyse("Column graph", result_frame(reshaped, "Reshaped data"), dataset.analyses[1][1])
        self.assertIsNotNone(graph.figure)


class Limits(unittest.TestCase):
    def widen(self, rows, levels, ids=1):
        frame = pd.DataFrame({**{f"k{n}": np.repeat(np.arange(rows), levels) for n in range(ids)},
                              "lev": np.tile([f"L{n}" for n in range(levels)], rows),
                              "v": np.arange(rows * levels, dtype=float)})
        return {"Direction": "Long to wide", "ID columns": [f"k{n}" for n in range(ids)], "Name column": "lev",
                "Value column": "v"}, frame

    def test_result_exactly_at_the_cell_limit(self):
        options, frame = self.widen(5, 3)  # 5 rows × (1 + 3) columns = 20 cells, map 15 × 4 = 60
        with mock.patch.object(rl, "MAX_CELLS", 60):
            self.assertEqual(run(frame, options)["Reshaped data"].shape, (5, 4))
        with mock.patch.object(rl, "MAX_CELLS", 59), self.assertRaises(FieldError) as raised:
            run(frame, options)
        self.assertEqual(str(raised.exception), "The source map would have 15 rows; the limit is 14.")
        options, frame = self.widen(5, 1, ids=3)  # 5 × 4 = 20 cells, map 5 × 4 = 20
        with mock.patch.object(rl, "MAX_CELLS", 20):
            self.assertEqual(run(frame, options)["Reshaped data"].shape, (5, 4))
        with mock.patch.object(rl, "MAX_CELLS", 19), self.assertRaises(FieldError) as raised:
            run(frame, options)
        self.assertEqual((raised.exception.field, str(raised.exception)),
                         ("Name column", "The result would have 20 cells (5 rows × 4 columns); the limit is 19."))

    def test_column_limit_counts_the_levels(self):
        options, frame = self.widen(2, 6)
        with mock.patch.object(rl, "MAX_COLUMNS", 7):
            self.assertEqual(run(frame, options)["Reshaped data"].shape, (2, 7))
        with mock.patch.object(rl, "MAX_COLUMNS", 6), self.assertRaises(FieldError) as raised:
            rl.preview(frame, options)
        self.assertEqual(str(raised.exception), "The result would have 7 columns; the limit is 6.")

    def test_real_limit_two_million_cells(self):
        options, frame = self.widen(500_000, 1, ids=3)  # 500,000 × 4 = 2,000,000 cells, map 2,000,000 cells
        self.assertEqual(run(frame, options)["Reshaped data"].size, rl.MAX_CELLS)
        options, frame = self.widen(500_001, 1, ids=3)
        with self.assertRaises(FieldError):
            rl.plan(frame, options)

    def test_unpivot_over_budget_fails_before_allocating(self):
        frame = pd.DataFrame({"id": np.arange(10), **{f"m{n}": np.ones(10) for n in range(5)}})
        options = {"Direction": "Wide to long", "ID columns": ["id"], "Measure columns": [f"m{n}" for n in range(5)]}
        with mock.patch.object(rl, "MAX_CELLS", 149), self.assertRaises(FieldError) as raised:
            run(frame, options)  # 50 rows × 3 columns = 150 cells
        self.assertEqual(raised.exception.field, "Measure columns")


class Preview(unittest.TestCase):
    def test_preview_is_the_head_of_the_result(self):
        frame = pd.DataFrame({"id": np.repeat(np.arange(40), 20), "lev": np.tile([f"L{n}" for n in range(20)], 40),
                              "v": np.arange(800.)})
        options = {"Direction": "Long to wide", "ID columns": ["id"], "Name column": "lev", "Value column": "v"}
        shown = rl.preview(frame, options)
        full = run(frame, options)["Reshaped data"]
        self.assertEqual((shown.rows, shown.columns, shown.table.shape), (40, 21, (25, 12)))
        self.assertEqual((shown.hidden_rows, shown.hidden_columns, shown.mapped, shown.missing), (15, 9, 800, 0))
        pd.testing.assert_frame_equal(shown.table, full.iloc[:25, :12])

    def test_preview_of_unpivot_and_its_errors(self):
        wide = sheet("wide.csv")
        shown = rl.preview(wide, {**LENGTHEN, "Drop missing values": True}, rows=3)
        self.assertEqual((shown.rows, shown.mapped, shown.missing, len(shown.table)), (7, 7, 0, 3))
        self.assertEqual(shown.table["Measure"].tolist(), [5, 6, 0])
        with self.assertRaises(FieldError) as raised:
            rl.preview(sheet("long.csv"), {**WIDEN, "ID columns": ["Sample $"]})
        self.assertEqual(raised.exception.field, "ID columns")


class Cancel(unittest.TestCase):
    class After:
        """An event that reports set after ``count`` checks: cancellation in the middle of the work."""

        def __init__(self, count):
            self.count = count

        def is_set(self):
            self.count -= 1
            return self.count < 0

    def test_cancel_before_and_during(self):
        frame = sheet("long.csv")
        event = threading.Event()
        event.set()
        with self.assertRaises(rl.ReshapeCancelled):
            run(frame, WIDEN, cancel=event)
        checks = 0
        while True:
            try:
                run(frame, WIDEN, cancel=self.After(checks))
            except rl.ReshapeCancelled:
                checks += 1
                continue
            break
        self.assertGreater(checks, 4)  # every phase checks: keys, levels, each column, map
        self.assertTrue(issubclass(rl.ReshapeCancelled, ChainCancelled))


class Legacy(unittest.TestCase):
    def test_reshape_replicates_and_extract_rearrange_unchanged(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_legacy", DATA / "make_legacy.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = json.loads((DATA / "legacy.json").read_text(encoding="utf-8"))
        for case in expected:
            with self.subTest(method=case["method"], options=case["options"]):
                current = module.encode(analyse(case["method"], module.TABLE.copy(), case["options"]))
                self.assertEqual(current, case["tables"])


if __name__ == "__main__":
    unittest.main()
