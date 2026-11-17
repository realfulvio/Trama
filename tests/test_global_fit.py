import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.stats import f, t

from analisi import stats as engine
from analisi.curve_models import MODELS
from analisi.global_fit import global_nonlinear


MODEL = "Michaelis–Menten"
WEIGHTED = {"weighting": "Inverse variance (column)", "sigma": "sd"}


def saturation_frame(midpoints=(3., 3.)):
    x = np.r_[0., np.geomspace(.1, 40., 24)]
    return pd.concat([
        pd.DataFrame({"x": x, "y": vmax * x / (km + x) + .1 * np.sin(x + vmax),
                      "sd": (1 + x / 10) * scale, "group": label})
        for vmax, km, scale, label in zip((12., 18.), midpoints, (1., 3.), ("A", "B"))
    ])


def fit(frame, model=MODEL, **options):
    return global_nonlinear(frame, "x", "y", model, "group", **options)


class GlobalFitTests(unittest.TestCase):
    def test_large_global_design_is_rejected_before_allocating_dense_jacobian(self):
        frame = pd.DataFrame({"x": np.tile([1., 2., 3.], 101), "y": np.tile([2., 3., 4.], 101),
                              "group": np.repeat(np.arange(101), 3)})
        with patch("analisi.global_fit.optimize.least_squares", side_effect=AssertionError("optimizer ran")):
            with self.assertRaisesRegex(ValueError, "100 series"):
                fit(frame)

    def test_dense_local_parameter_budget_is_checked_before_optimization(self):
        x = np.arange(1., 20001.)
        frame = pd.DataFrame({"x": x, "y": 100. * x / (3. + x),
                              "group": np.repeat(np.arange(100), 200)})
        with patch("analisi.global_fit.optimize.least_squares", side_effect=AssertionError("optimizer ran")):
            with self.assertRaisesRegex(ValueError, "Jacobian budget"):
                fit(frame)

    def test_weighted_shared_fit_uses_one_objective_and_joint_covariance(self):
        frame = saturation_frame()
        joint = fit(frame, shared=("Km",), **WEIGHTED)
        estimates = joint.parameters["Estimate"]
        self.assertEqual(joint.diagnostics["df"], len(frame) - 3)
        km = estimates["Shared", None, "Km"]
        self.assertAlmostEqual(km, 3., delta=.1)
        gradients = []
        for label, group in joint.groups.items():
            vmax = estimates["Local", label, "Vmax"]
            self.assertAlmostEqual(vmax, {"A": 12., "B": 18.}[label], delta=.2)
            self.assertEqual(group.parameters.loc["Km", "Estimate"], km)
            x, sd = group.data["x"], group.data["sd"]
            local = x / (km + x) / sd
            shared = -vmax * x / (km + x)**2 / sd
            zero = np.zeros(len(x))
            gradients.append(np.column_stack((shared, local if label == "A" else zero,
                                              local if label == "B" else zero)))
        weighted_residual = np.concatenate([g.residuals["Weighted residual"] for g in joint.groups.values()])
        jacobian = np.vstack(gradients)
        np.testing.assert_allclose(jacobian.T @ weighted_residual, 0., atol=1e-6)
        ss = weighted_residual @ weighted_residual
        self.assertAlmostEqual(joint.diagnostics["Weighted residual SS"], ss)
        covariance = np.linalg.inv(jacobian.T @ jacobian) * (ss / joint.diagnostics["df"])
        coordinates = [("Shared", None, "Km"), ("Local", "A", "Vmax"), ("Local", "B", "Vmax")]
        np.testing.assert_allclose(joint.covariance.loc[coordinates, coordinates], covariance, rtol=1e-5)
        group = joint.groups["B"]
        x = group.curve[:, 0]
        vmax = estimates["Local", "B", "Vmax"]
        grid_gradient = np.column_stack((-vmax * x / (km + x)**2, np.zeros_like(x), x / (km + x)))
        variance = np.einsum("ij,jk,ik->i", grid_gradient, covariance, grid_gradient)
        expected_margin = t.ppf(.975, joint.diagnostics["df"]) * np.sqrt(variance)
        np.testing.assert_allclose(group.band, group.curve[:, 1, None] + expected_margin[:, None] * [-1, 1],
                                   rtol=1e-5, atol=1e-12)

    def test_common_sd_units_do_not_change_estimates_or_covariance(self):
        frame = saturation_frame()
        options = dict(shared=("Km",), **WEIGHTED)
        original = fit(frame, **options)
        converted = fit(frame.assign(sd=frame["sd"] * 1e30), **options)
        np.testing.assert_allclose(original.parameters, converted.parameters, rtol=1e-6)
        np.testing.assert_allclose(original.covariance, converted.covariance, rtol=1e-6)
        self.assertAlmostEqual(original.diagnostics["Weighted residual SS"],
                               converted.diagnostics["Weighted residual SS"] * 1e60)

    def test_incomplete_curves_can_identify_a_shared_model_jointly(self):
        x = np.arange(1., 5.)
        frame = pd.DataFrame({"x": x, "y": 8 * x / (3 + x), "group": ["A", "A", "B", "C"]})
        joint = fit(frame, shared=("Vmax", "Km"), compare=True)
        self.assertEqual(joint.diagnostics["df"], 2)
        np.testing.assert_allclose(joint.parameters["Estimate"], [8., 3.], rtol=1e-7)
        self.assertEqual(joint.groups["B"].diagnostics["N"], 1)
        self.assertIsNone(joint.comparison)
        self.assertTrue(joint.comparison_note)

    def test_missing_rows_preserve_duplicate_input_labels_and_weight_alignment(self):
        frame = saturation_frame()
        frame.loc[4, ["y", "sd"]] = np.nan
        joint = fit(frame, shared=("Km",), **WEIGHTED)
        self.assertEqual(joint.diagnostics["N"], len(frame) - 2)
        for group in joint.groups.values():
            self.assertNotIn(4, group.residuals.index)
            np.testing.assert_array_equal(group.residuals.index, group.data.index)
            np.testing.assert_allclose(group.residuals["Weighted residual"],
                                       group.residuals["Residual"] / group.data["sd"])
        self.assertEqual(joint.groups["A"].residuals.index[0], joint.groups["B"].residuals.index[0])

    def test_local_estimates_match_existing_independent_fit(self):
        frame = saturation_frame(midpoints=(3., 8.))
        joint = fit(frame, compare=True, **WEIGHTED)
        independent = engine.nonlinear(frame, "x", "y", MODEL, "group", **WEIGHTED)
        for label, group in joint.groups.items():
            np.testing.assert_allclose(group.parameters["Estimate"], independent[label].parameters["Estimate"],
                                       rtol=1e-6)
        self.assertIsNone(joint.comparison)

    def test_comparison_uses_same_weights_and_preserves_fixed_constraints(self):
        frame = saturation_frame(midpoints=(3., 8.))
        options = dict(fixed={"Vmax": 15.}, **WEIGHTED)
        shared = fit(frame, shared=("Km",), compare=True, **options)
        local = fit(frame, **options)
        comparison = shared.comparison
        self.assertEqual(comparison["df numerator"], 1)
        self.assertEqual(comparison["df denominator"], len(frame) - 2)
        self.assertAlmostEqual(comparison["Shared SS"], shared.diagnostics["Weighted residual SS"])
        self.assertAlmostEqual(comparison["Independent SS"], local.diagnostics["Weighted residual SS"])
        expected = (comparison["Shared SS"] - comparison["Independent SS"]) / (
            comparison["Independent SS"] / comparison["df denominator"]
        )
        self.assertAlmostEqual(comparison["F"], expected)
        self.assertAlmostEqual(comparison["p"], f.sf(expected, 1, len(frame) - 2))
        self.assertEqual(shared.parameters.loc[("Fixed", None, "Vmax"), "Estimate"], 15.)
        self.assertTrue(np.isnan(shared.parameters.loc[("Fixed", None, "Vmax"), "SE"]))
        self.assertEqual(shared.covariance.shape, (1, 1))

    def test_comparison_can_add_sharing_to_a_mixed_fit(self):
        x = np.linspace(0., 10., 25)
        frame = pd.concat([
            pd.DataFrame({"x": x, "y": plateau + span * np.exp(-rate * x) + .05 * np.sin(x), "group": label})
            for label, plateau, span, rate in [("A", 1., 4., .5), ("B", 1., 6., 1.)]
        ])
        full = fit(frame, "One-phase decay", shared=("Plateau",), compare_local=("Rate",))
        reduced = fit(frame, "One-phase decay", shared=("Plateau", "Rate"))
        comparison = full.local_comparison
        self.assertAlmostEqual(comparison["Reduced SS"], reduced.diagnostics["Residual SS"])
        self.assertAlmostEqual(comparison["Full SS"], full.diagnostics["Residual SS"])
        self.assertEqual(comparison["df numerator"], 1)
        self.assertEqual(comparison["df denominator"], len(frame) - 5)
        self.assertLess(comparison["p"], .001)
        self.assertIsNone(full.comparison)
        with self.assertRaisesRegex(ValueError, "local"):
            fit(frame, "One-phase decay", shared=("Rate",), compare_local=("Rate",))

    def test_user_initial_values_are_validated_and_can_start_a_fit(self):
        frame = saturation_frame()
        joint = fit(frame, shared=("Km",), initial={"Km": .4, "Vmax": 4.})
        baseline = fit(frame, shared=("Km",))
        np.testing.assert_allclose(joint.parameters["Estimate"], baseline.parameters["Estimate"], rtol=1e-6)
        for guesses in ({"Unknown": 1.}, {"Km": np.nan}, {"Km": -1.}):
            with self.subTest(guesses=guesses), self.assertRaisesRegex(ValueError, "parameter|initial"):
                fit(frame, initial=guesses)

    def test_start_at_a_bound_does_not_stop_at_a_wrong_fit(self):
        x = np.arange(10.)
        frame = pd.concat([pd.DataFrame({"x": x, "y": 100 + 5*np.exp(-.5*x) + .02*np.sin(x), "group": g})
                           for g in ("A", "B")])
        options = {"shared": ["Plateau"], "fixed": {"Span": 5., "Rate": .5},
                   "bounds": {"Plateau": (0., None)}}
        expected = fit(frame, model="One-phase decay", **options)
        result = fit(frame, model="One-phase decay", initial={"Plateau": 0.}, **options)
        np.testing.assert_allclose(result.parameters.iloc[0], expected.parameters.iloc[0], rtol=1e-7)
        self.assertLess(result.diagnostics["Residual SS"], .004)

    def test_active_bound_status_is_invariant_to_initial_guess_scale(self):
        x = np.arange(10.)
        frame = pd.concat([pd.DataFrame({"x": x, "y": 2 + 5*np.exp(-.5*x) + .02*np.sin(x), "group": g})
                           for g in ("A", "B")])
        options = {"shared": ["Plateau"], "fixed": {"Span": 5., "Rate": .5},
                   "bounds": {"Plateau": (0., None)}, "intervals": "profile"}
        close = fit(frame, model="One-phase decay", initial={"Plateau": 2.}, **options)
        distant = fit(frame, model="One-phase decay", initial={"Plateau": 1e8}, **options)
        self.assertEqual(distant.diagnostics["Active bounds"], 0)
        np.testing.assert_allclose(distant.parameters.iloc[0], close.parameters.iloc[0], rtol=1e-5)

    def test_active_bounds_suppress_inference_and_comparison(self):
        joint = fit(saturation_frame(), shared=("Km",), bounds={"Km": (4., None)}, compare=True)
        self.assertAlmostEqual(joint.parameters.loc[("Shared", None, "Km"), "Estimate"], 4.)
        self.assertTrue(joint.diagnostics["Active bounds"])
        self.assertTrue(joint.parameters["CI 95% low"].isna().all())
        self.assertTrue(all(group.band is None for group in joint.groups.values()))
        self.assertIsNone(joint.comparison)
        self.assertIn("bound", joint.comparison_note.lower())

    def test_independent_fit_active_bound_suppresses_f_test(self):
        frame = saturation_frame(midpoints=(2., 8.))
        joint = fit(frame, shared=("Km",), bounds={"Km": (3., None)}, compare=True)
        self.assertEqual(joint.diagnostics["Active bounds"], 0)
        self.assertIsNotNone(joint.groups["A"].band)
        self.assertIsNone(joint.comparison)
        self.assertIn("bound", joint.comparison_note.lower())

    def test_comparison_ss_remains_finite_for_small_sd_units(self):
        frame = saturation_frame()
        x = frame["x"]
        frame["y"] = 10 * x / (3 + x) + 1e-6 * np.sin(x)
        frame["sd"] = 1e-155
        shared = fit(frame, shared=("Km",), fixed={"Vmax": 10.}, compare=True, **WEIGHTED)
        self.assertTrue(np.isfinite(shared.comparison["Independent SS"]))

    def test_profile_intervals_reoptimize_nuisance_parameters_at_the_f_threshold(self):
        frame = saturation_frame(midpoints=(1., 12.))
        joint = fit(frame, shared=("Km",), intervals="profile", **WEIGHTED)
        estimate, _, low, high = joint.parameters.loc[("Shared", None, "Km")]
        self.assertLess(low, estimate)
        self.assertGreater(high, estimate)
        self.assertGreater(high - estimate, estimate - low)
        ss = joint.diagnostics["Weighted residual SS"]
        df = joint.diagnostics["df"]
        for endpoint in (low, high):
            profiled_ss = 0.
            for group in joint.groups.values():
                x, y, sd = (group.data[column].to_numpy() for column in ("x", "y", "sd"))
                slope = x / (endpoint + x) / sd
                target = y / sd
                vmax = slope @ target / (slope @ slope)
                residual = target - vmax * slope
                profiled_ss += residual @ residual
            self.assertAlmostEqual((profiled_ss - ss) / (ss / df), f.ppf(.95, 1, df), places=6)

    def test_optimizer_roundoff_is_not_residual_variance(self):
        x = np.arange(10.)
        frame = pd.concat([pd.DataFrame({"x": x, "y": base + span*np.exp(-.5*x), "group": group})
                           for group, base, span in (("A", 2., 5.), ("B", 4., 8.))])
        result = fit(frame, model="One-phase decay", shared=["Rate"], intervals="profile")
        self.assertFalse(result.diagnostics["Positive residual variance"])
        self.assertTrue(result.parameters["CI 95% low"].isna().all())

    def test_perfect_fit_does_not_report_residual_based_inference(self):
        x = np.arange(10.)
        y = MODELS["One-phase decay"].equation(x, 2., 5., .5)
        frame = pd.concat([pd.DataFrame({"x": x, "y": y, "group": label}) for label in ("A", "B")])
        joint = fit(frame, "One-phase decay", shared=("Plateau",), fixed={"Span": 5., "Rate": .5},
                    initial={"Plateau": 2.}, compare=True)
        self.assertEqual(joint.diagnostics["Residual SS"], 0.)
        self.assertTrue(joint.parameters["SE"].isna().all())
        self.assertIsNone(joint.groups["A"].band)
        self.assertIsNone(joint.comparison)

    def test_all_fixed_parameters_have_no_uncertainty(self):
        frame = saturation_frame()
        joint = fit(frame, fixed={"Vmax": 15., "Km": 3.}, compare=True)
        self.assertEqual(joint.diagnostics["df"], len(frame))
        self.assertEqual(joint.covariance.shape, (0, 0))
        self.assertIsNone(joint.comparison)
        for group in joint.groups.values():
            self.assertIsNone(group.band)
            x = group.data["x"]
            np.testing.assert_allclose(group.residuals["Predicted"], 15 * x / (3 + x))

    def test_nonidentifiable_joint_design_is_rejected(self):
        frame = saturation_frame().assign(x=1.)
        with self.assertRaisesRegex(ValueError, "identif"):
            fit(frame, shared=("Km",))

    def test_invalid_domains_and_parameter_constraints_are_rejected(self):
        frame = saturation_frame()
        for options, regex in [(dict(fixed={"Km": 0.}), "bound"),
                               (dict(bounds={"Km": (2., 1.)}), "bound"),
                               (dict(bounds={"Km": (3., 3.)}), "bound"),
                               (dict(shared=("not a parameter",)), "parameter")]:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, regex):
                fit(frame, **options)
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            fit(frame.assign(x=-1.), shared=("Km",))
        with self.assertRaisesRegex(ValueError, "positive"):
            fit(frame.assign(sd=0.), **WEIGHTED)

    def test_original_catalog_equations_fit_with_shared_parameters(self):
        dose = np.geomspace(.05, 100., 35)
        time = np.linspace(0., 12., 30)
        cases = [
            ("Normalized inhibition", dose * 1e-12, [3e-12, 1.2], [8e-12, 1.2]),
            ("One-phase decay", time, [2., 5., .4], [4., 10., .4]),
            ("Logistic (4 parameters)", time, [1., 9., 4., 1.], [3., 12., 5., 1.]),
            ("Stimulation (standard slope)", dose, [2., 14., 3.], [3., 17., 3.]),
            ("Stimulation (variable slope)", dose, [2., 14., 3., 1.6], [3., 17., 4., 1.6]),
            ("Inhibition (standard slope)", dose, [2., 14., 3.], [3., 17., 3.]),
            ("Inhibition (variable slope)", dose, [2., 14., 3., -1.6], [3., 17., 4., -1.6]),
            ("Michaelis–Menten", dose * 1e-12, [12., 3e-12], [18., 3e-12]),
            ("One-site specific binding", dose, [12., 3.], [18., 3.]),
            ("One-site total binding", dose, [12., 3., .2, 1.1], [18., 4., .3, 1.1]),
            ("One-phase association", time, [2., 9., .7], [4., 14., .7]),
            ("Exponential growth", time, [2., .3], [5., .3]),
            ("Gaussian", np.linspace(-4., 6., 41), [6., 1., .9], [9., 2., .9]),
        ]
        self.assertTrue({case[0] for case in cases} <= set(MODELS))
        for model, x, first, second in cases:
            with self.subTest(model=model):
                spec = MODELS[model]
                frame = pd.concat([
                    pd.DataFrame({"x": x, "y": spec.equation(x, *parameters), "group": label})
                    for label, parameters in zip(("A", "B"), (first, second))
                ])
                joint = fit(frame, model, shared=(spec.parameters[-1],))
                for label, expected in zip(("A", "B"), (first, second)):
                    np.testing.assert_allclose(joint.groups[label].parameters["Estimate"], expected, rtol=1e-5)
