"""Exact binomial test of two observed categories: engine, validation and the Pearson path left untouched.

The oracle below sums exact rational masses (``fractions.Fraction``). It shares no code with the engine,
and the frozen values in tests/data/exact_binomial/expected.json are synthetic.
"""
import json
import time
import tracemalloc
import unittest
from fractions import Fraction
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from scipy.special import betaincinv
from scipy.stats import binom, binomtest

from analisi.data import Dataset
from analisi.exact_binomial import TIE_TOLERANCE, clopper_pearson, confidence_level, two_sided
from analisi.field_error import FieldError
from analisi.workbench import GRAPH_METHODS, analyse

DATA = Path(__file__).parent / "data" / "exact_binomial"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = "Compare observed distribution with expected"
LEGACY = {"Observed counts": "Count", "Row titles": "Row title",
          "Expected distribution": "Weights in a column", "Expected values": "Weight"}
EXACT = {**LEGACY, "Test method": "Exact binomial", "Confidence level (%)": 95.0}


def masses(n, p):
    return [comb(n, j) * p**j * (1 - p)**(n - j) for j in range(n + 1)]


def oracle(n, p, k):
    """Inclusive tails and the mass-ordered two-sided sum, ties kept within the engine's tolerance."""
    pmf = masses(n, p)
    limit = pmf[k] * (1 + Fraction(1, 10**7))
    return (float(sum(pmf[:k + 1])), float(sum(pmf[k:])), float(sum(value for value in pmf if value <= limit)))


def counts(first, second, **extra):
    return pd.DataFrame({"Row title": ["A", "B"], "Count": [first, second], **extra})


def two_rows(first, second):
    return {"Observed counts": "Count", "Row titles": "Row title", "Test method": "Exact binomial"}, counts(first, second)


def run(frame=None, options=EXACT):
    return analyse(METHOD, pd.read_csv(DATA / "counts.csv") if frame is None else frame, options)


def error_field(frame, options):
    with unittest.TestCase().assertRaises(FieldError) as caught:
        run(frame, options)
    return caught.exception.field


class ExactBinomialTests(unittest.TestCase):
    def test_frozen_fixture_and_table_layout(self):
        result = run()
        self.assertEqual(list(result.tables), ["Test", "Categories"])
        self.assertIsNone(result.figure)
        self.assertNotIn(METHOD, GRAPH_METHODS)
        report = result.tables["Test"]["Value"]
        self.assertEqual(list(report.index), ["Total count", "Null proportion", "Observed proportion", "p lower", "p upper",
                                              "p", "CI lower", "CI upper", "Confidence level (%)", "Method"])
        for key, value in EXPECTED.items():
            self.assertAlmostEqual(report[key] / value, 1.0, places=11, msg=key)
        self.assertEqual((report["Total count"], report["Method"]), (100, "Exact binomial"))
        self.assertAlmostEqual(report["Null proportion"], 0.2, places=15)
        self.assertAlmostEqual(report["Observed proportion"], 0.07, places=15)
        self.assertEqual(report["Confidence level (%)"], 95.0)
        categories = result.tables["Categories"]
        self.assertEqual(list(categories.columns), ["Category", "Observed", "Expected"])
        self.assertEqual(categories["Category"].tolist(), ["Signal $", "Other"])
        self.assertEqual(categories["Observed"].tolist(), [7, 93])
        np.testing.assert_allclose(categories["Expected"], [20, 80])

    def test_the_two_sided_value_is_not_twice_the_smaller_tail(self):
        report = run().tables["Test"]["Value"]
        self.assertGreater(abs(report["p"] - 2 * report["p lower"]), 1e-5)
        # The interval is equal-tailed and the test is mass-ordered: the decisions can differ.
        self.assertLess(report["p"], 0.05)
        self.assertGreater(report["CI upper"], 0.0)

    def test_weights_and_expected_counts_agree(self):
        weights = run().tables["Test"]["Value"]
        by_counts = run(options={**EXACT, "Expected distribution": "Expected counts in a column",
                                 "Expected values": "Expected"}).tables["Test"]["Value"]
        for key in EXPECTED:
            self.assertAlmostEqual(weights[key], by_counts[key], places=14)

    def test_random_tables_match_the_rational_oracle(self):
        rng = np.random.default_rng(93)
        for trial in range(250):
            n = int(rng.integers(1, 160))
            p = Fraction(1, 2) if trial % 4 == 0 else Fraction(int(rng.integers(1, 100)), 100)
            k = int(rng.integers(0, n + 1))
            options, frame = two_rows(k, n - k)
            weights = pd.DataFrame({"Weight": [p.numerator, p.denominator - p.numerator]})
            report = run(pd.concat([frame, weights], axis=1),
                         {**options, "Expected distribution": "Weights in a column",
                          "Expected values": "Weight"}).tables["Test"]["Value"]
            lower, upper, both = oracle(n, p, k)
            with self.subTest(n=n, p=p, k=k):
                self.assertAlmostEqual(report["p lower"], lower, delta=max(1e-14, 1e-11 * lower))
                self.assertAlmostEqual(report["p upper"], upper, delta=max(1e-14, 1e-11 * upper))
                self.assertAlmostEqual(report["p"], both, delta=max(1e-14, 1e-10 * both))

    def test_ties_are_included_by_numeric_parity(self):
        # Binomial(4, 1/2): the masses 1, 4, 6, 4, 1 over 16 tie in pairs. Observed 1 gives (1 + 4 + 4 + 1) / 16.
        options, frame = two_rows(1, 3)
        report = run(frame, {**options, "Expected distribution": "Equal proportions"}).tables["Test"]["Value"]
        self.assertEqual(report["p"], 0.625)
        self.assertEqual(report["p lower"], 0.3125)
        self.assertEqual(report["p upper"], 0.9375)
        report = run(counts(2, 2), {**options, "Expected distribution": "Equal proportions"}).tables["Test"]["Value"]
        self.assertEqual(report["p"], 1.0)

    def test_far_tails_keep_relative_precision(self):
        # 1 - cdf would return 0 or rounding noise here; the survival function keeps every digit.
        for n, p, k in [(1000, Fraction(1, 100), 100), (600, Fraction(1, 20), 150), (400, Fraction(99, 100), 300)]:
            options, frame = two_rows(k, n - k)
            weights = pd.DataFrame({"Weight": [p.numerator, p.denominator - p.numerator]})
            report = run(pd.concat([frame, weights], axis=1), {**options, "Expected distribution": "Weights in a column",
                                                               "Expected values": "Weight"}).tables["Test"]["Value"]
            lower, upper, both = oracle(n, p, k)
            with self.subTest(n=n, p=p, k=k):
                smallest = min(lower, upper)
                self.assertLess(smallest, 1e-30)
                self.assertAlmostEqual(report["p lower"] / lower, 1.0, places=9)
                self.assertAlmostEqual(report["p upper"] / upper, 1.0, places=9)
                self.assertAlmostEqual(report["p"] / both, 1.0, places=9)

    def test_two_sided_p_agrees_with_scipy_where_scipy_can_allocate(self):
        for n, p0, k in [(1000, 0.3, 260), (1000, 0.3, 340), (999, 0.5, 450), (50_000, 0.01, 540), (1_000_000, 0.2, 199_000)]:
            with self.subTest(n=n, p0=p0, k=k):
                expected = binomtest(k, n, p0).pvalue
                self.assertAlmostEqual(two_sided(k, n, p0) / expected, 1.0, places=9)

    def test_interval_is_clopper_pearson_with_exact_limits_at_the_ends(self):
        report = run().tables["Test"]["Value"]
        self.assertAlmostEqual(report["CI lower"], float(betaincinv(7, 94, 0.025)), places=14)
        self.assertAlmostEqual(report["CI upper"], float(betaincinv(8, 93, 0.975)), places=14)
        # Both equal tails of the interval hold at the stated level.
        self.assertAlmostEqual(float(binom.sf(6, 100, report["CI lower"])), 0.025, places=12)
        self.assertAlmostEqual(float(binom.cdf(7, 100, report["CI upper"])), 0.025, places=12)
        for first, second in [(0, 4), (4, 0), (0, 1), (1, 0)]:
            options, frame = two_rows(first, second)
            report = run(frame, {**options, "Expected distribution": "Equal proportions"}).tables["Test"]["Value"]
            if first == 0:
                self.assertEqual(report["CI lower"], 0.0)
                self.assertGreater(report["CI upper"], 0.0)
            else:
                self.assertEqual(report["CI upper"], 1.0)
                self.assertLess(report["CI lower"], 1.0)
        options, frame = two_rows(0, 4)
        report = run(frame, {**options, "Expected distribution": "Equal proportions"}).tables["Test"]["Value"]
        self.assertAlmostEqual(report["p"], 1 / 8, places=15)
        self.assertEqual((report["p lower"], report["p upper"]), (1 / 16, 1.0))

    def test_all_in_one_category_and_the_inverted_table(self):
        equal = {"Expected distribution": "Equal proportions"}
        for first, second in [(12, 0), (0, 12)]:
            options, frame = two_rows(first, second)
            report = run(frame, {**options, **equal}).tables["Test"]["Value"]
            self.assertEqual(report["Total count"], 12)
            self.assertAlmostEqual(report["p"], 2 / 4096, places=15)
        original = run().tables["Test"]["Value"]
        inverted = run(pd.DataFrame({"Row title": ["Other", "Signal $"], "Count": [93, 7], "Weight": [8, 2]})).tables["Test"]["Value"]
        self.assertAlmostEqual(inverted["p"], original["p"], places=14)
        self.assertAlmostEqual(inverted["p lower"], original["p upper"], places=14)
        self.assertAlmostEqual(inverted["p upper"], original["p lower"], places=14)
        self.assertAlmostEqual(inverted["CI lower"], 1 - original["CI upper"], places=14)
        self.assertAlmostEqual(inverted["CI upper"], 1 - original["CI lower"], places=14)

    def test_level_changes_the_interval_only(self):
        base = run().tables["Test"]["Value"]
        narrow = run(options={**EXACT, "Confidence level (%)": 80.0}).tables["Test"]["Value"]
        wide = run(options={**EXACT, "Confidence level (%)": 99.9}).tables["Test"]["Value"]
        for key in ("Total count", "Null proportion", "Observed proportion", "p lower", "p upper", "p"):
            self.assertEqual(base[key], narrow[key])
            self.assertEqual(base[key], wide[key])
        self.assertLess(narrow["CI upper"] - narrow["CI lower"], base["CI upper"] - base["CI lower"])
        self.assertLess(base["CI upper"] - base["CI lower"], wide["CI upper"] - wide["CI lower"])
        self.assertEqual((narrow["Confidence level (%)"], wide["Confidence level (%)"]), (80.0, 99.9))
        self.assertAlmostEqual(narrow["CI lower"], float(betaincinv(7, 94, 0.1)), places=13)

    def test_level_must_be_finite_and_strictly_inside_the_range(self):
        for bad in (0, 0.0, 100, 100.0, -5, 120, float("nan"), float("inf"), -float("inf"), "high", None, True, 1e-20):
            with self.subTest(level=bad):
                self.assertEqual(error_field(None, {**EXACT, "Confidence level (%)": bad}), "Confidence level (%)")
        for good in (1e-8, 50, 95, 99.99999999999999, "90"):
            with self.subTest(level=good):
                self.assertGreater(confidence_level(good), 0)
        low, high = clopper_pearson(7, 100, 99.99999999999999)
        self.assertTrue(0 < low < 0.07 < high < 1)

    def test_blank_rows_are_skipped_and_labels_stay_literal(self):
        frame = pd.DataFrame({"Row title": ["  $x ", "", "Mid", "", "Last"], "Count": [3, None, "", None, 9],
                              "Weight": [1, None, None, None, 1]})
        result = run(frame)
        self.assertEqual(result.tables["Categories"]["Category"].tolist(), ["  $x ", "Last"])
        self.assertEqual(result.tables["Test"]["Value"]["Total count"], 12)
        self.assertEqual(result.tables["Test"]["Value"]["Null proportion"], 0.5)

    def test_validation_names_the_field(self):
        def three(**kw):
            return pd.DataFrame({"Row title": list("ABC"), "Count": [2, 3, 4], "Weight": [2, 3, 5]}).assign(**kw)
        one = pd.DataFrame({"Row title": ["A", "B"], "Count": [5, None], "Weight": [1, 1]})
        cases = [
            (three(), EXACT, "Observed counts"),
            (one, EXACT, "Observed counts"),
            (counts(0, 0, Weight=[1, 1]), EXACT, "Observed counts"),
            (counts(2.5, 4, Weight=[1, 1]), EXACT, "Observed counts"),
            (counts(-1, 4, Weight=[1, 1]), EXACT, "Observed counts"),
            (counts("x", 4, Weight=[1, 1]), EXACT, "Observed counts"),
            (counts(5_000_001, 5_000_000, Weight=[1, 1]), EXACT, "Observed counts"),
            (counts(1, 1, Weight=[1, 1]), {**EXACT, "Observed counts": "Missing"}, "Observed counts"),
            (counts(1, 1, Weight=[1, 0]), EXACT, "Expected values"),
            (counts(1, 1, Weight=[1, -2]), EXACT, "Expected values"),
            (counts(1, 1, Weight=[1, np.nan]), EXACT, "Expected values"),
            (counts(1, 1, Weight=[1e-300, 1e300]), EXACT, "Expected values"),
            (counts(1, 1, Weight=[1e300, 1e-300]), EXACT, "Expected values"),
            (counts(1, 1, Weight=[1, 1]), {**EXACT, "Expected values": "Count"}, "Expected values"),
            (counts(4, 6, Weight=[4, 5]), {**EXACT, "Expected distribution": "Expected counts in a column"}, "Expected values"),
            (counts(1, 1, Weight=[1, 1]), {**EXACT, "Estimated parameters": 1}, "Estimated parameters"),
            (counts(1, 1, Weight=[1, 1]), {**EXACT, "Estimated parameters": 0.0}, "Estimated parameters"),
            (counts(1, 1, Weight=[1, 1]), {**EXACT, "Test method": "Fisher"}, "Test method"),
            (counts(1, 1, Weight=[1, 1]), {**EXACT, "Row titles": "Nope"}, "Row titles"),
        ]
        for frame, options, field in cases:
            with self.subTest(field=field, options=options):
                self.assertEqual(error_field(frame, options), field)
        run(counts(1, 1, Weight=[1, 1]), {**EXACT, "Estimated parameters": 0})

    def test_three_filled_rows_never_reach_the_engine_with_a_wrong_total(self):
        frame = pd.DataFrame({"Row title": list("ABC"), "Count": [2, 3, 4], "Weight": [2, 3, 5]})
        with self.assertRaisesRegex(FieldError, "exactly two"):
            run(frame)
        report = run(frame, LEGACY).tables["Test"]["Value"]
        self.assertEqual(report["df"], 2)

    def test_total_of_ten_million_is_fast_and_allocates_no_count_sized_array(self):
        options, frame = two_rows(4_998_000, 5_002_000)
        options = {**options, "Expected distribution": "Equal proportions"}
        tracemalloc.start()
        started = time.perf_counter()
        report = run(frame, options).tables["Test"]["Value"]
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertLess(peak, 5_000_000)
        self.assertLess(elapsed, 5.0)
        self.assertEqual(report["Total count"], 10_000_000)
        self.assertAlmostEqual(report["p lower"] + report["p upper"], 1 + float(binom.pmf(4_998_000, 10_000_000, .5)), places=12)
        self.assertAlmostEqual(report["p"], 2 * report["p lower"], places=12)
        options, frame = two_rows(0, 10_000_000)
        report = run(frame, {**options, "Expected distribution": "Equal proportions"}).tables["Test"]["Value"]
        self.assertEqual(report["p"], 0.0)
        self.assertEqual((report["p lower"], report["p upper"], report["CI lower"]), (0.0, 1.0, 0.0))
        self.assertGreater(report["CI upper"], 0.0)
        options, frame = two_rows(5_000_000, 5_000_001)
        with self.assertRaises(FieldError):
            run(frame, {**options, "Expected distribution": "Equal proportions"})

    def test_extreme_proportions_stay_valid(self):
        options, frame = two_rows(1, 9_999_999)
        report = run(frame.assign(Weight=[1, 999_999_999]), {**options, "Expected distribution": "Weights in a column",
                                                              "Expected values": "Weight"}).tables["Test"]["Value"]
        self.assertAlmostEqual(report["Null proportion"], 1e-9, places=20)
        self.assertTrue(0 < report["p"] <= 1 and 0 <= report["p lower"] <= 1 and 0 <= report["p upper"] <= 1)
        self.assertLessEqual(TIE_TOLERANCE, 1e-7)

    def test_pearson_is_the_default_and_the_explicit_key_changes_nothing(self):
        legacy, explicit = run(options=LEGACY).tables, run(options={**LEGACY, "Test method": "Pearson chi-square"}).tables
        self.assertEqual(list(legacy), ["Test", "Categories"])
        for name in legacy:
            assert_frame_equal(legacy[name], explicit[name], check_exact=True)
        self.assertEqual(list(legacy["Test"].index), ["Pearson χ²", "df", "p", "Total count", "Minimum expected count"])
        self.assertEqual(list(legacy["Categories"].columns), ["Category", "Observed", "Expected", "Pearson residual", "Contribution"])
        self.assertAlmostEqual(legacy["Test"].loc["Pearson χ²", "Value"], 10.5625, places=12)
        # The level belongs to the exact test only.
        ignored = run(options={**LEGACY, "Confidence level (%)": 7.0}).tables
        assert_frame_equal(legacy["Test"], ignored["Test"], check_exact=True)

    def test_pearson_errors_keep_their_fields_and_order(self):
        three = pd.DataFrame({"Row title": list("ABC"), "Count": [2, 3, 4], "Weight": [2, 3, 5]})
        self.assertEqual(error_field(three, {**LEGACY, "Estimated parameters": 2}), "Estimated parameters")
        self.assertEqual(error_field(counts(4, 6, Weight=[4, 5]), {**LEGACY, "Expected distribution": "Expected counts in a column"}),
                         "Expected values")

    def test_excluded_cell_removes_its_row(self):
        data = Dataset(pd.DataFrame({"Row title": ["A", "B"], "Count": [7, 93], "Weight": [2, 8]}), excluded={(1, 1)})
        with self.assertRaises(FieldError) as caught:
            run(data.frame(mask_excluded=True))
        self.assertEqual(caught.exception.field, "Observed counts")
        assert run(data.frame(mask_excluded=False)).tables["Test"]["Value"]["Total count"] == 100


if __name__ == "__main__":
    unittest.main()
