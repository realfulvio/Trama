"""Logistic diagnostics, strict classification and profile probability intervals."""
import unittest

import numpy as np
import pandas as pd
from scipy.special import expit

from analisi.logistic_diagnostics import (LOGISTIC_CI, LOGISTIC_CUTOFF, LOGISTIC_DIAGNOSTICS, LOGISTIC_PROFILES,
                                          auc, deviance_residual, logistic_result, pearson_residual)
from analisi.models import logistic_fit, regression
from analisi.processing import FieldError
from analisi.workbench import analyse

METHOD_OPTIONS = {"Response": "Y", "Predictors": ["X"], "Categorical predictors": []}


def logistic_frame():
    """Eight rows at each of X = −1 and X = 1, with outcomes in the proportions 1/4 and 3/4."""
    return pd.DataFrame({
        "X": [-1] * 8 + [1] * 8,
        "Y": [0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1],
    })


def categorical_frame():
    return pd.DataFrame({
        "X": [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1],
        "Group": ["A", "A", "A", "A", "B", "B", "B", "B", "A", "A", "A", "A", "B", "B", "B", "B"],
        "Y": [1, 0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0],
    })


def _fit(frame, predictors=None, categories=None, **extra):
    options = {**METHOD_OPTIONS, "Predictors": predictors or ["X"],
               "Categorical predictors": [] if categories is None else categories, **extra}
    return logistic_result(options, logistic_fit(frame, options["Response"], options["Predictors"],
                                                 options["Categorical predictors"]))


class LogisticFormulaTests(unittest.TestCase):
    def test_boundary_residuals_match_the_stable_limits(self):
        observed = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
        probability = np.array([0.0, 1.0, 1.0, 0.0, 1e-300, 1 - 1e-16])
        pearson = pearson_residual(observed, probability)
        deviance = deviance_residual(observed, probability)
        self.assertEqual(pearson[0], 0.0)
        self.assertEqual(deviance[0], 0.0)
        self.assertEqual(pearson[1], 0.0)
        self.assertEqual(deviance[1], 0.0)
        self.assertEqual(pearson[2], -np.inf)
        self.assertEqual(deviance[2], -np.inf)
        self.assertEqual(pearson[3], np.inf)
        self.assertEqual(deviance[3], np.inf)
        self.assertTrue(np.isfinite(pearson[4]) and pearson[4] < 0)
        self.assertTrue(np.isfinite(deviance[5]) and deviance[5] > 0)
        moderate = np.array([0.2, 0.8])
        outcomes = np.array([0.0, 1.0])
        np.testing.assert_allclose(pearson_residual(outcomes, moderate),
                                   (outcomes - moderate) / np.sqrt(moderate * (1 - moderate)))

    def test_auc_gives_ties_half_credit(self):
        # One tied pair: half credit is 0.875, counting the tie as a miss is 0.75.
        observed = np.array([1, 1, 0, 0])
        probability = np.array([0.9, 0.4, 0.4, 0.1])
        self.assertAlmostEqual(auc(observed, probability), 0.875)

    def test_exact_balanced_design_matches_the_analytic_fit(self):
        frame = logistic_frame()
        threshold = float(regression(frame, "Y", ["X"], [], "Logistic")["Fitted values"]["Fitted"].iloc[0])
        profiles = [{"name": "X -1", "values": {"X": -1}}, {"name": "X 0", "values": {"X": 0}},
                    {"name": "X 1", "values": {"X": 1}}]
        result = _fit(frame, **{LOGISTIC_DIAGNOSTICS: True, LOGISTIC_CUTOFF: threshold, LOGISTIC_PROFILES: profiles,
                                LOGISTIC_CI: 95})
        beta = np.array([0.0, np.log(3)])
        design = np.column_stack((np.ones(16), frame.X))
        probability = expit(design @ beta)
        diagnostics = result.tables["Logistic diagnostics"]
        np.testing.assert_allclose(diagnostics["Probability"], probability, rtol=1e-7, atol=1e-9)
        np.testing.assert_allclose(diagnostics["Pearson residual"],
                                   (frame.Y - probability) / np.sqrt(probability * (1 - probability)),
                                   rtol=1e-7, atol=1e-9)
        sign = np.sign(frame.Y - probability)
        magnitude = np.sqrt(-2 * (frame.Y * np.log(probability) + (1 - frame.Y) * np.log(1 - probability)))
        np.testing.assert_allclose(diagnostics["Deviance residual"], sign * magnitude, rtol=1e-7, atol=1e-9)
        self.assertEqual(diagnostics["Source row"].tolist(), list(range(16)))
        self.assertFalse(bool(diagnostics["Classified positive"].iloc[0]))
        np.testing.assert_array_equal(result.tables["Logistic classification"].to_numpy(), [[6, 2], [2, 6]])
        metrics = result.tables["Logistic fit metrics"]["Value"]
        np.testing.assert_allclose(metrics.loc[["Brier score", "AUC", "Tjur R²"]], [3 / 16, 3 / 4, 1 / 4])
        self.assertIn("In-sample", result.tables["Logistic fit metrics"]["Note"].iloc[0])
        predicted = result.tables["Logistic predictions"]
        np.testing.assert_allclose(predicted["Probability"], [0.25, 0.5, 0.75])
        critical = 1.959963984540054
        expected = []
        for value in (-1, 0, 1):
            eta = np.log(3) * value
            se = np.sqrt((1 + value ** 2) / 3)
            expected.append([expit(eta - critical * se), expit(eta + critical * se)])
        np.testing.assert_allclose(predicted[["CI low", "CI high"]], expected, rtol=1e-7, atol=1e-9)
        self.assertIn("conditional mean probability", predicted["Interval"].iloc[0])
        base = regression(frame, "Y", ["X"], [], "Logistic")
        for name in ("Coefficients", "Model", "Fitted values"):
            pd.testing.assert_frame_equal(result.tables[name], base[name])

    def test_cutoff_equal_to_a_fitted_probability_stays_negative(self):
        frame = logistic_frame()
        fitted = float(regression(frame, "Y", ["X"], [], "Logistic")["Fitted values"]["Fitted"].iloc[0])
        result = _fit(frame, **{LOGISTIC_DIAGNOSTICS: True, LOGISTIC_CUTOFF: fitted})
        group = np.isclose(result.tables["Logistic diagnostics"]["Probability"], fitted)
        self.assertFalse(result.tables["Logistic diagnostics"].loc[group, "Classified positive"].any())

    def test_categorical_profiles_use_the_fit_coding(self):
        frame = categorical_frame()
        profiles = [{"name": "A-zero", "values": {"X": 0, "Group": "A"}},
                    {"name": "B-uno", "values": {"X": 1, "Group": "B"}}]
        result = _fit(frame, ["X", "Group"], ["Group"], **{LOGISTIC_PROFILES: profiles})
        np.testing.assert_allclose(result.tables["Logistic predictions"]["Probability"], [0.25, 0.75],
                                   rtol=1e-6, atol=1e-8)
        self.assertIn("Reference levels", result.tables)

    def test_invalid_cutoff_names_its_field(self):
        with self.assertRaises(FieldError) as caught:
            _fit(logistic_frame(), **{LOGISTIC_DIAGNOSTICS: True, LOGISTIC_CUTOFF: 1.5})
        self.assertEqual(caught.exception.field, LOGISTIC_CUTOFF)

    def test_incomplete_unknown_and_infinite_profiles_name_the_profile_field(self):
        frame = categorical_frame()
        cases = [
            [{"name": "incompleto", "values": {}}],
            [{"name": "nuovo", "values": {"X": 0, "Group": "Z"}}],
            [{"name": "infinito", "values": {"X": np.inf, "Group": "A"}}],
            [{"name": "doppio", "values": {"X": 0, "Group": "A"}},
             {"name": "doppio", "values": {"X": 1, "Group": "B"}}],
        ]
        for profiles in cases:
            with self.subTest(profiles=profiles):
                with self.assertRaises(FieldError) as caught:
                    _fit(frame, ["X", "Group"], ["Group"], **{LOGISTIC_PROFILES: profiles})
                self.assertEqual(caught.exception.field, LOGISTIC_PROFILES)

    def test_confidence_outside_the_open_unit_interval_names_its_field(self):
        profiles = [{"name": "centro", "values": {"X": 0}}]
        with self.assertRaises(FieldError) as caught:
            _fit(logistic_frame(), **{LOGISTIC_PROFILES: profiles, LOGISTIC_CI: 100})
        self.assertEqual(caught.exception.field, LOGISTIC_CI)

    def test_separating_single_outcome_and_rank_use_the_existing_errors(self):
        separated = pd.DataFrame({"X": [-3, -2, -1, 1, 2, 3], "Y": [0, 0, 0, 1, 1, 1]})
        with self.assertRaisesRegex(ValueError, "separat|converg|estim"):
            logistic_fit(separated, "Y", ["X"], [])
        single = pd.DataFrame({"X": [0, 1, 2, 3], "Y": [1, 1, 1, 1]})
        with self.assertRaisesRegex(ValueError, "both outcomes"):
            logistic_fit(single, "Y", ["X"], [])
        rank = pd.DataFrame({"X": [0, 0, 1, 1, 2, 2], "C": [1, 1, 1, 1, 1, 1], "Y": [0, 1, 0, 1, 0, 1]})
        with self.assertRaisesRegex(ValueError, "rank deficient"):
            logistic_fit(rank, "Y", ["X", "C"], [])

    def test_incomplete_rows_and_duplicate_indices_keep_the_source_row(self):
        frame = logistic_frame()
        frame.loc[3, "X"] = np.nan
        frame.index = [0, 0, 2, 3, 4, 4, 6, 7, 8, 9, 10, 10, 12, 13, 14, 15]
        result = _fit(frame, **{LOGISTIC_DIAGNOSTICS: True})
        self.assertEqual(result.tables["Logistic diagnostics"]["Source row"].tolist(),
                         [0, 0, 2, 4, 4, 6, 7, 8, 9, 10, 10, 12, 13, 14, 15])
        self.assertEqual(result.tables["Model"].loc["Incomplete rows", "Value"], 1)

    def test_defaults_leave_the_base_sheets_unchanged(self):
        frame = logistic_frame()
        base = regression(frame, "Y", ["X"], [], "Logistic")
        untouched = logistic_result({**METHOD_OPTIONS, LOGISTIC_DIAGNOSTICS: False, LOGISTIC_PROFILES: []},
                                    logistic_fit(frame, "Y", ["X"], []))
        for name in ("Coefficients", "Model", "Fitted values"):
            pd.testing.assert_frame_equal(untouched.tables[name], base[name])
        self.assertEqual(list(untouched.tables), list(base))


class LogisticDispatchTests(unittest.TestCase):
    def test_empty_request_matches_the_base_sheets_through_analyse(self):
        frame = logistic_frame()
        base = analyse("Multiple regression", frame, {"Family": "Logistic", **METHOD_OPTIONS})
        same = analyse("Multiple regression", frame, {"Family": "Logistic", **METHOD_OPTIONS,
                                                      LOGISTIC_DIAGNOSTICS: False, LOGISTIC_PROFILES: []})
        self.assertEqual(list(base.tables), ["Coefficients", "Model", "Fitted values"])
        for name in base.tables:
            pd.testing.assert_frame_equal(same.tables[name], base.tables[name])

    def test_other_families_ignore_logistic_keys(self):
        frame = pd.DataFrame({"X": [1, 2, 3, 4, 5, 6.0], "Y": [1, 2, 1, 4, 3, 6.0], "Count": [0, 1, 0, 2, 1, 3]})
        linear = {"Family": "Linear", **METHOD_OPTIONS}
        plain = analyse("Multiple regression", frame, linear)
        extra = analyse("Multiple regression", frame, {**linear, LOGISTIC_DIAGNOSTICS: True, LOGISTIC_CUTOFF: 1.5,
                                                       LOGISTIC_PROFILES: [{"name": "x", "values": {"X": 0}}]})
        pd.testing.assert_frame_equal(plain.tables["Coefficients"], extra.tables["Coefficients"])
        poisson = {"Family": "Poisson", "Response": "Count", "Predictors": ["X"], "Categorical predictors": []}
        plain = analyse("Multiple regression", frame, poisson)
        extra = analyse("Multiple regression", frame, {**poisson, LOGISTIC_DIAGNOSTICS: True})
        pd.testing.assert_frame_equal(plain.tables["Coefficients"], extra.tables["Coefficients"])

    def test_analyse_reports_the_fixture_metrics_and_cutoff_field(self):
        frame = logistic_frame()
        base = {"Family": "Logistic", **METHOD_OPTIONS}
        threshold = float(analyse("Multiple regression", frame, base).tables["Fitted values"]["Fitted"].iloc[0])
        profiles = [{"name": name, "values": {"X": value}} for name, value in (("X -1", -1), ("X 0", 0), ("X 1", 1))]
        result = analyse("Multiple regression", frame, {**base, LOGISTIC_DIAGNOSTICS: True, LOGISTIC_CUTOFF: threshold,
                                                        LOGISTIC_PROFILES: profiles, LOGISTIC_CI: 95})
        metrics = result.tables["Logistic fit metrics"]["Value"]
        np.testing.assert_allclose(metrics.loc[["Brier score", "AUC", "Tjur R²"]], [3 / 16, 3 / 4, 1 / 4])
        np.testing.assert_allclose(result.tables["Logistic predictions"]["Probability"], [0.25, 0.5, 0.75])
        np.testing.assert_array_equal(result.tables["Logistic classification"].to_numpy(), [[6, 2], [2, 6]])
        with self.assertRaises(FieldError) as caught:
            analyse("Multiple regression", frame, {**base, LOGISTIC_DIAGNOSTICS: True, LOGISTIC_CUTOFF: 1.5})
        self.assertEqual(caught.exception.field, LOGISTIC_CUTOFF)

    def test_dialog_labels_keep_english_keys_and_translate(self):
        from analisi.i18n import translate

        english = {
            "analysis.logistic.tab": "Diagnostics and profiles",
            "analysis.logistic.diagnostics": "Logistic diagnostics",
            "analysis.logistic.cutoff": "Logistic cutoff",
            "analysis.logistic.profiles": "Logistic profiles",
            "analysis.logistic.confidence": "Logistic confidence (%)",
        }
        italian = {
            "analysis.logistic.tab": "Diagnostica e profili",
            "analysis.logistic.diagnostics": "Diagnostica logistica",
            "analysis.logistic.cutoff": "Soglia logistica",
            "analysis.logistic.profiles": "Profili logistici",
            "analysis.logistic.confidence": "Confidenza logistica (%)",
        }
        for key, text in english.items():
            self.assertEqual(translate("en", key), text)
            self.assertEqual(translate("it", key), italian[key])
