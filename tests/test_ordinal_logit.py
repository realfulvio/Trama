"""Ordinal logistic regression engine: an analytic oracle, an independent Newton fit, orders, budgets and failures."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.special import expit
from scipy.stats import norm

from analisi import models, ordinal_logit as ol
from analisi.field_error import FieldError
from analisi.workbench import GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "ordinal_logit"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
ORDER = ["Low", "Medium", "High"]


def stages():
    return pd.read_csv(DATA / "stages.csv")


def recipe(**overrides):
    base = {"Response": "Stage", "Predictors": ["Treatment"], "Categorical predictors": [],
            "Category order": ORDER, "Confidence level (%)": 95.0, "Profiles": [], "Show graph": False}
    return {**base, **overrides}


def run(frame=None, **overrides):
    return analyse(ol.ORDINAL_LOGIT, stages() if frame is None else frame, recipe(**overrides))


def failure(frame=None, **overrides):
    with unittest.TestCase().assertRaises(FieldError) as caught:
        run(frame, **overrides)
    return caught.exception


def simulated(rows=300, seed=7, levels=4):
    """Ordinal data from a known proportional-odds model with two continuous predictors and one categorical."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({"Dose": rng.normal(size=rows), "Age": rng.uniform(20, 70, size=rows),
                          "Site": rng.choice(["north", "south", "east"], size=rows)})
    eta = 0.9 * frame["Dose"] - 0.03 * (frame["Age"] - 45) + frame["Site"].map({"north": 0, "south": 0.7, "east": -0.4})
    cuts = np.array([-1.2, 0.1, 1.4][:levels - 1])
    latent = eta.to_numpy() + rng.logistic(size=rows)
    frame["Grade"] = np.searchsorted(cuts, latent) + 1
    return frame


def newton_reference(codes, design):
    """Maximum likelihood by Newton's method on the thresholds and slopes, with an analytic gradient.

    The Hessian is a central difference of the gradient, so nothing of the engine (statsmodels, standardization or
    BFGS) is shared with it.
    """
    levels, k = int(codes.max()) + 1, design.shape[1]

    def parts(params):
        beta, theta = params[:k], params[k:]
        eta = design @ beta
        upper = np.where(codes < levels - 1, theta[np.minimum(codes, levels - 2)] - eta, np.inf)
        lower = np.where(codes > 0, theta[np.maximum(codes - 1, 0)] - eta, -np.inf)
        return eta, expit(upper), expit(lower)

    def loglike(params):
        _, high, low = parts(params)
        with np.errstate(all="ignore"):
            return float(np.log(high - low).sum())

    def gradient(params):
        eta, high, low = parts(params)
        mass = high - low
        slope_high, slope_low = high * (1 - high), low * (1 - low)
        grad = np.zeros(len(params))
        grad[:k] = design.T @ (-(slope_high - slope_low) / mass)
        for j in range(levels - 1):
            grad[k + j] += (slope_high / mass)[codes == j].sum() - (slope_low / mass)[codes == j + 1].sum()
        return grad

    marginal = np.bincount(codes, minlength=levels).cumsum()[:-1] / len(codes)
    params = np.concatenate([np.zeros(k), np.log(marginal / (1 - marginal))])
    for _ in range(100):
        grad = gradient(params)
        hessian = np.empty((len(params), len(params)))
        for index in range(len(params)):
            step = np.zeros(len(params))
            step[index] = 1e-5
            hessian[index] = (gradient(params + step) - gradient(params - step)) / 2e-5
        hessian = (hessian + hessian.T) / 2
        move = np.linalg.solve(hessian, -grad)
        size, base = 1.0, loglike(params)
        while size > 1e-6:
            trial = loglike(params + size * move)
            if np.isfinite(trial) and trial >= base - 1e-12:
                break
            size /= 2
        params = params + size * move
        if np.abs(grad).max() < 1e-10:
            break
    step = np.zeros(len(params))
    hessian = np.empty((len(params), len(params)))
    for index in range(len(params)):
        step[:] = 0
        step[index] = 1e-5
        hessian[index] = (gradient(params + step) - gradient(params - step)) / 2e-5
    covariance = np.linalg.inv(-(hessian + hessian.T) / 2)
    return params, covariance, loglike(params)


class OracleTests(unittest.TestCase):
    def test_saturated_two_group_fit_matches_the_analytic_values(self):
        result = run()
        coefficient = result.tables["Coefficients"].loc["Treatment"]
        np.testing.assert_allclose(coefficient["Estimate"], EXPECTED["coeff"], rtol=5e-8)
        np.testing.assert_allclose(coefficient["Estimate"], np.log(2), rtol=5e-8)
        np.testing.assert_allclose(coefficient["SE"], EXPECTED["se"], rtol=5e-6)
        np.testing.assert_allclose(coefficient["p"], EXPECTED["p"], rtol=5e-5)
        np.testing.assert_allclose(coefficient["Odds ratio"], EXPECTED["odds_ratio"], rtol=5e-8)
        np.testing.assert_allclose([coefficient["OR lower"], coefficient["OR upper"]], EXPECTED["odds_ci"], rtol=5e-6)
        np.testing.assert_allclose(result.tables["Thresholds"]["Estimate"], EXPECTED["thresholds"], rtol=5e-8)
        fit = result.tables["Model fit"].iloc[0]
        self.assertEqual((fit["N"], fit["Incomplete rows"]), (EXPECTED["n"], 0))
        np.testing.assert_allclose(fit["Log likelihood"], EXPECTED["ll"], rtol=1e-9)
        np.testing.assert_allclose(fit["AIC"], EXPECTED["aic"], rtol=1e-9)
        self.assertEqual(fit["Confidence level (%)"], 95.0)

    def test_fitted_probabilities_are_the_group_proportions_in_the_declared_order(self):
        table = run().tables["Fitted probabilities"]
        self.assertEqual(list(table.columns), ["Source row", "Observed", "Predicted", "P(Low)", "P(Medium)", "P(High)"])
        frame = stages()
        for treatment, expected in zip((0, 1), EXPECTED["probabilities"]):
            rows = table[(frame["Treatment"] == treatment).to_numpy()]
            np.testing.assert_allclose(rows[["P(Low)", "P(Medium)", "P(High)"]].to_numpy(),
                                       np.tile(expected, (len(rows), 1)), atol=5e-9)
        np.testing.assert_allclose(table[["P(Low)", "P(Medium)", "P(High)"]].sum(axis=1), 1, atol=1e-12)
        self.assertEqual(list(table.index[:3]), [1, 2, 3])

    def test_tables_and_their_order_follow_the_contract(self):
        tables = run().tables
        self.assertEqual(list(tables), ["Coefficients", "Thresholds", "Model fit", "Fitted probabilities"])
        self.assertEqual(list(tables["Coefficients"].columns),
                         ["Estimate", "SE", "p", "Odds ratio", "OR lower", "OR upper"])
        self.assertEqual(list(tables["Thresholds"].columns), ["Lower category", "Upper category", "Estimate"])
        self.assertEqual(list(tables["Thresholds"].index), [1, 2])
        self.assertEqual(list(tables["Thresholds"]["Lower category"]), ["Low", "Medium"])
        self.assertEqual(list(tables["Thresholds"]["Upper category"]), ["Medium", "High"])
        self.assertEqual(list(tables["Model fit"].columns),
                         ["N", "Incomplete rows", "Log likelihood", "AIC", "Confidence level (%)"])
        self.assertTrue(np.all(np.diff(tables["Thresholds"]["Estimate"]) > 0))

    def test_confidence_level_changes_only_the_interval(self):
        base, wide = run().tables["Coefficients"].iloc[0], run(**{"Confidence level (%)": 99.0}).tables["Coefficients"].iloc[0]
        np.testing.assert_allclose(wide["Estimate"], base["Estimate"], rtol=1e-12)
        z = norm.ppf(0.995)
        np.testing.assert_allclose([wide["OR lower"], wide["OR upper"]],
                                   np.exp(wide["Estimate"] + np.array([-z, z]) * wide["SE"]), rtol=1e-10)
        self.assertGreater(wide["OR upper"], base["OR upper"])


class IndependentFitTests(unittest.TestCase):
    def check_against_newton(self, frame, response, predictors, categorical, levels):
        result = run(frame, Response=response, Predictors=predictors, **{"Categorical predictors": categorical,
                                                                         "Category order": levels})
        prepared = ol.check_options(frame, recipe(Response=response, Predictors=predictors,
                                                  **{"Categorical predictors": categorical, "Category order": levels}))
        params, covariance, loglike = newton_reference(prepared.codes, prepared.design)
        k = len(prepared.terms)
        coefficients = result.tables["Coefficients"]
        np.testing.assert_allclose(coefficients["Estimate"], params[:k], rtol=1e-6, atol=1e-7)
        np.testing.assert_allclose(coefficients["SE"], np.sqrt(np.diag(covariance)[:k]), rtol=1e-4)
        np.testing.assert_allclose(result.tables["Thresholds"]["Estimate"], params[k:], rtol=1e-6, atol=1e-7)
        np.testing.assert_allclose(result.tables["Model fit"]["Log likelihood"].iloc[0], loglike, rtol=1e-10)
        np.testing.assert_allclose(result.tables["Model fit"]["AIC"].iloc[0], -2 * loglike + 2 * len(params),
                                   rtol=1e-10)
        return result, prepared, params

    def test_continuous_and_categorical_predictors_match_an_independent_newton_fit(self):
        frame = simulated()
        result, prepared, params = self.check_against_newton(frame, "Grade", ["Dose", "Age", "Site"], ["Site"],
                                                             ["1", "2", "3", "4"])
        self.assertEqual(list(result.tables["Coefficients"].index), ["Dose", "Age", "Site [north]", "Site [south]"])
        self.assertEqual(result.tables["Reference levels"].loc["Site", "Reference"], "east")
        # The fitted probabilities follow the cumulative logit definition on the original scale.
        k = len(prepared.terms)
        eta = prepared.design @ params[:k]
        cumulative = expit(params[k:][None, :] - eta[:, None])
        expected = np.diff(np.column_stack([np.zeros(len(eta)), cumulative, np.ones(len(eta))]), axis=1)
        table = result.tables["Fitted probabilities"]
        np.testing.assert_allclose(table[[f"P({label})" for label in "1234"]].to_numpy(), expected, atol=1e-7)

    def test_more_levels_and_one_predictor_match_the_independent_fit(self):
        frame = simulated(rows=500, seed=3, levels=4)
        frame["Wide"] = frame["Grade"] + (frame["Dose"] > 0.8).astype(int) * 2
        levels = [str(value) for value in sorted(frame["Wide"].unique())]
        self.check_against_newton(frame, "Wide", ["Dose"], [], levels)

    def test_probability_sign_convention_is_odds_of_being_above(self):
        frame = simulated(rows=400, seed=11)
        result = run(frame, Response="Grade", Predictors=["Dose"], **{"Category order": ["1", "2", "3", "4"]})
        self.assertGreater(result.tables["Coefficients"].loc["Dose", "Odds ratio"], 1)
        fitted = result.tables["Fitted probabilities"]
        high = frame["Dose"].idxmax(), frame["Dose"].idxmin()
        self.assertGreater(fitted.loc[high[0] + 1, "P(4)"], fitted.loc[high[1] + 1, "P(4)"])


class OrderTests(unittest.TestCase):
    def test_reversed_order_flips_the_sign_and_keeps_label_probabilities(self):
        forward, backward = run(), run(**{"Category order": ORDER[::-1]})
        np.testing.assert_allclose(backward.tables["Coefficients"]["Estimate"],
                                   -forward.tables["Coefficients"]["Estimate"], rtol=1e-6)
        np.testing.assert_allclose(backward.tables["Coefficients"]["Odds ratio"],
                                   1 / forward.tables["Coefficients"]["Odds ratio"], rtol=1e-6)
        np.testing.assert_allclose(backward.tables["Thresholds"]["Estimate"].to_numpy(),
                                   -forward.tables["Thresholds"]["Estimate"].to_numpy()[::-1], rtol=1e-6)
        self.assertEqual(list(backward.tables["Fitted probabilities"].columns[3:]), ["P(High)", "P(Medium)", "P(Low)"])
        np.testing.assert_allclose(backward.tables["Fitted probabilities"]["P(Low)"],
                                   forward.tables["Fitted probabilities"]["P(Low)"], atol=1e-7)
        np.testing.assert_allclose(backward.tables["Model fit"]["Log likelihood"].iloc[0],
                                   forward.tables["Model fit"]["Log likelihood"].iloc[0], rtol=1e-10)

    def test_an_unchanged_order_is_proposed_by_the_data(self):
        frame = stages()
        self.assertEqual(ol.proposed_order(frame, "Stage", ["Treatment"]), ["High", "Low", "Medium"])
        numeric = pd.DataFrame({"y": [10, 2, 3.0, 2, 10, 3], "x": [1., 2, 3, 4, 5, 6]})
        self.assertEqual(ol.proposed_order(numeric, "y", ["x"]), ["2", "3", "10"])
        mixed = pd.DataFrame({"y": ["b", "A", "c", "b", "A", "c"], "x": range(6)})
        self.assertEqual(ol.proposed_order(mixed, "y", ["x"]), ["A", "b", "c"])
        self.assertEqual(ol.proposed_order(frame, "Missing", ["Treatment"]), [])

    def test_no_declared_order_uses_the_proposal(self):
        result = run(**{"Category order": []})
        self.assertEqual(list(result.tables["Thresholds"]["Lower category"]), ["High", "Low"])

    def test_a_new_level_requires_a_new_order(self):
        frame = stages()
        frame.loc[0, "Stage"] = "Critical"
        error = failure(frame)
        self.assertEqual(error.field, "Category order")
        self.assertIn('"Critical"', str(error))

    def test_a_removed_level_is_an_error_on_the_order(self):
        frame = stages()
        frame = frame[frame["Stage"] != "Medium"].copy()
        frame.loc[frame.index[:2], "Stage"] = "Mid"
        self.assertEqual(failure(frame).field, "Category order")
        quiet = frame[frame["Stage"] != "Mid"].assign(Stage=lambda data: data["Stage"])
        # Two levels left: the response itself is the problem, with the order not reached.
        self.assertEqual(failure(quiet, **{"Category order": ["Low", "High"]}).field, "Response")

    def test_order_with_duplicates_extra_or_wrong_types_is_rejected(self):
        for order in (["Low", "Low", "Medium", "High"], ["Low", "Medium", "High", "Other"], "Low", ["Low", None, "High"]):
            self.assertEqual(failure(**{"Category order": order}).field, "Category order", order)

    def test_numeric_and_text_responses_keep_literal_labels(self):
        frame = pd.DataFrame({"y": [1, 2, 3, 2, 1, 3, 2, 3, 1, 2, 3, 1], "x": [1., 2, 3, 2, 1.5, 3.5, 2.5, 2, 0.5, 3, 4, 1]})
        result = run(frame, Response="y", Predictors=["x"], **{"Category order": [1, 2.0, 3]})
        self.assertEqual(list(result.tables["Thresholds"]["Lower category"]), ["1", "2"])
        self.assertEqual(list(result.tables["Fitted probabilities"].columns[3:]), ["P(1)", "P(2)", "P(3)"])

    def test_labels_that_print_alike_are_an_error_on_the_response(self):
        frame = pd.DataFrame({"y": pd.Series([1, "1", 2, 3, "1", 2, 3, 1], dtype=object),
                              "x": [1., 2, 3, 4, 5, 6, 7, 8]})
        self.assertEqual(failure(frame, Response="y", Predictors=["x"], **{"Category order": []}).field, "Response")

    def test_levels_budget_and_minimum(self):
        frame = pd.DataFrame({"y": [str(i % 13) for i in range(130)], "x": np.arange(130.)})
        self.assertEqual(failure(frame, Response="y", Predictors=["x"], **{"Category order": []}).field, "Response")
        two = pd.DataFrame({"y": ["a", "b"] * 6, "x": np.arange(12.)})
        self.assertEqual(failure(two, Response="y", Predictors=["x"], **{"Category order": []}).field, "Response")


class WorksheetTests(unittest.TestCase):
    def test_rows_with_a_blank_response_or_predictor_are_dropped_and_physical_rows_kept(self):
        frame = stages()
        frame.index = [41] * len(frame)
        frame.iloc[5, 0] = np.nan
        frame.iloc[9, 1] = np.nan
        frame.iloc[12, 0] = "  "
        result = run(frame)
        fit = result.tables["Model fit"].iloc[0]
        self.assertEqual((fit["N"], fit["Incomplete rows"]), (165, 3))
        source = result.tables["Fitted probabilities"]["Source row"].tolist()
        self.assertEqual(source, [row for row in range(1, 169) if row not in (6, 10, 13)])

    def test_a_filled_value_that_cannot_be_used_is_an_error_on_its_field(self):
        frame = stages().astype({"Treatment": object})
        frame.iloc[4, 1] = "abc"
        self.assertEqual(failure(frame).field, "Predictors")
        frame = stages().astype({"Treatment": float})
        frame.iloc[4, 1] = np.inf
        self.assertEqual(failure(frame).field, "Predictors")
        frame = stages().astype({"Stage": object})
        frame.iloc[4, 0] = (1, 2)
        self.assertEqual(failure(frame).field, "Response")
        frame = pd.DataFrame({"y": [1., 2, 3, np.inf, 1, 2, 3, 2], "x": np.arange(8.)})
        self.assertEqual(failure(frame, Response="y", Predictors=["x"], **{"Category order": []}).field, "Response")

    def test_no_complete_rows_and_the_row_budget_are_checked_before_the_fit(self):
        empty = stages().assign(Treatment=np.nan)
        self.assertEqual(failure(empty).field, "Response")
        big = pd.DataFrame({"Stage": np.random.default_rng(1).choice(ORDER, size=ol.MAX_ROWS + 1),
                            "Treatment": np.arange(ol.MAX_ROWS + 1) % 2})
        with patch.object(ol, "fit_model", side_effect=AssertionError("the fit must not start")):
            self.assertEqual(failure(big).field, "Response")

    def test_categorical_coding_equals_multiple_regression(self):
        frame = simulated(rows=120)
        prepared = ol.check_options(frame, recipe(Response="Grade", Predictors=["Dose", "Site"],
                                                  **{"Categorical predictors": ["Site"],
                                                     "Category order": ["1", "2", "3", "4"]}))
        design, references = models._design(frame, ["Dose", "Site"], ["Site"], False)
        self.assertEqual(prepared.terms, list(design.columns))
        np.testing.assert_array_equal(prepared.design, design.to_numpy())
        self.assertEqual(prepared.references, references)

    def test_numbers_used_as_categories_keep_their_text_levels(self):
        frame = simulated(rows=150)
        frame["Site"] = frame["Site"].map({"north": 1, "south": 2, "east": 10})
        result = run(frame, Response="Grade", Predictors=["Dose", "Site"], **{"Categorical predictors": ["Site"],
                                                                              "Category order": list("1234")})
        self.assertEqual(list(result.tables["Coefficients"].index), ["Dose", "Site [10]", "Site [2]"])
        self.assertEqual(result.tables["Reference levels"].loc["Site", "Reference"], "1")


class SelectionTests(unittest.TestCase):
    def test_selection_errors_name_the_field_to_correct(self):
        cases = [(dict(Response=None), "Response"), (dict(Response="Nope"), "Response"),
                 (dict(Predictors=[]), "Predictors"), (dict(Predictors=None), "Predictors"),
                 (dict(Predictors="Treatment"), "Predictors"), (dict(Predictors=["Nope"]), "Predictors"),
                 (dict(Predictors=["Stage"]), "Predictors"), (dict(Predictors=["Treatment", "Treatment"]), "Predictors"),
                 (dict(**{"Categorical predictors": ["Stage"]}), "Categorical predictors"),
                 (dict(**{"Categorical predictors": "Treatment"}), "Categorical predictors"),
                 (dict(**{"Confidence level (%)": 0}), "Confidence level (%)"),
                 (dict(**{"Confidence level (%)": 100}), "Confidence level (%)"),
                 (dict(**{"Confidence level (%)": float("nan")}), "Confidence level (%)"),
                 (dict(**{"Confidence level (%)": True}), "Confidence level (%)"),
                 (dict(**{"Confidence level (%)": "95"}), "Confidence level (%)"),
                 (dict(**{"Show graph": "yes"}), "Show graph"), (dict(**{"Show graph": True}), "Profiles")]
        for overrides, field in cases:
            self.assertEqual(failure(**overrides).field, field, overrides)

    def test_duplicate_worksheet_columns_are_rejected(self):
        frame = stages()
        frame.columns = ["Stage", "Stage"]
        self.assertEqual(failure(frame).field, "Response")

    def test_predictor_budget(self):
        frame = pd.DataFrame(np.random.default_rng(5).normal(size=(80, 10)), columns=[f"x{i}" for i in range(10)])
        frame["y"] = np.random.default_rng(6).choice(list("abc"), size=80)
        self.assertEqual(failure(frame, Response="y", Predictors=[f"x{i}" for i in range(9)],
                                 **{"Category order": []}).field, "Predictors")
        ok = run(frame, Response="y", Predictors=[f"x{i}" for i in range(8)], **{"Category order": []})
        self.assertEqual(len(ok.tables["Coefficients"]), 8)

    def test_expanded_coefficient_budget_is_checked_before_the_fit(self):
        frame = pd.DataFrame({"y": np.random.default_rng(2).choice(list("abc"), size=600),
                              "g": [f"L{i % 26:02d}" for i in range(600)]})
        with patch.object(ol, "fit_model", side_effect=AssertionError("the fit must not start")):
            error = failure(frame, Response="y", Predictors=["g"],
                            **{"Categorical predictors": ["g"], "Category order": []})
        self.assertEqual(error.field, "Predictors")
        self.assertIn("25", str(error))

    def test_a_categorical_predictor_needs_two_levels(self):
        frame = stages().assign(Treatment="same")
        self.assertEqual(failure(frame, **{"Categorical predictors": ["Treatment"]}).field, "Predictors")

    def test_error_messages_are_the_english_catalog_entries(self):
        from analisi.ordinal_logit_catalog import EN
        self.assertEqual(str(failure(**{"Confidence level (%)": 120})), EN["ord.error.level"])


class IdentificationTests(unittest.TestCase):
    def test_constant_implicit_constant_and_collinear_predictors_are_errors_on_predictors(self):
        frame = stages()
        frame["Same"] = 3.0
        frame["Mirror"] = 1.0 - frame["Treatment"]
        frame["Copy"] = 2 * frame["Treatment"]
        for predictors, text in ((["Same"], "constant"), (["Treatment", "Mirror"], "constant"),
                                 (["Treatment", "Copy"], "collinear")):
            error = failure(frame, Predictors=predictors)
            self.assertEqual(error.field, "Predictors", predictors)
            self.assertIn(text, str(error).lower(), predictors)

    def test_too_few_rows_for_the_parameters(self):
        frame = pd.DataFrame({"y": ["a", "b", "c", "a"], "x": [1., 2., 3., 4.], "z": [1., 0, 1, 3]})
        self.assertEqual(failure(frame, Response="y", Predictors=["x", "z"], **{"Category order": []}).field,
                         "Predictors")

    def test_complete_separation_is_reported_on_the_predictors(self):
        rng = np.random.default_rng(9)
        x = rng.normal(size=90)
        frame = pd.DataFrame({"x": x, "y": np.where(x < -0.5, "low", np.where(x < 0.5, "mid", "high"))})
        error = failure(frame, Response="y", Predictors=["x"], **{"Category order": ["low", "mid", "high"]})
        self.assertEqual(error.field, "Predictors")
        self.assertIn("separat", str(error).lower())

    def test_a_response_unrelated_to_the_predictor_still_fits(self):
        rng = np.random.default_rng(4)
        frame = pd.DataFrame({"x": rng.normal(size=200), "y": rng.choice(list("abc"), size=200)})
        result = run(frame, Response="y", Predictors=["x"], **{"Category order": list("abc")})
        self.assertLess(abs(result.tables["Coefficients"].loc["x", "Estimate"]), 0.6)

    def test_a_badly_scaled_predictor_is_fitted_on_the_standardized_scale(self):
        frame = simulated(rows=300, seed=21)
        scaled = frame.assign(Dose=frame["Dose"] * 1e6, Age=frame["Age"] + 1e9)
        base = run(frame, Response="Grade", Predictors=["Dose", "Age"], **{"Category order": list("1234")})
        bad = run(scaled, Response="Grade", Predictors=["Dose", "Age"], **{"Category order": list("1234")})
        np.testing.assert_allclose(bad.tables["Coefficients"].loc["Dose", "Estimate"] * 1e6,
                                   base.tables["Coefficients"].loc["Dose", "Estimate"], rtol=1e-5)
        np.testing.assert_allclose(bad.tables["Model fit"]["Log likelihood"], base.tables["Model fit"]["Log likelihood"],
                                   rtol=1e-8)

    def test_a_failed_estimation_never_returns_a_partial_result(self):
        for patched in (dict(side_effect=np.linalg.LinAlgError("singular")), dict(side_effect=ValueError("nan"))):
            with patch.object(ol.OrderedModel, "fit", **patched):
                self.assertEqual(failure().field, "Predictors")
        with patch.object(ol, "MAX_ITERATIONS", 1):
            self.assertEqual(failure(simulated(), Response="Grade", Predictors=["Dose", "Age"],
                                     **{"Category order": list("1234")}).field, "Predictors")


class ProbabilityTests(unittest.TestCase):
    def test_tail_probabilities_keep_their_relative_accuracy(self):
        from decimal import Decimal, getcontext
        getcontext().prec = 80

        def logistic(value):
            return 1 / (1 + (-Decimal(value)).exp())

        cases = [(0.0, [-2.0, 2.0]), (30.0, [-1.0, 0.5, 4.0]), (-35.0, [-3.0, 1.0, 6.0, 9.0]), (12.0, [11.9999, 12.0001])]
        for eta, thresholds in cases:
            got = ol.category_probabilities(np.array([eta]), np.array(thresholds))[0]
            cuts = [Decimal(0)] + [logistic(Decimal(t) - Decimal(eta)) for t in thresholds] + [Decimal(1)]
            exact = [float(high - low) for low, high in zip(cuts, cuts[1:])]
            np.testing.assert_allclose(got, exact, rtol=1e-9, atol=0)
            self.assertTrue((got >= 0).all())
            self.assertAlmostEqual(float(got.sum()), 1.0, places=12)

    def test_probabilities_of_extreme_linear_predictors_are_finite_and_sum_to_one(self):
        eta = np.array([-800.0, -50.0, 0.0, 50.0, 800.0])
        table = ol.category_probabilities(eta, np.array([-1.0, 0.0, 2.0]))
        self.assertTrue(np.isfinite(table).all() and (table >= 0).all())
        np.testing.assert_allclose(table.sum(axis=1), 1, atol=1e-12)

    def test_the_predicted_category_of_a_tie_is_the_first_in_the_declared_order(self):
        table = np.array([[0.4, 0.4, 0.2], [0.2, 0.4, 0.4], [1 / 3, 1 / 3, 1 / 3]])
        self.assertEqual(list(ol._first_best(table)), [0, 1, 0])


class ProfileTests(unittest.TestCase):
    PROFILES = [{"Name": "Control", "Values": {"Treatment": 0}}, {"Name": "Treated", "Values": {"Treatment": 1}}]

    def test_profile_probabilities_equal_the_group_proportions(self):
        result = run(Profiles=self.PROFILES)
        table = result.tables["Profile probabilities"]
        self.assertEqual(list(table.columns), ["Profile", "P(Low)", "P(Medium)", "P(High)"])
        np.testing.assert_allclose(table.iloc[:, 1:].to_numpy(), EXPECTED["probabilities"], atol=5e-9)
        self.assertIsNone(result.figure)

    def test_a_profile_for_every_predictor_kind_and_the_extrapolation_note(self):
        frame = simulated(rows=200)
        profiles = [{"Name": "Inside", "Values": {"Dose": 0.0, "Age": 45, "Site": "south"}},
                    {"Name": "Outside", "Values": {"Dose": 50.0, "Age": "45", "Site": "east"}}]
        options = dict(Response="Grade", Predictors=["Dose", "Age", "Site"], Profiles=profiles,
                       **{"Categorical predictors": ["Site"], "Category order": list("1234")})
        with self.assertRaises(FieldError) as caught:
            run(frame, **options)
        self.assertEqual(caught.exception.field, "Profiles")  # "45" is text, not a number
        profiles[1]["Values"]["Age"] = 45
        table = run(frame, **options).tables["Profile probabilities"]
        self.assertEqual(table.loc[0, "Note"], "")
        self.assertIn("Dose = 50 is outside the observed range", table.loc[1, "Note"])
        np.testing.assert_allclose(table[["P(1)", "P(2)", "P(3)", "P(4)"]].sum(axis=1), 1, atol=1e-12)
        self.assertGreater(table.loc[1, "P(4)"], 0.99)

    def test_a_numeric_category_matches_its_printed_level(self):
        frame = simulated(rows=200)
        frame["Site"] = frame["Site"].map({"north": 1, "south": 2, "east": 10})
        profiles = [{"Name": "Ten", "Values": {"Dose": 0.0, "Site": 10}}, {"Name": "One", "Values": {"Dose": 0.0, "Site": "1"}}]
        table = run(frame, Response="Grade", Predictors=["Dose", "Site"], Profiles=profiles,
                    **{"Categorical predictors": ["Site"], "Category order": list("1234")}).tables["Profile probabilities"]
        self.assertEqual(list(table["Profile"]), ["Ten", "One"])

    def test_invalid_profiles_are_errors_on_the_profiles_field(self):
        frame = simulated(rows=120)
        base = dict(Response="Grade", Predictors=["Dose", "Site"], **{"Categorical predictors": ["Site"],
                                                                     "Category order": list("1234")})
        ok = {"Dose": 0.0, "Site": "south"}
        bad = [[{"Name": "x", "Values": {"Dose": 0.0}}],                                  # a missing predictor
               [{"Name": "x", "Values": {**ok, "Site": "west"}}],                         # an unknown category
               [{"Name": "x", "Values": {**ok, "Other": 1}}],                             # an unknown key
               [{"Name": "x", "Values": {**ok, "Dose": float("nan")}}],
               [{"Name": "x", "Values": {**ok, "Dose": True}}],
               [{"Name": "", "Values": ok}], [{"Values": ok}], [{"Name": "x"}], ["x"],
               [{"Name": "x", "Values": ok}, {"Name": "x", "Values": ok}],
               [{"Name": str(i), "Values": ok} for i in range(13)], "x"]
        for profiles in bad:
            self.assertEqual(failure(frame, Profiles=profiles, **base).field, "Profiles", profiles)

    def test_the_figure_stacks_to_one_and_keeps_literal_text(self):
        names = ["$Control$", "Treated {x}"]
        profiles = [{"Name": names[0], "Values": {"Treatment": 0}}, {"Name": names[1], "Values": {"Treatment": 1}}]
        frame = stages().replace({"Medium": "$mid$"})
        result = run(frame, Profiles=profiles, **{"Show graph": True, "Category order": ["Low", "$mid$", "High"]})
        chart = result.figure
        axes = chart.axes[0]
        self.assertEqual(axes.get_title(), ol.FIGURE_TITLE)
        bars = [patch for patch in axes.patches if (patch.get_gid() or "").startswith("ordinal-logit-profile-")]
        self.assertEqual(len(bars), 6)
        totals = {}
        for bar in bars:
            profile = bar.get_gid().split("-")[3]
            totals[profile] = totals.get(profile, 0) + bar.get_height()
            self.assertEqual(bar.get_y() == 0, bar.get_gid().endswith("category-1"))
        np.testing.assert_allclose(list(totals.values()), 1, atol=1e-12)
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], ["Low", "$mid$", "High"])
        self.assertEqual([label.get_text() for label in axes.get_xticklabels()], names)
        self.assertFalse(any(text.get_parse_math() for text in (axes.get_legend().get_title(), *axes.get_legend().get_texts(),
                                                                *axes.get_xticklabels())))
        colors = [bar.get_facecolor() for bar in bars if bar.get_gid().startswith("ordinal-logit-profile-1-")]
        self.assertEqual(len({tuple(color) for color in colors}), 3)
        self.assertEqual(ol.palette(3), ol.palette(3))

    def test_the_figure_is_not_drawn_without_the_option(self):
        self.assertIsNone(run(Profiles=self.PROFILES).figure)


class IntegrationTests(unittest.TestCase):
    def test_the_method_is_registered_once_in_regression_and_curves(self):
        self.assertIn(ol.ORDINAL_LOGIT, METHODS)
        self.assertEqual(GROUPS["Regression and Curves"].count(ol.ORDINAL_LOGIT), 1)
        self.assertEqual(list(METHODS[ol.ORDINAL_LOGIT]), list(ol.OPTIONS))
        self.assertEqual(ol.OPTIONS[ol.CATEGORICAL], "Multiple (optional)")
        self.assertEqual(ol.OPTIONS[ol.LEVEL], 95.0)
        self.assertIs(ol.OPTIONS[ol.GRAPH], False)

    def test_binary_logistic_recipes_of_multiple_regression_are_unchanged(self):
        import statsmodels.api as sm
        frame = simulated(rows=250, seed=13)
        frame["Event"] = (frame["Grade"] >= 3).astype(int)
        for predictors, categorical in ((["Dose"], []), (["Dose", "Age", "Site"], ["Site"])):
            result = analyse("Multiple regression", frame, {"Response": "Event", "Predictors": predictors,
                                                             "Categorical predictors": categorical, "Family": "Logistic"})
            self.assertNotIn("Thresholds", result.tables)
            design, _ = models._design(frame, predictors, categorical, True)
            reference = sm.GLM(frame["Event"], design, family=sm.families.Binomial()).fit()
            table = result.tables["Coefficients"]
            np.testing.assert_allclose(table["Estimate"].to_numpy(), reference.params.to_numpy(), rtol=1e-7)

    def test_the_input_frame_is_never_modified(self):
        frame = simulated(rows=100)
        before = frame.copy(deep=True)
        run(frame, Response="Grade", Predictors=["Dose", "Site"], **{"Categorical predictors": ["Site"],
                                                                    "Category order": list("1234")})
        pd.testing.assert_frame_equal(frame, before)

    def test_the_fit_is_made_once_per_analysis(self):
        with patch.object(ol, "fit_model", wraps=ol.fit_model) as counted:
            run(Profiles=ProfileTests.PROFILES, **{"Show graph": True})
        self.assertEqual(counted.call_count, 1)

    def test_every_message_has_an_italian_translation_with_the_same_placeholders(self):
        import string
        from analisi.ordinal_logit_catalog import EN, IT
        self.assertEqual(set(EN), set(IT))
        formatter = string.Formatter()
        for key in EN:
            self.assertEqual({field for _, field, _, _ in formatter.parse(EN[key]) if field},
                             {field for _, field, _, _ in formatter.parse(IT[key]) if field}, key)


if __name__ == "__main__":
    unittest.main()
