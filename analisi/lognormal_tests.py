"""Lognormal t-tests and geometric-mean ratios for positive data.

Paired, Welch, Student and One-sample t-tests on the logarithms of positive observations,
reported back as a ratio of geometric means with its confidence interval.

* Log ratios use bounded binary mantissas and exponent differences: the direct observation ratio
  can leave the floating-point range even when every input is finite. Sample spreads use relative
  logs before adding the common offset, so changing measurement units cannot erase variability.
  The observations table still reports the ordinary logarithms of the unchanged input values.
* Paired uses the complete pairs (both cells present) before positivity is checked. Welch and Student
  drop the missing cells of each column separately. One-sample compares log(First) with log(reference).
* Report ratio only flips the sign of the log ratio and of t. Null ratio moves the test
  (t = (log ratio − log null) / SE), never the estimate or its two-sided interval.
* The internal logarithm is natural. Mean/SE log ratio and the log limits are divided by ln(base);
  the ratio, its interval, t, df and P do not depend on the base.
* An exponential that overflows or underflows is left missing (Status = "Ratio overflow") while the logs
  and the inference stay finite. A standard error of zero keeps the estimate and reports
  Status = "Inference unavailable"; the zero tests allow for rounding in the relative log ratios
  (see ``_noise``), so ratios that are constant up to floating-point noise are degenerate too.
"""
from numbers import Real

import numpy as np
import pandas as pd
from scipy import stats

from .category_graphs import COLORS
from .field_error import FieldError
from .reporting import Result, _plot, _report
from .variance_ratio import SHOW as VARIANCE_SHOW, attach_lognormal

LOGNORMAL = "Lognormal t-test"
DESIGN = "Design"
PAIRED, WELCH, STUDENT, ONE_SAMPLE = DESIGNS = ("Paired", "Welch", "Student", "One-sample")
FIRST, SECOND = "First", "Second"
REPORT_RATIO = "Report ratio"
FIRST_OVER_SECOND, SECOND_OVER_FIRST = ORIENTATIONS = ("First / Second", "Second / First")
NULL_RATIO = "Null ratio"
REFERENCE = "Hypothetical geometric mean"
LEVEL = "Confidence level (%)"
ALTERNATIVE = "Alternative"
TWO_SIDED, GREATER, LESS = ALTERNATIVES = ("Two-sided", "Greater", "Less")
LOG_BASE = "Log base"
BASE_10, BASE_E = LOG_BASES = ("10", "e")
GRAPH = "Graph"
RATIO_ESTIMATION, LOG_OBSERVATIONS, LOG_RATIOS, NO_GRAPH = GRAPHS = (
    "Ratio estimation", "Log observations", "Log ratios", "None")
PAIRING = "Pairing correlation"

# The first entry of each choice is its default in the dialog.
OPTIONS = {DESIGN: DESIGNS, FIRST: None, SECOND: None, REPORT_RATIO: ORIENTATIONS, NULL_RATIO: 1.0,
           REFERENCE: 1.0, LEVEL: 95.0, ALTERNATIVE: ALTERNATIVES, LOG_BASE: LOG_BASES, GRAPH: GRAPHS,
           PAIRING: True, VARIANCE_SHOW: False}
# Fields that belong on the Data tab; the others sit on the Test and graph tab.
DATA_FIELDS = (DESIGN, FIRST, SECOND, REPORT_RATIO, REFERENCE)

TEST_SHEET, OBSERVATIONS_SHEET, RATIOS_SHEET, SETTINGS_SHEET = (
    "Lognormal test", "Log observations", "Paired ratios", "Settings")
OK, UNAVAILABLE, OVERFLOW = "OK", "Inference unavailable", "Ratio overflow"
RESULT_COLUMNS = ["N first", "N second", "Mean log ratio", "SE log ratio", "Log lower", "Log upper", "t", "df", "p",
                  "Geometric ratio", "Lower", "Upper", "Status", "Reason"]
GID = "lognormal:"

# Interface captions and choice labels. Recipes keep the English field names and values.
TAB_KEYS = {"Data": "ratio_t.tab.data", "Test and graph": "ratio_t.tab.test"}
LABEL_KEYS = {DESIGN: "ratio_t.field.design", FIRST: "ratio_t.field.first", SECOND: "ratio_t.field.second",
              REPORT_RATIO: "ratio_t.field.report", NULL_RATIO: "ratio_t.field.null", REFERENCE: "ratio_t.field.reference",
              LEVEL: "ratio_t.field.level", ALTERNATIVE: "ratio_t.field.alternative", LOG_BASE: "ratio_t.field.base",
              GRAPH: "ratio_t.field.graph", PAIRING: "ratio_t.field.pairing"}
CHOICE_KEYS = {PAIRED: "ratio_t.choice.paired", WELCH: "ratio_t.choice.welch", STUDENT: "ratio_t.choice.student",
               ONE_SAMPLE: "ratio_t.choice.one_sample", FIRST_OVER_SECOND: "ratio_t.choice.first_second",
               SECOND_OVER_FIRST: "ratio_t.choice.second_first", TWO_SIDED: "ratio_t.choice.two_sided",
               GREATER: "ratio_t.choice.greater", LESS: "ratio_t.choice.less", BASE_E: "ratio_t.choice.natural",
               RATIO_ESTIMATION: "ratio_t.choice.estimation", LOG_OBSERVATIONS: "ratio_t.choice.observations",
               LOG_RATIOS: "ratio_t.choice.ratios", NO_GRAPH: "ratio_t.choice.none"}

_EPS = np.finfo(float).eps


def visibility(design):
    """Fields that apply to the chosen design; the others are inactive and never validated."""
    return {SECOND: design != ONE_SAMPLE, REFERENCE: design == ONE_SAMPLE, PAIRING: design == PAIRED,
            VARIANCE_SHOW: design in (WELCH, STUDENT)}


# ----- options -------------------------------------------------------------------------------------------------------

def _choice(options, name, choices, default):
    value = options.get(name, default)
    if not isinstance(value, str) or value not in choices:
        raise FieldError(name, f"{name}: choose " + ", ".join(choices[:-1]) + f" or {choices[-1]}.")
    return value


def _real(options, name, default, what):
    value = options.get(name, default)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not np.isfinite(float(value)):
        raise FieldError(name, f"{name} must be {what}.")
    return float(value)


def _positive(options, name, default):
    value = _real(options, name, default, "a finite positive number")
    if not value > 0:
        raise FieldError(name, f"{name} must be a finite positive number.")
    return value


def _settings(options):
    design = _choice(options, DESIGN, DESIGNS, PAIRED)
    orientation = _choice(options, REPORT_RATIO, ORIENTATIONS, FIRST_OVER_SECOND)
    null = _positive(options, NULL_RATIO, 1.0)
    reference = _positive(options, REFERENCE, 1.0) if design == ONE_SAMPLE else None
    level = _real(options, LEVEL, 95.0, "a finite number between 0 and 100")
    if not 0 < level < 100:
        raise FieldError(LEVEL, f"{LEVEL} must be greater than 0 and less than 100.")
    alternative = _choice(options, ALTERNATIVE, ALTERNATIVES, TWO_SIDED)
    base = _choice(options, LOG_BASE, LOG_BASES, BASE_10)
    graph = _choice(options, GRAPH, GRAPHS, RATIO_ESTIMATION)
    if graph == LOG_RATIOS and design not in (PAIRED, ONE_SAMPLE):
        raise FieldError(GRAPH, "Log ratios are drawn only for Paired and One-sample designs. Choose another graph.")
    pairing = True
    if design == PAIRED:
        pairing = options.get(PAIRING, True)
        if not isinstance(pairing, (bool, np.bool_)):
            raise FieldError(PAIRING, f"{PAIRING}: choose on or off.")
    return design, orientation, null, reference, level, alternative, base, graph, bool(pairing)


# ----- data ----------------------------------------------------------------------------------------------------------

def _column(frame, name, role):
    if not isinstance(name, str) or not name:
        raise FieldError(role, f"Choose a column for {role}.")
    if name not in frame:
        raise FieldError(role, f'Choose an existing column for {role}: "{name}" is not in the worksheet.')
    raw = frame[name]
    if isinstance(raw, pd.DataFrame):
        raise FieldError(role, "Worksheet column names must be unique.")
    cells = raw.to_numpy(dtype=object)
    present = np.array([not (value is None or value is pd.NA or (isinstance(value, float) and np.isnan(value))
                             or (isinstance(value, str) and not value.strip()) or value is pd.NaT)
                        for value in cells], dtype=bool)
    values = np.full(len(cells), np.nan)
    for i in np.flatnonzero(present):
        value = cells[i]
        if isinstance(value, (bool, np.bool_)):
            continue
        try:
            values[i] = float(value.replace(",", ".")) if isinstance(value, str) else float(value)
        except (TypeError, ValueError, OverflowError):
            pass
    return present, values


def _used(frame, role, name, present, values, rows):
    """Return the float values of the used rows, or raise on the first unusable cell of that column."""
    chosen = values[rows]
    bad = ~np.isfinite(chosen) | ~(chosen > 0)
    if bad.any():
        first = int(np.flatnonzero(bad)[0])
        label = frame.index[rows[first]]
        count = int(bad.sum())
        extra = f" ({count} cells are unusable)" if count > 1 else ""
        raise FieldError(role, f'Column "{name}" must hold finite positive numbers in the rows used. '
                               f"Source row {label} is not{extra}.")
    return chosen


def _prepare(frame, design, first_name, second_name):
    """Return the source rows, values and counts of the observations used."""
    if not frame.columns.is_unique:
        raise FieldError(FIRST, "Worksheet column names must be unique.")
    present_a, values_a = _column(frame, first_name, FIRST)
    if design == ONE_SAMPLE:
        rows_a = np.flatnonzero(present_a)
        return {"rows_a": rows_a, "a": _used(frame, FIRST, first_name, present_a, values_a, rows_a),
                "rows_b": np.array([], dtype=int), "b": np.array([])}
    if not isinstance(second_name, str) or not second_name:
        raise FieldError(SECOND, f"Choose a column for {SECOND}.")
    if first_name == second_name:
        raise FieldError(SECOND, "Choose different columns for First and Second.")
    present_b, values_b = _column(frame, second_name, SECOND)
    if design == PAIRED:
        rows = np.flatnonzero(present_a & present_b)
        a = _used(frame, FIRST, first_name, present_a, values_a, rows)
        b = _used(frame, SECOND, second_name, present_b, values_b, rows)
        return {"rows_a": rows, "a": a, "rows_b": rows, "b": b}
    rows_a, rows_b = np.flatnonzero(present_a), np.flatnonzero(present_b)
    return {"rows_a": rows_a, "a": _used(frame, FIRST, first_name, present_a, values_a, rows_a),
            "rows_b": rows_b, "b": _used(frame, SECOND, second_name, present_b, values_b, rows_b)}


# ----- numerics ------------------------------------------------------------------------------------------------------

def _mantissa_log_ratio(first, second, exponent):
    """log(first / second) + exponent·log(2), without a large-offset subtraction.

    ``first`` and ``second`` are bounded mantissas (or products of two mantissas). A power of two
    is applied before log1p when the values straddle a binary boundary, preserving a ratio close
    to one. Neither the original ratio nor a product of the original observations is formed.
    """
    shift = np.clip(exponent, -2, 2)
    shifted = np.ldexp(first, shift)
    return np.log1p((shifted - second) / second) + (exponent - shift) * np.log(2.0)


def _log_ratio(first, second, null=1.0):
    """log(first / second / null), without forming either original ratio or product."""
    a, ea = np.frexp(first)
    b, eb = np.frexp(second)
    c, ec = np.frexp(null)
    return _mantissa_log_ratio(a, b * c, ea - eb - ec)


def _paired_logs(first, second):
    """First pair's log ratio and centered log ratios, with its common offset kept separate."""
    a, ea = np.frexp(first)
    b, eb = np.frexp(second)
    exponent = ea - eb
    centered = _mantissa_log_ratio(a * b[0], b * a[0], exponent - exponent[0])
    return float(_log_ratio(first[0], second[0])), centered


def _noise(values):
    """Roundoff of relative log ratios, independent of the observations' common unit scale.

    Bounded mantissa products, their ratio, and the input rounding can produce a few ulps of
    variation even for a constant ratio. The common log offset never enters this tolerance.
    """
    return 8 * _EPS * (1 + float(np.max(np.abs(values))))


def _spread(values):
    """Sample standard deviation, or exactly 0 when it is below the rounding noise of the logs."""
    sd = float(np.std(values, ddof=1))
    return 0.0 if sd <= _noise(values) else sd


def _inference(design, first, second, reference=1.0):
    """Return (origin, centered mean, se, df), keeping the log-ratio offset separate."""
    n, m = len(first), len(second)
    if design == PAIRED:
        origin, centered = _paired_logs(first, second)
        return origin, float(np.mean(centered)), _spread(centered) / np.sqrt(n), n - 1.0
    la = _log_ratio(first, first[0])
    if design == ONE_SAMPLE:
        return float(_log_ratio(first[0], reference)), float(np.mean(la)), _spread(la) / np.sqrt(n), n - 1.0
    lb = _log_ratio(second, second[0])
    origin, centered = float(_log_ratio(first[0], second[0])), float(np.mean(la) - np.mean(lb))
    va, vb = _spread(la) ** 2, _spread(lb) ** 2
    if design == STUDENT:
        pooled = ((n - 1) * va + (m - 1) * vb) / (n + m - 2)
        return origin, centered, float(np.sqrt(pooled * (1 / n + 1 / m))), n + m - 2.0
    total = va / n + vb / m
    if total == 0:
        return origin, centered, 0.0, np.nan
    df = total ** 2 / ((va / n) ** 2 / (n - 1) + (vb / m) ** 2 / (m - 1))
    return origin, centered, float(np.sqrt(total)), float(df)


def _exp(value):
    with np.errstate(all="ignore"):
        answer = float(np.exp(value))
    return answer if np.isfinite(answer) and answer > 0 else np.nan


def _p_value(t, df, alternative):
    if alternative == GREATER:
        return float(stats.t.sf(t, df))
    if alternative == LESS:
        return float(stats.t.cdf(t, df))
    return float(2 * stats.t.sf(abs(t), df))


def _pairing_correlation(la, lb):
    """Pearson r and its two-sided P for the logs of the two columns, or (nan, nan, reason)."""
    if len(la) < 3:
        return np.nan, np.nan, "At least three complete pairs are needed."
    if _spread(la) == 0 or _spread(lb) == 0:
        return np.nan, np.nan, "A column has constant log values, so the correlation is undefined."
    result = stats.pearsonr(la, lb)
    return float(result.statistic), float(result.pvalue), ("Correlation of the log values; "
                                                           "it does not prove that the pairing was effective.")


# ----- analysis ------------------------------------------------------------------------------------------------------

def lognormal_test(frame, options):
    design, orientation, null, reference, level, alternative, base, graph, pairing = _settings(options)
    first_name = options.get(FIRST)
    second_name = options.get(SECOND) if design != ONE_SAMPLE else None
    data = _prepare(frame, design, first_name, second_name)
    la, lb = np.log(data["a"]), np.log(data["b"])
    n, m = len(la), len(lb)
    if design == PAIRED and n < 2:
        raise FieldError(FIRST, f"A paired test needs at least two complete pairs; {n} found.")
    if design != PAIRED and n < 2:
        raise FieldError(FIRST, f'Column "{first_name}" needs at least two positive observations; {n} found.')
    if design in (WELCH, STUDENT) and m < 2:
        raise FieldError(SECOND, f'Column "{second_name}" needs at least two positive observations; {m} found.')
    sign = -1.0 if orientation == SECOND_OVER_FIRST else 1.0
    origin, centered, se, df = _inference(design, data["a"], data["b"], reference)
    delta = sign * (origin + centered)
    divisor = float(np.log(10.0)) if base == BASE_10 else 1.0

    row = dict.fromkeys(RESULT_COLUMNS, np.nan)
    row.update({"N first": n, "N second": 0 if design == ONE_SAMPLE else m, "Mean log ratio": delta / divisor,
                "SE log ratio": se / divisor, "df": df, "Geometric ratio": _exp(delta), "Status": OK, "Reason": ""})
    reasons = []
    if se == 0:
        row["Status"] = UNAVAILABLE
        reasons.append("The standard error is zero (no variability beyond rounding in the log values), "
                       "so t, P and the confidence interval are undefined.")
    else:
        # Center the origin on the null before adding the tiny sample difference. Subtracting two
        # large logs here would lose the test statistic even though the spread was computed safely.
        first, second = data["a"][0], reference if design == ONE_SAMPLE else data["b"][0]
        null_offset = (sign * origin if null == 1.0 else
                       _log_ratio(first, second, null) if sign > 0 else _log_ratio(second, first, null))
        t = (null_offset + sign * centered) / se
        half = float(stats.t.isf((100.0 - level) / 200.0, df)) * se
        low, high = delta - half, delta + half
        row.update({"t": t, "p": _p_value(t, df, alternative), "Log lower": low / divisor, "Log upper": high / divisor,
                    "Lower": _exp(low), "Upper": _exp(high)})
        if not np.isfinite([row["Log lower"], row["Log upper"]]).all():
            raise FieldError(LEVEL, f"{LEVEL} is too close to 100 for an interval to be computed.")
    missing = [name for name in ("Geometric ratio", *(("Lower", "Upper") if se != 0 else ())) if np.isnan(row[name])]
    if missing:
        row["Status"] = OVERFLOW
        reasons.append("The ratio is outside the floating-point range (" + ", ".join(missing).lower() + " left "
                       "missing); the log results and the test remain valid.")
    row["Reason"] = " ".join(reasons)

    label = f"{first_name} / {second_name}" if design != ONE_SAMPLE else f"{first_name} / reference"
    ratio_text = label if sign > 0 else (f"{second_name} / {first_name}" if design != ONE_SAMPLE
                                         else f"reference / {first_name}")
    tables = {TEST_SHEET: pd.DataFrame([row], columns=RESULT_COLUMNS)}

    # Observations on the chosen log base; paired data use only the complete pairs.
    records = []
    for name, rows, values, logs in ((first_name, data["rows_a"], data["a"], la),
                                     (second_name, data["rows_b"], data["b"], lb)):
        for source, value, log in zip(frame.index[rows], values, logs / divisor, strict=True):
            records.append({"Source row": source, "Sample": name, "Value": value, "Log value": log})
    tables[OBSERVATIONS_SHEET] = pd.DataFrame(records, columns=["Source row", "Sample", "Value", "Log value"])

    differences = (sign * _log_ratio(data["a"], data["b"]) if design == PAIRED
                   else sign * _log_ratio(data["a"], reference) if design == ONE_SAMPLE else None)
    if design == PAIRED:
        tables[RATIOS_SHEET] = pd.DataFrame({
            "Source row": frame.index[data["rows_a"]], "First": data["a"], "Second": data["b"],
            "Log ratio": differences / divisor, "Ratio": [_exp(value) for value in differences]})

    settings = {"Design": design, "First": first_name, "Second": second_name if design != ONE_SAMPLE else "Not used",
                "Report ratio": orientation, "Ratio definition": ratio_text, "Null ratio": null,
                "Hypothetical geometric mean": reference if design == ONE_SAMPLE else "Not used",
                "Confidence level (%)": level, "Alternative": alternative, "Log base": base,
                "Graph": graph, "Pairing correlation": ("Not applicable" if design != PAIRED
                                                        else "On" if pairing else "Off"),
                "Interval": "Two-sided at the stated level, also for one-sided P values; Null ratio does not move it.",
                "Log scale": "log10 columns" if base == BASE_10 else "natural-log columns"}
    if design == PAIRED and pairing:
        r, p, note = _pairing_correlation(_log_ratio(data["a"], data["a"][0]),
                                         _log_ratio(data["b"], data["b"][0]))
        settings.update({"Pearson r (log values)": r, "Pearson P (two-sided)": p, "Pairing correlation note": note})
    tables[SETTINGS_SHEET] = _report(settings)

    figure = None
    if graph != NO_GRAPH:
        figure = _figure(graph, design, first_name, second_name, ratio_text, base, orientation, level, null, reference,
                         row, data, la, lb, differences, divisor)
    attach_lognormal(tables, data["a"], data["b"], options, design, level)
    return Result(tables, figure)


# ----- graphs --------------------------------------------------------------------------------------------------------

def _base_name(base):
    return "log10" if base == BASE_10 else "ln"


def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def _title(design, ratio_text, base, level):
    return f"{LOGNORMAL} · {design} · {ratio_text} · {_base_name(base)}, {level:g}% CI"


def _jitter(count, seed):
    return ((np.arange(count) * 0.6180339887498949 + seed) % 1.0 - 0.5) * 0.28


def _figure(graph, design, first_name, second_name, ratio_text, base, orientation, level, null, reference, row, data,
            la, lb, differences, divisor):
    title = _title(design, ratio_text, base, level)
    if graph == RATIO_ESTIMATION:
        figure, axes = _plot(title, f"Geometric mean ratio ({ratio_text}), logarithmic axis")
        _plain(axes.title, axes.xaxis.label)
        axes.set_xscale("log")
        axes.set_yticks([])
        axes._tramastat_numeric_axes = ("x",)
        axes._tramastat_categorical_axes = ("y",)
        axes.spines["left"].set_visible(False)
        axes.set_ylim(-1, 1)
        estimate, low, high = row["Geometric ratio"], row["Lower"], row["Upper"]
        reference_line = axes.axvline(null, color="#6b7785", linestyle="--", linewidth=1.3, zorder=1,
                                      label=f"Null ratio = {null:g}")
        reference_line.set_gid(f"{GID}reference")
        notes = []
        if np.isfinite(estimate):
            if np.isfinite(low) and np.isfinite(high):
                container = axes.errorbar([estimate], [0], xerr=[[estimate - low], [high - estimate]], fmt="o",
                                          color=COLORS[0], capsize=6, markersize=7, linewidth=1.8, zorder=3,
                                          label=f"{estimate:.4g} ({level:g}% CI {low:.4g} to {high:.4g})")
                container.lines[0].set_gid(f"{GID}estimate")
            else:
                axes.scatter([estimate], [0], s=60, color=COLORS[0], zorder=3, label=f"{estimate:.4g}").set_gid(
                    f"{GID}estimate")
                notes.append("Interval not available." if not np.isfinite(row["Log lower"])
                             else "Interval limit outside the numeric range.")
        else:
            notes.append("Estimate outside the numeric range of a floating-point ratio, so it is not drawn.")
        name = _base_name(base)
        if notes or not np.isfinite([estimate, low, high]).all():
            lower = row["Log lower"]
            upper = row["Log upper"]
            interval = "" if np.isnan(lower) else f", {level:g}% CI {lower:.6g} to {upper:.6g}"
            notes.append(f"Mean {name} ratio = {row['Mean log ratio']:.6g}{interval}.")
            axes.text(.5, .88, " ".join(notes), transform=axes.transAxes, ha="center", va="top", fontsize=9,
                      color="#8a3b12", wrap=True, zorder=5,
                      bbox={"facecolor": "white", "edgecolor": "none", "alpha": .92}).set_parse_math(False)
        if not np.isfinite(estimate):
            axes.set_xlim(null / 10, null * 10)
        else:
            axes.margins(x=.2)
        legend = axes.legend(frameon=True, facecolor="white", edgecolor="none", framealpha=.92, loc="lower center",
                             bbox_to_anchor=(.5, 0), fontsize=9)
        _plain(legend.get_title(), *legend.get_texts())
        return figure

    names = [first_name] if design == ONE_SAMPLE else [first_name, second_name]
    name = _base_name(base)
    if graph == LOG_OBSERVATIONS:
        figure, axes = _plot(title, "", f"{name}(value)")
        _plain(axes.title, axes.yaxis.label)
        samples = [(la / divisor, "First")] + ([] if design == ONE_SAMPLE else [(lb / divisor, "Second")])
        positions = [1.0, 2.0][:len(samples)]
        if design == PAIRED and len(samples) == 2:
            for k, (a, b) in enumerate(zip(samples[0][0], samples[1][0], strict=True)):
                line, = axes.plot([1, 2], [a, b], color="#9aa5b1", linewidth=1.0, zorder=1, label="_nolegend_")
                line.set_gid(f"{GID}pair:{k + 1}")
        for index, ((values, _), position) in enumerate(zip(samples, positions, strict=True)):
            spread = _jitter(len(values), index * .37)
            points = axes.scatter(position + (spread if design != PAIRED else 0 * spread), values, s=30,
                                  color=COLORS[index % len(COLORS)], edgecolors="white", linewidths=.6, zorder=3,
                                  label=names[index])
            points.set_gid(f"{GID}observations:{index + 1}")
            mean = float(np.mean(values))
            mean_line, = axes.plot([position - .3, position + .3], [mean, mean], color="#1f2933", linewidth=2.2,
                                   zorder=4, label="Mean" if index == 0 else "_nolegend_")
            mean_line.set_gid(f"{GID}mean:{index + 1}")
        if design == ONE_SAMPLE:
            line = axes.axhline(float(np.log(reference)) / divisor, color="#6b7785", linestyle="--", linewidth=1.3,
                                label=f"log({REFERENCE.lower()} = {reference:g})")
            line.set_gid(f"{GID}reference")
        axes.set_xticks(positions, names)
        axes.set_xlim(.4, positions[-1] + .6)
        _plain(*axes.get_xticklabels())
        legend = axes.legend(frameon=False, loc="best", fontsize=9)
        _plain(legend.get_title(), *legend.get_texts())
        return figure

    # Log ratios: one value per pair (or per observation against the reference).
    what = f"{ratio_text}"
    figure, axes = _plot(title, "", f"{name}({what})")
    _plain(axes.title, axes.yaxis.label)
    values = differences / divisor
    points = axes.scatter(1 + _jitter(len(values), .11), values, s=32, color=COLORS[0], edgecolors="white",
                          linewidths=.6, zorder=3, label=f"{len(values)} log ratios")
    points.set_gid(f"{GID}log-ratios")
    mean = row["Mean log ratio"]
    low, high = row["Log lower"], row["Log upper"]
    if np.isfinite(low) and np.isfinite(high):
        container = axes.errorbar([1], [mean], yerr=[[mean - low], [high - mean]], fmt="D", color="#1f2933",
                                  capsize=8, markersize=7, linewidth=2, zorder=4,
                                  label=f"Mean and {level:g}% CI")
        container.lines[0].set_gid(f"{GID}mean")
    else:
        axes.scatter([1], [mean], marker="D", s=60, color="#1f2933", zorder=4, label="Mean").set_gid(f"{GID}mean")
    line = axes.axhline(float(np.log(null)) / divisor, color="#6b7785", linestyle="--", linewidth=1.3,
                        label=f"{name}(null ratio = {null:g})")
    line.set_gid(f"{GID}reference")
    axes.set_xticks([1], [what])
    axes.set_xlim(.4, 1.6)
    _plain(*axes.get_xticklabels())
    legend = axes.legend(frameon=False, loc="best", fontsize=9)
    _plain(legend.get_title(), *legend.get_texts())
    return figure
