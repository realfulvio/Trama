"""Independent regressions found in joint correlation/layout review."""
import unittest

import numpy as np
import pandas as pd

from analisi.correlation_details import correlation_statistics
from analisi.workbench import analyse


class JointCorrelationReviewTests(unittest.TestCase):
    def test_pearson_keeps_finite_inference_near_float_limit(self):
        x = np.array([1., 1.1, 1.2, 1.3, 1.4, 1.5])
        y = np.array([2., 1., 4., 3., 6., 5.])
        expected = correlation_statistics(x, y)
        for scaled_x, scaled_y in ((x * 1e308, y), (x, y * 1e307),
                                   (x * 1e308, y * 1e307)):
            with self.subTest(xmax=scaled_x.max(), ymax=scaled_y.max()):
                actual = correlation_statistics(scaled_x, scaled_y)
                for key in ("Coefficient", "p", "Lower", "Upper", "R²"):
                    self.assertTrue(np.isfinite(actual[key]), (key, actual))
                    self.assertAlmostEqual(actual[key], expected[key], places=12)

    def test_large_integer_group_identifiers_remain_distinct(self):
        low, high = 2**53, 2**53 + 1
        frame = pd.DataFrame({"X": [1., 2, 3, 4, 1, 2, 3, 4],
                              "Y": [1., 3, 2, 5, 2, 4, 1, 3],
                              "Group": [low] * 4 + [high] * 4})
        result = analyse("Compare independent correlations", frame,
                         {"X": "X", "Y": "Y", "Group": "Group"})
        self.assertEqual(result.tables["Groups"]["Group"].tolist(), [low, high])
        self.assertEqual(result.tables["Groups"]["N"].tolist(), [4, 4])
        self.assertTrue(np.isfinite(result.tables["Comparison"].loc["p", "Value"]))

    def test_control_keeps_extreme_finite_responses_available(self):
        x = np.array([1., 1.1, 1.2, 1.3, 1.4, 1.5])
        frame = pd.DataFrame({"X": x * 1e308, "Y": [2., 1, 4, 3, 6, 5],
                              "Z": [5., 4, 6, 2, 3, 1]})
        options = {"X": "X", "Variables": ["Y", "Z"], "P adjustment": "Holm"}
        result = analyse("Correlate against control", frame, options)
        rows = result.tables["Correlations"]
        self.assertTrue(np.isfinite(rows[["Coefficient", "p", "p adjusted"]].to_numpy(dtype=float)).all())
        self.assertEqual(rows["Status"].tolist(), ["Available", "Available"])
