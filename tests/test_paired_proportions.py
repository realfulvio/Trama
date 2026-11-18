"""Paired proportions with McNemar's test: statistics, both input modes, validation, report tables and figure.

Expected numbers come from ``tests/paired_proportions_oracle.py`` (exact binomial sums, statsmodels, SciPy beta
quantiles; no Trama code) and from the frozen synthetic fixtures in ``tests/data/paired_proportions``.
"""
import json
import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analisi.contingency import CONTINGENCY
from analisi.field_error import FieldError
from analisi.paired_proportions import (AFTER, AFTER_NEGATIVE, AFTER_POSITIVE, BEFORE, CHI_SQUARE, COUNT_MATRIX, EXACT,
                                        FORMAT, GRAPH, LEVEL, MID_P, NEGATIVE, OBSERVATIONS, OPTIONS,
                                        PAIRED_PROPORTIONS, POSITIVE, TEST, mcnemar_summary, paired_proportions,
                                        visibility)
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse
from tests import paired_proportions_oracle as oracle

DATA = Path(__file__).parent / "data" / "paired_proportions"
CASES = json.loads((DATA / "cases.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
REPORT = ["N pairs", "Before positive fraction", "After positive fraction", "Difference (after − before)",
          "Discordant pairs", "Chi-square", "p", "Matched odds ratio", "OR CI lower", "OR CI upper"]
TRANSITIONS = ["Unchanged negative", "Gain", "Loss", "Unchanged positive"]


def matrix(counts):
    a, b, c, d = counts
    return pd.DataFrame({"After negative": [a, c], "After positive": [b, d]})


def count_options(**changes):
    return {FORMAT: COUNT_MATRIX, AFTER_NEGATIVE: "After negative", AFTER_POSITIVE: "After positive",
            TEST: EXACT, LEVEL: 95.0, GRAPH: False, **changes}


def observation_options(**changes):
    return {FORMAT: OBSERVATIONS, BEFORE: "Before", AFTER: "After", NEGATIVE: "off", POSITIVE: "on", TEST: EXACT,
            LEVEL: 95.0, GRAPH: False, **changes}


def fixture_observations():
    return pd.read_csv(DATA / "observations.csv", keep_default_na=False)


def summary(result):
    return result.tables["Paired proportions"]["Value"]


def counts_of(result):
    return result.tables["Paired counts"].to_numpy().ravel().tolist()


def empty(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


def same(actual, expected):
    if expected is None:
        return empty(actual)
    if expected == "+inf":
        return actual == math.inf
    return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-11)


class FrozenFixtureTests(unittest.TestCase):
    def test_every_matrix_case_matches_the_frozen_values_and_the_independent_oracle(self):
        for name, case in CASES.items():
            with self.subTest(case=name):
                result = analyse(PAIRED_PROPORTIONS, matrix(case["counts"]),
                                 count_options(**{TEST: case["method"], LEVEL: case["level"]}))
                report = summary(result)
                independent = oracle.reference(case["counts"], case["level"], case["method"])
                for field in REPORT:
                    self.assertTrue(same(report[field], EXPECTED[name][field]), (field, report[field]))
                    self.assertTrue(same(report[field], independent[field]), (field, report[field]))
                self.assertEqual(counts_of(result), case["counts"])

    def test_the_observation_fixture_reproduces_the_orientation_case(self):
        frame = fixture_observations()
        frame.index = [42] * len(frame)
        result = analyse(PAIRED_PROPORTIONS, frame, observation_options(**{GRAPH: True}))
        report = summary(result)
        for field in REPORT:
            self.assertTrue(same(report[field], EXPECTED["direction"][field]), field)
        self.assertEqual(result.tables["Pairs"]["Source row"].tolist(), list(range(1, 17)) + [18])
        self.assertEqual(result.tables["Pairs"]["Transition"].tolist(),
                         ["Unchanged negative"] * 4 + ["Gain"] * 9 + ["Loss"] * 2 + ["Unchanged positive"] * 2)
        self.assertEqual(counts_of(result), [4, 9, 2, 2])
        self.assertEqual([patch.get_height() for patch in result.figure.axes[0].patches], [4, 9, 2, 2])

    def test_the_fixture_orientation_numbers(self):
        report = summary(analyse(PAIRED_PROPORTIONS, matrix([4, 9, 2, 2]), count_options()))
        self.assertAlmostEqual(report["p"], 0.0654296875, places=15)
        self.assertAlmostEqual(report["Difference (after − before)"], 7 / 17, places=15)
        self.assertEqual(report["Matched odds ratio"], 4.5)
        self.assertEqual(report["N pairs"], 17)


class StatisticsTests(unittest.TestCase):
    def test_exact_p_matches_statsmodels_over_a_grid_of_counts(self):
        from statsmodels.stats.contingency_tables import mcnemar
        for b in range(0, 14):
            for c in range(0, 14):
                if b + c == 0:
                    continue
                with self.subTest(b=b, c=c):
                    p = mcnemar_summary(3, b, c, 5, EXACT, 95.0)["p"]
                    self.assertAlmostEqual(p, float(mcnemar(np.array([[3, b], [c, 5]]), exact=True).pvalue),
                                           places=13)

    def test_mid_p_matches_the_independent_oracle(self):
        for b, c in ((9, 2), (3, 3), (0, 6), (4, 7), (25, 12), (3, 4)):
            with self.subTest(b=b, c=c):
                expected = oracle.reference([1, b, c, 1], 95.0, MID_P)["p"]
                self.assertAlmostEqual(mcnemar_summary(1, b, c, 1, MID_P, 95.0)["p"], expected, places=13)

    def test_mid_p_removes_half_of_the_point_probability_from_the_doubled_tail(self):
        b, c = 9, 2
        point = math.comb(b + c, min(b, c)) / 2 ** (b + c)
        exact = mcnemar_summary(1, b, c, 1, EXACT, 95.0)["p"]
        self.assertAlmostEqual(mcnemar_summary(1, b, c, 1, MID_P, 95.0)["p"], exact - point, places=13)

    def test_a_tie_gives_exactly_one_for_the_exact_and_the_mid_p_tests(self):
        for method in (EXACT, MID_P):
            for b in (1, 3, 40, 5000):
                with self.subTest(method=method, b=b):
                    self.assertEqual(mcnemar_summary(2, b, b, 2, method, 95.0)["p"], 1.0)

    def test_chi_square_uses_the_continuity_correction_and_one_degree_of_freedom(self):
        result = mcnemar_summary(4, 9, 2, 2, CHI_SQUARE, 95.0)
        self.assertAlmostEqual(result["chi_square"], 3.272727272727273, places=14)
        self.assertAlmostEqual(result["p"], 0.070440429272088, places=12)
        self.assertEqual(mcnemar_summary(4, 3, 3, 2, CHI_SQUARE, 95.0)["chi_square"], 0.0)
        self.assertEqual(mcnemar_summary(4, 3, 3, 2, CHI_SQUARE, 95.0)["p"], 1.0)
        self.assertEqual(mcnemar_summary(4, 4, 3, 2, CHI_SQUARE, 95.0)["chi_square"], 0.0)

    def test_binomial_tests_leave_the_chi_square_statistic_empty(self):
        for method in (EXACT, MID_P):
            self.assertTrue(empty(mcnemar_summary(4, 9, 2, 2, method, 95.0)["chi_square"]))

    def test_swapping_before_and_after_flips_the_sign_and_inverts_the_odds_ratio_interval(self):
        for b, c in ((9, 2), (1, 12), (4, 3), (30, 31)):
            for method in (EXACT, MID_P, CHI_SQUARE):
                with self.subTest(b=b, c=c, method=method):
                    one = mcnemar_summary(5, b, c, 7, method, 95.0)
                    swapped = mcnemar_summary(5, c, b, 7, method, 95.0)
                    self.assertEqual(one["p"], swapped["p"])
                    self.assertEqual(one["difference"], -swapped["difference"])
                    self.assertAlmostEqual(one["odds_ratio"], 1 / swapped["odds_ratio"], places=12)
                    self.assertAlmostEqual(one["or_lower"], 1 / swapped["or_upper"], places=12)
                    self.assertAlmostEqual(one["or_upper"], 1 / swapped["or_lower"], places=12)

    def test_one_direction_only_gives_infinite_and_zero_limits(self):
        gains = mcnemar_summary(4, 6, 0, 2, EXACT, 95.0)
        self.assertEqual(gains["odds_ratio"], math.inf)
        self.assertEqual(gains["or_upper"], math.inf)
        self.assertGreater(gains["or_lower"], 0)
        losses = mcnemar_summary(4, 0, 6, 2, EXACT, 95.0)
        self.assertEqual(losses["odds_ratio"], 0.0)
        self.assertEqual(losses["or_lower"], 0.0)
        self.assertTrue(math.isfinite(losses["or_upper"]))
        self.assertAlmostEqual(gains["or_lower"], 1 / losses["or_upper"], places=12)

    def test_no_discordant_pairs_gives_p_one_and_empty_estimates_with_a_reason(self):
        for method in (EXACT, MID_P, CHI_SQUARE):
            with self.subTest(method=method):
                result = mcnemar_summary(4, 0, 0, 5, method, 95.0)
                self.assertEqual(result["p"], 1.0)
                for key in ("chi_square", "odds_ratio", "or_lower", "or_upper"):
                    self.assertTrue(empty(result[key]), key)
                self.assertIn("discordant", result["reason"])
                self.assertEqual(result["difference"], 0.0)

    def test_the_odds_ratio_interval_is_conditional_and_ignores_the_test_choice(self):
        intervals = {method: mcnemar_summary(4, 9, 2, 2, method, 90.0) for method in (EXACT, MID_P, CHI_SQUARE)}
        self.assertEqual(len({(v["or_lower"], v["or_upper"]) for v in intervals.values()}), 1)
        expected = oracle.reference([4, 9, 2, 2], 90.0, EXACT)
        self.assertAlmostEqual(intervals[MID_P]["or_lower"], expected["OR CI lower"], places=12)
        self.assertAlmostEqual(intervals[MID_P]["or_upper"], expected["OR CI upper"], places=12)

    def test_no_continuity_adjustment_is_applied_to_zero_counts(self):
        # With c = 0 the odds ratio is infinite, never b / 0.5.
        self.assertEqual(mcnemar_summary(0, 3, 0, 0, EXACT, 95.0)["odds_ratio"], math.inf)

    def test_large_counts_stay_finite_and_inside_the_unit_interval(self):
        for counts in ((5_000_000, 2_000_000, 1_000_000, 2_000_000), (0, 2_500_000, 2_500_000, 5_000_000),
                       (9_999_000, 1, 0, 0), (0, 5_000_000, 4_999_999, 1)):
            for method in (EXACT, MID_P, CHI_SQUARE):
                with self.subTest(counts=counts, method=method):
                    result = mcnemar_summary(*counts, method, 95.0)
                    self.assertTrue(0.0 <= result["p"] <= 1.0, result["p"])
                    self.assertTrue(math.isfinite(result["p"]))
                    self.assertTrue(math.isfinite(result["difference"]))

    def test_an_extreme_tail_keeps_a_positive_p_value(self):
        p = mcnemar_summary(0, 400, 0, 0, EXACT, 95.0)["p"]
        self.assertTrue(0 < p < 1e-100, p)

    def test_the_fractions_come_from_integer_division(self):
        result = mcnemar_summary(10 ** 6, 3, 1, 10 ** 6 + 7, EXACT, 95.0)
        total = 2 * 10 ** 6 + 11
        self.assertEqual(result["before"], (1 + 10 ** 6 + 7) / total)
        self.assertEqual(result["after"], (3 + 10 ** 6 + 7) / total)
        self.assertEqual(result["difference"], 2 / total)


class ObservationInputTests(unittest.TestCase):
    def test_the_same_counts_from_observations_and_from_a_matrix_agree(self):
        observations = summary(analyse(PAIRED_PROPORTIONS, fixture_observations(), observation_options()))
        counts = summary(analyse(PAIRED_PROPORTIONS, matrix([4, 9, 2, 2]), count_options()))
        for field in REPORT:
            if field == "Chi-square":
                self.assertTrue(empty(observations[field]) and empty(counts[field]))
            else:
                self.assertEqual(observations[field], counts[field], field)

    def test_incomplete_pairs_are_discarded_without_renumbering_the_others(self):
        frame = pd.DataFrame({"Before": ["off", None, "on", "off", ""], "After": ["on", "on", pd.NA, "off", "on"]})
        result = analyse(PAIRED_PROPORTIONS, frame, observation_options())
        self.assertEqual(result.tables["Pairs"]["Source row"].tolist(), [1, 4])
        self.assertEqual(counts_of(result), [1, 1, 0, 0])
        self.assertEqual(summary(result)["Discarded pairs"], 3)

    def test_an_unknown_value_in_a_discarded_pair_is_not_an_error(self):
        frame = pd.DataFrame({"Before": ["off", "maybe", "on"], "After": ["on", None, "on"]})
        result = analyse(PAIRED_PROPORTIONS, frame, observation_options())
        self.assertEqual(result.tables["Pairs"]["Source row"].tolist(), [1, 3])

    def test_an_unknown_value_in_a_complete_pair_names_the_column_and_the_source_row(self):
        for column in ("Before", "After"):
            data = fixture_observations()
            data.loc[3, column] = "pending"
            with self.subTest(column=column):
                with self.assertRaises(FieldError) as caught:
                    analyse(PAIRED_PROPORTIONS, data, observation_options())
                self.assertEqual(caught.exception.field, column)
                self.assertIn("pending", str(caught.exception))
                self.assertIn("4", str(caught.exception))

    def test_source_row_is_the_position_before_filtering_whatever_the_index(self):
        frame = pd.DataFrame({"Before": ["off", "on", "off"], "After": ["on", None, "off"]}, index=[7, 7, 7])
        result = analyse(PAIRED_PROPORTIONS, frame, observation_options())
        self.assertEqual(result.tables["Pairs"]["Source row"].tolist(), [1, 3])

    def test_pairs_keep_the_order_of_entry_and_the_original_cell_values(self):
        frame = pd.DataFrame({"Before": ["on", "off", "off", "on"], "After": ["on", "on", "off", "off"]})
        pairs = analyse(PAIRED_PROPORTIONS, frame, observation_options()).tables["Pairs"]
        self.assertEqual(list(pairs.columns), ["Source row", "Before", "After", "Transition"])
        self.assertEqual(pairs["Before"].tolist(), ["on", "off", "off", "on"])
        self.assertEqual(pairs["Transition"].tolist(), ["Unchanged positive", "Gain", "Unchanged negative", "Loss"])

    def test_numeric_codes_accept_every_representation_of_the_same_number(self):
        frame = pd.DataFrame({"Before": [0, 1, 0.0, 1.0, " 0 "], "After": ["1", "0", "1,0", "1", "1.00"]})
        result = analyse(PAIRED_PROPORTIONS, frame, observation_options(**{NEGATIVE: "0", POSITIVE: "1"}))
        self.assertEqual(counts_of(result), [0, 3, 1, 1])

    def test_decimal_comma_codes_match_decimal_point_cells(self):
        frame = pd.DataFrame({"Before": [0.5, 1.5, 0.5], "After": ["1,5", "0,5", "0.5"]})
        result = analyse(PAIRED_PROPORTIONS, frame, observation_options(**{NEGATIVE: "0,5", POSITIVE: "1.5"}))
        self.assertEqual(counts_of(result), [1, 1, 1, 0])

    def test_nullable_integer_columns_with_excluded_cells_work(self):
        frame = pd.DataFrame({"Before": pd.array([0, 1, pd.NA, 0], dtype="Int64"),
                              "After": pd.array([1, 1, 1, pd.NA], dtype="Int64")})
        result = analyse(PAIRED_PROPORTIONS, frame, observation_options(**{NEGATIVE: "0", POSITIVE: "1"}))
        self.assertEqual(counts_of(result), [0, 1, 0, 1])
        self.assertEqual(result.tables["Pairs"]["Source row"].tolist(), [1, 2])

    def test_text_codes_are_trimmed_and_case_sensitive(self):
        frame = pd.DataFrame({"Before": [" off ", "off"], "After": ["on", "ON"]})
        with self.assertRaises(FieldError) as caught:
            analyse(PAIRED_PROPORTIONS, frame, observation_options())
        self.assertEqual(caught.exception.field, "After")
        frame.loc[1, "After"] = " on"
        self.assertEqual(counts_of(analyse(PAIRED_PROPORTIONS, frame, observation_options(**{NEGATIVE: " off"}))),
                         [0, 2, 0, 0])

    def test_boolean_cells_are_not_converted_to_zero_and_one(self):
        frame = pd.DataFrame({"Before": [False, True], "After": [True, True]})
        for codes in ({NEGATIVE: "0", POSITIVE: "1"}, {NEGATIVE: "False", POSITIVE: "True"}):
            with self.subTest(codes=codes):
                with self.assertRaises(FieldError) as caught:
                    analyse(PAIRED_PROPORTIONS, frame, observation_options(**codes))
                self.assertEqual(caught.exception.field, "Before")

    def test_a_numeric_code_never_matches_the_text_of_a_non_numeric_cell(self):
        frame = pd.DataFrame({"Before": ["zero", "1"], "After": ["1", "1"]})
        with self.assertRaises(FieldError) as caught:
            analyse(PAIRED_PROPORTIONS, frame, observation_options(**{NEGATIVE: "0", POSITIVE: "1"}))
        self.assertEqual(caught.exception.field, "Before")

    def test_codes_default_to_zero_and_one(self):
        frame = pd.DataFrame({"Before": [0, 1, 1], "After": [1, 1, 0]})
        options = observation_options()
        del options[NEGATIVE], options[POSITIVE]
        self.assertEqual(counts_of(analyse(PAIRED_PROPORTIONS, frame, options)), [0, 1, 1, 1])

    def test_integer_codes_in_a_recipe_are_accepted(self):
        frame = pd.DataFrame({"Before": [0, 1], "After": [1, 1]})
        result = analyse(PAIRED_PROPORTIONS, frame, observation_options(**{NEGATIVE: 0, POSITIVE: 1}))
        self.assertEqual(counts_of(result), [0, 1, 0, 1])

    def test_empty_or_equivalent_codes_name_positive_value(self):
        frame = pd.DataFrame({"Before": ["0", "1"], "After": ["1", "1"]})
        for codes in ({NEGATIVE: "", POSITIVE: "1"}, {NEGATIVE: "0", POSITIVE: " "}, {NEGATIVE: "1", POSITIVE: "1.0"},
                      {NEGATIVE: "on", POSITIVE: "on"}, {NEGATIVE: "0,5", POSITIVE: "0.50"}):
            with self.subTest(codes=codes):
                with self.assertRaises(FieldError) as caught:
                    analyse(PAIRED_PROPORTIONS, frame, observation_options(**codes))
                self.assertEqual(caught.exception.field, POSITIVE)

    def test_text_codes_that_differ_only_by_case_are_two_different_codes(self):
        frame = pd.DataFrame({"Before": ["y", "Y"], "After": ["Y", "Y"]})
        result = analyse(PAIRED_PROPORTIONS, frame, observation_options(**{NEGATIVE: "y", POSITIVE: "Y"}))
        self.assertEqual(counts_of(result), [0, 1, 0, 1])

    def test_columns_must_exist_and_differ(self):
        frame = fixture_observations()
        cases = ((BEFORE, None, BEFORE), (BEFORE, "", BEFORE), (BEFORE, "Missing", BEFORE), (AFTER, None, AFTER),
                 (AFTER, "Missing", AFTER), (AFTER, "Before", AFTER))
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaises(FieldError) as caught:
                    analyse(PAIRED_PROPORTIONS, frame, observation_options(**{field: value}))
                self.assertEqual(caught.exception.field, expected)

    def test_duplicated_worksheet_column_names_are_refused(self):
        frame = pd.DataFrame([["off", "on", "on"]], columns=["Before", "After", "After"])
        with self.assertRaises(FieldError) as caught:
            analyse(PAIRED_PROPORTIONS, frame, observation_options())
        self.assertEqual(caught.exception.field, AFTER)

    def test_zero_valid_pairs_are_refused(self):
        frame = pd.DataFrame({"Before": ["off", None], "After": [None, "on"]})
        with self.assertRaises(FieldError) as caught:
            analyse(PAIRED_PROPORTIONS, frame, observation_options())
        self.assertEqual(caught.exception.field, BEFORE)
        with self.assertRaises(FieldError):
            analyse(PAIRED_PROPORTIONS, frame.iloc[:0], observation_options())

    def test_the_worksheet_is_not_modified(self):
        frame = fixture_observations()
        before = frame.copy(deep=True)
        analyse(PAIRED_PROPORTIONS, frame, observation_options(**{GRAPH: True}))
        pd.testing.assert_frame_equal(frame, before)

    def test_the_pairs_table_is_not_produced_for_a_matrix(self):
        self.assertNotIn("Pairs", analyse(PAIRED_PROPORTIONS, matrix([1, 2, 3, 4]), count_options()).tables)


class CountMatrixTests(unittest.TestCase):
    def test_the_two_rows_are_before_negative_and_before_positive(self):
        table = analyse(PAIRED_PROPORTIONS, matrix([4, 9, 2, 2]), count_options()).tables["Paired counts"]
        self.assertEqual(list(table.index), ["Before negative", "Before positive"])
        self.assertEqual(list(table.columns), ["After negative", "After positive"])
        self.assertEqual(table.to_numpy().tolist(), [[4, 9], [2, 2]])
        self.assertTrue(all(np.issubdtype(kind, np.integer) for kind in table.dtypes))

    def test_changing_the_orientation_of_the_sheet_reverses_the_sign_and_the_odds_ratio_and_keeps_p(self):
        one = summary(analyse(PAIRED_PROPORTIONS, matrix([4, 9, 2, 2]), count_options()))
        # Swapping the roles of the sheet rows and columns is the same as swapping Before and After: b <-> c.
        two = summary(analyse(PAIRED_PROPORTIONS, matrix([4, 2, 9, 2]), count_options()))
        self.assertEqual(one["p"], two["p"])
        self.assertAlmostEqual(one["Difference (after − before)"], -two["Difference (after − before)"], places=15)
        self.assertAlmostEqual(one["Matched odds ratio"], 1 / two["Matched odds ratio"], places=12)
        self.assertAlmostEqual(one["OR CI lower"], 1 / two["OR CI upper"], places=12)

    def test_rows_are_never_sorted_by_name(self):
        frame = pd.DataFrame({"Row": ["Z second", "A first"], "After negative": [4, 2], "After positive": [9, 2]})
        result = analyse(PAIRED_PROPORTIONS, frame, count_options())
        self.assertEqual(counts_of(result), [4, 9, 2, 2])

    def test_trailing_rows_that_are_empty_in_the_selected_columns_are_ignored(self):
        frame = pd.DataFrame({"After negative": [4, 2, None, "", " "], "After positive": [9, 2, np.nan, None, ""],
                              "Note": ["", "", "kept elsewhere", "", ""]})
        self.assertEqual(counts_of(analyse(PAIRED_PROPORTIONS, frame, count_options())), [4, 9, 2, 2])

    def test_a_filled_third_row_is_an_error_on_its_column(self):
        for column, field in (("After negative", AFTER_NEGATIVE), ("After positive", AFTER_POSITIVE)):
            frame = pd.DataFrame({"After negative": [4, 2, None], "After positive": [9, 2, None]})
            frame.loc[2, column] = 1
            with self.subTest(column=column):
                with self.assertRaises(FieldError) as caught:
                    analyse(PAIRED_PROPORTIONS, frame, count_options())
                self.assertEqual(caught.exception.field, field)

    def test_a_filled_row_after_an_empty_one_is_still_an_error(self):
        frame = pd.DataFrame({"After negative": [4, 2, None, 1], "After positive": [9, 2, None, None]})
        with self.assertRaises(FieldError):
            analyse(PAIRED_PROPORTIONS, frame, count_options())

    def test_fewer_than_two_rows_are_refused(self):
        with self.assertRaises(FieldError) as caught:
            analyse(PAIRED_PROPORTIONS, matrix([4, 9, 2, 2]).iloc[:1], count_options())
        self.assertEqual(caught.exception.field, AFTER_NEGATIVE)

    def test_empty_counts_in_the_two_required_rows_are_errors_on_their_column(self):
        for row in (0, 1):
            for column, field in (("After negative", AFTER_NEGATIVE), ("After positive", AFTER_POSITIVE)):
                for blank in (None, np.nan, "", " ", pd.NA):
                    frame = matrix([4, 9, 2, 2]).astype(object)
                    frame.loc[row, column] = blank
                    with self.subTest(row=row, column=column, blank=repr(blank)):
                        with self.assertRaises(FieldError) as caught:
                            analyse(PAIRED_PROPORTIONS, frame, count_options())
                        self.assertEqual(caught.exception.field, field)

    def test_malformed_counts_are_errors_on_their_column(self):
        for bad in ("", -1, 0.25, True, np.bool_(True), float("inf"), float("-inf"), "x", "-3", "2,5", "1e400", "inf",
                    "nan", "0x10"):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(FieldError) as caught:
                    analyse(PAIRED_PROPORTIONS, matrix([1, bad, 3, 4]), count_options())
                self.assertEqual(caught.exception.field, AFTER_POSITIVE)
                with self.assertRaises(FieldError) as caught:
                    analyse(PAIRED_PROPORTIONS, matrix([bad, 1, 3, 4]), count_options())
                self.assertEqual(caught.exception.field, AFTER_NEGATIVE)

    def test_sheet_numbers_and_whole_strings_are_counts(self):
        frame = pd.DataFrame({"After negative": [np.float64(4.0), "2"], "After positive": ["9,0", np.int64(2)]})
        self.assertEqual(counts_of(analyse(PAIRED_PROPORTIONS, frame, count_options())), [4, 9, 2, 2])

    def test_the_total_is_limited_with_integer_arithmetic(self):
        limit = 10_000_000
        self.assertEqual(summary(analyse(PAIRED_PROPORTIONS, matrix([limit - 3, 1, 1, 1]), count_options()))["N pairs"],
                         limit)
        for counts in ([limit - 2, 1, 1, 1], [10 ** 30, 1, 1, 1], [2 ** 53 + 1, 0, 0, 0]):
            with self.subTest(counts=counts):
                with self.assertRaises(FieldError) as caught:
                    analyse(PAIRED_PROPORTIONS, matrix(counts), count_options())
                self.assertIn(caught.exception.field, (AFTER_NEGATIVE, AFTER_POSITIVE))

    def test_a_zero_total_is_an_error_on_a_count_field(self):
        with self.assertRaises(FieldError) as caught:
            analyse(PAIRED_PROPORTIONS, matrix([0, 0, 0, 0]), count_options())
        self.assertIn(caught.exception.field, (AFTER_NEGATIVE, AFTER_POSITIVE))

    def test_the_two_count_columns_must_exist_and_differ(self):
        cases = (({AFTER_NEGATIVE: None}, AFTER_NEGATIVE), ({AFTER_NEGATIVE: "Nope"}, AFTER_NEGATIVE),
                 ({AFTER_POSITIVE: None}, AFTER_POSITIVE), ({AFTER_POSITIVE: "Nope"}, AFTER_POSITIVE),
                 ({AFTER_POSITIVE: "After negative"}, AFTER_POSITIVE))
        for changes, field in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(FieldError) as caught:
                    analyse(PAIRED_PROPORTIONS, matrix([1, 2, 3, 4]), count_options(**changes))
                self.assertEqual(caught.exception.field, field)

    def test_the_observation_fields_are_not_validated_in_matrix_mode(self):
        options = count_options(**{BEFORE: "Missing", AFTER: "Missing", NEGATIVE: "", POSITIVE: ""})
        self.assertEqual(counts_of(analyse(PAIRED_PROPORTIONS, matrix([1, 2, 3, 4]), options)), [1, 2, 3, 4])

    def test_the_matrix_fields_are_not_validated_in_observation_mode(self):
        options = observation_options(**{AFTER_NEGATIVE: "Missing", AFTER_POSITIVE: None})
        self.assertEqual(counts_of(analyse(PAIRED_PROPORTIONS, fixture_observations(), options)), [4, 9, 2, 2])


class OptionValidationTests(unittest.TestCase):
    def run_matrix(self, **changes):
        return analyse(PAIRED_PROPORTIONS, matrix([1, 2, 3, 4]), count_options(**changes))

    def test_invalid_modes_tests_levels_and_graph_flags_name_their_field(self):
        cases = ((FORMAT, "Long", FORMAT), (FORMAT, None, FORMAT), (TEST, "Fisher", TEST), (TEST, None, TEST),
                 (TEST, "exact", TEST), (LEVEL, 0, LEVEL), (LEVEL, 100, LEVEL), (LEVEL, -5, LEVEL),
                 (LEVEL, 101, LEVEL), (LEVEL, float("nan"), LEVEL), (LEVEL, float("inf"), LEVEL), (LEVEL, True, LEVEL),
                 (LEVEL, "95", LEVEL), (LEVEL, None, LEVEL), (GRAPH, "yes", GRAPH), (GRAPH, 1, GRAPH))
        for field, value, expected in cases:
            with self.subTest(field=field, value=repr(value)):
                with self.assertRaises(FieldError) as caught:
                    self.run_matrix(**{field: value})
                self.assertEqual(caught.exception.field, expected)

    def test_defaults_apply_when_options_are_missing(self):
        result = analyse(PAIRED_PROPORTIONS, matrix([4, 9, 2, 2]),
                         {AFTER_NEGATIVE: "After negative", AFTER_POSITIVE: "After positive", FORMAT: COUNT_MATRIX})
        self.assertAlmostEqual(summary(result)["p"], 0.0654296875, places=15)
        self.assertEqual(summary(result)["Test"], EXACT)
        self.assertEqual(summary(result)["Confidence level (%)"], 95.0)
        self.assertIsNone(result.figure)
        observed = analyse(PAIRED_PROPORTIONS, pd.DataFrame({"B": [0, 1], "A": [1, 1]}), {BEFORE: "B", AFTER: "A"})
        self.assertEqual(counts_of(observed), [0, 1, 0, 1])

    def test_the_confidence_level_changes_the_odds_ratio_interval_only(self):
        narrow = summary(self.run_matrix(**{LEVEL: 50.0}))
        wide = summary(self.run_matrix(**{LEVEL: 99.0}))
        self.assertGreater(narrow["OR CI lower"], wide["OR CI lower"])
        self.assertLess(narrow["OR CI upper"], wide["OR CI upper"])
        self.assertEqual(narrow["p"], wide["p"])
        self.assertEqual(wide["Confidence level (%)"], 99.0)

    def test_numpy_numbers_are_valid_levels(self):
        self.assertIsNotNone(self.run_matrix(**{LEVEL: np.float64(90.0)}))
        self.assertIsNotNone(self.run_matrix(**{LEVEL: 90}))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.result = analyse(PAIRED_PROPORTIONS, matrix([4, 9, 2, 2]), count_options())

    def test_the_sheets_are_published_in_a_fixed_order(self):
        self.assertEqual(list(self.result.tables), ["Paired counts", "Paired proportions"])
        observed = analyse(PAIRED_PROPORTIONS, fixture_observations(), observation_options())
        self.assertEqual(list(observed.tables), ["Paired counts", "Paired proportions", "Pairs"])

    def test_the_report_lists_the_required_rows_first_with_a_value_column(self):
        table = self.result.tables["Paired proportions"]
        self.assertEqual(list(table.columns), ["Value"])
        self.assertEqual(list(table.index[:len(REPORT)]), REPORT)

    def test_the_report_names_the_test_the_level_the_interval_method_and_the_scope_of_the_interval(self):
        report = summary(self.result)
        self.assertEqual(report["Test"], EXACT)
        self.assertEqual(report["Confidence level (%)"], 95.0)
        self.assertIn("Clopper–Pearson", report["OR CI method"])
        self.assertIn("odds ratio", report["Note"])
        self.assertIn("marginal difference", report["Note"])

    def test_the_discarded_pairs_are_counted_only_for_observations(self):
        self.assertNotIn("Discarded pairs", summary(self.result).index)
        observed = analyse(PAIRED_PROPORTIONS, fixture_observations(), observation_options())
        self.assertEqual(summary(observed)["Discarded pairs"], 2)

    def test_an_estimable_odds_ratio_is_numeric_and_infinite_values_survive_csv_export(self):
        gains = analyse(PAIRED_PROPORTIONS, matrix([4, 6, 0, 2]), count_options())
        report = summary(gains)
        self.assertIsInstance(report["Matched odds ratio"], float)
        self.assertEqual(report["Matched odds ratio"], math.inf)
        text = gains.tables["Paired proportions"].to_csv()
        self.assertIn("inf", text)
        self.assertIn("infinite", report["Note"])

    def test_one_direction_notes_explain_the_limit(self):
        losses = summary(analyse(PAIRED_PROPORTIONS, matrix([4, 0, 6, 2]), count_options()))
        self.assertEqual(losses["Matched odds ratio"], 0.0)
        self.assertIn("No gains", losses["Note"])

    def test_no_discordance_gives_a_visible_reason_and_empty_cells(self):
        report = summary(analyse(PAIRED_PROPORTIONS, matrix([4, 0, 0, 5]), count_options()))
        self.assertEqual(report["p"], 1.0)
        for field in ("Chi-square", "Matched odds ratio", "OR CI lower", "OR CI upper"):
            self.assertTrue(empty(report[field]), field)
        self.assertIn("No discordant pairs", report["Note"])
        self.assertIn("cannot be estimated", report["Note"])

    def test_the_input_table_formats_are_unchanged_by_the_report(self):
        data = matrix([4, 9, 2, 2])
        before = data.copy(deep=True)
        analyse(PAIRED_PROPORTIONS, data, count_options())
        pd.testing.assert_frame_equal(data, before)


class FigureTests(unittest.TestCase):
    def figure(self, counts, **changes):
        return analyse(PAIRED_PROPORTIONS, matrix(counts), count_options(**{GRAPH: True, **changes})).figure

    def test_graph_off_publishes_no_figure_and_graph_on_publishes_four_bars_in_order(self):
        self.assertIsNone(analyse(PAIRED_PROPORTIONS, matrix([4, 9, 2, 2]), count_options()).figure)
        axes = self.figure([4, 9, 2, 2]).axes[0]
        self.assertEqual([patch.get_height() for patch in axes.patches], [4, 9, 2, 2])
        self.assertEqual([tick.get_text() for tick in axes.get_xticklabels()], TRANSITIONS)

    def test_every_bar_carries_its_count_even_when_the_bar_is_zero(self):
        axes = self.figure([4, 0, 0, 5]).axes[0]
        self.assertEqual([patch.get_height() for patch in axes.patches], [4, 0, 0, 5])
        self.assertEqual([text.get_text() for text in axes.texts if text.get_text().isdigit()], ["4", "0", "0", "5"])
        self.assertGreater(axes.get_ylim()[1], 5)
        self.assertEqual(axes.get_ylim()[0], 0)

    def test_the_figure_is_native_with_a_categorical_x_axis_and_a_numeric_count_axis(self):
        axes = self.figure([4, 9, 2, 2]).axes[0]
        self.assertEqual(axes._tramastat_categorical_axes, ("x",))
        self.assertEqual(axes._tramastat_numeric_axes, ("y",))
        self.assertIn("Paired proportions", axes.get_title())
        self.assertEqual(axes.get_ylabel(), "Pairs")

    def test_the_figure_does_not_decide_anything_by_itself(self):
        title = self.figure([4, 9, 2, 2]).axes[0].get_title()
        for word in ("significant", "p =", "equivalent"):
            self.assertNotIn(word, title)

    def test_bars_have_stable_group_ids_for_formatting(self):
        axes = self.figure([4, 9, 2, 2]).axes[0]
        self.assertEqual([patch.get_gid() for patch in axes.patches],
                         ["paired:unchanged-negative", "paired:gain", "paired:loss", "paired:unchanged-positive"])

    def test_the_four_bars_have_distinguishable_colors(self):
        axes = self.figure([4, 9, 2, 2]).axes[0]
        colors = [patch.get_facecolor() for patch in axes.patches]
        self.assertEqual(len(set(colors)), 4)

    def test_a_large_total_does_not_break_the_axis(self):
        axes = self.figure([5_000_000, 2_000_000, 1_000_000, 2_000_000]).axes[0]
        self.assertEqual(axes.patches[0].get_height(), 5_000_000)


class RegistrationTests(unittest.TestCase):
    def test_the_method_is_listed_under_group_comparison_once(self):
        self.assertEqual(GROUPS["Group Comparison"].count(PAIRED_PROPORTIONS), 1)
        self.assertIn(PAIRED_PROPORTIONS, METHODS)
        self.assertEqual(METHODS[PAIRED_PROPORTIONS], OPTIONS)

    def test_the_graph_is_opt_in_so_the_method_is_not_always_a_graph_method(self):
        self.assertNotIn(PAIRED_PROPORTIONS, GRAPH_METHODS)
        self.assertFalse(OPTIONS[GRAPH])

    def test_defaults_declared_for_the_dialog(self):
        self.assertEqual(OPTIONS[FORMAT], (OBSERVATIONS, COUNT_MATRIX))
        self.assertEqual(OPTIONS[TEST], (EXACT, MID_P, CHI_SQUARE))
        self.assertEqual(OPTIONS[LEVEL], 95.0)

    def test_visibility_follows_the_input_format(self):
        observations, counts = visibility(OBSERVATIONS), visibility(COUNT_MATRIX)
        for field in (BEFORE, AFTER, NEGATIVE, POSITIVE):
            self.assertTrue(observations[field])
            self.assertFalse(counts[field])
        for field in (AFTER_NEGATIVE, AFTER_POSITIVE):
            self.assertFalse(observations[field])
            self.assertTrue(counts[field])

    def test_the_independent_contingency_recipes_still_work_and_publish_their_own_sheets(self):
        result = analyse(CONTINGENCY, matrix([4, 9, 2, 2]), {
            "Input format": "Count matrix", "Count columns": ["After negative", "After positive"],
            "Test": "Fisher exact (2 × 2)", "Confidence level (%)": 95.0})
        self.assertNotIn("Paired proportions", result.tables)
        self.assertIn("Counts", result.tables)

    def test_the_direct_entry_point_and_the_dispatcher_agree(self):
        frame = matrix([4, 9, 2, 2])
        direct = paired_proportions(frame, count_options())
        via = analyse(PAIRED_PROPORTIONS, frame, count_options())
        for name in direct.tables:
            pd.testing.assert_frame_equal(direct.tables[name], via.tables[name])


if __name__ == "__main__":
    unittest.main()
