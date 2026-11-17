"""Exact runs test and replicate lack of fit, independent of the optimizer."""
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi.field_error import FieldError
from analisi.fit_quality import REPLICATES, RUNS, check_options, fit_quality, replicate_test, runs_test


def _residuals(x, residual, predicted=None):
    x = np.asarray(x, dtype=float)
    residual = np.asarray(residual, dtype=float)
    predicted = np.full(len(x), 10.0) if predicted is None else np.asarray(predicted, dtype=float)
    return pd.DataFrame({"X": x, "Observed": predicted + residual, "Predicted": predicted, "Residual": residual})


def _line(x, slope=2.0, intercept=10.0):
    x = np.asarray(x, dtype=float)
    return intercept + slope * x


class RunsTests(unittest.TestCase):
    def test_curved_and_alternating_match_the_oracle(self):
        curved = [5, 3, 1, -3, -3, -3, -3, -3, -3, 1, 3, 5]
        result = runs_test(_residuals(range(12), curved, _line(range(12))))
        self.assertEqual(result["Status"], "Available")
        self.assertEqual(result["Positive"], 6)
        self.assertEqual(result["Negative"], 6)
        self.assertEqual(result["Observed runs"], 3)
        self.assertEqual(result["Expected runs"], 7)
        self.assertAlmostEqual(result["p"], 0.012987012987012988)
        self.assertEqual(result["Tail"], "Exact lower tail")
        # Residuals of runs_alternating.csv from the oracle line y = 10 + 2X.
        signs = [1, -1, 1, -1, -1, 1, -1, 1]
        alternating = runs_test(_residuals(range(8), signs, _line(range(8), 2, 10)))
        self.assertEqual((alternating["Positive"], alternating["Negative"], alternating["Observed runs"]), (4, 4, 7))
        self.assertAlmostEqual(alternating["p"], 0.9714285714285714)
        self.assertGreater(alternating["p"], 0.5)

    def test_sign_swap_and_maximum_alternation(self):
        residual = np.array([5, 3, 1, -3, -3, -3, -3, -3, -3, 1, 3, 5], dtype=float)
        forward = runs_test(_residuals(range(12), residual))
        swapped = runs_test(_residuals(range(12), -residual))
        self.assertEqual(swapped["Observed runs"], forward["Observed runs"])
        self.assertAlmostEqual(swapped["p"], forward["p"])
        self.assertEqual((swapped["Positive"], swapped["Negative"]), (forward["Negative"], forward["Positive"]))
        full = runs_test(_residuals(range(8), [1, -1, 1, -1, 1, -1, 1, -1]))
        self.assertEqual(full["p"], 1)

    def test_domain_budget_duplicates_and_order(self):
        for residual in ([1] * 8, [0] * 8, [1, 1, -1, -1], [1, 1, 1, 1, 1, -1]):
            result = runs_test(_residuals(range(len(residual)), residual))
            self.assertEqual(result["Status"], "Not available")
            self.assertTrue(result["Reason"])
            self.assertIsNone(result["p"])
        large = runs_test(_residuals(range(2001), [1, -1] * 1000 + [1]))
        self.assertEqual(large["Status"], "Not available")
        self.assertIn("2000", large["Reason"])
        exact = runs_test(_residuals(range(2000), [1] * 1000 + [-1] * 1000))
        self.assertEqual(exact["Status"], "Available")
        self.assertEqual(exact["Observed runs"], 2)
        self.assertEqual((exact["Positive"], exact["Negative"]), (1000, 1000))
        # 2/C(2000, 1000) is far below the float64 range, so the published p is 0.
        self.assertEqual(exact["p"], 0.0)
        representable = runs_test(_residuals(range(200), [1] * 100 + [-1] * 100))
        self.assertEqual(representable["Observed runs"], 2)
        self.assertGreater(representable["p"], 0)
        duplicated = _residuals([0, 0, 1, 2, 3, 4, 5, 6], [0, 1, -1, 1, -1, 1, -1, 1])
        self.assertEqual(runs_test(duplicated)["Status"], "Not available")
        self.assertIn("replicate", runs_test(duplicated)["Reason"].lower())
        unsorted = runs_test(_residuals([1, 0, 2, 3, 4, 5, 6, 7], [1, -1, 1, -1, 1, -1, 1, -1]))
        self.assertEqual(unsorted["Status"], "Not available")
        self.assertIn("Reorder", unsorted["Reason"])

    def test_zero_tolerance_follows_the_data_scale(self):
        eps = np.finfo(float).eps
        base = runs_test(_residuals(range(12), [5, 3, 1, -3, -3, -3, -3, -3, -3, 1, 3, 5]))
        scaled = runs_test(_residuals(range(12), np.array([5, 3, 1, -3, -3, -3, -3, -3, -3, 1, 3, 5]) * 1e-20,
                                      _line(range(12)) * 1e-20))
        self.assertAlmostEqual(scaled["p"], base["p"])
        predicted = np.full(14, 1e-20)
        residual = np.array([0, 5, 3, 1, -3, -3, -3, -3, -3, -3, 1, 3, 5, 0]) * 1e-20
        removed = runs_test(_residuals(range(14), residual, predicted))
        self.assertEqual(removed["Zero"], 2)
        self.assertAlmostEqual(removed["p"], base["p"])
        tau = 64 * eps * 1
        at_tau = runs_test(_residuals(range(8), [tau, tau, -1, -1, 1, 1, -1, -1], np.ones(8)))
        above = runs_test(_residuals(range(8), [tau * 4, tau * 4, -1, -1, 1, 1, -1, -1], np.ones(8)))
        self.assertEqual(at_tau["Zero"], 2)
        self.assertEqual(above["Zero"], 0)


class ReplicateTests(unittest.TestCase):
    def test_line_and_curve_match_the_oracle(self):
        def frame(values, slope, intercept):
            x = np.repeat(np.arange(5), 3).astype(float)
            predicted = intercept + slope * x
            observed = np.asarray(values, dtype=float)
            return _residuals(x, observed - predicted, predicted)
        line = replicate_test(frame([1, 2, 3, 3, 4, 5, 5, 6, 7, 7, 8, 9, 9, 10, 11], 2, 2), p_free=2)
        self.assertEqual(line["Status"], "Available")
        self.assertEqual((line["N"], line["Unique X"], line["Free parameters"]), (15, 5, 2))
        self.assertAlmostEqual(line["Residual SS"], 10)
        self.assertAlmostEqual(line["Pure error SS"], 10)
        self.assertEqual(line["Lack of fit SS"], 0)
        self.assertEqual((line["df pure error"], line["df lack of fit"]), (10, 3))
        self.assertEqual(line["F"], 0)
        self.assertEqual(line["p"], 1)
        curved = replicate_test(frame([1, 2, 3, 2, 3, 4, 5, 6, 7, 10, 11, 12, 17, 18, 19], 4, 0), p_free=2)
        self.assertAlmostEqual(curved["Residual SS"], 52)
        self.assertAlmostEqual(curved["Pure error SS"], 10)
        self.assertAlmostEqual(curved["Lack of fit SS"], 42)
        self.assertAlmostEqual(curved["F"], 14)
        self.assertAlmostEqual(curved["p"], 0.0006523706476901394)
        shuffled = frame([1, 2, 3, 2, 3, 4, 5, 6, 7, 10, 11, 12, 17, 18, 19], 4, 0).iloc[::-1]
        again = replicate_test(shuffled, p_free=2)
        self.assertAlmostEqual(again["F"], curved["F"])
        self.assertAlmostEqual(again["p"], curved["p"])

    def test_separates_nearby_x_and_unbalanced_replicates(self):
        neighbor = np.nextafter(1.0, 2.0)
        separated = replicate_test(_residuals([1, 1, neighbor], [0, 0, 0], [1, 1, 1]), p_free=1)
        self.assertEqual(separated["Unique X"], 2)
        self.assertEqual(separated["Status"], "Not available")
        third = np.nextafter(neighbor, 2.0)
        apart = replicate_test(_residuals([1, neighbor, third], [0, 0, 0], [1, 1, 1]), p_free=1)
        self.assertEqual(apart["Unique X"], 3)
        unbalanced = replicate_test(_residuals([0, 0, 0, 1, 1], [1, -1, 0, 2, -2], [5, 5, 5, 7, 7]), p_free=1)
        self.assertEqual(unbalanced["Status"], "Available")
        self.assertEqual(unbalanced["df pure error"], 3)
        self.assertAlmostEqual(unbalanced["Pure error SS"], 1 + 1 + 0 + 4 + 4)

    def test_pure_error_zero_clamp_and_tiny_scale(self):
        none = replicate_test(_residuals(range(8), [1, -1] * 4), p_free=2)
        self.assertEqual(none["Status"], "Not available")
        self.assertIn("repeated", none["Reason"])
        no_df = replicate_test(_residuals([0, 0, 1, 1], [1, -1, 1, -1]), p_free=2)
        self.assertEqual(no_df["Status"], "Not available")
        both = replicate_test(_residuals([0, 0, 1, 1], [0, 0, 0, 0], [1, 1, 2, 2]), p_free=1)
        positive = replicate_test(_residuals([0, 0, 1, 1], [0, 0, 1, 1], [1, 1, 2, 2]), p_free=1)
        self.assertIsNone(both["p"])
        self.assertIsNone(positive["p"])
        self.assertNotEqual(both["Reason"], positive["Reason"])
        self.assertIn("zero", both["Reason"].lower())
        pure = 10.0
        tau = 128 * np.finfo(float).eps * pure
        clamped = replicate_test(_residuals([0, 0, 1, 1, 2, 2], [1, -1, 1, -1, 1, -1],
                                            [0, 0, 1, 1, 2, 2]), p_free=1)
        # Construct lack of fit just below zero by shifting predictions off the means by a fraction of tau.
        y = np.array([1., -1, 1, -1, 1, -1])
        means = np.array([0., 0, 0])
        # Use observed centered at 0 so SSPE is 6, and predictions that make SSE slightly smaller.
        observed = np.array([1., -1, 1, -1])
        predicted = observed.copy()
        predicted[-1] += 1e-8
        manual = replicate_test(_residuals([0, 0, 1, 1], observed - predicted, predicted), p_free=1)
        self.assertIn(manual["Status"], ("Available", "Not available"))
        eps = np.finfo(float).eps
        # Keep the observations fixed so pure error stays 4, and shrink only the residual column.
        observed = np.array([1., -1, 1, -1], dtype=float)
        sspe = 4.0
        target = sspe - 0.5 * (128 * eps * sspe)
        factor = np.sqrt(target / float(observed @ observed))
        almost = replicate_test(pd.DataFrame({
            "X": [0, 0, 1, 1], "Observed": observed,
            "Predicted": np.zeros(4), "Residual": observed * factor,
        }), p_free=1)
        self.assertEqual(almost["Status"], "Available")
        self.assertEqual(almost["Lack of fit SS"], 0)
        self.assertEqual(almost["F"], 0)
        self.assertIn("zero", almost["Reason"].lower())
        broken = replicate_test(pd.DataFrame({
            "X": [0, 0, 1, 1], "Observed": observed,
            "Predicted": np.zeros(4), "Residual": observed * 0.1,
        }), p_free=1)
        self.assertEqual(broken["Status"], "Not available")
        self.assertIsNone(broken["p"])
        tiny = replicate_test(_residuals([0, 0, 1, 1], observed * 1e-18, np.zeros(4)), p_free=1)
        self.assertEqual(tiny["Status"], "Available")
        self.assertGreater(tiny["Pure error SS"], 0)
        self.assertIsNotNone(tiny["p"])
        self.assertIsNot(clamped, None)

    def test_free_parameters_come_from_the_fit_degrees_of_freedom(self):
        class Fit:
            pass
        fit = Fit()
        x = np.repeat(np.arange(5), 3)
        predicted = 2 + 2 * x.astype(float)
        observed = np.array([1, 2, 3, 3, 4, 5, 5, 6, 7, 7, 8, 9, 9, 10, 11], dtype=float)
        residual = observed - predicted
        fit.residuals = _residuals(x, residual, predicted)
        fit.parameters = pd.DataFrame({"Estimate": [2, 2, 0, 0]}, index=["a", "b", "fixed", "fixed"])
        fit.residual_ss = float(residual @ residual)
        fit.diagnostics = {"N": 15, "df": 13, "Weighting": "Unweighted"}
        fit.covariance = None
        original = fit.residuals.copy(deep=True)
        result = fit_quality(fit, runs=True, replicates=True)
        self.assertEqual(result[REPLICATES]["Free parameters"], 2)
        self.assertEqual(result[REPLICATES]["Status"], "Available")
        self.assertEqual(result[RUNS]["Status"], "Not available")
        pd.testing.assert_frame_equal(fit.residuals, original)
        self.assertIsNone(fit.covariance)

    def test_weighted_requests_name_the_first_active_test(self):
        with self.assertRaises(FieldError) as runs:
            check_options({"Weighting": "1/Y²", RUNS: True, REPLICATES: True})
        self.assertEqual(runs.exception.field, RUNS)
        with self.assertRaises(FieldError) as only:
            check_options({"Weighting": "1/Y²", REPLICATES: True})
        self.assertEqual(only.exception.field, REPLICATES)
        check_options({"Weighting": "1/Y²", "Residuals versus X": True})
        check_options({"Runs test": False})


if __name__ == "__main__":
    unittest.main()
