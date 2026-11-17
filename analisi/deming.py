"""Jackknife t intervals for Deming regression.

The published slope and intercept are always the full-sample fit from
``exploration.deming`` (Y / X error variance). Leave-one-out coefficients are
not a second estimator of that fit. They update the centered moments in O(n),

Sxx_(-i) = Sxx - (n/(n-1)) * (x_i - mean x)^2,

and the same subtraction for Syy and Sxy. The leave-one-out mean is
mean - (value - mean)/(n-1). Each omitted fit then uses the same slope
algebra as ``exploration.deming``. Direct ``deming`` calls are the test
oracle on small samples, not this production path. The standard error is

sqrt((n-1)/n * sum (theta_i - mean of the leave-one-out values)^2).

The interval is a two-sided Student t interval on n-1 degrees of freedom,
centered on the full-sample coefficient. It is not a prediction interval.

Intervals need at least four complete pairs so every omitted fit still has
three. The full-sample fit is kept and the interval is marked unavailable
when a leave-one-out fit is degenerate, or when the number of complete pairs
exceeds ``JACKKNIFE_LIMIT`` (100_000).

An identity line uses one shared domain: the union of observed X and observed
Y. Both axes are limited to that interval, and both the identity segment and
the fitted line are drawn across it, so Y = X spans the cloud instead of only
the observed X range. A steep fit may leave that square; the axis limits stay
on the union of the observations.
"""
import numpy as np
import pandas as pd
from scipy import stats

from . import exploration

JACKKNIFE_LIMIT = 100_000
RESIDUAL_COLUMN = "Vertical residual (Y \u2212 fitted)"
PAIR_COLUMNS = ("Source row", "X", "Y", "Fitted Y", RESIDUAL_COLUMN)
_INTERVALS = ("None", "Jackknife (t)")
_UNAVAILABLE = "Interval unavailable"


def identity_limits(x_values, y_values):
    """Return the shared [low, high] domain for an identity overlay.

    The domain is the union of observed X and observed Y. Draw Y = X and the
    fitted line across it, and show that same interval on both axes.
    """
    observed = np.concatenate((np.asarray(x_values, dtype=float).ravel(),
                               np.asarray(y_values, dtype=float).ravel()))
    return float(np.min(observed)), float(np.max(observed))


def leave_one_out_coefficients(x_values, y_values, error_ratio):
    """Leave-one-out slopes and intercepts, or None if any omitted fit is degenerate."""
    xx = np.asarray(x_values, dtype=float)
    yy = np.asarray(y_values, dtype=float)
    if xx.ndim != 1 or xx.shape != yy.shape or xx.size < 2:
        raise ValueError("Leave-one-out Deming expects paired X and Y values.")
    n = xx.size
    mean_x, mean_y = xx.mean(), yy.mean()
    dx, dy = xx - mean_x, yy - mean_y
    sxx, syy, sxy = dx @ dx, dy @ dy, dx @ dy
    scale = n / (n - 1)
    sxx_i = sxx - scale * dx * dx
    syy_i = syy - scale * dy * dy
    sxy_i = sxy - scale * dx * dy
    varying = (sxx_i > 0) & (syy_i > 0)
    tolerance = np.finfo(float).eps * np.sqrt(np.where(varying, sxx_i * syy_i, 0))
    if np.any(~varying | (np.abs(sxy_i) <= tolerance)):
        return None
    diff = syy_i - error_ratio * sxx_i
    root = np.hypot(diff, 2 * np.sqrt(error_ratio) * sxy_i)
    slopes = np.empty(n)
    # Same slope branches as exploration.deming, including the diff >= 0 split.
    positive = diff >= 0
    with np.errstate(divide="ignore", invalid="ignore"):
        slopes[positive] = (diff[positive] + root[positive]) / (2 * sxy_i[positive])
        slopes[~positive] = 2 * error_ratio * sxy_i[~positive] / (root[~positive] - diff[~positive])
    means_x = mean_x - dx / (n - 1)
    means_y = mean_y - dy / (n - 1)
    intercepts = means_y - slopes * means_x
    if not (np.isfinite(slopes).all() and np.isfinite(intercepts).all()):
        return None
    return slopes, intercepts


def _jackknife_se(values):
    centered = np.asarray(values, dtype=float)
    centered = centered - centered.mean()
    n = centered.size
    return np.sqrt((n - 1) / n * centered @ centered)


def _unavailable(report, status):
    return {**report, "Interval": "Jackknife (t)", "Interval status": f"{_UNAVAILABLE}: {status}"}


def _level(level):
    try:
        level = float(level)
    except (TypeError, ValueError):
        level = np.nan
    if not np.isfinite(level) or not 0 < level < 100:
        raise ValueError("Confidence level (%) must be finite and strictly between 0 and 100.")
    return level


def jackknife_deming(frame, x, y, error_ratio=1.0, *, intervals="None", level=95.0):
    """Full-sample Deming fit, optional jackknife t intervals, and pair residuals.

    ``intervals`` is ``"None"`` or ``"Jackknife (t)"``. With intervals off, the
    report is exactly the dictionary ``exploration.deming`` returns. ``pairs``
    always lists complete pairs in source order.
    """
    if intervals not in _INTERVALS:
        raise ValueError('Parameter intervals must be "None" or "Jackknife (t)".')
    report, points = exploration.deming(frame, x, y, error_ratio)
    xx = np.array(points[x].to_numpy(dtype=float), copy=True)
    yy = np.array(points[y].to_numpy(dtype=float), copy=True)
    fitted = report["Intercept"] + report["Slope"] * xx
    pairs = pd.DataFrame({
        "Source row": np.array(points.index, copy=True),
        "X": xx,
        "Y": yy,
        "Fitted Y": fitted,
        RESIDUAL_COLUMN: yy - fitted,
    })
    if intervals == "None":
        return report, points, pairs
    level = _level(level)
    n = len(points)
    if n > JACKKNIFE_LIMIT:
        return _unavailable(report, "the jackknife work limit was exceeded."), points, pairs
    if n < 4:
        return _unavailable(report, "at least 4 complete pairs are required."), points, pairs
    replicates = leave_one_out_coefficients(xx, yy, error_ratio)
    if replicates is None:
        return _unavailable(report, "a leave-one-out fit is degenerate."), points, pairs
    slopes, intercepts = replicates
    critical = stats.t.isf((100 - level) / 200, n - 1)
    enriched = {**report, "Interval": "Jackknife (t)", "Confidence level (%)": level, "df": n - 1}
    for name, estimate, replicates_ in (("Slope", report["Slope"], slopes),
                                        ("Intercept", report["Intercept"], intercepts)):
        standard_error = _jackknife_se(replicates_)
        half = critical * standard_error
        enriched[f"{name} SE"] = standard_error
        enriched[f"{name} CI low"] = estimate - half
        enriched[f"{name} CI high"] = estimate + half
    return enriched, points, pairs
