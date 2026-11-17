"""Unit changes must not turn a noisy linear model into a perfect fit."""
import unittest
import numpy as np
import pandas as pd
from analisi.stats import linear


class LinearScaleTests(unittest.TestCase):
    def test_extreme_units_preserve_inference(self):
        frame = pd.DataFrame({"X": np.arange(5.), "Y": [1., 3., 2., 5., 7.]})
        baseline = linear(frame, "X", "Y")
        for sx, sy in [(1e-150, 1e-100), (1., 1e-200), (1e150, 1e150), (1e-150, 1e150)]:
            with self.subTest(sx=sx, sy=sy):
                got = linear(frame.assign(X=frame.X*sx, Y=frame.Y*sy), "X", "Y")
                np.testing.assert_allclose([got["R²"], got["p"]], [baseline["R²"], baseline["p"]], rtol=1e-12)
                for key in ["Slope", "Slope SE", "Slope CI 95% low", "Slope CI 95% high"]:
                    np.testing.assert_allclose(got[key]/(sy/sx), baseline[key], rtol=1e-12, atol=0)
                np.testing.assert_allclose(got["Intercept"]/sy, baseline["Intercept"], rtol=1e-12, atol=0)

    def test_scaled_constant_response_and_true_range_error(self):
        constant = pd.DataFrame({"X": np.arange(5.)*1e150, "Y": [1e-200]*5})
        got = linear(constant, "X", "Y")
        self.assertEqual(got["Slope"], 0.)
        self.assertTrue(np.isnan(got["Slope SE"]))
        impossible = pd.DataFrame({"X": np.arange(5.)*1e-200, "Y": np.arange(5.)*1e200})
        with self.assertRaisesRegex(ValueError, "numeric range"):
            linear(impossible, "X", "Y")
