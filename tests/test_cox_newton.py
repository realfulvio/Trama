"""The vectorised Cox fit reproduces statsmodels PHReg (0.109.x)."""
import time
import unittest

import numpy as np
from statsmodels.duration.hazard_regression import PHReg

from analisi import cox_newton


def simulated(n, p, seed, decimals=1):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, p))
    t = np.round(rng.exponential(np.exp(-x @ np.linspace(.5, -.5, p))), decimals) + 10.0 ** -decimals
    return t, x, (rng.random(n) < .7).astype(int)


class CoxNewtonTest(unittest.TestCase):
    def test_matches_phreg_with_ties(self):
        for n, p, seed in ((60, 1, 1), (300, 3, 2), (2000, 5, 3)):
            t, x, e = simulated(n, p, seed)
            for ties in ("efron", "breslow"):
                reference = PHReg(t, x, status=e, ties=ties).fit()
                fit = cox_newton.fit(t, x, e, ties)
                np.testing.assert_allclose(fit.params, reference.params, rtol=1e-9, atol=1e-12)
                np.testing.assert_allclose(fit.bse, reference.bse, rtol=1e-9)
                np.testing.assert_allclose(fit.cov_params(), reference.cov_params(), rtol=1e-8, atol=1e-14)
                np.testing.assert_allclose(fit.pvalues, reference.pvalues, rtol=1e-7, atol=1e-300)
                np.testing.assert_allclose(fit.conf_int(), reference.conf_int(), rtol=1e-9, atol=1e-12)
                self.assertAlmostEqual(fit.llf, reference.llf, delta=1e-9 * abs(reference.llf))

    def test_row_order_does_not_matter(self):
        t, x, e = simulated(500, 2, 4)
        order = np.random.default_rng(5).permutation(len(t))
        a, b = cox_newton.fit(t, x, e), cox_newton.fit(t[order], x[order], e[order])
        np.testing.assert_allclose(a.params, b.params, rtol=1e-12)

    def test_large_sample_is_fast(self):
        t, x, e = simulated(100_000, 2, 6, decimals=2)
        started = time.perf_counter()
        cox_newton.fit(t, x, e)
        self.assertLess(time.perf_counter() - started, 2)

    def test_collinear_design_is_reported(self):
        t, x, e = simulated(200, 1, 7)
        with self.assertRaises((np.linalg.LinAlgError, cox_newton.CoxConvergenceError)):
            cox_newton.fit(t, np.column_stack([x, 2 * x]), e)


if __name__ == "__main__":
    unittest.main()
