"""Independent or matched group comparisons for each worksheet row."""
from itertools import chain
from math import sqrt
import re

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .category_graphs import _SUMMARY, _title
from .processing import FieldError, _column, _number
from .reporting import Result, _plot, _report
from .worksheet_series import series_columns


ROW_TESTS = "Multiple tests (one per row)"
RAW, MEAN_SD, MEAN_SEM = FORMATS = ("Raw replicates", "Mean, SD and N", "Mean, SEM and N")
WELCH, STUDENT, PAIRED, MANN_WHITNEY, WILCOXON = TESTS = (
    "Welch t-test", "Student t-test", "Paired t-test", "Mann–Whitney", "Wilcoxon matched pairs")
FDR = {"Benjamini–Hochberg": "fdr_bh", "Benjamini–Yekutieli": "fdr_by",
       "Benjamini–Krieger–Yekutieli": "fdr_tsbky"}
CORRECTIONS = {"Holm–Šídák": "holm-sidak", "Šídák": "sidak", "Bonferroni": "bonferroni",
               "Holm": "holm", "None": None, **FDR}
RAW_FIELDS = ("First replicates", "Second replicates")
SUMMARY_FIELDS = tuple(f"{group} {value}" for group in ("First", "Second") for value in ("mean", "error", "N"))
PLOTS = ("Volcano plot", "Differences and intervals", "None")
OPTIONS = {
    "Input format": FORMATS, **dict.fromkeys(RAW_FIELDS, "Multiple"),
    **dict.fromkeys(SUMMARY_FIELDS, None), "Row labels": "Optional", "Test": TESTS,
    "Correction": tuple(CORRECTIONS), "Family alpha": .05, "False discovery rate (%)": 5.,
    "Confidence level (%)": 95., "Graph": PLOTS,
}
_SUBCOLUMN = re.compile(r" \[([1-9]\d*)\](?: \(\d+\))?$")
_SUMMARY_ROLE = re.compile(r"(.+) \[(Mean|SD|SEM|N)\]( \(\d+\))?$")
_MAX_ROWS = 2_000


def visibility(input_format, test, correction):
    raw = input_format == RAW
    return {**dict.fromkeys(RAW_FIELDS, raw), **dict.fromkeys(SUMMARY_FIELDS, not raw),
            "Family alpha": correction not in FDR, "False discovery rate (%)": correction in FDR,
            "Confidence level (%)": test not in {MANN_WHITNEY, WILCOXON}}


def default_options(frame):
    names = list(frame.columns)
    summary = {}
    for name in names:
        if match := _SUMMARY_ROLE.fullmatch(name):
            summary.setdefault(match[1] + (match[3] or ""), {})[match[2]] = name
    for format_name, error in ((MEAN_SD, "SD"), (MEAN_SEM, "SEM")):
        complete = [fields for fields in summary.values() if {"Mean", error, "N"} <= fields.keys()]
        if len(complete) == 2:
            columns = [fields[role] for fields in complete for role in ("Mean", error, "N")]
            return {"Input format": format_name, **dict(zip(SUMMARY_FIELDS, columns, strict=True))}
    groups = [group for group in series_columns(frame, names, recognize_replicates=True)
              if len(group) > 1 and not any(_SUMMARY.fullmatch(name) for name in group)]
    if len(groups) == 2:
        return dict(zip(RAW_FIELDS, groups, strict=True))
    return {}


def _choice(options, field, choices):
    value = options.get(field, next(iter(choices)))
    if value not in choices:
        raise FieldError(field, f"Choose a valid {field.lower()}.")
    return value


def _number_in_range(options, field, default, upper):
    value = _number(options.get(field, default), field)
    if not 0 < value < upper:
        raise FieldError(field, f"Enter a number strictly between 0 and {upper:g}.")
    return value


def _raw_columns(options, field):
    names = options.get(field, ())
    if (not isinstance(names, (tuple, list)) or not 1 <= len(names) <= 128
            or any(not isinstance(name, str) or _SUMMARY.fullmatch(name) for name in names)
            or len(set(names)) != len(names)):
        raise FieldError(field, "Choose distinct raw replicate columns for the group.")
    return names


def _matched(first, second):
    keys = [[_SUBCOLUMN.search(name) for name in group] for group in (first, second)]
    numbered = [match for match in chain.from_iterable(keys) if match]
    if not numbered:
        if len(first) != len(second):
            raise FieldError("Second replicates", "Select equally many ordered columns for an unnumbered paired comparison.")
        return first, second
    if len(numbered) != len(first) + len(second):
        raise FieldError("Second replicates", "For paired tests, number the subcolumns in both groups or use ordered columns.")
    pairs = [dict(zip((int(match[1]) for match in matches), names, strict=True))
             for matches, names in zip(keys, (first, second), strict=True)]
    if len(pairs[0]) != len(first) or len(pairs[1]) != len(second):
        raise FieldError("Second replicates", "Select only one subcolumn for each replicate number per group.")
    shared = sorted(pairs[0].keys() & pairs[1].keys())
    if len(shared) < 2:
        raise FieldError("Second replicates", "Select at least two corresponding replicate numbers.")
    return tuple([group[number] for number in shared] for group in pairs)


def _source(frame, options, input_format, test):
    if input_format == RAW:
        first, second = (_raw_columns(options, field) for field in RAW_FIELDS)
        if set(first) & set(second):
            raise FieldError("Second replicates", "The two groups must use distinct columns.")
        groups = _matched(first, second) if test in {PAIRED, WILCOXON} else (first, second)
        labels = []
        for field, group in zip(RAW_FIELDS, (first, second), strict=True):
            titles = {_title(name).strip() for name in group}
            labels.append(next(iter(titles)) if len(titles) == 1 else field.split()[0])
        columns = {name: _column(frame, name, field).to_numpy()
                   for field, selected in zip(RAW_FIELDS, (first, second), strict=True) for name in selected}
        populated = np.logical_or.reduce([np.isfinite(values) for values in columns.values()])
        data = [np.column_stack([columns[name] for name in group]) for group in groups]
        return labels, data, populated

    names = [options.get(field) for field in SUMMARY_FIELDS]
    data = [_column(frame, name, field).to_numpy() for field, name in zip(SUMMARY_FIELDS, names, strict=True)]
    if len(set(names)) != len(names):
        raise FieldError("Input format", "Assign a distinct column to each summary measure.")
    for offset in (0, 3):
        error, count = data[offset + 1:offset + 3]
        if (error[np.isfinite(error)] < 0).any():
            raise FieldError(SUMMARY_FIELDS[offset + 1], "Error values must be nonnegative.")
        observed = count[np.isfinite(count)]
        if ((observed < 2) | (observed != np.floor(observed)) | (observed > 2**53)).any():
            raise FieldError(SUMMARY_FIELDS[offset + 2], "Sample sizes must be exact whole numbers of at least two.")
    labels = tuple(_SUMMARY_ROLE.sub(r"\1\3", names[offset]).strip() for offset in (0, 3))
    populated = np.logical_or.reduce([np.isfinite(values) for values in data])
    return labels, [np.column_stack(data[:3]), np.column_stack(data[3:])], populated


def _mean_sd(values):
    if not len(values):
        return np.nan, np.nan
    scale = np.abs(values).max()
    if scale == 0:
        return 0., 0. if len(values) > 1 else np.nan
    scaled = values / scale
    with np.errstate(over="ignore"):
        return scaled.mean() * scale, scaled.std(ddof=1) * scale if len(values) > 1 else np.nan


def _t_result(difference, se, df, level):
    if not (np.isfinite(difference) and np.isfinite(se) and se > 0 and np.isfinite(df)):
        return {"Status": "Variance or difference unavailable"}
    t = difference / se
    margin = stats.t.isf((100 - level) / 200, df) * se
    bounds = difference - margin, difference + margin
    return {"Statistic": t, "df": df, "p": 2 * stats.t.sf(abs(t), df),
            "CI lower": bounds[0] if np.isfinite(bounds[0]) else np.nan,
            "CI upper": bounds[1] if np.isfinite(bounds[1]) else np.nan}


def _unpaired_t(mean_a, sd_a, n_a, mean_b, sd_b, n_b, test, level):
    scale = max(sd_a, sd_b)
    if not np.isfinite(scale) or scale <= 0:
        return {"Status": "Variance unavailable"}
    v_a, v_b = (sd_a / scale)**2, (sd_b / scale)**2
    if test == STUDENT:
        df = n_a + n_b - 2
        variance = ((n_a - 1) * v_a + (n_b - 1) * v_b) / df
        se = sqrt(variance * (1 / n_a + 1 / n_b)) * scale
    else:
        a, b = v_a / n_a, v_b / n_b
        se = sqrt(a + b) * scale
        df = (a + b)**2 / (a**2 / (n_a - 1) + b**2 / (n_b - 1))
    return _t_result(mean_a - mean_b, se, df, level)


def _raw_row(a, b, test, level):
    paired = test in {PAIRED, WILCOXON}
    if paired:
        present = np.isfinite(a) & np.isfinite(b)
        a, b = a[present], b[present]
    else:
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    mean_a, sd_a = _mean_sd(a)
    mean_b, sd_b = _mean_sd(b)
    with np.errstate(over="ignore", invalid="ignore"):
        difference = mean_a - mean_b
    row = {"N first": len(a), "N second": len(b), "Mean first": mean_a, "Mean second": mean_b,
           "Difference": difference if np.isfinite(difference) else np.nan}
    if min(len(a), len(b)) < 2:
        return {**row, "Status": "Insufficient complete pairs" if paired else "Insufficient observations"}
    if test == PAIRED:
        with np.errstate(over="ignore"):
            delta = a - b
        if not np.isfinite(delta).all():
            return {**row, "Status": "Difference unavailable"}
        center, sd = _mean_sd(delta)
        fit = _t_result(center, sd / sqrt(len(a)), len(a) - 1, level)
        row["Difference"] = center
    elif test == WILCOXON:
        with np.errstate(over="ignore"):
            delta = a - b
        if not np.isfinite(delta).all():
            return {**row, "Status": "Difference unavailable"}
        if (delta == 0).all():
            fit = {"Statistic": 0., "p": 1.}
        else:
            result = stats.wilcoxon(delta, alternative="two-sided", method="auto")
            fit = {"Statistic": result.statistic, "p": result.pvalue}
    elif test == MANN_WHITNEY:
        result = stats.mannwhitneyu(a, b, alternative="two-sided", method="auto")
        fit = {"Statistic": result.statistic, "p": result.pvalue}
    else:
        with np.errstate(over="ignore", invalid="ignore"):
            fit = _unpaired_t(mean_a, sd_a, len(a), mean_b, sd_b, len(b), test, level)
    return {**row, **fit}


def _summary_row(a, b, input_format, test, level):
    mean_a, sd_a, n_a = a
    mean_b, sd_b, n_b = b
    with np.errstate(over="ignore", invalid="ignore"):
        difference = mean_a - mean_b
    row = {"N first": n_a, "N second": n_b, "Mean first": mean_a, "Mean second": mean_b,
           "Difference": difference if np.isfinite(difference) else np.nan}
    if not np.isfinite([*a, *b]).all():
        return {**row, "Status": "Missing summary"}
    with np.errstate(over="ignore", invalid="ignore"):
        if input_format == MEAN_SEM:
            sd_a, sd_b = sd_a * sqrt(n_a), sd_b * sqrt(n_b)
        fit = _unpaired_t(mean_a, sd_a, n_a, mean_b, sd_b, n_b, test, level)
    return {**row, **fit}


def _bky_q(probabilities):
    """Find each minimum FDR by searching the first-stage rejection count."""
    order = np.argsort(probabilities, kind="stable")
    p = probabilities[order]
    m = len(p)
    bh = np.minimum.accumulate((p * m / np.arange(1, m + 1))[::-1])[::-1]
    # For r first-stage rejections, alpha-prime must reach both BH cutoffs.
    # The first-stage cutoff increases with r while the second decreases.
    lower, upper = np.ones(m, dtype=int), np.full(m, m, dtype=int)
    while (lower < upper).any():
        count = (lower + upper) // 2
        crossed = bh[count - 1] >= bh * ((m - count) / m)
        upper = np.where(crossed, count, upper)
        lower = np.where(crossed, lower, count + 1)
    before = np.maximum(lower - 1, 1)
    at_crossing = np.maximum(bh[lower - 1], bh * ((m - lower) / m))
    before_crossing = np.maximum(bh[before - 1], bh * ((m - before) / m))
    alpha_prime = np.minimum(at_crossing, before_crossing)
    result = np.empty(m)
    result[order] = np.divide(alpha_prime, 1 - alpha_prime, out=np.ones(m), where=alpha_prime < .5)
    return result


def _multiplicity(table, correction, threshold):
    p = table["p"].to_numpy(dtype=float)
    valid = np.isfinite(p)
    adjusted = np.full(len(p), np.nan)
    discoveries = pd.array([None] * len(p), dtype="boolean")
    if valid.any():
        method = CORRECTIONS[correction]
        if method is None:
            rejected, values = p[valid] <= threshold, p[valid]
        else:
            # Holm–Šídák uses log(1 - p), including the valid endpoint p = 1.
            with np.errstate(divide="ignore"):
                rejected, values, _, _ = multipletests(p[valid], alpha=threshold, method=method)
            if method == "fdr_tsbky":
                values = _bky_q(p[valid])
        discoveries[valid] = rejected
        adjusted[valid] = values
    column = "q" if correction in FDR else "Adjusted p"
    table[column] = adjusted
    table["Discovery" if correction in FDR else "Significant"] = discoveries
    return column


def _graph(table, plot, probability_column, labels):
    if plot == PLOTS[-1]:
        return None
    x = table["Difference"].to_numpy(dtype=float)
    valid = np.isfinite(x) & table[probability_column].notna().to_numpy()
    if not valid.any():
        return None
    if plot == PLOTS[0]:
        y = table[probability_column].to_numpy(dtype=float)[valid]
        figure, axes = _plot("Multiple row comparisons", f"Mean difference ({labels[0]} − {labels[1]})",
                             f"−log₁₀({probability_column})")
        axes.axvline(0, color="#a4b4c4", linewidth=1)
        axes.scatter(x[valid], -np.log10(np.maximum(y, np.finfo(float).tiny)), color="#276d98")
    else:
        figure, axes = _plot("Multiple row comparisons", f"Mean difference ({labels[0]} − {labels[1]})", "")
        positions = np.flatnonzero(valid)
        axes.axvline(0, color="#a4b4c4", linewidth=1)
        axes.scatter(x[valid], positions, color="#276d98")
        low, high = table[["CI lower", "CI upper"]].to_numpy(dtype=float).T
        intervals = valid & np.isfinite(low) & np.isfinite(high)
        axes.hlines(np.flatnonzero(intervals), low[intervals], high[intervals], color="#276d98")
        step = max(1, (len(positions) + 24) // 25)
        axes.set_yticks(positions[::step], table.index[positions[::step]])
        axes.invert_yaxis()
    return figure


def row_tests(frame, options):
    input_format = _choice(options, "Input format", FORMATS)
    test = _choice(options, "Test", TESTS if input_format == RAW else TESTS[:2])
    correction = _choice(options, "Correction", CORRECTIONS)
    plot = _choice(options, "Graph", PLOTS)
    fdr = correction in FDR
    threshold = (_number_in_range(options, "False discovery rate (%)", 5., 100.) / 100 if fdr
                 else _number_in_range(options, "Family alpha", .05, 1.))
    level = (_number_in_range(options, "Confidence level (%)", 95., 100.)
             if test not in {MANN_WHITNEY, WILCOXON} else None)
    labels, (first, second), populated = _source(frame, options, input_format, test)
    row_label = options.get("Row labels") or next(
        (name for name in frame if name.casefold() in {"row title", "row titles"}), None)
    if row_label is not None and row_label not in frame:
        raise FieldError("Row labels", "Choose an existing row label column.")
    names = frame[row_label].astype("string").fillna("").tolist() if row_label else [""] * len(frame)
    populated |= np.asarray(names, dtype=bool)
    positions = np.flatnonzero(populated)
    if not 1 <= len(positions) <= _MAX_ROWS:
        raise FieldError("Input format", f"Use 1 to {_MAX_ROWS} populated worksheet rows.")
    evaluate = _raw_row if input_format == RAW else lambda a, b, t, l: _summary_row(a, b, input_format, t, l)
    records = [evaluate(first[i], second[i], test, level) for i in positions]
    index = pd.Index([names[i] or f"Row {i + 1}" for i in positions], name="Row")
    columns = ["N first", "N second", "Mean first", "Mean second", "Difference", "Statistic", "df", "p",
               "CI lower", "CI upper", "Status"]
    table = pd.DataFrame(records, index=index, columns=columns)
    table["Status"] = table["Status"].astype("string").fillna("Calculated")
    column = _multiplicity(table, correction, threshold)
    summary = {"First group": labels[0], "Second group": labels[1], "Input format": input_format,
               "Test": test, "Correction": correction, "Comparisons tested": int(table["p"].count()),
               "False discovery rate (%)" if fdr else "Family alpha": threshold * (100 if fdr else 1)}
    if level is not None:
        summary["Unadjusted interval level (%)"] = level
    return Result({"Row comparisons": table, "Settings": _report(summary)}, _graph(table, plot, column, labels))
