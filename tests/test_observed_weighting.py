from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from analisi import fit_weights
from analisi import stats as engine
from analisi.data import Dataset, load_project, save_project
from analisi.global_fit import global_nonlinear
from analisi.processing import FieldError
from analisi.workbench import METHODS, analyse

X = np.arange(10.)
Y = np.array([1.2, 2.1, 2.9, 5.1, 5.9, 9.4, 10.1, 12.7, 16.0, 17.4])
LINE = {"1/abs(Y)": 0.5, "1/Y²": 1.0}
BASE = {"X": "X", "Y columns": ["Y"], "Grouping variables": [], "Model": "Straight line"}


def wls(x, y, power):
    """Closed-form weighted least squares for a straight line: residual scale |Y|**power."""
    scale = np.abs(y) ** power
    design = np.column_stack((np.ones(len(x)), x))
    z = design / scale[:, None]
    beta = np.linalg.lstsq(z, y / scale, rcond=None)[0]
    residual = y - design @ beta
    weighted = residual / scale
    covariance = np.linalg.inv(z.T @ z) * (weighted @ weighted) / (len(x) - 2)
    weights = 1 / scale**2
    mean = np.average(y, weights=weights)
    r2 = 1 - (weighted @ weighted) / np.sum(weights * (y - mean) ** 2)
    return beta, covariance, residual, weighted, r2


def line(**columns):
    return pd.DataFrame({"X": X, "Y": Y, **columns})


def fit_of(frame, weighting, **kwargs):
    return engine.nonlinear(frame, "X", "Y", "Straight line", weighting=weighting, **kwargs)["All"]


class ObservedWeightingTests(unittest.TestCase):
    def test_both_modes_match_the_closed_form_weighted_line(self):
        for label, power in LINE.items():
            with self.subTest(weighting=label):
                beta, covariance, residual, weighted, r2 = wls(X, Y, power)
                fit = fit_of(line(), label)
                np.testing.assert_allclose(fit.parameters["Estimate"], beta, rtol=2e-6)
                np.testing.assert_allclose(fit.covariance, covariance, rtol=2e-6)
                np.testing.assert_allclose(fit.parameters["SE"], np.sqrt(np.diag(covariance)), rtol=2e-6)
                np.testing.assert_allclose(fit.residuals["Residual"], residual, rtol=1e-5, atol=1e-9)
                np.testing.assert_allclose(fit.residuals["Weighted residual"], weighted, rtol=1e-5, atol=1e-9)
                d = fit.diagnostics
                self.assertEqual(d["Weighting"], label)
                self.assertAlmostEqual(d["Residual SS"], residual @ residual, delta=2e-6 * (residual @ residual))
                self.assertAlmostEqual(d["Weighted residual SS"], weighted @ weighted, delta=2e-6 * (weighted @ weighted))
                self.assertAlmostEqual(d["Residual SD"], np.sqrt(residual @ residual / 8), delta=1e-6)
                self.assertAlmostEqual(d["Weighted R²"], r2, delta=2e-6)
                total = (Y - Y.mean()) @ (Y - Y.mean())
                self.assertAlmostEqual(d["R²"], 1 - d["Residual SS"] / total, places=9)
                self.assertEqual(list(d)[:6], ["N", "df", "Weighting", "Residual SS", "Weighted residual SS", "Residual SD"])

    def test_negated_responses_flip_coefficients_and_keep_sums_and_covariance(self):
        for label in LINE:
            with self.subTest(weighting=label):
                positive, negative = fit_of(line(), label), fit_of(line().assign(Y=-Y), label)
                np.testing.assert_allclose(negative.parameters["Estimate"], -positive.parameters["Estimate"], rtol=1e-6)
                np.testing.assert_allclose(negative.residuals["Residual"], -positive.residuals["Residual"], atol=1e-9)
                np.testing.assert_allclose(negative.covariance, positive.covariance, rtol=1e-6)
                for key in ("Residual SS", "Weighted residual SS", "Weighted R²"):
                    self.assertAlmostEqual(negative.diagnostics[key], positive.diagnostics[key],
                                           delta=1e-6 * abs(positive.diagnostics[key]))

    def test_scaling_responses_by_a_million_scales_the_fit_not_the_weights(self):
        for label, power in LINE.items():
            with self.subTest(weighting=label):
                base, big = fit_of(line(), label), fit_of(line().assign(Y=Y * 1e6), label)
                np.testing.assert_allclose(big.parameters["Estimate"], base.parameters["Estimate"] * 1e6, rtol=1e-6)
                np.testing.assert_allclose(big.diagnostics["Residual SS"], base.diagnostics["Residual SS"] * 1e12, rtol=1e-6)
                # r²/|Y|**(2p): the weighted sum scales with 1e6 for 1/|Y| and stays put for 1/Y².
                np.testing.assert_allclose(big.diagnostics["Weighted residual SS"],
                                           base.diagnostics["Weighted residual SS"] * 1e12 / 1e12**power, rtol=1e-6)
                self.assertAlmostEqual(big.diagnostics["Weighted R²"], base.diagnostics["Weighted R²"], places=8)
                np.testing.assert_allclose(big.parameters["SE"], base.parameters["SE"] * 1e6, rtol=1e-6)

    def test_zero_response_on_a_complete_pair_names_the_weighting_field(self):
        for label in LINE:
            frame = line()
            frame.loc[4, "Y"] = 0.
            with self.subTest(weighting=label):
                with self.assertRaises(FieldError) as raised:
                    engine.nonlinear(frame, "X", "Y", "Straight line", weighting=label)
                self.assertEqual(raised.exception.field, "Weighting")
                with self.assertRaises(FieldError) as dispatched:
                    analyse("Nonlinear regression", frame, {**BASE, "Weighting": label})
                self.assertEqual(dispatched.exception.field, "Weighting")
        # The same zero is accepted by the other weightings.
        frame = line(sd=1.)
        frame.loc[4, "Y"] = 0.
        fit_of(frame, "Unweighted")
        fit_of(frame, "Inverse variance (column)", sigma="sd")

    def test_zero_response_with_missing_x_or_exclusion_is_filtered_before_the_check(self):
        for label in LINE:
            with self.subTest(weighting=label):
                frame = line()
                frame.loc[4, ["X", "Y"]] = [np.nan, 0.]
                expected = fit_of(line().drop(index=4), label)
                fit = fit_of(frame, label)
                np.testing.assert_allclose(fit.parameters["Estimate"], expected.parameters["Estimate"], rtol=1e-12)
                self.assertEqual(fit.diagnostics["N"], 9)
                blank = line()
                blank.loc[4, "Y"] = np.nan  # an excluded cell reaches the engine as a blank
                self.assertEqual(fit_of(blank, label).diagnostics["N"], 9)
                incomplete = line()
                incomplete.loc[4, "Y"] = 0.
                incomplete.loc[4, "X"] = np.nan
                self.assertEqual(analyse("Nonlinear regression", incomplete, {**BASE, "Weighting": label})
                                 .tables["Fit: All"].loc["N", "Value"], 9)

    def test_duplicate_index_labels_and_multiplicity_are_kept(self):
        frame = line()
        frame.index = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
        frame.loc[2, "X"] = np.nan  # drops both rows labelled 2
        for label in LINE:
            with self.subTest(weighting=label):
                fit = fit_of(frame, label)
                self.assertEqual(fit.residuals.index.tolist(), [1, 1, 3, 3, 4, 4, 5, 5])
                np.testing.assert_allclose(fit.residuals["Weighted residual"],
                                           fit.residuals["Residual"] / np.abs(fit.residuals["Observed"]) ** LINE[label])

    def test_two_groups_use_their_own_observed_responses(self):
        frame = pd.concat([line().assign(G="a"), line().assign(Y=2 * Y[::-1] + 1, G="b")], ignore_index=True)
        for label, power in LINE.items():
            with self.subTest(weighting=label):
                fits = engine.nonlinear(frame, "X", "Y", "Straight line", "G", weighting=label)
                self.assertEqual(list(fits), ["a", "b"])
                for name, y in (("a", Y), ("b", 2 * Y[::-1] + 1)):
                    np.testing.assert_allclose(fits[name].parameters["Estimate"], wls(X, y, power)[0], rtol=2e-6)
                    self.assertEqual(fits[name].diagnostics["Weighting"], label)

    def test_dispatcher_handles_several_responses_and_groups_with_matching_graph(self):
        frame = pd.concat([line().assign(G="a", Z=3 * Y + 2), line().assign(Y=Y[::-1] + 1, Z=Y + 5, G="b")],
                          ignore_index=True)
        for label, power in LINE.items():
            with self.subTest(weighting=label):
                options = {**BASE, "Y columns": ["Y", "Z"], "Grouping variables": ["G"], "Weighting": label}
                result = analyse("Nonlinear regression", frame, options)
                self.assertEqual([axes.get_title() for axes in result.figure.axes], ["Y", "Z"])
                parameters = result.tables["Parameters"].set_index(["Response variable", "Group"])
                for response, name, y in (("Y", "1 · G='a'", Y), ("Y", "2 · G='b'", Y[::-1] + 1),
                                          ("Z", "1 · G='a'", 3 * Y + 2), ("Z", "2 · G='b'", Y + 5)):
                    estimate = parameters.loc[(response, name), "Estimate"]
                    np.testing.assert_allclose(estimate, wls(X, y, power)[0], rtol=2e-6)
                fit = result.tables["Fit"].set_index(["Response variable", "Metric"])
                self.assertTrue((fit.loc[("Z", "Weighting"), "Value"] == label).all())
                # The drawn curves come from the tabulated estimates.
                axes = result.figure.axes[0]
                a = parameters.loc[("Y", "1 · G='a'"), "Estimate"].to_numpy()
                curve = axes.lines[0].get_xydata()
                np.testing.assert_allclose(curve[:, 1], a[0] + a[1] * curve[:, 0], rtol=1e-9)

    def test_zero_in_one_response_keeps_the_field_and_names_the_response(self):
        frame = line(Z=Y + 1)
        frame.loc[3, "Z"] = 0.
        with self.assertRaises(FieldError) as raised:
            analyse("Nonlinear regression", frame, {**BASE, "Y columns": ["Y", "Z"], "Weighting": "1/Y²"})
        self.assertEqual(raised.exception.field, "Weighting")
        self.assertIn("Z", str(raised.exception))

    def test_sd_column_is_only_read_by_inverse_variance(self):
        for label in LINE:
            reference = fit_of(line(), label)
            for sd in ("missing", "X"):
                with self.subTest(weighting=label, sd=sd):
                    fit = fit_of(line(), label, sigma=sd)
                    np.testing.assert_allclose(fit.parameters["Estimate"], reference.parameters["Estimate"])
            options = {**BASE, "Weighting": label, "SD column": "bad"}
            self.assertIn("Fit: All", analyse("Nonlinear regression", line(bad=0.), options).tables)
        with self.assertRaises(ValueError):
            analyse("Nonlinear regression", line(), {**BASE, "Weighting": "Inverse variance (column)"})
        with self.assertRaisesRegex(ValueError, "standard deviations"):
            fit_of(line(), "Inverse variance (column)")

    def test_previous_weightings_keep_tables_and_ignore_the_unit_of_the_sd(self):
        frame = line(sd=np.linspace(1, 3, 10))
        legacy = {**BASE}  # recipes saved before this version have no Weighting key
        old = analyse("Nonlinear regression", frame, legacy)
        explicit = analyse("Nonlinear regression", frame, {**legacy, "Weighting": "Unweighted"})
        for name in old.tables:
            pd.testing.assert_frame_equal(old.tables[name], explicit.tables[name])
        self.assertNotIn("Weighted R²", old.tables["Fit: All"].index)
        options = {**legacy, "Weighting": "Inverse variance (column)", "SD column": "sd"}
        base = analyse("Nonlinear regression", frame, options)
        converted = analyse("Nonlinear regression", frame.assign(sd=frame["sd"] * 1e9), options)
        np.testing.assert_allclose(
            base.tables["Parameters: All"][["Estimate", "SE"]], converted.tables["Parameters: All"][["Estimate", "SE"]],
            rtol=1e-6)
        self.assertEqual(base.tables["Fit: All"].loc["Weighting", "Value"], "Inverse variance (column)")

    def test_choices_are_listed_for_the_independent_and_global_fits_but_not_for_the_model_comparison(self):
        choices = METHODS["Nonlinear regression"]["Weighting"]
        self.assertEqual(choices, ("Unweighted", "Inverse variance (column)", "1/abs(Y)", "1/Y²",
                                   "1/abs(Yfit)", "1/Yfit²"))
        self.assertEqual(engine.FIT_WEIGHTINGS, ("Unweighted", "Inverse variance (column)"))
        self.assertEqual(fit_weights.NONLINEAR_WEIGHTINGS, choices)
        self.assertEqual(METHODS["Compare nonlinear models"]["Weighting"], engine.FIT_WEIGHTINGS)
        self.assertEqual(METHODS["Global nonlinear regression"]["Weighting"], fit_weights.GLOBAL_WEIGHTINGS)
        self.assertEqual(fit_weights.GLOBAL_WEIGHTINGS, choices)
        x = np.tile(np.linspace(1, 10, 12), 2)
        frame = pd.DataFrame({"X": x, "Y": 1 + np.exp(-x / 3), "S": np.repeat(["a", "b"], 12)})
        for label in (*LINE, *fit_weights.FITTED_WEIGHTINGS):
            with self.assertRaisesRegex(ValueError, "supported regression weighting"):
                engine.compare_nonlinear(frame, "X", "Y", "Stimulation (standard slope)",
                                         "Stimulation (variable slope)", weighting=label)
        with self.assertRaisesRegex(ValueError, "supported regression weighting"):
            global_nonlinear(frame, "X", "Y", "One-phase decay", "S", weighting="1/Y")

    def test_source_columns_are_not_changed_and_no_helper_columns_are_added(self):
        frame = line(sd=1.)
        before = frame.copy()
        for label in LINE:
            fit = fit_of(frame, label)
            self.assertEqual(list(fit.data.columns), ["X", "Y"])
        pd.testing.assert_frame_equal(frame, before)

    def test_choice_survives_a_saved_project_and_recalculates_to_the_same_tables(self):
        stale = {**BASE, "Weighting": "1/Y²", "SD column": "gone"}  # a leftover SD column is ignored
        dataset = Dataset(line())
        dataset.analyses.append(("Nonlinear regression", stale))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "weights.alab"
            save_project(path, {"Data": dataset})
            method, options = load_project(path)["Data"].analyses[0]
        self.assertEqual((method, options), ("Nonlinear regression", stale))
        first = analyse(method, line(), options)
        again = analyse(method, line(), options)
        for name in first.tables:
            pd.testing.assert_frame_equal(first.tables[name], again.tables[name])
        self.assertEqual(first.tables["Fit: All"].loc["Weighting", "Value"], "1/Y²")


if __name__ == "__main__":
    unittest.main()
