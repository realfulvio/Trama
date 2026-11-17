import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from analisi.processing import FieldError
from analisi.transpose_xy import (ASCENDING, MAX_SETS, REPLICATES, SINGLE, SUMMARY_MEAN, TRANSPOSE_XY, propose_sets,
                                  proposed_x)
from analisi.workbench import GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "transpose_xy"
SINGLE_A = {"name": "Single A", "mode": SINGLE, "columns": ["A"]}
REP_A = {"name": "Rep A", "mode": REPLICATES, "columns": ["A [1]", "A [2]"]}
MEAN_B = {"name": "Mean B", "mode": SUMMARY_MEAN, "columns": ["B [Mean]"]}
BASE = {"X": "Dose", "Row title": "Title"}


def run(frame, **options):
    return analyse(TRANSPOSE_XY, frame, {**BASE, **options})


class TransposeXyTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.read_csv(DATA / "xy.csv")
        self.expected = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))

    def failure(self, frame, field, **options):
        with self.assertRaises(FieldError) as caught:
            run(frame, **options)
        self.assertEqual(caught.exception.field, field)
        return str(caught.exception)

    def test_fixture_cases(self):
        cases = {
            "single": {"Y sets": [SINGLE_A]},
            "stable-sort": {"Y sets": [SINGLE_A], "Order": ASCENDING},
            "mixed-blocks": {"Y sets": [REP_A, MEAN_B]},
            "transform-after-swap": {"Y sets": [REP_A, MEAN_B], "X transform": "Log10", "Y transform": "Reciprocal"},
        }
        for name, options in cases.items():
            with self.subTest(name):
                result = run(self.frame, **options)
                for sheet, wanted in self.expected[name].items():
                    data = result.tables[sheet].astype(object)
                    actual = data.where(data.notna(), None).to_numpy().tolist()
                    self.assertEqual(len(actual), len(wanted))
                    for row, expect in zip(actual, wanted):
                        for value, target in zip(row, expect):
                            if isinstance(target, (int, float)):
                                self.assertAlmostEqual(value, target, delta=1e-10 * max(1, abs(target)))
                            else:
                                self.assertEqual(value, target)

    def test_output_contract(self):
        result = run(self.frame, **{"Y sets": [REP_A, MEAN_B]})
        self.assertEqual(list(result.tables), ["Transposed XY", "Source rows", "Settings"])
        table = result.tables["Transposed XY"]
        self.assertEqual(list(table.columns), ["X", "Row title", "Rep A", "Mean B"])
        self.assertIsInstance(table.index, pd.RangeIndex)
        self.assertEqual(table.attrs["worksheet_roles"], {"x": ["X"], "y": [["Rep A"], ["Mean B"]]})
        self.assertEqual(table.attrs["table_format"], "xy")
        self.assertIsNone(result.figure)
        settings = result.tables["Settings"]["Value"]
        self.assertEqual((settings["Input rows"], settings["Output rows"]), (6, 8))

    def test_without_row_title_and_with_plot(self):
        result = analyse(TRANSPOSE_XY, self.frame, {"X": "Dose", "Y sets": [SINGLE_A, MEAN_B], "Plot": True})
        self.assertEqual(list(result.tables["Transposed XY"].columns), ["X", "Single A", "Mean B"])
        self.assertEqual(len(result.figure.axes[0].lines), 2)

    def test_duplicate_index_and_source_positions(self):
        frame = self.frame.set_index(pd.Index([5, 5, 5, 5, 5, 5]))
        sources = run(frame, **{"Y sets": [SINGLE_A]}).tables["Source rows"]
        self.assertEqual(sources["Source row"].tolist(), [1, 3, 5, 6])

    def test_replicate_mean_ignores_blanks_and_avoids_overflow(self):
        frame = pd.DataFrame({"Dose": [1., 2, 3], "R [1]": [1e308, None, None], "R [2]": [1e308, 4, None]})
        result = analyse(TRANSPOSE_XY, frame, {"X": "Dose", "Y sets": [
            {"name": "R", "mode": REPLICATES, "columns": ["R [1]", "R [2]"]}]})
        np.testing.assert_allclose(result.tables["Transposed XY"]["X"], [1e308, 4])
        self.assertEqual(result.tables["Source rows"]["N present"].tolist(), [2, 1])

    def test_errors_name_their_field(self):
        cases = (
            ("Y sets", {"Y sets": [SINGLE_A, SINGLE_A]}),
            ("Y sets", {"Y sets": [SINGLE_A, {**MEAN_B, "columns": ["A"]}]}),
            ("Y sets", {"Y sets": [{**SINGLE_A, "name": "X"}]}),
            ("Y sets", {"Y sets": [{**SINGLE_A, "name": "Dose"}]}),
            ("Y sets", {"Y sets": [{**SINGLE_A, "columns": ["Dose"]}]}),
            ("Y sets", {"Y sets": [{**REP_A, "columns": ["A [1]"]}]}),
            ("Y sets", {"Y sets": [{**SINGLE_A, "columns": ["A", "A [1]"]}]}),
            ("Y sets", {"Y sets": [{**SINGLE_A, "columns": ["missing"]}]}),
            ("Y sets", {"Y sets": []}),
            ("Y sets", {"Y sets": [{**SINGLE_A, "mode": "Other"}]}),
            ("Y sets", {"Y sets": [{"name": f"S{i}", "mode": SINGLE, "columns": ["A"]} for i in range(MAX_SETS + 1)]}),
            ("Row title", {"Y sets": [SINGLE_A], "Row title": "Dose"}),
            ("Row title", {"Y sets": [SINGLE_A], "Row title": "missing"}),
            ("X", {"Y sets": [SINGLE_A], "X": "missing"}),
            ("Order", {"Y sets": [SINGLE_A], "Order": "Random"}),
            ("X transform", {"Y sets": [SINGLE_A], "X transform": "Square"}),
        )
        for field, options in cases:
            with self.subTest(options):
                self.failure(self.frame, field, **options)

    def test_data_and_transform_errors(self):
        self.failure(self.frame.assign(A="bad"), "Y sets", **{"Y sets": [SINGLE_A]})
        self.failure(self.frame.assign(Dose="bad"), "X", **{"Y sets": [SINGLE_A]})
        self.failure(self.frame.assign(A=float("inf")), "Y sets", **{"Y sets": [SINGLE_A]})
        self.failure(self.frame.assign(A=None), "Y sets", **{"Y sets": [SINGLE_A]})
        self.failure(self.frame.assign(A=0), "X transform", **{"Y sets": [SINGLE_A], "X transform": "Log10"})
        self.failure(self.frame.assign(A=0), "X transform", **{"Y sets": [SINGLE_A], "X transform": "Reciprocal"})
        self.failure(self.frame.assign(Dose=0), "Y transform", **{"Y sets": [SINGLE_A], "Y transform": "Reciprocal"})
        self.failure(self.frame.assign(Dose=-1), "Y transform", **{"Y sets": [SINGLE_A], "Y transform": "Log10"})
        self.failure(self.frame.assign(A=1e-320), "X transform", **{"Y sets": [SINGLE_A], "X transform": "Reciprocal"})

    def test_empty_set_among_others_is_allowed(self):
        frame = self.frame.assign(A=None)
        result = run(frame, **{"Y sets": [SINGLE_A, MEAN_B]})
        self.assertEqual(result.tables["Source rows"]["Series"].unique().tolist(), ["Mean B"])
        self.assertEqual(list(result.tables["Transposed XY"].columns), ["X", "Row title", "Single A", "Mean B"])

    def test_cell_budget_is_checked_before_building(self):
        wide = pd.DataFrame({"Dose": np.arange(1., 60_001), **{f"Y{i}": np.arange(1., 60_001) for i in range(40)}})
        message = self.failure(wide, "Y sets", **{"Row title": None, "Y sets": [
            {"name": f"S{i}", "mode": SINGLE, "columns": [f"Y{i}"]} for i in range(40)]})
        self.assertIn("cells", message)

    def test_proposed_roles(self):
        frame = self.frame.copy()
        self.assertIsNone(proposed_x(frame))
        # Without roles the titles decide: plain numeric columns, "Name [n]" replicates and "Name [Mean]".
        self.assertEqual(propose_sets(frame, "Dose"), [
            {"name": "A", "mode": SINGLE, "columns": ["A"]},
            {"name": "A (2)", "mode": REPLICATES, "columns": ["A [1]", "A [2]"]},
            {"name": "B", "mode": SUMMARY_MEAN, "columns": ["B [Mean]"]}])
        frame.attrs["worksheet_roles"] = {"x": ["Dose"], "y": [["A [1]", "A [2]"], ["B [Mean]", "B [SD]"], ["A"]]}
        self.assertEqual(proposed_x(frame), "Dose")
        self.assertEqual(propose_sets(frame, "Dose"), [
            {"name": "A", "mode": REPLICATES, "columns": ["A [1]", "A [2]"]},
            {"name": "B", "mode": SUMMARY_MEAN, "columns": ["B [Mean]"]},
            {"name": "A (2)", "mode": SINGLE, "columns": ["A"]}])

    def test_catalog(self):
        self.assertIn(TRANSPOSE_XY, GROUPS["Data Processing"])
        self.assertIn(TRANSPOSE_XY, METHODS)
        self.assertTrue(analyse("Transform", self.frame, {"Variables": ["Dose"], "Operation": "Square"}).tables)


if __name__ == "__main__":
    unittest.main()
