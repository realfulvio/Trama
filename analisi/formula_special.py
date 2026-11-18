"""Vectorized special functions for worksheet formulas."""

import numpy as np


def _special(name, domain=None):
    def calculate(*values):
        from scipy import special

        args = np.broadcast_arrays(*values)
        valid = np.logical_and.reduce([np.isfinite(arg) for arg in args])
        if domain is not None:
            valid &= domain(*args)
        result = np.full(valid.shape, np.nan)
        getattr(special, name)(*args, out=result, where=valid)
        result[~np.isfinite(result)] = np.nan
        return result.item() if result.ndim == 0 else result

    return calculate


def _regular_gamma_argument(x):
    return (x > 0) | (x != np.trunc(x))


def _positive_gamma(x):
    from scipy.special import gammasgn

    return gammasgn(x) > 0


def _incomplete_gamma_domain(shape, x):
    return (shape > 0) & (x >= 0)


SPECIAL_FORMULA_FUNCTIONS = {
    "GAMMA": (1, _special("gamma", _regular_gamma_argument)),
    "GAMMALN": (1, _special("gammaln", _positive_gamma)),
    "PSI": (1, _special("psi", _regular_gamma_argument)),
    "IGAMMA": (2, _special("gammainc", _incomplete_gamma_domain)),
    "IGAMMAC": (2, _special("gammaincc", _incomplete_gamma_domain)),
    "BETA": (2, _special("beta", lambda a, b: (a > 0) & (b > 0))),
    "IBETA": (3, _special("betainc", lambda a, b, x: (a > 0) & (b > 0) & (x >= 0) & (x <= 1))),
    "BESSELJ": (2, _special("jv")),
    "BESSELY": (2, _special("yv", lambda order, x: x > 0)),
    "PERC": (1, lambda x: np.divide(x, 100)),
}
