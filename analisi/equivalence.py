"""Two one-sided tests (TOST) from a difference, its standard error and its degrees of freedom.

This module holds only the statistics: it imports nothing from the application and works on three
numbers plus the equivalence zone. Data extraction, the four designs, the tables and the figure live in
``equivalence_workbench``.

Given the difference ``d``, standard error ``se``, degrees of freedom ``df``, margins ``L < 0 < U`` and ``alpha``:

* ``t_lower = (d − L) / se`` and ``p_lower = P(T ≥ t_lower)``, the upper tail of Student's t;
* ``t_upper = (d − U) / se`` and ``p_upper = P(T ≤ t_upper)``;
* ``p_tost = max(p_lower, p_upper)``; the interval is ``d ± t(1 − alpha, df) · se`` at level ``100·(1 − 2·alpha)``.

The conclusion is *Equivalent* only when both one-sided p values are strictly below ``alpha`` **and** the
interval lies strictly inside ``(L, U)``. The two rules agree except at an exact tie, where one of them can
fall on the wrong side of ``alpha`` by an ulp; requiring both keeps the boundary case "not demonstrated".
Anything that cannot be represented raises ``ValueError``: no placeholder p value is ever produced.
"""
from numbers import Real

import numpy as np
from scipy import stats

EQUIVALENT = "Equivalent"
NOT_DEMONSTRATED = "Not demonstrated"
UNAVAILABLE = "Inference unavailable"


def _number(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (Real, np.number)):
        raise TypeError(f"{name} must be a real number.")
    value = float(value)
    if not np.isfinite(value):
        raise ValueError(f"{name} must be finite.")
    return value


def check_zone(lower, upper, alpha):
    """Validate the equivalence zone and Alpha; return them as floats."""
    lower, upper, alpha = _number(lower, "Lower margin"), _number(upper, "Upper margin"), _number(alpha, "Alpha")
    if not lower < 0:
        raise ValueError("Lower margin must be below zero.")
    if not upper > 0:
        raise ValueError("Upper margin must be above zero.")
    if not 0 < alpha < 0.5:
        raise ValueError("Alpha must be greater than 0 and less than 0.5.")
    return lower, upper, alpha


def tost_from_summary(estimate, se, df, lower, upper, alpha=0.05):
    """TOST for one difference; see the module docstring for the formulas and the decision rule."""
    estimate, se, df = _number(estimate, "Difference"), _number(se, "Standard error"), _number(df, "df")
    lower, upper, alpha = check_zone(lower, upper, alpha)
    if not se > 0:
        raise ValueError("The standard error must be greater than zero.")
    if not df > 0:
        raise ValueError("The degrees of freedom must be greater than zero.")
    # Dividing first only when subtraction overflows preserves a representable
    # statistic without changing ordinary inputs' rounding.
    def statistic(margin):
        difference = estimate - margin
        return difference / se if np.isfinite(difference) else estimate / se - margin / se

    t_lower = statistic(lower)
    t_upper = statistic(upper)
    critical = float(stats.t.isf(alpha, df))
    half = critical * se
    ci_lower, ci_upper = estimate - half, estimate + half
    ci_level = 100.0 * (1.0 - 2.0 * alpha)
    p_lower = float(stats.t.sf(t_lower, df))
    p_upper = float(stats.t.cdf(t_upper, df))
    if not np.isfinite((t_lower, t_upper, critical, ci_lower, ci_upper, p_lower, p_upper)).all():
        raise ValueError("The result cannot be represented as a finite number.")
    equivalent = p_lower < alpha and p_upper < alpha and lower < ci_lower and ci_upper < upper
    return {"difference": estimate, "se": se, "df": df, "lower_margin": lower, "upper_margin": upper, "alpha": alpha,
            "ci_level": ci_level, "ci_lower": ci_lower, "ci_upper": ci_upper, "t_lower": t_lower, "p_lower": p_lower,
            "t_upper": t_upper, "p_upper": p_upper, "p_tost": max(p_lower, p_upper),
            "conclusion": EQUIVALENT if equivalent else NOT_DEMONSTRATED}
