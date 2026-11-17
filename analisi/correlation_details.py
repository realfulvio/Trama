"""Detailed correlation, correlation against a control and two independent Pearson correlations.

The numeric contract is independent of any reference product. ``Correlation`` with
``Detailed results`` omitted or false stays on the legacy path in ``workbench``.
Confidence intervals are always two-sided at the chosen level. Exact Spearman p values
permute the observed ranks, ties included. Saved recipes without an explicit budget keep the nine-pair policy.
"""
from math import isnan
from textwrap import fill

import numpy as np
import pandas as pd
from scipy import stats

from .correlation_matrix import _coefficient_and_p, _exact_key, _permutation_p, _rank_scores
from .field_error import FieldError
from .processing import _column, _number
from .reporting import Result, _plot, _report
from .spearman_exact_budget import (BUDGETS, EXTENDED, FIELD as EXACT_BUDGET, STANDARD, ExactSpearmanFamily)

CORRELATE_CONTROL = "Correlate against control"
COMPARE_INDEPENDENT = "Compare independent correlations"
CORRELATION_METHODS = frozenset({"Correlation", CORRELATE_CONTROL, COMPARE_INDEPENDENT})

ALTERNATIVES = ("Two-sided", "Positive", "Negative")
P_METHODS = ("Automatic", "Exact", "Approximate")
MISSING = ("Pairwise complete", "Listwise complete")
ADJUSTMENTS = ("None", "Holm", "Benjamini–Hochberg")
SINGLE_METHODS = ("Pearson", "Spearman", "Kendall")
CONTROL_METHODS = ("Pearson", "Spearman")
_SCIPY_ALTERNATIVE = {"Two-sided": "two-sided", "Positive": "greater", "Negative": "less"}
EXACT_LIMIT = 9
MAX_RESPONSES = 24
SINGLE_EXTRA = {
    "Detailed results": False,
    "Alternative": ALTERNATIVES,
    "Confidence level (%)": 95.0,
    "Spearman p values": P_METHODS,
    EXACT_BUDGET: BUDGETS,
}
CONTROL_OPTIONS = {
    "X": None,
    "Variables": "Multiple",
    "Method": CONTROL_METHODS,
    "Alternative": ALTERNATIVES,
    "Confidence level (%)": 95.0,
    "Spearman p values": P_METHODS,
    EXACT_BUDGET: BUDGETS,
    "Missing values": MISSING,
    "P adjustment": ADJUSTMENTS,
    "Show intervals": True,
}
INDEPENDENT_OPTIONS = {
    "X": None,
    "Y": None,
    "Group": None,
    "Alternative": ALTERNATIVES,
    "Confidence level (%)": 95.0,
    "Show intervals": True,
}
_STAT_KEYS = ("N", "Coefficient", "p", "Lower", "Upper", "R²", "P method", "CI method", "Reason")


def _choice(options, field, choices, default=None):
    value = options.get(field, choices[0] if default is None else default)
    if value not in choices:
        raise FieldError(field, f"Choose a valid {field}.")
    return value


def _level(options):
    level = _number(options.get("Confidence level (%)", 95.0), "Confidence level (%)")
    if not 0 < level < 100:
        raise FieldError("Confidence level (%)",
                         "Confidence level (%) must be a finite number strictly between 0 and 100.")
    return level


def _flag(options, field, default):
    value = options.get(field, default)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise FieldError(field, f"{field} must be yes or no.")


def _series(frame, name, field):
    if not isinstance(name, str) or not name:
        raise FieldError(field, f"Choose a column for {field}.")
    if name not in frame.columns:
        raise FieldError(field, f'Column "{name}" is not in the table.')
    return _column(frame, name, field)


def _distinct(field, message, *names):
    chosen = [name for name in names if name]
    if len(chosen) != len(set(chosen)):
        raise FieldError(field, message)


def _varies(values):
    return len(values) > 0 and values.min() != values.max()


def _literal(artist):
    if artist is not None and hasattr(artist, "set_parse_math"):
        artist.set_parse_math(False)
    return artist


def _style_text(axes):
    _literal(axes.title)
    _literal(axes.xaxis.label)
    _literal(axes.yaxis.label)
    for tick in (*axes.get_xticklabels(), *axes.get_yticklabels()):
        _literal(tick)


def adjust_p_values(values, method):
    """Holm and Benjamini–Hochberg on the finite p values only, in their given order."""
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="stable")
    count = len(values)
    if method == "None":
        return values.tolist()
    if method == "Holm":
        raw = np.maximum.accumulate((count - np.arange(count)) * values[order])
    else:
        raw = np.minimum.accumulate((values[order] * count / (np.arange(count) + 1))[::-1])[::-1]
    out = np.empty(count)
    out[order] = np.minimum(raw, 1)
    return out.tolist()


def _exact_p(x, y, alternative):
    scores_x = _rank_scores(stats.rankdata(x))
    scores_y = _rank_scores(stats.rankdata(y))
    return _permutation_p(_exact_key(scores_x, scores_y), int(scores_x @ scores_y), _SCIPY_ALTERNATIVE[alternative])


def _interval(coefficient, n, level, kind):
    """Two-sided Fisher z, or Bonett–Wright for Spearman. No interval is invented below the minimum n."""
    if kind == "Pearson" and n >= 4 or kind == "Spearman" and n >= 11:
        method = "Fisher z" if kind == "Pearson" else "Bonett–Wright"
        if abs(coefficient) == 1:
            return coefficient, coefficient, method, ""
        variance = 1 + coefficient * coefficient / 2 if kind == "Spearman" else 1.0
        delta = stats.norm.isf((1 - level / 100) / 2) * np.sqrt(variance / (n - 3))
        center = np.arctanh(coefficient)
        return float(np.tanh(center - delta)), float(np.tanh(center + delta)), method, ""
    if kind == "Pearson":
        reason = f"Confidence limits are omitted because n = {n} is below 4."
    elif kind == "Spearman":
        reason = f"Confidence limits are omitted because n = {n} is below 11."
    else:
        reason = "Kendall tau-b has no confidence interval in this analysis."
    return None, None, "Unavailable", reason


def correlation_statistics(x, y, *, method="Pearson", alternative="Two-sided", confidence=95.0,
                           p_method="Automatic", exact_budget=STANDARD, exact_family=None):
    """N, coefficient, p, two-sided limits, R², the p and interval methods, and the reason.

    ``x`` and ``y`` are not modified. R² is Pearson only. The missing budget
    retains Standard (9 pairs); Extended enables resource-bounded tests through 17.
    """
    x = np.asarray(x, dtype=float).copy()
    y = np.asarray(y, dtype=float).copy()
    if method not in SINGLE_METHODS:
        raise FieldError("Method", "Choose a valid Method.")
    if alternative not in ALTERNATIVES:
        raise FieldError("Alternative", "Choose a valid Alternative.")
    if p_method not in P_METHODS:
        raise FieldError("Spearman p values", "Choose a valid Spearman p values.")
    level = _number(confidence, "Confidence level (%)")
    if not 0 < level < 100:
        raise FieldError("Confidence level (%)",
                         "Confidence level (%) must be a finite number strictly between 0 and 100.")
    if x.shape != y.shape or x.ndim != 1 or len(x) < 3 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Complete finite arrays of at least three pairs are required.")
    if not _varies(x) or not _varies(y):
        raise ValueError("Constant vector")
    n = len(x)
    reasons = []
    if method == "Pearson":
        # Center around a safe midpoint before scaling: a direct mean can overflow
        # even when every observation and the correlation are representable.
        coefficient, probability = _coefficient_and_p(x, y, _SCIPY_ALTERNATIVE[alternative])
        label = "Pearson beta"
    elif method == "Spearman":
        test = stats.spearmanr(x, y, alternative=_SCIPY_ALTERNATIVE[alternative])
        coefficient = float(test.statistic)
        if p_method != "Approximate" and exact_budget not in BUDGETS:
            raise FieldError(EXACT_BUDGET, f"Choose a valid {EXACT_BUDGET}.")
        if p_method != "Approximate" and exact_budget == EXTENDED:
            family = exact_family if exact_family is not None else ExactSpearmanFamily()
            probability, reason = family.probability(x, y, alternative, p_method)
            label = "Exact" if probability is not None else "Approximate"
            if probability is None:
                probability = float(test.pvalue)
                reasons.append(reason)
        else:
            probability, label, reason = _standard_spearman(x, y, alternative, p_method, test)
            if reason:
                reasons.append(reason)
    else:
        test = stats.kendalltau(x, y, method="asymptotic", variant="b", alternative=_SCIPY_ALTERNATIVE[alternative])
        coefficient, probability, label = float(test.statistic), float(test.pvalue), "Kendall asymptotic"
    low, high, interval, reason = _interval(coefficient, n, level, method)
    if reason:
        reasons.append(reason)
    return {
        "N": n, "Coefficient": coefficient, "p": probability, "Lower": low, "Upper": high,
        "R²": coefficient * coefficient if method == "Pearson" else None,
        "P method": label, "CI method": interval, "Reason": " ".join(reasons),
    }


def _standard_spearman(x, y, alternative, p_method, test):
    n = len(x)
    reason = ""
    exact = p_method == "Exact" or (p_method == "Automatic" and n <= EXACT_LIMIT)
    if p_method == "Exact" and n > EXACT_LIMIT:
        raise FieldError("Spearman p values",
                         f"Exact Spearman p values support at most {EXACT_LIMIT} complete pairs; {n} were found.")
    if exact:
        probability, label = _exact_p(x, y, alternative), "Exact"
    else:
        probability, label = float(test.pvalue), "Approximate"
        if p_method == "Automatic":
            reason = (f"Automatic Spearman p values use the t approximation because n = {n} "
                      f"exceeds the exact budget of {EXACT_LIMIT} pairs.")
    return probability, label, reason


def independent_correlation_test(r1, n1, r2, n2, *, alternative="Two-sided", confidence=95.0):
    """Compare two independent Pearson correlations on the Fisher z scale.

    Difference is r1 − r2 and is descriptive. The interval is not transformed back to r.
    A coefficient of exactly ±1 keeps the caller’s estimates elsewhere and makes this test unavailable.
    """
    if alternative not in ALTERNATIVES:
        raise FieldError("Alternative", "Choose a valid Alternative.")
    level = _number(confidence, "Confidence level (%)")
    if not 0 < level < 100:
        raise FieldError("Confidence level (%)",
                         "Confidence level (%) must be a finite number strictly between 0 and 100.")
    r1, r2, n1, n2 = float(r1), float(r2), int(n1), int(n2)
    difference = r1 - r2
    if abs(r1) == 1 or abs(r2) == 1:
        return {"Fisher z difference": None, "SE": None, "Z": None, "p": None, "Z lower": None, "Z upper": None,
                "Difference": difference, "Status": "Unavailable",
                "Reason": "The comparison is unavailable because a coefficient is exactly ±1."}
    if min(n1, n2) <= 3:
        raise ValueError("Each correlation needs more than three pairs.")
    z1, z2 = np.arctanh(r1), np.arctanh(r2)
    difference_z = float(z1 - z2)
    standard_error = float(np.sqrt(1 / (n1 - 3) + 1 / (n2 - 3)))
    z = difference_z / standard_error
    if alternative == "Two-sided":
        probability = float(2 * stats.norm.sf(abs(z)))
    elif alternative == "Positive":
        probability = float(stats.norm.sf(z))
    else:
        probability = float(stats.norm.cdf(z))
    delta = float(stats.norm.isf((1 - level / 100) / 2) * standard_error)
    return {"Fisher z difference": difference_z, "SE": standard_error, "Z": z, "p": probability,
            "Z lower": difference_z - delta, "Z upper": difference_z + delta, "Difference": difference,
            "Status": "Available", "Reason": ""}


def _complete_pairs(x, y):
    mask = x.notna().to_numpy() & y.notna().to_numpy()
    return x.to_numpy(dtype=float)[mask], y.to_numpy(dtype=float)[mask], x.index[mask]


def _unavailable(name, n, reason):
    return {"Variable": name, "N": n, "Coefficient": None, "p": None, "p adjusted": None,
            "Lower": None, "Upper": None, "R²": None, "P method": "", "CI method": "",
            "Status": "Unavailable", "Reason": reason}


def _scatter(method, x_name, y_name, x, y):
    figure, axes = _plot(f"{method} correlation", x_name, y_name)
    axes.scatter(x, y, gid="corr:points")
    _style_text(axes)
    return figure


def _coefficient_figure(title, rows, show, level, note):
    figure, axes = _plot(title, "Coefficient", "")
    available = [row for row in rows if row.get("Status", "Available") == "Available"]
    positions = np.arange(len(available))
    coefficients = [row["Coefficient"] for row in available]
    axes.plot(coefficients, positions, "o", color="#1f4e79", gid="corr:coefficients", linestyle="none")
    if show:
        limited = [(position, row) for position, row in zip(positions, available)
                   if row["Lower"] is not None and row["Upper"] is not None]
        if limited:
            container = axes.errorbar(
                [row["Coefficient"] for _, row in limited], [position for position, _ in limited],
                xerr=[[row["Coefficient"] - row["Lower"] for _, row in limited],
                      [row["Upper"] - row["Coefficient"] for _, row in limited]],
                fmt="none", capsize=3, ecolor="#1f4e79")
            for line in container.lines[2]:
                line.set_gid("corr:intervals")
    axes.axvline(0, color="#7d8da1", linewidth=0.8)
    axes.set_xlim(-1, 1)
    axes.set_yticks(positions)
    axes.set_yticklabels([str(row.get("Variable", row.get("Group"))) for row in available])
    axes.set_xlabel("Coefficient")
    caption = fill(f"{note} Level {level:g}%.", width=36)
    axes.plot([], [], "o", color="#1f4e79", label="Coefficient")
    # Outside the axes: a long pointwise note must not cover the coefficients.
    legend = axes.legend(title=caption, loc="center left", bbox_to_anchor=(1.02, 0.5), borderaxespad=0)
    if legend is not None:
        _literal(legend.get_title())
        for text in legend.get_texts():
            _literal(text)
    _style_text(axes)
    return figure


def validate_request(method, frame, options):
    """Name the field to correct. Counting pairs is allowed; permutations are not."""
    if method == "Correlation" and options.get("Detailed results") is not True:
        return None
    if method not in CORRELATION_METHODS:
        return None
    alternative = _choice(options, "Alternative", ALTERNATIVES)
    level = _level(options)
    if method == "Correlation":
        if options.get("Detailed results") is not True:
            return None
        _flag(options, "Detailed results", False)
        x_name, y_name = options.get("X"), options.get("Y")
        _distinct("Y", "Select different columns for X and Y.", x_name, y_name)
        x, y = _series(frame, x_name, "X"), _series(frame, y_name, "Y")
        chosen = _choice(options, "Method", SINGLE_METHODS)
        p_method = _choice(options, "Spearman p values", P_METHODS) if chosen == "Spearman" else "Automatic"
        budget = _active_budget(options, chosen, p_method)
        xs, ys, index = _complete_pairs(x, y)
        _require_pair(xs, ys, chosen, p_method, 17 if budget == EXTENDED else EXACT_LIMIT)
        return {"kind": "single", "x": xs, "y": ys, "method": chosen, "alternative": alternative,
                "level": level, "p_method": p_method, "exact_budget": budget, "omitted": int(len(x) - len(xs)),
                "x_name": x_name, "y_name": y_name, "index": index}
    if method == CORRELATE_CONTROL:
        return _prepare_control(frame, options, alternative, level)
    return _prepare_independent(frame, options, alternative, level)


def _active_budget(options, method, p_method):
    if method != "Spearman" or p_method == "Approximate":
        return STANDARD
    return _choice(options, EXACT_BUDGET, BUDGETS, default=STANDARD)


def _require_pair(xs, ys, method, p_method, limit=EXACT_LIMIT):
    if len(xs) < 3:
        raise FieldError("Y", f"At least three complete pairs are required; {len(xs)} were found.")
    if not _varies(xs):
        raise FieldError("X", "X has no variation in the complete pairs.")
    if not _varies(ys):
        raise FieldError("Y", "Y has no variation in the complete pairs.")
    if method == "Spearman" and p_method == "Exact" and len(xs) > limit:
        raise FieldError("Spearman p values",
                         f"Exact Spearman p values support at most {limit} complete pairs; {len(xs)} were found.")


def _prepare_control(frame, options, alternative, level):
    x_name = options.get("X")
    names = options.get("Variables")
    if (not isinstance(names, (list, tuple)) or not 1 <= len(names) <= MAX_RESPONSES
            or any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names)
            or x_name in names):
        raise FieldError("Variables", "Choose 1 to 24 distinct response columns, all different from X.")
    method = _choice(options, "Method", CONTROL_METHODS)
    missing = _choice(options, "Missing values", MISSING)
    adjustment = _choice(options, "P adjustment", ADJUSTMENTS)
    show = _flag(options, "Show intervals", True)
    p_method = _choice(options, "Spearman p values", P_METHODS) if method == "Spearman" else "Automatic"
    budget = _active_budget(options, method, p_method)
    limit = 17 if budget == EXTENDED else EXACT_LIMIT
    x = _series(frame, x_name, "X")
    responses = [(name, _series(frame, name, "Variables")) for name in names]
    if missing == "Listwise complete":
        mask = x.notna().to_numpy()
        for _, series in responses:
            mask = mask & series.notna().to_numpy()
    else:
        mask = None
    planned = []
    over_budget = None
    calculable = False
    for name, series in responses:
        if mask is None:
            xs, ys, index = _complete_pairs(x, series)
        else:
            xs = x.to_numpy(dtype=float)[mask]
            ys = series.to_numpy(dtype=float)[mask]
            index = x.index[mask]
        usable = len(xs) >= 3 and _varies(xs) and _varies(ys)
        if usable:
            calculable = True
            if method == "Spearman" and p_method == "Exact" and len(xs) > limit and over_budget is None:
                over_budget = len(xs)
        planned.append((name, xs, ys, index, usable))
    if over_budget is not None:
        raise FieldError("Spearman p values",
                         f"Exact Spearman p values support at most {limit} complete pairs; {over_budget} were found.")
    if not calculable:
        raise FieldError("Variables",
                         "No selected response has at least three complete pairs and variation in both variables.")
    return {"kind": "control", "method": method, "alternative": alternative, "level": level, "p_method": p_method,
            "exact_budget": budget, "missing": missing, "adjustment": adjustment, "show": show, "x_name": x_name, "planned": planned}


def _missing_group(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, (float, np.floating)):
        return bool(isnan(float(value)))
    return False


def _same_group(left, right):
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, (bool, np.bool_)) or isinstance(right, (bool, np.bool_)):
        return (isinstance(left, (bool, np.bool_)) and isinstance(right, (bool, np.bool_))
                and bool(left) is bool(right))
    if isinstance(left, (int, np.integer, float, np.floating)) and isinstance(right, (int, np.integer, float, np.floating)):
        # Python compares int/float without rounding the integer first. Converting
        # both to float would merge distinct identifiers above 2**53.
        left = int(left) if isinstance(left, (int, np.integer)) else float(left)
        right = int(right) if isinstance(right, (int, np.integer)) else float(right)
        return left == right
    return type(left) is type(right) and left == right


def _prepare_independent(frame, options, alternative, level):
    x_name, y_name, group_name = options.get("X"), options.get("Y"), options.get("Group")
    _distinct("Y", "Select different columns for X and Y.", x_name, y_name)
    if not isinstance(group_name, str) or not group_name or group_name in (x_name, y_name):
        raise FieldError("Group", "Choose a grouping column that is not X or Y.")
    if group_name not in frame.columns:
        raise FieldError("Group", f'Column "{group_name}" is not in the table.')
    show = _flag(options, "Show intervals", True)
    x, y = _series(frame, x_name, "X"), _series(frame, y_name, "Y")
    groups, omitted = [], 0
    for value in frame[group_name].tolist():
        if _missing_group(value):
            omitted += 1
            continue
        if not any(_same_group(value, found) for found in groups):
            groups.append(value)
    if len(groups) != 2:
        raise FieldError("Group", f"Exactly two non-missing groups are required; {len(groups)} were found.")
    prepared = []
    for group in groups:
        rows = np.array([not _missing_group(value) and _same_group(value, group)
                        for value in frame[group_name].tolist()], dtype=bool)
        xs = x.to_numpy(dtype=float)[rows]
        ys = y.to_numpy(dtype=float)[rows]
        index = x.index[rows]
        finite = np.isfinite(xs) & np.isfinite(ys)
        xs, ys, index = xs[finite], ys[finite], index[finite]
        if len(xs) < 4:
            raise FieldError("Group", f"Group {group} needs at least four complete pairs; {len(xs)} were found.")
        if not _varies(xs) or not _varies(ys):
            raise FieldError("Group", f"Group {group} has no variation in X or Y.")
        prepared.append((group, xs, ys, index))
    incomplete = int((~x.notna().to_numpy() | ~y.notna().to_numpy()).sum())
    return {"kind": "independent", "alternative": alternative, "level": level, "show": show,
            "x_name": x_name, "y_name": y_name, "group_name": group_name, "groups": prepared,
            "omitted_groups": omitted, "incomplete": incomplete}


def _single_result(plan, cancel=None):
    family = ExactSpearmanFamily(cancel=cancel)
    summary = correlation_statistics(plan["x"], plan["y"], method=plan["method"], alternative=plan["alternative"],
                                     confidence=plan["level"], p_method=plan["p_method"],
                                     exact_budget=plan["exact_budget"], exact_family=family)
    table = {key: summary[key] for key in _STAT_KEYS}
    pairs = pd.DataFrame({"Source row": plan["index"].tolist(), "X": plan["x"], "Y": plan["y"]})
    tables = {"Correlation": _report(table), "Pairs": pairs}
    if plan["method"] == "Spearman":
        tables["Ranks"] = pd.DataFrame({
            "Source row": plan["index"].tolist(),
            "X rank": stats.rankdata(plan["x"]),
            "Y rank": stats.rankdata(plan["y"]),
        })
    settings = {
        "X": plan["x_name"], "Y": plan["y_name"], "Method": plan["method"], "Alternative": plan["alternative"],
        "Confidence level (%)": plan["level"], "Detailed results": True,
        "Confidence intervals": "Always two-sided at the chosen level, including when the test is one-sided.",
        "Exact Spearman budget": f"At most {EXACT_LIMIT} complete pairs (362880 labelled permutations).",
        "Rows omitted (incomplete pairs)": plan["omitted"],
        "P method": summary["P method"], "CI method": summary["CI method"], "Reason": summary["Reason"],
    }
    if plan["method"] == "Spearman":
        settings["Spearman p values"] = plan["p_method"]
        if plan["exact_budget"] == EXTENDED:
            settings["Exact Spearman budget"] = "At most 17 complete pairs; 4,000,000 family transitions; 384 MiB planned dense storage."
            settings[EXACT_BUDGET] = EXTENDED
    tables["Settings"] = _report(settings)
    return Result(tables, _scatter(plan["method"], plan["x_name"], plan["y_name"], plan["x"], plan["y"]))


def _control_result(plan, cancel=None):
    family = ExactSpearmanFamily(cancel=cancel)
    rows, probabilities, usable = [], [], []
    pair_frames = []
    for name, xs, ys, index, usable_row in plan["planned"]:
        family.check()
        pair_frames.append(pd.DataFrame({"Variable": name, "Source row": index.tolist(), "X": xs, "Y": ys}))
        if not usable_row:
            reason = f"{name} is constant or has fewer than three complete pairs."
            rows.append(_unavailable(name, len(xs), reason))
            continue
        summary = correlation_statistics(xs, ys, method=plan["method"], alternative=plan["alternative"],
                                         confidence=plan["level"], p_method=plan["p_method"],
                                     exact_budget=plan["exact_budget"], exact_family=family)
        rows.append({"Variable": name, "N": summary["N"], "Coefficient": summary["Coefficient"], "p": summary["p"],
                     "p adjusted": None, "Lower": summary["Lower"], "Upper": summary["Upper"], "R²": summary["R²"],
                     "P method": summary["P method"], "CI method": summary["CI method"], "Status": "Available",
                     "Reason": summary["Reason"]})
        probabilities.append(summary["p"])
        usable.append(len(rows) - 1)
    adjusted = adjust_p_values(probabilities, plan["adjustment"])
    for index, value in zip(usable, adjusted, strict=True):
        rows[index]["p adjusted"] = value
    columns = ["Variable", "N", "Coefficient", "p", "p adjusted", "Lower", "Upper", "R²",
               "P method", "CI method", "Status", "Reason"]
    settings = {
        "X": plan["x_name"], "Variables": ", ".join(name for name, *_ in plan["planned"]),
        "Method": plan["method"], "Alternative": plan["alternative"], "Confidence level (%)": plan["level"],
        "Missing values": plan["missing"], "P adjustment": plan["adjustment"], "Show intervals": plan["show"],
        "Interval scope": "Pointwise, not simultaneous. Adjusted p values do not change the intervals.",
        "Confidence intervals": "Always two-sided at the chosen level, including when the test is one-sided.",
        "Exact Spearman budget": f"At most {EXACT_LIMIT} complete pairs.",
    }
    if plan["method"] == "Spearman":
        settings["Spearman p values"] = plan["p_method"]
        if plan["exact_budget"] == EXTENDED:
            settings["Exact Spearman budget"] = "At most 17 complete pairs; 4,000,000 family transitions; 384 MiB planned dense storage."
            settings[EXACT_BUDGET] = EXTENDED
    # Tick labels stay the worksheet names. Sample size is only in the legend.
    figure_rows = [{"Variable": row["Variable"], "Coefficient": row["Coefficient"], "Lower": row["Lower"],
                    "Upper": row["Upper"], "Status": row["Status"]} for row in rows]
    note = (f"{plan['method']}. Pointwise, not simultaneous. "
            + ", ".join(f"n({row['Variable']})={row['N']}" for row in rows if row["Status"] == "Available"))
    tables = {"Correlations": pd.DataFrame(rows, columns=columns),
              "Pairs": pd.concat(pair_frames, ignore_index=True) if pair_frames else pd.DataFrame(
                  columns=["Variable", "Source row", "X", "Y"]),
              "Settings": _report(settings)}
    return Result(tables, _coefficient_figure(f"Correlations with {plan['x_name']}", figure_rows, plan["show"],
                                             plan["level"], note))


def _independent_result(plan):
    group_rows, comparisons, pair_frames = [], [], []
    for group, xs, ys, index in plan["groups"]:
        summary = correlation_statistics(xs, ys, method="Pearson", alternative="Two-sided", confidence=plan["level"])
        group_rows.append({"Group": group, "N": summary["N"], "Coefficient": summary["Coefficient"],
                           "Lower": summary["Lower"], "Upper": summary["Upper"]})
        comparisons.append(summary)
        pair_frames.append(pd.DataFrame({"Group": group, "Source row": index.tolist(), "X": xs, "Y": ys}))
    first, second = comparisons
    tested = independent_correlation_test(first["Coefficient"], first["N"], second["Coefficient"], second["N"],
                                         alternative=plan["alternative"], confidence=plan["level"])
    settings = {
        "X": plan["x_name"], "Y": plan["y_name"], "Group": plan["group_name"],
        "Alternative": plan["alternative"], "Confidence level (%)": plan["level"], "Show intervals": plan["show"],
        "Rows omitted (missing group)": plan["omitted_groups"],
        "Rows omitted (incomplete pairs)": plan["incomplete"],
        "Comparison interval": "Fisher z difference. Not an interval for the difference of the coefficients.",
        "Confidence intervals": "Per-group Fisher z intervals are always two-sided and are plotted on the correlation scale.",
        "Independence": "The two groups are assumed independent. Trama does not check the study design.",
    }
    figure_rows = [{"Group": row["Group"], "Variable": str(row["Group"]), "Coefficient": row["Coefficient"],
                    "Lower": row["Lower"], "Upper": row["Upper"], "Status": "Available"} for row in group_rows]
    note = ("Pearson. Plotted intervals are per-group Fisher z intervals on the correlation scale. "
            "The comparison interval is the Fisher z difference. "
            + ", ".join(f"n({row['Group']})={row['N']}" for row in group_rows))
    tables = {
        "Groups": pd.DataFrame(group_rows, columns=["Group", "N", "Coefficient", "Lower", "Upper"]),
        "Comparison": _report(tested),
        "Pairs": pd.concat(pair_frames, ignore_index=True),
        "Settings": _report(settings),
    }
    return Result(tables, _coefficient_figure("Independent Pearson correlations", figure_rows, plan["show"],
                                             plan["level"], note))


def correlation_result(frame, options, *, cancel=None):
    plan = validate_request("Correlation", frame, options)
    return _single_result(plan, cancel=cancel)


def control_result(frame, options, *, cancel=None):
    plan = validate_request(CORRELATE_CONTROL, frame, options)
    return _control_result(plan, cancel=cancel)


def independent_result(frame, options):
    plan = validate_request(COMPARE_INDEPENDENT, frame, options)
    return _independent_result(plan)
