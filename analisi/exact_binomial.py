"""Exact binomial test and Clopper–Pearson interval for two observed categories.

The numbers are exact binomial masses from SciPy. Nothing here allocates an array that grows with the
total count, and no tail is computed as ``1 - cdf``: the upper tail comes from the survival function.
"""
from math import isfinite, log1p

import numpy as np
from scipy.stats import beta, binom

from .field_error import FieldError

PEARSON, EXACT = "Pearson chi-square", "Exact binomial"
TEST_METHODS = (PEARSON, EXACT)
LEVEL_FIELD = "Confidence level (%)"
DEFAULT_LEVEL = 95.0
MAX_TOTAL = 10_000_000
# SciPy's two-sided test uses the same relative allowance on the mass of the observed count.
TIE_TOLERANCE = 1e-7
# Below this mass the comparison is done on logarithms.
DEEP_TAIL = 1e-250


def confidence_level(value):
    """Return a level strictly between 0 and 100 whose complement is also strictly between 0 and 100."""
    try:
        if isinstance(value, (bool, np.bool_)):
            raise TypeError
        level = float(value)
    except (TypeError, ValueError, OverflowError):
        level = np.nan
    if not isfinite(level) or not 0 < level < 100 or not 0 < 100 - level < 100:
        raise FieldError(LEVEL_FIELD, "Choose a confidence level strictly between 0 and 100.")
    return level


def null_proportion(first, total):
    """First weight over the total weight, or None when it cannot sit strictly between 0 and 1."""
    p0 = first / total
    return p0 if 0 < p0 < 1 else None


def _mode(n, p0):
    """A global mode of Binomial(n, p0): the best of the floating-point neighbours of (n + 1) p0."""
    guess = min(n, max(0, int(np.floor((n + 1) * p0))))
    near = [j for j in (guess - 1, guess, guess + 1) if 0 <= j <= n]
    return near[int(np.argmax(binom.pmf(near, n, p0)))]


def _boundary(predicate, low, high):
    """Smallest j in [low, high] where ``predicate`` holds, or high + 1; ``predicate`` is monotone."""
    while low <= high:
        middle = (low + high) // 2
        if predicate(middle):
            high = middle - 1
        else:
            low = middle + 1
    return low


def _not_above(k, n, p0):
    """Test j -> P(X = j) <= P(X = k) within the tie tolerance.

    Masses are compared directly. When the mass at k is too small to keep full precision the
    comparison moves to logarithms, so a count deep in a tail still excludes its own neighbours.
    """
    at_k = float(binom.pmf(k, n, p0))
    if at_k >= DEEP_TAIL:
        limit = at_k * (1 + TIE_TOLERANCE)
        return lambda j: float(binom.pmf(j, n, p0)) <= limit
    log_limit = float(binom.logpmf(k, n, p0)) + log1p(TIE_TOLERANCE)
    return lambda j: float(binom.logpmf(j, n, p0)) <= log_limit


def tails(k, n, p0):
    """P(X <= k) and P(X >= k), both inclusive, for X ~ Binomial(n, p0)."""
    return float(binom.cdf(k, n, p0)), float(binom.sf(k - 1, n, p0))


def two_sided(k, n, p0):
    """Sum of P(X = j) over the integers j with P(X = j) <= P(X = k), ties included.

    The mass is unimodal, so each tail of the set is found by bisection around the mode
    and then added with the cumulative and survival functions.
    """
    mode = _mode(n, p0)
    not_above = _not_above(k, n, p0)
    if not_above(mode):
        return 1.0
    # Left of the mode the mass rises: the set is 0..a. Right of it the mass falls: the set is b..n.
    a = _boundary(lambda j: not not_above(j), 0, mode) - 1
    b = _boundary(not_above, mode, n)
    if k <= mode:
        a = max(a, k)
    if k >= mode:
        b = min(b, k)
    lower = float(binom.cdf(a, n, p0)) if a >= 0 else 0.0
    upper = float(binom.sf(b - 1, n, p0)) if b <= n else 0.0
    return min(1.0, lower + upper)


def clopper_pearson(k, n, level):
    """Equal-tailed exact interval for k / n; the limits are exactly 0 and 1 at the extremes."""
    tail = (100.0 - level) / 200.0
    lower = 0.0 if k == 0 else float(beta.ppf(tail, k, n - k + 1))
    upper = 1.0 if k == n else float(beta.isf(tail, k + 1, n - k))
    return lower, upper
