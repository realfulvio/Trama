"""Pairwise missing data, inference and rank-permutation regression checks."""
from itertools import permutations
from math import factorial
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi.correlation_matrix import CORRELATION_MATRIX
from analisi.processing import FieldError
from analisi.workbench import analyse


class CorrelationMatrixTests(unittest.TestCase):
    def matrix(self, data, **options):
        frame = pd.DataFrame(data)
        return analyse(CORRELATION_MATRIX, frame, {"Variables": list(frame), **options})

    def test_pearson_pairwise_and_listwise_match_scipy(self):
        data = {"A": [1, 2, 5, 4, None, 6, 7],
                "B": [2, 4, 3, 1, 9, None, 8],
                "C": [8, None, 6, 5, 4, 2, 1]}
        frame = pd.DataFrame(data)
        for missing in ("Pairwise complete", "Listwise complete"):
            with self.subTest(missing=missing):
                result = self.matrix(data, **{"Missing values": missing, "Confidence level (%)": 90})
                tables = result.tables
                for a, b in (("A", "B"), ("A", "C"), ("B", "C")):
                    pair = (frame.dropna() if missing == "Listwise complete" else frame)[[a, b]].dropna()
                    test = stats.pearsonr(pair[a], pair[b])
                    self.assertEqual(tables["Sample sizes"].loc[a, b], len(pair))
                    self.assertAlmostEqual(tables["Coefficients"].loc[a, b], test.statistic)
                    self.assertAlmostEqual(tables["P values"].loc[a, b], test.pvalue)
                    lower, upper = test.confidence_interval(.90)
                    self.assertAlmostEqual(tables["Confidence limits (lower)"].loc[a, b], lower)
                    self.assertAlmostEqual(tables["Confidence limits (upper)"].loc[a, b], upper)
                self.assertTrue(np.isnan(tables["P values"].loc["A", "A"]))
                self.assertFalse("P value type" in tables)
                np.testing.assert_allclose(result.figure.axes[0].images[0].get_array(), tables["R²"])

    def test_exact_spearman_matches_full_permutation_with_ties_and_tails(self):
        x, y = [2, 2, 3, 4, 4, 6], [9, 5, 9, 1, 2, 2]
        a = stats.rankdata(x)
        b = stats.rankdata(y)
        a, b = a - a.mean(), b - b.mean()
        observed = a @ b
        possible = np.asarray(list(permutations(b))) @ a
        for tail, expected in (("Two-sided", abs(possible) >= abs(observed)),
                               ("Positive", possible >= observed), ("Negative", possible <= observed)):
            with self.subTest(tail=tail):
                tables = self.matrix({"A": x, "B": y}, Method="Spearman", Alternative=tail).tables
                self.assertAlmostEqual(tables["Coefficients"].loc["A", "B"], stats.spearmanr(x, y).statistic)
                self.assertEqual(tables["P values"].loc["A", "B"], expected.mean())
                self.assertEqual(tables["P value type"].loc["A", "B"], "Exact")
                self.assertTrue(np.isnan(tables["Confidence limits (lower)"].loc["A", "B"]))

    def test_exact_cutoff_and_approximate_fallback(self):
        for n in (17, 18):
            y = list(range(n))[::-1]
            y[2], y[3] = y[3], y[2]
            data = {"X": list(range(n)), "Y": y}
            tables = self.matrix(data, Method="Spearman", **{"R² heat map": False}).tables
            label = tables["P value type"].iat[0, 1]
            if n == 17:
                self.assertEqual(label, "Exact")
                # Perfect permutations and the n - 1 possible adjacent swaps in each tail.
                self.assertAlmostEqual(tables["P values"].iat[0, 1] * factorial(n), 2 * n)
            else:
                self.assertEqual(label, "Approximate")
                np.testing.assert_allclose(tables["P values"].iat[0, 1], stats.spearmanr(data["X"], y).pvalue,
                                           rtol=1e-10)
            forced = self.matrix(data, Method="Spearman", **{"Spearman p values": "Approximate",
                                                            "R² heat map": False})
            self.assertIsNone(forced.figure)
            self.assertEqual(forced.tables["P value type"].iat[0, 1], "Approximate")
            low = forced.tables["Confidence limits (lower)"].iat[0, 1]
            high = forced.tables["Confidence limits (upper)"].iat[0, 1]
            self.assertLess(low, forced.tables["Coefficients"].iat[0, 1])
            self.assertLess(forced.tables["Coefficients"].iat[0, 1], high)

    def test_pearson_direction_and_unavailable_cells(self):
        data = {"a": [1, 2, 3, 4], "b": [3, 1, 2, 0], "constant": [4] * 4,
                "sparse": [1, 2, None, None]}
        out = self.matrix(data, Alternative="Positive")
        self.assertAlmostEqual(out.tables["P values"].iat[0, 1],
                               stats.pearsonr(data["a"], data["b"], alternative="greater").pvalue)
        self.assertTrue(np.isnan(out.tables["Coefficients"].loc["a", "constant"]))
        self.assertEqual(out.tables["Sample sizes"].loc["a", "constant"], 4)
        self.assertEqual(out.tables["Sample sizes"].loc["a", "sparse"], 2)
        self.assertTrue(np.ma.getmaskarray(out.figure.axes[0].images[0].get_array())[0, 2])

    def test_extreme_magnitudes_and_validation(self):
        result = self.matrix({"a": [1e308, 1.2e308, 1.3e308, 1.4e308],
                              "b": [-1e308, -1.2e308, -1.3e308, -1.4e308]})
        self.assertAlmostEqual(result.tables["Coefficients"].iat[0, 1], -1)
        for frame, options, field in (
            ({"a": [1, 2, 3]}, {}, "Variables"),
            ({"a": [1, 1, 1], "b": [0, 1, 2]}, {}, "Variables"),
            ({"a": [0, 1, 2], "b": [1, "error", 3]}, {}, "Variables"),
            ({"a": [1, 2, 3], "b": [0, 1, 2]}, {"Confidence level (%)": 100}, "Confidence level (%)"),
        ):
            with self.subTest(frame=frame, options=options):
                with self.assertRaises(FieldError) as error:
                    self.matrix(frame, **options)
                self.assertEqual(error.exception.field, field)


if __name__ == "__main__":
    unittest.main()
