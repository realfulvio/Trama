"""Remove baseline and column math with replicate subcolumns (package 05)."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.processing import FieldError
from analisi.workbench import analyse

DATA = Path(__file__).parent / "data"
BASELINE = "Remove baseline and column math"
REF, SIGNAL = ["Ref [1]", "Ref [2]"], ["Signal [1]", "Signal [2]"]
REF_B, SIGNAL_B = ["Ref B [1]", "Ref B [2]"], ["Signal B [1]", "Signal B [2]"]
E = np.nan
EACH, MEANS, MATCHED = "Each replicate vs baseline mean", "Mean vs baseline mean", "Matched subcolumns"
SAME_ROW, LINEAR = "Baseline column, same row", "Linear fit of baseline column vs X"
ACE, BDF = "Alternate columns: A, C, E… are baselines", "Alternate columns: B, D, F… are baselines"
FIRST, LAST = "Mean of first K rows", "Mean of last K rows"
DIFFERENCE, RATIO = "Difference: Y − baseline", "Ratio: Y / baseline"


def table(roles=True):
    frame = pd.read_csv(DATA / "replicate-baseline.csv")
    if roles:
        frame.attrs["worksheet_roles"] = {"x": ["X"], "y": [REF, SIGNAL, REF_B, SIGNAL_B]}
    return frame


def options(handling=EACH, **extra):
    return {"Data columns": SIGNAL, "Baseline subcolumns": REF, "X": "X", "Row titles": None,
            "Replicate handling": handling, "Baseline": SAME_ROW, "Rows for baseline (K)": 1,
            "Drop baseline rows": False, "Operation": DIFFERENCE, **extra}


def run(frame, **extra):
    return analyse(BASELINE, frame, options(**extra))


class ReplicateBaselineTests(unittest.TestCase):
    def values(self, result, columns, expected, sheet="Processed data"):
        np.testing.assert_allclose(result.tables[sheet][columns].to_numpy(dtype=float),
                                   np.asarray(expected, dtype=float), equal_nan=True)

    def field(self, field, frame, **extra):
        with self.assertRaises(FieldError) as caught:
            run(frame, **extra)
        self.assertEqual(caught.exception.field, field)
        return str(caught.exception)

    def test_three_modes_with_same_row_baseline(self):
        frame = table()
        each = run(frame)
        self.values(each, SIGNAL, [[7, 11], [7, 11], [E, E], [0, 8], [11, 13]])
        self.values(run(frame, **{"Replicate handling": MATCHED}), SIGNAL,
                    [[8, 10], [8, 10], [E, E], [0, 8], [12, 12]])
        means = run(frame, **{"Replicate handling": MEANS})
        self.assertEqual(list(means.tables["Processed data"].columns), ["X", "Signal"])
        self.values(means, "Signal", [9, 9, E, 4, 12])
        self.assertEqual(means.tables["Processed data"].attrs["worksheet_roles"], {"x": ["X"], "y": [["Signal"]]})
        processed = each.tables["Processed data"]
        self.assertEqual(list(processed.columns), ["X", *SIGNAL])
        self.assertEqual(processed.attrs["worksheet_roles"], {"x": ["X"], "y": [SIGNAL]})
        notes = each.tables["Notes"].to_string()
        self.assertIn(EACH, notes)
        self.assertIn("Ref [1], Ref [2]", notes)

    def test_ratio_leaves_zero_and_missing_baselines_blank(self):
        result = run(table(), Operation=RATIO)
        self.values(result, SIGNAL, [[10 / 3, 14 / 3], [12 / 5, 16 / 5], [E, E], [E, E], [20 / 9, 22 / 9]])
        self.assertIn("Zero denominators left blank", result.tables["Notes"].to_string())

    def test_alternate_datasets_pair_whole_groups(self):
        everything = REF + SIGNAL + REF_B + SIGNAL_B
        result = run(table(), **{"Data columns": everything, "Baseline": ACE})
        self.values(result, SIGNAL, [[7, 11], [7, 11], [E, E], [0, 8], [11, 13]])
        self.values(result, SIGNAL_B, [[6, 8], [6, 9], [6, 8], [3, 4], [9, 10]])
        self.assertEqual(result.tables["Processed data"].attrs["worksheet_roles"]["y"], [SIGNAL, SIGNAL_B])
        matched = run(table(), **{"Data columns": everything, "Baseline": ACE, "Replicate handling": MATCHED})
        self.values(matched, SIGNAL_B, [[6, 8], [7, 8], [6, E], [3, 4], [10, 9]])
        reverse = run(table(), **{"Data columns": everything, "Baseline": BDF})
        self.assertEqual(list(reverse.tables["Processed data"].columns), ["X", *REF, *REF_B])
        self.values(reverse, REF, [[-10, -8], [-10, -8], [E, E], [-4, -4], [-13, -11]])
        message = self.field("Data columns", table(), **{"Data columns": REF + SIGNAL + REF_B, "Baseline": ACE})
        self.assertIn("even number", message)

    def test_linear_fit_of_row_means_predicts_rows_without_baseline(self):
        frame = pd.read_csv(DATA / "replicate-baseline-linear.csv")  # no metadata: "Name [n]" titles
        result = run(frame, Baseline=LINEAR)
        line = result.tables["Linear baseline"]
        np.testing.assert_allclose(line["Predicted baseline"], [3, 5, 7, 9])
        np.testing.assert_allclose(line["Observed baseline mean"], [3, 5, E, 9], equal_nan=True)
        self.values(result, SIGNAL, [[7, 11], [7, 11], [8, 12], [11, 13]])
        self.values(run(frame, Baseline=LINEAR, **{"Replicate handling": MEANS}), "Signal", [9, 9, 10, 12])
        self.assertIn("linear baseline", self.field("Replicate handling", frame, Baseline=LINEAR,
                                                    **{"Replicate handling": MATCHED}))
        short = frame.copy()
        short.loc[1:, REF] = E
        self.assertIn("three rows", self.field("Baseline subcolumns", short, Baseline=LINEAR))

    def test_first_and_last_k_rows(self):
        frame = table()
        self.values(run(frame, Baseline=FIRST, **{"Rows for baseline (K)": 2}), SIGNAL,
                    [[-3, 1], [-1, 3], [2, 6], [-13, -5], [7, 9]])
        self.values(run(frame, Baseline=FIRST, **{"Rows for baseline (K)": 2, "Replicate handling": MATCHED}),
                    SIGNAL, [[-1, -1], [1, 1], [4, 4], [-11, -7], [9, 7]])
        self.values(run(frame, Baseline=FIRST, **{"Rows for baseline (K)": 2, "Replicate handling": MEANS}),
                    "Signal", [-1, 1, 4, -9, 8])
        # Last two physical rows: Signal [1] = 0, 20 and Signal [2] = 8, 22, pooled mean 12.5.
        last = run(frame, Baseline=LAST, **{"Rows for baseline (K)": 2, "Drop baseline rows": True})
        processed = last.tables["Processed data"]
        self.assertEqual(processed["X"].tolist(), [0, 1, 2])
        self.values(last, SIGNAL, [[-2.5, 1.5], [-.5, 3.5], [2.5, 6.5]])
        self.assertIn("Rows removed", last.tables["Notes"].to_string())
        holes = frame.copy()
        holes.loc[0:1, SIGNAL] = E
        self.assertIn("first 2 row(s)", self.field("Rows for baseline (K)", holes, Baseline=FIRST,
                                                   **{"Rows for baseline (K)": 2}))

    def test_excluded_cells_are_ignored_not_zero(self):
        dataset = Dataset(table(), table_format="XY with replicates")
        dataset.excluded.add((0, list(dataset.raw.columns).index("Ref [2]")))
        result = run(dataset.frame(mask_excluded=True))
        self.values(result, SIGNAL, [[8, 12], [7, 11], [E, E], [0, 8], [11, 13]])
        means = run(dataset.frame(mask_excluded=True), Baseline=FIRST, **{"Rows for baseline (K)": 1,
                                                                          "Replicate handling": MATCHED})
        self.values(means, SIGNAL, [[0, 0], [2, 2], [5, 5], [-10, -6], [10, 8]])
        dataset.excluded.add((0, list(dataset.raw.columns).index("Signal [1]")))
        pooled = run(dataset.frame(mask_excluded=True), Baseline=FIRST, **{"Rows for baseline (K)": 2})
        self.values(pooled, SIGNAL, [[E, 0], [-2, 2], [1, 5], [-14, -6], [6, 8]])

    def test_incompatible_and_incomplete_groups_are_field_errors(self):
        frame = table()
        frame["Ref [3]"] = [1., 2, 3, 4, 5]
        frame.attrs["worksheet_roles"] = {"x": ["X"], "y": [[*REF, "Ref [3]"], SIGNAL, REF_B, SIGNAL_B]}
        message = self.field("Baseline subcolumns", frame, **{"Baseline subcolumns": [*REF, "Ref [3]"],
                                                               "Replicate handling": MATCHED})
        self.assertIn("same number of replicates", message)
        self.assertIn("incomplete", self.field("Data columns", table(), **{"Data columns": ["Signal [1]"]}))
        self.assertIn("incomplete", self.field("Baseline subcolumns", table(), **{"Baseline subcolumns": ["Ref [1]"]}))
        self.assertIn("single", self.field("Baseline subcolumns", table(), **{"Baseline subcolumns": REF + REF_B}))
        self.assertIn("also selected", self.field("Baseline subcolumns", table(), **{"Data columns": REF}))
        self.assertIn("X", self.field("Baseline subcolumns", table(), X="Ref [1]"))

    def test_tables_without_metadata(self):
        self.values(run(table(roles=False)), SIGNAL, [[7, 11], [7, 11], [E, E], [0, 8], [11, 13]])
        plain = pd.DataFrame({"X": [0, 1], "A": [1., 2], "B": [3., 4], "C": [1., 1]})
        self.assertIn("does not belong", self.field("Baseline subcolumns", plain, **{"Data columns": ["A", "B"],
                                                                             "Baseline subcolumns": ["C"]}))
        summary = pd.DataFrame({"X": [0, 1], "A [Mean]": [1., 2], "A [SD]": [1., 1], "B [1]": [1., 1]})
        self.assertIn("summary subcolumn", self.field("Data columns", summary, **{
            "Data columns": ["A [Mean]", "A [SD]"], "Baseline subcolumns": ["B [1]"]}))

    def test_mean_name_is_disambiguated(self):
        frame = table()
        frame.insert(0, "Signal", ["a", "b", "c", "d", "e"])
        result = run(frame, **{"Replicate handling": MEANS, "Row titles": "Signal"})
        self.assertEqual(list(result.tables["Processed data"].columns), ["Signal", "X", "Signal (2)"])

    def test_legacy_recipe_keeps_independent_columns(self):
        legacy = {"Data columns": ["Signal [1]"], "Baseline column": "Ref [1]", "Baseline": SAME_ROW,
                  "Operation": DIFFERENCE}
        result = analyse(BASELINE, table(), legacy)
        np.testing.assert_allclose(result.tables["Processed data"]["Signal [1]"], [8, 8, E, 0, 12], equal_nan=True)
        self.assertNotIn("worksheet_roles", result.tables["Processed data"].attrs)
        same = analyse(BASELINE, table(), {**legacy, "Replicate handling": "Independent columns"})
        pd.testing.assert_frame_equal(same.tables["Processed data"], result.tables["Processed data"])

    def test_roles_survive_project_round_trip(self):
        processed = run(table()).tables["Processed data"].rename(columns=str)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.alab"
            save_project(path, {"Processed": Dataset(processed, table_format=processed.attrs["table_format"])})
            loaded = load_project(path)["Processed"]
        self.assertEqual(loaded.raw.attrs["worksheet_roles"], {"x": ["X"], "y": [SIGNAL]})
        self.assertEqual(loaded.table_format, "XY with replicates")
        again = run(loaded.frame(), **{"Data columns": SIGNAL, "Baseline": FIRST, "Replicate handling": MEANS})
        self.values(again, "Signal", [0, 0, E, -5, 3])


if __name__ == "__main__":
    unittest.main()
