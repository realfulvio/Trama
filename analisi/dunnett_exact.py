"""Dunnett probabilities by deterministic quadrature when the contrasts share one control (0.109.x).

Comparisons of several groups with one control have correlations rho_ij = s_i s_j a_i a_j (a one-factor
structure, a_i = sqrt(n_i / (n_i + n_control)) for unpooled sample sizes). Then
P(max |T_i| < c) = int f_nu(s) int phi(z) prod_i [Phi((c s + a_i z)/sqrt(1-a_i²)) - Phi((-c s + a_i z)/sqrt(1-a_i²))] dz ds
with f_nu the density of sqrt(chi²_nu / nu) (Dunnett 1955). The inner integral uses Gauss–Hermite
nodes, the outer one adaptive quadrature, so the result is reproducible and accurate to about 1e-11,
where the quasi-Monte Carlo multivariate t integration gives about three digits.
"""
from math import inf, lgamma, log, sqrt

import numpy as np
from scipy import integrate, special

_NODES, _WEIGHTS = np.polynomial.hermite_e.hermegauss(160)
_WEIGHTS = _WEIGHTS / sqrt(2 * np.pi)
MAX_LOADING = 0.97     # beyond this the inner integrand is too sharp for the fixed nodes


def one_factor_loadings(correlation, tolerance=1e-10):
    """Return |a| when the correlation matrix is one-factor (off-diagonal s_i s_j a_i a_j), else None."""
    correlation = np.asarray(correlation, dtype=float)
    count = len(correlation)
    if count < 3:
        return None
    loadings = np.empty(count)
    for i in range(count):
        j, k = [m for m in range(count) if m != i][:2]
        if correlation[j, k] == 0:
            return None
        value = correlation[i, j] * correlation[i, k] / correlation[j, k]
        if not 0 < value < MAX_LOADING ** 2:
            return None
        loadings[i] = sqrt(value)
    signs = np.sign(correlation[0])
    signs[0] = 1
    if np.any(signs == 0):
        return None
    model = np.outer(signs * loadings, signs * loadings)
    np.fill_diagonal(model, 1)
    if not np.allclose(model, correlation, rtol=0, atol=tolerance):
        return None
    return loadings


def _inside(c, loadings, scale):
    """P(max |T_i| < c) given the chi scale s, by Gauss–Hermite over the common normal factor."""
    root = np.sqrt(1 - loadings ** 2)
    shift = loadings[None, :] * _NODES[:, None]
    upper = (c * scale + shift) / root
    lower = (-c * scale + shift) / root
    return float(_WEIGHTS @ np.prod(special.ndtr(upper) - special.ndtr(lower), axis=1))


def tail(c, loadings, df):
    """P(max |T_i| >= c) for the one-factor correlation and df residual degrees of freedom."""
    if c <= 0:
        return 1.
    if not np.isfinite(df) or df > 1e7:
        return max(0., 1 - _inside(c, loadings, 1.))
    log_norm = 0.5 * df * log(df) - ((0.5 * df - 1) * log(2) + lgamma(0.5 * df))

    def integrand(s):
        if s <= 0:
            return 0.
        density = np.exp(log_norm + (df - 1) * log(s) - 0.5 * df * s * s)
        return density * (1 - _inside(c, loadings, s))

    upper = 1 + 40 / sqrt(df) + 10
    value = integrate.quad(integrand, 0, 1, epsabs=1e-15, epsrel=1e-12, limit=400)[0]
    value += integrate.quad(integrand, 1, upper, epsabs=1e-15, epsrel=1e-12, limit=400)[0]
    return min(1., max(0., value))
