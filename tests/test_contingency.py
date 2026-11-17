"""Count layouts, association tests and interval oracles."""
from math import comb
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import optimize, stats

from analisi.contingency import (AUTO, CONDITIONAL, COUNT_MATRIX, FISHER, FISHER_RXC, KATZ, KOOPMAN, MONTE_CARLO,
                                 TREND, YATES, contingency, diagnostic_measures, koopman_risk_ratio)
from analisi.processing import FieldError, INTERVALS, WILSON_BROWN, _intervals
from analisi.extract_rearrange import extract_rearrange


def count_test(counts, **options):
    columns = [f"Outcome {index + 1}" for index in range(len(counts[0]))]
    data = pd.DataFrame(counts, columns=columns)
    return contingency(data, {"Input format": COUNT_MATRIX, "Count columns": columns, **options}).tables


class ContingencyTests(unittest.TestCase):
    def test_observation_mode_preserves_legacy_primary_and_fisher_results(self):
        raw = pd.DataFrame({"Arm": ["A"] * 3 + ["B"] * 4, "Outcome": ["Yes", "Yes", "No", "Yes", "No", "No", "No"]})
        report = contingency(raw, {"Rows": "Arm", "Columns": "Outcome"}).tables
        self.assertEqual(report["Counts"].to_numpy().tolist(), [[1, 2], [3, 1]])
        expected = count_test([[1, 2], [3, 1]], Test=AUTO)
        pd.testing.assert_series_equal(report["Tests"]["Value"], expected["Tests"]["Value"])

    def test_published_woolf_result_and_reversal(self):
        # Original GraphPad odds-ratio guide gives 2.974 [1.787, 4.950].
        report = count_test([[688, 21], [650, 59]])
        effects = report["2 × 2 effects"]
        np.testing.assert_allclose(effects.loc["Odds ratio", ["Estimate", "Lower", "Upper"]].astype(float),
                                   [2.973772893772894, 1.78673703018007, 4.94942740558030], rtol=1e-12)
        forward = float(effects.loc["Relative risk", "Estimate"])
        reversed_report = count_test([[650, 59], [688, 21]])
        np.testing.assert_allclose(reversed_report["2 × 2 effects"].loc["Relative risk", "Estimate"], 1 / forward)
        difference = effects.loc["Difference in proportions"]
        self.assertLess(difference["Lower"], difference["Estimate"])
        self.assertGreater(difference["Upper"], difference["Estimate"])

    def test_exact_fisher_and_yates(self):
        fisher = count_test([[0, 10], [6, 4]], Test=FISHER, **{"Fisher alternative": "First row odds lower",
                                                            "Odds ratio interval": CONDITIONAL})
        # Conditional probability of zero events in first group.
        exact = comb(14, 10) / comb(20, 10)
        self.assertAlmostEqual(fisher["Tests"].loc["p", "Value"], exact)
        self.assertEqual(fisher["2 × 2 effects"].loc["Odds ratio", "Estimate"], 0.)
        self.assertEqual(fisher["2 × 2 effects"].loc["Odds ratio", "Lower"], 0.)
        yates = count_test([[10, 20], [30, 40]], Test=YATES)["Tests"]["Value"]
        self.assertAlmostEqual(yates["Yates-corrected χ²"], .4464285714285714)
        self.assertLess(yates["Yates-corrected χ²"], yates["Pearson χ²"])

    def test_ordered_trend_and_general_effect_size(self):
        values = [[1, 9], [4, 6], [7, 3]]
        tables = count_test(values, Test=TREND)
        test = tables["Tests"]["Value"]
        self.assertAlmostEqual(test["Trend χ²"], 7.5)
        self.assertGreater(test["Trend z"], 0)
        self.assertAlmostEqual(test["Cramér’s V"], np.sqrt(test["Pearson χ²"] / 30))
        reverse = count_test(values[::-1], Test=TREND)
        self.assertAlmostEqual(reverse["Tests"].loc["Trend z", "Value"], -test["Trend z"])
        np.testing.assert_allclose(tables["Expected counts"].to_numpy(), [[4., 6.]] * 3)

    def test_seeded_rx_c_simulation_against_exact_enumeration(self):
        options = {"Test": MONTE_CARLO, "Monte Carlo samples": 10_000, "Seed": 87}
        observed = [[0, 2, 1], [3, 0, 1]]
        # Equal margins make the conditional table probabilities proportional
        # to the products of binomial coefficients of the first row.
        expected = sum(comb(3, i) * comb(2, j) * comb(2, 3 - i - j)
                       for i in range(4) for j in range(3) if 0 <= 3 - i - j <= 2
                       and comb(3, i) * comb(2, j) * comb(2, 3 - i - j) <= 2) / comb(7, 3)
        exact = count_test(observed, Test=FISHER_RXC)["Tests"]["Value"]
        self.assertEqual(exact["p"], expected)
        self.assertEqual(exact["Fixed-margin tables"], 8)
        transposed = count_test(np.asarray(observed).T[::-1, ::-1], Test=FISHER_RXC)["Tests"]["Value"]
        self.assertEqual(exact["p"], transposed["p"])
        pvalue = count_test(observed, **options)["Tests"].loc["p", "Value"]
        self.assertAlmostEqual(pvalue, expected, delta=.025)
        self.assertEqual(pvalue, count_test(observed, **options)["Tests"].loc["p", "Value"])

    def test_r_job_satisfaction_example(self):
        # R's fisher.test help reports 0.7827 for this table.
        values = [[1, 3, 10, 6], [2, 3, 10, 7], [1, 6, 14, 12], [0, 1, 9, 11]]
        test = count_test(values, Test=FISHER_RXC)["Tests"]["Value"]
        self.assertAlmostEqual(test["p"], 0.7827, places=4)
        self.assertEqual(test["Primary test"], FISHER_RXC)

    def test_exact_work_budget_is_invariant_under_transposition(self):
        counts = np.array([[4, 13, 3, 0], [0, 0, 21, 0], [0, 0, 12, 10], [0, 0, 0, 33]])
        first = count_test(counts, Test=FISHER_RXC)["Tests"]["Value"]
        second = count_test(counts.T, Test=FISHER_RXC)["Tests"]["Value"]
        self.assertGreater(first["p"], 0)
        self.assertEqual(first["p"], second["p"])
        self.assertEqual(first["Fixed-margin tables"], second["Fixed-margin tables"])

    def test_exact_work_limit_never_silently_simulates(self):
        for counts, budget in (([[0, 2, 1], [3, 0, 1]], 1), ([[2001, 0, 1], [0, 2, 0]], 100)):
            with self.subTest(counts=counts), patch("analisi.fisher_exact._MAX_WORK", budget):
                with self.assertRaisesRegex(ValueError, "Choose Fisher Monte Carlo"):
                    count_test(counts, Test=FISHER_RXC)
        with self.assertRaisesRegex(ValueError, "Choose Pearson chi-square"):
            count_test([[10_000_001, 1, 0], [0, 0, 1]], Test=FISHER_RXC)

    def test_exact_underflow_keeps_log_probability(self):
        from math import log

        tests = count_test([[700, 0, 0], [0, 700, 1]], Test=FISHER_RXC)["Tests"]["Value"]
        self.assertIsNone(tests["p"])
        self.assertAlmostEqual(tests["log(p)"], log(2) - log(comb(1401, 700)), places=11)

    def test_weighted_extract_result_flows_into_count_analysis(self):
        source = pd.DataFrame({"Arm": ["Treatment", "Treatment", "Control", "Control"],
                               "Event": ["Yes", "No", "Yes", "No"], "N": [4, 2, 3, 6]})
        data = extract_rearrange(source, {"Output table": "Contingency", "Row (treatment) variable": "Arm",
                                        "Column (outcome) variable": "Event", "Count variable": "N"}).tables["Rearranged data"]
        result = contingency(data, {"Input format": COUNT_MATRIX, "Count columns": ["Yes", "No"]}).tables
        self.assertEqual(result["Counts"].to_numpy().tolist(), [[3, 6], [4, 2]])
        self.assertEqual(result["Comparison order"].loc["Event column", "Value"], "Yes")

    def test_missing_zero_margins_and_invalid_counts(self):
        with self.assertRaisesRegex(ValueError, "blank"):
            count_test([[None, 3], [5, 2]])
        tables = count_test([[None, 3], [5, 2], [0, 0]], **{"Blank cells": "Treat blanks as zero"})
        self.assertEqual(tables["Counts"].to_numpy().tolist(), [[0, 3], [5, 2], [0, 0]])
        self.assertEqual(tables["Tests"].loc["Zero-margin rows omitted", "Value"], 1)
        self.assertEqual(tables["Expected counts"].shape, (2, 2))
        for counts in ([[1.5, 3], [5, 2]], [["3.0000000000000001", 3], [5, 2]], [[-1, 3], [5, 2]], [[2**53, 3], [5, 2]]):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                count_test(counts)


def reference_score(r, a, n1, c, n2):
    """Independent oracle: maximize the constrained likelihood by root-finding on its derivative."""
    def derivative(q):
        return (a + c) / q - (n1 - a) * r / (1 - r * q) - (n2 - c) / (1 - q)

    top = min(1., 1 / r)
    eps = 1e-14
    q = optimize.brentq(derivative, eps, top * (1 - eps), xtol=1e-15, rtol=1e-15, maxiter=500)
    p1 = min(r * q, 1.)
    return (a / n1 - r * c / n2) / np.sqrt(p1 * (1 - p1) / n1 + r * r * q * (1 - q) / n2)


class KoopmanTests(unittest.TestCase):
    def test_published_tables(self):
        for (a, n1, c, n2), expected in (
                ((76, 475, 129, 461), (0.5717829457364341, 0.4437731466195718, 0.7348721884503758)),
                ((12, 30, 5, 25), (2, 0.8652526331656134, 4.933971535197795))):
            with self.subTest(a=a):
                np.testing.assert_allclose(koopman_risk_ratio(a, n1, c, n2, 95), expected, rtol=1e-12)

    def test_limits_invert_the_unscaled_score(self):
        z = stats.norm.isf(.025)
        for counts in ((76, 475, 129, 461), (12, 30, 5, 25), (1, 1000, 999, 1000), (3, 10, 5, 7), (0, 10, 5, 20)):
            _, lower, upper = koopman_risk_ratio(*counts, 95)
            with self.subTest(counts=counts):
                if lower > 0:
                    self.assertAlmostEqual(reference_score(lower, *counts), z, places=8)
                self.assertAlmostEqual(reference_score(upper, *counts), -z, places=8)

    def test_level_90_and_statsmodels_agreement(self):
        from statsmodels.stats.proportion import confint_proportions_2indep

        for counts in ((12, 30, 5, 25), (10, 10, 5, 20), (0, 10, 5, 20), (3, 10, 0, 20)):
            with self.subTest(counts=counts):
                _, lower, upper = koopman_risk_ratio(*counts, 90)
                with np.errstate(all="ignore"):
                    expected = confint_proportions_2indep(*counts, method="score", compare="ratio", alpha=.1,
                                                          correction=False)
                np.testing.assert_allclose([lower, upper], np.real(expected), rtol=1e-7, atol=1e-9)
        wide, narrow = koopman_risk_ratio(12, 30, 5, 25, 99), koopman_risk_ratio(12, 30, 5, 25, 90)
        self.assertLess(wide[1], narrow[1])
        self.assertGreater(wide[2], narrow[2])

    def test_boundary_groups(self):
        _, lower, upper = koopman_risk_ratio(0, 10, 5, 20, 95)
        self.assertEqual((lower, 0 < upper < 1.3), (0., True))
        estimate, lower, upper = koopman_risk_ratio(3, 10, 0, 20, 95)
        self.assertEqual((estimate, upper), (np.inf, np.inf))
        self.assertGreater(lower, 1)
        # Events in every subject of both groups: closed form, statsmodels fails here.
        z2 = stats.norm.isf(.025) ** 2
        estimate, lower, upper = koopman_risk_ratio(10, 10, 20, 20, 95)
        self.assertEqual(estimate, 1)
        np.testing.assert_allclose([lower, upper], [10 / (10 + z2), 1 + z2 / 20], rtol=1e-9)
        self.assertTrue(all(np.isnan(koopman_risk_ratio(0, 10, 0, 20, 95))))

    def test_nearly_all_events_at_large_counts(self):
        n = 10**10
        values = count_test([[n - 1, 1], [n - 1, 1]], **{"Relative risk interval": KOOPMAN})
        risk = values["2 × 2 effects"].loc["Relative risk"]
        self.assertEqual(risk["Estimate"], 1)
        # Independent 75-digit inversion of the constrained binomial score.
        self.assertAlmostEqual((1 - risk["Lower"]) * n, 4.737058527920745, places=5)
        self.assertAlmostEqual((risk["Upper"] - 1) * n, 4.737058530164717, places=5)

    def test_swapping_rows_inverts_the_interval(self):
        for counts in ((76, 475, 129, 461), (0, 10, 5, 20), (10, 10, 5, 20), (3, 10, 0, 20), (10, 10, 20, 20)):
            a, n1, c, n2 = counts
            forward, backward = koopman_risk_ratio(*counts, 95), koopman_risk_ratio(c, n2, a, n1, 95)
            with self.subTest(counts=counts):
                with np.errstate(divide="ignore"):
                    inverse = np.reciprocal(np.array([backward[0], backward[2], backward[1]], dtype=float))
                np.testing.assert_allclose(inverse, forward, rtol=1e-8)

    def test_public_choice_changes_only_the_risk_row(self):
        counts = [[12, 18], [5, 20]]
        katz, koopman = count_test(counts), count_test(counts, **{"Relative risk interval": KOOPMAN})
        self.assertEqual(katz["2 × 2 effects"].loc["Relative risk", "Interval method"], KATZ)
        row = koopman["2 × 2 effects"].loc["Relative risk"]
        self.assertEqual(row["Interval method"], KOOPMAN)
        np.testing.assert_allclose(row[["Estimate", "Lower", "Upper"]].astype(float),
                                   [2, 0.8652526331656134, 4.933971535197795], rtol=1e-12)
        pd.testing.assert_frame_equal(katz["2 × 2 effects"].drop("Relative risk"),
                                      koopman["2 × 2 effects"].drop("Relative risk"))
        for name in ("Counts", "Tests", "Expected counts"):
            pd.testing.assert_frame_equal(katz[name], koopman[name])
        order = koopman["Comparison order"]["Value"]
        self.assertEqual((order["Relative risk numerator row"], order["Relative risk denominator row"],
                          order["Event column"]), ("Row 1", "Row 2", "Outcome 1"))
        self.assertIn("(Row 1 events) / (Row 2 events)", order["Relative risk orientation"])
        # Level 90, swapped rows and edge groups through the public path.
        swapped = count_test(counts[::-1], **{"Relative risk interval": KOOPMAN, "Confidence level (%)": 90.})
        forward = count_test(counts, **{"Relative risk interval": KOOPMAN, "Confidence level (%)": 90.})
        f, s = (t["2 × 2 effects"].loc["Relative risk", ["Estimate", "Lower", "Upper"]].astype(float).to_numpy()
                for t in (forward, swapped))
        np.testing.assert_allclose([1 / s[0], 1 / s[2], 1 / s[1]], f, rtol=1e-8)
        zero = count_test([[0, 10], [5, 15]], **{"Relative risk interval": KOOPMAN})["2 × 2 effects"].loc["Relative risk"]
        self.assertEqual((zero["Estimate"], zero["Lower"]), (0, 0))
        self.assertTrue(0 < zero["Upper"] < 2)
        full = count_test([[10, 0], [5, 15]], **{"Relative risk interval": KOOPMAN})["2 × 2 effects"].loc["Relative risk"]
        self.assertEqual(full["Estimate"], 4)
        self.assertTrue(1 < full["Lower"] < 4 < full["Upper"] < np.inf)
        with self.assertRaisesRegex(ValueError, "valid relative risk interval"):
            count_test(counts, **{"Relative risk interval": "Other"})

    def test_zero_margin_rule_is_kept(self):
        with self.assertRaisesRegex(ValueError, "At least two rows and columns"):
            count_test([[10, 0], [20, 0]], **{"Relative risk interval": KOOPMAN})


class BaptistaPikeTests(unittest.TestCase):
    options = {"Odds ratio interval": "Baptista–Pike exact"}

    def test_published_example_includes_tied_probabilities(self):
        # Fagerland (2012), section 5. The lower limit is a probability tie.
        counts = [[7, 27], [1, 33]]
        report = count_test(counts, **self.options)
        effects = report["2 × 2 effects"]
        odds = effects.loc["Odds ratio"]
        self.assertEqual(odds["Interval method"], self.options["Odds ratio interval"])
        self.assertAlmostEqual(odds["Estimate"], 77 / 9)
        self.assertAlmostEqual(odds["Lower"], 1.)
        # The exact root from direct 65-digit binomial weights is slightly
        # below the reported iterative result of 195.495.
        self.assertAlmostEqual(odds["Upper"], 195.49211395464274, places=10)
        legacy = count_test(counts)
        pd.testing.assert_frame_equal(effects.drop("Odds ratio"), legacy["2 × 2 effects"].drop("Odds ratio"))
        pd.testing.assert_frame_equal(report["Tests"], legacy["Tests"])

    def test_boundary_cells_and_confidence_level(self):
        # With one observation in each group the two conditional weights are 1 and OR.
        counts = [[0, 1], [1, 0]]
        for level, bound in ((95., 19.), (90., 9.)):
            with self.subTest(level=level):
                options = {**self.options, "Confidence level (%)": level}
                forward = count_test(counts, **options)["2 × 2 effects"].loc["Odds ratio"]
                reverse = count_test(counts[::-1], **options)["2 × 2 effects"].loc["Odds ratio"]
                np.testing.assert_allclose(forward[["Estimate", "Lower", "Upper"]].astype(float), [0, 0, bound])
                np.testing.assert_allclose(reverse[["Estimate", "Lower", "Upper"]].astype(float),
                                           [np.inf, 1 / bound, np.inf])

    def test_one_zero_uses_the_unadjusted_sample_odds_ratio(self):
        odds = count_test([[0, 10], [5, 5]], **self.options)["2 × 2 effects"].loc["Odds ratio"]
        # Reference from direct binomial weights with 65-digit arithmetic.
        np.testing.assert_allclose(odds[["Estimate", "Lower", "Upper"]].astype(float),
                                   [0, 0, 0.638434756818528097], rtol=1e-12)

    def test_non_square_table_and_work_limit_have_field_error(self):
        for counts, explanation in (([[1, 2, 3], [2, 3, 1]], "two rows and two columns"),
                                    ([[2500, 2500], [2500, 2500]], "4,096")):
            with self.subTest(counts=counts):
                with self.assertRaisesRegex(FieldError, explanation) as raised:
                    count_test(counts, Test="Pearson chi-square", **self.options)
                self.assertEqual(raised.exception.field, "Odds ratio interval")


class DiagnosticMeasureTests(unittest.TestCase):
    options = {"Diagnostic measures": True}

    def test_off_by_default(self):
        tables = count_test([[12, 18], [5, 20]])
        self.assertNotIn("Diagnostic measures", tables)
        self.assertNotIn("Diagnostic orientation", tables)

    def test_estimates_and_oriented_labels(self):
        tables = count_test([[12, 18], [5, 20]], **self.options)
        measures = tables["Diagnostic measures"]
        np.testing.assert_allclose(measures["Estimate"].astype(float),
                                   [12 / 17, 20 / 38, 12 / 30, 20 / 25, 32 / 55], rtol=1e-14)
        self.assertEqual(measures[["Numerator", "Denominator"]].to_numpy().tolist(),
                         [[12, 17], [20, 38], [12, 30], [20, 25], [32, 55]])
        self.assertEqual(set(measures["Interval method"]), {INTERVALS[2]})
        orientation = tables["Diagnostic orientation"]["Value"]
        self.assertEqual((orientation["Test positive (row)"], orientation["Condition present (column)"]),
                         ("Row 1", "Outcome 1"))
        self.assertEqual(orientation["TP (true positive)"], "12: Row 1 × Outcome 1")
        self.assertEqual(orientation["TN (true negative)"], "20: Row 2 × Outcome 2")
        # Existing 2 x 2 sheets are unchanged.
        plain = count_test([[12, 18], [5, 20]])
        for name in plain:
            pd.testing.assert_frame_equal(plain[name], tables[name])

    def test_labels_follow_the_entered_worksheet(self):
        data = pd.DataFrame({"Row title": ["Negative test", "Positive test"], "Absent": [20, 18], "Present": [5, 12]})
        tables = contingency(data, {"Input format": COUNT_MATRIX, "Count columns": ["Absent", "Present"],
                                    "Row titles": "Row title", **self.options}).tables
        orientation = tables["Diagnostic orientation"]["Value"]
        # The first row and column are read as positive and present, whatever their titles say.
        self.assertEqual((orientation["Test positive (row)"], orientation["Condition present (column)"]),
                         ("Negative test", "Absent"))
        self.assertAlmostEqual(tables["Diagnostic measures"].loc["Sensitivity", "Estimate"], 20 / 38)

    def test_interval_methods_use_the_shared_oracles(self):
        for method, level in ((INTERVALS[2], 95.), (INTERVALS[1], 95.), (INTERVALS[1], 90.), (WILSON_BROWN, 80.)):
            with self.subTest(method=method, level=level):
                tables = count_test([[12, 18], [5, 20]], **self.options, **{
                    "Diagnostic interval": method, "Confidence level (%)": level})
                measures = tables["Diagnostic measures"]
                for name, row in measures.iterrows():
                    k, n = int(row["Numerator"]), int(row["Denominator"])
                    if method == INTERVALS[1]:
                        expected = stats.binomtest(k, n).proportion_ci(level / 100, method="exact")
                        np.testing.assert_allclose([row["Lower"], row["Upper"]], [expected.low, expected.high], rtol=1e-9)
                    elif method == INTERVALS[2]:
                        expected = stats.binomtest(k, n).proportion_ci(level / 100, method="wilson")
                        np.testing.assert_allclose([row["Lower"], row["Upper"]], [expected.low, expected.high], rtol=1e-9)
                    self.assertTrue(row["Lower"] <= row["Estimate"] <= row["Upper"], name)
                self.assertEqual(tables["Diagnostic orientation"]["Value"]["Interval method"], method)
                self.assertEqual(tables["Diagnostic orientation"]["Value"]["Confidence level (%)"], level)

    def test_wilson_brown_rare_cases_and_level_constraint(self):
        # Rare events switch to the Poisson bound; the table is [[TP, FP], [FN, TN]].
        measures = diagnostic_measures([[2, 1], [30, 400]], 95, WILSON_BROWN)
        lower, upper = _intervals(WILSON_BROWN, [2, 400, 2, 400, 402], [32, 401, 3, 430, 433], 95)
        np.testing.assert_allclose(measures[["Lower", "Upper"]].to_numpy(), np.column_stack([lower, upper]))
        with self.assertRaisesRegex(ValueError, "50% to below 100%") as caught:
            count_test([[12, 18], [5, 20]], **self.options, **{
                "Diagnostic interval": WILSON_BROWN, "Confidence level (%)": 40.})
        self.assertEqual(caught.exception.field, "Confidence level (%)")
        # Without the diagnostic sheet the level is not restricted.
        count_test([[12, 18], [5, 20]], **{"Diagnostic interval": WILSON_BROWN, "Confidence level (%)": 40.})

    def test_zero_denominator_shows_blank_value_and_reason(self):
        measures = diagnostic_measures([[0, 3], [0, 9]], 95, INTERVALS[2])
        row = measures.loc["Sensitivity"]
        self.assertTrue(np.isnan(row["Estimate"]) and np.isnan(row["Lower"]) and np.isnan(row["Upper"]))
        self.assertEqual((row["Numerator"], row["Denominator"]), (0, 0))
        self.assertIn("denominator TP + FN is 0", row["Note"])
        self.assertEqual(measures.loc["Specificity", "Note"], "")
        self.assertEqual(measures.loc["Positive predictive value", "Estimate"], 0)

    def test_only_two_by_two_tables_and_field_error(self):
        for counts in ([[1, 2, 3], [4, 5, 6]], [[1, 2], [3, 4], [5, 6]]):
            with self.subTest(shape=np.shape(counts)), self.assertRaisesRegex(ValueError, "exactly two rows") as caught:
                count_test(counts, **self.options)
            self.assertEqual(caught.exception.field, "Diagnostic measures")
            count_test(counts)  # The same table without the option still runs.

    def test_observation_input_and_other_methods_stay_intact(self):
        raw = pd.DataFrame({"Test": ["Positive"] * 3 + ["Negative"] * 4,
                            "State": ["Present", "Present", "Absent", "Present", "Absent", "Absent", "Absent"]})
        tables = contingency(raw, {"Rows": "Test", "Columns": "State", **self.options}).tables
        # Levels are sorted alphabetically: Negative/Positive rows, Absent/Present columns.
        self.assertEqual(tables["Diagnostic orientation"]["Value"]["Test positive (row)"], "Negative")
        base = contingency(raw, {"Rows": "Test", "Columns": "State"}).tables
        pd.testing.assert_frame_equal(base["2 × 2 effects"], tables["2 × 2 effects"])
