import unittest

import numpy as np
import pandas as pd
from scipy.stats import t

from analisi.global_fit import global_nonlinear


def frame(midpoints=(3., 3.)):
    x = np.geomspace(.1, 40., 25)
    return pd.concat([
        pd.DataFrame({"x": x, "y": vmax * x / (km + x) + .1 * np.sin(x + vmax), "group": label})
        for vmax, km, label in zip((12., 18.), midpoints, ("A", "B"), strict=True)
    ])


def fit(data, **options):
    return global_nonlinear(data, "x", "y", "Michaelis–Menten", "group", **options)


class SeriesConstraintsTests(unittest.TestCase):
    def test_series_fixed_parameters_leave_only_free_coordinates_in_covariance(self):
        data = frame()
        result = fit(data, intervals="profile", series_constraints={
            "A": {"Vmax": {"fixed": 12.}, "Km": {"fixed": 2.}},
            "B": {"Km": {"fixed": 3.}},
        })
        self.assertEqual(result.diagnostics["df"], len(data) - 1)
        self.assertEqual(list(result.covariance.index), [("Local", "B", "Vmax")])
        for label, value in (("A", 2.), ("B", 3.)):
            row = result.parameters.loc[("Fixed", label, "Km")]
            self.assertEqual(row["Estimate"], value)
            self.assertTrue(row.iloc[1:].isna().all())
            self.assertEqual(result.groups[label].parameters.loc["Km", "Estimate"], value)
        self.assertIsNone(result.groups["A"].band)
        self.assertIsNotNone(result.groups["B"].band)
        self.assertAlmostEqual(result.groups["B"].parameters.loc["Vmax", "Estimate"], 18., delta=.1)
        x = result.groups["A"].data["x"]
        np.testing.assert_allclose(result.groups["A"].residuals["Predicted"], 12 * x / (2 + x))

    def test_per_series_bounds_intersect_common_limits(self):
        result = fit(frame(), fixed={"Km": 3.}, bounds={"Vmax": (10., 19.)}, series_constraints={
            "A": {"Vmax": {"lower": 0., "upper": 11.}},
            "B": {"Vmax": {"lower": 18.5, "upper": 25.}},
        })
        self.assertAlmostEqual(result.parameters.loc[("Local", "A", "Vmax"), "Estimate"], 11.)
        self.assertAlmostEqual(result.parameters.loc[("Local", "B", "Vmax"), "Estimate"], 18.5)
        self.assertEqual(result.diagnostics["Active bounds"], 2)
        self.assertTrue(result.parameters["SE"].isna().all())
        with self.assertRaisesRegex(ValueError, "bound"):
            fit(frame(), bounds={"Vmax": (10., 19.)}, series_constraints={"A": {"Vmax": {"upper": 9.}}})

    def test_shared_bounds_intersect_series_limits(self):
        result = fit(frame(), shared=("Vmax",), fixed={"Km": 3.}, compare=True, series_constraints={
            "A": {"Vmax": {"lower": 16.}}, "B": {"Vmax": {"upper": 17.}},
        })
        self.assertAlmostEqual(result.parameters.loc[("Shared", None, "Vmax"), "Estimate"], 16.)
        self.assertIsNone(result.comparison)
        self.assertIn("bound", result.comparison_note.lower())

    def test_relaxed_comparison_respects_the_series_limits(self):
        result = fit(frame(), shared=("Vmax",), fixed={"Km": 3.}, compare=True, series_constraints={
            "A": {"Vmax": {"lower": 13.}},
        })
        self.assertEqual(result.diagnostics["Active bounds"], 0)
        self.assertIsNone(result.comparison)
        self.assertIn("bound", result.comparison_note.lower())

    def test_weakly_active_bounds_suppress_inference_and_nearby_interior_fits_do_not(self):
        x = np.arange(1., 7.)
        predictor = x / (3 + x)
        noise = np.array([1., -2., 1., 0., 0., 0.])
        noise -= predictor * ((predictor @ noise) / (predictor @ predictor))
        data = pd.DataFrame({"x": np.tile(x, 2), "y": np.r_[12 * predictor + noise, 18 * predictor - noise],
                             "group": np.repeat(["A", "B"], len(x))})
        for label, side, optimum, limit, active in (
            ("A", "lower", 12., 12.00001, True),
            ("A", "lower", 12., 12.0001, True),
            ("A", "lower", 12., 12., True),
            ("B", "upper", 18., 17.99999, True),
            ("A", "lower", 12., 11.99999, False),
            ("B", "upper", 18., 18.00001, False),
        ):
            with self.subTest(label=label, limit=limit):
                result = fit(data, fixed={"Km": 3.}, initial={"Vmax": 15.}, compare_local=("Vmax",),
                             series_constraints={label: {"Vmax": {side: limit}}})
                row = result.parameters.loc[("Local", label, "Vmax")]
                self.assertEqual(result.diagnostics["Active bounds"], int(active))
                self.assertAlmostEqual(row["Estimate"], limit if active else optimum, places=7)
                if active:
                    self.assertTrue(np.isnan(row["SE"]))
                    self.assertIsNone(result.local_comparison)
                    self.assertIn("bound", result.local_comparison_note.lower())
                else:
                    self.assertTrue(np.isfinite(row["SE"]))
                    self.assertLess(result.local_comparison["p"], .001)

    def test_comparison_relaxing_sharing_keeps_series_fixed_values(self):
        data = frame((3., 8.))
        constraints = {"A": {"Vmax": {"fixed": 12.}}}
        shared = fit(data, shared=("Km",), compare=True, series_constraints=constraints)
        independent = fit(data, series_constraints=constraints)
        self.assertEqual(shared.comparison["df numerator"], 1)
        self.assertEqual(shared.comparison["df denominator"], len(data) - 3)
        self.assertAlmostEqual(shared.comparison["Independent SS"], independent.diagnostics["Residual SS"])

    def test_additional_sharing_comparison_keeps_unrelated_series_fixed_values(self):
        data = frame((3., 8.))
        constraints = {"A": {"Vmax": {"fixed": 12.}}}
        independent = fit(data, compare_local=("Km",), series_constraints=constraints)
        shared = fit(data, shared=("Km",), series_constraints=constraints)
        self.assertEqual(independent.local_comparison["df numerator"], 1)
        self.assertAlmostEqual(independent.local_comparison["Reduced SS"], shared.diagnostics["Residual SS"])

    def test_additional_sharing_requires_free_coordinates_and_overlapping_bounds(self):
        data = frame()
        for constraints, message in (
            ({"A": {"Vmax": {"fixed": 12.}}}, "fixed"),
            ({"A": {"Vmax": {"upper": 14.}}, "B": {"Vmax": {"lower": 16.}}}, "bound"),
        ):
            with self.subTest(constraints=constraints):
                result = fit(data, compare_local=("Vmax",), series_constraints=constraints)
                self.assertIsNone(result.local_comparison)
                self.assertIn(message, result.local_comparison_note.lower())

    def test_profile_limit_stops_at_the_series_bound(self):
        data = frame()
        part = data[data["group"] == "B"]
        predictor = part["x"].to_numpy() / (3 + part["x"].to_numpy())
        response = part["y"].to_numpy()
        estimate = (predictor @ response) / (predictor @ predictor)
        upper = estimate + .005
        result = fit(data, fixed={"Km": 3.}, intervals="profile", series_constraints={
            "A": {"Vmax": {"fixed": 12.}}, "B": {"Vmax": {"upper": upper}},
        })
        row = result.parameters.loc[("Local", "B", "Vmax")]
        df = len(data) - 1
        se = np.sqrt(result.diagnostics["Residual SS"] / df / (predictor @ predictor))
        self.assertAlmostEqual(row["Estimate"], estimate)
        self.assertAlmostEqual(row["CI 95% low"], estimate - t.ppf(.975, df) * se)
        self.assertAlmostEqual(row["CI 95% high"], upper)

    def test_common_guess_can_be_adapted_to_tighter_series_limits(self):
        result = fit(frame(), initial={"Vmax": 17.}, series_constraints={
            "A": {"Vmax": {"lower": 10., "upper": 14.}},
            "B": {"Vmax": {"lower": 16., "upper": 20., "initial": 16.}},
        })
        self.assertAlmostEqual(result.parameters.loc[("Local", "A", "Vmax"), "Estimate"], 12., delta=.1)
        self.assertAlmostEqual(result.parameters.loc[("Local", "B", "Vmax"), "Estimate"], 18., delta=.1)

    def test_series_start_selects_the_requested_peak_over_the_common_guess(self):
        x = np.linspace(-5., 5., 51)
        y = np.exp(-.5 * ((x - 2) / .35)**2) + np.exp(-.5 * ((x + 2) / .35)**2)
        data = pd.DataFrame({"x": np.tile(x, 2), "y": np.tile(y, 2),
                             "group": np.repeat(["A", "B"], len(x))})
        result = global_nonlinear(data, "x", "y", "Gaussian", "group",
                                  fixed={"Amplitude": 1., "SD": .35}, initial={"Mean": -2.},
                                  series_constraints={"B": {"Mean": {"initial": 2.}}})
        self.assertAlmostEqual(result.parameters.loc[("Local", "A", "Mean"), "Estimate"], -2.)
        self.assertAlmostEqual(result.parameters.loc[("Local", "B", "Mean"), "Estimate"], 2.)

    def test_invalid_series_options_are_reported(self):
        data = frame()
        for constraints, options, message in (
            ({"missing": {"Km": {"fixed": 3.}}}, {}, "series"),
            ({"A": {"unknown": {"fixed": 3.}}}, {}, "parameter"),
            ({"A": {"Km": {"bad": 3.}}}, {}, "option"),
            ({"A": {"Km": {"fixed": np.nan}}}, {}, "fixed"),
            ({"A": {"Km": {"fixed": 0.}}}, {}, "bound"),
            ({"A": {"Km": {"lower": 4., "initial": 3.}}}, {}, "initial"),
            ({"A": {"Km": {"fixed": 3., "initial": 3.}}}, {}, "initial"),
            ({"A": {"Km": {"fixed": 3.}}}, {"shared": ("Km",)}, "shared"),
            ({"A": {"Km": {"fixed": 3.}}}, {"fixed": {"Km": 3.}}, "fixed"),
            ({"A": {"Km": {"lower": 4.}}}, {"fixed": {"Km": 3.}}, "bound"),
        ):
            with self.subTest(constraints=constraints, options=options), self.assertRaisesRegex(ValueError, message):
                fit(data, series_constraints=constraints, **options)
