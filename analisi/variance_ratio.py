"""Compare two independent sample variances and the confidence interval of their ratio.

The ratio keeps the order First / Second. The separate F statistic is the larger variance
divided by the smaller one, with the degrees of freedom of those groups. A small p value
does not choose Student or Welch. The interval is the exact F interval, not a Wald interval.

Sample variances are computed after scaling each sample by its own maximum absolute value,
so a common change of units cannot turn a representable spread into zero or infinity.
Lognormal uses the natural logarithms of strictly positive values before that scaling.
Missing values are dropped inside each sample, not by pairing rows.
"""
import math

import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .reporting import Result, _plot, _report

METHOD = "Compare two variances"
FIRST, SECOND = "First", "Second"
LEVEL = "Confidence level (%)"
DISTRIBUTION = "Distribution"
NORMAL, LOGNORMAL = DISTRIBUTIONS = ("Normal", "Lognormal")
GRAPH = "Graph"
GRAPH_NONE, GRAPH_VARIANCE, GRAPH_SD = GRAPHS = ("None", "Variance ratio", "SD ratio")
SHOW = "Show variance comparison"
SHEET, SUMMARY, SETTINGS = "Variance comparison", "Summary", "Settings"
UNPAIRED = ("Welch", "Student")
KEYS = (
    "N first", "N second", "Variance first", "Variance second", "Variance ratio", "SD ratio",
    "F", "DFn", "DFd", "p", "Variance ratio lower", "Variance ratio upper",
    "SD ratio lower", "SD ratio upper",
)
LABEL_KEYS = {
    FIRST: "variance.ratio.field.first",
    SECOND: "variance.ratio.field.second",
    LEVEL: "variance.ratio.field.level",
    DISTRIBUTION: "variance.ratio.field.distribution",
    GRAPH: "variance.ratio.field.graph",
    SHOW: "variance.ratio.field.show",
}
CHOICE_KEYS = {
    NORMAL: "variance.ratio.choice.normal",
    LOGNORMAL: "variance.ratio.choice.lognormal",
    GRAPH_NONE: "variance.ratio.choice.none",
    GRAPH_VARIANCE: "variance.ratio.choice.variance",
    GRAPH_SD: "variance.ratio.choice.sd",
}
NOTE_KEY = "variance.ratio.note"
_FIELDS = frozenset({FIRST, SECOND, LEVEL, DISTRIBUTION, GRAPH, SHOW})
GID = "variance-ratio:"


class _InputError(ValueError):
    """A domain error tagged with the sample or option that caused it."""

    def __init__(self, which, message):
        super().__init__(message)
        self.which = which


def _say(key, english, **values):
    from .i18n import tr
    text = tr(key, **values)
    return english if text == key else text


def shows_graph(options):
    """True when the saved recipe asks for the ratio figure."""
    return options.get(GRAPH, GRAPH_NONE) in (GRAPH_VARIANCE, GRAPH_SD)


def _flag(value):
    if type(value) is bool or type(value) is np.bool_:
        return bool(value)
    raise _InputError("flag", "Choose yes or no.")


def requested(options, design):
    """True only for an explicit unpaired request. Paired and one-sample ignore the flag."""
    if design not in UNPAIRED or SHOW not in options:
        return False
    try:
        return _flag(options[SHOW])
    except _InputError as error:
        raise FieldError(SHOW, str(error)) from None


def _level(level):
    if isinstance(level, (bool, np.bool_)) or not isinstance(level, (int, float, np.integer, np.floating)):
        raise _InputError("level", "Confidence level (%) must be a finite number greater than 0 and less than 100.")
    level = float(level)
    if not math.isfinite(level) or not 0 < level < 100:
        raise _InputError("level", "Confidence level (%) must be a finite number greater than 0 and less than 100.")
    return level


def _distribution(distribution):
    if not isinstance(distribution, str) or distribution not in DISTRIBUTIONS:
        raise _InputError("distribution", "Choose Normal or Lognormal.")
    return distribution


def _missing(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _number(value):
    if isinstance(value, (bool, np.bool_)):
        raise _InputError("sample", "The sample contains non-numeric or infinite data.")
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", "."))
        except ValueError:
            raise _InputError("sample", "The sample contains non-numeric or infinite data.") from None
    elif isinstance(value, (int, np.integer, float, np.floating)):
        value = float(value)
    else:
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            raise _InputError("sample", "The sample contains non-numeric or infinite data.") from None
    if not math.isfinite(value):
        raise _InputError("sample", "The sample contains non-numeric or infinite data.")
    return value


def _parse(sample, which):
    """Finite observations and the number of blanks removed from this sample alone."""
    if isinstance(sample, pd.Series):
        raw = sample.tolist()
    elif isinstance(sample, np.ndarray):
        raw = sample.tolist()
    else:
        try:
            raw = list(sample)
        except TypeError:
            raise _InputError(which, "The sample contains non-numeric or infinite data.") from None
    values, missing = [], 0
    try:
        for value in raw:
            if _missing(value):
                missing += 1
                continue
            values.append(_number(value))
    except _InputError as error:
        raise _InputError(which, str(error).replace("The sample", "The first sample" if which == "first"
                                                    else "The second sample")) from None
    if len(values) < 2:
        side = "first" if which == "first" else "second"
        raise _InputError(which, f"The {side} sample needs at least two finite observations.")
    return values, missing


def _as_array(values, distribution, which):
    array = np.asarray(values, dtype=np.float64)
    if distribution == LOGNORMAL:
        if np.any(array <= 0):
            side = "first" if which == "first" else "second"
            raise _InputError(which, f"The {side} sample must contain strictly positive values "
                              "for a lognormal comparison.")
        array = np.log(array)
    return array


def _parts(array):
    """Sample variance as (float or nan, mantissa, binary exponent, constant).

    ``mantissa * 2**exponent`` is the variance. The float is nan when that product
    is outside the finite positive range; the mantissa and exponent still carry it.
    Subtracting the first observation removes a shared offset before scaling, so a
    translation that is still representable cannot erase the spread.
    """
    with np.errstate(over="ignore"):
        shifted = array - float(array[0])
    peak = float(np.max(np.abs(shifted)))
    if not math.isfinite(peak):
        # Finite values at opposite extremes can have an unrepresentable
        # difference. Normalize before centering in that case; keep centering
        # first otherwise, to preserve small spreads around a large offset.
        peak = float(np.max(np.abs(array)))
        scaled = array / peak
        scaled = scaled - float(scaled[0])
    elif peak == 0.0:
        return 0.0, 0.0, 0, True, 0.0
    else:
        scaled = shifted / peak
    center = float(scaled.mean())
    deviation = scaled - center
    squares = float(deviation @ deviation)
    if not squares > 0.0:
        return 0.0, 0.0, 0, True, peak
    mantissa = squares / (shifted.size - 1)
    peak_mantissa, peak_exponent = math.frexp(peak)
    mantissa *= peak_mantissa * peak_mantissa
    exponent = 2 * peak_exponent
    mantissa, extra = math.frexp(mantissa)
    exponent += extra
    try:
        as_float = math.ldexp(mantissa, exponent)
    except OverflowError:
        as_float = math.inf
    if not math.isfinite(as_float) or as_float == 0.0:
        as_float = math.nan
    return as_float, mantissa, exponent, False, peak


def _quotient(left, right):
    """Return ``ldexp(left_m, left_e) / ldexp(right_m, right_e)`` when it is finite and positive."""
    mantissa, extra = math.frexp(left[0] / right[0])
    exponent = left[1] - right[1] + extra
    try:
        value = math.ldexp(mantissa, exponent)
    except OverflowError:
        value = math.inf
    if not math.isfinite(value) or value <= 0.0:
        raise _InputError("ratio", "The variance ratio is outside the range floating-point numbers can represent.")
    return value


def _positive(value, which, message):
    if not math.isfinite(value) or value <= 0.0:
        raise _InputError(which, message)
    return float(value)


def compare_variances(first, second, *, level=95., distribution="Normal"):
    """Oriented variance comparison. ``level`` is a percent strictly between 0 and 100."""
    level = _level(level)
    distribution = _distribution(distribution)
    first_values, _ = _parse(first, "first")
    second_values, _ = _parse(second, "second")
    first_array = _as_array(first_values, distribution, "first")
    second_array = _as_array(second_values, distribution, "second")
    variance_first, mant_first, exp_first, flat_first, _ = _parts(first_array)
    variance_second, mant_second, exp_second, flat_second, _ = _parts(second_array)
    if flat_first:
        raise _InputError("first", "The first sample has zero variance.")
    if flat_second:
        raise _InputError("second", "The second sample has zero variance.")
    ratio = _quotient((mant_first, exp_first), (mant_second, exp_second))
    df1, df2 = len(first_values) - 1, len(second_values) - 1
    if ratio >= 1.0:
        statistic, dfn, dfd = ratio, df1, df2
    else:
        statistic = _positive(1.0 / ratio, "ratio",
                              "The variance ratio is outside the range floating-point numbers can represent.")
        dfn, dfd = df2, df1
    cdf = float(stats.f.cdf(ratio, df1, df2))
    survival = float(stats.f.sf(ratio, df1, df2))
    if not math.isfinite(cdf) or not math.isfinite(survival):
        raise _InputError("ratio", "The variance ratio is outside the range floating-point numbers can represent.")
    probability = min(1.0, 2.0 * min(cdf, survival))
    alpha = (100.0 - level) / 100.0
    # The reciprocal F distribution swaps the degrees of freedom. Its lower
    # tail avoids rounding 1 - alpha/2 to 1 at high confidence levels (isf in
    # some SciPy versions also performs that subtraction internally).
    reciprocal_upper_quantile = float(stats.f.ppf(alpha / 2.0, df2, df1))
    lower_quantile = float(stats.f.ppf(alpha / 2.0, df1, df2))
    interval = "The confidence interval is outside the range floating-point numbers can represent."
    lower = _positive(ratio * reciprocal_upper_quantile, "interval", interval)
    upper = _positive(ratio / lower_quantile, "interval", interval)
    sd = _positive(math.sqrt(ratio), "ratio",
                   "The variance ratio is outside the range floating-point numbers can represent.")
    return {
        "N first": len(first_values), "N second": len(second_values),
        "Variance first": float(variance_first), "Variance second": float(variance_second),
        "Variance ratio": ratio, "SD ratio": sd, "F": float(statistic), "DFn": int(dfn), "DFd": int(dfd),
        "p": float(probability), "Variance ratio lower": lower, "Variance ratio upper": upper,
        "SD ratio lower": _positive(math.sqrt(lower), "interval", interval),
        "SD ratio upper": _positive(math.sqrt(upper), "interval", interval),
    }


def _column(frame, name, role):
    if not isinstance(name, str) or not name:
        raise FieldError(role, "Choose a column.")
    if not frame.columns.is_unique:
        raise FieldError(FIRST, "Worksheet column names must be unique.")
    if name not in frame.columns:
        raise FieldError(role, f'Column "{name}" is not in the worksheet.')
    raw = frame[name]
    if isinstance(raw, pd.DataFrame):
        raise FieldError(role, "Worksheet column names must be unique.")
    try:
        values, missing = _parse(raw, "first" if role == FIRST else "second")
    except _InputError as error:
        text = str(error)
        if "at least two" in text:
            raise FieldError(role, f'Column "{name}" needs at least two finite observations.') from None
        raise FieldError(role, f'Column "{name}" contains non-numeric or infinite data.') from None
    return values, missing


def _field_error(error, first_name, second_name):
    text = str(error)
    if error.which == "level":
        return FieldError(LEVEL, text)
    if error.which == "distribution":
        return FieldError(DISTRIBUTION, text)
    if error.which == "interval":
        return FieldError(LEVEL, text)
    if error.which == "ratio":
        return FieldError(FIRST, text)
    role = FIRST if error.which == "first" else SECOND
    column = first_name if role == FIRST else second_name
    if "zero variance" in text:
        message = f'Column "{column}" has zero variance.'
    elif "strictly positive" in text:
        message = f'Column "{column}" must contain strictly positive values for a lognormal comparison.'
    elif "at least two" in text:
        message = f'Column "{column}" needs at least two finite observations.'
    else:
        message = f'Column "{column}" contains non-numeric or infinite data.'
    return FieldError(role, message)


def _scale_note(distribution):
    if distribution == LOGNORMAL:
        return ("Natural logarithms of the strictly positive observations. Each sample is then centered "
                "and scaled independently; scaling precedes centering if a finite difference would overflow.")
    return ("Each sample is centered and scaled independently; scaling precedes centering if a finite "
            "difference would overflow.")


def _peaks(first, second, distribution):
    return (float(np.max(np.abs(_as_array(first, distribution, "first")))),
            float(np.max(np.abs(_as_array(second, distribution, "second")))))


def _span(low, high):
    """Multiplicative margin that still contains both ends when the margin cannot be stored."""
    left, right = low / 1.35, high * 1.35
    if not math.isfinite(left) or left <= 0.0:
        left = low
    if not math.isfinite(right) or right <= left:
        right = high
    return left, right


def _figure(result, options, distribution, level):
    graph = options[GRAPH]
    if graph == GRAPH_NONE:
        return None
    kind = "variance" if graph == GRAPH_VARIANCE else "sd"
    estimate = result["Variance ratio" if graph == GRAPH_VARIANCE else "SD ratio"]
    lower = result["Variance ratio lower" if graph == GRAPH_VARIANCE else "SD ratio lower"]
    upper = result["Variance ratio upper" if graph == GRAPH_VARIANCE else "SD ratio upper"]
    axis = _say(f"variance.ratio.axis.{kind}",
                "Variance ratio (First / Second), logarithmic axis" if graph == GRAPH_VARIANCE
                else "SD ratio (First / Second), logarithmic axis")
    title = _say("variance.ratio.figure.title",
                 "{method} · {distribution} · {first} / {second} · {level}% CI",
                 method=_say("variance.ratio.method", METHOD),
                 distribution=_say(CHOICE_KEYS[distribution], distribution),
                 first=options[FIRST], second=options[SECOND], level=f"{level:g}")
    figure, axes = _plot(title, axis, "")
    for text in (axes.title, axes.xaxis.label):
        text.set_parse_math(False)
    axes.set_xscale("log")
    axes.set_yticks([])
    axes.set_ylim(-1, 1)
    axes.spines["left"].set_visible(False)
    axes._tramastat_numeric_axes = ("x",)
    axes._tramastat_categorical_axes = ("y",)
    reference = axes.axvline(1, color="#6b7785", linestyle="--", linewidth=1.3, zorder=1,
                             label=_say("variance.ratio.reference", "Reference = 1"))
    reference.set_gid(f"{GID}reference")
    interval = axes.plot([lower, upper], [0, 0], color="#216a94", linewidth=1.8, solid_capstyle="butt",
                         zorder=2)[0]
    interval.set_gid(f"{GID}interval")
    for cap, end in (("low", lower), ("high", upper)):
        mark = axes.plot([end, end], [-0.12, 0.12], color="#216a94", linewidth=1.4, zorder=2)[0]
        mark.set_gid(f"{GID}cap-{cap}")
    point = axes.scatter([estimate], [0], s=46, color="#216a94", zorder=3,
                         label=_say("variance.ratio.estimate",
                                    "{estimate} ({level}% CI {lower} to {upper})",
                                    estimate=f"{estimate:.4g}", level=f"{level:g}",
                                    lower=f"{lower:.4g}", upper=f"{upper:.4g}"))
    point.set_gid(f"{GID}estimate")
    left, right = min(lower, upper, 1.0), max(lower, upper, 1.0)
    axes.set_xlim(*_span(left, right))
    legend = axes.legend(frameon=True, facecolor="white", edgecolor="none", framealpha=.92,
                         loc="lower center", bbox_to_anchor=(.5, 0), fontsize=9)
    for text in legend.get_texts():
        text.set_parse_math(False)
    return figure


def _summary(options, distribution, level, first, second, missing_first, missing_second, result):
    first_peak, second_peak = _peaks(first, second, distribution)
    note = _scale_note(distribution)
    unavailable = [name for name in ("Variance first", "Variance second")
                   if isinstance(result[name], float) and math.isnan(result[name])]
    if unavailable:
        note += " " + " and ".join(unavailable) + " cannot be stored as a finite floating-point number; the ratio is unchanged."
    summary = {
        "N first": result["N first"], "N second": result["N second"],
        "Missing first": missing_first, "Missing second": missing_second,
        "First": options[FIRST], "Second": options[SECOND],
        "Orientation": f"{options[FIRST]} / {options[SECOND]}",
        "Distribution": distribution, "Scale": note,
        "First peak": first_peak, "Second peak": second_peak,
    }
    settings = {
        "Confidence level (%)": level, "Alpha": (100.0 - level) / 100.0,
        "Distribution": distribution, "Graph": options[GRAPH],
        "First": options[FIRST], "Second": options[SECOND],
        "Orientation": f"{options[FIRST]} / {options[SECOND]}",
        "Missing values": "Dropped separately in each sample.",
        "Interval": "Exact F interval for the oriented variance ratio. Not a Wald interval.",
        "F": "Larger sample variance divided by the smaller one. Degrees of freedom follow that order.",
        "Scale": note, "First peak": first_peak, "Second peak": second_peak,
    }
    return summary, settings


def analysis(frame, options):
    """Build the comparison sheets and, when requested, the log-axis interval figure."""
    if not isinstance(options, dict):
        raise FieldError(FIRST, "Choose a column.")
    try:
        level = _level(options.get(LEVEL, 95.0))
    except _InputError as error:
        raise FieldError(LEVEL, str(error)) from None
    try:
        distribution = _distribution(options.get(DISTRIBUTION, NORMAL))
    except _InputError as error:
        raise FieldError(DISTRIBUTION, str(error)) from None
    graph = options.get(GRAPH, GRAPH_NONE)
    if not isinstance(graph, str) or graph not in GRAPHS:
        raise FieldError(GRAPH, "Choose None, Variance ratio, or SD ratio.")
    first_name, second_name = options.get(FIRST), options.get(SECOND)
    if isinstance(first_name, str) and first_name and first_name == second_name:
        raise FieldError(SECOND, "Choose different columns for First and Second.")
    try:
        first, missing_first = _column(frame, first_name, FIRST)
        second, missing_second = _column(frame, second_name, SECOND)
        if distribution == LOGNORMAL:
            _as_array(first, distribution, "first")
            _as_array(second, distribution, "second")
        result = compare_variances(first, second, level=level, distribution=distribution)
    except _InputError as error:
        raise _field_error(error, first_name, second_name) from None
    stored = dict(options)
    stored[LEVEL] = level
    stored[DISTRIBUTION] = distribution
    stored[GRAPH] = graph
    summary, settings = _summary(stored, distribution, level, first, second, missing_first, missing_second, result)
    tables = {SHEET: _report({key: result[key] for key in KEYS}),
              SUMMARY: _report(summary), SETTINGS: _report(settings)}
    return Result(tables, _figure(result, stored, distribution, level))


def diagnostic_sheet(first, second, *, distribution="Normal", level=95.0):
    """One extra sheet. A sample that cannot be compared explains why and invents no p value."""
    try:
        result = compare_variances(first, second, level=level, distribution=distribution)
    except ValueError as error:
        from .i18n import translate_message
        reason = translate_message(str(error), "variance.ratio.error.")
        return {SHEET: _report({"Reason": reason})}
    return {SHEET: _report({key: result[key] for key in KEYS})}


def attach_ttest(frame, options, tables):
    """Add the sheet for an unpaired t-test when the option is on. Means stay untouched."""
    design = options.get("Design")
    if not requested(options, design):
        return tables
    from .stats import complete
    response, group = options.get("Response"), options.get("Group")
    data = complete(frame, [response], [group])
    order = options.get("Group order")
    labels = list(order) if order else data[group].drop_duplicates().tolist()
    first = data.loc[data[group] == labels[0], response].to_numpy(dtype=float)
    second = data.loc[data[group] == labels[1], response].to_numpy(dtype=float)
    tables.update(diagnostic_sheet(first, second, distribution=NORMAL, level=95.0))
    return tables


def attach_lognormal(tables, first, second, options, design, level):
    """Add the sheet for an unpaired lognormal t-test. The mean ratio is not recomputed."""
    if not requested(options, design):
        return tables
    tables.update(diagnostic_sheet(first, second, distribution=LOGNORMAL, level=level))
    return tables


def format_error(error):
    """Prefix a catalogued field error with the translated caption. None for other errors."""
    field = getattr(error, "field", None)
    if field not in _FIELDS:
        return None
    from .i18n import translate_message
    text = translate_message(str(error), "variance.ratio.error.")
    label = _say(LABEL_KEYS[field], field) if field in LABEL_KEYS else field
    if label and label not in text:
        return f"{label}: {text}"
    return text
