"""Brown–Forsythe F* and simultaneous comparisons for one-way ANOVA with unequal variances.

The group sizes, means and variances come from ``inference.one_way_anova``,
which collects the groups once for every method.
"""
from math import exp, pi, sqrt

import numpy as np
from scipy import integrate, optimize, special, stats

from .processing import FieldError

JOINT = "Welch and Brown–Forsythe"
TAMHANE = "Tamhane T2"
DUNNETT_T3 = "Dunnett T3"
DUNNETT = "Dunnett"
LEVEL = "Confidence level (%)"
DEFAULT_LEVEL = 95.0
METHOD = "Method"
POSTHOC = "Post-hoc"
FAMILY, CONTROL, PAIRS = "Comparison family", "Control group", "Selected pairs"
ALL_PAIRS, VERSUS_CONTROL = "All pairs", "Versus control"
FAMILIES = (ALL_PAIRS, VERSUS_CONTROL, PAIRS)
# Dialog labels → engine keys. Saved recipes keep the labels.
METHOD_KEYS = {"Ordinary": "ordinary", "Welch": "welch", JOINT: "welch-bf"}
UNEQUAL_METHODS = {"welch", "welch-bf"}


def confidence_level(value):
    """Return a finite confidence level strictly between 0 and 100."""
    try:
        level = float(value)
    except (TypeError, ValueError):
        level = np.nan
    if not np.isfinite(level) or not 0 < level < 100:
        raise FieldError(LEVEL, "Confidence level (%) must be finite and strictly between 0 and 100.")
    return level


def check_one_way_options(options):
    """Raise a field error for an incompatible post-hoc choice or an invalid level."""
    method, posthoc = options.get(METHOD, "Ordinary"), options.get(POSTHOC, "None")
    if posthoc in UNEQUAL_POSTHOC_KEYS:
        if METHOD_KEYS.get(method) not in UNEQUAL_METHODS:
            raise FieldError(POSTHOC, f"{posthoc} requires the Welch or {JOINT} method.")
        confidence_level(options.get(LEVEL, DEFAULT_LEVEL))
    if posthoc == "Tukey" and METHOD_KEYS.get(method) in UNEQUAL_METHODS:
        raise FieldError(POSTHOC, "Tukey assumes equal variances. Choose Games–Howell, Tamhane T2 or Dunnett T3.")
    if posthoc == "Games–Howell" and METHOD_KEYS.get(method) == "ordinary":
        raise FieldError(POSTHOC, "Games–Howell requires the Welch or Welch and Brown–Forsythe method.")
    if posthoc == DUNNETT:
        if METHOD_KEYS.get(method) != "ordinary":
            raise FieldError(POSTHOC, "Dunnett uses pooled variance and requires ordinary ANOVA.")
        confidence_level(options.get(LEVEL, DEFAULT_LEVEL))


def one_way_visibility(posthoc, family=ALL_PAIRS):
    unequal = posthoc in UNEQUAL_POSTHOC_KEYS
    dunnett = posthoc == DUNNETT
    return {LEVEL: unequal or dunnett, FAMILY: unequal, CONTROL: dunnett or (unequal and family == VERSUS_CONTROL),
            PAIRS: unequal and family == PAIRS}


def check_group_variances(labels, sizes, within_ss, response):
    """Name the first group without two observations or positive variance."""
    for label, size, ss in zip(labels, sizes, within_ss):
        if size < 2 or not ss > 0:
            problem = "has a single observation" if size < 2 else "has zero variance"
            raise FieldError("Response", f"Welch ANOVA requires at least two observations and positive variance "
                                         f"in every group. Group {label!s} {problem} in {response}.")


def brown_forsythe(sizes, means, variances):
    """Return the original Brown–Forsythe F*, df1, df2 and p for unequal variances."""
    sizes = np.asarray(sizes, dtype=float)
    total = sizes.sum()
    grand = np.average(means, weights=sizes)
    weights = (1 - sizes / total) * variances
    denominator = weights.sum()
    statistic = np.sum(sizes * np.square(means - grand)) / denominator
    df1 = len(sizes) - 1
    df2 = 1 / np.sum(np.square(weights / denominator) / (sizes - 1))
    return statistic, df1, df2, stats.f.sf(statistic, df1, df2)


def tamhane_t2(differences, se, df, level):
    """Return raw p, Šidák adjusted p and simultaneous limits for Welch pairwise t tests."""
    m = len(differences)
    raw = 2 * stats.t.sf(np.abs(differences / se), df)
    with np.errstate(divide="ignore"):
        adjusted = np.clip(-np.expm1(m * np.log1p(-raw)), 0, 1)
    alpha_pair = -np.expm1(np.log1p(-(1 - level / 100)) / m)
    half_width = stats.t.isf(alpha_pair / 2, df) * se
    return raw, adjusted, differences - half_width, differences + half_width


def _maximum_modulus_probability(t, df, comparisons, *, survival):
    """Tail of max(|Z_i|) / sqrt(chi-square(df) / df) with a shared denominator."""
    if t == 0:
        return float(survival)
    if not np.isfinite(t):
        return float(not survival)
    gamma_probability = special.gammainc if survival else special.gammaincc
    shape = df / 2
    coefficient = comparisons * sqrt(2 / pi)

    def integrand(x):
        ratio = x / t
        density = coefficient * exp(-x * x / 2) * special.erf(x / sqrt(2)) ** (comparisons - 1)
        return density * gamma_probability(shape, shape * ratio * ratio)

    # Resolve the transition near t when the denominator concentrates at large df.
    # Beyond 40 the standard-normal density underflows in double precision.
    points = [1, 4, 8, 16, 28]
    spread = 8 * t / sqrt(2 * df)
    points.extend(x for x in (t - spread, t, t + spread) if 0 < x < 40)
    probability, _ = integrate.quad(integrand, 0, 40, points=points, epsabs=1e-180, epsrel=1e-10)
    return min(1., max(0., probability))


def _maximum_modulus_critical(df, comparisons, level):
    coverage = level / 100
    upper = 2 * stats.t.isf((1 - coverage) / (2 * comparisons), df)
    survival = coverage >= .5
    target = 1 - coverage if survival else coverage
    return optimize.brentq(lambda t: _maximum_modulus_probability(t, df, comparisons, survival=survival) - target,
                           0, upper, xtol=1e-12, rtol=1e-11)


def dunnett_t3_df(df):
    """Integer degrees of freedom for the maximum modulus calculation."""
    return np.maximum(1, np.rint(df)).astype(int)


def dunnett_t3(differences, se, df, level):
    """Pairwise Welch statistics adjusted with the integer-df maximum modulus distribution."""
    df = dunnett_t3_df(df)
    comparisons = len(differences)
    if comparisons == 1:
        return tamhane_t2(differences, se, df, level)
    statistic = np.abs(differences / se)
    raw = 2 * stats.t.sf(statistic, df)
    adjusted = np.array([_maximum_modulus_probability(float(t), float(degrees), comparisons, survival=True)
                         for t, degrees in zip(statistic, df, strict=True)])
    adjusted = np.clip(adjusted, raw, np.minimum(1., comparisons * raw))
    critical = np.array([_maximum_modulus_critical(float(degrees), comparisons, level) for degrees in df])
    half_width = critical * se
    return raw, adjusted, differences - half_width, differences + half_width


UNEQUAL_POSTHOC = {"tamhane": (TAMHANE, tamhane_t2), "dunnett-t3": (DUNNETT_T3, dunnett_t3)}
UNEQUAL_POSTHOC_KEYS = {label: key for key, (label, _) in UNEQUAL_POSTHOC.items()}
