"""Independent permutation oracles and bounded extended Spearman contracts."""
from itertools import combinations, permutations
from math import comb, factorial
import threading
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from analisi.correlation_details import correlation_statistics
from analisi.field_error import FieldError
from analisi.workbench import analyse

EXTENDED = "Extended (17 pairs)"
FIELD = "Spearman exact budget"


class ExtendedCorrelation(unittest.TestCase):
    def test_new_option_is_explicit_and_legacy_stays_unchanged(self):
        x = np.arange(11.)
        old = correlation_statistics(x, x, method="Spearman")
        self.assertEqual(old["P method"], "Approximate")
        with self.assertRaises(FieldError):
            correlation_statistics(x, x, method="Spearman", p_method="Exact")
        new = correlation_statistics(x, x, method="Spearman", exact_budget=EXTENDED)
        self.assertEqual(new["P method"], "Exact")
        self.assertAlmostEqual(new["p"] / (2 / factorial(11)), 1., places=13)

    def test_perfect_and_reverse_tails_ten_through_seventeen(self):
        from analisi.spearman_exact_budget import ExactSpearmanFamily
        for n in range(10, 18):
            family = ExactSpearmanFamily()
            x = np.arange(float(n))
            for y, alternative, expected in ((x, "Two-sided", 2/factorial(n)),
                                              (x[::-1], "Negative", 1/factorial(n)),
                                              (x, "Positive", 1/factorial(n))):
                got = correlation_statistics(x, y, method="Spearman", alternative=alternative,
                                             exact_budget=EXTENDED, exact_family=family)
                self.assertAlmostEqual(got["p"]/expected, 1., places=14)

    def test_seventeen_pairs_binary_ties_match_subset_enumeration(self):
        # Each choice of eight labelled ranks has the same 8! 9! multiplicity.
        x = np.arange(17.)
        y = np.array([1.] * 8 + [0.] * 9)
        y[[0, 8]] = y[[8, 0]]
        observed = sum(x[y == 1])
        totals = np.array([sum(c) for c in combinations(range(17), 8)])
        center = 8 * 8
        expected = {"Two-sided": np.mean(abs(totals-center) >= abs(observed-center)),
                    "Positive": np.mean(totals >= observed), "Negative": np.mean(totals <= observed)}
        from analisi.spearman_exact_budget import ExactSpearmanFamily
        family = ExactSpearmanFamily()
        for alternative, oracle in expected.items():
            got = correlation_statistics(x, y, method="Spearman", alternative=alternative,
                                         exact_budget=EXTENDED, exact_family=family)
            self.assertEqual(got["P method"], "Exact")
            self.assertAlmostEqual(got["p"], oracle, places=14)

    def test_small_asymmetric_ties_all_tails_match_labelled_permutations(self):
        x = np.array([0, 0, 2, 3, 4, 5.])
        y = np.array([0, 1, 1, 1, 4, 3.])
        rx, ry = stats.rankdata(x), stats.rankdata(y)
        observed = np.dot(rx-rx.mean(), ry-ry.mean())
        values = np.array([np.dot(rx-rx.mean(), np.array(p)-ry.mean()) for p in permutations(ry)])
        for alt, mask in (("Two-sided", abs(values) >= abs(observed)),
                          ("Positive", values >= observed), ("Negative", values <= observed)):
            got = correlation_statistics(x, y, method="Spearman", alternative=alt, exact_budget=EXTENDED)
            self.assertAlmostEqual(got["p"], np.mean(mask), places=14)

    def test_random_small_ties_reflections_and_shuffles(self):
        rng = np.random.default_rng(20261116)
        for n in (4, 5, 6, 7):
            for _ in range(3):
                x, y = rng.integers(0, 3, size=(2, n))
                if len(set(x)) < 2 or len(set(y)) < 2:
                    continue
                rx, ry = 2*stats.rankdata(x), 2*stats.rankdata(y)
                scores = np.array([np.dot(rx, p) for p in permutations(ry)])
                observed = np.dot(rx, ry)
                centered = n*scores - sum(rx)*sum(ry)
                threshold = abs(n*observed-sum(rx)*sum(ry))
                for alt, mask in (("Two-sided", abs(centered) >= threshold),
                                  ("Positive", scores >= observed), ("Negative", scores <= observed)):
                    got = correlation_statistics(x, y, method="Spearman", alternative=alt, exact_budget=EXTENDED)
                    self.assertAlmostEqual(got["p"], np.mean(mask), places=14)

    def test_automatic_eighteen_explains_and_exact_rejects(self):
        x = np.arange(18.)
        got = correlation_statistics(x, x, method="Spearman", exact_budget=EXTENDED)
        self.assertEqual(got["P method"], "Approximate")
        self.assertIn("17", got["Reason"])
        with self.assertRaises(FieldError):
            correlation_statistics(x, x, method="Spearman", exact_budget=EXTENDED, p_method="Exact")

    def test_inactive_budget_is_ignored(self):
        for method, p_method in (("Pearson", "Automatic"), ("Kendall", "Automatic"),
                                 ("Spearman", "Approximate")):
            got = correlation_statistics([1, 2, 3, 4], [1, 3, 2, 4], method=method,
                                         p_method=p_method, exact_budget="inactive garbage")
            self.assertTrue(np.isfinite(got["p"]))

    def test_dispatcher_control_deduplicates_twenty_four_untied_responses(self):
        x = np.arange(10.)
        frame = pd.DataFrame({"X": x, **{f"Y{i}": np.roll(x, i) for i in range(24)}})
        options = {"X": "X", "Variables": [f"Y{i}" for i in range(24)], "Method": "Spearman", FIELD: EXTENDED}
        got = analyse("Correlate against control", frame, options)
        self.assertEqual(got.tables["Correlations"]["P method"].tolist(), ["Exact"]*24)
        self.assertIn("17", str(got.tables["Settings"].to_dict()))


class ResourceBudgets(unittest.TestCase):
    def test_layer_span_sum_matches_independent_subset_rearrangement(self):
        from analisi.spearman_exact_budget import layer_spans
        left, right = (0, 1, 1, 3, 4, 6), (0, 0, 2, 3, 3, 5)
        actual = layer_spans(left, right)
        oracle = [1]
        for k in range(1, 7):
            spans = [sum(a*b for a, b in zip(left[:k], c)) -
                     sum(a*b for a, b in zip(left[:k], reversed(c))) + 1 for c in combinations(right, k)]
            oracle.append(sum(spans))
        self.assertEqual(actual, tuple(oracle))

    def test_resource_rejection_precedes_dense_allocation(self):
        from analisi.spearman_exact_budget import ExactSpearmanFamily
        family = ExactSpearmanFamily(max_bytes=1)
        with patch("analisi.spearman_exact_budget._count_permutation_distribution") as count:
            got = correlation_statistics(np.arange(12.), np.arange(12.), method="Spearman",
                                         exact_budget=EXTENDED, exact_family=family)
            self.assertEqual(got["P method"], "Approximate")
            self.assertIn("storage", got["Reason"])
            with self.assertRaises(FieldError) as error:
                correlation_statistics(np.arange(12.), np.arange(12.), method="Spearman", p_method="Exact",
                                       exact_budget=EXTENDED, exact_family=family)
            self.assertEqual(error.exception.field, FIELD)
            count.assert_not_called()

    def test_storage_boundary_and_real_different_tie_shapes(self):
        from analisi.spearman_exact_budget import ExactSpearmanFamily, storage_bound
        from analisi.correlation_matrix import _exact_key, _rank_scores
        for y in (np.arange(8.), np.array([0, 0, 2, 3, 3, 5, 6, 7.])):
            x = np.arange(8.)
            key = _exact_key(_rank_scores(stats.rankdata(x)), _rank_scores(stats.rankdata(y)))
            limit = storage_bound(key)
            below = correlation_statistics(x, y, method="Spearman", exact_budget=EXTENDED,
                                          exact_family=ExactSpearmanFamily(max_bytes=limit-1))
            at = correlation_statistics(x, y, method="Spearman", exact_budget=EXTENDED,
                                       exact_family=ExactSpearmanFamily(max_bytes=limit))
            self.assertEqual(below["P method"], "Approximate")
            self.assertEqual(at["P method"], "Exact")

    def test_family_work_and_duplicate_distributions(self):
        from analisi.spearman_exact_budget import ExactSpearmanFamily
        family = ExactSpearmanFamily(max_work=10*2**9)
        x = np.arange(10.)
        for y in (x, x[::-1], np.roll(x, 3)):
            got = correlation_statistics(x, y, method="Spearman", exact_budget=EXTENDED, exact_family=family)
            self.assertEqual(got["P method"], "Exact")
        tied = x.copy(); tied[1] = 0
        got = correlation_statistics(x, tied, method="Spearman", exact_budget=EXTENDED, exact_family=family)
        self.assertEqual(got["P method"], "Approximate")
        self.assertIn("family", got["Reason"])

    def test_cancel_is_checked_during_counting_and_not_cached(self):
        from analisi.spearman_exact_budget import ExactSpearmanFamily, ExactSpearmanCancelled
        event = threading.Event()
        family = ExactSpearmanFamily(cancel=event)
        event.set()
        with self.assertRaises(ExactSpearmanCancelled):
            correlation_statistics(np.arange(12.), np.arange(12.), method="Spearman",
                                   exact_budget=EXTENDED, exact_family=family)
        event.clear()
        got = correlation_statistics(np.arange(12.), np.arange(12.), method="Spearman",
                                     exact_budget=EXTENDED, exact_family=family)
        self.assertEqual(got["P method"], "Exact")

    def test_cancellation_interrupts_a_partial_distribution(self):
        from analisi.spearman_exact_budget import ExactSpearmanFamily, ExactSpearmanCancelled
        class CancelAfterBatches:
            calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls >= 12
        cancel = CancelAfterBatches()
        family = ExactSpearmanFamily(cancel=cancel)
        with self.assertRaises(ExactSpearmanCancelled):
            correlation_statistics(np.arange(17.), np.arange(17.), method="Spearman",
                                   exact_budget=EXTENDED, exact_family=family)
        self.assertEqual(family.distributions, {})
        self.assertEqual(family.used_work, 0)
