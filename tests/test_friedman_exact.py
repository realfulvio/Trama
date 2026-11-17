import unittest
from fractions import Fraction
from itertools import permutations, product
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from analisi import friedman_exact, inference
from analisi.inference import AUTOMATIC_P, CHI_SQUARE_P, EXACT_P, FRIEDMAN_P
from analisi.processing import FieldError
from analisi.workbench import analyse

F1 = [[1, 1, 3], [2, 1, 3], [1, 3, 3], [1, 2, 4]]


def matched(values, labels=None):
    values = np.asarray(values)
    labels = labels or [chr(65 + i) for i in range(values.shape[1])]
    return pd.DataFrame([(subject, labels[group], value) for subject, row in enumerate(values)
                         for group, value in enumerate(row)], columns=["Subject", "Group", "Y"])


def run(values, method=None, **extra):
    options = {"Response": "Y", "Group": "Group", "Subject": "Subject", **extra}
    if method:
        options[FRIEDMAN_P] = method
    return analyse("Friedman", matched(values), options)


def summary(values, method=None, **extra):
    return run(values, method, **extra).tables["Friedman"].iloc[0]


def enumerate_p(values):
    """Reference oracle: label every assignment of every row, no reuse of the counting code."""
    ranks = (2 * stats.rankdata(np.asarray(values), axis=1)).astype(int)
    observed = (ranks.sum(axis=0) ** 2).sum()
    k = ranks.shape[1]
    extreme = total = 0
    for choice in product(permutations(range(k)), repeat=len(ranks)):
        sums = np.zeros(k, dtype=int)
        for row, order in zip(ranks, choice):
            sums += row[list(order)]
        total += 1
        extreme += (sums ** 2).sum() >= observed
    return Fraction(int(extreme), total)


class FriedmanExactOracles(unittest.TestCase):
    def test_f1_ties_match_hand_count_and_are_invariant(self):
        row = summary(F1, EXACT_P)
        self.assertEqual(row["p"], 5 / 54)
        self.assertEqual(friedman_exact.friedman_exact_tail(np.array(F1)), (120, 1296))
        self.assertAlmostEqual(row["Statistic"], 39 / 7)
        self.assertEqual(row["p method"], EXACT_P)
        chi = summary(F1, CHI_SQUARE_P)
        self.assertEqual(chi["p"], 0.06168501256797605)
        self.assertEqual(chi["p method"], CHI_SQUARE_P)
        reflected = np.array(F1)[:, ::-1]
        shuffled = np.array(F1)[[2, 0, 3, 1]]
        for values in (reflected, shuffled, reflected[[3, 1, 0, 2]]):
            self.assertEqual(summary(values, EXACT_P)["p"], 5 / 54)

    def test_f2_identical_orders_are_automatic_exact_and_fast(self):
        eleven = [[1, 2, 3]] * 11
        row = summary(eleven)
        self.assertEqual((row["Statistic"], row["df"], row["p method"]), (22, 2, EXACT_P))
        self.assertEqual(row["p"], 1 / 6**10)
        self.assertNotIn("p method reason", row.index)
        twelve = summary([[1, 2, 3]] * 12)
        self.assertEqual(twelve["p method"], CHI_SQUARE_P)
        self.assertIn("exceeds 1,000,000,000", twelve["p method reason"])
        self.assertEqual(twelve["p"], stats.friedmanchisquare(*np.array([[1, 2, 3]] * 12).T).pvalue)
        # The explicit request has no limit of its own beyond the counting budget.
        self.assertEqual(summary([[1, 2, 3]] * 12, EXACT_P)["p"], 1 / 6**11)

    def test_f3_balanced_orders_and_ties(self):
        row = summary([[1, 2, 3], [3, 1, 2], [2, 3, 1]], EXACT_P)
        self.assertEqual((row["Statistic"], row["p"]), (0, 1))
        # A subject that is entirely tied is allowed when another subject is informative.
        mixed = [[5, 5, 5], [1, 2, 3], [2, 3, 1]]
        self.assertEqual(summary(mixed, EXACT_P)["p"], float(enumerate_p(mixed)))
        with self.assertRaisesRegex(ValueError, "only ties"):
            run([[4, 4, 4], [2, 2, 2]], EXACT_P)

    def test_incomplete_and_duplicate_matrices_still_fail(self):
        frame = matched(F1)
        options = {"Response": "Y", "Group": "Group", "Subject": "Subject", FRIEDMAN_P: EXACT_P}
        with self.assertRaisesRegex(ValueError, "complete"):
            analyse("Friedman", frame.iloc[:-1], options)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            analyse("Friedman", pd.concat([frame, frame.iloc[:1]]), options)

    def test_counting_matches_full_enumeration(self):
        rng = np.random.default_rng(20240)
        cases = [rng.integers(0, 3, size=(3, 3)), rng.integers(0, 2, size=(4, 3)), rng.permutation(12).reshape(3, 4),
                 rng.integers(0, 3, size=(3, 4)), rng.integers(0, 4, size=(2, 5)), [[1, 1, 1, 2], [1, 2, 3, 4], [4, 4, 1, 1]],
                 F1, [[1, 2, 3]] * 5, [[1, 1, 2], [3, 3, 4]]]
        checked = 0
        for values in cases:
            values = np.asarray(values)
            if not np.any(values != values[:, :1]):
                continue
            expected = enumerate_p(values)
            with self.subTest(values=values.tolist()):
                self.assertEqual(Fraction(*friedman_exact.friedman_exact_tail(values)), expected)
                # Python integer counts must give the same answer as int64 counts.
                with patch.object(friedman_exact, "_INT64_SAFE", 0):
                    self.assertEqual(Fraction(*friedman_exact.friedman_exact_tail(values)), expected)
                with patch.object(friedman_exact, "_CHUNK", 7):
                    self.assertEqual(Fraction(*friedman_exact.friedman_exact_tail(values)), expected)
                checked += 1
        self.assertGreaterEqual(checked, 8)

    def test_large_counts_use_exact_python_integers(self):
        values = np.array([[1, 2, 3]] * 60)
        extreme, total = friedman_exact.friedman_exact_tail(values)
        self.assertEqual((extreme, total), (6, 6**60))

    def test_distinct_orderings_are_generated_without_duplicates(self):
        for row in ([1, 1, 2, 3], [4, 4, 4], [1, 2, 3, 4], [2, 2, 5, 5]):
            values, counts, orders, weight = friedman_exact.distinct_orders(np.array(row))
            table = friedman_exact._generate_orders(values, counts)
            expected = sorted(set(permutations(row)))
            self.assertEqual(len(table), orders)
            self.assertEqual(sorted(map(tuple, table.tolist())), expected)
            self.assertEqual(orders * weight, 24 if len(row) == 4 else 6)


class FriedmanOptionAndBudget(unittest.TestCase):
    def test_order_cells_are_checked_before_materializing_rank_vectors(self):
        values = np.array([[1, 2, 3], [2, 1, 3]])
        with patch.object(friedman_exact, "_MAX_VECTOR_CELLS", 12):
            with patch.object(friedman_exact, "_generate_orders", side_effect=AssertionError("allocated orders")):
                with self.assertRaisesRegex(friedman_exact.ExactBudgetExceeded, "rank cells"):
                    friedman_exact.friedman_exact_tail(values)

    def test_default_and_saved_recipes_without_p_value_are_automatic(self):
        self.assertEqual(summary(F1)["p method"], EXACT_P)
        self.assertEqual(summary(F1)["p"], summary(F1, AUTOMATIC_P)["p"])
        self.assertIn(FRIEDMAN_P, analyse.__globals__["METHODS"]["Friedman"])

    def test_manual_chi_square_never_calls_the_exact_count(self):
        with patch.object(inference, "friedman_exact_tail", side_effect=AssertionError):
            self.assertEqual(summary(F1, CHI_SQUARE_P)["p method"], CHI_SQUARE_P)

    def test_invalid_method_is_a_field_error(self):
        with self.assertRaises(FieldError) as caught:
            run(F1, "Monte Carlo")
        self.assertEqual(caught.exception.field, FRIEDMAN_P)

    def test_state_budget_falls_back_for_automatic_and_rejects_exact(self):
        with patch.object(friedman_exact, "_MAX_STATES", 1):
            fallback = summary(F1, AUTOMATIC_P)
            self.assertEqual(fallback["p method"], CHI_SQUARE_P)
            self.assertEqual(fallback["p"], 0.06168501256797605)
            self.assertIn("work limit", fallback["p method reason"])
            with self.assertRaises(FieldError) as caught:
                run(F1, EXACT_P)
        self.assertEqual(caught.exception.field, FRIEDMAN_P)
        self.assertIn("limit", str(caught.exception))
        self.assertEqual(summary(F1, EXACT_P)["p"], 5 / 54)

    def test_transition_budget_and_row_order_limit_are_checked_before_allocating(self):
        with patch.object(friedman_exact, "_MAX_TRANSITIONS", 5):
            with patch.object(friedman_exact, "_generate_orders", side_effect=AssertionError):
                with self.assertRaises(friedman_exact.ExactBudgetExceeded):
                    friedman_exact.friedman_exact_tail(np.array(F1))
            self.assertEqual(summary(F1, AUTOMATIC_P)["p method"], CHI_SQUARE_P)
        rows = [list(range(1, 11)), list(range(10, 0, -1))]
        with patch.object(friedman_exact, "_MAX_ORDERS", 1000):
            with patch.object(friedman_exact, "_generate_orders", side_effect=AssertionError):
                with self.assertRaises(friedman_exact.ExactBudgetExceeded):
                    friedman_exact.friedman_exact_tail(np.array(rows))

    def test_automatic_threshold_is_exact_integer_arithmetic(self):
        self.assertTrue(inference._friedman_assignments_within_limit(11, 3))
        self.assertFalse(inference._friedman_assignments_within_limit(12, 3))
        self.assertTrue(inference._friedman_assignments_within_limit(4, 5))
        self.assertFalse(inference._friedman_assignments_within_limit(5, 5))

    def test_selected_pairs_do_not_depend_on_the_global_p_method(self):
        options = {"Dunn comparisons": "Selected pairs", "Selected pairs": [["C", "A"], ["B", "A"]],
                   "Dunn adjustment": "Bonferroni"}
        reference = None
        for method in (AUTOMATIC_P, EXACT_P, CHI_SQUARE_P):
            pairs = run(F1, method, **options).tables["Dunn comparisons"]
            self.assertEqual(len(pairs), 2)
            self.assertTrue(np.allclose(pairs["Adjusted p"], np.minimum(1, 2 * pairs["p"])))
            if reference is None:
                reference = pairs
            pd.testing.assert_frame_equal(pairs, reference)
        with patch.object(friedman_exact, "_MAX_STATES", 1):
            pd.testing.assert_frame_equal(run(F1, AUTOMATIC_P, **options).tables["Dunn comparisons"], reference)


if __name__ == "__main__":
    unittest.main()
