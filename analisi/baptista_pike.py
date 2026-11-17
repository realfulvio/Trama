"""Exact conditional odds-ratio limits using probability ordering."""
from math import exp, inf, log, log1p

import numpy as np
from scipy.optimize import brentq


MAX_TABLES = 4096


def _log_step(numerator, denominator):
    # Preserve precision near a tie even for large integer margins.
    if 2 * numerator >= denominator and numerator <= 2 * denominator:
        return log1p((numerator - denominator) / denominator)
    return log(numerator / denominator)


def _lower_log_limit(relative, observed, alpha):
    if observed == 0:
        return -inf
    offsets = np.arange(len(relative)) - observed
    crossings = -relative[:observed] / offsets[:observed]

    def weights_at(log_odds):
        logs = relative + offsets * log_odds
        return np.exp(logs - logs.max())

    # Log concavity orders the ties from left to right. Up to the last tie,
    # all tables at or above the observed count are in the rejection tails.
    previous = crossings[0] - 64.
    for entering, crossing in enumerate(crossings):
        weights = weights_at(crossing)
        total = weights.sum()
        tail = weights[:entering].sum() + weights[observed:].sum()
        if tail / total >= alpha:
            def difference(log_odds):
                weights = weights_at(log_odds)
                return (weights[:entering].sum() + weights[observed:].sum()) / weights.sum() - alpha

            return brentq(difference, previous, crossing, xtol=1e-14)
        # At the tie the newly equal table is included. At the last tie
        # every table is included, so the probability is exactly one.
        if entering == observed - 1 or (weights[:entering + 1].sum() + weights[observed:].sum()) / total >= alpha:
            return crossing
        previous = crossing


def baptista_pike(counts, level):
    """Sample odds ratio and outer limits of the exact two-sided conditional test.

    The caller checks for positive margins and at most MAX_TABLES tables.
    """
    a, b, c, d = map(int, counts.ravel())
    row, column, total = a + b, a + c, a + b + c + d
    start, end = max(0, row + column - total), min(row, column)
    observed = a - start
    steps = np.array([
        _log_step((column - count) * (row - count), (count + 1) * (total - column - row + count + 1))
        for count in range(start, end)
    ])
    relative = np.r_[-np.cumsum(steps[:observed][::-1])[::-1], 0., np.cumsum(steps[observed:])]
    alpha = (100 - level) / 100
    lower = _lower_log_limit(relative, observed, alpha)
    reverse_lower = _lower_log_limit(relative[::-1], end - a, alpha)
    return a * d / (b * c) if b and c else inf, exp(lower), exp(-reverse_lower)
