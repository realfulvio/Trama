"""Tolerance intervals and one-sided tolerance limits for several numeric columns and groups.

A tolerance interval is built to contain at least a proportion P of the population (the population coverage)
with confidence gamma. It is not a confidence interval of the mean: the mean interval narrows as the sample
grows, a tolerance interval keeps describing individual values.

Methods (one row per variable and group):

* Normal, Two-sided: Howe's approximation (NIST handbook 7.2.6.3),
  ``k2 = z((1+P)/2) * sqrt((n-1)(1+1/n) / chi2(1-gamma; n-1))``, limits ``mean +/- k2 * s``.
* Normal, Lower or Upper: the exact factor ``k1``, the gamma quantile of the noncentral t distribution
  (``n-1`` degrees of freedom, noncentrality ``z(P) * sqrt(n)``) divided by ``sqrt(n)``. The quantile is checked
  against the matching tail of the distribution; if the check fails the row says so and no limit is invented.
* Distribution-free, Two-sided: the largest rank ``r`` for which ``[x(r), x(n-r+1)]`` holds a proportion P with
  confidence at least gamma. The mass between the two order statistics is Beta(n-2r+1, 2r), so the confidence is
  its upper tail at P.
* Distribution-free, Lower or Upper: the largest ``r`` with ``Beta(n-r+1, r)`` upper tail at P of at least gamma,
  limit ``x(r)`` (Lower) or ``x(n-r+1)`` (Upper). ``r = 1`` gives the largest confidence reachable by the sample;
  when even that is below gamma the row reads "Insufficient sample" and carries that maximum.

The exact distribution-free statement assumes independent observations from a continuous population. Repeated
values (resolution, rounding) are reported in Settings.

Means and standard deviations come from values scaled by a power of two and a corrected two-pass sum, so a large
common shift or a very large or small unit neither overflows nor erases the spread. Tails are read from the
smaller side (``cdf`` or ``sf``), so confidence levels close to 0 or 100 keep their precision.
"""
import math
import warnings
from numbers import Real

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from scipy import special, stats

from .field_error import FieldError
from .presentation import GraphGroup, register_groups
from .reporting import Result, _report

TOLERANCE = "Tolerance intervals"
VARIABLES, GROUP, DISTRIBUTION, SIDES = "Variables", "Group", "Distribution", "Sides"
COVERAGE, CONFIDENCE, SHOW_GRAPH = "Population coverage (%)", "Confidence level (%)", "Show graph"
NORMAL, DISTRIBUTION_FREE = DISTRIBUTIONS = ("Normal", "Distribution-free")
TWO_SIDED, LOWER, UPPER = SIDE_CHOICES = ("Two-sided", "Lower", "Upper")
SETTINGS = "Settings"
# Role strings are the ones the workbench uses ("Multiple", "Optional"); the first choice is the default.
OPTIONS = {VARIABLES: "Multiple", GROUP: "Optional", DISTRIBUTION: DISTRIBUTIONS, SIDES: SIDE_CHOICES,
           COVERAGE: 90.0, CONFIDENCE: 95.0, SHOW_GRAPH: False}
DEFAULTS = {COVERAGE: 90.0, CONFIDENCE: 95.0, SHOW_GRAPH: False, DISTRIBUTION: NORMAL, SIDES: TWO_SIDED}

# Interface captions and choices; recipes keep the English field names and values.
TAB_KEYS = {"Data": "tolerance.tab.data", "Interval": "tolerance.tab.interval"}
LABEL_KEYS = {VARIABLES: "tolerance.field.variables", GROUP: "tolerance.field.group",
              DISTRIBUTION: "tolerance.field.distribution", SIDES: "tolerance.field.sides",
              COVERAGE: "tolerance.field.coverage", CONFIDENCE: "tolerance.field.confidence",
              SHOW_GRAPH: "tolerance.field.graph"}
CHOICE_KEYS = {NORMAL: "tolerance.choice.normal", DISTRIBUTION_FREE: "tolerance.choice.free",
               TWO_SIDED: "tolerance.choice.two_sided", LOWER: "tolerance.choice.lower",
               UPPER: "tolerance.choice.upper"}
HINT_KEY = "tolerance.hint"
ERROR_PREFIX = "tolerance.error."

OK, INSUFFICIENT, NO_VARIANCE, UNAVAILABLE = (
    "OK", "Insufficient sample", "Variance not measurable", "Calculation unavailable")
COLUMNS = ["Variable", "Group", "N", "Mean", "SD", "Lower", "Upper", "k factor", "Lower rank", "Upper rank",
           "Achieved confidence (%)", "Maximum confidence (%)", "Status"]

MAX_VARIABLES, MAX_GROUPS, MAX_PAIRS, MAX_OBSERVATIONS = 24, 48, 192, 100_000
GID_INTERVAL, GID_LIMIT = "tolerance-interval-", "tolerance-limit-"
# Tail check of the noncentral t quantile: relative error of the tail probability.
QUANTILE_TOLERANCE = 1e-7
LARGE, SMALL = 1e100, 1e-100
REPEATED_NOTE = ("The exact distribution-free statement assumes independent observations from a continuous "
                 "population. Repeated values, from resolution or rounding, make the stated confidence approximate.")
INTERPRETATION = ("The interval is built to contain at least the population coverage of all values, with the "
                  "stated confidence. It describes individual values, not the mean.")


class _Unavailable(Exception):
    """A number that cannot be computed reliably; the row says so and keeps its counts."""


# ----- options -------------------------------------------------------------------------------------------------------

def _percentage(options, name):
    value = options.get(name, DEFAULTS[name])
    message = f"{name} must be a finite number greater than 0 and less than 100."
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise FieldError(name, message)
    value = float(value)
    if not math.isfinite(value) or not 0 < value < 100:
        raise FieldError(name, message)
    if not 0 < value / 100 < 1:
        raise FieldError(name, message)
    return value


def _choice(options, name, choices, message):
    value = options.get(name, DEFAULTS[name])
    if not isinstance(value, str) or value not in choices:
        raise FieldError(name, message)
    return value


def _settings(options):
    distribution = _choice(options, DISTRIBUTION, DISTRIBUTIONS, "Distribution: choose Normal or Distribution-free.")
    sides = _choice(options, SIDES, SIDE_CHOICES, "Sides: choose Two-sided, Lower or Upper.")
    coverage = _percentage(options, COVERAGE)
    confidence = _percentage(options, CONFIDENCE)
    graph = options.get(SHOW_GRAPH, DEFAULTS[SHOW_GRAPH])
    if not isinstance(graph, (bool, np.bool_)):
        raise FieldError(SHOW_GRAPH, "Show graph: choose on or off.")
    return distribution, sides, coverage, confidence, bool(graph)


# ----- data ----------------------------------------------------------------------------------------------------------

def _blank(cells):
    """True for the cells that hold nothing: None, NaN, NA and text without characters."""
    return np.array([value is None or value is pd.NA or value is pd.NaT
                     or (isinstance(value, float) and np.isnan(value))
                     or (isinstance(value, str) and not value.strip()) for value in cells], dtype=bool)


def _column(frame, name, role):
    if not isinstance(name, str) or not name:
        raise FieldError(role, f"Choose a column for {role}.")
    if name not in frame:
        raise FieldError(role, f'Choose an existing column for {role}: "{name}" is not in the worksheet.')
    column = frame[name]
    if isinstance(column, pd.DataFrame):
        raise FieldError(role, "Worksheet column names must be unique.")
    return column


def _variable_names(frame, options):
    names = options.get(VARIABLES)
    if isinstance(names, str) or not isinstance(names, (list, tuple, np.ndarray, pd.Index)):
        raise FieldError(VARIABLES, f"Select at least one column for {VARIABLES}.")
    names = list(names)
    if not names:
        raise FieldError(VARIABLES, f"Select at least one column for {VARIABLES}.")
    if len(names) > MAX_VARIABLES:
        raise FieldError(VARIABLES, f"Choose up to {MAX_VARIABLES} columns for {VARIABLES}; {len(names)} selected.")
    if len(set(map(str, names))) != len(names):
        raise FieldError(VARIABLES, "Choose each variable once.")
    for name in names:
        _column(frame, name, VARIABLES)
    return names


def _group_name(frame, options, variables):
    name = options.get(GROUP)
    if name is None or (isinstance(name, str) and not name):
        return None
    _column(frame, name, GROUP)
    if name in variables:
        raise FieldError(GROUP, "Choose a Group column that is not one of the variables.")
    return name


def _label(value):
    if isinstance(value, (float, np.floating)) and float(value).is_integer() and abs(float(value)) < 1e15:
        return str(int(value))
    return str(value)


def _groups(frame, name):
    """(labels, codes, present): labels in order of first appearance, the group index of each row (-1 if none)."""
    cells = frame[name].to_numpy(dtype=object)
    present = ~_blank(cells)
    index, labels, codes = {}, [], np.full(len(cells), -1, dtype=np.int64)
    for position in np.flatnonzero(present):
        value = cells[position]
        if isinstance(value, np.generic):
            value = value.item()
        key = (isinstance(value, bool), value)
        code = index.get(key)
        if code is None:
            code = index[key] = len(labels)
            labels.append(_label(value))
            if len(labels) > MAX_GROUPS:
                raise FieldError(GROUP, f"Group has more than {MAX_GROUPS} groups; choose a column with fewer groups.")
        codes[position] = code
    if len(set(labels)) != len(labels):
        raise FieldError(GROUP, "Group labels must stay distinct when written as text.")
    return labels, codes, present


def _numeric(column, name, used, frame):
    """Float values of a variable and the cells that hold something; the ``used`` rows must hold finite numbers."""
    dtype = column.dtype
    if (pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype)
            and not pd.api.types.is_complex_dtype(dtype)):
        values = column.to_numpy(dtype=float, na_value=np.nan)
        filled = ~np.isnan(values)
    else:
        cells = column.to_numpy(dtype=object)
        filled = ~_blank(cells)
        values = np.full(len(cells), np.nan)
        for position in np.flatnonzero(filled & used):
            value = cells[position]
            if isinstance(value, (bool, np.bool_)):
                values[position] = np.inf
                continue
            try:
                values[position] = float(value.strip()) if isinstance(value, str) else float(value)
            except (TypeError, ValueError, OverflowError):
                values[position] = np.inf
    bad = used & filled & ~np.isfinite(values)
    if bad.any():
        row = frame.index[int(np.flatnonzero(bad)[0])]
        raise FieldError(VARIABLES, f'Column "{name}" must hold finite numbers. '
                                    f"Source row {row} is not a finite number.")
    return values, filled


def _check_budget(frame, variables, group_labels, used_rows):
    pairs = len(variables) * max(1, len(group_labels))
    if pairs > MAX_PAIRS:
        raise FieldError(GROUP if group_labels else VARIABLES,
                         f"The analysis needs {pairs} variable-group pairs; the limit is {MAX_PAIRS}.")
    for name in variables:
        count = int((frame[name].notna().to_numpy() & used_rows).sum())
        if count > MAX_OBSERVATIONS:
            raise FieldError(VARIABLES, f'Column "{name}" has {count:,} observations; '
                                        f"the limit is {MAX_OBSERVATIONS:,} per variable.")


# ----- statistics ----------------------------------------------------------------------------------------------------

def _exponent(values):
    """Binary exponent that brings the largest magnitude into [0.5, 1)."""
    peak = float(np.max(np.abs(values))) if len(values) else 0.0
    return int(np.frexp(peak)[1]) if peak > 0 else 0


def _unscale(value, exponent):
    with np.errstate(over="ignore", under="ignore"):
        return float(np.ldexp(value, exponent))


def _moments(values):
    """Scaled mean and SD with the exponent that scales them; the SD is zero when no spread is measurable."""
    exponent = _exponent(values)
    scaled = np.ldexp(values, -exponent)
    center = float(np.mean(scaled))
    delta = scaled - center
    correction = float(np.mean(delta))
    center += correction
    delta -= correction
    spread = math.sqrt(float(np.dot(delta, delta)) / (len(values) - 1)) if len(values) > 1 else float("nan")
    return center, spread, exponent


def _lower_tail_first(confidence):
    """True when the lower tail is the smaller one, so cdf rather than sf keeps the precision."""
    return confidence <= 50.0


def normal_two_sided_factor(n, coverage, confidence):
    """Howe's k2 for coverage and confidence in percent. Needs n >= 2."""
    if n < 2:
        raise _Unavailable("n")
    df = n - 1
    z = math.sqrt(2.0) * float(special.erfinv(coverage / 100.0))
    # chi-square critical value that is exceeded with probability gamma, read from the smaller tail.
    if _lower_tail_first(confidence):
        chi = float(stats.chi2.isf(confidence / 100.0, df))
    else:
        chi = float(stats.chi2.ppf((100.0 - confidence) / 100.0, df))
    factor = z * math.sqrt(df * (1.0 + 1.0 / n) / chi) if chi > 0 else float("nan")
    if not math.isfinite(factor):
        raise _Unavailable("k2")
    return factor


def normal_one_sided_factor(n, coverage, confidence):
    """Exact k1: the confidence quantile of the noncentral t distribution divided by sqrt(n). Needs n >= 2."""
    if n < 2:
        raise _Unavailable("n")
    df = n - 1
    root = math.sqrt(n)
    noncentrality = float(special.ndtri(coverage / 100.0)) * root
    gamma, rest = confidence / 100.0, (100.0 - confidence) / 100.0
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        quantile = float(stats.nct.ppf(gamma, df, noncentrality)) if _lower_tail_first(confidence) else float(
            stats.nct.isf(rest, df, noncentrality))
        if not math.isfinite(quantile):
            raise _Unavailable("quantile")
        # The returned quantile must reproduce the requested tail.
        if _lower_tail_first(confidence):
            tail, wanted = float(stats.nct.cdf(quantile, df, noncentrality)), gamma
        else:
            tail, wanted = float(stats.nct.sf(quantile, df, noncentrality)), rest
    if not math.isfinite(tail) or abs(tail - wanted) > QUANTILE_TOLERANCE * wanted:
        raise _Unavailable("tail")
    return quantile / root


def _shape(n, rank, two_sided):
    return (n - 2 * rank + 1, 2 * rank) if two_sided else (n - rank + 1, rank)


def rank_confidence(n, rank, coverage, two_sided):
    """Confidence (as a probability) that the order statistics of rank ``rank`` hold at least P of the population."""
    a, b = _shape(n, rank, two_sided)
    return float(special.betaincc(a, b, coverage / 100.0))


def _rank_meets(n, rank, coverage, confidence, two_sided):
    a, b = _shape(n, rank, two_sided)
    p = coverage / 100.0
    if _lower_tail_first(confidence):
        return float(special.betaincc(a, b, p)) >= confidence / 100.0
    # High confidence: compare the small failure probability, not two numbers that are both close to 1.
    return float(special.betainc(a, b, p)) <= (100.0 - confidence) / 100.0


def distribution_free_rank(n, coverage, confidence, two_sided):
    """Largest rank r with confidence at least the requested one, or None, plus the maximum confidence (r = 1).

    The confidence decreases as r grows, so the largest admissible r is found by bisection.
    """
    limit = n // 2 if two_sided else n
    if limit < 1:
        return None, float("nan")
    maximum = rank_confidence(n, 1, coverage, two_sided)
    if not _rank_meets(n, 1, coverage, confidence, two_sided):
        return None, maximum
    low, high = 1, limit
    while low < high:
        middle = (low + high + 1) // 2
        if _rank_meets(n, middle, coverage, confidence, two_sided):
            low = middle
        else:
            high = middle - 1
    return low, maximum


# ----- one sample ----------------------------------------------------------------------------------------------------

def _blank_row(variable, group, n):
    row = dict.fromkeys(COLUMNS)
    row.update({"Variable": variable, "Group": group, "N": int(n)})
    for name in ("Mean", "SD", "Lower", "Upper", "k factor", "Achieved confidence (%)", "Maximum confidence (%)"):
        row[name] = np.nan
    return row


def _normal_row(row, values, sides, coverage, confidence):
    n = len(values)
    if n < 2:
        row["Status"] = INSUFFICIENT
        if n == 1:
            row["Mean"] = float(values[0])
        return
    center, spread, exponent = _moments(values)
    mean, sd = _unscale(center, exponent), _unscale(spread, exponent)
    row["Mean"] = mean if math.isfinite(mean) else np.nan
    row["SD"] = sd if math.isfinite(sd) else np.nan
    if not math.isfinite(sd):
        row["Status"] = UNAVAILABLE
        return
    try:
        factor = (normal_two_sided_factor if sides == TWO_SIDED else normal_one_sided_factor)(n, coverage, confidence)
    except _Unavailable:
        row["Status"] = UNAVAILABLE
        return
    row["k factor"] = factor
    if spread == 0:
        row["Status"] = NO_VARIANCE
        return
    lower = _unscale(center - factor * spread, exponent) if sides != UPPER else None
    upper = _unscale(center + factor * spread, exponent) if sides != LOWER else None
    if any(limit is not None and not math.isfinite(limit) for limit in (lower, upper)):
        row["Status"] = UNAVAILABLE
        return
    row["Lower"] = np.nan if lower is None else lower
    row["Upper"] = np.nan if upper is None else upper
    row["Status"] = OK


def _free_row(row, values, sides, coverage, confidence):
    n = len(values)
    two_sided = sides == TWO_SIDED
    if n:
        center, spread, exponent = _moments(values) if n > 1 else (float(values[0]), np.nan, 0)
        row["Mean"] = _unscale(center, exponent)
        if n > 1:
            row["SD"] = _unscale(spread, exponent)
    rank, maximum = distribution_free_rank(n, coverage, confidence, two_sided)
    row["Maximum confidence (%)"] = 100.0 * maximum if not np.isnan(maximum) else np.nan
    if rank is None:
        row["Status"] = INSUFFICIENT
        return
    ordered = np.sort(values)
    lower_rank, upper_rank = (rank, n - rank + 1) if two_sided else (
        (rank, None) if sides == LOWER else (None, n - rank + 1))
    row["Lower rank"], row["Upper rank"] = lower_rank, upper_rank
    if lower_rank is not None:
        row["Lower"] = float(ordered[lower_rank - 1])
    if upper_rank is not None:
        row["Upper"] = float(ordered[upper_rank - 1])
    row["Achieved confidence (%)"] = 100.0 * rank_confidence(n, rank, coverage, two_sided)
    row["Status"] = OK


def _repeated(values):
    if len(values) < 2:
        return False
    ordered = np.sort(values)
    return bool(np.any(ordered[1:] == ordered[:-1]))


# ----- analysis ------------------------------------------------------------------------------------------------------

def check_options(frame, options):
    """Validate the selected fields before iterating over the observations."""
    settings = _settings(options)
    variables = _variable_names(frame, options)
    group = _group_name(frame, options, variables)
    return settings, variables, group


def tolerance_intervals(frame, options):
    (distribution, sides, coverage, confidence, graph), variables, group = check_options(frame, options)
    labels, codes, present = _groups(frame, group) if group else ([None], np.zeros(len(frame), np.int64), None)
    grouped = group is not None
    if present is None:
        present = np.ones(len(frame), dtype=bool)
    _check_budget(frame, variables, labels if grouped else [], present)
    rows, repeated = [], []
    missing_values, no_group = {}, 0
    carried = np.zeros(len(frame), dtype=bool)
    for name in variables:
        column = _column(frame, name, VARIABLES)
        values, filled = _numeric(column, name, present, frame)
        carried |= filled
        usable = filled & present
        missing_values[name] = int(present.sum() - usable.sum())
        for code, label in enumerate(labels):
            chosen = values[usable & (codes == code)] if grouped else values[usable]
            row = _blank_row(name, label, len(chosen))
            if distribution == NORMAL:
                _normal_row(row, chosen, sides, coverage, confidence)
            else:
                _free_row(row, chosen, sides, coverage, confidence)
                if _repeated(chosen):
                    repeated.append(name if label is None else f"{name} ({label})")
            rows.append(row)
    if grouped:
        no_group = int((~present & carried).sum())
    table = _table(rows)
    tables = {TOLERANCE: table, SETTINGS: _settings_table(distribution, sides, coverage, confidence, variables,
                                                          group, no_group, missing_values, repeated)}
    figure = _figure(rows, variables, labels, group, distribution, sides, coverage, confidence) if graph else None
    return Result(tables, figure)


def _table(rows):
    table = pd.DataFrame(rows, columns=COLUMNS)
    for name in ("Lower rank", "Upper rank"):
        # Ranks are whole numbers; an inapplicable rank is an empty cell, never 0 or NaN.
        table[name] = pd.Series([row[name] for row in rows], dtype=object)
    table["Group"] = pd.Series([row["Group"] for row in rows], dtype=object)
    return table


def _method_text(distribution, sides):
    if distribution == NORMAL:
        if sides == TWO_SIDED:
            return ("Normal two-sided interval, Howe approximation",
                    "k2 = z((1+P)/2) · √[(n−1)(1+1/n) / χ²(1−γ; n−1)]; limits mean ± k2·s")
        return ("Normal one-sided limit, exact factor",
                "k1 = quantile γ of the noncentral t distribution (n−1 df, noncentrality z(P)·√n) / √n; "
                "Lower = mean − k1·s, Upper = mean + k1·s")
    if sides == TWO_SIDED:
        return ("Distribution-free interval, order statistics",
                "largest r with P(Beta(n−2r+1, 2r) ≥ P) ≥ γ; limits x(r) and x(n−r+1)")
    return ("Distribution-free limit, order statistic",
            "largest r with P(Beta(n−r+1, r) ≥ P) ≥ γ; Lower = x(r), Upper = x(n−r+1)")


def _settings_table(distribution, sides, coverage, confidence, variables, group, no_group, missing, repeated):
    method, factor = _method_text(distribution, sides)
    values = {"Method": method, "Factor": factor, "Distribution": distribution, "Sides": sides,
              "Population coverage (%)": coverage, "Confidence level (%)": confidence,
              "Variables": ", ".join(variables), "Group": group if group else "None",
              "Interpretation": INTERPRETATION}
    if group:
        values["Rows without a group (omitted)"] = no_group
    for name in variables:
        values[f"Missing values omitted ({name})"] = missing[name]
    if repeated:
        shown = ", ".join(repeated[:5]) + (" …" if len(repeated) > 5 else "")
        values["Repeated values"] = f"{len(repeated)} sample(s): {shown}. {REPEATED_NOTE}"
    return _report(values)


# ----- figure --------------------------------------------------------------------------------------------------------

COLORS = ("#1b6e8f", "#c2571a", "#2f7d4f", "#8a4f9e", "#b8860b", "#5b6770", "#a3324a", "#3d8c8c")
MUTED = "#5b6770"


def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def _display_exponent(values):
    """Exponent that keeps drawn coordinates in a safe range, or 0 when the values are ordinary."""
    finite = np.array([abs(v) for v in values if math.isfinite(v) and v != 0.0])
    if not len(finite):
        return 0
    return _exponent(finite) if finite.max() > LARGE or finite.min() < SMALL else 0


def _figure(rows, variables, labels, group, distribution, sides, coverage, confidence):
    panels, rows_per_panel = len(variables), len(labels)
    columns = 1 if panels == 1 else 2 if panels <= 4 else 3
    grid_rows = math.ceil(panels / columns)
    figure = Figure(figsize=(max(5.6, 4.8 * columns), max(2.8, (0.55 * rows_per_panel + 1.5)) * grid_rows),
                    dpi=100, layout="constrained")
    unit = "" if sides == TWO_SIDED else f", {sides.lower()} limit"
    _plain(figure.suptitle(f"{TOLERANCE} · {distribution}{unit} · {coverage:g}% of the population · "
                           f"{confidence:g}% confidence", fontsize=11))
    axes_list, groups = [], {}
    sequence = 0
    for index, name in enumerate(variables):
        axes = figure.add_subplot(grid_rows, columns, index + 1)
        axes_list.append(axes)
        part = rows[index * rows_per_panel:(index + 1) * rows_per_panel]
        coordinates = [row[key] for row in part if row["Status"] == OK for key in ("Lower", "Upper")]
        exponent = _display_exponent(coordinates)
        shown = lambda value: float(np.ldexp(value, -exponent)) if exponent else value  # noqa: E731
        axes.set_title(name, fontsize=10)
        axes.set_xlabel("Value" + (f" · displayed values × 2^{exponent}" if exponent else ""))
        axes.set_ylabel(group or "")
        axes.spines[["right", "top"]].set_visible(False)
        axes._tramastat_numeric_axes = ("x",)
        axes._tramastat_categorical_axes = ("y",)
        _plain(axes.title, axes.xaxis.label, axes.yaxis.label)
        axes.set_ylim(rows_per_panel - 0.5, -0.5)
        if group is None:
            axes.set_yticks([])
        else:
            axes.set_yticks(range(rows_per_panel), [str(label) for label in labels])
        for label in axes.get_yticklabels():
            label.set_parse_math(False)
        axes.grid(axis="x", color="#e4e8ec", linewidth=0.8)
        axes.set_axisbelow(True)
        finite = []
        for position, row in enumerate(part):
            color = COLORS[position % len(COLORS)] if group else COLORS[index % len(COLORS)]
            key = labels[position] if group else name
            if row["Status"] != OK:
                _plain(axes.text(0.5, position, row["Status"], transform=axes.get_yaxis_transform(), ha="center",
                                 va="center", fontsize=8.5, style="italic", color=MUTED))
                continue
            sequence += 1
            if sides == TWO_SIDED:
                x = [shown(row["Lower"]), shown(row["Upper"])]
                line, = axes.plot(x, [position, position], color=color, linewidth=3.4, solid_capstyle="butt",
                                  marker="|", markersize=12, markeredgewidth=2.4, gid=f"{GID_INTERVAL}{sequence}")
            else:
                limit = shown(row["Lower"] if sides == LOWER else row["Upper"])
                x = [limit]
                line, = axes.plot(x, [position], color=color, linestyle="none", marker=">" if sides == LOWER else "<",
                                  markersize=11, gid=f"{GID_LIMIT}{sequence}")
            finite.extend(x)
            groups.setdefault((key, color), []).append((line, "line"))
        if finite:
            low, high = min(finite), max(finite)
            pad = 0.1 * (high - low) if high > low else max(0.05 * abs(high), 1.0)
            axes.set_xlim(low - pad, high + pad)
        else:
            axes.set_xlim(0, 1)
            axes.set_xticks([])
    register_groups(axes_list[0], [GraphGroup(f"tolerance:{key}", str(key), "line", float(i), artists)
                                   for i, ((key, _), artists) in enumerate(groups.items())
                                   if len(f"tolerance:{key}") <= 1024])
    return figure
