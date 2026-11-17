"""Independent invariance and representability checks added during integration."""
import io
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi.equivalence import tost_from_summary
from analisi.equivalence_workbench import ONE_SAMPLE, PAIRED, STUDENT, WELCH, _estimate, equivalence_test


class EquivalenceNumericsTests(unittest.TestCase):
    def test_one_sample_centers_reference_before_averaging(self):
        base = 1e15
        values = base + np.array([0., .25, .25])
        difference, se, df, reason = _estimate(ONE_SAMPLE, {"a": values, "b": np.array([])}, base)
        self.assertEqual(reason, "")
        self.assertAlmostEqual(difference, 1 / 6, places=15)
        self.assertAlmostEqual(se, 1 / 12, places=15)
        self.assertEqual(df, 2)

    def test_paired_variation_survives_common_offset(self):
        base = 1e15
        difference, se, df, reason = _estimate(PAIRED, {
            "a": base + np.array([1., 2., 3.]), "b": np.full(3, base)}, None)
        self.assertEqual(reason, "")
        np.testing.assert_allclose([difference, se, df], [2., 1 / np.sqrt(3), 2.], rtol=1e-14)

    def test_independent_results_are_invariant_to_common_offset(self):
        a, b = np.array([1., 2., 3., 4.]), np.array([0., 1., 2., 3.])
        for design in (STUDENT, WELCH):
            with self.subTest(design=design):
                actual = _estimate(design, {"a": a + 1e15, "b": b + 1e15}, None)
                self.assertEqual(actual[3], "")
                np.testing.assert_allclose(actual[:3], [1., np.sqrt(5 / 6), 6.], rtol=1e-14)

    def test_welch_variance_from_small_group_is_not_lost(self):
        actual = _estimate(WELCH, {"a": np.full(3, 1e300), "b": np.array([1., 2., 3.]) * 1e-300}, None)
        self.assertEqual(actual[3], "")
        np.testing.assert_allclose(actual[1], 1e-300 / np.sqrt(3), rtol=1e-14, atol=0)
        self.assertEqual(actual[2], 2)

    def test_tiny_alpha_uses_a_tail_quantile(self):
        actual = tost_from_summary(0., 1., 10., -1000., 1000., 1e-20)
        self.assertAlmostEqual(actual["ci_upper"] / stats.t.isf(1e-20, 10), 1., places=14)

    def test_representable_t_is_kept_after_overflowing_subtraction(self):
        actual = tost_from_summary(1e308, 1e307, 10., -1e308, 1.5e308, .1)
        np.testing.assert_allclose([actual["t_lower"], actual["t_upper"]], [20., -5.], rtol=1e-14)
        self.assertTrue(np.isfinite([actual["ci_lower"], actual["ci_upper"]]).all())

    def test_extreme_units_render_without_axis_overflow(self):
        for factor, margin in ((1e-250, 1e-249), (1e307, 1.5e308)):
            with self.subTest(factor=factor):
                result = equivalence_test(pd.DataFrame({"Y": np.array([1., 2., 3.]) * factor}), {
                    "Design": ONE_SAMPLE, "Response": "Y", "Reference": 0.,
                    "Lower margin": -margin, "Upper margin": margin, "Alpha": .05})
                output = io.BytesIO()
                result.figure.savefig(output, format="svg")
                self.assertGreater(len(output.getvalue()), 1000)
                self.assertTrue(np.isfinite(result.figure.axes[0].get_xlim()).all())
