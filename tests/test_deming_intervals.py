import unittest
import warnings
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import exploration
from analisi.deming import (JACKKNIFE_LIMIT, PAIR_COLUMNS, RESIDUAL_COLUMN, identity_limits,
                            jackknife_deming, leave_one_out_coefficients)
from analisi.exploration import deming


def _line(x_values, y_values):
    return pd.DataFrame({"x": x_values, "y": y_values})


def _fixture():
    return _line([0, 1, 2, 3, 4], [1, 3, 2, 5, 7])


class DemingIntervalTests(unittest.TestCase):
    def test_level_just_below_one_hundred_has_finite_limits(self):
        level = np.nextafter(100., 0.)
        report, _, _ = jackknife_deming(_fixture(), "x", "y", intervals="Jackknife (t)", level=level)
        for name in ("Slope", "Intercept"):
            low, high = report[f"{name} CI low"], report[f"{name} CI high"]
            self.assertTrue(np.isfinite([low, high]).all())
            self.assertLess(low, report[name])
            self.assertLess(report[name], high)

    def test_jackknife_matches_full_sample_fit_and_leave_one_out_deming(self):
        frame = _fixture()
        original = frame.copy()
        baseline, baseline_points = deming(frame, "x", "y", 1)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            with patch("analisi.deming.exploration.deming", wraps=exploration.deming) as spy:
                report, points, pairs = jackknife_deming(frame, "x", "y", 1, intervals="Jackknife (t)")
        self.assertEqual(spy.call_count, 1)
        pd.testing.assert_frame_equal(frame, original)
        np.testing.assert_allclose(report["Slope"], 1.5769804236540488, rtol=1e-15, atol=0)
        np.testing.assert_allclose(report["Intercept"], 0.44603915269190253, rtol=1e-15, atol=0)
        self.assertEqual(report["Slope"], baseline["Slope"])
        self.assertEqual(report["Intercept"], baseline["Intercept"])
        self.assertEqual(report["N"], 5)
        self.assertEqual(report["Y / X measurement error variance"], 1)
        self.assertEqual(report["Interval"], "Jackknife (t)")
        self.assertEqual(report["Confidence level (%)"], 95)
        self.assertEqual(report["df"], 4)
        self.assertNotIn("Interval status", report)
        np.testing.assert_allclose(report["Slope SE"], 0.32862363, atol=5e-9)
        np.testing.assert_allclose(report["Intercept SE"], 1.04511970, atol=5e-9)
        np.testing.assert_allclose(report["Slope CI high"] - report["Slope"], 0.91240547, atol=5e-9)
        np.testing.assert_allclose(report["Intercept CI high"] - report["Intercept"], 2.90171748, atol=5e-9)
        for name in ("Slope", "Intercept"):
            half = report[f"{name} CI high"] - report[name]
            np.testing.assert_allclose(report[name] - report[f"{name} CI low"], half, atol=1e-12)
        slopes, intercepts = leave_one_out_coefficients(points["x"], points["y"], 1)
        np.testing.assert_allclose(slopes, [1.84268604, 1.65927619, 1.41900491, 1.60330391, 1.39742175], atol=5e-9)
        self.assertGreater(abs(slopes.mean() - report["Slope"]), 1e-3)
        direct_slopes, direct_intercepts = [], []
        for index in points.index:
            omitted, _ = deming(points.drop(index), "x", "y", 1)
            direct_slopes.append(omitted["Slope"])
            direct_intercepts.append(omitted["Intercept"])
        np.testing.assert_allclose(slopes, direct_slopes, rtol=1e-12, atol=0)
        np.testing.assert_allclose(intercepts, direct_intercepts, rtol=1e-12, atol=0)
        pd.testing.assert_frame_equal(points, baseline_points)
        self.assertEqual(tuple(pairs.columns), PAIR_COLUMNS)
        self.assertEqual(RESIDUAL_COLUMN, "Vertical residual (Y \u2212 fitted)")
        self.assertEqual(list(pairs.index), list(range(5)))
        np.testing.assert_allclose(pairs["Source row"], points.index.to_numpy())
        np.testing.assert_allclose(pairs["Fitted Y"], report["Intercept"] + report["Slope"] * pairs["X"])
        np.testing.assert_allclose(pairs[RESIDUAL_COLUMN], pairs["Y"] - pairs["Fitted Y"])
        pairs.loc[0, "X"] = 12345
        points.iloc[0, 0] = -999
        pd.testing.assert_frame_equal(frame, original)

    def test_intervals_off_returns_the_deming_dictionary_and_still_lists_pairs(self):
        frame = _fixture()
        baseline, baseline_points = deming(frame, "x", "y", 1)
        report, points, pairs = jackknife_deming(frame, "x", "y", 1, intervals="None", level=120)
        self.assertEqual(report, baseline)
        self.assertEqual(list(report), ["N", "Slope", "Intercept", "Y / X measurement error variance"])
        pd.testing.assert_frame_equal(points, baseline_points)
        self.assertEqual(len(pairs), 5)

    def test_exact_line_has_zero_jackknife_width(self):
        frame = _line([0, 1, 2, 3, 4], [3, 5, 7, 9, 11])
        report, _, _ = jackknife_deming(frame, "x", "y", 1, intervals="Jackknife (t)")
        np.testing.assert_allclose(report["Slope"], 2, atol=1e-12)
        np.testing.assert_allclose(report["Intercept"], 3, atol=1e-12)
        self.assertLess(abs(report["Slope SE"]), 1e-10)
        self.assertLess(abs(report["Intercept SE"]), 1e-10)
        np.testing.assert_allclose([report["Slope CI low"], report["Slope CI high"]], [2, 2], atol=1e-10)
        np.testing.assert_allclose([report["Intercept CI low"], report["Intercept CI high"]], [3, 3], atol=1e-10)

    def test_invalid_ratio_zero_covariance_and_bad_requests_raise(self):
        frame = _fixture()
        for ratio in (0, -1, np.nan, np.inf):
            with self.subTest(ratio=ratio):
                with self.assertRaises(ValueError):
                    jackknife_deming(frame, "x", "y", ratio, intervals="Jackknife (t)")
        orthogonal = _line([1, 2, 3, 4], [1, 2, 2, 1])
        with self.assertRaisesRegex(ValueError, "covariance"):
            jackknife_deming(orthogonal, "x", "y", 1, intervals="Jackknife (t)")
        with self.assertRaisesRegex(ValueError, "three pairs"):
            jackknife_deming(_line([0, 1], [1, 3]), "x", "y", 1, intervals="Jackknife (t)")
        with self.assertRaisesRegex(ValueError, "Parameter intervals"):
            jackknife_deming(frame, "x", "y", 1, intervals="Bootstrap")
        for level in (0, 100, np.nan, 120, -5):
            with self.subTest(level=level):
                with self.assertRaisesRegex(ValueError, "Confidence level"):
                    jackknife_deming(frame, "x", "y", 1, intervals="Jackknife (t)", level=level)

    def test_three_pairs_and_a_degenerate_omit_keep_the_fit_without_a_ci(self):
        short = _line([0, 1, 2], [1, 2, 4])
        report, points, pairs = jackknife_deming(short, "x", "y", 1, intervals="Jackknife (t)")
        self.assertEqual(report["N"], 3)
        self.assertEqual(report["Interval"], "Jackknife (t)")
        self.assertIn("unavailable", report["Interval status"])
        self.assertNotIn("Slope SE", report)
        self.assertNotIn("Slope CI low", report)
        self.assertEqual((len(points), len(pairs)), (3, 3))
        flat = _line([0, 0, 0, 1], [0, 1, 2, 3])
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            base, _ = deming(flat, "x", "y", 1)
            report, _, _ = jackknife_deming(flat, "x", "y", 1, intervals="Jackknife (t)")
        self.assertIsNone(leave_one_out_coefficients(flat["x"], flat["y"], 1))
        with self.assertRaises(ValueError):
            deming(flat.iloc[:3], "x", "y", 1)
        self.assertEqual(report["Slope"], base["Slope"])
        self.assertEqual(report["Intercept"], base["Intercept"])
        self.assertIn("degenerate", report["Interval status"])
        self.assertNotIn("Intercept CI high", report)
        self.assertNotIn("df", report)

    def test_missing_row_keeps_source_order_and_a_near_vertical_line_stays_finite(self):
        frame = pd.DataFrame({"x": [0, 1, np.nan, 2, 3, 4], "y": [1, 3, 9, 2, 5, 7]},
                             index=[10, 11, 12, 13, 14, 15])
        report, points, pairs = jackknife_deming(frame, "x", "y", 1, intervals="Jackknife (t)")
        np.testing.assert_allclose(report["Slope"], 1.5769804236540488, rtol=1e-15, atol=0)
        self.assertEqual(pairs["Source row"].tolist(), [10, 11, 13, 14, 15])
        self.assertEqual(points.index.tolist(), [10, 11, 13, 14, 15])
        steep = _line([0, 0.001, 0.002, 0.003, 0.004], [0, 5, 9, 14, 20])
        report, _, _ = jackknife_deming(steep, "x", "y", 1, intervals="Jackknife (t)", level=90)
        self.assertTrue(np.isfinite(report["Slope"]) and abs(report["Slope"]) > 1000)
        self.assertTrue(np.isfinite(report["Slope SE"]) and np.isfinite(report["Intercept SE"]))
        self.assertEqual(report["df"], 4)
        self.assertEqual(report["Confidence level (%)"], 90)

    def test_swapping_axes_with_the_reciprocal_ratio_inverts_an_identifiable_slope(self):
        noisy = _fixture()
        forward, _, _ = jackknife_deming(noisy, "x", "y", 1)
        backward, _, _ = jackknife_deming(noisy, "y", "x", 1)
        np.testing.assert_allclose(backward["Slope"], 1 / forward["Slope"], rtol=1e-12, atol=0)
        affine = _line([1, 2, 3, 4, 5], [7, 5, 3, 1, -1])
        forward, _, _ = jackknife_deming(affine, "x", "y", 2)
        backward, _, _ = jackknife_deming(affine, "y", "x", 0.5)
        np.testing.assert_allclose(forward["Slope"], -2, rtol=1e-12, atol=0)
        np.testing.assert_allclose(backward["Slope"], 1 / forward["Slope"], rtol=1e-12, atol=0)
        np.testing.assert_allclose(backward["Slope"], -0.5, rtol=1e-12, atol=0)

    def test_work_limit_skips_the_interval_and_identity_domain_is_the_union(self):
        frame = _fixture()
        self.assertEqual(JACKKNIFE_LIMIT, 100_000)
        with patch("analisi.deming.JACKKNIFE_LIMIT", 4):
            blocked, _, pairs = jackknife_deming(frame, "x", "y", 1, intervals="Jackknife (t)")
        self.assertIn("jackknife work limit was exceeded", blocked["Interval status"])
        self.assertEqual(blocked["Interval"], "Jackknife (t)")
        self.assertNotIn("Slope SE", blocked)
        self.assertEqual(len(pairs), 5)
        np.testing.assert_allclose(blocked["Slope"], 1.5769804236540488, rtol=1e-15, atol=0)
        with patch("analisi.deming.JACKKNIFE_LIMIT", 5):
            allowed, _, _ = jackknife_deming(frame, "x", "y", 1, intervals="Jackknife (t)")
        self.assertIn("Slope SE", allowed)
        self.assertEqual(identity_limits([0, 4], [1, 7]), (0, 7))
        self.assertEqual(identity_limits(np.array([2, -3]), np.array([0.5, 0.5])), (-3, 2))

    def test_analysis_keeps_old_deming_options_and_draws_identity_on_the_shared_domain(self):
        from matplotlib.colors import to_hex

        from analisi.workbench import analyse

        frame = _fixture()
        old = analyse("Deming regression", frame, {"X": "x", "Y": "y", "Y / X error variance": 1.})
        self.assertEqual(list(old.tables), ["Deming regression", "Data", "Pairs"])
        self.assertEqual(list(old.tables["Deming regression"].index),
                         ["N", "Slope", "Intercept", "Y / X measurement error variance"])
        axis = old.figure.axes[0]
        self.assertIsNone(axis.get_legend())
        self.assertTrue(all(line.get_label().startswith("_") for line in axis.lines))
        np.testing.assert_allclose(axis.lines[0].get_xdata(), [0, 4])
        intervals = analyse("Deming regression", frame, {
            "X": "x", "Y": "y", "Y / X error variance": 1., "Parameter intervals": "Jackknife (t)",
            "Confidence level (%)": 95., "Identity line": False})
        self.assertIn("Slope SE", intervals.tables["Deming regression"].index)
        self.assertIsNone(intervals.figure.axes[0].get_legend())
        np.testing.assert_allclose(intervals.figure.axes[0].lines[0].get_xdata(), [0, 4])
        shown = analyse("Deming regression", frame, {
            "X": "x", "Y": "y", "Y / X error variance": 1., "Parameter intervals": "None",
            "Identity line": True})
        self.assertNotIn("Slope SE", shown.tables["Deming regression"].index)
        axis = shown.figure.axes[0]
        identity = next(line for line in axis.lines if line.get_label() == "Identity")
        fit = next(line for line in axis.lines if line.get_label() == "Deming fit")
        self.assertEqual(identity.get_linestyle(), "--")
        self.assertEqual(to_hex(identity.get_color()), "#81919b")
        np.testing.assert_allclose(identity.get_xydata(), [[0, 0], [7, 7]])
        np.testing.assert_allclose(fit.get_xdata(), [0, 7])
        np.testing.assert_allclose(axis.get_xlim(), (0, 7))
        np.testing.assert_allclose(axis.get_ylim(), (0, 7))
        self.assertIsNotNone(axis.get_legend())
        area = analyse("Area under curve", frame, {"X": "x", "Y": "y", "Baseline": 0.})
        self.assertEqual(list(area.tables), ["Area under curve", "Data"])
