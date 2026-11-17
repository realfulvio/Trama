"""Pointwise linear mean estimates and real-line inverse confidence sets.

The inverse set is the intersection of the pointwise mean-response band with
the selected Y. It is not a prediction interval or a symmetric delta interval.
The caller supplies the already fitted OLS objects; this module never refits.
"""
import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .i18n import tr


FORWARD = "Y confidence interval at X"
INVERSE = "X confidence interval at Y"
X_VALUE, Y_VALUE = "X value", "Y value"
LEVEL = "Confidence level (%)"
SHEET = "Linear estimates"
OPTIONS = {FORWARD: False, X_VALUE: 0.0, INVERSE: False, Y_VALUE: 0.0}
LABEL_KEYS = {
    FORWARD: "analysis.linear.estimates.forward",
    INVERSE: "analysis.linear.estimates.inverse",
    X_VALUE: "analysis.linear.estimates.x",
    Y_VALUE: "analysis.linear.estimates.y",
    LEVEL: "analysis.linear.estimates.level",
}
COLUMNS = ["Direction", "Input value", "Estimate", "Component", "Lower", "Upper",
           LEVEL, "Confidence set", "Note"]


def requested(options):
    return bool(options.get(FORWARD, False) or options.get(INVERSE, False))


def check_options(options):
    """Validate only active coordinates; stale hidden values are ignored."""
    values = {}
    for flag, key in ((FORWARD, X_VALUE), (INVERSE, Y_VALUE)):
        if not options.get(flag, False):
            continue
        try:
            value = float(options.get(key, 0.0))
        except (TypeError, ValueError, OverflowError):
            value = np.nan
        if not np.isfinite(value):
            raise FieldError(key, tr("analysis.linear.estimates.finite", axis=key[0]))
        values[key] = value
    return values


def quadratic_confidence_set(a, b, c):
    """Solve a*u²+b*u+c <= 0 on the extended real line, with stable roots.

    A small nonzero leading coefficient remains nonzero: its far-away root
    can carry essential information about an unbounded inverse confidence set.
    """
    a, b, c = (np.longdouble(x) for x in (a, b, c))
    scale = max(abs(a), abs(b), abs(c))
    if scale:
        a, b, c = a/scale, b/scale, c/scale
    if a == 0:
        if b == 0:
            return ([(-np.inf, np.inf)], "All real values") if c <= 0 else ([], "Empty")
        root = -c/b
        return ([(-np.inf, root)] if b > 0 else [(root, np.inf)]), "Half-line"
    b2, ac4 = b*b, 4*a*c
    discriminant = b2 - ac4
    # Roundoff can turn an exact tangent into a tiny negative discriminant.
    # This tolerance has no absolute floor and does not classify a or b as zero.
    roundoff = 16*np.finfo(np.longdouble).eps*max(abs(b2), abs(ac4))
    if -roundoff <= discriminant < 0:
        discriminant = np.longdouble(0)
    if discriminant < 0:
        return ([(-np.inf, np.inf)], "All real values") if a < 0 else ([], "Empty")
    if discriminant == 0:
        root = -b/(2*a)
        return ([(-np.inf, np.inf)], "All real values") if a < 0 else ([(root, root)], "Bounded")
    q = -(b + np.copysign(np.sqrt(discriminant), b))/2
    with np.errstate(over="ignore", divide="ignore"):
        low, high = sorted((q/a, c/q))
    if not np.isfinite(low) or not np.isfinite(high):
        raise OverflowError("A finite confidence endpoint exceeds the numeric range.")
    if a > 0:
        return [(low, high)], "Bounded"
    return [(-np.inf, low), (high, np.inf)], "Two unbounded intervals"


def _finite_float(value, field):
    """Actual infinite confidence endpoints are handled by the caller."""
    if not np.isfinite(value) or abs(value) > np.finfo(float).max:
        raise FieldError(field, tr("analysis.linear.estimates.range"))
    return float(value)


def _product_ratio(numerators, denominators):
    """Combine exponents before evaluating a product/ratio (also on Windows)."""
    mantissa, exponent = np.longdouble(1), 0
    for value in numerators:
        part, power = np.frexp(value)
        mantissa *= part
        exponent += int(power)
    for value in denominators:
        part, power = np.frexp(value)
        mantissa /= part
        exponent -= int(power)
    with np.errstate(over="ignore", under="ignore"):
        return np.ldexp(mantissa, exponent)


def estimate_table(fit, options, level):
    values = check_options(options)
    critical = np.longdouble(stats.t.isf((100.0-level)/200.0, fit.df))
    mean_x = np.longdouble(fit.mean_x)
    mean_y = np.mean(np.asarray(fit.y, dtype=np.longdouble))
    slope = np.longdouble(fit.summary["Slope"])
    sx = np.hypot.reduce(np.asarray(fit.x, dtype=np.longdouble)-mean_x)
    # Windows longdouble is float64. A hypot norm avoids under/overflow there
    # too; squaring tiny residuals before normalising would erase uncertainty.
    error = np.hypot.reduce(np.asarray(fit.residual, dtype=np.longdouble))/np.sqrt(np.longdouble(fit.df))
    rows = []
    if X_VALUE in values:
        query = values[X_VALUE]
        offset = np.longdouble(query)-mean_x
        estimate = mean_y+slope*offset
        # Apply the residual scale before a potentially enormous X/Sx ratio.
        # On Windows that ratio may overflow even with finite final limits.
        half = np.hypot(_product_ratio((critical, error), (np.sqrt(np.longdouble(fit.n)),)),
                        _product_ratio((critical, error, offset), (sx,)))
        note = "Pointwise confidence interval for mean Y; not a prediction interval."
        if query < np.min(fit.x) or query > np.max(fit.x):
            note += " Extrapolation beyond the observed X range."
        rows.append(["Y from X", query, _finite_float(estimate, X_VALUE), 1,
                     _finite_float(estimate-half, X_VALUE), _finite_float(estimate+half, X_VALUE),
                     level, "Bounded", note])
    if Y_VALUE in values:
        query = values[Y_VALUE]
        delta = np.longdouble(query)-mean_y
        estimate = _finite_float(mean_x+delta/slope, Y_VALUE) if slope != 0 else np.nan
        # Match X units to the query using the larger of slope and slope
        # uncertainty. Otherwise distant queries can erase the leading term
        # by underflow, or a nearly horizontal fit can make the X scale huge.
        slope_scale = max(abs(slope), _product_ratio((critical, error), (sx,)))
        coordinate_scale = max(sx, abs(delta)/slope_scale) if slope_scale else sx
        response_scale = max(abs(delta), abs(slope*coordinate_scale), error)
        if response_scale:
            d, b = delta/response_scale, slope*coordinate_scale/response_scale
            noise = _product_ratio((critical, error), (response_scale,))
            slope_noise = _product_ratio((critical, error, coordinate_scale), (response_scale, sx))
        else:
            d = b = noise = slope_noise = np.longdouble(0)
        try:
            components, kind = quadratic_confidence_set(b*b-slope_noise**2, -2*d*b, d*d-noise**2/fit.n)
        except OverflowError:
            raise FieldError(Y_VALUE, tr("analysis.linear.estimates.range")) from None
        note = "Inverse pointwise mean-response confidence set; not clipped to observed X."
        if slope == 0:
            note += " No unique X estimate for a horizontal fitted line."
        elif estimate < np.min(fit.x) or estimate > np.max(fit.x):
            note += " Extrapolation beyond the observed X range."
        for number, (lower, upper) in enumerate(components, 1):
            lower = float(lower) if np.isinf(lower) else _finite_float(mean_x+lower*coordinate_scale, Y_VALUE)
            upper = float(upper) if np.isinf(upper) else _finite_float(mean_x+upper*coordinate_scale, Y_VALUE)
            rows.append(["X from Y", query, estimate, number, lower, upper, level, kind, note])
        if not components:
            rows.append(["X from Y", query, estimate, np.nan, np.nan, np.nan, level, kind,
                         note+" The confidence band does not reach the selected Y."])
    return pd.DataFrame(rows, columns=COLUMNS)
