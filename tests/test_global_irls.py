"""Global and independent nonlinear fits with weights from the observed Y or from the fitted curve (0.60)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.stats import f as f_distribution, t as t_distribution

from analisi import fit_weights
from analisi import stats as engine
from analisi.data import Dataset, load_project, save_project
from analisi.global_fit import global_nonlinear
from analisi.processing import FieldError
from analisi.repeated_workbench import METHODS, check_global_weighting
from analisi.workbench import analyse

DATA = Path(__file__).parent / "data" / "global_irls"
ORACLE = json.loads((DATA / "oracle.json").read_text(encoding="utf-8"))
LEGACY = json.loads((DATA / "legacy-global.json").read_text(encoding="utf-8"))
OBSERVED = ("1/abs(Y)", "1/Y²")
FITTED = ("1/abs(Yfit)", "1/Yfit²")
KEYS = [("Shared", None, "Slope"), ("Local", "A", "Intercept"), ("Local", "B", "Intercept")]
LONG = {"Input format": "Long table", "X": "X", "Y": "Y", "Series": "Series", "Model": "Straight line",
        "Shared parameters": ["Slope"]}


def global_frame():
    return pd.read_csv(DATA / "global.csv")


def power(label):
    return 1.0 if "²" in label else 0.5


def reference(frame, label, *, fixed_a=None, levels=None):
    """Joint WLS by one design matrix; the fitted modes iterate the unweighted start to a fixed point."""
    series = frame["Series"].to_numpy()
    levels = levels or list(dict.fromkeys(series))
    x, y = frame["X"].to_numpy(), frame["Y"].to_numpy()
    design = np.column_stack([x, *[series == level for level in levels]]).astype(float)
    offset = np.zeros(len(y))
    if fixed_a is not None:
        offset = design[:, 1] * fixed_a
        design = np.delete(design, 1, axis=1)
    target = y - offset
    beta = np.linalg.lstsq(design, target, rcond=None)[0]
    scale = np.ones(len(y))
    for _ in range(500):
        if label in OBSERVED:
            scale = np.abs(y) ** power(label)
        elif label in FITTED:
            scale = np.abs(design @ beta + offset) ** power(label)
        update = np.linalg.lstsq(design / scale[:, None], target / scale, rcond=None)[0]
        done = np.allclose(update, beta, rtol=1e-12, atol=0)
        beta = update
        if label in OBSERVED or done:
            break
    residual = target - design @ beta
    weighted_ss = float(np.sum((residual / scale) ** 2))
    df = len(y) - design.shape[1]
    covariance = np.linalg.inv((design / scale[:, None]).T @ (design / scale[:, None])) * weighted_ss / df
    return beta, covariance, weighted_ss, scale, residual / scale


class OracleTests(unittest.TestCase):
    def test_reference_matches_the_independent_oracle(self):
        frame = global_frame()
        for label, row in ORACLE.items():
            beta, covariance, weighted_ss, _, _ = reference(frame, label)
            np.testing.assert_allclose(beta, row["beta"], rtol=1e-9)
            np.testing.assert_allclose(covariance, row["covariance"], rtol=1e-7)
            self.assertAlmostEqual(weighted_ss, row["Weighted residual SS"], places=9)

    def test_joint_estimates_covariance_residuals_and_comparison(self):
        frame = global_frame()
        for label, row in ORACLE.items():
            with self.subTest(label):
                fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",),
                                       weighting=label, compare=True)
                np.testing.assert_allclose(fit.parameters.loc[KEYS, "Estimate"], row["beta"], rtol=2e-5)
                np.testing.assert_allclose(fit.covariance.loc[KEYS, KEYS], row["covariance"], rtol=3e-4)
                self.assertAlmostEqual(fit.diagnostics["Weighted residual SS"], row["Weighted residual SS"],
                                       delta=2e-5 * row["Weighted residual SS"])
                self.assertAlmostEqual(fit.diagnostics["Residual SS"], row["Residual SS"], delta=2e-5 * row["Residual SS"])
                self.assertAlmostEqual(fit.diagnostics["Weighted R²"], row["Weighted R²"], places=6)
                np.testing.assert_allclose(fit.comparison["F"], row["comparison"]["F"], rtol=3e-4)
                np.testing.assert_allclose(fit.comparison["p"], row["comparison"]["p"], rtol=3e-4)
                np.testing.assert_allclose(fit.comparison["Independent SS"], row["comparison"]["Independent SS"],
                                           rtol=3e-5)
                weighted = np.concatenate([part.residuals["Weighted residual"] for part in fit.groups.values()])
                np.testing.assert_allclose(weighted, row["weighted_residual"], rtol=2e-5, atol=1e-7)
                self.assertEqual(fit.diagnostics["Weighting"], label)

    def test_fixed_parameter_for_one_series(self):
        frame = global_frame()
        for label, row in ORACLE.items():
            with self.subTest(label):
                fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label,
                                       series_constraints={"A": {"Intercept": {"fixed": 2.2}}})
                keys = [("Shared", None, "Slope"), ("Local", "B", "Intercept")]
                np.testing.assert_allclose(fit.parameters.loc[keys, "Estimate"], row["fixed"]["beta"], rtol=2e-5)
                np.testing.assert_allclose(fit.covariance.loc[keys, keys], row["fixed"]["covariance"], rtol=3e-4)
                np.testing.assert_allclose(fit.diagnostics["Weighted residual SS"],
                                           row["fixed"]["Weighted residual SS"], rtol=2e-5)

    def test_fitted_modes_report_iterations_and_the_frozen_inference_weights(self):
        frame = global_frame()
        for label in FITTED:
            diagnostics = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",),
                                           weighting=label).diagnostics
            self.assertEqual(diagnostics["Weighting"], label)
            self.assertIs(diagnostics["Weighting converged"], True)
            self.assertIsInstance(diagnostics["Weighting iterations"], int)
            self.assertTrue(1 <= diagnostics["Weighting iterations"] <= fit_weights.MAX_WEIGHT_REFITS)
            self.assertEqual(diagnostics["Inference weights"], "Final frozen weights")
        for label in ("Unweighted", *OBSERVED):
            diagnostics = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",),
                                           weighting=label).diagnostics
            self.assertNotIn("Weighting iterations", diagnostics)

    def test_the_last_refit_is_stationary_for_its_own_frozen_scales(self):
        frame = global_frame()
        x, y, series = frame["X"].to_numpy(), frame["Y"].to_numpy(), frame["Series"].to_numpy()
        design = np.column_stack((x, series == "A", series == "B")).astype(float)
        for label in FITTED:
            fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
            weighted = np.concatenate([part.residuals["Weighted residual"] for part in fit.groups.values()])
            scale = np.concatenate([part.residuals["Residual"] / part.residuals["Weighted residual"]
                                    for part in fit.groups.values()])
            np.testing.assert_allclose(design.T @ (weighted / scale), 0, atol=2e-7)
            beta = fit.parameters.loc[KEYS, "Estimate"].to_numpy()
            np.testing.assert_allclose(scale, np.abs(design @ beta) ** power(label), rtol=2e-7)

    def test_profile_intervals_keep_the_frozen_weights_and_match_t_in_the_linear_case(self):
        frame = global_frame()
        row = ORACLE["1/Yfit²"]
        profiled = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",),
                                    weighting="1/Yfit²", intervals="profile")
        delta = t_distribution.ppf(.975, 9) * np.sqrt(np.diag(row["covariance"]))
        np.testing.assert_allclose(profiled.parameters.loc[KEYS, "CI 95% low"], np.array(row["beta"]) - delta,
                                   rtol=5e-4, atol=1e-5)
        np.testing.assert_allclose(profiled.parameters.loc[KEYS, "CI 95% high"], np.array(row["beta"]) + delta,
                                   rtol=5e-4, atol=1e-5)
        self.assertEqual(profiled.diagnostics["Inference weights"], "Final frozen weights")
        self.assertEqual(profiled.diagnostics["Unavailable profile limits"], 0)

    def test_independent_fits_with_fitted_weights_match_the_oracle(self):
        single = pd.read_csv(DATA / "single.csv")
        for label in FITTED:
            fit = engine.nonlinear(single, "X", "Y", "Straight line", weighting=label)["All"]
            np.testing.assert_allclose(fit.parameters["Estimate"], ORACLE[label]["single"]["beta"], rtol=2e-5)
            np.testing.assert_allclose(fit.covariance, ORACLE[label]["single"]["covariance"], rtol=3e-4)
            self.assertIs(fit.diagnostics["Weighting converged"], True)
            self.assertEqual(fit.diagnostics["Inference weights"], "Final frozen weights")
            self.assertEqual(fit.diagnostics["Weighting"], label)
            self.assertLessEqual(fit.diagnostics["Weighting iterations"], fit_weights.MAX_WEIGHT_REFITS)

    def test_independent_fits_per_group_equal_the_reference_iteration(self):
        frame = global_frame()
        fits = engine.nonlinear(frame, "X", "Y", "Straight line", "Series", weighting="1/Yfit²")
        for label, part in frame.groupby("Series"):
            x, y = part["X"].to_numpy(), part["Y"].to_numpy()
            design = np.column_stack((np.ones(len(x)), x))
            beta = np.linalg.lstsq(design, y, rcond=None)[0]
            for _ in range(500):
                scale = np.abs(design @ beta)
                beta = np.linalg.lstsq(design / scale[:, None], y / scale, rcond=None)[0]
            np.testing.assert_allclose(fits[label].parameters["Estimate"], beta, rtol=1e-6)


class WeightScaleTests(unittest.TestCase):
    def test_the_normalization_is_common_to_all_series(self):
        """Duplicating the rows of one series doubles its weight in the single joint objective."""
        frame = global_frame()
        doubled = pd.concat([frame, frame[frame["Series"] == "B"]], ignore_index=True)
        for label in (*OBSERVED, *FITTED):
            with self.subTest(label):
                base = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
                more = global_nonlinear(doubled, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
                beta, *_ = reference(doubled, label)
                np.testing.assert_allclose(more.parameters.loc[KEYS, "Estimate"], beta, rtol=2e-5)
                self.assertGreater(abs(more.parameters.loc[KEYS[0], "Estimate"] - base.parameters.loc[KEYS[0], "Estimate"]),
                                   1e-3)

    def test_series_with_different_magnitudes_are_not_renormalized_locally(self):
        frame = global_frame()
        frame.loc[frame["Series"] == "B", "Y"] *= 1000
        for label in (*OBSERVED, *FITTED):
            with self.subTest(label):
                fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
                beta, *_ = reference(frame, label)
                np.testing.assert_allclose(fit.parameters.loc[KEYS, "Estimate"], beta, rtol=2e-5)

    def test_negated_responses_give_the_mirrored_fit(self):
        frame = global_frame()
        negated = frame.assign(Y=-frame["Y"])
        for label in (*OBSERVED, *FITTED):
            with self.subTest(label):
                fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
                mirror = global_nonlinear(negated, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
                np.testing.assert_allclose(mirror.parameters["Estimate"], -fit.parameters["Estimate"], rtol=1e-6)
                np.testing.assert_allclose(mirror.diagnostics["Weighted residual SS"],
                                           fit.diagnostics["Weighted residual SS"], rtol=1e-6)

    def test_large_response_units_leave_the_fit_unchanged(self):
        frame = global_frame()
        for label in (*OBSERVED, *FITTED):
            with self.subTest(label):
                fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
                big = global_nonlinear(frame.assign(Y=frame["Y"] * 1e6), "X", "Y", "Straight line", "Series",
                                       shared=("Slope",), weighting=label)
                np.testing.assert_allclose(big.parameters["Estimate"], fit.parameters["Estimate"] * 1e6, rtol=1e-6)
                np.testing.assert_allclose(big.diagnostics["Weighted residual SS"],
                                           fit.diagnostics["Weighted residual SS"] * 1e6 ** (2 - 2 * power(label)),
                                           rtol=1e-6)
                np.testing.assert_allclose(big.parameters["SE"], fit.parameters["SE"] * 1e6, rtol=1e-5)

    def test_duplicate_index_labels_do_not_realign_rows(self):
        frame = global_frame()
        shuffled = frame.set_axis([0, 1] * (len(frame) // 2))
        for label in (*OBSERVED, *FITTED):
            fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
            same = global_nonlinear(shuffled, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
            np.testing.assert_allclose(same.parameters["Estimate"], fit.parameters["Estimate"], rtol=1e-9)

    def test_more_than_two_series_with_one_fixed_parameter_each(self):
        rng = np.random.default_rng(11)
        x = np.tile(np.arange(1., 7.), 3)
        series = np.repeat(list("ABC"), 6)
        y = 1.5 * x + np.repeat([2., 9., 20.], 6) + .2 * rng.standard_normal(18)
        frame = pd.DataFrame({"X": x, "Y": y, "Series": series})
        constraints = {"A": {"Intercept": {"fixed": 2.}}, "B": {"Intercept": {"fixed": 9.}},
                       "C": {"Intercept": {"fixed": 20.}}}
        for label in (*OBSERVED, *FITTED):
            with self.subTest(label):
                fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label,
                                       series_constraints=constraints)
                offset = np.repeat([2., 9., 20.], 6)
                design = x[:, None]
                target = y - offset
                beta = np.linalg.lstsq(design, target, rcond=None)[0]
                for _ in range(500):
                    scale = (np.abs(y) if label in OBSERVED else np.abs(design @ beta + offset)) ** power(label)
                    new = np.linalg.lstsq(design / scale[:, None], target / scale, rcond=None)[0]
                    done = np.allclose(new, beta, rtol=1e-12, atol=0)
                    beta = new
                    if done or label in OBSERVED:
                        break
                np.testing.assert_allclose(fit.parameters.loc[("Shared", None, "Slope"), "Estimate"], beta[0], rtol=2e-6)
                self.assertEqual(int((fit.parameters.index.get_level_values("Scope") == "Fixed").sum()), 3)

    def test_a_bound_active_at_the_solution_still_gives_a_weighted_fit_without_inference(self):
        frame = global_frame()
        for label in (*OBSERVED, *FITTED):
            with self.subTest(label):
                fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label,
                                       bounds={"Slope": (None, 1.2)})
                self.assertEqual(fit.diagnostics["Active bounds"], 1)
                self.assertAlmostEqual(fit.parameters.loc[KEYS[0], "Estimate"], 1.2, places=6)
                self.assertTrue(np.isnan(fit.parameters["SE"]).all())

    def test_nonlinear_shared_parameter_with_fitted_weights(self):
        rng = np.random.default_rng(5)
        x = np.geomspace(.2, 40, 12)
        frames = [pd.DataFrame({"x": x, "y": vmax * x / (3. + x) * (1 + .04 * rng.standard_normal(len(x))), "g": label})
                  for vmax, label in ((12., "A"), (18., "B"), (8., "C"))]
        frame = pd.concat(frames, ignore_index=True)
        for label in (*OBSERVED, *FITTED):
            with self.subTest(label):
                fit = global_nonlinear(frame, "x", "y", "Michaelis–Menten", "g", shared=("Km",), weighting=label,
                                       compare=True)
                self.assertAlmostEqual(fit.parameters.loc[("Shared", None, "Km"), "Estimate"], 3., delta=.6)
                self.assertIsNotNone(fit.comparison)
                scales = np.concatenate([part.residuals["Residual"] / part.residuals["Weighted residual"]
                                         for part in fit.groups.values()])
                if label in OBSERVED:
                    np.testing.assert_allclose(scales, np.abs(frame["y"]) ** power(label), rtol=1e-12)
                else:
                    predicted = np.concatenate([part.residuals["Predicted"] for part in fit.groups.values()])
                    np.testing.assert_allclose(scales, np.abs(predicted) ** power(label), rtol=1e-6)


class ErrorTests(unittest.TestCase):
    def test_a_zero_observed_response_names_the_weighting_field_for_the_observed_modes(self):
        frame = global_frame()
        frame.loc[2, "Y"] = 0.
        for label in OBSERVED:
            with self.assertRaises(FieldError) as raised:
                global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
            self.assertEqual(raised.exception.field, "Weighting")
            self.assertIn("zero", str(raised.exception))
            with self.assertRaises(FieldError) as raised:
                analyse("Global nonlinear regression", frame, {**LONG, "Weighting": label})
            self.assertEqual(raised.exception.field, "Weighting")
            with self.assertRaises(FieldError) as raised:
                check_global_weighting(frame, {**LONG, "Weighting": label})
            self.assertEqual(raised.exception.field, "Weighting")

    def test_the_fitted_modes_accept_a_zero_response_when_the_fitted_values_are_nonzero(self):
        frame = global_frame()
        frame.loc[2, "Y"] = 0.
        for label in FITTED:
            fit = global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting=label)
            self.assertIs(fit.diagnostics["Weighting converged"], True)
            check_global_weighting(frame, {**LONG, "Weighting": label})
            single = engine.nonlinear(frame[frame["Series"] == "A"], "X", "Y", "Straight line", weighting=label)["All"]
            self.assertIs(single.diagnostics["Weighting converged"], True)

    def test_a_zero_fitted_value_names_the_weighting_field(self):
        frame = pd.DataFrame({"X": [1., 2., 3., 4.] * 2, "Y": 0., "Series": ["A"] * 4 + ["B"] * 4})
        for label in FITTED:
            with self.assertRaises(FieldError) as raised:
                global_nonlinear(frame, "X", "Y", "Horizontal line", "Series", weighting=label)
            self.assertEqual(raised.exception.field, "Weighting")
            self.assertIn("fitted curve is zero", str(raised.exception))
            with self.assertRaises(FieldError) as raised:
                engine.nonlinear(frame[frame["Series"] == "A"], "X", "Y", "Horizontal line", weighting=label)
            self.assertEqual(raised.exception.field, "Weighting")

    def test_the_package_fixture_with_a_zero_prediction_names_weighting_in_both_paths(self):
        frame = pd.read_csv(DATA / "irls-zero-prediction.csv")
        options = {"Input format": "Long table", "X": "X", "Y": "Y", "Series": "Series", "Model": "Michaelis–Menten",
                   "Shared parameters": ["Km"], "Weighting": "1/Yfit²"}
        with self.assertRaises(FieldError) as raised:
            analyse("Global nonlinear regression", frame, options)
        self.assertEqual(raised.exception.field, "Weighting")
        independent = {"X": "X", "Y columns": ["Y"], "Grouping variables": ["Series"], "Model": "Michaelis–Menten"}
        for label in FITTED:
            with self.assertRaises(FieldError) as raised:
                analyse("Nonlinear regression", frame, {**independent, "Weighting": label})
            self.assertEqual(raised.exception.field, "Weighting")
        fit = analyse("Global nonlinear regression", frame, {**options, "Weighting": "Unweighted"})
        self.assertEqual(fit.tables["Joint fit"]["Value"]["Weighting"], "Unweighted")

    def test_missing_convergence_is_an_error_on_the_weighting_field_without_a_partial_result(self):
        frame = global_frame()
        with patch.object(fit_weights, "MAX_WEIGHT_REFITS", 1):
            with self.assertRaises(FieldError) as raised:
                global_nonlinear(frame, "X", "Y", "Straight line", "Series", shared=("Slope",), weighting="1/Yfit²")
            self.assertEqual(raised.exception.field, "Weighting")
            self.assertIn("did not converge", str(raised.exception))
            with self.assertRaises(FieldError):
                engine.nonlinear(frame, "X", "Y", "Straight line", weighting="1/Yfit²")

    def test_unknown_weighting_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "supported regression weighting"):
            global_nonlinear(global_frame(), "X", "Y", "Straight line", "Series", weighting="1/Y")


class WorkbenchTests(unittest.TestCase):
    def test_new_choices_are_listed(self):
        self.assertEqual(METHODS["Global nonlinear regression"]["Weighting"],
                         ("Unweighted", "Inverse variance (column)", "1/abs(Y)", "1/Y²", "1/abs(Yfit)", "1/Yfit²"))

    def test_legacy_global_tables_are_unchanged(self):
        result = analyse("Global nonlinear regression", global_frame(), {**LONG, "Weighting": "Unweighted"})
        for expected in LEGACY:
            if expected["name"] in {"Fit curves", "Residuals"}:
                continue
            table = result.tables[expected["name"]]
            self.assertEqual([None if pd.isna(value) else value for value in table.columns], expected["columns"])
            for row, values in zip(table.itertuples(index=False, name=None), expected["values"], strict=True):
                for found, wanted in zip(row, values, strict=True):
                    if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
                        self.assertAlmostEqual(found, wanted, delta=1e-8 * max(1., abs(wanted)))
                    else:
                        self.assertEqual(found if not pd.isna(found) else None, wanted)

    def test_dispatcher_reports_the_iteration_diagnostics_and_a_graph(self):
        for label in FITTED:
            result = analyse("Global nonlinear regression", global_frame(), {**LONG, "Weighting": label})
            report = result.tables["Joint fit"]["Value"]
            self.assertEqual(report["Weighting"], label)
            self.assertEqual(report["Inference weights"], "Final frozen weights")
            self.assertTrue(report["Weighting converged"])
            self.assertIsNotNone(result.figure)
        plain = analyse("Global nonlinear regression", global_frame(), {**LONG, "Weighting": "1/Y²"})
        self.assertNotIn("Weighting iterations", plain.tables["Joint fit"].index)

    def test_an_inactive_sd_column_does_not_block_the_fit(self):
        frame = global_frame().assign(sd=np.nan)
        for label in ("Unweighted", *OBSERVED, *FITTED):
            result = analyse("Global nonlinear regression", frame, {**LONG, "Weighting": label, "SD column": "sd"})
            self.assertEqual(result.tables["Joint fit"]["Value"]["Weighting"], label)

    def test_wide_xy_and_long_tables_agree_for_individual_observations_and_means(self):
        rng = np.random.default_rng(2)
        x = np.arange(1., 8.)
        wide = pd.DataFrame({"X": x})
        for name, intercept in (("A", 2.), ("B", 9.)):
            for replicate in (1, 2):
                wide[f"{name} [{replicate}]"] = intercept + 1.5 * x + .3 * rng.standard_normal(len(x)) + 1
        long = wide.melt(id_vars="X", var_name="Column", value_name="Y")
        long["Series"] = long["Column"].str[0]
        for label in (*OBSERVED, *FITTED):
            for replicates in ("Individual observations", "Means at each X"):
                with self.subTest(label=label, replicates=replicates):
                    common = {"Model": "Straight line", "Shared parameters": ["Slope"], "Weighting": label,
                              "Replicates": replicates, "X": "X"}
                    from_wide = analyse("Global nonlinear regression", wide, {
                        **common, "Input format": "Wide XY", "Y columns": list(wide.columns[1:])})
                    from_long = analyse("Global nonlinear regression", long, {
                        **common, "Input format": "Long table", "Y": "Y", "Series": "Series"})
                    pd.testing.assert_frame_equal(from_wide.tables["Parameters"], from_long.tables["Parameters"],
                                                  rtol=1e-6)
                    if replicates == "Means at each X":
                        means = wide.assign(A=wide[["A [1]", "A [2]"]].mean(axis=1), B=wide[["B [1]", "B [2]"]].mean(axis=1))
                        mean_long = means.melt(id_vars="X", value_vars=["A", "B"], var_name="Series", value_name="Y")
                        direct = global_nonlinear(mean_long, "X", "Y", "Straight line", "Series", shared=("Slope",),
                                                  weighting=label)
                        np.testing.assert_allclose(from_wide.tables["Parameters"]["Estimate"],
                                                   direct.parameters["Estimate"], rtol=1e-6)

    def test_saved_recipe_reloads_and_recalculates_to_the_same_tables(self):
        dataset = Dataset(global_frame())
        recipe = {**LONG, "Weighting": "1/abs(Yfit)", "Parameter intervals": "Profile likelihood"}
        dataset.analyses.append(("Global nonlinear regression", recipe))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "irls.alab"
            save_project(path, {"Data": dataset})
            method, options = load_project(path)["Data"].analyses[0]
        self.assertEqual((method, options), ("Global nonlinear regression", recipe))
        first = analyse(method, global_frame(), options)
        again = analyse(method, global_frame(), options)
        for name, table in first.tables.items():
            pd.testing.assert_frame_equal(table, again.tables[name])

    def test_exclusion_changes_the_confirmed_fit_through_the_normal_path(self):
        frame = global_frame()
        kept = frame.drop(index=3)
        options = {**LONG, "Weighting": "1/Yfit²"}
        full = analyse("Global nonlinear regression", frame, options)
        reduced = analyse("Global nonlinear regression", kept, options)
        self.assertEqual(reduced.tables["Joint fit"]["Value"]["N"], 11)
        self.assertNotEqual(full.tables["Parameters"]["Estimate"].iloc[0], reduced.tables["Parameters"]["Estimate"].iloc[0])

    def test_comparison_sheet_uses_the_weights_of_the_main_fit(self):
        frame = global_frame()
        result = analyse("Global nonlinear regression", frame,
                         {**LONG, "Weighting": "1/Yfit²", "Compare with independent fits": True})
        table = result.tables["Shared vs independent"]["Value"]
        row = ORACLE["1/Yfit²"]
        np.testing.assert_allclose(table["Independent SS"], row["comparison"]["Independent SS"], rtol=3e-5)
        expected_p = f_distribution.sf(row["comparison"]["F"], 1, 8)
        np.testing.assert_allclose(table["p"], expected_p, rtol=3e-4)


if __name__ == "__main__":
    unittest.main()
