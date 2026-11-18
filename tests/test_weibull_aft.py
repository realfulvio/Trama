"""Weibull AFT engine: frozen references, an independent optimiser, units, identification and budgets."""
import json
from pathlib import Path
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from scipy import optimize, stats
from statsmodels.tools.numdiff import approx_fprime, approx_hess3

from analisi import models
from analisi import weibull_aft as aft
from analisi.field_error import FieldError

DATA = Path(__file__).parent / "data" / "weibull_aft"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
TOLERANCE = {"atol": 2e-6, "rtol": 5e-6}
CONTROL, TREATED = ({"Name": "Control", "Values": {"Treatment": 0}}, {"Name": "Treated", "Values": {"Treatment": 1}})


def follow_up():
    return pd.read_csv(DATA / "follow-up.csv", keep_default_na=False).replace("", np.nan)


def options(**changes):
    base = {"Time": "Time", "Event": "Status", "Event value": "event", "Censor value": "censored",
            "Predictors": ["Treatment"], "Categorical predictors": [], "Shape mode": "Fixed", "Shape": 1.5,
            "Confidence level (%)": 95.0, "Profiles": [], "Times": [], "Show graph": False}
    return base | changes


def run(frame=None, **changes):
    tables, plan, fit = aft.run(follow_up() if frame is None else frame, options(**changes))
    return tables, plan, fit


def field_of(call):
    with unittest.TestCase().assertRaises(FieldError) as caught:
        call()
    return caught.exception.field, str(caught.exception)


def cohort(n=240, seed=7):
    """Synthetic cohort: a continuous covariate with a large offset, a three-level group and ~30% censoring."""
    rng = np.random.default_rng(seed)
    x = rng.normal(10.0, 3.0, n)
    group = rng.choice(["A", "B", "C"], n)
    eta = 1.2 + 0.05 * (x - 10) + 0.4 * (group == "B") - 0.3 * (group == "C")
    event_time = np.exp(eta) * (-np.log(rng.uniform(size=n))) ** (1 / 1.8)
    censor_time = np.exp(eta) * rng.uniform(0.2, 3.0, n)
    time = np.minimum(event_time, censor_time)
    return pd.DataFrame({"t": time, "d": (event_time <= censor_time).astype(int), "x": x, "g": group})


def cohort_options(**changes):
    base = {"Time": "t", "Event": "d", "Predictors": ["x", "g"], "Categorical predictors": ["g"],
            "Shape mode": "Estimated ML", "Event value": "1", "Censor value": "0"}
    return base | changes


class FrozenReferenceTests(unittest.TestCase):
    """The profile-likelihood references of the package, for a fixed and for an estimated shape."""

    def check(self, mode, shape_mode):
        expected = EXPECTED[mode]
        tables, _, fit = run(**{"Shape mode": shape_mode})
        coefficients, model = tables["Coefficients"], tables["Model fit"].iloc[0]
        np.testing.assert_allclose(coefficients["Estimate"], expected["beta"], **TOLERANCE)
        self.assertAlmostEqual(coefficients.loc["Treatment", "Time ratio"], 2.0, places=5)
        if mode == "fixed":
            np.testing.assert_allclose(coefficients["SE"], expected["fixed_se"], **TOLERANCE)
        np.testing.assert_allclose([model["Shape"], model["Log likelihood"], model["AIC"]],
                                   [expected["shape"], expected["ll"], expected["aic"]], **TOLERANCE)
        self.assertEqual((model["N"], model["Events"], model["Censored"], model["Incomplete rows"]), (16, 10, 6, 0))
        np.testing.assert_allclose(tables["Fitted survival"]["Median time"].iloc[[0, 8]], expected["median"],
                                   **TOLERANCE)
        return tables, fit

    def test_fixed_shape(self):
        tables, fit = self.check("fixed", "Fixed")
        self.assertEqual(fit.parameters, 2)
        self.assertTrue(np.isnan(tables["Model fit"].iloc[0]["Shape lower"]))

    def test_estimated_shape_counts_the_shape_in_the_aic(self):
        tables, fit = self.check("estimated", "Estimated ML")
        self.assertEqual(fit.parameters, 3)
        model = tables["Model fit"].iloc[0]
        self.assertLess(model["Shape lower"], model["Shape"] < model["Shape upper"] and model["Shape"])
        self.assertAlmostEqual(model["AIC"], -2 * model["Log likelihood"] + 6, places=9)

    def test_the_shape_interval_is_the_wald_interval_of_log_shape(self):
        """At the frozen optimum, SE(log k) from a numerical Hessian of weibull_min; level 90% to see the quantile."""
        expected = EXPECTED["estimated"]
        frame = follow_up()
        time, event = frame["Time"].to_numpy(float), (frame["Status"] == "event").to_numpy()
        design = np.column_stack([np.ones(len(frame)), frame["Treatment"].to_numpy(float)])

        def negative(theta):
            scale = np.exp(design @ theta[:2])
            k = np.exp(theta[2])
            return -float(np.where(event, stats.weibull_min.logpdf(time, k, scale=scale),
                                   stats.weibull_min.logsf(time, k, scale=scale)).sum())

        theta = np.r_[expected["beta"], np.log(expected["shape"])]
        se = np.sqrt(np.linalg.inv(approx_hess3(theta, negative))[2, 2])
        z = stats.norm.ppf(0.95)
        model = run(**{"Shape mode": "Estimated ML", "Confidence level (%)": 90.0})[0]["Model fit"].iloc[0]
        np.testing.assert_allclose([model["Shape lower"], model["Shape upper"]],
                                   np.exp(theta[2] + np.array([-z, z]) * se), rtol=1e-5)

    def test_survival_of_profiles_matches_the_reference(self):
        tables, _, _ = run(Profiles=[CONTROL, TREATED], Times=[0, 2, 4, 8])
        curves = tables["Survival curves"]
        np.testing.assert_allclose(curves["Survival"].to_numpy().reshape(2, 4), EXPECTED["fixed"]["survival"],
                                   **TOLERANCE)
        self.assertEqual(list(curves["Profile"]), ["Control"] * 4 + ["Treated"] * 4)

    def test_wald_intervals_and_p_values_follow_the_standard_errors(self):
        tables, _, _ = run(**{"Confidence level (%)": 90.0})
        co = tables["Coefficients"]
        critical = stats.norm.ppf(0.95)
        np.testing.assert_allclose(co["Lower"], co["Estimate"] - critical * co["SE"], rtol=1e-12)
        np.testing.assert_allclose(co["Ratio upper"], np.exp(co["Upper"]), rtol=1e-12)
        np.testing.assert_allclose(co["p"], 2 * stats.norm.sf(np.abs(co["Estimate"] / co["SE"])), rtol=1e-10)


class IndependentFitTests(unittest.TestCase):
    """A mixed covariate model against scipy's optimiser and numerical derivatives of weibull_min."""

    @staticmethod
    def negative_log_likelihood(theta, time, event, design, shape):
        beta = theta[:design.shape[1]]
        k = shape if shape is not None else np.exp(theta[-1])
        scale = np.exp(design @ beta)
        return -float(np.where(event, stats.weibull_min.logpdf(time, k, scale=scale),
                               stats.weibull_min.logsf(time, k, scale=scale)).sum())

    def check(self, shape):
        frame = cohort()
        mode = {"Shape mode": "Fixed", "Shape": shape} if shape else {"Shape mode": "Estimated ML"}
        _, plan, fit = aft.run(frame, cohort_options(**mode))
        data = plan.data
        self.assertEqual(data.terms, ["Intercept", "x", "g [B]", "g [C]"])
        args = (data.time, data.event, data.design, shape)
        start = np.r_[np.zeros(4), [0.0] if shape is None else []]
        start[0] = np.log(data.time.mean())
        best = optimize.minimize(self.negative_log_likelihood, start, args=args, method="BFGS",
                                 options={"gtol": 1e-10, "maxiter": 2000})
        theta = np.r_[fit.beta, [] if shape else [np.log(fit.shape)]]
        np.testing.assert_allclose(theta, best.x, rtol=2e-5, atol=2e-5)
        self.assertAlmostEqual(-fit.log_likelihood, best.fun, places=6)
        hessian = approx_hess3(theta, self.negative_log_likelihood, args=args)
        reference = np.linalg.inv(hessian)
        size = 4
        np.testing.assert_allclose(fit.covariance, reference[:size, :size], rtol=2e-4, atol=1e-9)
        if shape is None:
            self.assertAlmostEqual(fit.log_shape_se, float(np.sqrt(reference[size, size])), delta=2e-4)

    def test_fixed_shape(self):
        self.check(1.8)

    def test_estimated_shape(self):
        self.check(None)

    def test_gradient_and_hessian_match_finite_differences(self):
        frame = cohort(60, seed=2)
        plan = aft.check_options(frame, cohort_options())
        data = plan.data
        log_time = np.log(data.time)
        centred = log_time - log_time.mean()
        z = np.column_stack([np.ones(data.n), (data.design[:, 1] - 10) / 3, data.design[:, 2:]])
        for fixed in (None, 1.7):
            likelihood = aft.Likelihood(z, centred, log_time, data.event, fixed)
            theta = np.r_[[0.1, 0.2, -0.1, 0.15], [] if fixed else [0.3]]
            value, gradient, hessian = likelihood(theta)
            np.testing.assert_allclose(gradient, approx_fprime(theta, lambda t: likelihood(t)[0], centered=True),
                                       rtol=1e-6, atol=1e-7)
            numeric = approx_hess3(theta, lambda t: likelihood(t)[0])
            np.testing.assert_allclose(hessian, numeric, rtol=1e-4, atol=1e-4)

    def test_profile_curve_uses_the_worksheet_units_of_the_coefficients(self):
        frame = cohort()
        profile = {"Name": "P", "Values": {"x": 12.5, "g": "C"}}
        tables, plan, fit = aft.run(frame, cohort_options(Profiles=[profile], Times=[0.5, 1.0, 2.5]))
        co = tables["Coefficients"]["Estimate"]
        eta = co["Intercept"] + co["x"] * 12.5 + co["g [C]"]
        expected = np.exp(-np.exp(fit.shape * (np.log([0.5, 1.0, 2.5]) - eta)))
        np.testing.assert_allclose(tables["Survival curves"]["Survival"], expected, rtol=1e-10)
        median = np.exp(eta + np.log(np.log(2)) / fit.shape)
        self.assertAlmostEqual(aft.median_time(fit.linear_predictor(plan.profile_design[0]), fit.shape), median,
                               delta=1e-9 * median)

    def test_fitted_survival_rows_match_the_standard_formulas(self):
        frame = cohort(80, seed=4)
        tables, _, fit = aft.run(frame, cohort_options())
        fitted = tables["Fitted survival"]
        co = tables["Coefficients"]["Estimate"]
        eta = (co["Intercept"] + co["x"] * frame["x"] + co["g [B]"] * (frame["g"] == "B")
               + co["g [C]"] * (frame["g"] == "C"))
        np.testing.assert_allclose(fitted["Median time"], np.exp(eta + np.log(np.log(2)) / fit.shape), rtol=1e-9)
        np.testing.assert_allclose(fitted["Survival at time"],
                                   np.exp(-np.exp(fit.shape * (np.log(frame["t"]) - eta))), rtol=1e-9)


class UnitsAndLimitsTests(unittest.TestCase):
    def test_changing_the_unit_of_time_moves_only_the_intercept(self):
        frame = follow_up()
        base = run(frame, **{"Shape mode": "Estimated ML"})[0]
        for factor in (24.0, 1 / 60, 1e-9, 3e6):
            scaled = run(frame.assign(Time=frame["Time"] * factor), **{"Shape mode": "Estimated ML"})[0]
            delta = scaled["Coefficients"]["Estimate"].to_numpy() - base["Coefficients"]["Estimate"].to_numpy()
            np.testing.assert_allclose(delta, [np.log(factor), 0.0], atol=1e-8)
            np.testing.assert_allclose(scaled["Coefficients"]["SE"], base["Coefficients"]["SE"], rtol=1e-7)
            np.testing.assert_allclose(scaled["Model fit"].iloc[0]["Shape"], base["Model fit"].iloc[0]["Shape"],
                                       rtol=1e-7)

    def test_times_near_the_ends_of_the_double_range(self):
        frame = follow_up()
        base = run(frame, **{"Shape mode": "Estimated ML"})[0]
        for factor in (1e200, 1e-200, 1e300):
            tables = run(frame.assign(Time=frame["Time"] * factor), **{"Shape mode": "Estimated ML"})[0]
            delta = tables["Coefficients"]["Estimate"].to_numpy() - base["Coefficients"]["Estimate"].to_numpy()
            np.testing.assert_allclose(delta, [np.log(factor), 0.0], atol=1e-7)
            self.assertTrue(np.isfinite(tables["Fitted survival"]["Median time"]).all())
            np.testing.assert_allclose(tables["Fitted survival"]["Survival at time"],
                                       base["Fitted survival"]["Survival at time"], rtol=1e-7)

    def test_a_covariate_with_a_huge_offset_is_harmless(self):
        frame = cohort(120, seed=5)
        shifted = frame.assign(x=frame["x"] + 1e9)
        base = aft.run(frame, cohort_options())[0]["Coefficients"]
        moved = aft.run(shifted, cohort_options())[0]["Coefficients"]
        np.testing.assert_allclose(moved.loc["x", ["Estimate", "SE"]], base.loc["x", ["Estimate", "SE"]], rtol=1e-6)
        np.testing.assert_allclose(moved.loc[["g [B]", "g [C]"], "Estimate"], base.loc[["g [B]", "g [C]"], "Estimate"],
                                   rtol=1e-6, atol=1e-8)

    def test_shape_limits_are_inclusive_and_outside_values_name_the_field(self):
        for shape in (0.05, 50):
            self.assertEqual(run(Shape=shape)[2].shape, shape)
        for shape in (0.0499, 50.0001, 0, -2, np.nan, np.inf, "1.5", True, None):
            self.assertEqual(field_of(lambda s=shape: run(Shape=s))[0], "Shape", shape)

    def test_shape_is_not_validated_when_it_is_estimated(self):
        self.assertAlmostEqual(run(**{"Shape mode": "Estimated ML", "Shape": -9})[2].shape,
                               EXPECTED["estimated"]["shape"], places=5)

    def test_confidence_level_must_lie_strictly_between_0_and_100(self):
        for level in (0, 100, -1, 101, np.nan, np.inf, "95", True):
            self.assertEqual(field_of(lambda v=level: run(**{"Confidence level (%)": v}))[0], "Confidence level (%)")
        self.assertEqual(run(**{"Confidence level (%)": 99.9})[2].data.settings.level, 99.9)

    def test_a_model_with_no_predictor_is_the_intercept_only_weibull(self):
        tables, _, fit = run(Predictors=[], **{"Shape mode": "Estimated ML"})
        times, events = follow_up()["Time"].to_numpy(), follow_up()["Status"].eq("event").to_numpy()

        def negative(theta):
            return -np.where(events, stats.weibull_min.logpdf(times, np.exp(theta[1]), scale=np.exp(theta[0])),
                             stats.weibull_min.logsf(times, np.exp(theta[1]), scale=np.exp(theta[0]))).sum()
        best = optimize.minimize(negative, [1.0, 0.0], method="BFGS", options={"gtol": 1e-10})
        np.testing.assert_allclose([tables["Coefficients"].loc["Intercept", "Estimate"], np.log(fit.shape)], best.x,
                                   rtol=1e-5)
        self.assertEqual(list(tables["Coefficients"].index), ["Intercept"])


class IdentificationTests(unittest.TestCase):
    def test_a_wholly_censored_group_is_an_error_on_the_predictors_in_both_modes(self):
        frame = follow_up()
        frame.loc[frame["Treatment"] == 1, "Status"] = "censored"
        for mode in ("Fixed", "Estimated ML"):
            field, message = field_of(lambda m=mode: run(frame, **{"Shape mode": m}))
            self.assertEqual(field, "Predictors")
            self.assertIn("Treatment", message)

    def test_a_categorical_level_without_events_names_the_level(self):
        frame = cohort(90, seed=1)
        frame.loc[frame["g"] == "C", "d"] = 0
        field, message = field_of(lambda: aft.run(frame, cohort_options()))
        self.assertEqual(field, "Predictors")
        self.assertIn("g [C]", message)

    def test_collinear_predictors_are_rejected_before_the_fit(self):
        frame = cohort(60, seed=3).assign(twice=lambda f: 2 * f["x"])
        with mock.patch.object(aft, "fit_weibull", side_effect=AssertionError("fitted")):
            field, _ = field_of(lambda: aft.run(frame, cohort_options(Predictors=["x", "twice"],
                                                                      **{"Categorical predictors": []})))
        self.assertEqual(field, "Predictors")

    def test_nearly_collinear_predictors_are_an_error_on_the_predictors(self):
        rng = np.random.default_rng(1)
        frame = cohort(80, seed=6)
        frame["near"] = frame["x"] + rng.normal(0, 1e-9, len(frame))
        field, _ = field_of(lambda: aft.run(frame, cohort_options(Predictors=["x", "near"],
                                                                  **{"Categorical predictors": []})))
        self.assertEqual(field, "Predictors")

    def test_a_constant_predictor_is_an_error(self):
        frame = cohort(60).assign(flat=4.0)
        field, message = field_of(lambda: aft.run(frame, cohort_options(Predictors=["flat"],
                                                                        **{"Categorical predictors": []})))
        self.assertEqual((field, "flat" in message), ("Predictors", True))

    def test_a_categorical_predictor_with_one_level_is_an_error_on_categorical_predictors(self):
        frame = cohort(60).assign(g="A")
        self.assertEqual(field_of(lambda: aft.run(frame, cohort_options()))[0], "Categorical predictors")

    def test_identical_times_leave_the_estimated_shape_without_a_maximum(self):
        frame = follow_up().assign(Time=5.0, Status="event")
        field, _ = field_of(lambda: run(frame, Predictors=[], **{"Shape mode": "Estimated ML"}))
        self.assertEqual(field, "Shape mode")
        self.assertAlmostEqual(run(frame, Predictors=[])[0]["Coefficients"].loc["Intercept", "Estimate"],
                               np.log(5.0), places=9)

    def test_no_event_is_not_hidden_behind_a_fallback_shape(self):
        field, _ = field_of(lambda: run(follow_up().assign(Status="censored"), **{"Shape mode": "Estimated ML"}))
        self.assertEqual(field, "Event")

    def test_duplicate_model_terms_are_rejected(self):
        frame = cohort(60).assign(Intercept=lambda f: f["x"] * 2 + 1)
        field, message = field_of(lambda: aft.run(frame, cohort_options(Predictors=["Intercept"],
                                                                        **{"Categorical predictors": []})))
        self.assertEqual(field, "Predictors")
        self.assertIn("Intercept", message)


class StatusAndRowTests(unittest.TestCase):
    def test_unknown_status_codes_name_the_event_field(self):
        self.assertEqual(field_of(lambda: run(follow_up().assign(Status="unmapped")))[0], "Event")

    def test_a_wrong_event_value_names_the_event_field_and_the_values_present(self):
        field, message = field_of(lambda: run(**{"Event value": "death"}))
        self.assertEqual(field, "Event")
        self.assertIn("censored", message)

    def test_equal_codes_are_rejected(self):
        self.assertEqual(field_of(lambda: run(**{"Censor value": "event"}))[0], "Censor value")

    def test_numeric_status_columns_use_numeric_codes(self):
        frame = follow_up()
        frame["Status"] = frame["Status"].eq("event").astype(int)
        _, _, fit = run(frame, **{"Event value": "1", "Censor value": "0"})
        self.assertAlmostEqual(fit.log_likelihood, EXPECTED["fixed"]["ll"], places=5)

    def test_non_positive_and_missing_times(self):
        frame = follow_up()
        for bad in (0.0, -3.0):
            changed = frame.copy()
            changed.loc[4, "Time"] = bad
            field, message = field_of(lambda c=changed: run(c))
            self.assertEqual(field, "Time")
            self.assertIn("Source row 5", message)

    def test_incomplete_rows_are_left_out_and_counted(self):
        frame = follow_up()
        frame.loc[2, "Time"] = np.nan
        frame.loc[9, "Status"] = np.nan
        frame.loc[12, "Treatment"] = np.nan
        tables, _, _ = run(frame)
        kept = frame.drop(index=[2, 9, 12]).reset_index(drop=True)
        reference = run(kept)[0]
        np.testing.assert_allclose(tables["Coefficients"]["Estimate"], reference["Coefficients"]["Estimate"],
                                   rtol=1e-10)
        self.assertEqual(tables["Model fit"].iloc[0]["Incomplete rows"], 3)
        self.assertEqual(tables["Model fit"].iloc[0]["N"], 13)
        self.assertEqual(list(tables["Fitted survival"]["Source row"]), [1, 2, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16])

    def test_source_row_is_the_physical_position_even_with_repeated_index_labels(self):
        frame = follow_up()
        frame.index = [21] * len(frame)
        frame.iloc[2, 0] = np.nan
        self.assertEqual(list(run(frame)[0]["Fitted survival"]["Source row"]), [1, 2, *range(4, 17)])
        frame.iloc[5, 0] = -1.0
        self.assertIn("Source row 6", field_of(lambda: run(frame))[1])

    def test_an_error_names_the_row_of_the_worksheet_not_of_the_complete_cases(self):
        frame = follow_up()
        frame.loc[0, "Status"] = np.nan
        frame.loc[1, "Time"] = np.nan
        frame.loc[6, "Time"] = 0.0
        self.assertIn("Source row 7", field_of(lambda: run(frame))[1])

    def test_no_complete_row_names_the_column_that_is_empty(self):
        frame = follow_up().assign(Time=np.nan)
        self.assertEqual(field_of(lambda: run(frame))[0], "Time")

    def test_roles_must_be_existing_distinct_columns(self):
        self.assertEqual(field_of(lambda: aft.run(follow_up(), options(Time=None)))[0], "Time")
        self.assertEqual(field_of(lambda: aft.run(follow_up(), options(Event="Nope")))[0], "Event")
        self.assertEqual(field_of(lambda: aft.run(follow_up(), options(Event="Time")))[0], "Event")
        self.assertEqual(field_of(lambda: aft.run(follow_up(), options(Predictors=["Time"])))[0], "Predictors")
        self.assertEqual(field_of(lambda: aft.run(follow_up(), options(Predictors=["Status"])))[0], "Predictors")
        self.assertEqual(field_of(lambda: aft.run(follow_up(), options(Predictors=["Treatment", "Treatment"])))[0],
                         "Predictors")
        self.assertEqual(field_of(lambda: aft.run(follow_up(), options(**{"Categorical predictors": ["Time"]})))[0],
                         "Categorical predictors")

    def test_text_in_a_numeric_predictor_is_an_error_on_the_predictors(self):
        frame = follow_up().assign(Treatment=["a"] * 16)
        self.assertEqual(field_of(lambda: run(frame))[0], "Predictors")

    def test_the_worksheet_is_never_changed(self):
        frame = follow_up()
        before = frame.copy(deep=True)
        run(frame, Profiles=[CONTROL], Times=[1, 2])
        pd.testing.assert_frame_equal(frame, before)


class ParityWithMultipleRegressionTests(unittest.TestCase):
    """Dummy coding, reference level and term names are those of the multiple-regression models."""

    def test_terms_and_reference_levels(self):
        frame = cohort(100, seed=8)
        frame["g"] = frame["g"].map({"A": "zeta", "B": "alpha", "C": "mid"})
        frame["flag"] = np.where(frame["x"] > 10, 10, 2)
        predictors, categories = ["x", "g", "flag"], ["g", "flag"]
        design, references = models._design(frame, predictors, categories, True)
        tables, plan, _ = aft.run(frame, cohort_options(Predictors=predictors, **{"Categorical predictors": categories}))
        self.assertEqual(plan.data.terms, list(design.columns))
        np.testing.assert_array_equal(plan.data.design, design.to_numpy())
        self.assertEqual(tables["Reference levels"]["Reference"].to_dict(), references)
        self.assertEqual(list(tables["Reference levels"].index), list(references))
        self.assertEqual(list(tables["Coefficients"].index), list(design.columns))

    def test_there_is_no_reference_sheet_without_categorical_predictors(self):
        self.assertNotIn("Reference levels", run()[0])

    def test_a_numeric_category_is_matched_by_its_text_in_a_profile(self):
        for value in (1, "1", 1.0):
            tables = run(Profiles=[{"Name": "P", "Values": {"Treatment": value}}], Times=[2],
                         **{"Categorical predictors": ["Treatment"]})[0]
            np.testing.assert_allclose(tables["Survival curves"]["Survival"], [EXPECTED["fixed"]["survival"][1][1]],
                                       **TOLERANCE)
        self.assertIn("Treatment [1]", run(**{"Categorical predictors": ["Treatment"]})[0]["Coefficients"].index)


class ProfileAndTimeTests(unittest.TestCase):
    def test_profile_errors_name_the_profiles_field(self):
        cases = {
            "level outside the schema": [{"Name": "P", "Values": {"Treatment": 5}}],
            "unknown predictor": [{"Name": "P", "Values": {"Treatment": 0, "Other": 1}}],
            "missing predictor": [{"Name": "P", "Values": {}}],
            "not a number": [{"Name": "P", "Values": {"Treatment": "high"}}],
            "empty name": [{"Name": " ", "Values": {"Treatment": 0}}],
            "repeated name": [CONTROL, {"Name": "Control", "Values": {"Treatment": 1}}],
            "not an object": ["Control"],
        }
        for label, profiles in cases.items():
            extra = {"Categorical predictors": ["Treatment"]} if label == "level outside the schema" else {}
            self.assertEqual(field_of(lambda p=profiles, e=extra: run(Profiles=p, **e))[0], "Profiles", label)

    def test_a_level_outside_the_schema_lists_the_categories(self):
        _, message = field_of(lambda: run(Profiles=[{"Name": "P", "Values": {"Treatment": 5}}],
                                          **{"Categorical predictors": ["Treatment"]}))
        self.assertIn("Treatment", message)
        self.assertIn("0, 1", message)

    def test_times_must_be_strictly_increasing_and_not_negative(self):
        for times in ([0, 8, 2], [0, 2, 2], [-1, 2], [1, np.nan], [1, np.inf], [1, "x"], [True]):
            self.assertEqual(field_of(lambda t=times: run(Profiles=[CONTROL], Times=t))[0], "Times", times)

    def test_curves_start_from_one_at_time_zero_and_stay_inside_zero_one(self):
        tables, _, _ = run(Profiles=[CONTROL, TREATED], Times=[0, 1e-12, 1, 1e3, 1e12])
        survival = tables["Survival curves"]["Survival"]
        self.assertEqual(survival.iloc[0], 1.0)
        self.assertTrue(((survival >= 0) & (survival <= 1)).all())
        self.assertTrue(np.isfinite(survival).all())

    def test_extrapolation_is_flagged_beyond_the_longest_observed_time(self):
        longest = follow_up()["Time"].max()
        tables, _, _ = run(Profiles=[CONTROL], Times=[0, longest, longest * 2])
        self.assertEqual(list(tables["Survival curves"]["Extrapolated"]), ["No", "No", "Yes"])

    def test_empty_times_use_101_points_from_zero_to_the_longest_time(self):
        tables, _, _ = run(Profiles=[CONTROL, TREATED])
        curves = tables["Survival curves"]
        self.assertEqual(len(curves), 202)
        np.testing.assert_allclose(curves["Time"].iloc[:101], np.linspace(0, follow_up()["Time"].max(), 101))
        self.assertEqual(curves["Survival"].iloc[0], 1.0)

    def test_the_graph_needs_a_profile(self):
        self.assertEqual(field_of(lambda: run(**{"Show graph": True}))[0], "Profiles")
        self.assertEqual(field_of(lambda: run(**{"Show graph": "yes"}))[0], "Show graph")

    def test_profiles_leave_the_fit_unchanged(self):
        plain = run()[0]
        with_profiles = run(Profiles=[CONTROL, TREATED], Times=[1, 2])[0]
        pd.testing.assert_frame_equal(plain["Coefficients"], with_profiles["Coefficients"])
        pd.testing.assert_frame_equal(plain["Model fit"], with_profiles["Model fit"])


class BudgetAndCallTests(unittest.TestCase):
    def test_more_than_40000_rows_is_refused_before_any_column_is_read(self):
        frame = pd.DataFrame({"Time": np.ones(40_001), "Status": "event", "Treatment": 0.0})
        with mock.patch.object(aft, "_numbers", side_effect=AssertionError("read")):
            field, message = field_of(lambda: run(frame))
        self.assertEqual(field, "Time")
        self.assertIn("40,000", message)
        frame = frame.iloc[:40_000].copy()
        frame["Treatment"] = np.arange(40_000) % 2
        frame["Time"] = 1 + np.arange(40_000) % 7
        self.assertEqual(run(frame)[0]["Model fit"].iloc[0]["N"], 40_000)

    def test_more_than_eight_predictors_is_refused(self):
        frame = cohort(60)
        for number in range(9):
            frame[f"v{number}"] = np.random.default_rng(number).normal(size=len(frame))
        field, _ = field_of(lambda: aft.run(frame, cohort_options(Predictors=[f"v{n}" for n in range(9)],
                                                                  **{"Categorical predictors": []})))
        self.assertEqual(field, "Predictors")

    def test_more_than_24_coefficients_is_refused_before_the_matrix_exists(self):
        rng = np.random.default_rng(0)
        frame = pd.DataFrame({"t": rng.uniform(1, 9, 300), "d": rng.integers(0, 2, 300), "g": rng.integers(0, 25, 300)})
        opts = {"Time": "t", "Event": "d", "Predictors": ["g"], "Categorical predictors": ["g"],
                "Event value": "1", "Censor value": "0"}
        with mock.patch.object(aft.np, "column_stack", side_effect=AssertionError("matrix built")):
            field, message = field_of(lambda: aft.run(frame, opts))
        self.assertEqual(field, "Predictors")
        self.assertIn("25", message)
        frame["g"] = rng.integers(0, 24, 300)
        self.assertEqual(len(aft.run(frame, opts)[0]["Coefficients"]), 24)

    def test_more_than_5000_profile_time_pairs_is_refused_before_the_fit(self):
        profiles = [{"Name": f"P{n}", "Values": {"Treatment": n % 2}} for n in range(12)]
        with mock.patch.object(aft, "fit_weibull", side_effect=AssertionError("fitted")):
            field, message = field_of(lambda: run(Profiles=profiles, Times=list(np.arange(1, 418, dtype=float))))
            self.assertEqual(field, "Times")
            self.assertIn("5,000", message)
            field, _ = field_of(lambda: run(Profiles=profiles * 2))
            self.assertEqual(field, "Profiles")
        tables, _, _ = run(Profiles=profiles, Times=list(np.arange(1, 417, dtype=float)))
        self.assertEqual(len(tables["Survival curves"]), 4_992)

    def test_checking_the_options_never_fits(self):
        with mock.patch.object(aft, "fit_weibull", side_effect=AssertionError("fitted")):
            plan = aft.check_options(follow_up(), options(Profiles=[CONTROL], Times=[1, 2]))
        self.assertEqual(plan.profile_names, ["Control"])

    def test_one_fit_per_run(self):
        with mock.patch.object(aft, "fit_weibull", wraps=aft.fit_weibull) as fitted, \
                mock.patch.object(aft, "maximise", wraps=aft.maximise) as maximised:
            run(Profiles=[CONTROL, TREATED], Times=[0, 2], **{"Shape mode": "Estimated ML"})
        self.assertEqual((fitted.call_count, maximised.call_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
