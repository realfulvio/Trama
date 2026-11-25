"""The exact rank tests give up before doing work they could never finish (0.109.x).

The budget floors only predict failures the dynamic programme would certainly reach, so every
exact result is unchanged, and large samples reach the normal approximation in milliseconds.
"""
import itertools
import time
import unittest

import numpy as np
import pandas as pd

from analisi import rank_exact
from analisi.workbench import analyse


def run(blocks, take, states, transitions):
    try:
        rank_exact._distribution(blocks, take, states, transitions)
    except rank_exact.ExactBudgetExceeded:
        return False
    return True


class BudgetFloorTest(unittest.TestCase):
    def test_state_floor_never_exceeds_the_distinct_sums(self):
        rng = np.random.default_rng(11)
        for _ in range(300):
            size = int(rng.integers(2, 12))
            values = rng.integers(0, int(rng.integers(1, 6)), size).astype(float)
            take = int(rng.integers(1, size))
            doubled = rank_exact.doubled_ranks(values)
            sums = {sum(c) for c in itertools.combinations(doubled.tolist(), take)}
            self.assertLessEqual(rank_exact.mann_whitney_state_floor(doubled, take), len(sums))
        untied = rank_exact.doubled_ranks(np.arange(20.0))
        self.assertEqual(rank_exact.mann_whitney_state_floor(untied, 7), 7 * 13 + 1)

    def test_floors_only_announce_failures_that_would_happen(self):
        rng = np.random.default_rng(12)
        for _ in range(1500):
            size = int(rng.integers(2, 50))
            values = rng.integers(0, int(rng.integers(1, 30)), size).astype(float)
            doubled = rank_exact.doubled_ranks(values)
            states, transitions = int(rng.integers(5, 400)), int(rng.integers(20, 4000))
            take = int(rng.integers(1, size)) if size > 1 else 1
            take = min(take, size - take) or 1
            if rank_exact._mann_whitney_budget_floor(doubled, take, states, transitions) is not None:
                self.assertFalse(run(rank_exact._blocks(doubled), take, states, transitions))
            positive = rank_exact.doubled_ranks(values + 1)
            if rank_exact._signed_rank_budget_floor(positive, states, transitions) is not None:
                self.assertFalse(run(rank_exact._blocks(positive), None, states, transitions))

    def test_exact_results_are_unchanged_below_the_limits(self):
        from unittest.mock import patch
        rng = np.random.default_rng(13)
        for size in (8, 20, 40, 60):
            values = np.round(rng.normal(size=size), 1)
            first = np.arange(size) < size // 3
            doubled = rank_exact.doubled_ranks(values)
            result = rank_exact.mann_whitney_tails(doubled, first)
            with patch.object(rank_exact, "_mann_whitney_budget_floor", return_value=None):
                self.assertEqual(result, rank_exact.mann_whitney_tails(doubled, first))
            positive = doubled[: size // 2]
            signs = np.arange(len(positive)) % 3 == 0
            result = rank_exact.signed_rank_tails(positive, signs)
            with patch.object(rank_exact, "_signed_rank_budget_floor", return_value=None):
                self.assertEqual(result, rank_exact.signed_rank_tails(positive, signs))

    def test_large_samples_reach_the_normal_approximation_quickly(self):
        rng = np.random.default_rng(14)
        size = 100_000
        groups = pd.DataFrame({"Group": np.where(rng.random(size) < .5, "A", "B"), "Value": rng.normal(size=size)})
        started = time.perf_counter()
        table = analyse("Mann–Whitney", groups, {"Response": "Value", "Group": "Group", "P value": "Automatic",
                                                 "Alternative": "Two-sided", "Continuity correction": True}).tables["Mann–Whitney"]
        self.assertLess(time.perf_counter() - started, 5)
        self.assertEqual(table.loc["p method", "Value"], "Normal approximation")
        pairs = pd.DataFrame({"A": rng.normal(size=20_000)})
        pairs["B"] = pairs["A"] + rng.normal(.1, 1, len(pairs))
        started = time.perf_counter()
        analyse("Wilcoxon signed-rank", pairs, {"First": "A", "Second": "B", "P value": "Automatic", "Alternative": "Two-sided",
                                                 "Continuity correction": True, "Zero differences": "Discard"})
        self.assertLess(time.perf_counter() - started, 1)


if __name__ == "__main__":
    unittest.main()
