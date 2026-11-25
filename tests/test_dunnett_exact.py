"""Dunnett against one control by deterministic quadrature (0.109.x)."""
import unittest

import numpy as np
import pandas as pd
from scipy import optimize, stats

from analisi import dunnett_exact
from analisi.advanced import dunnett_scores

# Reference: nested adaptive quadrature (scipy.integrate.quad, epsrel 1e-13) of Dunnett's
# representation for control n=20 and groups n=25, 30, 22 with 93 residual df, cross-checked
# by an 80-million-sample Monte Carlo (agreement within its standard error).
SIZES, CONTROL, DF = np.array([25, 30, 22]), 20, 93
T_ABS = np.array([1.4241241953703199, 0.8774408932036653, 4.057580622771412])
P_REFERENCE = np.array([0.34031152340362303, 0.6963589558985616, 0.00029804664988419827])
C95_REFERENCE = 2.3753634561702484


def standardized_contrasts(sizes, control):
    count = len(sizes)
    coordinates = np.zeros((count, count + 1))
    coordinates[np.arange(count), 0] = 1 / np.sqrt(control)
    coordinates[np.arange(count), np.arange(1, count + 1)] = -1 / np.sqrt(sizes)
    return coordinates / np.linalg.norm(coordinates, axis=1)[:, None]


class DunnettExactTest(unittest.TestCase):
    def test_matches_the_reference_integral(self):
        loadings = np.sqrt(SIZES / (SIZES + CONTROL))
        p = [dunnett_exact.tail(x, loadings, DF) for x in T_ABS]
        np.testing.assert_allclose(p, P_REFERENCE, rtol=1e-10)
        critical = optimize.brentq(lambda x: dunnett_exact.tail(x, loadings, DF) - .05, 1.5, 4, xtol=1e-13)
        self.assertAlmostEqual(critical, C95_REFERENCE, delta=1e-10)

    def test_dunnett_scores_uses_the_exact_path(self):
        standardized = standardized_contrasts(SIZES, CONTROL)
        raw = 2 * stats.t.sf(T_ABS, DF)
        adjusted, critical = dunnett_scores(T_ABS, raw, standardized, DF, .05)
        np.testing.assert_allclose(adjusted, P_REFERENCE, rtol=1e-9)
        self.assertAlmostEqual(critical, C95_REFERENCE, delta=1e-9)

    def test_recognises_only_one_factor_correlations(self):
        loadings = np.array([.3, .5, .7, .6])
        correlation = np.outer(loadings, loadings)
        correlation[0, 1:] *= -1
        correlation[1:, 0] *= -1
        np.fill_diagonal(correlation, 1)
        np.testing.assert_allclose(dunnett_exact.one_factor_loadings(correlation), loadings, rtol=1e-12)
        correlation[1, 2] = correlation[2, 1] = .1
        self.assertIsNone(dunnett_exact.one_factor_loadings(correlation))

    def test_balanced_design_matches_published_critical_value(self):
        # Dunnett (1955) table: 3 treatments + control, 20 df, two-sided 95%: 2.54
        loadings = np.sqrt(np.full(3, .5))
        critical = optimize.brentq(lambda x: dunnett_exact.tail(x, loadings, 20) - .05, 1.5, 4, xtol=1e-12)
        self.assertAlmostEqual(critical, 2.54, delta=0.005)


if __name__ == "__main__":
    unittest.main()
