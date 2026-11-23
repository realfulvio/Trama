"""Fixed coefficients stay fixed in native least-squares calculations."""
import unittest

import numpy as np
import pandas as pd

from analisi.stats import nonlinear


class FixedNonlinearTests(unittest.TestCase):
    def test_fixed_terms_have_no_uncertainty_and_only_free_terms_consume_df(self):
        x = np.arange(1., 8.)
        data = pd.DataFrame({"X": x, "Y": 10 + 90 * np.exp(-.8 * x)})
        fit = nonlinear(data, "X", "Y", "One-phase decay", fixed={"Plateau": 10, "Span": 90})["All"]
        self.assertAlmostEqual(fit.parameters.at["Rate", "Estimate"], .8, places=7)
        self.assertEqual(fit.parameters.at["Span", "Estimate"], 90)
        self.assertTrue(np.isnan(fit.parameters.at["Span", "SE"]))
        self.assertEqual(fit.parameters.at["Plateau", "Status"], "Fixed")
        self.assertEqual(fit.diagnostics["df"], len(x) - 1)
        np.testing.assert_equal(fit.covariance[:2], np.zeros((2, 3)))

    def test_fixed_values_validate_names_and_domain(self):
        data = pd.DataFrame({"X": [1., 2., 3., 4.], "Y": [1., 2., 3., 4.]})
        for fixed in ({"Typo": 3.}, {"Rate": -1.}, {"Span": np.nan}, {"Plateau": 10, "Span": 90, "Rate": 1.}):
            with self.subTest(fixed=fixed), self.assertRaises(ValueError):
                nonlinear(data, "X", "Y", "One-phase decay", fixed=fixed)
