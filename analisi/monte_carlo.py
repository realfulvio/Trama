"""Repeatable Monte Carlo studies: generate data, repeat one test per replicate and summarise its behaviour.

Three designs are available. Each replicate draws its values from its own generator,
``Generator(PCG64(SeedSequence([seed, i])))`` with the 0-based replicate index ``i``, so the first k replicates of a
study with N replicates equal a study of k replicates, whatever the block order, a cancellation or other open
studies. The global NumPy generator is never used.

Welch difference
    ``a = rng.normal(Mean A, SD A, N A)`` then ``b = rng.normal(Mean B, SD B, N B)``. Estimate and truth are B − A.
    Welch t against Null value (two-sided), Welch–Satterthwaite df and a t interval centred on the estimate. A
    replicate whose two groups are both constant has SE 0 and is Undefined.
OLS slope
    X is ``linspace(X minimum, X maximum, N)`` or, from the worksheet, the finite non-excluded values of X column in
    row order (at least three, with positive spread). ``y = Intercept + Slope·x + rng.normal(0, SD, n)``. OLS with an
    intercept, t on n − 2 df for (slope − Null value) and a t interval. SD 0 leaves no residual variance, so every
    replicate is Undefined.
Pearson 2x2
    ``rng.binomial([N A, N B], [Probability A, Probability B])`` gives the successes of the 2 × 2 table. Pearson
    chi-square without Yates correction, 1 df. Estimate and truth are the difference of proportions B − A. No
    interval or coverage is computed. A table with no successes or no failures has a zero margin and is Undefined.

Reject means p < Alpha and Covers truth uses inclusive interval limits. The summary uses the valid replicates:
rejection rate with its Monte Carlo SE ``sqrt(rate(1 − rate)/Valid)`` and Wilson interval, coverage over the
replicates with an interval, mean, bias, RMSE and linear quantiles of the estimates.

Limits: 1–10 000 replicates and at most 2 000 000 generated values per study, counted as
``Replicates × (N A + N B)`` for Welch and Pearson and ``Replicates × N`` for OLS. Means, intercept, slope and X are
limited to ±1e100 and a positive SD to 1e-100–1e100 so that sums of squares stay representable; a result outside the
floating-point range stops the study with a message on the field.
"""
from dataclasses import dataclass, field
from operator import index

import numpy as np
import pandas as pd
from scipy import stats

from . import parallel
from .processing import FieldError
from .reporting import Result, _plot

MONTE_CARLO = "Monte Carlo study"
STUDY, REPLICATES, SEED, ALPHA, LEVEL, GRAPH = (
    "Study", "Replicates", "Seed", "Alpha", "Interval level (%)", "Graph")
WELCH, OLS, PEARSON = STUDIES = ("Welch difference", "OLS slope", "Pearson 2x2")
GRAPH_NONE, GRAPH_ESTIMATES, GRAPH_P = GRAPHS = ("None", "Estimates", "P values")
N_A, N_B, MEAN_A, MEAN_B, SD_A, SD_B, NULL = "N A", "N B", "Mean A", "Mean B", "SD A", "SD B", "Null value"
X_SOURCE, X_COLUMN, N, X_MIN, X_MAX, INTERCEPT, SLOPE, SD = (
    "X source", "X column", "N", "X minimum", "X maximum", "Intercept", "Slope", "SD")
GENERATED, WORKSHEET = X_SOURCES = ("Generated", "Worksheet")
P_A, P_B = "Probability A", "Probability B"

COMMON = (STUDY, REPLICATES, SEED, ALPHA, LEVEL, GRAPH)
DESIGN_FIELDS = {
    WELCH: (N_A, N_B, MEAN_A, MEAN_B, SD_A, SD_B, NULL),
    OLS: (X_SOURCE, X_COLUMN, N, X_MIN, X_MAX, INTERCEPT, SLOPE, SD, NULL),
    PEARSON: (N_A, N_B, P_A, P_B),
}
ALL_FIELDS = tuple(dict.fromkeys(COMMON + sum(DESIGN_FIELDS.values(), ())))

# The dialog builds its controls from these defaults: tuples are choices, None is a column, int and float are entries.
OPTIONS = {
    STUDY: STUDIES, REPLICATES: 1000, SEED: 42, ALPHA: .05, LEVEL: 95., GRAPH: GRAPHS,
    X_SOURCE: X_SOURCES, X_COLUMN: None, N_A: 10, N_B: 10, N: 10,
    MEAN_A: 0., MEAN_B: 0., SD_A: 1., SD_B: 1., P_A: .5, P_B: .5,
    X_MIN: 0., X_MAX: 1., INTERCEPT: 0., SLOPE: 1., SD: 1., NULL: 0.,
}
DEFAULTS = {name: (value[0] if isinstance(value, tuple) else value) for name, value in OPTIONS.items()}

MAX_REPLICATES, MAX_SEED, BUDGET = 10_000, 2**64 - 1, 2_000_000
MAX_N = BUDGET
MAGNITUDE, SD_FLOOR = 1e100, 1e-100
BLOCK_VALUES, MAX_BLOCK = 50_000, 500
SEQUENCE = "PCG64 v1: Generator(PCG64(SeedSequence([seed, i]))), i = replicate − 1"

REPLICATE_SHEET, SUMMARY_SHEET, SETTINGS_SHEET = "Replicates", "Summary", "Settings"
ROW_COLUMNS = ["Replicate", "Estimate", "Statistic", "p", "CI low", "CI high", "Reject", "Covers truth", "Status",
               "Reason"]
OK, UNDEFINED = "OK", "Undefined"

# Presentation keys that TramaStat keeps on every recipe when parameters change.
_KEPT_KEYS = frozenset({"Prism title", "Prism notes"})

TEST_VS_TRUTH = ("Test vs Truth: p compares each estimate with Null value (Pearson: no difference), and Reject "
                 "means p < Alpha. Coverage asks whether the interval contains the truth used to generate the data "
                 "(B − A or Slope), so a study under H0 sets the truth equal to the null value.")
REPEATABLE = ("Repeatable recalculation: the same seed gives the same replicates. Raising Replicates recalculates "
              "the study and the first replicates stay identical.")


class MonteCarloCancelled(Exception):
    """The user cancelled the calculation between two blocks."""


def visibility(study, x_source=GENERATED):
    """The fields of the chosen design; worksheet X hides N and the X limits."""
    fields = DESIGN_FIELDS.get(study, ())
    shown = {name: name in fields for name in ALL_FIELDS if name not in COMMON}
    if study == OLS:
        worksheet = x_source == WORKSHEET
        shown.update({X_COLUMN: worksheet, N: not worksheet, X_MIN: not worksheet, X_MAX: not worksheet})
    return shown


@dataclass
class Plan:
    study: str
    replicates: int
    seed: int
    alpha: float
    level: float
    graph: str
    values: dict
    truth: float
    null: float
    per_replicate: int
    x: np.ndarray | None = None
    x_column: str | None = None
    ignored_x: int = 0
    settings: list = field(default_factory=list)


def _integer(options, name, low, high):
    value = options.get(name, DEFAULTS[name])
    message = f"{name} must be a whole number from {low:,} to {high:,}."
    if isinstance(value, (bool, np.bool_)):
        raise FieldError(name, message)
    try:
        value = index(value)
    except TypeError:
        raise FieldError(name, message) from None
    if not low <= value <= high:
        raise FieldError(name, message)
    return int(value)


def _real(options, name, message=None):
    value = options.get(name, DEFAULTS[name])
    message = message or f"{name} must be a finite number."
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(name, message)
    try:
        value = float(value)
    except OverflowError:
        raise FieldError(name, message) from None
    if not np.isfinite(value):
        raise FieldError(name, message)
    return value


def _bounded(options, name):
    value = _real(options, name)
    if abs(value) > MAGNITUDE:
        raise FieldError(name, f"{name} must be between −1e100 and 1e100.")
    return value


def _sd(options, name):
    value = _real(options, name, f"{name} must be a finite number of at least 0.")
    if value < 0:
        raise FieldError(name, f"{name} must be a finite number of at least 0.")
    if value and not SD_FLOOR <= value <= MAGNITUDE:
        raise FieldError(name, f"{name} must be 0 or between 1e-100 and 1e100.")
    return value


def _choice(options, name, choices):
    value = options.get(name, DEFAULTS[name])
    if value not in choices:
        raise FieldError(name, f"{name} must be one of: {', '.join(choices)}.")
    return value


def _budget(replicates, per_replicate, field_name):
    if replicates * per_replicate > BUDGET:
        raise FieldError(field_name, f"Replicates × sample size is {replicates * per_replicate:,} generated values. "
                                     f"Keep it at most {BUDGET:,} per study.")


def _worksheet_x(frame, name):
    if not isinstance(name, str) or not name or name not in frame:
        raise FieldError(X_COLUMN, "Choose a column for X column.")
    raw = frame[name]
    if pd.api.types.is_bool_dtype(raw):
        raise FieldError(X_COLUMN, f'Column "{name}" must contain numbers.')
    present = raw.notna().to_numpy()
    if raw.dtype == object:
        blank = raw.map(lambda value: isinstance(value, str) and not value.strip()).to_numpy(dtype=bool)
        present &= ~blank
    numbers = pd.to_numeric(raw.where(present), errors="coerce")
    values = numbers.to_numpy(dtype=float, na_value=np.nan)
    if (present & np.isnan(values)).any():
        raise FieldError(X_COLUMN, f'Column "{name}" contains text. Use a column of numbers for X.')
    finite = np.isfinite(values)
    x = values[finite]
    if len(x) < 3:
        raise FieldError(X_COLUMN, f'Column "{name}" needs at least three finite, non-excluded X values.')
    if np.max(np.abs(x)) > MAGNITUDE:
        raise FieldError(X_COLUMN, f'Column "{name}" has X values outside −1e100 to 1e100.')
    if np.ptp(x) == 0:
        raise FieldError(X_COLUMN, f'Column "{name}" needs X values that differ.')
    return x, int(len(values) - len(x))


def check_options(frame, options):
    """Validate a recipe before any value is generated and return its plan. Errors name the field."""
    if not isinstance(options, dict):
        raise ValueError("Monte Carlo study options must be a mapping.")
    study = _choice(options, STUDY, STUDIES)
    allowed = set(COMMON) | set(DESIGN_FIELDS[study]) | _KEPT_KEYS
    for name in options:
        if name not in allowed:
            raise FieldError(name if name in ALL_FIELDS else STUDY,
                             f'"{name}" is not a setting of a {study} study.')
    replicates = _integer(options, REPLICATES, 1, MAX_REPLICATES)
    seed = _integer(options, SEED, 0, MAX_SEED)
    alpha = _real(options, ALPHA, "Alpha must be a finite number greater than 0 and less than 1.")
    if not 0 < alpha < 1:
        raise FieldError(ALPHA, "Alpha must be a finite number greater than 0 and less than 1.")
    level = _real(options, LEVEL, "Interval level (%) must be a finite number greater than 0 and less than 100.")
    if not 0 < level < 100:
        raise FieldError(LEVEL, "Interval level (%) must be a finite number greater than 0 and less than 100.")
    graph = _choice(options, GRAPH, GRAPHS)
    common = dict(study=study, replicates=replicates, seed=seed, alpha=alpha, level=level, graph=graph)

    if study == WELCH:
        n_a, n_b = _integer(options, N_A, 2, MAX_N), _integer(options, N_B, 2, MAX_N)
        _budget(replicates, n_a + n_b, REPLICATES)
        mean_a, mean_b = _bounded(options, MEAN_A), _bounded(options, MEAN_B)
        sd_a, sd_b = _sd(options, SD_A), _sd(options, SD_B)
        null = _bounded(options, NULL)
        for name, mean, sd in ((SD_A, mean_a, sd_a), (SD_B, mean_b, sd_b)):
            if abs(mean) + 40 * sd > MAGNITUDE:
                raise FieldError(name, f"{name} with its mean leaves the supported numeric range.")
        values = {N_A: n_a, N_B: n_b, MEAN_A: mean_a, MEAN_B: mean_b, SD_A: sd_a, SD_B: sd_b}
        plan = Plan(**common, values=values, truth=mean_b - mean_a, null=null, per_replicate=n_a + n_b)
        test = "Welch two-sample t, two-sided, Welch–Satterthwaite df"
        sizes = [(N_A, n_a), (N_B, n_b)]
        generation = [(MEAN_A, mean_a), (SD_A, sd_a), (MEAN_B, mean_b), (SD_B, sd_b)]
    elif study == OLS:
        source = _choice(options, X_SOURCE, X_SOURCES)
        if source == WORKSHEET:
            for name in (N, X_MIN, X_MAX):
                if name in options:
                    raise FieldError(name, f"{name} does not apply when X source is Worksheet.")
            x, ignored = _worksheet_x(frame, options.get(X_COLUMN))
            _budget(replicates, len(x), REPLICATES)
            column = options[X_COLUMN]
        else:
            if X_COLUMN in options:
                raise FieldError(X_COLUMN, "X column applies only when X source is Worksheet.")
            n = _integer(options, N, 3, MAX_N)
            _budget(replicates, n, REPLICATES)
            x_min, x_max = _bounded(options, X_MIN), _bounded(options, X_MAX)
            if not x_max > x_min:
                raise FieldError(X_MAX, "X maximum must exceed X minimum.")
            x = np.linspace(x_min, x_max, n)
            if np.ptp(x) == 0 or not np.isfinite(x).all():
                raise FieldError(X_MAX, "X minimum and X maximum must give X values that differ.")
            ignored, column = 0, None
        intercept, slope = _bounded(options, INTERCEPT), _bounded(options, SLOPE)
        sd, null = _sd(options, SD), _bounded(options, NULL)
        if abs(intercept) + abs(slope) * float(np.max(np.abs(x))) + 40 * sd > MAGNITUDE:
            raise FieldError(SLOPE, "Intercept, Slope, SD and X leave the supported numeric range.")
        values = {X_SOURCE: source, INTERCEPT: intercept, SLOPE: slope, SD: sd}
        plan = Plan(**common, values=values, truth=slope, null=null, per_replicate=len(x), x=x,
                    x_column=column, ignored_x=ignored)
        test = "OLS slope with intercept, t on n − 2 df, two-sided"
        sizes = [("N", len(x))]
        generation = [(X_SOURCE, source)]
        if source == WORKSHEET:
            generation += [(X_COLUMN, column), ("X values ignored", ignored)]
        else:
            generation += [(X_MIN, float(x[0])), (X_MAX, float(x[-1]))]
        generation += [(INTERCEPT, intercept), (SLOPE, slope), (SD, sd)]
    else:
        n_a, n_b = _integer(options, N_A, 1, MAX_N), _integer(options, N_B, 1, MAX_N)
        _budget(replicates, n_a + n_b, REPLICATES)
        message = "{} must be a number from 0 to 1."
        p_a, p_b = (_real(options, name, message.format(name)) for name in (P_A, P_B))
        for name, value in ((P_A, p_a), (P_B, p_b)):
            if not 0 <= value <= 1:
                raise FieldError(name, message.format(name))
        values = {N_A: n_a, N_B: n_b, P_A: p_a, P_B: p_b}
        plan = Plan(**common, values=values, truth=p_b - p_a, null=0., per_replicate=n_a + n_b)
        test = "Pearson chi-square on the 2 × 2 table, no Yates correction, 1 df"
        sizes = [(N_A, n_a), (N_B, n_b)]
        generation = [(P_A, p_a), (P_B, p_b)]

    plan.settings = [
        (STUDY, study), ("Test", test), (REPLICATES, replicates), (SEED, str(seed)), ("Random sequence", SEQUENCE),
        (ALPHA, alpha), (LEVEL, level if study != PEARSON else "Not used (no interval)"),
        ("Truth", plan.truth), *([(NULL, plan.null)] if study != PEARSON else []),
        *[(f"Effective {name}" if name != "N" else "Effective N", size) for name, size in sizes],
        *generation, (GRAPH, graph),
    ]
    return plan


def _rng(seed, replicate):
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, replicate])))


def _t_quantile(level, df):
    return stats.t.ppf((1 + level / 100) / 2, df)


def _welch_block(plan, start, stop):
    v = plan.values
    n_a, n_b = v[N_A], v[N_B]
    a, b = np.empty((stop - start, n_a)), np.empty((stop - start, n_b))
    for row, replicate in enumerate(range(start, stop)):
        rng = _rng(plan.seed, replicate)
        a[row] = rng.normal(v[MEAN_A], v[SD_A], n_a)
        b[row] = rng.normal(v[MEAN_B], v[SD_B], n_b)
    # A constant group has variance exactly 0, even when its mean is rounded.
    var_a = np.where(np.ptp(a, axis=1) == 0, 0., a.var(axis=1, ddof=1)) / n_a
    var_b = np.where(np.ptp(b, axis=1) == 0, 0., b.var(axis=1, ddof=1)) / n_b
    total = var_a + var_b
    defined = total > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        se = np.sqrt(total)
        estimate = b.mean(axis=1) - a.mean(axis=1)
        statistic = (estimate - plan.null) / se
        share = var_a / total
        df = 1 / (share ** 2 / (n_a - 1) + (1 - share) ** 2 / (n_b - 1))
        p = 2 * stats.t.sf(np.abs(statistic), df)
        half = _t_quantile(plan.level, df) * se
    reason = "Both groups are constant, so the standard error is 0."
    return _block(plan, defined, reason, estimate, statistic, p, estimate - half, estimate + half,
                  (statistic, df, half), SD_A)


def _ols_block(plan, start, stop):
    v, x = plan.values, plan.x
    n = len(x)
    noise = np.empty((stop - start, n))
    for row, replicate in enumerate(range(start, stop)):
        noise[row] = _rng(plan.seed, replicate).normal(0, v[SD], n)
    y = v[INTERCEPT] + v[SLOPE] * x + noise
    centred = x - x.mean()
    sxx = centred @ centred
    slope = (y - y.mean(axis=1, keepdims=True)) @ centred / sxx
    residual = y - y.mean(axis=1, keepdims=True) - slope[:, None] * centred
    ssr = np.einsum("ij,ij->i", residual, residual)
    # SD 0 means the data lie on the line, whatever rounding leaves in the residuals.
    defined = np.full(len(slope), v[SD] > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        se = np.sqrt(ssr / (n - 2) / sxx)
        defined &= se > 0
        statistic = (slope - plan.null) / se
        p = 2 * stats.t.sf(np.abs(statistic), n - 2)
        half = _t_quantile(plan.level, n - 2) * se
    reason = "The residual variance is 0, so the slope standard error is 0."
    return _block(plan, defined, reason, slope, statistic, p, slope - half, slope + half, (statistic, half), SD)


def _pearson_block(plan, start, stop):
    v = plan.values
    n = np.array([v[N_A], v[N_B]])
    successes = np.empty((stop - start, 2), dtype=np.int64)
    for row, replicate in enumerate(range(start, stop)):
        successes[row] = _rng(plan.seed, replicate).binomial(n, [v[P_A], v[P_B]])
    s_a, s_b = successes[:, 0].astype(float), successes[:, 1].astype(float)
    n_a, n_b = float(n[0]), float(n[1])
    total = n_a + n_b
    hits = s_a + s_b
    misses = total - hits
    defined = (hits > 0) & (misses > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        statistic = total * (s_a * (n_b - s_b) - s_b * (n_a - s_a)) ** 2 / (n_a * n_b * hits * misses)
        p = stats.chi2.sf(statistic, 1)
    estimate = s_b / n_b - s_a / n_a
    reasons = np.where(hits == 0, "No successes in either group: the success margin of the 2 × 2 table is 0.",
                       "No failures in either group: the failure margin of the 2 × 2 table is 0.")
    empty = np.full(len(estimate), np.nan)
    return _block(plan, defined, reasons, estimate, statistic, p, empty, empty, (statistic,), None)


def _block(plan, defined, reason, estimate, statistic, p, low, high, checks, field_name):
    values = [estimate, statistic, p, *checks]
    if plan.study != PEARSON:
        values += [low, high]
    if not all(np.isfinite(column[defined]).all() for column in values):
        raise FieldError(field_name or STUDY, "The simulated values leave the supported numeric range. "
                                              "Use smaller means, SDs or X values.")
    reasons = np.broadcast_to(np.asarray(reason, dtype=object), defined.shape)
    return {
        "Estimate": np.where(defined, estimate, np.nan), "Statistic": np.where(defined, statistic, np.nan),
        "p": np.where(defined, p, np.nan), "CI low": np.where(defined, low, np.nan),
        "CI high": np.where(defined, high, np.nan), "defined": defined,
        "Reason": np.where(defined, "", reasons).astype(object),
    }


_BLOCKS = {WELCH: _welch_block, OLS: _ols_block, PEARSON: _pearson_block}


def block_size(plan):
    """Replicates per block: enough to vectorise the tests, few enough to keep cancellation responsive."""
    return int(max(1, min(MAX_BLOCK, BLOCK_VALUES // plan.per_replicate)))


def blocks(plan):
    size = block_size(plan)
    return [(start, min(start + size, plan.replicates)) for start in range(0, plan.replicates, size)]


def simulate_block(plan, start, stop):
    """Test replicates start..stop−1 (0-based). Each one depends only on the seed and its own index."""
    if not 0 <= start < stop <= plan.replicates:
        raise ValueError("Replicate block is outside the study.")
    return _BLOCKS[plan.study](plan, start, stop)


def _numbers(values):
    """Float column, or object column with None for the empty cells of Undefined rows and missing intervals."""
    values = np.asarray(values, dtype=float)
    if not np.isnan(values).any():
        return values
    return pd.Series([None if np.isnan(value) else float(value) for value in values], dtype=object)


def _flags(values, defined):
    return pd.Series([bool(flag) if ok else None for flag, ok in zip(values, defined, strict=True)], dtype=object)


def replicate_table(plan, parts):
    """Assemble block results, which must cover the study in order, into the Replicates sheet.

    Empty cells hold None; Reject and Covers truth are True, False or None.
    """
    merged = {key: np.concatenate([part[key] for part in parts]) for key in parts[0]}
    defined = merged["defined"]
    reject = _flags(merged["p"] < plan.alpha, defined)
    if plan.study == PEARSON:
        covers = _flags(defined, np.zeros(len(defined), dtype=bool))
    else:
        with np.errstate(invalid="ignore"):
            inside = (merged["CI low"] <= plan.truth) & (plan.truth <= merged["CI high"])
        covers = _flags(inside, defined)
    return pd.DataFrame({
        "Replicate": np.arange(1, len(defined) + 1, dtype=np.int64),
        **{name: _numbers(merged[name]) for name in ("Estimate", "Statistic", "p", "CI low", "CI high")},
        "Reject": reject, "Covers truth": covers,
        "Status": pd.Series(np.where(defined, OK, UNDEFINED), dtype=object),
        "Reason": pd.Series(merged["Reason"], dtype=object),
    }, columns=ROW_COLUMNS)


def _wilson(successes, n, level):
    if n == 0:
        return np.nan, np.nan
    z = stats.norm.ppf((1 + level / 100) / 2)
    rate = successes / n
    centre = (successes + z * z / 2) / (n + z * z)
    half = z / (n + z * z) * np.sqrt(n * rate * (1 - rate) + z * z / 4)
    return float(max(0., centre - half)), float(min(1., centre + half))


def summary_table(plan, rows):
    valid = rows[rows["Status"] == OK]
    count = len(valid)
    rejected = int(sum(bool(flag) for flag in valid["Reject"]))
    coverage = [bool(flag) for flag in valid["Covers truth"] if flag is not None]
    covered = int(sum(coverage))
    estimates = valid["Estimate"].to_numpy(dtype=float)
    rate = rejected / count if count else np.nan
    cover_rate = covered / len(coverage) if len(coverage) else np.nan
    r_low, r_high = _wilson(rejected, count, plan.level)
    c_low, c_high = _wilson(covered, len(coverage), plan.level)
    mean = float(estimates.mean()) if count else np.nan
    quantiles = np.percentile(estimates, [2.5, 50, 97.5], method="linear") if count else [np.nan] * 3
    return pd.DataFrame([{
        "Requested": int(len(rows)), "Valid": int(count), "Undefined": int(len(rows) - count),
        "Rejected": rejected, "Rejection rate": rate,
        "Monte Carlo SE": float(np.sqrt(rate * (1 - rate) / count)) if count else np.nan,
        "Rejection Wilson low": r_low, "Rejection Wilson high": r_high,
        "Coverage N": int(len(coverage)), "Covered": covered, "Coverage rate": cover_rate,
        "Coverage Wilson low": c_low, "Coverage Wilson high": c_high, "Truth": plan.truth,
        "Mean estimate": mean, "Bias": mean - plan.truth if count else np.nan,
        "RMSE": float(np.sqrt(np.mean((estimates - plan.truth) ** 2))) if count else np.nan,
        "Estimate 2.5%": float(quantiles[0]), "Estimate 50%": float(quantiles[1]),
        "Estimate 97.5%": float(quantiles[2]),
    }])


def settings_table(plan):
    return pd.DataFrame({"Setting": [name for name, _ in plan.settings],
                         "Value": pd.Series([value for _, value in plan.settings], dtype=object)})


def study_figure(plan, rows):
    """Histogram of the valid estimates with the truth, or of the valid p values with Alpha."""
    valid = rows[rows["Status"] == OK]
    if plan.graph == GRAPH_ESTIMATES:
        figure, axes = _plot(f"Monte Carlo study · {plan.study} estimates", "Estimate", "Replicates")
        values = valid["Estimate"].to_numpy(dtype=float)
    else:
        figure, axes = _plot(f"Monte Carlo study · {plan.study} P values", "P value", "Replicates")
        values = valid["p"].to_numpy(dtype=float)
    if not len(values):
        axes.text(.5, .5, "No valid replicates to plot.\nEvery replicate is Undefined: see Reason in Replicates.",
                  ha="center", va="center", transform=axes.transAxes, color="#486075")
        axes.set(xticks=[], yticks=[])
        return figure
    if plan.graph == GRAPH_ESTIMATES:
        axes.hist(values, bins="auto" if np.ptp(values) > 0 else 1, color="#7aa6c2", edgecolor="#2d5c7a")
        axes.axvline(plan.truth, color="#b0413e", linestyle="--", linewidth=1.6, label=f"Truth = {plan.truth:.4g}")
    else:
        axes.hist(values, bins=20, range=(0, 1), color="#7aa6c2", edgecolor="#2d5c7a")
        axes.axvline(plan.alpha, color="#b0413e", linestyle="--", linewidth=1.6, label=f"Alpha = {plan.alpha:.4g}")
        axes.set_xlim(0, 1)
    axes.legend(frameon=False)
    return figure


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise MonteCarloCancelled("Monte Carlo study cancelled.")


def _simulate_task(item, cancel):
    plan, schedule = item
    parts = []
    for start, stop in schedule:
        _check_cancel(cancel)
        parts.append(simulate_block(plan, start, stop))
    return parts


def monte_carlo(frame, options, *, progress=None, cancel=None):
    """Run a study with the same per-replicate stream regardless of process count."""
    plan = check_options(frame, options)
    schedule = blocks(plan)
    _check_cancel(cancel)
    # Avoid paying the worker start-up cost for short simulations.
    processes = parallel.warm_process_count()
    if plan.replicates >= 4096 and processes > 1:
        chunk = (len(schedule) + 2 * processes - 1) // (2 * processes)
        jobs = [(plan, schedule[start:start + chunk]) for start in range(0, len(schedule), chunk)]
        capacity = block_size(plan) * chunk

        def report(done, total):
            if progress is not None and (cancel is None or not cancel.is_set()):
                # A conservative count when the shorter last task finishes first.
                progress(plan.replicates - (total - done) * capacity, plan.replicates)

        batches = parallel.run_tasks(_simulate_task, jobs, cancel=cancel, with_cancel=True, progress=report)
        parts = [part for batch in batches for part in batch]
    else:
        parts = []
        for start, stop in schedule:
            _check_cancel(cancel)
            parts.append(simulate_block(plan, start, stop))
            if progress is not None:
                progress(stop, plan.replicates)
    _check_cancel(cancel)
    rows = replicate_table(plan, parts)
    figure = None if plan.graph == GRAPH_NONE else study_figure(plan, rows)
    return Result({REPLICATE_SHEET: rows, SUMMARY_SHEET: summary_table(plan, rows),
                   SETTINGS_SHEET: settings_table(plan)}, figure)
