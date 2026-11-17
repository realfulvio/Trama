"""Pointwise inverse intervals for nonlinear standard curves.

Fixtures under tests/data/nonlinear-inverse are synthetic. They do not depend on
an external packet path. Tolerances are the contract (rtol 2e-9, atol 2e-11).
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import nonlinear_calibration as cal
from analisi import nonlinear_inverse as inv
from analisi.additional import _calibration_figure, _standard_curve
from analisi.curve_models import MODELS
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, active_language, set_language, translate_message
from analisi.stats import nonlinear
from analisi.workbench import analyse


ROOT = Path(__file__).resolve().parent / "data" / "nonlinear-inverse"
RTOL = 2e-9
ATOL = 2e-11
METHOD = "Interpolate a standard curve"
CLIPPED = set(cal.CLIPPED.values())


def cases():
    return json.loads((ROOT / "cases.json").read_text())


def expected():
    return json.loads((ROOT / "expected.json").read_text())


def case(name):
    found = next(item for item in cases() if item["id"] == name)
    return {key: value for key, value in found.items() if key != "id"}


def decay_frame():
    return pd.read_csv(ROOT / "standards-decay.csv")


def decay_options(**extra):
    options = {"Direction": "X from Y", "Curve": "Nonlinear", "Model": "One-phase decay",
               "X": "X", "Y": "Y", "Unknown responses": "Unknown"}
    options.update(extra)
    return options


def columns(x_values, y_values, unknown):
    length = max(len(x_values), len(y_values), len(unknown))

    def pad(values):
        values = list(values)
        return values + [np.nan] * (length - len(values))

    return pd.DataFrame({"X": pad(x_values), "Y": pad(y_values), "Unknown": pad(unknown)})


def solve(name):
    return inv.inverse_band_components(**case(name))


class SolverContractTests(unittest.TestCase):
    def test_fixtures_match_the_independent_contract(self):
        wanted = expected()
        for item in cases():
            with self.subTest(item["id"]):
                got = inv.inverse_band_components(**{key: value for key, value in item.items() if key != "id"})
                target = wanted[item["id"]]
                self.assertEqual(len(got), len(target), got)
                for found, goal in zip(got, target):
                    self.assertEqual(len(found), 2)
                    self.assertLessEqual(found[0], found[1])
                    np.testing.assert_allclose(found, goal, rtol=RTOL, atol=ATOL)

    def test_mean_is_inside_prediction_and_more_replicates_narrow_it(self):
        mean = solve("decay-mean")[0]
        four = solve("decay-prediction-k4")[0]
        one = solve("decay-prediction-k1")[0]
        self.assertGreaterEqual(mean[0], four[0] - 1e-9)
        self.assertLessEqual(mean[1], four[1] + 1e-9)
        self.assertGreaterEqual(four[0], one[0] - 1e-9)
        self.assertLessEqual(four[1], one[1] + 1e-9)
        self.assertLess(mean[1] - mean[0], four[1] - four[0])
        self.assertLess(four[1] - four[0], one[1] - one[0])

    def test_scaling_the_decay_response_keeps_the_same_x_interval(self):
        original = solve("decay-mean")
        base = case("decay-mean")
        scale = 3.5
        theta = np.array(base["parameters"], dtype=float)
        theta[:2] *= scale
        matrix = np.array(base["covariance"], dtype=float)
        magnitudes = np.array([scale, scale, 1.0])
        matrix = matrix * np.outer(magnitudes, magnitudes)
        scaled = inv.inverse_band_components(
            base["model"], theta, matrix, base["residual_variance"] * scale ** 2, base["df"],
            base["response"] * scale, base["low"], base["high"], uncertainty=base["uncertainty"],
            level=base["level"], replicates=base["replicates"])
        np.testing.assert_allclose(scaled, original, rtol=RTOL, atol=ATOL)

    def test_scaling_concentration_scales_the_interval(self):
        original = solve("concentration-stimulate")
        base = case("concentration-stimulate")
        alpha = 4.0
        theta = np.array(base["parameters"], dtype=float)
        theta[2] /= alpha
        matrix = np.array(base["covariance"], dtype=float)
        magnitudes = np.array([1.0, 1.0, 1.0 / alpha, 1.0])
        matrix = matrix * np.outer(magnitudes, magnitudes)
        scaled = inv.inverse_band_components(
            base["model"], theta, matrix, base["residual_variance"], base["df"], base["response"],
            base["low"] / alpha, base["high"] / alpha, uncertainty=base["uncertainty"],
            level=base["level"], replicates=base["replicates"])
        np.testing.assert_allclose(np.asarray(scaled) * alpha, original, rtol=1e-8, atol=1e-8)

    def test_rejected_inputs_raise_before_a_search(self):
        base = case("decay-mean")
        rejected = [
            {**base, "model": "One-phase association"},
            {**base, "df": 0},
            {**base, "df": -1},
            {**base, "level": 0},
            {**base, "level": 100},
            {**base, "replicates": 0},
            {**base, "replicates": True},
            {**base, "replicates": 1.5},
            {**base, "replicates": 2**53 + 1},
            {**base, "residual_variance": -0.01},
            {**base, "covariance": [[1, 0, 0], [0, 1, 0], [0, 0, -1]]},
            {**base, "covariance": [[1, 0.2, 0], [0, 1, 0], [0, 0, 1]]},
            {**base, "low": 3, "high": 1},
            {**base, "parameters": [2, 8]},
            {**base, "response": np.nan},
            {**base, "uncertainty": "None"},
        ]
        for kwargs in rejected:
            with self.subTest(kwargs=sorted(set(kwargs) ^ set(base)) or kwargs.get("model")):
                with self.assertRaises(inv.InverseError):
                    inv.inverse_band_components(**kwargs)
        stimulation = case("concentration-stimulate")
        stimulation["parameters"] = [0, 10, 0, 1.2]
        with self.assertRaises(inv.InverseError):
            inv.inverse_band_components(**stimulation)
        stimulation["parameters"] = [0, 10, 1, 1.2]
        stimulation["low"] = -0.1
        with self.assertRaises(inv.InverseError):
            inv.inverse_band_components(**stimulation)

    def test_zero_covariance_and_a_zero_residual_are_accepted_by_the_solver(self):
        found = solve("singleton-at-domain-end")
        self.assertEqual(found, [(0.0, 0.0)])

    def test_a_tiny_budget_refuses_an_uncertified_set(self):
        account = inv.SearchAccount(query_limit=8, study_limit=8)
        with self.assertRaises(inv.InverseBudgetError) as raised:
            inv.inverse_band_components(**case("decay-mean"), account=account)
        self.assertIn("evaluation budget", str(raised.exception))

    def test_account_is_optional_and_a_new_query_resets_only_its_own_count(self):
        account = inv.SearchAccount()
        first = inv.inverse_band_components(**case("empty-set"), account=account)
        used = account.study
        self.assertEqual(first, [])
        self.assertGreater(used, 0)
        inv.inverse_band_components(**case("singleton-at-domain-end"), account=account)
        self.assertGreater(account.study, used)
        self.assertLess(account.query, account.study)


class AnalysisPathTests(unittest.TestCase):
    def test_prediction_counts_narrow_the_real_decay_and_leave_the_outside_blank(self):
        frame = decay_frame()
        calls = []
        real = cal.nonlinear

        def counted(*args, **kwargs):
            calls.append(nonlinear(*args, **kwargs))
            return calls[-1]

        seen = {}
        real_inverse = inv.inverse_band_components

        def spy(model, parameters, covariance, residual_variance, df, response, low, high, **kwargs):
            seen.setdefault("calls", []).append({
                "covariance": np.array(covariance, copy=True),
                "residual_variance": residual_variance,
                "df": df,
                "response": response,
                "replicates": kwargs["replicates"],
            })
            return real_inverse(model, parameters, covariance, residual_variance, df, response, low, high, **kwargs)

        options = decay_options(**{"Uncertainty": "Prediction", "Confidence level (%)": 95,
                                   "Replicate count column": "k"})
        snapshot = dict(options)
        with patch.object(cal, "nonlinear", side_effect=counted), \
                patch.object(cal.nonlinear_inverse, "inverse_band_components", side_effect=spy):
            result = analyse(METHOD, frame, options)
        self.assertEqual(options, snapshot)
        self.assertEqual(len(calls), 1)
        fit = calls[0]["All"]
        self.assertEqual(len(seen["calls"]), 3)
        for item in seen["calls"]:
            np.testing.assert_allclose(item["covariance"], fit.covariance, rtol=0, atol=0)
            self.assertEqual(item["df"], int(fit.diagnostics["df"]))
            self.assertEqual(item["residual_variance"], float(fit.residual_ss) / item["df"])
        self.assertEqual([item["replicates"] for item in seen["calls"]], [1, 4, 1])
        table = result.tables["Interpolated values"]
        self.assertEqual(list(table.columns),
                         ["Source row", "Response", "Interpolated X", "Status", "Domain low", "Domain high",
                          "X lower", "X upper", cal.INTERVAL_STATUS, "Reason", cal.REPLICATES])
        self.assertEqual(table[cal.REPLICATES].tolist(), [1, 4, 1, 1])
        self.assertLess(table.at[0, "X lower"], table.at[0, "Interpolated X"])
        self.assertLess(table.at[0, "Interpolated X"], table.at[0, "X upper"])
        self.assertLess(table.at[1, "X upper"] - table.at[1, "X lower"],
                        table.at[0, "X upper"] - table.at[0, "X lower"])
        self.assertTrue(pd.isna(table.at[3, "X lower"]))
        self.assertTrue(pd.isna(table.at[3, "X upper"]))
        self.assertEqual(table.at[3, cal.INTERVAL_STATUS], "")
        self.assertEqual(table.at[3, "Reason"], cal.OUTSIDE_REASON)
        self.assertEqual(table.at[0, cal.INTERVAL_STATUS], cal.COMPLETE)
        self.assertEqual(result.tables["Fit diagnostics"].at["Interval note", "Value"], cal.INTERVAL_NOTE)
        self.assertNotIn("Inverse interval components", result.tables)
        labels = [text.get_text() for text in result.figure.axes[0].get_legend().get_texts()]
        self.assertIn("95% prediction interval", labels)
        self.assertNotIn("95% prediction band", labels)

    def test_missing_uncertainty_matches_an_explicit_none(self):
        frame = decay_frame()
        plain = analyse(METHOD, frame, decay_options())
        explicit = analyse(METHOD, frame, decay_options(**{"Uncertainty": "None", "Confidence level (%)": 95,
                                                           "Replicate count column": "k"}))
        self.assertEqual(list(plain.tables), list(explicit.tables))
        for name in plain.tables:
            pd.testing.assert_frame_equal(plain.tables[name], explicit.tables[name])
        self.assertNotIn("X lower", plain.tables["Interpolated values"].columns)
        self.assertNotIn("Interval note", plain.tables["Fit diagnostics"].index)
        labels = [text.get_text() for text in plain.figure.axes[0].get_legend().get_texts()]
        self.assertEqual(labels, ["Standards", "One-phase decay", "Estimates"])

    def test_each_supported_model_reuses_one_fit_and_states_the_note(self):
        specs = {
            "One-phase decay": (np.linspace(0, 8, 12), (2.0, 8.0, 0.6), [4.0, 40.0]),
            "Stimulation (variable slope)": (
                np.concatenate([[0.0], np.geomspace(0.05, 40, 13)]), (1.0, 11.0, 2.0, 1.3), [6.0, -5.0]),
            "Inhibition (variable slope)": (
                np.concatenate([[0.0], np.geomspace(0.05, 40, 13)]), (1.0, 11.0, 2.0, -1.3), [6.0, 30.0]),
            "Stimulation (variable slope, log10 X)": (np.linspace(-2, 2, 13), (1.0, 11.0, 0.0, 1.3), [3.0, 30.0]),
            "Inhibition (variable slope, log10 X)": (np.linspace(-2, 2, 13), (1.0, 11.0, 0.0, -1.3), [9.0, -5.0]),
        }
        for model, (x_values, theta, queries) in specs.items():
            with self.subTest(model):
                curve = MODELS[model].equation(np.asarray(x_values, dtype=float), *theta)
                noise = np.linspace(-0.04, 0.04, len(x_values))
                frame = columns(x_values, curve + noise, queries)
                calls = []

                def counted(*args, _calls=calls, **kwargs):
                    _calls.append(1)
                    return nonlinear(*args, **kwargs)

                with patch.object(cal, "nonlinear", side_effect=counted):
                    result = cal.interpolate_standard_curve(
                        frame, "X", "Y", "Unknown", "Nonlinear", model, "Mean response", 95)
                self.assertEqual(calls, [1])
                table = result.tables["Interpolated values"]
                self.assertEqual(result.tables["Fit diagnostics"].at["Interval note", "Value"], cal.INTERVAL_NOTE)
                inside = table.iloc[0]
                self.assertEqual(inside["Status"], cal.IN_RANGE)
                self.assertIn(inside[cal.INTERVAL_STATUS], CLIPPED)
                self.assertLessEqual(inside["X lower"], inside["Interpolated X"])
                self.assertLessEqual(inside["Interpolated X"], inside["X upper"])
                self.assertGreater(inside["X upper"] - inside["X lower"], 0)
                self.assertNotEqual(inside["Reason"], cal.EXACT_REASON)
                outside = table.iloc[1]
                self.assertEqual(outside["Status"], cal.OUT_OF_RANGE)
                self.assertEqual(outside[cal.INTERVAL_STATUS], "")
                self.assertEqual(outside["Reason"], cal.OUTSIDE_REASON)
                self.assertTrue(pd.isna(outside["X lower"]))
                if model.endswith(", log10 X)"):
                    self.assertLess(inside["Interpolated X"], 0)
                    self.assertIn("10^X", table.columns)

    def test_low_noise_is_not_reported_as_an_exact_fit(self):
        x_values = np.linspace(0, 8, 16)
        rng = np.random.default_rng(7)
        y_values = 2 + 8 * np.exp(-0.6 * x_values) + rng.normal(0, 0.02, size=len(x_values))
        frame = columns(x_values, y_values, [4.0])
        table = cal.interpolate_standard_curve(
            frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay", "Mean response", 95
        ).tables["Interpolated values"]
        self.assertEqual(table.at[0, cal.INTERVAL_STATUS], cal.COMPLETE)
        self.assertGreater(table.at[0, "X upper"] - table.at[0, "X lower"], 1e-4)
        self.assertNotEqual(table.at[0, "Reason"], cal.EXACT_REASON)

    def test_exact_fit_bound_and_unusable_covariance_name_the_reason(self):
        x_values = np.linspace(0, 6, 10)
        y_values = 2 + 8 * np.exp(-0.7 * x_values)
        frame = columns(x_values, y_values, [4.0, 30.0])
        exact = cal.interpolate_standard_curve(
            frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay", "Mean response", 95)
        row = exact.tables["Interpolated values"].iloc[0]
        self.assertEqual(row["Status"], cal.IN_RANGE)
        self.assertEqual(row[cal.INTERVAL_STATUS], cal.UNCERTAINTY_UNAVAILABLE)
        self.assertEqual(row["Reason"], cal.EXACT_REASON)
        self.assertTrue(pd.isna(row["X lower"]))
        outside = exact.tables["Interpolated values"].iloc[1]
        self.assertEqual(outside["Reason"], cal.OUTSIDE_REASON)

        noisy = decay_frame()
        fit = nonlinear(noisy, "X", "Y", "One-phase decay")["All"]
        estimates = cal.interpolate_standard_curve(noisy, "X", "Y", "Unknown", "Nonlinear", "One-phase decay")
        base = estimates.tables["Interpolated values"]
        theta = tuple(float(fit.parameters.at[name, "Estimate"]) for name in MODELS["One-phase decay"].parameters)
        blocked = (float(theta[0]), float(theta[1]), cal.RATE_BOUND / 10)
        table, components = cal._nonlinear_intervals(
            fit, "X", "Y", "One-phase decay", blocked, base, "Mean response", 95.0, None)
        self.assertIsNone(components)
        self.assertEqual(table.at[0, "Reason"], cal.BOUND_REASON)
        self.assertEqual(table.at[0, cal.INTERVAL_STATUS], cal.UNCERTAINTY_UNAVAILABLE)
        fit.covariance = None
        table, _components = cal._nonlinear_intervals(
            fit, "X", "Y", "One-phase decay", theta, base, "Mean response", 95.0, None)
        self.assertEqual(table.at[0, "Reason"], cal.COVARIANCE_REASON)
        fit.diagnostics["df"] = 0
        fit.covariance = nonlinear(noisy, "X", "Y", "One-phase decay")["All"].covariance
        table, _components = cal._nonlinear_intervals(
            fit, "X", "Y", "One-phase decay", theta, base, "Mean response", 95.0, None)
        self.assertEqual(table.at[0, "Reason"], cal.DF_REASON)

        stimulation = nonlinear(
            pd.DataFrame({"X": np.geomspace(0.05, 40, 12),
                          "Y": MODELS["Stimulation (variable slope)"].equation(
                              np.geomspace(0.05, 40, 12), 1, 11, 2, 1.3) + 0.05}),
            "X", "Y", "Stimulation (variable slope)")["All"]
        stim_theta = tuple(float(stimulation.parameters.at[name, "Estimate"])
                           for name in MODELS["Stimulation (variable slope)"].parameters)
        stuck = (stim_theta[0], stim_theta[1], stim_theta[2], np.finfo(float).tiny)
        queries = pd.DataFrame({"Source row": [0], "Response": [6.0], "Interpolated X": [2.0],
                                "Status": [cal.IN_RANGE], "Domain low": [0.05], "Domain high": [40.0]})
        table, _components = cal._nonlinear_intervals(
            stimulation, "X", "Y", "Stimulation (variable slope)", stuck, queries, "Mean response", 95.0, None)
        self.assertEqual(table.at[0, "Reason"], cal.BOUND_REASON)

    def test_not_identifiable_and_a_budget_failure_stay_on_the_row(self):
        frame = decay_frame()
        fit = nonlinear(frame, "X", "Y", "One-phase decay")["All"]
        estimates = cal.interpolate_standard_curve(frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay")
        base = estimates.tables["Interpolated values"].copy()
        base.loc[base["Status"] == cal.IN_RANGE, "Status"] = cal.NOT_IDENTIFIABLE
        theta = tuple(float(fit.parameters.at[name, "Estimate"]) for name in MODELS["One-phase decay"].parameters)
        table, components = cal._nonlinear_intervals(
            fit, "X", "Y", "One-phase decay", theta, base, "Mean response", 95.0, None)
        self.assertIsNone(components)
        named = table.loc[table["Status"] == cal.NOT_IDENTIFIABLE]
        self.assertTrue((named[cal.INTERVAL_STATUS] == "").all())
        self.assertTrue((named["Reason"] == cal.IDENTIFIABLE_REASON).all())
        self.assertTrue(named[["X lower", "X upper"]].isna().all().all())

        class Tiny(inv.SearchAccount):
            def __init__(self, query_limit=inv.QUERY_EVALUATIONS, study_limit=inv.STUDY_EVALUATIONS):
                super().__init__(8, 8)

        with patch.object(cal.nonlinear_inverse, "SearchAccount", Tiny):
            failed = cal.interpolate_standard_curve(
                frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay", "Mean response", 95)
        reasons = failed.tables["Interpolated values"]["Reason"].tolist()
        self.assertIn("evaluation budget", reasons[0])
        self.assertEqual(failed.tables["Interpolated values"].at[0, cal.INTERVAL_STATUS], cal.UNCERTAINTY_UNAVAILABLE)
        self.assertEqual(reasons[-1], cal.OUTSIDE_REASON)

    def test_disconnected_components_do_not_fill_the_gap(self):
        frame = decay_frame()
        real_inverse = inv.inverse_band_components

        def two(model, parameters, covariance, residual_variance, df, response, low, high, **kwargs):
            found = real_inverse(
                model, parameters, covariance, residual_variance, df, response, low, high, **kwargs)
            if len(found) != 1:
                return found
            _left, right = found[0]
            if right + 1.0 < high:
                return [found[0], (high - 0.25, high)]
            return found

        with patch.object(cal.nonlinear_inverse, "inverse_band_components", side_effect=two):
            result = cal.interpolate_standard_curve(
                frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay", "Mean response", 95)
        table = result.tables["Interpolated values"]
        disconnected = table.loc[table[cal.INTERVAL_STATUS] == cal.DISCONNECTED]
        self.assertEqual(len(disconnected), 3)
        self.assertTrue(disconnected[["X lower", "X upper"]].isna().all().all())
        components = result.tables[cal.COMPONENTS]
        self.assertEqual(list(components.columns), ["Source row", "Component", "X lower", "X upper"])
        self.assertEqual(components["Component"].tolist(), [1, 2, 1, 2, 1, 2])
        for source, group in components.groupby("Source row"):
            self.assertGreater(group["X lower"].iloc[1], group["X upper"].iloc[0], source)
        figure = _calibration_figure(frame, decay_options(), result)
        drawn = [tuple(line.get_xdata()) for line in figure.axes[0].lines if line.get_color() == "#9a3412"]
        self.assertEqual(len(drawn), 6)
        for source, group in components.groupby("Source row"):
            pieces = [tuple(pair) for pair in group[["X lower", "X upper"]].to_numpy()]
            self.assertIn(pieces[0], drawn)
            self.assertIn(pieces[1], drawn)
            union = (pieces[0][0], pieces[1][1])
            self.assertNotIn(union, drawn)

        def missing(*_args, **_kwargs):
            return [(7.5, 7.9)]

        with patch.object(cal.nonlinear_inverse, "inverse_band_components", side_effect=missing):
            missed = cal.interpolate_standard_curve(
                frame, "X", "Y", "Unknown", "Nonlinear", "One-phase decay", "Mean response", 95)
        missed_table = missed.tables["Interpolated values"]
        self.assertEqual(missed_table.at[0, cal.INTERVAL_STATUS], cal.UNCERTAINTY_UNAVAILABLE)
        self.assertEqual(missed_table.at[0, "Reason"], "The interval search did not contain the point estimate.")
        self.assertNotIn(cal.COMPONENTS, missed.tables)

    def test_a_singleton_at_the_low_end_is_clipped_low_and_drawn_as_a_bar(self):
        frame = decay_frame()
        fit = nonlinear(frame, "X", "Y", "One-phase decay")["All"]
        estimates = pd.DataFrame({
            "Source row": [0], "Response": [10.0], "Interpolated X": [0.0], "Status": [cal.IN_RANGE],
            "Domain low": [0.0], "Domain high": [8.0],
        })
        theta = tuple(float(fit.parameters.at[name, "Estimate"]) for name in MODELS["One-phase decay"].parameters)

        def point(*_args, **_kwargs):
            return [(0.0, 0.0)]

        with patch.object(cal.nonlinear_inverse, "inverse_band_components", side_effect=point):
            table, components = cal._nonlinear_intervals(
                fit, "X", "Y", "One-phase decay", theta, estimates, "Mean response", 95.0, None)
        self.assertIsNone(components)
        self.assertEqual(table.at[0, cal.INTERVAL_STATUS], "Clipped low")
        self.assertEqual(table.at[0, "X lower"], 0.0)
        self.assertEqual(table.at[0, "X upper"], 0.0)
        built = cal.StandardCurve(
            {"Interpolated values": table}, curve=np.array(fit.curve, copy=True), model="One-phase decay",
            uncertainty="Mean response", level=95.0)
        figure = _calibration_figure(frame, decay_options(), built)
        markers = [line for line in figure.axes[0].lines if line.get_color() == "#9a3412"]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].get_marker(), "|")
        self.assertEqual([text.get_text() for text in figure.axes[0].get_legend().get_texts()].count(
            "95% mean response interval"), 1)

    def test_dialog_checks_reject_association_level_counts_and_too_many_queries(self):
        frame = decay_frame()
        options = decay_options(**{"Uncertainty": "Mean response", "Confidence level (%)": 95,
                                   "Model": "One-phase association"})
        with patch.object(cal, "nonlinear", side_effect=AssertionError("searched")):
            with self.assertRaises(FieldError) as raised:
                cal.check_nonlinear_inverse(frame, options)
            self.assertEqual(raised.exception.field, cal.UNCERTAINTY)
            with self.assertRaises(FieldError) as raised:
                cal.interpolate_standard_curve(
                    frame, "X", "Y", "Unknown", "Nonlinear", "One-phase association", "Prediction", 95)
            self.assertEqual(raised.exception.field, cal.UNCERTAINTY)
            options["Model"] = "One-phase decay"
            options["Confidence level (%)"] = 100
            with self.assertRaises(FieldError) as raised:
                cal.check_nonlinear_inverse(frame, options)
            self.assertEqual(raised.exception.field, cal.LEVEL)

        counted = frame.copy()
        counted["k"] = [1, 1.5, 1, 1, np.nan, np.nan, np.nan, np.nan, np.nan]
        with self.assertRaises(FieldError) as raised:
            cal.interpolate_standard_curve(
                counted, "X", "Y", "Unknown", "Nonlinear", "One-phase decay", "Prediction", 95, "k")
        self.assertEqual(raised.exception.field, cal.COUNT)
        counted["k"] = [2**53, 1, 1, 1, np.nan, np.nan, np.nan, np.nan, np.nan]
        accepted = cal.replicate_counts(counted, "k", "Unknown", ("X", "Y"))
        self.assertEqual(int(accepted[0]), 2**53)
        counted["k"] = pd.Series([2**53 + 1, 1, 1, 1, np.nan, np.nan, np.nan, np.nan, np.nan], dtype=object)
        with self.assertRaises(FieldError) as raised:
            cal.replicate_counts(counted, "k", "Unknown", ("X", "Y"))
        self.assertEqual(raised.exception.field, cal.COUNT)

        many = pd.DataFrame({
            "X": [0, 1, 2, 3, 4, 5, 6, 8] + [np.nan] * 249,
            "Y": [10, 8, 6, 5, 4, 3.5, 3, 2.5] + [np.nan] * 249,
            "Unknown": [4.0] * 257,
        })
        with patch.object(cal, "nonlinear", side_effect=AssertionError("searched")):
            cal.check_nonlinear_inverse(many.iloc[:256].reset_index(drop=True), decay_options(**{
                "Uncertainty": "Mean response", "Confidence level (%)": 95}))
            with self.assertRaises(FieldError) as raised:
                cal.check_nonlinear_inverse(many, decay_options(**{
                    "Uncertainty": "Mean response", "Confidence level (%)": 95}))
            self.assertEqual(raised.exception.field, cal.UNKNOWN_RESPONSES)
            self.assertIn("256", str(raised.exception))

    def test_visibility_follows_the_model_and_keeps_the_historical_call(self):
        hidden = {"Unknown responses": True, "Unknown X": False, "Model": True, "Uncertainty": False,
                  "Confidence level (%)": False, "Replicate count column": False}
        self.assertEqual(cal.calibration_visibility("X from Y", "Nonlinear", "Prediction"), hidden)
        for model in cal.INVERSE_INTERVAL_MODELS:
            shown = cal.calibration_visibility("X from Y", "Nonlinear", "Prediction", model)
            self.assertTrue(shown[cal.UNCERTAINTY], model)
            self.assertTrue(shown[cal.LEVEL], model)
            self.assertTrue(shown[cal.COUNT], model)
            mean = cal.calibration_visibility("X from Y", "Nonlinear", "Mean response", model)
            self.assertTrue(mean[cal.LEVEL], model)
            self.assertFalse(mean[cal.COUNT], model)
        association = cal.calibration_visibility(
            "X from Y", "Nonlinear", "Mean response", "One-phase association")
        self.assertFalse(association[cal.UNCERTAINTY])
        self.assertFalse(association[cal.LEVEL])
        self.assertEqual(cal.INVERSE_INTERVAL_MODELS[0], "One-phase decay")

    def test_dialog_copy_matches_the_engine_and_has_an_italian_catalog(self):
        english = CATALOGS["en"]
        self.assertEqual(english["calib.inverse_nonlinear.note"], cal.INTERVAL_NOTE)
        self.assertEqual(english["calib.inverse_nonlinear.association"],
                         "Inverse intervals are not available for One-phase association. Choose None.")
        self.assertEqual(english["calib.inverse_nonlinear.queries"],
                         "Inverse intervals accept at most 256 unknown responses.")
        self.assertEqual(english["calib.inverse_nonlinear.level"],
                         "Choose a confidence level strictly between 0 and 100.")
        self.assertEqual(set(k for k in english if k.startswith("calib.inverse_nonlinear.")),
                         set(k for k in CATALOGS["it"] if k.startswith("calib.inverse_nonlinear.")))
        previous = active_language()
        set_language("it")
        try:
            association = translate_message(english["calib.inverse_nonlinear.association"], "calib.inverse_nonlinear.")
            self.assertNotEqual(association, english["calib.inverse_nonlinear.association"])
            self.assertIn("None", association)
            row = 'Column "k" needs a whole number of replicates between 1 and 9007199254740992 on row 2.'
            translated = translate_message(row, "calib.inverse_nonlinear.")
            self.assertIn("k", translated)
            self.assertIn("9007199254740992", translated)
            self.assertIn("2", translated)
            self.assertNotIn("needs a whole number", translated)
        finally:
            set_language(previous)


if __name__ == "__main__":
    unittest.main()
