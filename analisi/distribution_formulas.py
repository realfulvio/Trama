"""Probability, density and quantile functions for worksheet formulas.

Each function accepts scalars or worksheet columns and broadcasts them row by row. Invalid
arguments on a row (missing, non-finite, outside the domain, or an unknown tail coming from a
column) leave only that row blank, so the sheet keeps its index, length and order. A literal tail
that is not recognised is a formula error, reported before the formula is stored.

Conventions:

* ``"left"`` is the cumulative distribution, ``"right"`` the survival function.
* ``"one"`` is the smaller tail beyond the value relative to the mean, ``"two"`` twice that tail.
* A probability alone cannot tell which side a ``"one"`` or ``"two"`` quantile lies on, so the
  inverses return the upper, symmetric branch (at or above the mean).
* Upper tails and upper quantiles are computed directly, never as ``1 - p``, so very small
  probabilities keep their relative precision. Far in the t and F tails, where SciPy's inverses
  stop converging or t squared overflows, the leading term of the incomplete beta series is used
  in logarithms; a result beyond the double range is blank.
"""
from math import log, pi

import numpy as np
import pandas as pd
from scipy import special, stats

TAILS = ("left", "right", "one", "two")
_LEFT, _RIGHT, _ONE, _TWO = range(len(TAILS))
_TAIL_CODES = {name: code for code, name in enumerate(TAILS)}
_LOG_SQRT_TWO_PI = 0.5 * log(2 * pi)


def argument_count_message(name, arity):
    """Explain the accepted number of arguments for a function with optional arguments."""
    low, high = arity.start, arity.stop - 1
    if low == high:
        return f"{name} takes {low} argument{'s' if low != 1 else ''}."
    return f"{name} takes {low} to {high} arguments."


def _numbers(name, value):
    """Return finite floats; anything missing, non-numeric or infinite becomes NaN on its row."""
    if isinstance(value, str):
        raise ValueError(f"{name} needs numbers in its numeric arguments; text is only accepted as the tail.")
    array = np.asarray(value)
    if array.dtype.kind in "OUST":
        if array.ndim == 0:
            raise ValueError(f"{name} needs numbers in its numeric arguments; text is only accepted as the tail.")
        # Text columns and IF results with blanks: numbers stay, other cells are treated as missing.
        array = pd.to_numeric(pd.Series(array.ravel(), dtype=object), errors="coerce").to_numpy(
            dtype=float, na_value=np.nan).reshape(array.shape)
    else:
        array = array.astype(float)
    return np.where(np.isfinite(array), array, np.nan)


def _tail_codes(name, value):
    """Map a tail literal (strict) or a text column (row by row, unknown -> -1) to integer codes."""
    array = np.asarray(value)
    if isinstance(value, str) or array.ndim == 0:
        item = value if isinstance(value, str) else array.item()
        key = item.strip().casefold() if isinstance(item, str) else None
        if key not in _TAIL_CODES:
            raise ValueError(f'{name}: the tail must be "left", "right", "one" or "two" (got {item!r}).')
        return np.asarray(_TAIL_CODES[key])
    texts = pd.Series(array.ravel(), dtype=object)
    texts = texts.where(texts.map(type).eq(str))
    codes = texts.str.strip().str.casefold().map(_TAIL_CODES)
    return codes.fillna(-1).to_numpy(dtype=int).reshape(array.shape)


def _shape(*arrays):
    return np.broadcast_shapes(*(np.shape(array) for array in arrays))


def _finish(valid, result):
    """Blank the invalid rows and the infinite results, keeping scalars as scalars."""
    with np.errstate(all="ignore"):
        result = np.where(valid & np.isfinite(result), result, np.nan)
    return result if result.ndim else float(result)


def _finite(*arrays):
    valid = np.ones(_shape(*arrays), dtype=bool)
    for array in arrays:
        valid &= ~np.isnan(array)
    return valid


def _safe(valid, array, fallback):
    """Replace inputs of invalid rows so the special functions never see them."""
    return np.where(valid, array, fallback)


# Normal family -------------------------------------------------------------------------------

def _standard_normal(x, mean, sd):
    distance = x - mean
    # Opposite finite values may overflow the subtraction before scaling.
    return np.where(np.isfinite(distance), distance / sd, x / sd - mean / sd)


def _normal_probability(name, x, mean, sd, tail):
    x, mean, sd = (_numbers(name, value) for value in (x, mean, sd))
    code = _tail_codes(name, tail)
    valid = _finite(x, mean, sd) & (np.nan_to_num(sd) > 0) & (code >= 0)
    with np.errstate(all="ignore"):
        z = _safe(valid, _standard_normal(x, mean, _safe(valid, sd, 1.0)), 0.0)
        smaller = special.ndtr(-np.abs(z))
        result = np.select([code == _LEFT, code == _RIGHT, code == _ONE],
                           [special.ndtr(z), special.ndtr(-z), smaller], np.minimum(2 * smaller, 1.0))
    return _finish(valid, result)


def _normal_quantile(name, p, mean, sd, tail):
    p, mean, sd = (_numbers(name, value) for value in (p, mean, sd))
    code = _tail_codes(name, tail)
    probability = np.nan_to_num(p, nan=-1.0)
    # Left and right exclude both ends; the symmetric upper branches admit p = 0.5 and p = 1.
    inside = (probability > 0) & np.select([code == _ONE, code == _TWO],
                                           [probability <= 0.5, probability <= 1], probability < 1)
    valid = _finite(p, mean, sd) & (np.nan_to_num(sd) > 0) & (code >= 0) & inside
    with np.errstate(all="ignore"):
        p = _safe(valid, p, 0.5)
        # The upper branch uses the quantile of the upper tail directly: -ndtri(q) is the isf of q.
        standard = np.select([code == _LEFT, code == _RIGHT, code == _ONE],
                             [special.ndtri(p), -special.ndtri(p), -special.ndtri(p)],
                             -special.ndtri_exp(np.log(p) - log(2.0)))
        result = mean + sd * standard
    return _finish(valid, result)


def _normal_density(name, x, mean, sd):
    x, mean, sd = (_numbers(name, value) for value in (x, mean, sd))
    valid = _finite(x, mean, sd) & (np.nan_to_num(sd) > 0)
    with np.errstate(all="ignore"):
        sd = _safe(valid, sd, 1.0)
        z = _safe(valid, _standard_normal(x, mean, sd), 0.0)
        result = np.exp(-0.5 * z * z - _LOG_SQRT_TWO_PI - np.log(sd))
    return _finish(valid, result)


def normdist(x, mean=0.0, sd=1.0, tail="left"):
    return _normal_probability("NORMDIST", x, mean, sd, tail)


def norminv(p, mean=0.0, sd=1.0, tail="left"):
    return _normal_quantile("NORMINV", p, mean, sd, tail)


def normpdf(x, mean=0.0, sd=1.0):
    return _normal_density("NORMPDF", x, mean, sd)


def zdist(z, tail="left"):
    return _normal_probability("ZDIST", z, 0.0, 1.0, tail)


def zinv(p, tail="left"):
    return _normal_quantile("ZINV", p, 0.0, 1.0, tail)


def zpdf(z):
    return _normal_density("ZPDF", z, 0.0, 1.0)


# Student t, chi-square and F -------------------------------------------------------------------

def _positive(*arrays):
    valid = _finite(*arrays)
    for array in arrays:
        valid &= np.nan_to_num(array) > 0
    return valid


# Below this log, the incomplete beta I_x(a, b) equals its leading term x^a / (a B(a, b)) to double
# precision (the next term is about b x): far tails use logarithms, so they neither overflow nor underflow.
_LEADING_TERM_LOG = -230.0


def _only_where(mask, function, *args):
    """function(*args) on the rows of mask, 1.0 elsewhere: the beta inverses are the costly part."""
    *args, mask = np.broadcast_arrays(*args, mask)
    out = np.ones(mask.shape)
    function(*args, out=out, where=mask)
    return out


def _beta_inverse_pair(a, b, p):
    """Return (x, 1 - x, log x, far) with I_x(a, b) = p.

    The side below 1/2 is solved from the smaller of p and 1 - p, and the side near 1 from the
    complementary inverse, so both keep full precision. ``far`` marks rows where x comes from
    the leading term in logarithms and may underflow; ``log x`` is then the value to use.
    """
    a, b, p = np.broadcast_arrays(a, b, p)
    upper = p > 0.5
    first, second, q = np.where(upper, b, a), np.where(upper, a, b), np.where(upper, 1 - p, p)
    log_leading = (np.log(q) + np.log(first) + special.betaln(first, second)) / first
    far = log_leading + np.log(np.maximum(second, 1.0)) < _LEADING_TERM_LOG
    small = np.where(far, np.exp(log_leading), _only_where(~far, special.betaincinv, first, second, q))
    large = _only_where(~far, special.betainccinv, second, first, q)
    x, rest = np.where(upper, large, small), np.where(upper, small, large)
    return x, rest, np.where(far, log_leading, np.log(x)), far & ~upper


def _t_log_x(t, df):
    """log x for x = df / (df + t^2), without overflowing t^2."""
    ratio = np.abs(t) / np.sqrt(df)
    return np.where(ratio > 1e100, -2 * np.log(ratio), -np.log1p(t / df * t))


def tdist(t, df):
    """Upper tail P(T > t), from the incomplete beta so that very large |t| keeps its tail."""
    t, df = _numbers("TDIST", t), _numbers("TDIST", df)
    valid = _finite(t) & _positive(df)
    with np.errstate(all="ignore"):
        t, df = _safe(valid, t, 0.0), _safe(valid, df, 1.0)
        a = df / 2
        log_x = _t_log_x(t, df)
        # stdtr(df, -t) is the upper tail itself; past the leading-term threshold it underflows.
        far = log_x < _LEADING_TERM_LOG
        tail = 0.5 * np.exp(a * log_x - np.log(a) - special.betaln(a, 0.5))
        result = np.where(far, np.where(t >= 0, tail, 1 - tail), special.stdtr(df, -t))
    return _finish(valid, result)


def tinv(p, df):
    """Upper quantile whose upper tail is p / 2 (the two-sided critical value)."""
    p, df = _numbers("TINV", p), _numbers("TINV", df)
    valid = _positive(df) & (np.nan_to_num(p, nan=-1.0) > 0) & (np.nan_to_num(p, nan=2.0) <= 1)
    with np.errstate(all="ignore"):
        p, df = _safe(valid, p, 1.0), _safe(valid, df, 1.0)
        # Two-sided p = I_x(df/2, 1/2) with x = df / (df + t^2), so t^2 = df (1 - x) / x.
        x, w, log_x, far = _beta_inverse_pair(df / 2, 0.5, p)
        result = np.where(far, np.exp(0.5 * (np.log(df) - log_x)), np.sqrt(df * w / x))
    return _finish(valid, result)


def tpdf(t, df):
    t, df = _numbers("TPDF", t), _numbers("TPDF", df)
    valid = _finite(t) & _positive(df)
    with np.errstate(all="ignore"):
        df, t = _safe(valid, df, 1.0), _safe(valid, t, 0.0)
        log_x = _t_log_x(t, df)
        # log(1 + t^2 / df) = -log x.
        log_density = (np.log(special.poch(0.5 * df, 0.5)) - 0.5 * np.log(df * pi) + 0.5 * (df + 1) * log_x)
        result = np.exp(log_density)
    return _finish(valid, result)


def _chi_square_arguments(name, x, df):
    x, df = _numbers(name, x), _numbers(name, df)
    valid = _finite(x) & (np.nan_to_num(x, nan=-1.0) >= 0) & _positive(df)
    return _safe(valid, x, 0.0), _safe(valid, df, 1.0), valid


def chidist(x, df):
    """Upper tail P(X > x)."""
    x, df, valid = _chi_square_arguments("CHIDIST", x, df)
    with np.errstate(all="ignore"):
        return _finish(valid, special.chdtrc(df, x))


def chisqc(x, df):
    """Cumulative distribution P(X <= x)."""
    x, df, valid = _chi_square_arguments("CHISQC", x, df)
    with np.errstate(all="ignore"):
        return _finish(valid, special.chdtr(df, x))


def chiinv(p, df):
    """Quantile whose upper tail is p."""
    p, df = _numbers("CHIINV", p), _numbers("CHIINV", df)
    valid = _positive(df) & (np.nan_to_num(p, nan=-1.0) > 0) & (np.nan_to_num(p, nan=2.0) <= 1)
    with np.errstate(all="ignore"):
        result = special.chdtri(_safe(valid, df, 1.0), _safe(valid, p, 0.5))
    return _finish(valid, result)


def _f_arguments(name, x, df1, df2):
    x, df1, df2 = (_numbers(name, value) for value in (x, df1, df2))
    valid = _finite(x) & (np.nan_to_num(x, nan=-1.0) >= 0) & _positive(df1, df2)
    return _safe(valid, x, 1.0), _safe(valid, df1, 1.0), _safe(valid, df2, 1.0), valid


def fdist(x, df1, df2):
    """Upper tail P(F > x)."""
    x, df1, df2, valid = _f_arguments("FDIST", x, df1, df2)
    with np.errstate(all="ignore"):
        return _finish(valid, special.fdtrc(df1, df2, x))


def finv(p, df1, df2):
    """Quantile whose upper tail is p."""
    p, df1, df2 = (_numbers("FINV", value) for value in (p, df1, df2))
    valid = _positive(df1, df2) & (np.nan_to_num(p, nan=-1.0) > 0) & (np.nan_to_num(p, nan=2.0) <= 1)
    with np.errstate(all="ignore"):
        p, df1, df2 = _safe(valid, p, 0.5), _safe(valid, df1, 1.0), _safe(valid, df2, 1.0)
        # With x the quantile, p = I_v(df2/2, df1/2) for v = df2 / (df2 + df1 x), and u = 1 - v.
        v, u, log_v, far = _beta_inverse_pair(df2 / 2, df1 / 2, p)
        near = np.where(u == 0, 0.0, df2 * u / (df1 * v))
        result = np.where(far, np.exp(np.log(df2) - np.log(df1) - log_v), near)
    return _finish(valid, result)


def fpdf(x, df1, df2):
    x, df1, df2, valid = _f_arguments("FPDF", x, df1, df2)
    with np.errstate(all="ignore"):
        scaled = df1 * x
        total = df2 + scaled
        # Evaluate the beta density on the side of 1/2 where its argument keeps full precision.
        jacobian = (df1 / total) * (df2 / total)
        lower = stats.beta.pdf(scaled / total, df1 / 2, df2 / 2) * jacobian
        upper = stats.beta.pdf(df2 / total, df2 / 2, df1 / 2) * jacobian
        result = np.where(scaled > df2, upper, lower)
        # Where those products underflow, use log u^(df1/2) v^(df2/2) / (x B) with u = 1 - v = df1 x / total.
        log_ratio = np.log(df1) + np.log(x) - np.log(df2)
        log_density = (-0.5 * df1 * np.logaddexp(0.0, -log_ratio) - 0.5 * df2 * np.logaddexp(0.0, log_ratio)
                       - np.log(x) - special.betaln(df1 / 2, df2 / 2))
        result = np.where((x > 0) & ~(result > 1e-280), np.exp(log_density), result)
        # At x = 0 the density is infinite below two numerator df, one at two, and zero above.
        result = np.where(x == 0, np.select([df1 < 2, df1 == 2], [np.inf, 1.0], 0.0), result)
    return _finish(valid, result)


# Binomial, error function and probit -----------------------------------------------------------

def binomial(k, n, p):
    """Inclusive upper tail P(K >= k) of a binomial with n trials and success probability p."""
    k, n, p = (_numbers("BINOMIAL", value) for value in (k, n, p))
    with np.errstate(all="ignore"):
        whole = (np.floor(k) == k) & (np.floor(n) == n)
        valid = (_finite(k, n, p) & whole & (np.nan_to_num(k, nan=-1.0) >= 0)
                 & (np.nan_to_num(k) <= np.nan_to_num(n, nan=-1.0))
                 & (np.nan_to_num(p, nan=-1.0) >= 0) & (np.nan_to_num(p, nan=2.0) <= 1))
        k, n, p = _safe(valid, k, 1.0), _safe(valid, n, 1.0), _safe(valid, p, 0.5)
        # P(K >= k) = I_p(k, n - k + 1) for k >= 1; the regularized beta keeps small tails exact.
        result = np.where(k == 0, 1.0, special.betainc(np.maximum(k, 1.0), n - k + 1, p))
    return _finish(valid, result)


def erf(x):
    x = _numbers("ERF", x)
    valid = _finite(x)
    return _finish(valid, special.erf(_safe(valid, x, 0.0)))


def erfc(x):
    """Complementary error function, accurate in the small upper tail."""
    x = _numbers("ERFC", x)
    valid = _finite(x)
    return _finish(valid, special.erfc(_safe(valid, x, 0.0)))


def probit(p):
    """Five plus the left-tail standard normal quantile."""
    p = _numbers("PROBIT", p)
    probability = np.nan_to_num(p, nan=-1.0)
    valid = (probability > 0) & (probability < 1)
    with np.errstate(all="ignore"):
        return _finish(valid, 5 + special.ndtri(_safe(valid, p, 0.5)))


# Registered with the worksheet evaluator: name -> (accepted argument counts, function).
DISTRIBUTION_FUNCTIONS = {
    "NORMDIST": (range(1, 5), normdist), "NORMINV": (range(1, 5), norminv), "NORMPDF": (range(1, 4), normpdf),
    "ZDIST": (range(1, 3), zdist), "ZINV": (range(1, 3), zinv), "ZPDF": (range(1, 2), zpdf),
    "TDIST": (range(2, 3), tdist), "TINV": (range(2, 3), tinv), "TPDF": (range(2, 3), tpdf),
    "CHIDIST": (range(2, 3), chidist), "CHIINV": (range(2, 3), chiinv), "CHISQC": (range(2, 3), chisqc),
    "FDIST": (range(3, 4), fdist), "FINV": (range(3, 4), finv), "FPDF": (range(3, 4), fpdf),
    "BINOMIAL": (range(3, 4), binomial),
    "ERF": (range(1, 2), erf), "ERFC": (range(1, 2), erfc), "PROBIT": (range(1, 2), probit),
}
