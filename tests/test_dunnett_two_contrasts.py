"""Two control contrasts share a bivariate t distribution with common residual df."""
import unittest

import numpy as np
from scipy import integrate, stats

from analisi.advanced import dunnett_scores


def conditional_tail(threshold, rho, df):
    # Partition by the component with the largest absolute value. Symmetry gives
    # four identical regions: integrate P(-x <= T2 <= x | T1=x) over T1>x0.
    def density(x):
        scale = np.sqrt((df + x*x) * (1 - rho*rho) / (df + 1))
        inside = stats.t.cdf(x * (1 - rho) / scale, df + 1) - stats.t.cdf(-x * (1 + rho) / scale, df + 1)
        return 4 * stats.t.pdf(x, df) * inside

    return integrate.quad(density, threshold, np.inf, epsabs=0, epsrel=2e-11)[0]


class TwoContrastDunnettTests(unittest.TestCase):
    def test_probabilities_and_simultaneous_limit_against_conditional_quadrature(self):
        for df, rho, thresholds in [(36, .5, [7.952347908831159, 14.3]),
                                    (2, 0., [.4, 10.]), (120, -.88, [1.2, 8.])]:
            with self.subTest(df=df, rho=rho):
                t = np.array(thresholds)
                directions = np.array([[1., 0.], [rho, np.sqrt(1 - rho*rho)]])
                raw = 2 * stats.t.sf(t, df)
                adjusted, critical = dunnett_scores(t, raw, directions, df, .05)
                expected = [conditional_tail(x, rho, df) for x in t]
                np.testing.assert_allclose(adjusted, expected, rtol=2e-10, atol=0)
                self.assertAlmostEqual(conditional_tail(critical, rho, df), .05, places=10)

    def test_opposite_contrasts_have_one_effective_test(self):
        t = np.array([8., -8.])
        df = 17
        raw = 2 * stats.t.sf(np.abs(t), df)
        adjusted, critical = dunnett_scores(t, raw, np.array([[1., 0.], [-1., 0.]]), df, .01)
        np.testing.assert_allclose(adjusted, raw, rtol=1e-12, atol=0)
        self.assertAlmostEqual(critical, stats.t.isf(.005, df), places=11)
