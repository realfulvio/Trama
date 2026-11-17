import unittest

import numpy as np
import pandas as pd

from analisi import stats as engine


class CurveTests(unittest.TestCase):
    def test_curve_catalog_recovers_parameters_from_known_equations(self):
        dose = np.r_[0., np.geomspace(.05, 100., 35)]
        time = np.linspace(0., 12., 30)
        normal_x = np.linspace(-4., 6., 41)
        cases = [
            ("Stimulation (standard slope)", dose, 2 + 12 * dose / (3 + dose), [2, 14, 3]),
            ("Stimulation (variable slope)", dose, 2 + 12 * dose**1.6 / (3**1.6 + dose**1.6),
             [2, 14, 3, 1.6]),
            ("Inhibition (standard slope)", dose, 2 + 12 * 3 / (3 + dose), [2, 14, 3]),
            ("Inhibition (variable slope)", dose, 2 + 12 * 3**1.6 / (3**1.6 + dose**1.6),
             [2, 14, 3, -1.6]),
            ("Michaelis–Menten", dose * 1e-12, 12 * dose / (3 + dose), [12, 3e-12]),
            ("One-site specific binding", dose, 12 * dose / (3 + dose), [12, 3]),
            ("One-site total binding", dose, 1.1 + 12 * dose / (3 + dose) + .2 * dose,
             [12, 3, .2, 1.1]),
            ("One-phase association", time, 2 + 7 * (1 - np.exp(-.7 * time)), [2, 9, .7]),
            ("Exponential growth", time, 2 * np.exp(.3 * time), [2, .3]),
            ("Gaussian", normal_x, 6 * np.exp(-.5 * ((normal_x - 1) / .9)**2), [6, 1, .9]),
        ]
        for name, x, y, expected in cases:
            with self.subTest(model=name):
                self.assertIn(name, engine.MODELS)
                frame = pd.DataFrame({"x": x, "y": y})
                fit = engine.nonlinear(frame, "x", "y", name)["All"]
                np.testing.assert_allclose(fit.parameters["Estimate"], expected, rtol=1e-5, atol=0)
                self.assertLess(fit.residual_ss, 1e-12)
                self.assertEqual(fit.curve[0, 0], x.min())

    def test_weighted_fit_uses_supplied_scales_and_reports_residuals(self):
        x = np.linspace(0, 30, 20)
        expected = 10 * x / (x + 3)
        response = expected.copy()
        response[-1] += 20
        sigma = np.ones_like(x)
        sigma[-1] = 100
        frame = pd.DataFrame({"x": x, "y": response, "sd": sigma})
        self.assertIn("Inverse variance (column)", getattr(engine, "FIT_WEIGHTINGS", ()))
        fit = engine.nonlinear(frame, "x", "y", "Michaelis–Menten",
                               weighting="Inverse variance (column)", sigma="sd")["All"]
        np.testing.assert_allclose(fit.parameters["Estimate"], [10, 3], rtol=.001)
        self.assertEqual(fit.diagnostics["df"], 18)
        self.assertAlmostEqual(fit.diagnostics["Weighted residual SS"], .04, places=5)
        self.assertAlmostEqual(fit.residuals.iloc[-1]["Weighted residual"], .2, places=4)
        self.assertAlmostEqual(fit.residuals.iloc[-1]["Residual"], 20, places=2)
        self.assertGreater(fit.parameters.loc["Km", "CI 95% high"], 3)
        self.assertLess(fit.parameters.loc["Km", "CI 95% low"], 3)

    def test_invalid_concentrations_and_missing_or_nonpositive_scales_are_rejected(self):
        x = np.linspace(0, 30, 20)
        frame = pd.DataFrame({"x": x, "y": 10 * x / (x + 3), "sd": 1.})
        self.assertIn("Michaelis–Menten", engine.MODELS)
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            engine.nonlinear(frame.assign(x=x - 1), "x", "y", "Michaelis–Menten")
        for invalid in (0., -1., np.nan):
            with self.subTest(sd=invalid), self.assertRaisesRegex(ValueError, "positive"):
                data = frame.copy()
                data.loc[3, "sd"] = invalid
                engine.nonlinear(data, "x", "y", "Michaelis–Menten",
                                 weighting="Inverse variance (column)", sigma="sd")

    def test_parameter_estimates_and_intervals_are_invariant_to_common_sd_units(self):
        x = np.linspace(0, 30, 25)
        frame = pd.DataFrame({"x": x, "y": 10 * x / (x + 3) + np.sin(x) / 10, "sd": 1 + x})
        options = {"weighting": "Inverse variance (column)", "sigma": "sd"}
        baseline = engine.nonlinear(frame, "x", "y", "Michaelis–Menten", **options)["All"]
        converted = engine.nonlinear(frame.assign(sd=frame["sd"] * 1e30), "x", "y",
                                     "Michaelis–Menten", **options)["All"]
        np.testing.assert_allclose(baseline.parameters, converted.parameters, rtol=1e-6)

    def test_nullable_weighting_checks_only_rows_with_observations(self):
        frame = pd.DataFrame({"x": [0, 1, 2, 3, 4, 5], "y": [0, 3, np.nan, 6, 7, 7.5],
                              "sd": pd.array([1., 2., pd.NA, 4., 5., 6.], dtype="Float64")},
                             index=[1, 1, 2, 2, 3, 3])
        options = {"weighting": "Inverse variance (column)", "sigma": "sd"}
        fit = engine.nonlinear(frame, "x", "y", "Michaelis–Menten", **options)["All"]
        self.assertEqual(fit.residuals.index.tolist(), [1, 1, 2, 3, 3])
        np.testing.assert_allclose(fit.residuals["Weighted residual"], fit.residuals["Residual"] / [1, 2, 4, 5, 6])
        frame.loc[3, "sd"] = pd.NA
        with self.assertRaisesRegex(ValueError, "positive"):
            engine.nonlinear(frame, "x", "y", "Michaelis–Menten", **options)

    def test_nested_binding_f_test_compares_weighted_sums_of_squares(self):
        x = np.r_[0, np.geomspace(.1, 30., 35)]
        y = 2 + 12 * x / (x + 3) + .4 * x + .12 * np.sin(x)
        frame = pd.DataFrame({"x": x, "y": y, "sd": 1. + x / 5})
        options = {"weighting": "Inverse variance (column)", "sigma": "sd"}
        simple, full = "One-site specific binding", "One-site total binding"
        result = engine.compare_nonlinear(frame, "x", "y", simple, full, **options).loc["All"]
        self.assertEqual(result["df numerator"], 2)
        self.assertEqual(result["df denominator"], 32)
        for model, column in [(simple, "Simple SS"), (full, "Complex SS")]:
            fit = engine.nonlinear(frame, "x", "y", model, **options)["All"]
            self.assertAlmostEqual(result[column], fit.diagnostics["Weighted residual SS"], places=7)
        self.assertLess(result["p"], 1e-15)

    def test_nested_f_test_uses_group_specific_degrees_of_freedom(self):
        x = np.geomspace(.1, 100., 30)
        y = 2 + 12 * x**2 / (3**2 + x**2) + .08 * np.sin(x)
        frame = pd.concat([pd.DataFrame({"x": x, "y": y, "batch": "A"}),
                           pd.DataFrame({"x": x[:25], "y": y[:25], "batch": "B"})])
        compare = getattr(engine, "compare_nonlinear", None)
        self.assertTrue(callable(compare))
        result = compare(frame, "x", "y", "Stimulation (standard slope)",
                         "Stimulation (variable slope)", "batch")
        self.assertEqual(result["df numerator"].tolist(), [1, 1])
        self.assertEqual(result["df denominator"].tolist(), [26, 21])
        self.assertTrue((result["p"] < 1e-15).all())
        expected_f = (result["Simple SS"] - result["Complex SS"]) / (result["Complex SS"] / result["df denominator"])
        np.testing.assert_allclose(result["F"], expected_f)

    def test_f_test_rejects_non_nested_and_reversed_models(self):
        x = np.linspace(0, 30, 20)
        frame = pd.DataFrame({"x": x, "y": 10 * x / (x + 3)})
        compare = getattr(engine, "compare_nonlinear", None)
        self.assertTrue(callable(compare))
        with self.assertRaisesRegex(ValueError, "nested"):
            compare(frame, "x", "y", "Michaelis–Menten", "Gaussian")
        with self.assertRaisesRegex(ValueError, "nested"):
            compare(frame, "x", "y", "Inhibition (variable slope)", "Inhibition (standard slope)")


if __name__ == "__main__":
    unittest.main()
