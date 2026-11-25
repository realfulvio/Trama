"""Inverse and hyperbolic functions in custom equations (0.109.x)."""
import unittest

import numpy as np
import pandas as pd

from analisi.custom_equations import FUNCTIONS, RESERVED, compile_equation
from analisi.field_error import FieldError
from analisi.workbench import analyse

# NIST StRD Roszman1 (average difficulty): y = b1 - b2*x - arctan(b3/(x-b4))/pi
ROSZMAN1_X = [-4868.68, -4868.09, -4867.41, -3375.19, -3373.14, -3372.03, -2473.74, -2472.35, -2469.45, -1894.65,
              -1893.40, -1497.24, -1495.85, -1493.41, -1208.68, -1206.18, -1206.04, -997.92, -996.61, -996.31,
              -834.94, -834.66, -710.03, -530.16, -464.17]
ROSZMAN1_Y = [0.252429, 0.252141, 0.251809, 0.297989, 0.296257, 0.295319, 0.339603, 0.337731, 0.333820, 0.389510,
              0.386998, 0.438864, 0.434887, 0.427893, 0.471568, 0.461699, 0.461144, 0.513532, 0.506641, 0.505062,
              0.535648, 0.533726, 0.568064, 0.612886, 0.624169]
CERTIFIED = [2.0196866396E-01, -6.1953516256E-06, 1.2044556708E+03, -1.8134269537E+02]


class InverseFunctionsTest(unittest.TestCase):
    def test_functions_evaluate_like_numpy(self):
        x = np.array([-.5, 0., .25, .75])
        for name, reference in (("asin", np.arcsin), ("acos", np.arccos), ("atan", np.arctan),
                                ("sinh", np.sinh), ("cosh", np.cosh), ("tanh", np.tanh)):
            self.assertIn(name, FUNCTIONS)
            self.assertIn(name, RESERVED)
            compiled = compile_equation(f"A*{name}(X)", ["A"])
            np.testing.assert_allclose(compiled.evaluate(x, {"A": 2.0}), 2 * reference(x), rtol=0, atol=0)

    def test_function_names_cannot_be_coefficients(self):
        with self.assertRaises(FieldError):
            compile_equation("atan*X", ["atan"])

    def test_roszman1_matches_the_certified_values(self):
        frame = pd.DataFrame({"X": ROSZMAN1_X, "Y": ROSZMAN1_Y})
        for start in ([0.1, -0.00001, 1000, -100], [0.2, -0.000005, 1200, -150]):
            result = analyse("Fit custom equation", frame, {
                "X": "X", "Y": "Y", "Equation": "b1 - b2*X - atan(b3/(X - b4))/pi", "Weighting": "Unweighted",
                "Parameters": [{"name": f"b{i + 1}", "start": value, "lower": None, "upper": None, "fixed": False}
                               for i, value in enumerate(start)]})
            np.testing.assert_allclose(result.tables["Parameters: All"]["Estimate"].to_numpy(), CERTIFIED, rtol=1e-7)


if __name__ == "__main__":
    unittest.main()
