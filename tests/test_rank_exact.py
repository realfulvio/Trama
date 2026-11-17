import unittest
from fractions import Fraction
from itertools import combinations, product
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from analisi import rank_exact
from analisi.friedman_exact import ExactBudgetExceeded

DATA = Path(__file__).parent / "data" / "rank_exact"


def labelled_mann(values, first):
    """Reference oracle: every choice of the first group's positions, ranks taken from scipy."""
    ranks = (2 * stats.rankdata(values)).astype(int)
    n1 = int(np.sum(first))
    observed = int(ranks[np.asarray(first, dtype=bool)].sum())
    scores = [int(ranks[list(c)].sum()) for c in combinations(range(len(values)), n1)]
    return sum(s <= observed for s in scores), sum(s >= observed for s in scores), len(scores)


def labelled_signs(values):
    """Reference oracle: every sign assignment, ranks of the moduli taken from scipy."""
    values = np.asarray(values, dtype=float)
    ranks = (2 * stats.rankdata(np.abs(values))).astype(int)
    observed = int(ranks[values > 0].sum())
    scores = [sum(r for r, sign in zip(ranks, signs) if sign) for signs in product((False, True), repeat=len(ranks))]
    return sum(s <= observed for s in scores), sum(s >= observed for s in scores), len(scores)


class DoubledRanks(unittest.TestCase):
    def test_matches_scipy_midranks(self):
        rng = np.random.default_rng(3)
        for _ in range(20):
            values = rng.integers(0, 6, 15).astype(float)
            np.testing.assert_array_equal(rank_exact.doubled_ranks(values), (2 * stats.rankdata(values)).astype(int))

    def test_floats_are_compared_exactly(self):
        near = np.array([0.3, 0.30000000000000004, 0.3])
        np.testing.assert_array_equal(rank_exact.doubled_ranks(near), [3, 6, 3])
        np.testing.assert_array_equal(rank_exact.doubled_ranks([0.0, -0.0]), [3, 3])

    def test_empty(self):
        self.assertEqual(len(rank_exact.doubled_ranks([])), 0)


class MannWhitneyCounts(unittest.TestCase):
    def test_fixtures_match_labelled_allocations(self):
        for name in ("mann-1.csv", "mann-2.csv", "mann-3.csv", "mann-4.csv"):
            data = pd.read_csv(DATA / name)
            first = (data.Group == data.Group.iloc[0]).to_numpy()
            ranks = rank_exact.doubled_ranks(data.Y)
            self.assertEqual(rank_exact.mann_whitney_tails(ranks, first), labelled_mann(data.Y.to_numpy(), first), name)

    def test_random_small_samples_with_ties(self):
        rng = np.random.default_rng(11)
        for _ in range(40):
            size = int(rng.integers(3, 11))
            values = rng.integers(0, 5, size).astype(float)
            first = np.zeros(size, dtype=bool)
            first[rng.choice(size, int(rng.integers(1, size)), replace=False)] = True
            self.assertEqual(rank_exact.mann_whitney_tails(rank_exact.doubled_ranks(values), first),
                             labelled_mann(values, first), (values, first))

    def test_swapping_groups_swaps_the_tails(self):
        rng = np.random.default_rng(5)
        for n1 in (2, 3, 7):                  # also exercises counting the smaller group
            values = rng.integers(0, 9, 10).astype(float)
            first = np.arange(10) < n1
            ranks = rank_exact.doubled_ranks(values)
            low, high, total = rank_exact.mann_whitney_tails(ranks, first)
            swapped = rank_exact.mann_whitney_tails(ranks, ~first)
            self.assertEqual(swapped, (high, low, total))
            self.assertEqual(total, comb(10, n1))

    def test_all_tied_counts_exceed_int64(self):
        low, high, total = rank_exact.mann_whitney_tails(np.full(80, 81), np.arange(80) < 40)
        self.assertEqual((low, high, total), (comb(80, 40),) * 3)
        self.assertGreater(total, 2**64)

    def test_large_untied_counts_stay_exact(self):
        # 2^62 is the largest int64 count; 50+30 untied observations are far beyond it.
        ranks = rank_exact.doubled_ranks(np.arange(80.0))
        first = np.zeros(80, dtype=bool)
        first[::2][:30] = True
        low, high, total = rank_exact.mann_whitney_tails(ranks, first)
        self.assertEqual(total, comb(80, 30))
        self.assertGreater(total, 2**62)
        self.assertTrue(0 < low < total and 0 < high < total)
        self.assertGreaterEqual(low + high, total + 1)          # both tails include the observed sum

    def test_budget_is_checked_before_the_work(self):
        ranks = rank_exact.doubled_ranks(np.arange(60.0))
        first = np.arange(60) < 30
        with self.assertRaisesRegex(ExactBudgetExceeded, "transitions"):
            rank_exact.mann_whitney_tails(ranks, first, max_transitions=1_000)
        with self.assertRaisesRegex(ExactBudgetExceeded, "states"):
            rank_exact.mann_whitney_tails(ranks, first, max_states=100)


class SignedRankCounts(unittest.TestCase):
    def test_fixtures_match_labelled_signs(self):
        for name in ("wilcoxon-1.csv", "wilcoxon-2.csv", "wilcoxon-3.csv"):
            data = pd.read_csv(DATA / name)
            diff = (data.First - data.Second).to_numpy()
            diff = diff[diff != 0]
            self.assertEqual(rank_exact.signed_rank_tails(rank_exact.doubled_ranks(np.abs(diff)), diff > 0),
                             labelled_signs(diff), name)

    def test_random_small_samples_with_ties(self):
        rng = np.random.default_rng(17)
        for _ in range(40):
            diff = rng.integers(-4, 5, int(rng.integers(1, 11))).astype(float)
            diff = diff[diff != 0]
            if not len(diff):
                continue
            self.assertEqual(rank_exact.signed_rank_tails(rank_exact.doubled_ranks(np.abs(diff)), diff > 0),
                             labelled_signs(diff), diff)

    def test_all_positive_equal_differences_exceed_int64(self):
        low, high, total = rank_exact.signed_rank_tails(np.full(80, 81), np.ones(80, dtype=bool))
        self.assertEqual((low, high, total), (2**80, 1, 2**80))
        self.assertEqual(Fraction(2 * min(low, high), total), Fraction(1, 2**79))

    def test_no_nonzero_difference(self):
        self.assertEqual(rank_exact.signed_rank_tails([], []), (1, 1, 1))

    def test_distinct_moduli_budget(self):
        data = pd.read_csv(DATA / "budget.csv")
        diff = (data.First - data.Second).to_numpy()
        with self.assertRaises(ExactBudgetExceeded):
            rank_exact.signed_rank_tails(rank_exact.doubled_ranks(np.abs(diff)), diff > 0)

    def test_distribution_is_symmetric_and_complete(self):
        # The counts add up to 2^n and are symmetric about half the doubled total,
        # on both sides of the int64 / object boundary (2^62).
        for size in (61, 66):
            ranks = rank_exact.doubled_ranks(np.arange(1.0, size + 1))
            sums, counts = rank_exact._distribution(rank_exact._blocks(ranks), None, rank_exact.MAX_STATES,
                                                    rank_exact.MAX_TRANSITIONS)
            self.assertEqual(counts.dtype == object, size == 66)
            self.assertEqual(sum(counts.tolist()), 2**size)
            by_sum = dict(zip(sums.tolist(), counts.tolist()))
            top = int(ranks.sum())
            self.assertTrue(all(by_sum[s] == by_sum[top - s] for s in by_sum))
            low, high, total = rank_exact.signed_rank_tails(ranks, np.arange(size) % 2 == 0)
            observed = int(ranks[np.arange(size) % 2 == 0].sum())
            self.assertEqual(low, sum(c for s, c in by_sum.items() if s <= observed))
            self.assertEqual(high, sum(c for s, c in by_sum.items() if s >= observed))


if __name__ == "__main__":
    unittest.main()
