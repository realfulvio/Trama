import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi import design


class PowerTests(unittest.TestCase):
    def test_paired_effect_size_uses_number_of_complete_pairs(self):
        result = design.power("paired", .4, 20, alpha=.05)
        critical = stats.t.isf(.025, 19)
        noncentrality = .4 * np.sqrt(20)
        expected = stats.nct.sf(critical, 19, noncentrality) + stats.nct.cdf(-critical, 19, noncentrality)
        self.assertAlmostEqual(result["Power"], expected)
        self.assertEqual(result["N unit"], "Pairs")
        self.assertEqual(result["Total N"], 20)
        self.assertEqual(design.sample_size("one-sample", .5)["N"], 34)

    def test_independent_sample_size_is_per_arm_and_minimal(self):
        result = design.sample_size("independent", .5)
        self.assertEqual(result["N"], 64)
        self.assertEqual(result["Total N"], 128)
        self.assertGreaterEqual(result["Power"], .8)
        self.assertLess(design.power("independent", .5, 63)["Power"], .8)

    def test_anova_uses_total_n_and_balanced_integer_allocation(self):
        result = design.sample_size("anova", .25, groups=3)
        self.assertEqual(result["N"], 53)
        self.assertEqual(result["Total N"], 159)
        critical = stats.f.isf(.05, 2, 156)
        self.assertAlmostEqual(result["Power"], stats.ncf.sf(critical, 2, 156, 159 * .25**2))
        self.assertLess(design.power("anova", .25, 52, groups=3)["Power"], .8)

    def test_low_target_still_uses_a_valid_minimum_n(self):
        result = design.sample_size("paired", .2, alpha=.05, target=.01)
        self.assertEqual(result["N"], 2)
        self.assertGreaterEqual(result["Power"], result["Target power"])

    def test_invalid_inputs_and_unattainable_target_raise(self):
        with self.assertRaisesRegex(ValueError, "Alpha"):
            design.power("paired", .3, 10, alpha=0)
        with self.assertRaisesRegex(ValueError, "Target power"):
            design.sample_size("paired", .3, target=1)
        with self.assertRaisesRegex(ValueError, "Effect size"):
            design.power("paired", np.nan, 10)
        with self.assertRaisesRegex(ValueError, "integer"):
            design.power("independent", .3, 2.9)
        with self.assertRaisesRegex(ValueError, "Groups"):
            design.power("anova", .3, 10, groups=1)
        with self.assertRaisesRegex(ValueError, "sample size limit"):
            design.sample_size("one-sample", .000001)

    def test_anova_effect_outside_supported_numeric_range_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "numeric range"):
            design.power("anova", 1e300, 10)


class SimulationTests(unittest.TestCase):
    def test_seed_reproduces_a_normal_sample_with_requested_location_and_scale(self):
        first = design.simulate("normal", 8, seed=5, mean=3, sd=2)
        second = design.simulate("normal", 8, seed=5, mean=3, sd=2)
        pd.testing.assert_frame_equal(first, second)
        np.testing.assert_allclose(first["Value"], np.random.default_rng(5).normal(3, 2, 8))

    def test_xy_grid_and_linear_mean_when_noise_is_zero(self):
        result = design.simulate("xy", 4, seed=5, x_min=2, x_max=8, intercept=5, slope=-2, sd=0)
        np.testing.assert_array_equal(result["X"], [2, 4, 6, 8])
        np.testing.assert_array_equal(result["Y"], [1, -3, -7, -11])

    def test_contingency_preserves_odd_total_and_binomial_endpoints(self):
        result = design.simulate("contingency", 9, seed=3, p_a=1, p_b=0)
        self.assertEqual(result["Group"].tolist(), ["A", "B"])
        self.assertEqual(result["Success"].tolist(), [5, 0])
        self.assertEqual(result["Failure"].tolist(), [0, 4])

    def test_invalid_simulation_inputs_raise(self):
        with self.assertRaisesRegex(ValueError, "SD"):
            design.simulate("normal", 10, sd=-1)
        with self.assertRaisesRegex(ValueError, "X maximum"):
            design.simulate("xy", 10, x_min=1, x_max=1)
        with self.assertRaisesRegex(ValueError, "probability"):
            design.simulate("contingency", 10, p_a=1.1)
        with self.assertRaisesRegex(ValueError, "Seed"):
            design.simulate("normal", 10, seed=-1)
