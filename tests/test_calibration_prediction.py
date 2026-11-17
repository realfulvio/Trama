"""Y from X on a standard curve: independent references, bands, domain and 0.52.0 recipes."""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats

from analisi import nonlinear_calibration as cal
from analisi.processing import FieldError
from analisi.stats import nonlinear
from analisi.workbench import analyse

DATA = Path(__file__).resolve().parent / "data" / "calibration_prediction"
METHOD = "Interpolate a standard curve"
FIELDS = ["Source row", "X", "Predicted Y", "Status", "Y lower", "Y upper"]
BAND_FIELDS = ["X", "Fit", "Y lower", "Y upper"]
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))


def fixture(model):
    return pd.read_csv(DATA / f"{model}.csv")


def forward(frame, curve="Linear", uncertainty="None", level=None, **extra):
    options = {"X": "X", "Y": "Y", "Direction": "Y from X", "Unknown X": "Query X", "Curve": curve,
               "Uncertainty": uncertainty, **extra}
    if curve == "Nonlinear":
        options.setdefault("Model", "One-phase decay")
    if level is not None:
        options["Confidence level (%)"] = level
    return analyse(METHOD, frame, options)


def reference(frame, model, kind, level, grid):
    """Centered OLS, or least squares with an analytic Jacobian for the decay."""
    x, y = frame[["X", "Y"]].dropna().to_numpy().T
    if model == "linear":
        center = x.mean()

        def jac(z, _theta):
            return np.column_stack((np.ones_like(z), z - center))

        def curve(z, theta):
            return jac(z, theta) @ theta

        theta = np.linalg.lstsq(jac(x, None), y, rcond=None)[0]
    else:
        def jac(z, theta):
            e = np.exp(-theta[2] * z)
            return np.column_stack((np.ones_like(z), e, -theta[1] * z * e))

        def curve(z, theta):
            return theta[0] + theta[1] * np.exp(-theta[2] * z)

        theta = optimize.least_squares(lambda p: curve(x, p) - y, [2, 10, .65], jac=lambda p: jac(x, p),
                                       xtol=1e-14, ftol=1e-14, gtol=1e-13).x
    df = len(x) - len(theta)
    residual = y - curve(x, theta)
    s2 = residual @ residual / df
    cov = s2 * np.linalg.inv(jac(x, theta).T @ jac(x, theta))
    q = stats.t.ppf((1 + level / 100) / 2, df)
    g = jac(grid, theta)
    half = q * np.sqrt(np.einsum("ij,jk,ik->i", g, cov, g) + (s2 if kind == "Prediction" else 0))
    fitted = curve(grid, theta)
    return np.column_stack((grid, fitted, fitted - half, fitted + half))


def assert_rows(test, frame, expected):
    test.assertEqual(len(frame), len(expected))
    for actual, wanted in zip(frame.itertuples(index=False, name=None), expected, strict=True):
        for a, b in zip(actual, wanted, strict=True):
            if b is None:
                test.assertTrue(pd.isna(a), (actual, wanted))
            elif isinstance(b, str):
                test.assertEqual(a, b)
            else:
                np.testing.assert_allclose(a, b, rtol=2e-5, atol=2e-5)


class CalibrationPredictionTests(unittest.TestCase):
    def test_level_just_below_100_retains_finite_prediction_limits(self):
        level = np.nextafter(100.0, 0.0)
        predictions = forward(fixture("linear"), uncertainty="Prediction", level=level).tables[cal.PREDICTIONS]
        inside = predictions.iloc[:3]
        self.assertEqual(inside["Status"].tolist(), [cal.IN_RANGE] * 3)
        self.assertTrue(np.isfinite(inside[["Y lower", "Y upper"]].to_numpy()).all())

    def test_six_reference_cases(self):
        for model, level in (("linear", 95), ("decay", 90)):
            frame = fixture(model)
            curve = "Linear" if model == "linear" else "Nonlinear"
            for kind in cal.UNCERTAINTIES:
                with self.subTest(model=model, kind=kind):
                    result = forward(frame, curve, kind, None if kind == "None" else level)
                    expected = EXPECTED[f"{model}/{kind}"]
                    table = result.tables[cal.PREDICTIONS]
                    self.assertEqual(list(table.columns), ["Source row", "Row title", *FIELDS[1:]])
                    self.assertEqual(table["Row title"].tolist(), ["Sample 1", "Sample 2", "Sample 3", "Sample 4"])
                    assert_rows(self, table[FIELDS], expected["Calibrated predictions"]["rows"])
                    if kind == "None":
                        self.assertNotIn(cal.BANDS, result.tables)
                        continue
                    bands = result.tables[cal.BANDS]
                    self.assertEqual(list(bands.columns), BAND_FIELDS)
                    grid = bands["X"].to_numpy()
                    self.assertTrue(np.all(np.diff(grid) > 0))
                    self.assertEqual((grid[0], grid[-1]), (frame["X"].min(), frame["X"].max()))
                    np.testing.assert_allclose(bands.to_numpy(dtype=float), reference(frame, model, kind, level, grid),
                                               rtol=2e-5, atol=2e-5)
                    # The fixture's 7-point grid endpoints are on every grid.
                    assert_rows(self, bands.iloc[[0, -1]], [expected["Calibration bands"]["rows"][i] for i in (0, -1)])
                    labels = [text.get_text() for text in result.figure.axes[0].get_legend().get_texts()]
                    band = "mean response" if kind == "Mean response" else "prediction"
                    self.assertIn(f"{level:g}% {band} band", labels)
                    self.assertIn("Predictions", labels)
                    if model == "linear":
                        self.assertIn("Linear calibration", result.tables)
                    else:
                        self.assertIn("Calibration parameters", result.tables)
                        self.assertIn("Fit diagnostics", result.tables)

    def test_prediction_band_is_wider_than_mean_band(self):
        frame = fixture("decay")
        mean = forward(frame, "Nonlinear", "Mean response", 95).tables[cal.BANDS]
        single = forward(frame, "Nonlinear", "Prediction", 95).tables[cal.BANDS]
        self.assertTrue((single["Y upper"] - single["Y lower"] > mean["Y upper"] - mean["Y lower"]).all())

    def test_recipe_without_direction_keeps_inverse_calibration(self):
        frame = pd.DataFrame({"X": [0., 1, 2, 3, 4], "Y": [1., 3.1, 4.9, 7.2, 8.8], "Unknown": [2., 5., np.nan, 20., 1.],
                              "Query X": [1., 2, 3, 4, 5]})
        old = {"X": "X", "Y": "Y", "Unknown responses": "Unknown", "Curve": "Linear"}
        # Since 0.53 the inverse line has intervals; Uncertainty None keeps the 0.53.0 tables and ignores the level.
        explicit = {**old, "Direction": "X from Y", "Unknown X": "Query X", "Uncertainty": "None",
                    "Confidence level (%)": 500, "Replicate count column": "Query X"}
        first, second = analyse(METHOD, frame, old), analyse(METHOD, frame, explicit)
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, {**explicit, "Uncertainty": "Prediction"})
        self.assertEqual(raised.exception.field, "Confidence level (%)")
        self.assertEqual(list(first.tables), ["Interpolated values", "Linear calibration"])
        self.assertEqual(list(first.tables), list(second.tables))
        for name in first.tables:
            pd.testing.assert_frame_equal(first.tables[name], second.tables[name])
        decay = fixture("decay").assign(Unknown=[5., 3., 2.5, np.nan, 20., np.nan, np.nan, np.nan, np.nan])
        for model in cal.INVERSE_MODELS[:2]:
            options = {"X": "X", "Y": "Y", "Unknown responses": "Unknown", "Curve": "Nonlinear", "Model": model}
            try:
                legacy = analyse(METHOD, decay, options)
            except ValueError:
                continue
            self.assertIn("Interpolated values", legacy.tables)
            self.assertNotIn(cal.PREDICTIONS, legacy.tables)

    def test_level_and_model_errors_name_their_field(self):
        frame = fixture("linear")
        for level in (0, 100, -5, float("nan"), float("inf"), "abc"):
            with self.subTest(level=level), self.assertRaises(FieldError) as raised:
                forward(frame, uncertainty="Mean response", level=level)
            self.assertEqual(raised.exception.field, "Confidence level (%)")
        # A hidden level has no effect when no band is requested.
        result = forward(frame, uncertainty="None", level=500)
        self.assertNotIn(cal.BANDS, result.tables)
        with self.assertRaises(FieldError) as raised:
            forward(frame, "Nonlinear", "None", Model="One-phase association")
        self.assertEqual(raised.exception.field, "Model")
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, {"X": "X", "Y": "Y", "Direction": "Y from X", "Curve": "Linear"})
        self.assertEqual(raised.exception.field, "Unknown X")
        with self.assertRaises(FieldError) as raised:
            forward(frame.assign(**{"Query X": np.nan}))
        self.assertEqual(raised.exception.field, "Unknown X")

    def test_domain_duplicates_and_excluded_standards(self):
        frame = fixture("linear")
        frame.loc[4:6, "Query X"] = [7.0, 7.0000001, 0.0]
        table = forward(frame, uncertainty="Prediction", level=95).tables[cal.PREDICTIONS]
        self.assertEqual(table["Source row"].tolist(), [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(table["Status"].tolist(), ["In range"] * 3 + ["Outside calibration", "In range",
                                                                        "Outside calibration", "In range"])
        self.assertTrue(table.loc[3, ["Predicted Y", "Y lower", "Y upper"]].isna().all())
        # An excluded (missing) standard narrows the domain and changes the fit.
        excluded = frame.copy()
        excluded.loc[7, "Y"] = np.nan
        changed = forward(excluded, uncertainty="Prediction", level=95)
        moved = changed.tables[cal.PREDICTIONS]
        self.assertEqual(moved.at[4, "Status"], "Outside calibration")
        self.assertNotAlmostEqual(moved.at[0, "Predicted Y"], table.at[0, "Predicted Y"])
        self.assertEqual(changed.tables[cal.BANDS]["X"].iloc[-1], 6.0)

    def test_source_rows_follow_the_worksheet_index(self):
        frame = fixture("linear").drop(columns="Row title")
        frame.index = np.arange(20, 28)
        table = forward(frame).tables[cal.PREDICTIONS]
        self.assertEqual(list(table.columns), FIELDS)
        self.assertEqual(table["Source row"].tolist(), [20, 21, 22, 23])

    def test_exact_fit_keeps_estimates_without_limits(self):
        frame = pd.DataFrame({"X": [0., 1, 2, 3, 4], "Y": [1., 3, 5, 7, 9], "Query X": [1.5, 9, np.nan, np.nan, np.nan]})
        for kind in ("Mean response", "Prediction"):
            result = forward(frame, uncertainty=kind, level=95)
            table = result.tables[cal.PREDICTIONS]
            self.assertEqual(table["Status"].tolist(), [cal.UNCERTAINTY_UNAVAILABLE, "Outside calibration"])
            self.assertAlmostEqual(table.at[0, "Predicted Y"], 4.0)
            self.assertTrue(table[["Y lower", "Y upper"]].isna().all().all())
            self.assertNotIn(cal.BANDS, result.tables)
        none = forward(frame).tables[cal.PREDICTIONS]
        self.assertEqual(none.at[0, "Status"], "In range")

    def test_decay_covariance_matches_reported_standard_errors(self):
        fit = nonlinear(fixture("decay"), "X", "Y", "One-phase decay")["All"]
        np.testing.assert_allclose(np.sqrt(np.diag(fit.covariance)), fit.parameters["SE"], rtol=1e-10)

    def test_rate_on_its_bound_leaves_limits_unavailable(self):
        frame = fixture("decay")
        fit = nonlinear(frame, "X", "Y", "One-phase decay")["All"]
        fit.parameters.loc["Rate", "Estimate"] = cal.RATE_BOUND / 10
        from unittest.mock import patch
        with patch.object(cal, "nonlinear", return_value={"All": fit}):
            table = forward(frame, "Nonlinear", "Mean response", 95).tables[cal.PREDICTIONS]
        self.assertEqual(table["Status"].tolist()[:3], [cal.UNCERTAINTY_UNAVAILABLE] * 3)

    def test_variance_rounding(self):
        # Cancellation leaves -2e-13 against a scale of 4: rounding, reported as 0.
        g = np.array([[1.0, 1.0], [0.0, 1.0]])
        cov = np.array([[1.0, -1.0 - 1e-13], [-1.0 - 1e-13, 1.0]])
        variance = cal._variance(g, cov)
        self.assertEqual(variance[0], 0.0)
        self.assertEqual(variance[1], 1.0)
        clearly = cal._variance(np.array([[0.0, 1.0]]), np.array([[1.0, 0.0], [0.0, -1.0]]))
        self.assertTrue(np.isnan(clearly[0]))

    def test_visibility(self):
        self.assertEqual(cal.calibration_visibility("X from Y", "Linear", "Prediction"),
                         {"Unknown responses": True, "Unknown X": False, "Model": False, "Uncertainty": True,
                          "Confidence level (%)": True, "Replicate count column": True})
        self.assertEqual(cal.calibration_visibility("X from Y", "Nonlinear", "Prediction"),
                         {"Unknown responses": True, "Unknown X": False, "Model": True, "Uncertainty": False,
                          "Confidence level (%)": False, "Replicate count column": False})
        self.assertEqual(cal.calibration_visibility("Y from X", "Nonlinear", "Mean response"),
                         {"Unknown responses": False, "Unknown X": True, "Model": True, "Uncertainty": True,
                          "Confidence level (%)": True, "Replicate count column": False})
        self.assertFalse(cal.calibration_visibility("Y from X", "Linear", "None")["Confidence level (%)"])


if __name__ == "__main__":
    unittest.main()
