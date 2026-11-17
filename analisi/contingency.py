"""Association tests for observations or entered contingency counts."""
from decimal import Decimal, InvalidOperation
from math import exp, expm1, hypot, isfinite, log, log1p

import numpy as np
import pandas as pd
from scipy import optimize, stats
from scipy.stats.contingency import odds_ratio, relative_risk

from .baptista_pike import MAX_TABLES as MAX_BAPTISTA_PIKE_TABLES, baptista_pike
from .data import _worksheet_roles, decimal_comma
from .fisher_exact import FisherWorkLimit, fisher_exact_rxc
from .processing import FieldError, INTERVALS, WILSON_BROWN, _intervals
from .reporting import Result, _report
from .stats import complete


CONTINGENCY = "Contingency table"
OBSERVATIONS, COUNT_MATRIX = "Observations", "Count matrix"
AUTO, PEARSON, YATES = "Automatic", "Pearson chi-square", "Yates-corrected chi-square"
FISHER, MONTE_CARLO, TREND = "Fisher exact (2 × 2)", "Fisher Monte Carlo", "Cochran–Armitage trend"
FISHER_RXC = "Fisher exact (R × C)"
TESTS = (AUTO, PEARSON, FISHER, FISHER_RXC, YATES, MONTE_CARLO, TREND)
WOOLF, CONDITIONAL = "Woolf (logit)", "Conditional exact"
BAPTISTA_PIKE = "Baptista–Pike exact"
ODDS_INTERVALS = (WOOLF, CONDITIONAL, BAPTISTA_PIKE)
KATZ, KOOPMAN = "Katz", "Koopman score"
DIAGNOSTIC_INTERVALS = (INTERVALS[2], INTERVALS[1], WILSON_BROWN)
ALTERNATIVES = {"Two-sided": "two-sided", "First row odds higher": "greater", "First row odds lower": "less"}
BLANKS = ("Require counts", "Treat blanks as zero")
CONTINGENCY_OPTIONS = {
    "Input format": (OBSERVATIONS, COUNT_MATRIX), "Rows": None, "Columns": None,
    "Count columns": "Multiple", "Row titles": "Optional", "Blank cells": BLANKS,
    "Test": TESTS, "Fisher alternative": tuple(ALTERNATIVES), "Monte Carlo samples": 9999, "Seed": 42,
    "Confidence level (%)": 95., "Odds ratio interval": ODDS_INTERVALS,
    "Relative risk interval": (KATZ, KOOPMAN), "Diagnostic measures": False, "Diagnostic interval": DIAGNOSTIC_INTERVALS,
}
MAX_LEVELS = 128
MAX_TOTAL = 2**53
MAX_EXACT_TOTAL = 10_000_000


def _choice(options, field, values):
    choice = options.get(field, next(iter(values)))
    if choice not in values:
        raise FieldError(field, f"Choose a valid {field.lower()}.")
    return choice


def default_count_matrix(frame):
    """Recognize a native or imported count worksheet and leave old long tables alone."""
    roles = _worksheet_roles(frame)
    if roles and len(roles["y"]) >= 2:
        return str(frame.attrs.get("table_format", "")).casefold() == "contingency"
    if len(frame.columns) < 3 or str(frame.attrs.get("table_format", "")).casefold() != "contingency":
        return False
    return frame.columns[0].casefold() in {"row title", "row titles"}


def _from_observations(frame, options):
    rows, columns = options.get("Rows"), options.get("Columns")
    if rows not in frame or columns not in frame or rows == columns:
        raise FieldError("Rows", "Choose two distinct variables for the row and column categories.")
    data = complete(frame, [], [rows, columns])
    if any(not 2 <= data[name].nunique() <= MAX_LEVELS for name in (rows, columns)):
        raise FieldError("Rows", f"Use between 2 and {MAX_LEVELS} levels on each axis.")
    return pd.crosstab(data[rows], data[columns])


def _whole_count(value, name, *, field="Count columns"):
    try:
        if isinstance(value, str):
            value = Decimal(decimal_comma(value.strip()))
        if isinstance(value, (bool, np.bool_)) or not isfinite(value) or value < 0:
            raise ValueError
        if value > MAX_TOTAL:
            raise FieldError(field, "A count exceeds the supported exact integer range.")
        count = int(value)
        if value == count:
            return count
    except FieldError:
        raise
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        pass
    raise FieldError(field, f'"{name}" must contain whole, nonnegative counts.')


def _from_counts(frame, options):
    columns = options.get("Count columns", [])
    if (not isinstance(columns, list) or not 2 <= len(columns) <= MAX_LEVELS
            or any(not isinstance(name, str) or name not in frame for name in columns)
            or len(set(columns)) != len(columns)):
        raise FieldError("Count columns", f"Choose 2 to {MAX_LEVELS} distinct columns of counts.")
    label = options.get("Row titles")
    if label is None and frame.columns[0] not in columns:
        first = frame.columns[0]
        if first.casefold() in {"row title", "row titles"} or default_count_matrix(frame):
            label = first
    if label is not None and (label not in frame or label in columns):
        raise FieldError("Row titles", "Choose a row label column outside the selected count columns.")
    blanks = _choice(options, "Blank cells", BLANKS)
    row_labels = frame[label].astype("string").fillna("").str.strip() if label else pd.Series("", index=frame.index)
    selected = frame[columns].replace("", np.nan)
    positions = np.flatnonzero(selected.notna().any(axis=1).to_numpy() | row_labels.ne("").to_numpy())
    if not 2 <= len(positions) <= MAX_LEVELS:
        raise FieldError("Count columns", f"Use between 2 and {MAX_LEVELS} rows of counts.")
    selected = selected.iloc[positions]
    labels = [row_labels.iloc[row] or f"Row {row + 1}" for row in positions]
    if len(set(labels)) != len(labels):
        raise FieldError("Row titles", "Choose distinct row titles for the count matrix.")
    parsed, total = {}, 0
    for name in columns:
        counts = []
        for value in selected[name]:
            if pd.isna(value):
                if blanks == BLANKS[0]:
                    raise FieldError("Blank cells", f'Fill in the blank counts in "{name}", or choose to count them as zero.')
                value = 0
            count = _whole_count(value, name)
            total += count
            if total > MAX_TOTAL:
                raise FieldError("Count columns", "The total count exceeds the supported exact integer range.")
            counts.append(count)
        parsed[name] = counts
    return pd.DataFrame(parsed, index=pd.Index(labels, name=label or "Row"))


def _koopman_score(t, a, n1, c, n2):
    """Signed score at log(r) = t, without the N/(N − 1) correction."""
    if t < 0:
        return -_koopman_score(-t, c, n2, a, n1)
    r, h = exp(t), expm1(t)
    total = n1 + n2
    b, d = n1 - a, n2 - c
    # With p1 = r p2 and u = 1 − p1, the constrained likelihood gives
    # N u² + ((n1+c)(r−1) − b−d) u − b(r−1) = 0.
    # Compute both u and p1 from their stable roots, even near 0 or 1.
    linear = (n1 + c) * h - (b + d)
    root = hypot(linear, 2 * np.sqrt(total * b * h))
    u = (root - linear) / (2 * total) if linear <= 0 else 2 * b * h / (root + linear)
    p1 = min(1., 2 * r * (a + c) / (2 * total + linear + root))
    p2, v = p1 / r, (h + u) / r
    # Divide the score by r before computing its variance. The integer
    # difference preserves near-equality and expm1 preserves small offsets.
    difference = (a * n2 - c * n1) / (n1 * n2)
    numerator = (difference - h * (c / n2)) / r
    variance = (p1 * u / n1) / r / r + p2 * v / n2
    if variance <= 0:
        return 0. if numerator == 0 else np.copysign(np.inf, numerator)
    return numerator / np.sqrt(variance)


def koopman_risk_ratio(a, n1, c, n2, level):
    """Relative risk (a/n1)/(c/n2) with a Koopman asymptotic score interval.

    Both groups must be nonempty and at least one event must occur. The limit
    is 0 for no events in the numerator group and infinite for no events in
    the denominator group. All counts stay unadjusted.
    """
    a, n1, c, n2 = map(int, (a, n1, c, n2))
    if n1 <= 0 or n2 <= 0 or a + c <= 0:
        return np.nan, np.nan, np.nan
    z = stats.norm.isf((100 - level) / 200)
    limit = 300.  # log scale, far beyond any representable count ratio.
    estimate = np.inf if c == 0 else a * n2 / (n1 * c)
    centre = log(estimate) if 0 < estimate < np.inf else None
    if .5 < estimate < 2:
        centre = log1p((a * n2 - c * n1) / (n1 * c))

    def solve(sign, inner, step):
        # The score falls as r rises, so find the first |score| above z on the outer side.
        def target(t):
            return sign * (_koopman_score(t, a, n1, c, n2) - sign * z)

        start = inner
        outer = inner
        distance = 1.
        while True:
            outer = start + step * distance
            if abs(outer) > limit:
                return None
            if target(outer) > 0:
                break
            distance *= 2
        if target(inner) >= 0:
            return inner
        return optimize.brentq(target, *sorted((inner, outer)), xtol=1e-30, rtol=1e-14, maxiter=500)

    if a == 0:
        lower = 0.
    else:
        inner = centre if centre is not None else limit
        found = solve(1, inner, -1)
        lower = 0. if found is None else exp(found)
    if c == 0:
        upper = np.inf
    else:
        inner = centre if centre is not None else -limit
        found = solve(-1, inner, 1)
        upper = np.inf if found is None else exp(found)
    return estimate, lower, upper


def _effect_sizes(counts, level, method, risk_interval=KATZ):
    a, b, c, d = map(int, counts.ravel())
    n1, n2 = a + b, c + d
    p1, p2 = a / n1, c / n2
    p_lower, p_upper = _intervals(INTERVALS[2], [a, c], [n1, n2], level)
    difference = p1 - p2
    lower = difference - np.hypot(p1 - p_lower[0], p_upper[1] - p2)
    upper = difference + np.hypot(p_upper[0] - p1, p2 - p_lower[1])
    if risk_interval == KOOPMAN:
        risk_values = koopman_risk_ratio(a, n1, c, n2, level)
        risk_method = KOOPMAN
    else:
        risk = relative_risk(a, n1, c, n2)
        risk_ci = risk.confidence_interval(confidence_level=level / 100)
        risk_values, risk_method = (risk.relative_risk, risk_ci.low, risk_ci.high), KATZ
    if method == CONDITIONAL:
        odds = odds_ratio(counts, kind="conditional")
        odds_ci = odds.confidence_interval(confidence_level=level / 100)
        estimate, lo, hi = odds.statistic, odds_ci.low, odds_ci.high
    elif method == BAPTISTA_PIKE:
        estimate, lo, hi = baptista_pike(counts, level)
    else:
        cells = counts.astype(float)
        corrected = (cells == 0).any()
        if corrected:
            cells += .5
        a, b, c, d = cells.ravel()
        log_estimate = np.log(a) + np.log(d) - np.log(b) - np.log(c)
        margin = stats.norm.isf((100 - level) / 200) * np.sqrt(np.reciprocal(cells).sum())
        estimate, lo, hi = np.exp([log_estimate, log_estimate - margin, log_estimate + margin])
        if corrected:
            method += ", 0.5 added to each cell"
    return pd.DataFrame([
        ("First row event proportion", p1, p_lower[0], p_upper[0], "Wilson"),
        ("Second row event proportion", p2, p_lower[1], p_upper[1], "Wilson"),
        ("Difference in proportions", difference, lower, upper, "Newcombe–Wilson"),
        ("Relative risk", *risk_values, risk_method),
        ("Odds ratio", estimate, lo, hi, method),
    ], columns=["Effect", "Estimate", "Lower", "Upper", "Interval method"]).set_index("Effect")


def _level(options):
    try:
        level = float(options.get("Confidence level (%)", 95.))
    except (TypeError, ValueError, OverflowError):
        level = np.nan
    if not 0 < level < 100:
        raise FieldError("Confidence level (%)", "Choose a confidence level strictly between 0 and 100.")
    return level


def _check_diagnostics(counts, options):
    """Validate the diagnostic request against the table as entered, before any calculation."""
    if not options.get("Diagnostic measures", False):
        return None
    if counts.shape != (2, 2):
        raise FieldError("Diagnostic measures", "Diagnostic measures need exactly two rows (test positive, test negative) "
                         f"and two columns (condition present, condition absent). This table has {counts.shape[0]} rows "
                         f"and {counts.shape[1]} columns. Turn the option off, or reduce the data to a 2 × 2 table.")
    interval = _choice(options, "Diagnostic interval", DIAGNOSTIC_INTERVALS)
    level = _level(options)
    if interval == WILSON_BROWN and not 50 <= level < 100:
        raise FieldError("Confidence level (%)", "Wilson–Brown requires a confidence level from 50% to below 100%. "
                         "Choose another level or another Diagnostic interval.")
    return interval, level


def _check_baptista_pike(active):
    field = "Odds ratio interval"
    if active.shape != (2, 2):
        raise FieldError(field, "Baptista–Pike needs two rows and two columns with positive totals.")
    smallest_margin = min(active.sum(axis=0).min(), active.sum(axis=1).min())
    if smallest_margin >= MAX_BAPTISTA_PIKE_TABLES:
        raise FieldError(field, f"Baptista–Pike supports up to {MAX_BAPTISTA_PIKE_TABLES:,} fixed-margin tables. "
                         "Choose another interval method.")


def check_contingency_options(frame, options):
    """Cheap field validation for the dialog: builds the counts but runs no test."""
    layout = _choice(options, "Input format", (OBSERVATIONS, COUNT_MATRIX))
    counts = _from_counts(frame, options) if layout == COUNT_MATRIX else _from_observations(frame, options)
    _check_diagnostics(counts, options)
    if options.get("Odds ratio interval") == BAPTISTA_PIKE:
        _check_baptista_pike(counts.loc[counts.ne(0).any(axis=1), counts.ne(0).any(axis=0)])


MEASURES = (("Sensitivity", "TP", "TP + FN"), ("Specificity", "TN", "FP + TN"),
            ("Positive predictive value", "TP", "TP + FP"), ("Negative predictive value", "TN", "FN + TN"),
            ("Accuracy", "TP + TN", "TP + FP + FN + TN"))


def diagnostic_measures(values, level, interval):
    """Sensitivity, specificity, predictive values and accuracy of a [[TP, FP], [FN, TN]] table."""
    a, b, c, d = (int(x) for x in np.asarray(values).ravel())
    parts = ((a, a + c), (d, b + d), (a, a + b), (d, c + d), (a + d, a + b + c + d))
    numerator = np.array([k for k, _ in parts], dtype=float)
    denominator = np.array([n for _, n in parts], dtype=float)
    lower, upper = _intervals(interval, numerator, denominator, level)
    rows = []
    for (name, top, bottom), k, n, lo, hi in zip(MEASURES, numerator, denominator, lower, upper):
        if n == 0:
            rows.append((name, np.nan, int(k), 0, np.nan, np.nan, interval, f"Undefined: the denominator {bottom} is 0."))
        else:
            rows.append((name, k / n, int(k), int(n), lo, hi, interval, ""))
    return pd.DataFrame(rows, columns=["Measure", "Estimate", "Numerator", "Denominator", "Lower", "Upper",
                                       "Interval method", "Note"]).set_index("Measure")


def _diagnostic_tables(counts, level, interval):
    a, b, c, d = (int(x) for x in counts.to_numpy().ravel())
    rows, columns = (str(x) for x in counts.index), (str(x) for x in counts.columns)
    positive, negative = rows
    present, absent = columns
    orientation = {"Test positive (row)": positive, "Test negative (row)": negative,
                   "Condition present (column)": present, "Condition absent (column)": absent,
                   "TP (true positive)": f"{a}: {positive} × {present}", "FP (false positive)": f"{b}: {positive} × {absent}",
                   "FN (false negative)": f"{c}: {negative} × {present}", "TN (true negative)": f"{d}: {negative} × {absent}",
                   "Interval method": interval, "Confidence level (%)": level}
    if interval == WILSON_BROWN:
        orientation["Level constraint"] = "Wilson–Brown requires a confidence level from 50% to below 100%."
    return {"Diagnostic measures": diagnostic_measures(counts.to_numpy(), level, interval),
            "Diagnostic orientation": _report(orientation)}


def _trend(values):
    trials = values.sum(axis=1)
    totals = values.sum(axis=0)
    scores = np.arange(len(trials), dtype=float)
    centered = scores - np.average(scores, weights=trials)
    p = totals[0] / trials.sum()
    variance = p * (1 - p) * np.dot(trials, centered**2)
    return float(np.dot(centered, values[:, 0]) / np.sqrt(variance))


def _monte_carlo(values, samples, seed):
    row, column = values.sum(axis=1), values.sum(axis=0)
    rng = np.random.default_rng(seed)
    observed = stats.random_table.logpmf(values, row, column)
    tolerance = 64 * np.finfo(float).eps * max(1, abs(observed), int(row.sum()))
    extreme = 0
    for start in range(0, samples, 256):
        batch = stats.random_table.rvs(row, column, size=min(256, samples - start), random_state=rng)
        scores = stats.random_table.logpmf(batch, row, column)
        extreme += int(np.count_nonzero(scores <= observed + tolerance))
    return (extreme + 1) / (samples + 1)


def contingency(frame, options):
    layout = _choice(options, "Input format", (OBSERVATIONS, COUNT_MATRIX))
    counts = _from_counts(frame, options) if layout == COUNT_MATRIX else _from_observations(frame, options)
    diagnostic = _check_diagnostics(counts, options)
    nonzero_rows, nonzero_columns = counts.ne(0).any(axis=1), counts.ne(0).any(axis=0)
    active = counts.loc[nonzero_rows, nonzero_columns]
    if options.get("Odds ratio interval") == BAPTISTA_PIKE:
        _check_baptista_pike(active)
    if min(active.shape) < 2:
        raise FieldError("Count columns" if layout == COUNT_MATRIX else "Rows",
                         "At least two rows and columns must have positive totals.")
    values = active.to_numpy(dtype=np.int64)
    total = int(values.sum())
    result = stats.chi2_contingency(values, correction=False)
    pearson, pvalue = result.statistic, result.pvalue
    rows, columns = active.shape
    two_by_two = active.shape == (2, 2)
    method = _choice(options, "Test", TESTS)
    summary = {"Pearson χ²": pearson, "df": result.dof, "Pearson p": pvalue, "p": pvalue,
               "Minimum expected count": result.expected_freq.min()}
    if not nonzero_rows.all() or not nonzero_columns.all():
        summary["Zero-margin rows omitted"] = int((~nonzero_rows).sum())
        summary["Zero-margin columns omitted"] = int((~nonzero_columns).sum())
    summary["Primary test"] = PEARSON if method == AUTO else method
    association = np.sqrt(pearson / (total * (min(rows, columns) - 1)))
    summary["Phi" if two_by_two else "Cramér’s V"] = association

    if method in {FISHER, YATES} and not two_by_two:
        raise FieldError("Test", "This test requires two rows and two columns with positive totals.")
    if method == YATES:
        corrected = stats.chi2_contingency(values, correction=True)
        summary.update({"Yates-corrected χ²": corrected.statistic, "p": corrected.pvalue})
    if two_by_two and (method == FISHER or (method == AUTO and total <= MAX_EXACT_TOTAL)):
        if total > MAX_EXACT_TOTAL:
            raise FieldError("Test", "The total is too large for Fisher exact. Choose Pearson chi-square.")
        alternative = _choice(options, "Fisher alternative", ALTERNATIVES)
        fisher = stats.fisher_exact(values, alternative=ALTERNATIVES[alternative])
        summary.update({"Fisher exact p": fisher.pvalue, "Odds ratio": fisher.statistic,
                        "Fisher alternative": alternative})
        if method == FISHER:
            summary["p"] = fisher.pvalue
    elif two_by_two and method == AUTO:
        summary["Fisher exact"] = "Omitted above the exact-test work limit"
    if method == FISHER_RXC:
        try:
            tail, normalizer, count = fisher_exact_rxc(values)
        except FisherWorkLimit as error:
            fallback = MONTE_CARLO if total <= MAX_EXACT_TOTAL else PEARSON
            raise FieldError("Test", f"Fisher exact exceeded its table or work limit. Choose {fallback}.") from error
        exact = tail / normalizer
        summary.update({"Fisher exact p": exact or None, "p": exact or None, "Fixed-margin tables": count,
                        "Fisher alternative": "Association"})
        if exact == 0:
            summary["log(p)"] = log(tail) - log(normalizer)
            summary["Fisher note"] = "The exact probability is below the positive floating-point range."
    if method == MONTE_CARLO:
        samples, seed = options.get("Monte Carlo samples", 9999), options.get("Seed", 42)
        if (type(samples) is not int or not 999 <= samples <= 100_000
                or samples * values.size > 20_000_000 or total > MAX_EXACT_TOTAL):
            raise FieldError("Monte Carlo samples", "Use 999 to 100,000 samples within the table work limit.")
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise FieldError("Seed", "Choose an integer seed from 0 to 4,294,967,295.")
        estimate = _monte_carlo(values, samples, seed)
        summary.update({"p": estimate, "Monte Carlo samples": samples, "Seed": seed,
                        "Monte Carlo SE": np.sqrt(estimate * (1 - estimate) / (samples + 1))})
    if method == TREND:
        if columns != 2 or rows < 3:
            raise FieldError("Test", "A trend test requires two columns and at least three ordered rows.")
        z = _trend(values)
        summary.update({"Trend z": z, "Trend χ²": z**2, "Trend df": 1, "p": stats.chi2.sf(z**2, 1),
                        "Trend event": str(active.columns[0])})

    expected = pd.DataFrame(result.expected_freq, index=active.index, columns=active.columns)
    tables = {"Counts": counts, "Tests": _report(summary), "Expected counts": expected,
              "Pearson residuals": (active - expected) / np.sqrt(expected)}
    if two_by_two:
        level = _level(options)
        method = _choice(options, "Odds ratio interval", ODDS_INTERVALS)
        if method == CONDITIONAL and total > 1_000_000:
            raise FieldError("Odds ratio interval", "The total is too large for conditional exact intervals. Choose Woolf.")
        risk_interval = _choice(options, "Relative risk interval", (KATZ, KOOPMAN))
        tables["2 × 2 effects"] = _effect_sizes(values, level, method, risk_interval)
        first, second, event = str(active.index[0]), str(active.index[1]), str(active.columns[0])
        tables["Comparison order"] = _report({"First row": first, "Second row": second, "Event column": event,
                                               "Confidence level (%)": level,
                                               "Relative risk numerator row": first, "Relative risk denominator row": second,
                                               "Relative risk orientation": f"({first} events) / ({second} events), event = {event}",
                                               "Relative risk interval": risk_interval})
        if diagnostic:
            tables.update(_diagnostic_tables(active, level, diagnostic[0]))
    return Result(tables)
