"""Probability, quantile and density functions for calculated columns."""

import numpy as np


def _finite(value):
    return np.where(np.isfinite(value), value, np.nan)


def _finite_result(function):
    def calculate(*values):
        result = _finite(function(*values))
        return result.item() if result.ndim == 0 else result

    return calculate


def _tail_name(tail):
    if isinstance(tail, str) and tail.lower() in ("left", "right", "two"):
        return tail.lower()
    raise ValueError('Choose "left", "right" or "two" for the distribution tail.')


def _normal_scale(sd):
    return np.where(np.isfinite(sd) & (sd > 0), sd, np.nan)


def _standard_normal(x, mean, sd):
    x, mean = _finite(x), _finite(mean)
    distance = x - mean
    # Opposite large finite values can overflow the subtraction before scaling.
    return np.where(np.isfinite(distance), distance / sd, x / sd - mean / sd)


def _normal_dist(x, mean=0., sd=1., tail="left"):
    from scipy.special import ndtr

    tail = _tail_name(tail)
    z = _standard_normal(x, mean, _normal_scale(sd))
    if tail == "two":
        return 2 * ndtr(-np.abs(z))
    return ndtr(z if tail == "left" else -z)


def _normal_inv(p, mean=0., sd=1., tail="left"):
    from scipy.special import ndtri, ndtri_exp

    tail = _tail_name(tail)
    p = _finite(p)
    if tail == "two":
        z = np.where(p <= 1, -ndtri_exp(np.log(p) - np.log(2.)), np.nan)
    else:
        z = ndtri(p) if tail == "left" else -ndtri(p)
    return _finite(mean) + _normal_scale(sd) * z


def _normal_pdf(x, mean=0., sd=1.):
    scale = _normal_scale(sd)
    z = _standard_normal(x, mean, scale)
    return np.exp(-.5 * z * z) / np.sqrt(2 * np.pi) / scale


def _distribution(name, operation):
    def calculate(*values):
        from scipy import stats

        return getattr(getattr(stats, name), operation)(*map(_finite, values))

    return calculate


def _t_inv(p, df):
    from scipy.stats import t

    p, df = _finite(p), _finite(df)
    result = t.isf(p / 2, df)
    return np.where((p == 1) & (df > 0), 0., np.where(p <= 1, result, np.nan))


def _f_inv(p, numerator_df, denominator_df):
    from scipy.stats import f

    # The reciprocal exchanges the numerator and denominator degrees of freedom.
    # Inverting the lower tail of that distribution avoids subtracting a tiny p from 1.
    return 1 / f.ppf(_finite(p), _finite(denominator_df), _finite(numerator_df))


def _count(value):
    number = _finite(value)
    return np.where((number >= 0) & (number == np.floor(number)), number, np.nan)


def _binomial(k, n, p):
    from scipy.stats import binom

    return binom.sf(_count(k) - 1, _count(n), _finite(p))


DISTRIBUTION_FORMULA_FUNCTIONS = {
    name: (arity, _finite_result(function))
    for name, arity, function in (
        ("NORMDIST", range(1, 5), _normal_dist),
        ("NORMINV", range(1, 5), _normal_inv),
        ("NORMPDF", range(1, 4), _normal_pdf),
        ("ZDIST", range(1, 3), lambda z, tail="left": _normal_dist(z, tail=tail)),
        ("ZINV", range(1, 3), lambda p, tail="left": _normal_inv(p, tail=tail)),
        ("ZPDF", 1, _normal_pdf),
        ("TDIST", 2, _distribution("t", "sf")),
        ("TINV", 2, _t_inv),
        ("TPDF", 2, _distribution("t", "pdf")),
        ("CHIDIST", 2, _distribution("chi2", "sf")),
        ("CHISQC", 2, _distribution("chi2", "cdf")),
        ("CHIINV", 2, _distribution("chi2", "isf")),
        ("FDIST", 3, _distribution("f", "sf")),
        ("FINV", 3, _f_inv),
        ("FPDF", 3, _distribution("f", "pdf")),
        ("BINOMIAL", 3, _binomial),
        ("PROBIT", 1, lambda p: 5 + _normal_inv(p)),
    )
}
