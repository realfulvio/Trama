"""Bounded labelled-permutation Spearman tests, including average-rank ties.

The storage estimate bounds live dense arrays and adds an explicit bookkeeping
allowance; it is not a promise about total process RSS or the Python allocator.
No global cache: retained distributions belong to one analysis family only.
"""
from math import comb

import numpy as np
from scipy import stats

from .correlation_matrix import _count_permutation_distribution, _exact_key, _rank_scores
from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled

FIELD = "Spearman exact budget"
EXTENDED = "Extended (17 pairs)"
STANDARD = "Standard (9 pairs)"
BUDGETS = (EXTENDED, STANDARD)
MAX_PAIRS = 17
MAX_WORK = 4_000_000
MAX_BYTES = 384 * 1024**2
STATE_ALLOWANCE = 512


class ExactSpearmanCancelled(MonteCarloCancelled):
    """Cancellation before publishing a partial correlation family."""


def layer_spans(left, right):
    """Exact sum of inclusive dot-product spans for every subset at each layer.

    Rearrangement gives each subset's extreme products. The jth order statistic
    right[i] appears C(i,j)*C(n-i-1,k-j-1) times among k-subsets. Summing these
    contributions avoids enumerating 2**n states just to plan memory.
    """
    n = len(left)
    result = [1]
    for k in range(1, n + 1):
        span = comb(n, k)
        for j in range(k):
            total = sum(right[i] * comb(i, j) * comb(n-i-1, k-j-1)
                        for i in range(j, n-k+j+1))
            span += (left[j] - left[k-1-j]) * total
        result.append(span)
    return tuple(result)


def storage_bound(key):
    """Bytes for adjacent array layers, state allowance, and final score array."""
    left, right = key
    spans = layer_spans(left, right)
    n = len(left)
    return max(8*(spans[k-1]+spans[k]) + STATE_ALLOWANCE*(comb(n,k-1)+comb(n,k))
               for k in range(1, n+1)) + 8*spans[-1] + 4096


def extended_request(method, options):
    return (method in ("Correlation", "Correlate against control")
            and (method != "Correlation" or options.get("Detailed results") is True)
            and options.get("Method") == "Spearman"
            and options.get("Spearman p values", "Automatic") != "Approximate"
            and options.get(FIELD, STANDARD) == EXTENDED)


class ExactSpearmanFamily:
    """Deterministic work and simultaneous-storage limits for distinct null laws."""
    def __init__(self, *, max_work=MAX_WORK, max_bytes=MAX_BYTES, cancel=None):
        self.max_work, self.max_bytes, self.cancel = max_work, max_bytes, cancel
        self.used_work = self.retained_bytes = 0
        self.distributions = {}

    def check(self):
        if self.cancel is not None and self.cancel.is_set():
            raise ExactSpearmanCancelled("Exact Spearman calculation cancelled.")

    def probability(self, x, y, alternative, p_method):
        self.check()
        n = len(x)
        reason = ""
        if n > MAX_PAIRS:
            reason = f"n = {n} exceeds the exact budget of {MAX_PAIRS} pairs."
        else:
            sx, sy = _rank_scores(stats.rankdata(x)), _rank_scores(stats.rankdata(y))
            key = _exact_key(sx, sy)
            if key not in self.distributions:
                cost = n * (1 << (n-1))
                if self.used_work + cost > self.max_work:
                    reason = "The exact family work budget is exceeded."
                elif storage_bound(key) + self.retained_bytes > self.max_bytes:
                    reason = "The exact dense storage budget is exceeded."
                else:
                    # Check before allocation and within every DP layer/batch.
                    self.check()
                    scores, counts = _count_permutation_distribution(*key, check=self.check)
                    self.check()
                    self.distributions[key] = scores, counts
                    self.used_work += cost
                    self.retained_bytes += scores.nbytes + counts.nbytes + 1024
            if not reason:
                scores, counts = self.distributions[key]
                score = int(sx @ sy)
                if alternative == "Two-sided":
                    center = sum(key[0]) * sum(key[1])
                    tail = abs(n*scores-center) >= abs(n*score-center)
                elif alternative == "Positive":
                    tail = scores >= score
                else:
                    tail = scores <= score
                return float(counts[tail].sum() / counts.sum()), ""
        if p_method == "Exact":
            raise FieldError(FIELD, reason + " Choose Automatic or a smaller analysis.")
        return None, "Automatic Spearman p values use the t approximation. " + reason
