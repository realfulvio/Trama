"""Pairwise Pearson and Spearman correlation, with optional R² heat maps."""
from functools import lru_cache
from itertools import combinations

from matplotlib import colormaps
from mpl_toolkits.axes_grid1 import make_axes_locatable
import numpy as np
import pandas as pd
from scipy import stats

from .processing import FieldError, _column, _number
from .reporting import Result, _plot, _report


CORRELATION_MATRIX = "Correlation matrix"
METHODS = ("Pearson", "Spearman")
ALTERNATIVES = {"Two-sided": "two-sided", "Positive": "greater", "Negative": "less"}
MISSING = ("Pairwise complete", "Listwise complete")
P_VALUES = ("Exact when feasible", "Approximate")
OPTIONS = {"Method": METHODS, "Alternative": tuple(ALTERNATIVES), "Missing values": MISSING,
           "Spearman p values": P_VALUES, "Confidence level (%)": 95., "R² heat map": True}
MAX_VARIABLES = 32
MAX_EXACT_N = 17
EXACT_WORK_BUDGET = 4_000_000


def _choice(options, field, choices):
    value = options.get(field, next(iter(choices)))
    if value not in choices:
        raise FieldError(field, f"Choose a valid {field.lower()}.")
    return value


def _rank_scores(ranks):
    scores = (2 * (ranks - ranks.min())).astype(int)
    return scores // np.gcd.reduce(scores)


def _exact_key(x, y):
    left, right = tuple(sorted(x.tolist())), tuple(sorted(y.tolist()))
    return tuple(sorted((left, right)))


@lru_cache(maxsize=128)
def _permutation_distribution(left, right):
    """Count dot products by assigning a distinct right-hand index to each left rank."""
    return _count_permutation_distribution(left, right)


def _count_permutation_distribution(left, right, check=None):
    """Uncached shared counter; bounded callers may supply a cancellation check."""
    n = len(left)
    previous = {0: (0, np.ones(1, dtype=np.int64))}
    for level, coefficient in enumerate(left, 1):
        if check is not None:
            check()
        current = {}
        for step, indices in enumerate(combinations(range(n), level)):
            if check is not None and step % 256 == 0:
                check()
            mask = sum(1 << index for index in indices)
            terms = []
            for index in indices:
                offset, counts = previous[mask ^ (1 << index)]
                terms.append((offset + coefficient * right[index], counts))
            low = min(offset for offset, _ in terms)
            high = max(offset + len(counts) for offset, counts in terms)
            counts = np.zeros(high - low, dtype=np.int64)
            for offset, term in terms:
                begin = offset - low
                counts[begin:begin + len(term)] += term
            current[mask] = (low, counts)
        previous = current
    low, counts = previous[(1 << n) - 1]
    scores = np.arange(low, low + len(counts), dtype=np.int64)
    return scores, counts


def _permutation_p(key, score, alternative):
    scores, counts = _permutation_distribution(*key)
    if alternative == "two-sided":
        # Compare absolute centered products using integers, including ties exactly.
        n = len(key[0])
        center = sum(key[0]) * sum(key[1])
        tail = np.abs(n * scores - center) >= abs(n * score - center)
    elif alternative == "greater":
        tail = scores >= score
    else:
        tail = scores <= score
    return float(counts[tail].sum() / counts.sum())


def _unit_centered(values):
    # Shift before scaling to retain the variation between very large nearby values.
    midpoint = .5 * values.min() + .5 * values.max()
    centered = values - midpoint
    centered /= np.max(np.abs(centered))
    centered -= centered.mean()
    return centered / np.linalg.norm(centered)


def _coefficient_and_p(x, y, alternative):
    r = float(np.clip(_unit_centered(x) @ _unit_centered(y), -1., 1.))
    n = len(x)
    shape = n / 2 - 1
    if alternative == "two-sided":
        p = 2 * stats.beta.cdf((1 - abs(r)) / 2, shape, shape)
    elif alternative == "greater":
        p = stats.beta.cdf((1 - r) / 2, shape, shape)
    else:
        p = stats.beta.cdf((1 + r) / 2, shape, shape)
    return r, float(p)


def _confidence_interval(coefficient, n, critical, spearman):
    minimum = 11 if spearman else 4
    if n < minimum:
        return np.nan, np.nan
    if abs(coefficient) == 1:
        return coefficient, coefficient
    # Bonett–Wright (2000) adjusts Fisher's standard error for Spearman's rho.
    variance = 1 + coefficient**2 / 2 if spearman else 1.
    delta = critical * np.sqrt(variance / (n - 3))
    center = np.arctanh(coefficient)
    return np.tanh(center - delta), np.tanh(center + delta)


def _heat_map(coefficients, names):
    figure, axes = _plot("Correlation matrix")
    cmap = colormaps["Blues"].with_extremes(bad="#e2e8ef")
    squared = coefficients**2
    image = axes.imshow(squared, cmap=cmap, vmin=0., vmax=1.)
    axes.set_xticks(range(len(names)), names, rotation=40, ha="right")
    axes.set_yticks(range(len(names)), names)
    axes._tramastat_categorical_axes = ("x", "y")
    axes.tick_params(length=0)
    divider = make_axes_locatable(axes)
    colorbar = divider.append_axes("right", size="4%", pad=.24)
    figure.colorbar(image, cax=colorbar, label="R²")
    if len(names) <= 10:
        for (row, col), value in np.ndenumerate(squared):
            label = f"{value:.2f}" if np.isfinite(value) else "—"
            axes.text(col, row, label, va="center", ha="center",
                      color="white" if value >= .55 else "#1c3345")
    return figure


def correlation_matrix(frame, options):
    names = options.get("Variables", ())
    if (not isinstance(names, (tuple, list)) or not 2 <= len(names) <= MAX_VARIABLES
            or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names)):
        raise FieldError("Variables", f"Choose 2 to {MAX_VARIABLES} distinct variables.")
    method = _choice(options, "Method", METHODS)
    spearman = method == "Spearman"
    alternative_name = _choice(options, "Alternative", ALTERNATIVES)
    alternative = ALTERNATIVES[alternative_name]
    missing = _choice(options, "Missing values", MISSING)
    p_values = _choice(options, "Spearman p values", P_VALUES) if spearman else P_VALUES[0]
    level = _number(options.get("Confidence level (%)", 95.), "Confidence level (%)")
    if not 0 < level < 100:
        raise FieldError("Confidence level (%)", "Choose a confidence level between 0 and 100.")
    critical = stats.norm.isf((100 - level) / 200)

    matrix = np.column_stack([_column(frame, name, "Variables") for name in names])
    finite = np.isfinite(matrix)
    if missing == MISSING[1]:
        complete = finite.all(axis=1)
        matrix, finite = matrix[complete], finite[complete]
    valid = finite.astype(np.int64)
    counts = valid.T @ valid
    shape = counts.shape
    r, p, lower, upper = (np.full(shape, np.nan) for _ in range(4))
    p_type = np.full(shape, "", dtype=object)
    exact_keys = set()
    remaining = EXACT_WORK_BUDGET
    for index, n in enumerate(counts.diagonal()):
        observed = matrix[finite[:, index], index]
        if n >= 3 and observed.min() != observed.max():
            r[index, index] = 1.
    for i, j in combinations(range(len(names)), 2):
        n = counts[i, j]
        if n < 3:
            continue
        x, y = matrix[finite[:, i] & finite[:, j]][:, [i, j]].T
        if x.min() == x.max() or y.min() == y.max():
            continue
        if spearman:
            x, y = stats.rankdata(x), stats.rankdata(y)
        coefficient, probability = _coefficient_and_p(x, y, alternative)
        if spearman:
            label = "Approximate"
            if p_values == P_VALUES[0] and n <= MAX_EXACT_N:
                scores_x, scores_y = _rank_scores(x), _rank_scores(y)
                key = _exact_key(scores_x, scores_y)
                cost = n * (1 << (n - 1))
                if key in exact_keys or cost <= remaining:
                    if key not in exact_keys:
                        remaining -= cost
                        exact_keys.add(key)
                    probability = _permutation_p(key, int(scores_x @ scores_y), alternative)
                    label = "Exact"
            p_type[i, j] = p_type[j, i] = label
        r[i, j] = r[j, i] = coefficient
        p[i, j] = p[j, i] = probability
        low, high = _confidence_interval(coefficient, n, critical, spearman)
        lower[i, j] = lower[j, i] = low
        upper[i, j] = upper[j, i] = high

    if not np.isfinite(p).any():
        raise FieldError("Variables", "Choose variables with at least three complete pairs and variation in both.")
    tables = {name: pd.DataFrame(values, index=names, columns=names) for name, values in (
        ("Coefficients", r), ("P values", p), ("Sample sizes", counts),
        ("Confidence limits (lower)", lower), ("Confidence limits (upper)", upper), ("R²", r**2))}
    if spearman:
        tables["P value type"] = pd.DataFrame(p_type, index=names, columns=names)
    settings = {"Method": method, "Alternative": alternative_name, "Missing values": missing,
                "Confidence level (%)": level,
                "Confidence interval": "Bonett–Wright (n ≥ 11)" if spearman else "Fisher z (n ≥ 4)"}
    if spearman:
        settings["Spearman p values"] = p_values
    tables["Settings"] = _report(settings)
    figure = _heat_map(r, names) if options.get("R² heat map", True) else None
    return Result(tables, figure)
