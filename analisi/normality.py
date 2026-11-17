"""Normality tests per column and the normal Q–Q plot.

The four tests estimate the mean and standard deviation from the same column:

* Shapiro–Wilk (``scipy.stats.shapiro``), 3 to 5000 values.
* D'Agostino–Pearson K² (``scipy.stats.normaltest``), from 8 values.
* Anderson–Darling A² (``statsmodels.stats.diagnostic.normal_ad``), from 8 values. Its p value comes from an
  approximation for estimated parameters.
* Kolmogorov–Smirnov with Lilliefors' correction (``lilliefors(..., dist="norm", pvalmethod="table")``), from 5
  values. Its p value is interpolated in a simulated table and clipped to 0.001 and 0.990. The p value of the plain
  Kolmogorov–Smirnov test is never used because it assumes known parameters.

A test outside its domain gives a row with the reason. The other tests and columns still run.
"""
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import lilliefors, normal_ad

from .processing import FieldError, _column
from .qq_panels import LOGNORMAL_PANEL, NORMAL_PANEL, PANEL_ATTR, POINTS_ATTR, REFERENCE_ATTR
from .reporting import Result, _plot, _report
from .lognormality import (DISTRIBUTION, DISTRIBUTIONS, COMPARE, LOG_TESTS, COMPARISON, LOG_QQ, LOG_SETTINGS,
                           centered_logs, compare_distributions)

NORMALITY = "Normality tests"
SHAPIRO, DAGOSTINO, ANDERSON, LILLIEFORS = TESTS = (
    "Shapiro–Wilk", "D’Agostino–Pearson", "Anderson–Darling", "Kolmogorov–Smirnov (Lilliefors)")
ALPHA, QQ_PLOT, QQ_VARIABLE, QQ_LINE = "Alpha", "Q–Q plot", "Q–Q variable", "Q–Q reference line"
# Role strings are the ones the workbench uses ("Multiple", "Optional").
OPTIONS = {"Variables": "Multiple", DISTRIBUTION: DISTRIBUTIONS, COMPARE: False, SHAPIRO: True, DAGOSTINO: False, ANDERSON: False, LILLIEFORS: False,
           ALPHA: 0.05, QQ_PLOT: False, QQ_VARIABLE: "Optional", QQ_LINE: True}
LEGACY_OPTIONS = frozenset({"Variables"})
QQ_SHEET, QQ_SETTINGS = "Q–Q coordinates", "Q–Q settings"
SYMBOLS = {SHAPIRO: "W", DAGOSTINO: "K²", ANDERSON: "A²", LILLIEFORS: "D"}
DOMAINS = {SHAPIRO: (3, 5000), DAGOSTINO: (8, None), ANDERSON: (8, None), LILLIEFORS: (5, None)}
MAX_QQ_POINTS = 60_000
EXTREME = 1e100
LILLIEFORS_BOUNDS = (0.001, 0.990)
ANDERSON_ZERO_BOUND = 5e-31
MINIMUM_FOR_QQ = 3


def is_legacy(options):
    """Recipes saved before the test choices existed carry only their variables."""
    return set(options) <= LEGACY_OPTIONS


def visibility(show_qq):
    """Dialog fields that apply to the Q–Q plot."""
    return {QQ_VARIABLE: bool(show_qq), QQ_LINE: bool(show_qq)}


def _flag(options, name):
    value = options.get(name, OPTIONS[name])
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name}: choose on or off.")
    return bool(value)


def _alpha(options):
    value = options.get(ALPHA, OPTIONS[ALPHA])
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(ALPHA, "Alpha must be a number between 0 and 1.")
    value = float(value)
    if not np.isfinite(value) or not 0 < value < 1:
        raise FieldError(ALPHA, "Alpha must be a finite number greater than 0 and less than 1.")
    return value


def _variables(frame, options):
    names = options.get("Variables")
    if not isinstance(names, (list, tuple)) or not names:
        raise FieldError("Variables", "Select at least one column for Variables.")
    if any(not isinstance(name, str) or name not in frame for name in names) or len(set(names)) != len(names):
        raise FieldError("Variables", "Choose distinct existing columns for Variables.")
    if not frame.columns.is_unique:
        raise FieldError("Variables", "Worksheet column names must be unique.")
    return list(names)


def _qq_variable(options, names):
    if not _flag(options, QQ_PLOT):
        return None
    chosen = options.get(QQ_VARIABLE) or None
    if chosen is None:
        if len(names) != 1:
            raise FieldError(QQ_VARIABLE, "Choose the variable for the Q–Q plot.")
        return names[0]
    if not isinstance(chosen, str) or chosen not in names:
        raise FieldError(QQ_VARIABLE, "Choose a Q–Q variable among the selected variables.")
    return chosen


def check_options(frame, options):
    """Validate everything that does not need the observations. Raises FieldError naming the field."""
    names = _variables(frame, options)
    _alpha(options)
    distribution = options.get(DISTRIBUTION, "Normal")
    if distribution not in DISTRIBUTIONS:
        raise FieldError(DISTRIBUTION, "Choose Normal, Lognormal or Both.")
    _flag(options, COMPARE)
    if not any(_flag(options, test) for test in TESTS):
        raise FieldError(SHAPIRO, "Choose at least one normality test.")
    _flag(options, QQ_LINE)
    chosen = _qq_variable(options, names)
    if chosen is not None and distribution != "Normal":
        values, _ = _observations(frame, chosen, QQ_VARIABLE)
        if np.any(values <= 0):
            raise FieldError(QQ_VARIABLE, "Lognormal Q–Q requires strictly positive values in the selected variable.")


def _observations(frame, name, field):
    """Finite numeric values of a column and their 1-based worksheet rows."""
    numbers = _column(frame, name, field).to_numpy(dtype=float)
    keep = np.isfinite(numbers)
    return numbers[keep], np.flatnonzero(keep) + 1


def _scaled(values):
    """Values centered and divided by their largest magnitude so no product overflows or underflows."""
    scale = np.max(np.abs(values))
    scaled = values / scale
    return scaled - scaled.mean()


def _extreme(values):
    largest = np.max(np.abs(values))
    return largest > EXTREME or largest < 1 / EXTREME


def _evaluate(test, values):
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        if test == SHAPIRO:
            result = stats.shapiro(values)
            return float(result.statistic), float(result.pvalue)
        if test == DAGOSTINO:
            result = stats.normaltest(values)
            return float(result.statistic), float(result.pvalue)
        if test == ANDERSON:
            statistic, p = normal_ad(values)
            return float(statistic), float(p)
        statistic, p = lilliefors(values, dist="norm", pvalmethod="table")
        return float(statistic), float(p)


def _compute(test, values):
    """Statistic, p and whether the values had to be rescaled. The tests ignore location and scale."""
    rescaled = _extreme(values)
    for attempt in (rescaled, True):
        sample = _scaled(values) if attempt else values
        try:
            statistic, p = _evaluate(test, sample)
        except (ArithmeticError, ValueError):
            continue
        if np.isfinite(statistic) and np.isfinite(p):
            return statistic, p, attempt
        if attempt:
            break
    return None


def _method_note(test, n, p):
    notes = []
    if test == DAGOSTINO and n < 20:
        notes.append("The kurtosis component is only approximate below 20 values.")
    if test == ANDERSON:
        notes.append("Approximate p value for estimated mean and SD.")
        if p == 0:
            notes.append(f"The adjusted A² exceeds 13. The approximate p is below {ANDERSON_ZERO_BOUND:g} and is shown as 0.")
    if test == LILLIEFORS:
        notes.append("Tabulated p value for estimated mean and SD, interpolated in a simulated table.")
        low, high = LILLIEFORS_BOUNDS
        if p <= low:
            notes.append(f"The table ends at p = {low}: the true p can be smaller.")
        elif p >= high:
            notes.append(f"The table ends at p = {high}: the true p can be larger.")
    return " ".join(notes)


def _row(name, test, n, statistic, p, decision, note):
    return {"Variable": name, "Test": test, "N": n, "Statistic name": SYMBOLS[test], "Statistic": statistic,
            "p": p, "Decision": decision, "Note": note}


def _skipped(name, test, n, reason):
    return _row(name, test, n, np.nan, np.nan, "Not tested", reason)


def _column_rows(name, values, tests, alpha):
    n = len(values)
    constant = n > 0 and values.min() == values.max()
    rows = []
    for test in tests:
        low, high = DOMAINS[test]
        if n == 0:
            rows.append(_skipped(name, test, n, "No numeric observations."))
        elif n < low:
            rows.append(_skipped(name, test, n, f"{test} needs at least {low} values."))
        elif high is not None and n > high:
            rows.append(_skipped(name, test, n, f"{test} is limited to {low} to {high} values."))
        elif constant:
            rows.append(_skipped(name, test, n, "All values are identical, so the variance is zero."))
        else:
            computed = _compute(test, values)
            if computed is None:
                rows.append(_skipped(name, test, n, "The values are too extreme for a finite result."))
                continue
            statistic, p, rescaled = computed
            note = _method_note(test, n, p)
            if rescaled:
                note = (note + " " if note else "") + "Values were rescaled before testing to avoid overflow or underflow."
            low, high = LILLIEFORS_BOUNDS
            unresolved = (test == LILLIEFORS and ((p <= low and alpha <= low) or (p >= high and alpha > high))
                          or test == ANDERSON and p == 0 and alpha <= ANDERSON_ZERO_BOUND)
            if unresolved:
                decision = "Inconclusive at reported p limit"
            else:
                decision = "Reject normality" if p < alpha else "Do not reject normality"
            rows.append(_row(name, test, n, statistic, p, decision, note))
    return rows


def _mean_sd(values):
    """Sample mean and SD (N − 1). Extreme magnitudes are rescaled first."""
    if not _extreme(values):
        with np.errstate(all="ignore"):
            mean, sd = float(np.mean(values)), float(np.std(values, ddof=1))
        if np.isfinite(mean) and np.isfinite(sd):
            return mean, sd
    scale = np.max(np.abs(values))
    scaled = values / scale
    return float(scale * scaled.mean()), float(scale * scaled.std(ddof=1))


def qq_coordinates(values, rows):
    """Order statistics, their worksheet rows and the standard normal quantiles at (i − 0.5) / N."""
    order = np.argsort(values, kind="stable")
    n = len(values)
    positions = (np.arange(1, n + 1) - 0.5) / n
    return pd.DataFrame({"Rank": np.arange(1, n + 1), "Source row": rows[order], "Observed value": values[order],
                         "Plotting position": positions, "Theoretical quantile": stats.norm.ppf(positions)})


def _qq(frame, name, show_line, *, axes=None):
    values, rows = _observations(frame, name, QQ_VARIABLE)
    n = len(values)
    if n < MINIMUM_FOR_QQ:
        raise FieldError(QQ_VARIABLE, f"The Q–Q plot needs at least {MINIMUM_FOR_QQ} numeric values in {name}.")
    if n > MAX_QQ_POINTS:
        raise FieldError(QQ_VARIABLE, "Select a column with fewer observations for the Q–Q plot.")
    table = qq_coordinates(values, rows)
    mean, sd = _mean_sd(values)
    drawn = show_line and np.isfinite(mean) and np.isfinite(sd) and sd > 0
    compact_reference = axes is not None
    if axes is None:
        figure, axes = _plot(f"Normal Q–Q plot: {name}", "Theoretical normal quantile", f"Observed value ({name})")
    else:
        figure = axes.figure
        axes.set_title(f"Normal Q–Q plot: {name}")
        axes.set_xlabel("Theoretical normal quantile")
        axes.set_ylabel(f"Observed value ({name})")
        axes.spines[["right", "top"]].set_visible(False)
    setattr(axes, PANEL_ATTR, NORMAL_PANEL)
    axes.title.set_parse_math(False)
    axes.xaxis.label.set_parse_math(False)
    axes.yaxis.label.set_parse_math(False)
    points_artist = axes.scatter(table["Theoretical quantile"], table["Observed value"], s=26, color="#2866ae",
                                 edgecolors="white", linewidths=.6, zorder=3, label="Observed values")
    reference_artist = (
        axes.axline((0, mean), slope=sd, color="#bc4040", linewidth=1.5, zorder=2,
                    label="Fitted reference" if compact_reference else
                    f"Fitted normal: mean {mean:.6g} + SD {sd:.6g} × quantile")
        if drawn else None
    )
    setattr(axes, POINTS_ATTR, points_artist)
    setattr(axes, REFERENCE_ATTR, reference_artist)
    if show_line:
        axes.legend(loc="upper left", frameon=False)
        for text in axes.get_legend().get_texts():
            text.set_parse_math(False)
    settings = {"Variable": name, "N": n,
                "Plotting positions": "(i − 0.5) / N, with i = 1 to N",
                "Theoretical quantiles": "Standard normal quantile function at each plotting position",
                "Order": "Ascending observed values; ties keep the worksheet order of their source rows",
                "Reference line": "Mean + sample SD × quantile (fitted normal)" if drawn else
                "Not drawn" if not show_line else "Not drawn: the variance is zero or not finite",
                "Mean": mean, "SD (N − 1)": sd, "Bands": "No simulated band"}
    return table, _report(settings), figure


def normality(frame, options):
    """Run the chosen tests on every selected column and, optionally, draw one Q–Q plot."""
    check_options(frame, options)
    names, alpha = _variables(frame, options), _alpha(options)
    tests = [test for test in TESTS if _flag(options, test)]
    distribution = options.get(DISTRIBUTION, "Normal")
    normal_rows, log_rows, comparisons = [], [], []
    for name in names:
        values, _ = _observations(frame, name, "Variables")
        if distribution in ("Normal", "Both"):
            normal_rows.extend(_column_rows(name, values, tests, alpha))
        if distribution in ("Lognormal", "Both"):
            if len(values) and np.any(values <= 0):
                log_rows.extend(_skipped(name, test, len(values),
                    "Lognormal distributions require strictly positive observations; no values were discarded.") for test in tests)
            else:
                logs = centered_logs(values)[0] if len(values) else values
                entries = _column_rows(name, logs, tests, alpha)
                for entry in entries:
                    entry["Decision"] = entry["Decision"].replace("normality", "lognormality")
                    entry["Note"] = (entry["Note"]+" " if entry["Note"] else "") + "Tests use centered natural logarithms."
                log_rows.extend(entries)
        if _flag(options, COMPARE):
            comparison = compare_distributions(values)
            comparison.insert(0, "Variable", name)
            comparisons.append(comparison)
    tables = {}
    if distribution in ("Normal", "Both"):
        tables[NORMALITY] = pd.DataFrame(normal_rows)
    if distribution in ("Lognormal", "Both"):
        tables[LOG_TESTS] = pd.DataFrame(log_rows)
    if comparisons:
        tables[COMPARISON] = pd.concat(comparisons, ignore_index=True)
    figure = None
    chosen = _qq_variable(options, names)
    if chosen is not None:
        axes = (None, None)
        if distribution == "Both":
            figure, _ = _plot("Normal and lognormal Q–Q plots")
            figure.clear()
            figure.set_size_inches(11, 4.8)
            axes = figure.subplots(1, 2)
        if distribution in ("Normal", "Both"):
            coordinates, settings, figure = _qq(frame, chosen, _flag(options, QQ_LINE), axes=axes[0])
            tables[QQ_SHEET], tables[QQ_SETTINGS] = coordinates, settings
        if distribution in ("Lognormal", "Both"):
            coordinates, settings, figure = _log_qq(frame, chosen, _flag(options, QQ_LINE), axes=axes[1])
            tables[LOG_QQ], tables[LOG_SETTINGS] = coordinates, settings
    return Result(tables, figure)


def _log_qq(frame, name, show_line, *, axes=None):
    values, source_rows = _observations(frame, name, QQ_VARIABLE)
    if not len(values):
        raise FieldError(QQ_VARIABLE, "Choose at least three positive observations for a lognormal Q–Q plot.")
    logs, offset = centered_logs(values)
    transformed = np.full(len(frame), np.nan)
    transformed[source_rows-1] = logs
    table, settings, figure = _qq(pd.DataFrame({name:transformed}), name, show_line, axes=axes)
    table["Observed source value"] = frame[name].to_numpy()[table["Source row"].to_numpy()-1]
    table["Natural log value"] = table["Observed value"]+offset
    settings.loc["Log offset", "Value"] = offset
    settings.loc["Observed values", "Value"] = "ln(value) - log offset; centering preserves very small variation."
    target = axes if axes is not None else figure.axes[0]
    setattr(target, PANEL_ATTR, LOGNORMAL_PANEL)
    target.set_title(f"Lognormal Q–Q plot: {name}")
    target.set_ylabel(f"Centered ln(value) ({name})")
    target.title.set_parse_math(False)
    target.xaxis.label.set_parse_math(False)
    target.yaxis.label.set_parse_math(False)
    return table, settings, figure
