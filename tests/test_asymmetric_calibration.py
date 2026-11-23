"""5PL calibration with an independent midpoint-based response equation."""
import unittest

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import t

from analisi import nonlinear_calibration as cal, nonlinear_inverse as inv
from analisi.field_error import FieldError
from analisi.stats import nonlinear
from analisi.workbench import analyse


def response(dose, bottom, top, mid, hill, shape):
    weight = (2. ** (1. / shape) - 1.) * (mid / dose) ** hill
    return bottom + (top - bottom) / (1. + weight) ** shape


class AsymmetricCalibrationTests(unittest.TestCase):
    def frame(self, model, hill, *, noise=False):
        dose = np.geomspace(.04, 250., 27)
        query = np.array([.22, 3.2, 15.])
        values = response(dose, 2., 105., 3.2, hill, .43)
        if model == cal.CONCENTRATION_5PL:
            dose[0] = 0.
            values[0] = 2. if hill > 0 else 105.
        if noise:
            values += .16 * np.sin(np.arange(dose.size))
        x = np.log10(dose) if model == cal.LOG10_5PL else dose
        x_query = np.log10(query) if model == cal.LOG10_5PL else query
        unknown = response(query, 2., 105., 3.2, hill, .43)
        frame = pd.DataFrame({"Dose": x, "Signal": values, "Query X": np.nan, "Query Y": np.nan, "Replicates": 1})
        frame.loc[:3, "Query X"] = [*x_query, 1000.]
        frame.loc[:3, "Query Y"] = [*unknown, 200.]
        frame.loc[2, "Replicates"] = 4
        return frame, x_query, unknown

    def test_fit_and_inverse_keep_concentration_and_log10_units(self):
        for model in (cal.CONCENTRATION_5PL, cal.LOG10_5PL):
            for hill in (-1.25, 1.25):
                with self.subTest(model=model, hill=hill):
                    frame, x_query, y_query = self.frame(model, hill)
                    result = analyse("Interpolate a standard curve", frame, {
                        "X": "Dose", "Y": "Signal", "Unknown responses": "Query Y", "Curve": "Nonlinear", "Model": model,
                    })
                    table = result.tables[cal.INTERPOLATED]
                    self.assertEqual(list(table["Status"]), [cal.IN_RANGE] * 3 + [cal.OUT_OF_RANGE])
                    self.assertIsNotNone(result.figure)
                    np.testing.assert_allclose(table["Interpolated X"].iloc[:3], x_query, rtol=2e-6, atol=1e-8)
                    self.assertTrue(np.isnan(table["Interpolated X"].iloc[3]))
                    if model == cal.LOG10_5PL:
                        np.testing.assert_allclose(table[cal.POWER_COLUMN].iloc[:3], 10. ** x_query, rtol=2e-6)
                    else:
                        self.assertNotIn(cal.POWER_COLUMN, table)
                    forward = cal.predict_standard_curve(frame, "Dose", "Signal", "Query X", "Nonlinear", model)
                    predictions = forward.tables[cal.PREDICTIONS]
                    np.testing.assert_allclose(predictions["Predicted Y"].iloc[:3], y_query, rtol=2e-6)
                    self.assertEqual(predictions["Status"].iloc[3], cal.OUTSIDE_CALIBRATION)

    def test_closed_form_interpolation_resolves_subpicomolar_x(self):
        theta = (1., 8., 2e-18, 1.1, .61)
        interval = 0., 8e-17
        equation = cal.MODELS[cal.CONCENTRATION_5PL].equation
        left, right = equation(np.array(interval), *theta)
        x, status = cal._solve(cal.CONCENTRATION_5PL, theta, *interval, left, right, response(6e-18, *theta))
        self.assertEqual(status, cal.IN_RANGE)
        self.assertAlmostEqual(x / 6e-18, 1., places=12)

    def test_forward_prediction_uses_all_five_derivatives_and_query_counts(self):
        for model in (cal.CONCENTRATION_5PL, cal.LOG10_5PL):
            for hill in (-1.25, 1.25):
                with self.subTest(model=model, hill=hill):
                    frame, x_query, _ = self.frame(model, hill, noise=True)
                    fit = nonlinear(frame, "Dose", "Signal", model)["All"]
                    theta = fit.parameters["Estimate"].to_numpy()
                    prediction = cal.predict_standard_curve(
                        frame, "Dose", "Signal", "Query X", "Nonlinear", model, "Prediction", 95., "Replicates")
                    output = prediction.tables[cal.PREDICTIONS]
                    self.assertEqual(list(output[cal.REPLICATES]), [1, 1, 4, 1])
                    self.assertTrue(np.isfinite(prediction.tables[cal.BANDS].to_numpy()).all())

                    def expected(parameters):
                        if model == cal.LOG10_5PL:
                            bottom, top, mid, slope, shape = parameters
                            return response(10. ** x_query, bottom, top, 10. ** mid, slope, shape)
                        return response(x_query, *parameters)

                    gradient = []
                    for column in range(5):
                        step = np.zeros(5)
                        step[column] = 1e-5 * max(abs(theta[column]), 1.)
                        gradient.append((expected(theta + step) - expected(theta - step)) / (2. * step[column]))
                    gradient = np.transpose(gradient)
                    variance = np.einsum("ni,ij,nj->n", gradient, fit.covariance, gradient)
                    df = fit.diagnostics["df"]
                    half = t.ppf(.975, df) * np.sqrt(variance + fit.residual_ss / df / np.array([1., 1., 4.]))
                    predicted = expected(theta)
                    np.testing.assert_allclose(output["Y lower"].iloc[:3], predicted - half, rtol=1e-7)
                    np.testing.assert_allclose(output["Y upper"].iloc[:3], predicted + half, rtol=1e-7)

    def test_inverse_prediction_contains_the_estimate_and_uses_replicate_counts(self):
        for model in (cal.CONCENTRATION_5PL, cal.LOG10_5PL):
            with self.subTest(model=model):
                self.assertIn(model, cal.INVERSE_INTERVAL_MODELS)
                frame, _, _ = self.frame(model, -1.25, noise=True)
                options = ("Dose", "Signal", "Query Y", "Nonlinear", model, "Prediction", 95.)
                default = cal.interpolate_standard_curve(frame, *options).tables[cal.INTERPOLATED]
                counted = cal.interpolate_standard_curve(frame, *options, "Replicates").tables[cal.INTERPOLATED]
                self.assertEqual(list(counted[cal.REPLICATES]), [1, 1, 4, 1])
                self.assertTrue((counted["X lower"].iloc[:3] < counted["Interpolated X"].iloc[:3]).all())
                self.assertTrue((counted["X upper"].iloc[:3] > counted["Interpolated X"].iloc[:3]).all())
                self.assertGreater(counted.at[2, "X lower"], default.at[2, "X lower"])
                self.assertLess(counted.at[2, "X upper"], default.at[2, "X upper"])
                self.assertTrue(counted.loc[3, ["X lower", "X upper"]].isna().all())

    def test_inverse_finds_both_components_of_the_5pl_band(self):
        self.assertIn(cal.LOG10_5PL, inv.MODELS)
        theta = (2., 105., np.log10(3.2), 1.25, .43)
        covariance = np.diag([0., 0., 0., .7 ** 2, 0.])
        target = 53.
        quantile = t.ppf(.975, 22)

        def cross(x):
            bottom, top, mid, hill, shape = theta
            dose, ec50 = 10. ** x, 10. ** mid
            estimate = response(dose, bottom, top, ec50, hill, shape)
            derivative = response(dose, bottom, top, ec50, hill + 1e-20j, shape).imag / 1e-20
            return (estimate - target) ** 2 - (quantile * .7 * derivative) ** 2

        brackets = ((0., .2), (.48, .53), (.54, .62), (1., 1.15))
        expected = np.array([brentq(cross, *pair) for pair in brackets]).reshape(2, 2)
        actual = inv.inverse_band_components(cal.LOG10_5PL, theta, covariance, 0., 22, target, -2., 2.6)
        np.testing.assert_allclose(actual, expected, rtol=2e-9, atol=2e-11)
        self.assertGreater(actual[1][0], actual[0][1])
        dose_theta = (*theta[:2], 3.2e-18, *theta[3:])
        scaled = inv.inverse_band_components(cal.CONCENTRATION_5PL, dose_theta, covariance, 0., 22, target, 0., 4e-16)
        np.testing.assert_allclose(np.asarray(scaled) / 1e-18, 10. ** expected, rtol=2e-9, atol=2e-11)
        with self.assertRaises(inv.InverseBudgetError):
            account = inv.SearchAccount(query_limit=8)
            inv.inverse_band_components(cal.LOG10_5PL, theta, covariance, 0., 22, target, -2., 2.6, account=account)

    def test_wrong_concentration_names_the_model_field(self):
        frame, _, _ = self.frame(cal.CONCENTRATION_5PL, 1.25)
        frame.loc[0, "Dose"] = -1.
        with self.assertRaises(FieldError) as caught:
            cal.predict_standard_curve(frame, "Dose", "Signal", "Query X", "Nonlinear", cal.CONCENTRATION_5PL)
        self.assertEqual(caught.exception.field, "Model")
