"""Fit custom equation (0.61): numerical agreement with independent oracles, validation and recipe handling."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from analisi import curve_models, custom_fit
from analisi.custom_fit import CUSTOM_EQUATION, check_options
from analisi.data import Dataset, load_project, save_project
from analisi.field_error import FieldError
from analisi.workbench import GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "custom_equations"
ORACLE = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
LINE, DECAY, MISSING, GROUPED, RELATIVE_SD, TINY = (
    pd.read_csv(DATA / name) for name in ("line.csv", "decay.csv", "missing.csv", "grouped.csv",
                                          "relative-sd.csv", "tiny-coefficient.csv"))


def row(name, start, lower=None, upper=None, fixed=False):
    return {"name": name, "start": start, "lower": lower, "upper": upper, "fixed": fixed}


def recipe(**extra):
    return {"X": "X", "Y": "Y", "Group": None, "Equation": "A+B*X", "Parameters": [row("A", 1), row("B", 1)],
            "Weighting": "Unweighted", "SD column": None, "Confidence level (%)": 95.0, "Curve points": 201, **extra}


def run(frame=LINE, **extra):
    return analyse(CUSTOM_EQUATION, frame, recipe(**extra))


def rejected(test, field, frame=LINE, **extra):
    with test.assertRaises(FieldError) as caught:
        run(frame, **extra)
    test.assertEqual(caught.exception.field, field, str(caught.exception))
    return str(caught.exception)


STRICT = {"rtol": 2e-5, "atol": 0}


class ScaleInvarianceTests(unittest.TestCase):
    """Units must not change the answer: SD column factor, response units and the size of a coefficient.

    The tolerances are strict on purpose: an absolute tolerance such as atol=1e-8 would hide an error on a
    coefficient of order 1e-9.
    """

    WEIGHTED = {"Weighting": "Inverse variance (column)", "SD column": "SD"}

    def relative(self, factor, **extra):
        return run(RELATIVE_SD.assign(SD=RELATIVE_SD.SD * factor), **self.WEIGHTED, **extra)

    def test_relative_sd_common_factor_keeps_the_fit(self):
        oracle = ORACLE["relative_sd"]
        half = stats.t.ppf(.975, len(RELATIVE_SD) - 2) * np.asarray(oracle["SE"])
        for factor in (1.0, 1e8, 1e-8, 1e-150, 1e150):
            with self.subTest(factor=factor):
                result = self.relative(factor)
                table, fit = result.tables["Parameters: All"], result.tables["Fit: All"]["Value"]
                np.testing.assert_allclose(table["Estimate"], oracle["beta"], **STRICT)
                np.testing.assert_allclose(table["SE"], oracle["SE"], **STRICT)
                np.testing.assert_allclose(table["CI lower"], np.asarray(oracle["beta"]) - half, **STRICT)
                np.testing.assert_allclose(table["CI upper"], np.asarray(oracle["beta"]) + half, **STRICT)
                np.testing.assert_allclose(float(fit["Residual SS"]), oracle["Residual SS"], **STRICT)
                # Weighted residual SS follows the SD as given: it changes by 1 / factor**2, by design.
                np.testing.assert_allclose(float(fit["Weighted residual SS"]) * factor ** 2,
                                           oracle["Weighted residual SS"], **STRICT)

    def test_relative_sd_common_factor_keeps_residuals_and_curve(self):
        reference, scaled = self.relative(1.0), self.relative(1e8)
        for name in ("Residuals: All", "Curve: All"):
            for column in ("Predicted", "Residual"):
                if column in reference.tables[name]:
                    np.testing.assert_allclose(scaled.tables[name][column], reference.tables[name][column], **STRICT)

    def test_relative_sd_factor_also_holds_per_group_and_with_a_nonlinear_equation(self):
        grouped = GROUPED.assign(SD=1 + GROUPED.index % 3)
        options = {"Group": "Group", **self.WEIGHTED}
        base, scaled = run(grouped, **options), run(grouped.assign(SD=grouped.SD * 1e8), **options)
        for name in base.tables:
            if name.startswith("Parameters"):
                np.testing.assert_allclose(scaled.tables[name][["Estimate", "SE"]], base.tables[name][["Estimate", "SE"]],
                                           rtol=2e-5)
        exponential = {"Equation": "A*exp(-B*X)", "Parameters": [row("A", 5), row("B", .3)], **self.WEIGHTED}
        weights = DECAY.assign(SD=0.5 + DECAY.Y.abs() * .1)
        first, again = run(weights, **exponential), run(weights.assign(SD=weights.SD * 1e-8), **exponential)
        np.testing.assert_allclose(again.tables["Parameters: All"][["Estimate", "SE"]],
                                   first.tables["Parameters: All"][["Estimate", "SE"]], rtol=2e-5)

    def test_a_response_that_is_zero_everywhere_is_fitted_for_any_sd_factor(self):
        # The SD normalisation must not fall back to a factor that depends on the typed SD unit.
        zero = pd.read_csv(DATA / "zero.csv")
        self.assertTrue((zero.Y == 0).all())
        for equation, names in (("A*X", "A"), ("A+B*X", "AB")):
            for factor in (1.0, 1e8, 1e-8, 1e150):
                with self.subTest(equation=equation, factor=factor):
                    result = run(zero.assign(SD=zero.SD * factor), Equation=equation,
                                 Parameters=[row(name, 1.0) for name in names], **self.WEIGHTED)
                    table = result.tables["Parameters: All"]
                    np.testing.assert_allclose(table["Estimate"], np.zeros(len(names)), rtol=0, atol=1e-10)
                    self.assertLess(abs(float(result.tables["Fit: All"].loc["Residual SS", "Value"])), 1e-18)
                    self.assertEqual(list(table["Status"]), ["Free"] * len(names))

    def test_zero_response_with_unequal_sd_matches_the_closed_form(self):
        zero = pd.read_csv(DATA / "zero.csv").assign(SD=lambda f: 1 + f.X % 3)
        for factor in (1.0, 1e8):
            result = run(zero.assign(SD=zero.SD * factor), Equation="A*X", Parameters=[row("A", 3.0)], **self.WEIGHTED)
            self.assertAlmostEqual(float(result.tables["Parameters: All"].loc["A", "Estimate"]), 0.0, delta=1e-10)

    def small(self, start, units, lower=0.0, upper=1e-8, frame=TINY):
        options = {"Equation": "A*X", "Parameters": [row("A", start * units, lower * units, upper * units)]}
        result = run(frame.assign(Y=frame.Y * units), **options)
        return result.tables["Parameters: All"].loc["A"], result

    def test_tiny_coefficient_moves_from_its_start_and_matches_ols(self):
        oracle = ORACLE["tiny_coefficient"]
        half = stats.t.ppf(.975, len(TINY) - 1) * oracle["SE"]
        for units in (1.0, 1e9, 1e-3, 1e12):
            for start in (1e-9, oracle["estimate"], 5e-9):
                with self.subTest(units=units, start=start):
                    parameter, _ = self.small(start, units)
                    self.assertEqual(parameter["Status"], "Free", parameter.to_dict())
                    np.testing.assert_allclose(parameter["Estimate"] / units, oracle["estimate"], rtol=2e-5, atol=0)
                    np.testing.assert_allclose(parameter["SE"] / units, oracle["SE"], rtol=1e-4, atol=0)
                    np.testing.assert_allclose(parameter["CI lower"] / units, oracle["estimate"] - half, rtol=1e-4, atol=0)
                    np.testing.assert_allclose(parameter["CI upper"] / units, oracle["estimate"] + half, rtol=1e-4, atol=0)

    def test_a_limit_that_is_really_active_is_still_reported_at_bound(self):
        for units in (1.0, 1e9):
            with self.subTest(units=units, limit="upper, tiny scale"):
                parameter, result = self.small(1e-9, units, upper=2e-9)
                self.assertEqual(parameter["Status"], "At bound")
                np.testing.assert_allclose(parameter["Estimate"] / units, 2e-9, rtol=1e-6, atol=0)
                self.assertTrue(np.isnan(parameter["SE"]) and np.isnan(parameter["CI lower"]))
                self.assertIn("upper limit", str(result.tables["Fit: All"].loc["Note", "Value"]))
        # A lower limit of exactly zero reached from a start of order one.
        negative = TINY.assign(Y=-TINY.Y)
        for units in (1.0, 1e-6):
            with self.subTest(units=units, limit="lower zero"):
                parameter, _ = self.small(1.0, units, lower=0.0, upper=1e6, frame=negative)
                self.assertEqual(parameter["Status"], "At bound")
                self.assertTrue(np.isnan(parameter["SE"]))
                self.assertLess(abs(parameter["Estimate"]), 1e-8 * max(1.0, units))

    def test_a_coefficient_close_to_a_limit_but_not_on_it_is_free(self):
        # Interior estimate 3e-9 with the limit at 3.1e-9: 3% away, far beyond any tolerance.
        parameter, _ = self.small(1e-9, 1.0, upper=3.1e-9)
        self.assertEqual(parameter["Status"], "Free")
        self.assertTrue(np.isfinite(parameter["SE"]))


class NumericTests(unittest.TestCase):
    def test_line_matches_the_independent_oracle(self):
        result = run()
        parameters = result.tables["Parameters: All"]
        np.testing.assert_allclose(parameters["Estimate"], ORACLE["line"]["beta"], rtol=2e-6)
        np.testing.assert_allclose(parameters["SE"], np.sqrt(np.diag(ORACLE["line"]["covariance"])), rtol=5e-5)
        self.assertEqual(list(parameters["Status"]), ["Free", "Free"])
        self.assertEqual(list(result.tables), ["Parameters: All", "Fit: All", "Residuals: All", "Curve: All"])
        self.assertEqual(len(result.tables["Curve: All"]), 201)
        self.assertEqual(result.tables["Fit: All"].loc["Converged", "Value"], True)
        self.assertEqual(result.tables["Fit: All"].loc["Skipped rows", "Value"], 0)

    def test_weighted_fit_and_scale_invariance(self):
        weighted = run(**{"Weighting": "Inverse variance (column)", "SD column": "SD"})
        scaled = run(LINE.assign(SD=LINE.SD * 37.5), **{"Weighting": "Inverse variance (column)", "SD column": "SD"})
        for column in ("Estimate", "SE", "CI lower", "CI upper"):
            np.testing.assert_allclose(weighted.tables["Parameters: All"][column],
                                       scaled.tables["Parameters: All"][column], rtol=1e-6)
        np.testing.assert_allclose(weighted.tables["Parameters: All"]["Estimate"], ORACLE["weighted"]["beta"], rtol=2e-6)
        self.assertAlmostEqual(weighted.tables["Fit: All"].loc["Weighted residual SS", "Value"],
                               ORACLE["weighted"]["WSSE"], places=6)

    def test_fixed_coefficient_and_all_fixed(self):
        fixed = run(Parameters=[row("A", 1, fixed=True), row("B", 1)])
        table = fixed.tables["Parameters: All"]
        self.assertEqual(list(table["Status"]), ["Fixed", "Free"])
        self.assertTrue(np.isnan(table.loc["A", ["SE", "CI lower", "CI upper"]].astype(float)).all())
        self.assertEqual(fixed.tables["Fit: All"].loc["df", "Value"], 7)
        both = run(Parameters=[row("A", 1, fixed=True), row("B", 2, fixed=True)])
        self.assertEqual(both.tables["Fit: All"].loc["df", "Value"], 8)
        self.assertEqual(both.tables["Fit: All"].loc["Free parameters", "Value"], 0)
        self.assertEqual(both.tables["Fit: All"].loc["Converged", "Value"], "Not applicable")
        self.assertTrue(both.tables["Parameters: All"][["SE", "CI lower", "CI upper"]].isna().all().all())

    def test_constant_model_is_a_mean(self):
        result = run(Equation="A", Parameters=[row("A", 0)])
        self.assertAlmostEqual(result.tables["Parameters: All"].loc["A", "Estimate"], LINE.Y.mean(), places=8)
        self.assertEqual(result.tables["Fit: All"].loc["df", "Value"], 7)

    def test_nonlinear_decay_with_limits(self):
        result = run(DECAY, Equation="A*exp(-K*X)+C",
                     Parameters=[row("A", 8, lower=0), row("K", .7, lower=0), row("C", 2, lower=0)])
        table = result.tables["Parameters: All"]
        np.testing.assert_allclose(table["Estimate"], ORACLE["decay"]["beta"], rtol=2e-5)
        np.testing.assert_allclose(table["SE"], np.sqrt(np.diag(ORACLE["decay"]["covariance"])), rtol=1e-4)

    def test_curve_uses_the_reported_estimates(self):
        result = run(**{"Curve points": 50})
        a, b = result.tables["Parameters: All"]["Estimate"]
        curve = result.tables["Curve: All"]
        np.testing.assert_allclose(curve["Predicted"], a + b * curve["X"], rtol=1e-12)
        self.assertEqual((curve["X"].iloc[0], curve["X"].iloc[-1]), (LINE.X.min(), LINE.X.max()))

    def test_groups_keep_first_appearance_order(self):
        result = run(GROUPED, Group="Group")
        self.assertEqual([k for k in result.tables if k.startswith("Parameters")],
                         ["Parameters: Control", "Parameters: Treated"])
        np.testing.assert_allclose(result.tables["Parameters: Treated"]["Estimate"],
                                   np.asarray(ORACLE["line"]["beta"]) * 1.5 + [2, 0], rtol=2e-6)

    def test_missing_cells_are_excluded_not_zeros(self):
        result = run(MISSING)
        self.assertEqual(result.tables["Residuals: All"].index.tolist(), [0, 1, 2, 5, 6, 7, 8, 9])
        self.assertEqual(result.tables["Fit: All"].loc["Skipped rows", "Value"], 2)
        self.assertEqual(result.tables["Residuals: All"].index.name, "Source row")

    def test_duplicate_x_and_duplicate_index_are_not_errors(self):
        frame = pd.DataFrame({"X": [1., 1, 2, 2, 3], "Y": [1., 1.2, 2.1, 1.9, 3.2]}, index=[4, 4, 5, 5, 6])
        result = run(frame)
        self.assertEqual(result.tables["Residuals: All"].index.tolist(), [4, 4, 5, 5, 6])

    def test_reducing_coefficients_leaves_no_old_rows(self):
        wide = run()
        narrow = run(Equation="A", Parameters=[row("A", 1)])
        self.assertEqual(len(wide.tables["Parameters: All"]), 2)
        self.assertEqual(list(narrow.tables["Parameters: All"].index), ["A"])
        self.assertEqual(len(narrow.figure.axes[0].lines), 1)


class IdentifiabilityTests(unittest.TestCase):
    def test_collinear_coefficients_are_an_error_on_parameters(self):
        message = rejected(self, "Parameters", Equation="A+B*X+C*X", Parameters=[row("A", 1), row("B", 1), row("C", 1)])
        self.assertIn("identifiable", message)

    def test_single_distinct_x_cannot_fit_a_line(self):
        rejected(self, "Parameters", pd.DataFrame({"X": [2.] * 5, "Y": [1., 2, 3, 4, 5]}))

    def test_too_few_rows(self):
        rejected(self, "Parameters", LINE.head(2), Equation="A+B*X+C*X**2",
                 Parameters=[row("A", 1), row("B", 1), row("C", 1)])

    def test_coefficient_at_a_limit_keeps_the_estimate_without_inference(self):
        result = run(Parameters=[row("A", 1), row("B", .5, lower=0, upper=1)])
        table = result.tables["Parameters: All"]
        self.assertEqual(table.loc["B", "Status"], "At bound")
        self.assertAlmostEqual(table.loc["B", "Estimate"], 1.0, places=6)
        self.assertTrue(np.isnan(table.loc["B", ["SE", "CI lower", "CI upper"]].astype(float)).all())
        self.assertTrue(np.isfinite(table.loc["A", "SE"]))
        self.assertIn("upper limit", result.tables["Fit: All"].loc["Note", "Value"])

    def test_not_converging_is_an_error_not_a_result(self):
        with patch.object(custom_fit, "MAX_EVALUATIONS", 1):
            rejected(self, "Parameters", DECAY, Equation="A*exp(-K*X)+C",
                     Parameters=[row("A", 3), row("K", 3), row("C", 0)])


class ValidationTests(unittest.TestCase):
    def test_equation_errors(self):
        rejected(self, "Equation", Equation="X.__class__")
        rejected(self, "Equation", Equation="A+B*X+C")
        rejected(self, "Equation", Equation="A+B*log(X)")  # X ≤ 0 in the data
        rejected(self, "Equation", Equation="")

    def test_parameter_errors(self):
        rejected(self, "Parameters", Parameters=[row("A", 1), row("A", 2)])
        rejected(self, "Parameters", Parameters=[row("A", 2, lower=3), row("B", 1)])
        rejected(self, "Parameters", Parameters=[row("A", 1, lower=2, upper=1), row("B", 1)])
        rejected(self, "Parameters", Parameters=[row("A", float("inf")), row("B", 1)])
        rejected(self, "Parameters", Parameters=[row("A", float("nan")), row("B", 1)])
        rejected(self, "Parameters", Parameters=[row("A", True), row("B", 1)])
        rejected(self, "Parameters", Parameters=[row("A", 1), row("B", 1, upper=float("inf"))])
        rejected(self, "Parameters", Parameters=[row("A", 1), row("B", 1), row("X", 1)])
        rejected(self, "Parameters", Parameters=[row("A", 1), row("B", 1), row("C", 1)])  # C unused
        rejected(self, "Parameters", Parameters="A,B")
        rejected(self, "Parameters", Parameters=[row("A", 1, fixed=True, lower=2), row("B", 1)])

    def test_options(self):
        rejected(self, "Confidence level (%)", **{"Confidence level (%)": 100})
        rejected(self, "Confidence level (%)", **{"Confidence level (%)": 0})
        rejected(self, "Curve points", **{"Curve points": 19})
        rejected(self, "Curve points", **{"Curve points": 10_001})
        rejected(self, "Curve points", **{"Curve points": 100.5})
        rejected(self, "Weighting", Weighting="1/Y")
        rejected(self, "SD column", Weighting="Inverse variance (column)")
        rejected(self, "X", X="missing")
        rejected(self, "Y", Y="X")
        rejected(self, "Group", Group="X")

    def test_non_finite_curve_points_name_the_field_before_any_conversion(self):
        # int(nan) raises ValueError and int(inf) OverflowError, neither of which carries a field.
        for value in (float("nan"), float("inf"), -float("inf"), np.float64("nan"), np.float64("inf")):
            with self.subTest(value=value):
                message = rejected(self, "Curve points", **{"Curve points": value})
                self.assertIn("whole number", message)
                with self.assertRaises(FieldError) as caught:
                    check_options(LINE, recipe(**{"Curve points": value}))
                self.assertEqual(caught.exception.field, "Curve points")
        self.assertEqual(len(run(**{"Curve points": 20.0}).tables["Curve: All"]), 20)

    def test_text_and_infinite_values_are_rejected_not_imputed(self):
        rejected(self, "X", LINE.assign(X=["a"] + list(LINE.X[1:])))
        rejected(self, "Y", LINE.assign(Y=LINE.Y.astype(object).where(LINE.index != 2, "n/a")))
        rejected(self, "Y", LINE.assign(Y=[np.inf] + list(LINE.Y[1:])))
        rejected(self, "X", LINE.assign(X=[-np.inf] + list(LINE.X[1:])))

    def test_sd_rules(self):
        weighted = {"Weighting": "Inverse variance (column)", "SD column": "SD"}
        rejected(self, "SD column", LINE.assign(SD=[0.] + list(LINE.SD[1:])), **weighted)
        rejected(self, "SD column", LINE.assign(SD=[-1.] + list(LINE.SD[1:])), **weighted)
        rejected(self, "SD column", LINE.assign(SD=[np.inf] + list(LINE.SD[1:])), **weighted)
        rejected(self, "SD column", LINE.assign(SD=["x"] + list(LINE.SD[1:])), **weighted)
        empty = run(LINE.assign(SD=[np.nan] + list(LINE.SD[1:])), **weighted)
        self.assertEqual(empty.tables["Fit: All"].loc["Skipped rows", "Value"], 1)
        self.assertEqual(len(empty.tables["Residuals: All"]), 7)
        # An SD of zero on a row without Y is not used and not an error.
        run(LINE.assign(SD=[0.] + list(LINE.SD[1:]), Y=[np.nan] + list(LINE.Y[1:])), **weighted)

    def test_group_rules(self):
        rejected(self, "Group", GROUPED.assign(Group=[1, "1"] + ["x"] * 14).astype({"Group": object}), Group="Group")
        rejected(self, "Group", GROUPED.assign(Group=range(16)), Group="Group")  # more than twelve groups
        frame = GROUPED.assign(Group=GROUPED.Group.where(GROUPED.index % 2 == 0))
        self.assertEqual(len([k for k in run(frame, Group="Group").tables if k.startswith("Parameters")]), 2)
        empty = GROUPED.assign(Y=GROUPED.Y.where(GROUPED.Group != "Treated"))
        rejected(self, "Y", empty, Group="Group")

    def test_check_options_never_fits(self):
        with patch.object(custom_fit, "least_squares", side_effect=AssertionError("fit started")):
            check_options(LINE, recipe())
        with self.assertRaises(FieldError) as caught:
            check_options(LINE, recipe(Equation="A+B*log(X)"))
        self.assertEqual(caught.exception.field, "Equation")


class RecipeTests(unittest.TestCase):
    def test_method_is_listed_once_in_regression_and_curves(self):
        self.assertEqual(GROUPS["Regression and Curves"].count(CUSTOM_EQUATION), 1)
        self.assertIn(CUSTOM_EQUATION, METHODS)

    def test_catalog_is_not_modified(self):
        before = dict(curve_models.MODELS)
        run(Equation="A*X", Parameters=[row("A", 1)])
        self.assertEqual(before, curve_models.MODELS)
        self.assertNotIn("A*X", curve_models.MODELS)

    def test_two_projects_with_the_same_coefficient_names_do_not_mix(self):
        first = run(Equation="A+B*X")
        second = run(Equation="A*exp(B*X)", Parameters=[row("A", 1), row("B", .1)])
        again = run(Equation="A+B*X")
        self.assertFalse(np.allclose(first.tables["Parameters: All"]["Estimate"],
                                     second.tables["Parameters: All"]["Estimate"]))
        pd.testing.assert_frame_equal(first.tables["Parameters: All"], again.tables["Parameters: All"])

    def test_recipe_round_trips_through_alab_as_plain_json(self):
        options = recipe(Parameters=[row("A", 1, fixed=True), row("B", 1, lower=-5, upper=5)])
        dataset = Dataset(LINE.copy())
        dataset.analyses.append((CUSTOM_EQUATION, options))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "p.alab"
            save_project(path, {"T": dataset})
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("<", json.dumps(json.loads(text)["tables"][0]["analyses"]).replace("<=", ""))
            loaded = load_project(path)
        method, restored = list(loaded.values())[0].analyses[0] if isinstance(loaded, dict) else (None, None)
        self.assertEqual((method, restored), (CUSTOM_EQUATION, options))
        np.testing.assert_allclose(analyse(method, LINE, restored).tables["Parameters: All"]["Estimate"],
                                   analyse(method, LINE, options).tables["Parameters: All"]["Estimate"])


if __name__ == "__main__":
    unittest.main()
