import unittest

import numpy as np
import pandas as pd

from analisi.data import Dataset
from analisi.operations import adjust_p, normalize, reshape_replicates, row_statistics


class OperationsTests(unittest.TestCase):
    def test_normalize_uses_independent_column_range_and_keeps_blanks(self):
        table = pd.DataFrame({"x": [1, 2, None, 3], "y": [10, 30, 20, 50]})
        normalized = normalize(table, ["x", "y"], "Percent of range")
        np.testing.assert_allclose(normalized["x"], [0, 50, np.nan, 100])
        np.testing.assert_allclose(normalized["y"], [0, 50, 25, 100])

    def test_replicate_reshape_retains_original_subject_and_groups(self):
        table = pd.DataFrame({"Condition": ["before", "after"], "A [1]": [1, 2], "A [2]": [3, 4]})
        long = reshape_replicates(table, ["A [1]", "A [2]"], "Condition")
        self.assertEqual(list(long.columns), ["Condition", "Series", "Replicate", "Value"])
        self.assertEqual(long["Series"].tolist(), ["A"] * 4)
        self.assertEqual(long["Replicate"].tolist(), [1, 1, 2, 2])
        self.assertEqual(long["Value"].tolist(), [1, 2, 3, 4])

    def test_adjust_p_preserves_input_order_and_missing(self):
        values = pd.DataFrame({"p": [.04, np.nan, .01, .2]})
        got = adjust_p(values, "p", "fdr_bh")
        np.testing.assert_allclose(got["Adjusted p"], [.06, np.nan, .03, .2])

    def test_row_statistics_has_missing_rows(self):
        got = row_statistics(pd.DataFrame({"a": [1, None], "b": [3, None]}), ["a", "b"])
        self.assertEqual(got.loc[0, "Mean"], 2)
        self.assertEqual(got.loc[1, "N"], 0)
        self.assertTrue(pd.isna(got.loc[1, "Sum"]))

    def test_averageif_formula_reacts_to_source_data(self):
        ds = Dataset(pd.DataFrame({"Group": ["Control", "Treated", "Control"], "Ct": [4, 6, 8]}))
        ds.set_formula("Control mean", '=AVERAGEIF(Group, "Control", Ct)')
        self.assertEqual(ds.frame()["Control mean"].tolist(), [6, 6, 6])
        ds.raw.loc[0, "Ct"] = 6
        self.assertEqual(ds.frame()["Control mean"].tolist(), [7, 7, 7])
