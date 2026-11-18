"""Cox regression with the exact conditional treatment of tied event times."""
from itertools import combinations
import threading
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from scipy import optimize, stats
from scipy.special import logsumexp

from analisi import cox_exact, cox_outputs, models
from analisi.processing import FieldError
from analisi.workbench import analyse

METHOD = "Cox regression"
EXACT = "Exact (conditional)"
# Synthetic, 11 rows: Marker is empty in the last one. Times 1 and 3 carry two events; row 3 is censored at time 1.
TIED = pd.DataFrame({
    "Time": [1, 1, 1, 2, 3, 3, 4, 4, 5, 6, 7],
    "Status": ["Event", "Event", "Censored", "Event", "Event", "Event", "Censored", "Event", "Event", "Censored",
               "Censored"],
    "Marker": [0, 1, 3, 2, 0, 3, 1, 2, 3, 0, None],
    "Group": list("ABAABAABBAB")})
# The score root of the enumerated likelihood, to 1e-12 (verified independently, see enumerated()).
TIED_BETA = [-0.030136728866362414, 0.51699868904825]
TIED_SE = [0.3418917793255356, 0.8571422430888186]
TIED_LLF = -10.34738621201979
BASE = {"Time": "Time", "Event": "Status", "Predictors": ["Marker", "Group"], "Categorical predictors": ["Group"],
        "Event value": "Event", "Censor value": "Censored"}
OPTIONS = {**BASE, "Ties": EXACT}


def enumerated(x, time, event, beta):
    """Log likelihood, score and information by listing every subset of every risk set (small data only)."""
    x, time, event = np.asarray(x, dtype=float), np.asarray(time), np.asarray(event, dtype=bool)
    value, score, information = 0.0, np.zeros(x.shape[1]), np.zeros((x.shape[1],) * 2)
    for t in np.unique(time[event]):
        deaths = x[(time == t) & event]
        risk = x[time >= t]
        sums = np.array([sum(rows) for rows in combinations(risk, len(deaths))])
        weights = sums @ beta
        denominator = logsumexp(weights)
        probability = np.exp(weights - denominator)
        mean = probability @ sums
        centred = sums - mean
        value += float(deaths.sum(axis=0) @ beta - denominator)
        score += deaths.sum(axis=0) - mean
        information += (centred.T * probability) @ centred
    return value, score, information


def synthetic(rows=14, columns=2, seed=0, levels=4):
    """Tied times, censored rows at event times and several covariates."""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(rows, columns)).round(1)
    time = rng.integers(1, levels + 1, size=rows).astype(float)
    event = rng.random(rows) < 0.65
    event[:2] = True
    return x, time, event


def frame_of(x, time, event):
    frame = pd.DataFrame(x, columns=[f"X{i}" for i in range(x.shape[1])])
    return frame.assign(Time=time, Status=np.where(event, "Event", "Censored"))


def run(frame, **extra):
    options = {**OPTIONS, **extra}
    return analyse(METHOD, frame, options)


def numeric_options(columns, **extra):
    return {"Time": "Time", "Event": "Status", "Predictors": list(columns), "Categorical predictors": [],
            "Event value": "Event", "Censor value": "Censored", "Ties": EXACT, **extra}


def field_of(call):
    try:
        call()
    except FieldError as error:
        return error.field, str(error)
    raise AssertionError("FieldError expected")


class LikelihoodTests(unittest.TestCase):
    def test_terms_match_the_enumeration_of_subsets(self):
        for seed, columns in ((0, 1), (1, 2), (2, 3), (3, 2)):
            x, time, event = synthetic(columns=columns, seed=seed)
            for beta in (np.zeros(columns), np.linspace(0.3, -0.5, columns), np.full(columns, 1.1)):
                value, score, information = cox_exact.log_likelihood(x, time, event, beta)
                want = enumerated(x, time, event, beta)
                np.testing.assert_allclose(value, want[0], rtol=1e-11, atol=1e-11)
                np.testing.assert_allclose(score, want[1], rtol=1e-10, atol=1e-10)
                np.testing.assert_allclose(information, want[2], rtol=1e-10, atol=1e-10)

    def test_score_and_information_are_derivatives_of_the_likelihood(self):
        x, time, event = synthetic(rows=30, columns=3, seed=4, levels=6)
        beta, h = np.array([0.2, -0.3, 0.1]), 1e-5
        _, score, information = cox_exact.log_likelihood(x, time, event, beta)
        for index in range(3):
            step = np.eye(3)[index] * h
            plus, minus = (cox_exact.log_likelihood(x, time, event, beta + sign * step) for sign in (1, -1))
            self.assertAlmostEqual((plus[0] - minus[0]) / (2 * h), score[index], places=6)
            np.testing.assert_allclose((plus[1] - minus[1]) / (2 * h), -information[index], rtol=1e-6, atol=1e-6)

    def test_a_single_event_per_time_is_the_breslow_term(self):
        x, time, _ = synthetic(rows=12, columns=2, seed=5, levels=40)
        time = np.arange(12.0)[::-1] + 1
        event = np.array([True, True, False] * 4)
        beta = np.array([0.4, -0.2])
        value, score, information = cox_exact.log_likelihood(x, time, event, beta)
        eta, want = x @ beta, 0.0
        for t in time[event]:
            risk = time >= t
            weights = np.exp(eta[risk])
            want += eta[time == t][0] - np.log(weights.sum())
        self.assertAlmostEqual(value, want, places=12)
        self.assertTrue(np.isfinite(score).all() and np.isfinite(information).all())

    def test_a_time_that_fails_its_whole_risk_set_adds_nothing(self):
        x = np.array([[1.0], [2.0], [0.5], [3.0], [1.5]])
        time = np.array([1.0, 1.0, 2.0, 3.0, 3.0])
        event = np.array([True, False, True, True, True])
        shape = cox_exact.layout(x, time, event)
        # Time 3 has two events and a risk set of two rows; time 2 and time 1 are informative.
        self.assertEqual(sorted(shape.reads), [3, 5])
        self.assertEqual(shape.tied_times, 1)
        value, score, information = cox_exact.evaluate(shape, np.array([0.7]))
        want = enumerated(x, time, event, np.array([0.7]))
        np.testing.assert_allclose([value, *score, *information.ravel()], [want[0], *want[1], *want[2].ravel()],
                                   rtol=1e-12, atol=1e-12)

    def test_extreme_weights_stay_finite_and_exact(self):
        x, time, event = synthetic(rows=12, columns=1, seed=6)
        x = x * 80
        beta = np.array([3.0])  # exp(eta) overflows: eta reaches about 240 × 3
        value, score, information = cox_exact.log_likelihood(x, time, event, beta)
        want = enumerated(x, time, event, beta)
        np.testing.assert_allclose(value, want[0], rtol=1e-10)
        np.testing.assert_allclose(score, want[1], rtol=1e-8, atol=1e-8)
        np.testing.assert_allclose(information, want[2], rtol=1e-8, atol=1e-8)


class FitTests(unittest.TestCase):
    def test_fixture_matches_the_enumerated_solution(self):
        result = run(TIED)
        coefficients, model = result.tables["Coefficients"], result.tables["Model"]["Value"]
        self.assertEqual(list(result.tables), ["Coefficients", "Model", "Reference levels"])
        self.assertEqual(list(coefficients.index), ["Marker", "Group [B]"])
        np.testing.assert_allclose(coefficients["Estimate"], TIED_BETA, rtol=2e-6)
        np.testing.assert_allclose(coefficients["SE"], TIED_SE, rtol=2e-6)
        half = stats.norm.isf(0.025) * np.array(TIED_SE)
        np.testing.assert_allclose(coefficients["CI 95% low"], np.array(TIED_BETA) - half, rtol=2e-6)
        np.testing.assert_allclose(coefficients["CI 95% high"], np.array(TIED_BETA) + half, rtol=2e-6)
        np.testing.assert_allclose(coefficients["Exp(estimate)"], np.exp(TIED_BETA), rtol=2e-6)
        np.testing.assert_allclose(coefficients["p"], 2 * stats.norm.sf(np.abs(np.array(TIED_BETA) / TIED_SE)),
                                   rtol=1e-5)
        self.assertAlmostEqual(model["Log likelihood"], TIED_LLF, places=9)
        self.assertAlmostEqual(model["AIC"], -2 * TIED_LLF + 4, places=9)
        self.assertEqual((model["N"], model["Incomplete rows"], model["Events"], model["Tied event times"]),
                         (10, 1, 7, 2))
        self.assertEqual(model["Ties"], EXACT)
        self.assertEqual(list(result.tables["Model"].index), ["N", "Incomplete rows", "Log likelihood", "AIC", "Ties",
                                                              "Events", "Tied event times"])
        self.assertEqual(result.tables["Reference levels"]["Reference"].tolist(), ["A"])
        self.assertIsNone(result.figure)

    def test_the_root_is_the_enumerated_maximum_for_random_data(self):
        for seed in range(4):
            x, time, event = synthetic(rows=16, columns=2, seed=seed + 10, levels=5)
            fit = cox_exact.fit_exact(x, time, event)
            solution = optimize.root(lambda b: enumerated(x, time, event, b)[1], fit.beta * 0.9, tol=1e-12,
                                     jac=lambda b: -enumerated(x, time, event, b)[2])
            np.testing.assert_allclose(fit.beta, solution.x, rtol=1e-7, atol=1e-8)
            _, _, information = enumerated(x, time, event, solution.x)
            np.testing.assert_allclose(fit.se, np.sqrt(np.diag(np.linalg.inv(information))), rtol=1e-7)
            self.assertAlmostEqual(fit.log_likelihood, enumerated(x, time, event, solution.x)[0], places=9)

    def test_row_order_does_not_matter(self):
        shuffled = run(TIED.sample(frac=1, random_state=7)).tables["Coefficients"]
        np.testing.assert_allclose(shuffled["Estimate"], TIED_BETA, rtol=2e-6)
        np.testing.assert_allclose(shuffled["SE"], TIED_SE, rtol=2e-6)

    def test_a_censored_row_at_an_event_time_stays_in_the_risk_set(self):
        original = run(TIED).tables["Coefficients"]["Estimate"].to_numpy()

        def moved(time):
            changed = TIED.assign(Time=np.where(TIED.index == 2, time, TIED["Time"]))
            return run(changed).tables["Coefficients"]["Estimate"].to_numpy()

        # Row 2 is censored at time 1, together with two events. At 1.5 it is in the same risk sets (time 1 only).
        np.testing.assert_allclose(moved(1.5), original, rtol=1e-9)
        # Before the events it leaves the risk set of time 1; without it the fit changes too.
        self.assertGreater(np.abs(moved(0.5) - original).max(), 1e-3)
        dropped = run(TIED.drop(index=2)).tables["Coefficients"]["Estimate"].to_numpy()
        self.assertGreater(np.abs(dropped - original).max(), 1e-3)

    def test_untied_times_agree_with_efron_and_breslow(self):
        x, time, event = synthetic(rows=40, columns=2, seed=8, levels=5)
        time = time + np.arange(40) * 1e-3
        frame = frame_of(x, time, event)
        exact = run(frame, Predictors=["X0", "X1"], **{"Categorical predictors": []}).tables["Coefficients"]
        for ties in ("Efron", "Breslow"):
            other = analyse(METHOD, frame, {**numeric_options(["X0", "X1"]), "Ties": ties}).tables["Coefficients"]
            np.testing.assert_allclose(exact["Estimate"], other["Estimate"], rtol=2e-6, atol=1e-8)
            np.testing.assert_allclose(exact["SE"], other["SE"], rtol=2e-6, atol=1e-8)

    def test_translated_and_inversely_scaled_covariates_give_the_same_fit(self):
        x, time, event = synthetic(rows=30, columns=2, seed=9, levels=5)
        base = frame_of(x, time, event)
        moved = base.assign(X0=base["X0"] * 2500 + 1e6, X1=base["X1"] * 0.001 - 3)
        one = analyse(METHOD, base, numeric_options(["X0", "X1"])).tables
        two = analyse(METHOD, moved, numeric_options(["X0", "X1"])).tables
        for column, factor in (("Estimate", 1), ("SE", 1)):
            np.testing.assert_allclose(two["Coefficients"][column].to_numpy() * [2500, 0.001],
                                       one["Coefficients"][column].to_numpy(), rtol=1e-6)
        self.assertAlmostEqual(two["Model"]["Value"]["Log likelihood"], one["Model"]["Value"]["Log likelihood"],
                               places=8)
        self.assertAlmostEqual(two["Model"]["Value"]["AIC"], one["Model"]["Value"]["AIC"], places=8)

    def test_text_codes_a_categorical_predictor_and_incomplete_rows(self):
        frame = TIED.assign(Status=TIED["Status"].str.replace("Event", "dead").str.replace("Censored", "alive"))
        result = run(frame, **{"Event value": "dead", "Censor value": "alive"})
        np.testing.assert_allclose(result.tables["Coefficients"]["Estimate"], TIED_BETA, rtol=2e-6)
        # A blank group is missing, not a level, and a blank status leaves the row out as well.
        gaps = frame.copy()
        gaps.loc[0, "Group"] = None
        gaps.loc[4, "Status"] = None
        model = run(gaps, **{"Event value": "dead", "Censor value": "alive"}).tables["Model"]["Value"]
        self.assertEqual((model["N"], model["Incomplete rows"]), (8, 3))

    def test_three_levels_use_the_first_sorted_level_as_reference(self):
        x, time, event = synthetic(rows=30, columns=1, seed=11, levels=5)
        frame = frame_of(x, time, event).assign(Arm=np.resize(["c", "a", "b"], 30))
        options = {**numeric_options(["X0", "Arm"]), "Categorical predictors": ["Arm"]}
        tables = analyse(METHOD, frame, options).tables
        self.assertEqual(list(tables["Coefficients"].index), ["X0", "Arm [b]", "Arm [c]"])
        self.assertEqual(tables["Reference levels"].loc["Arm", "Reference"], "a")

    def test_coefficients_and_intervals_are_computed_once(self):
        with mock.patch.object(cox_exact, "fit_exact", wraps=cox_exact.fit_exact) as fitted, \
                mock.patch.object(models, "_report", wraps=models._report) as reported:
            run(TIED)
        self.assertEqual((fitted.call_count, reported.call_count), (1, 1))

    def test_efron_and_breslow_keep_their_own_path_and_sheets(self):
        frame = TIED.assign(Status=TIED["Status"].eq("Event").astype(int))
        legacy = {"Time": "Time", "Event": "Status", "Predictors": ["Marker", "Group"],
                  "Categorical predictors": ["Group"]}
        for ties in ("Efron", "Breslow"):
            got = analyse(METHOD, frame, {**legacy, "Ties": ties}).tables
            want = models.cox_regression(frame, "Time", "Status", ["Marker", "Group"], ["Group"], ties.lower())
            self.assertEqual(list(got), list(want))
            for name in got:
                pd.testing.assert_frame_equal(got[name], want[name], check_exact=True)
        efron = analyse(METHOD, TIED, {**BASE, "Ties": "Efron", cox_outputs.PREDICT: True,
                                       cox_outputs.PROFILES: [{"Label": "A", "Values": {"Marker": 1, "Group": "A"}}]})
        self.assertIn("Predicted survival", efron.tables)
        self.assertEqual(efron.tables["Model"]["Value"].get("Ties"), None)


class RefusalTests(unittest.TestCase):
    def test_outputs_built_on_the_baseline_are_refused_on_their_control(self):
        for field, extra in (("Predict survival", {"Predict survival": True}),
                             ("Cox diagnostics", {"Cox diagnostics": True}),
                             ("Schoenfeld residuals", {"Schoenfeld residuals": True}),
                             ("Graph display", {"Graph display": "Predicted survival"}),
                             ("Graph display", {"Graph display": "Schoenfeld vs time"})):
            self.assertEqual(field_of(lambda: run(TIED, **extra))[0], field, extra)
        # The first of several is named; profiles that are only stored are not an error.
        self.assertEqual(field_of(lambda: run(TIED, **{"Predict survival": True, "Cox diagnostics": True}))[0],
                         "Predict survival")
        profiles = [{"Label": "A", "Values": {"Marker": 1, "Group": "A"}}]
        self.assertIn("Coefficients", run(TIED, Profiles=profiles, **{"Graph display": "Automatic"}).tables)

    def test_launch_limits_name_the_ties_control_and_never_fall_back(self):
        rows = np.arange(2001)
        frame = pd.DataFrame({"Time": rows // 2 + 1, "Status": np.where(rows % 3, "Event", "Censored"),
                              "Marker": rows % 7, "Group": np.where(rows % 2, "A", "B")})
        field, message = field_of(lambda: run(frame))
        self.assertEqual(field, "Ties")
        self.assertIn("2000 complete rows", message)
        # Incomplete rows do not count toward the limit.
        rng = np.random.default_rng(15)
        complete = pd.DataFrame({"Time": rng.permutation(600) + 1.0, "Status": rng.choice(["Event", "Censored"], 600),
                                 "Marker": rng.integers(0, 4, 600), "Group": rng.choice(["A", "B"], 600)})
        blank = pd.DataFrame({"Time": 1.0, "Status": "Event", "Marker": [None] * 1600, "Group": "A"})
        model = run(pd.concat([complete, blank], ignore_index=True)).tables["Model"]["Value"]
        self.assertEqual((model["N"], model["Incomplete rows"]), (600, 1600))
        # Nine columns after coding.
        x, time, event = synthetic(rows=60, columns=1, seed=12, levels=6)
        wide = frame_of(x, time, event).assign(Arm=np.resize(list("abcdefghij"), 60))
        options = {**numeric_options(["X0", "Arm"]), "Categorical predictors": ["Arm"]}
        field, message = field_of(lambda: analyse(METHOD, wide, options))
        self.assertEqual(field, "Ties")
        self.assertIn("8 design columns", message)
        # The work budget: a long risk set of tied events.
        rows = np.arange(1500)
        heavy = pd.DataFrame({"Time": rows // 3 + 1, "Status": ["Event"] * 1500, "Marker": rows % 5,
                              "Group": np.where(rows % 2, "A", "B")})
        field, message = field_of(lambda: run(heavy))
        self.assertEqual(field, "Ties")
        self.assertIn("work budget of 5000000", message)

    def test_validation_precedes_the_engine(self):
        rows = np.arange(1500)
        heavy = pd.DataFrame({"Time": rows // 3 + 1, "Status": ["Event"] * 1500, "Marker": rows % 5,
                              "Group": np.where(rows % 2, "A", "B")})
        with mock.patch.object(cox_exact, "fit_exact") as fitted, mock.patch.object(cox_exact, "layout") as built:
            self.assertEqual(field_of(lambda: run(heavy))[0], "Ties")
        fitted.assert_not_called()
        built.assert_not_called()

    def test_input_errors_name_the_control(self):
        negative = TIED.assign(Time=np.where(TIED.index == 3, -1.0, TIED["Time"]))
        self.assertEqual(field_of(lambda: run(negative)), ("Time", 'Cox regression needs nonnegative times; row 4 of '
                                                                    '"Time" is -1.'))
        self.assertEqual(field_of(lambda: run(TIED.iloc[[0, 2]], Predictors=["Marker"],
                                              **{"Categorical predictors": []}))[0], "Event")
        self.assertEqual(field_of(lambda: run(TIED, Event="Time"))[0], "Event")
        self.assertEqual(field_of(lambda: run(TIED, Predictors=["Marker", "Status"]))[0], "Predictors")
        duplicate = TIED.assign(Twice=TIED["Marker"] * 2)
        self.assertEqual(field_of(lambda: run(duplicate, Predictors=["Marker", "Twice"]))[0], "Predictors")
        # Status codes keep the messages of the other estimators.
        self.assertEqual(field_of(lambda: run(TIED, **{"Event value": "Nothing"}))[0], "Event")
        self.assertEqual(field_of(lambda: run(TIED, **{"Censor value": "Event"}))[0], "Censor value")

    def test_separation_and_constant_predictors_are_errors_on_predictors_and_the_correction_works(self):
        separated = pd.DataFrame({"Time": [1, 1, 2, 2, 3, 4, 5, 6], "Status": ["Event"] * 4 + ["Censored"] * 4,
                                  "Arm": [1, 1, 1, 1, 0, 0, 0, 0]})
        options = {**numeric_options(["Arm"])}
        field, message = field_of(lambda: analyse(METHOD, separated, options))
        self.assertEqual(field, "Predictors")
        self.assertIn("no finite maximum", message)
        # A censored row with Arm = 1 in the late risk sets restores a finite maximum.
        repaired = separated.assign(Arm=[1, 1, 1, 0, 0, 1, 0, 0], Status=["Event"] * 4 + ["Censored", "Event",
                                                                                       "Censored", "Censored"])
        self.assertTrue(np.isfinite(analyse(METHOD, repaired, options).tables["Coefficients"]["SE"]).all())
        constant = TIED.assign(Flat=5.0)
        field, message = field_of(lambda: run(constant, Predictors=["Marker", "Flat"],
                                              **{"Categorical predictors": []}))
        self.assertEqual(field, "Predictors")
        self.assertIn("singular", message)
        # Every informative time is fully tied with its risk set: nothing to estimate.
        every = pd.DataFrame({"Time": [1, 1, 1, 1], "Status": ["Event"] * 4, "Arm": [0, 1, 0, 2]})
        self.assertEqual(field_of(lambda: analyse(METHOD, every, numeric_options(["Arm"])))[0], "Predictors")

    def test_non_convergence_is_bounded_by_the_iteration_limit(self):
        self.assertEqual(cox_exact.MAX_ITERATIONS, 100)
        x, time, event = synthetic(rows=20, columns=2, seed=13, levels=5)
        with mock.patch.object(cox_exact, "MAX_ITERATIONS", 1), \
                mock.patch.object(cox_exact, "DECREMENT_TOLERANCE", 0.0):
            field, message = field_of(lambda: cox_exact.fit_exact(x, time, event))
        self.assertEqual(field, "Predictors")
        self.assertIn("did not converge in 1 iterations", message)


class CancellationTests(unittest.TestCase):
    def test_a_set_token_stops_before_any_result(self):
        token = threading.Event()
        token.set()
        with self.assertRaises(cox_exact.CoxExactCancelled):
            analyse(METHOD, TIED, OPTIONS, cancel=token)

    def test_cancelling_between_iterations_and_inside_a_long_pass(self):
        x, time, event = synthetic(rows=400, columns=2, seed=14, levels=30)
        frame = frame_of(x, time, event)

        class After:
            """An event that reports set after a number of looks, as the UI thread would between two polls."""

            def __init__(self, looks):
                self.looks = looks

            def is_set(self):
                self.looks -= 1
                return self.looks < 0

        for looks in (1, 3, 8, 20):
            with self.assertRaises(cox_exact.CoxExactCancelled):
                analyse(METHOD, frame, numeric_options(["X0", "X1"]), cancel=After(looks))
        # The row loop polls every CHECK_EVERY rows, so a 400-row pass is looked at several times per evaluation.
        counter = After(10 ** 9)
        analyse(METHOD, frame, numeric_options(["X0", "X1"]), cancel=counter)
        self.assertGreater(10 ** 9 - counter.looks, 20)

class TranslationTests(unittest.TestCase):
    def tearDown(self):
        from analisi import i18n
        i18n.set_language("en")

    def test_catalog_parity_and_the_ties_choice(self):
        from analisi import i18n
        english = {key for key in i18n._EN if key.startswith("cox.exact.")}
        self.assertEqual(english, {key for key in i18n._IT if key.startswith("cox.exact.")})
        for key in english:
            self.assertEqual(i18n.placeholders(i18n._EN[key]), i18n.placeholders(i18n._IT[key]), key)
        keys = i18n.fixed_choice_keys(("Efron", "Breslow", EXACT))
        self.assertEqual(keys, {EXACT: "cox.exact.choice"})
        i18n.set_language("it")
        self.assertEqual(i18n.tr(keys[EXACT]), "Esatto (condizionale)")

    def test_every_engine_message_has_an_italian_entry(self):
        from analisi import i18n
        rows = np.arange(2001)
        big = pd.DataFrame({"Time": rows // 2 + 1, "Status": np.where(rows % 3, "Event", "Censored"),
                            "Marker": rows % 7, "Group": np.where(rows % 2, "A", "B")})
        wide = frame_of(*synthetic(rows=60, columns=1, seed=12, levels=6)).assign(Arm=np.resize(list("abcdefghij"), 60))
        heavy = pd.DataFrame({"Time": np.arange(1500) // 3 + 1, "Status": ["Event"] * 1500,
                              "Marker": np.arange(1500) % 5, "Group": np.where(np.arange(1500) % 2, "A", "B")})
        separated = pd.DataFrame({"Time": [1, 1, 2, 2, 3, 4, 5, 6], "Status": ["Event"] * 4 + ["Censored"] * 4,
                                  "Arm": [1, 1, 1, 1, 0, 0, 0, 0]})
        flat = TIED.assign(Flat=5.0)
        negative = TIED.assign(Time=np.where(TIED.index == 3, -1.0, TIED["Time"]))
        arm = {**numeric_options(["Arm"])}
        calls = [
            lambda: run(TIED, **{"Predict survival": True}), lambda: run(TIED, **{"Cox diagnostics": True}),
            lambda: run(TIED, **{"Graph display": "Predicted survival"}), lambda: run(big),
            lambda: analyse(METHOD, wide, {**numeric_options(["X0", "Arm"]), "Categorical predictors": ["Arm"]}),
            lambda: run(heavy), lambda: analyse(METHOD, separated, arm),
            lambda: run(flat, Predictors=["Marker", "Flat"], **{"Categorical predictors": []}),
            lambda: run(negative), lambda: run(TIED.iloc[[0, 2]], Predictors=["Marker"],
                                               **{"Categorical predictors": []}),
            lambda: run(TIED, Event="Time"), lambda: run(TIED, Predictors=["Marker", "Status"]),
            lambda: run(TIED.assign(Twice=TIED["Marker"] * 2), Predictors=["Marker", "Twice"]),
            lambda: run(TIED, **{"Event value": "Nothing"}), lambda: run(TIED, **{"Censor value": "Event"}),
            lambda: run(TIED, **{"Event value": " "}), lambda: run(TIED, Event="Missing"),
            lambda: run(TIED.assign(Marker=TIED["Marker"].astype(object).where(TIED.index != 2, "x"))),
            lambda: run(TIED, Predictors=[]), lambda: run(TIED.assign(Status="Censored")),
            lambda: analyse(METHOD, TIED.assign(Status=[1, 1, 0, 1, 1, 1, 0, 1, 1, 0, 0]),
                            {**BASE, "Ties": EXACT, "Event value": "Event"}),
            lambda: analyse(METHOD, TIED.assign(Status=[1, 1, 0, 1, 1, 1, 0, 1, 1, 0, 0]),
                            {**BASE, "Ties": EXACT, "Event value": "x"}),
        ]
        english = []
        for call in calls:
            try:
                call()
            except FieldError as error:
                english.append(str(error))
            else:
                self.fail("FieldError expected")
        i18n.set_language("it")
        for text in english:
            shown = cox_exact.translate_error(FieldError("x", text))
            self.assertNotEqual(shown, text, text)
            self.assertNotIn("{", shown)
        # Field names come back in their Italian caption, other values literally.
        self.assertIn("Stima sopravvivenza", cox_exact.translate_error(english[0]))
        i18n.set_language("en")
        self.assertEqual(cox_exact.translate_error(FieldError("x", english[0])), english[0])
        self.assertEqual(cox_exact.translate_error("a message nobody catalogued"), "a message nobody catalogued")


class RecipeTests(unittest.TestCase):
    def test_the_ties_choice_lists_exact_after_the_historical_two(self):
        from analisi.additional import EXTRA_METHODS
        self.assertEqual(EXTRA_METHODS[METHOD]["Ties"], ("Efron", "Breslow", EXACT))

    def test_an_older_recipe_still_edits_and_runs(self):
        old = {"Time": "Time", "Event": "Status", "Predictors": ["Marker"], "Categorical predictors": [],
               "Ties": "Efron"}
        frame = TIED.assign(Status=TIED["Status"].eq("Event").astype(int))
        self.assertEqual(list(analyse(METHOD, frame, old).tables), ["Coefficients", "Model"])
        self.assertEqual(list(analyse(METHOD, frame, {**old, "Ties": EXACT}).tables), ["Coefficients", "Model"])


if __name__ == "__main__":
    unittest.main()
