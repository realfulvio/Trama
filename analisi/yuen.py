"""Yuen's two-sample trimmed-mean test for independent samples.

For each sample, sort the finite observations, drop ``g = floor(n × trim)`` from each tail and average
the ``h = n − 2g`` central values. The variance of that mean uses the winsorized sum of squares: both
tails are replaced by the nearest retained value, ``sW²`` divides by ``h − 1``, and the variance
component is ``d = (n − 1) sW² / (h (h − 1))``, which is the winsorized sum of squares divided by
``h (h − 1)``. With trim 0 this is the ordinary variance divided by n, so the test matches Welch.

``g`` is the decimal floor of the percentage the user declared. ``n × 0.29`` in binary sits just under
29 when n is 100; flooring the decimal product of that percentage still removes 29.

The standard error is ``√(dA + dB)``. One constant sample is allowed. When both components are zero the
difference is reported and the t inference is left empty. A non-finite mean or variance names the sample
that overflowed.
"""
from decimal import Decimal, ROUND_FLOOR
import math
from numbers import Integral, Real

import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .mean_permutation import _blank, _numbers
from .reporting import Result, _report
from .ttest_options import COLUMNS, FIRST, GROUPED, INPUT, LEVEL, REVERSE, SECOND
from .yuen_text import text

METHOD = "Yuen's test for trimmed means"
RESPONSE, GROUP = "Response", "Group"
TRIM = "Trimming per tail (%)"
GROUP_ORDER = "Group order"
REASON_SE = text("yuen.reason.se")

OPTIONS = {
    INPUT: (COLUMNS, GROUPED),
    FIRST: None,
    SECOND: None,
    RESPONSE: None,
    GROUP: None,
    TRIM: 20.0,
    LEVEL: 95.0,
    REVERSE: False,
}
DATA_FIELDS = (INPUT, FIRST, SECOND, RESPONSE, GROUP)
NUMBER_FIELDS = (TRIM, LEVEL)
TAB_KEYS = {"Data": "yuen.tab.data", "Test": "yuen.tab.test"}
LABEL_KEYS = {
    INPUT: "ttest.field.input",
    FIRST: "ttest.field.first",
    SECOND: "ttest.field.second",
    RESPONSE: "interface.Response",
    GROUP: "interface.Group",
    TRIM: "yuen.field.trim",
    LEVEL: "ttest.field.level",
    REVERSE: "ttest.field.reverse",
}
CHOICE_KEYS = {GROUPED: "ttest.input.grouped", COLUMNS: "ttest.input.columns"}
GROUPS_SHEET, EFFECT_SHEET = "Yuen groups", "Yuen effect"

# Beyond this ratio of magnitude to spread, squaring deviations from the raw mean cancels.
_CANCEL_RATIO = 1e8


def removed_per_tail(n, trim):
    """Observations removed from each tail.

    ``trim`` is a fraction in ``[0, 0.5)``. The percentage is recovered with 12 significant digits,
    the precision stored from the dialog, and the product ``n × percentage / 100`` is floored in
    decimal arithmetic.
    """
    if isinstance(n, bool) or not isinstance(n, Integral) or int(n) < 0:
        raise ValueError("n must be a non-negative integer")
    fraction = _fraction(trim)
    if fraction is None or not 0 <= fraction < 0.5:
        raise ValueError("trim must be a fraction in [0, 0.5)")
    percent = format(fraction * 100.0, ".12g")
    product = Decimal(int(n)) * Decimal(percent) / Decimal(100)
    return int(product.to_integral_value(rounding=ROUND_FLOOR))


def yuen_summary(a, b, *, trim=0.2, level=0.95):
    """Trimmed-mean comparison of two finite vectors.

    ``trim`` and ``level`` are fractions (0.2 and 0.95 by default). The result always carries the
    difference, the standard error and the effective sizes. ``df``, ``statistic``, ``pvalue`` and the
    confidence limits are ``None`` when both winsorized variances are zero.
    """
    left, right = _vector(a), _vector(b)
    confidence = _fraction(level)
    if confidence is None or not 0 < confidence < 1:
        raise ValueError("level must be a fraction in (0, 1)")
    parts = [_component(values, trim) for values in (left, right)]
    (mean_a, d_a, h_a), (mean_b, d_b, h_b) = parts
    difference = mean_a - mean_b
    if not math.isfinite(difference):
        raise ValueError("the trimmed means are too large to subtract")
    total = d_a + d_b
    if not math.isfinite(total) or total < 0:
        raise ValueError("the variance components are not finite")
    se = math.sqrt(total)
    summary = {
        "difference": difference, "se": se, "df": None, "statistic": None, "pvalue": None,
        "ci_lower": None, "ci_upper": None, "h_a": h_a, "h_b": h_b,
    }
    if se == 0.0:
        return summary
    df = _degrees(d_a, d_b, h_a, h_b)
    statistic = difference / se
    if not (math.isfinite(df) and df > 0 and math.isfinite(statistic)):
        raise ValueError("the t statistic is not finite")
    critical = float(stats.t.ppf((1.0 + confidence) / 2.0, df))
    if not math.isfinite(critical):
        raise ValueError("the critical value is not finite")
    half = critical * se
    summary.update(
        df=df, statistic=statistic, pvalue=float(2.0 * stats.t.sf(abs(statistic), df)),
        ci_lower=difference - half, ci_upper=difference + half,
    )
    return summary


def visibility(layout):
    """Which dialog fields belong to a column pair and which belong to a grouped column."""
    columns = layout == COLUMNS
    return {
        INPUT: True, FIRST: columns, SECOND: columns, RESPONSE: not columns, GROUP: not columns,
        TRIM: True, LEVEL: True, REVERSE: True,
    }


def shown_number(value):
    """A saved percentage as the dialog shows it, with a decimal comma in Italian."""
    from .i18n import active_language
    rendered = format(float(value), ".12g")
    if active_language() == "it":
        rendered = rendered.replace(".", ",")
    return rendered


def describe_error(error, field=None):
    """Dialog banner: the engine message in the active language, naming the field to correct."""
    from .i18n import tr, translate_message

    def caption(name):
        key = LABEL_KEYS.get(name)
        return tr(key) if key else name

    field = getattr(error, "field", field)
    raw = str(error)
    shown = translate_message(raw, "yuen.error.", {"field": caption})
    if shown == raw:
        shown = translate_message(raw, "perm.error.", {"field": caption})
    label = caption(field) if field else ""
    if field and field.lower() not in shown.lower() and label.lower() not in shown.lower():
        shown = f"{label}: {shown}"
    return shown


def check_options(frame, options):
    """Validate the recipe and the worksheet. Field errors name the control to correct.

    A grouped recipe records ``Group order`` (appearance order, or the saved order when it still
    matches the two labels) so reopening the analysis does not swap the samples.
    """
    if not isinstance(options, dict):
        raise FieldError(INPUT, text("yuen.error.format"))
    layout = options.get(INPUT, COLUMNS)
    if layout not in (COLUMNS, GROUPED):
        raise FieldError(INPUT, text("yuen.error.format"))
    percent = _percent(options, TRIM, 20.0, "yuen.error.trim", low=0.0, high=50.0, exclusive_low=False)
    level = _percent(options, LEVEL, 95.0, "yuen.error.level", low=0.0, high=100.0, exclusive_low=True)
    reverse = _flag(options)
    samples = _read(frame, options, layout)
    if reverse:
        samples = (samples[1], samples[0])
    prepared = tuple(_checked(sample, percent / 100.0) for sample in samples)
    try:
        summary = yuen_summary(prepared[0].values, prepared[1].values, trim=percent / 100.0, level=level / 100.0)
    except (OverflowError, ValueError) as error:
        raise _overflow(prepared[0]) from error
    return prepared, summary


def yuen_test(frame, options):
    """Group statistics and the A − B effect. No figure."""
    samples, summary = check_options(frame, options)
    groups = pd.DataFrame([
        {
            "Group": sample.label, "Role": role,
            "N before filter": sample.n_before, "N after filter": sample.n_after,
            "Removed per tail": sample.removed, "Effective N": sample.effective,
            "Trimmed mean": sample.mean, "Variance component": sample.component,
        }
        for sample, role in zip(samples, ("First", "Second"))
    ])
    available = summary["pvalue"] is not None
    effect = {
        "First": samples[0].label, "Second": samples[1].label,
        "Difference": summary["difference"], "SE": summary["se"], "df": summary["df"],
        "t": summary["statistic"], "p": summary["pvalue"],
        "CI low": summary["ci_lower"], "CI high": summary["ci_upper"],
        "Confidence level (%)": _percent(options, LEVEL, 95.0, "yuen.error.level",
                                         low=0.0, high=100.0, exclusive_low=True),
        "Inference": "Available" if available else "Not available",
    }
    if not available:
        effect["Reason"] = REASON_SE
    return Result({GROUPS_SHEET: groups, EFFECT_SHEET: _report(effect)})


# ----- arithmetic ----------------------------------------------------------------------------------------------------

class _Sample:
    def __init__(self, field, label, n_before, values, grouped):
        self.field = field
        self.label = label
        self.n_before = int(n_before)
        self.values = values
        self.n_after = len(values)
        self.grouped = grouped
        self.removed = self.effective = None
        self.mean = self.component = None


def _fraction(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _vector(values):
    if isinstance(values, (str, bytes)):
        raise ValueError("a sample must be a finite vector")
    data = []
    for item in values:
        number = _fraction(item)
        if number is None:
            raise ValueError("a sample must be a finite vector")
        data.append(number)
    return data


def _component(values, trim):
    """Trimmed mean, variance component and effective size, or ``ValueError`` before any division by h < 2."""
    n = len(values)
    removed = removed_per_tail(n, trim)
    effective = n - 2 * removed
    if effective < 2:
        raise ValueError("fewer than 2 observations remain after trimming")
    mean, component = _moments(sorted(values), removed, effective)
    if not (math.isfinite(mean) and math.isfinite(component) and component >= 0):
        raise OverflowError("trimmed mean or variance is not finite")
    return mean, component, effective


def _moments(ordered, removed, effective):
    """Trimmed mean and ``d``. Direct sums when the values are not huge next to their spread."""
    n = len(ordered)
    central = ordered[removed:n - removed]
    low, high = central[0], central[-1]
    direct_mean, direct_d = _direct_moments(ordered, central, low, high, removed, effective)
    if direct_d == 0.0 and low == high:
        return direct_mean, 0.0
    scaled_mean, scaled_d, spread = _scaled_moments(central, low, high, removed, effective, n)
    modest = math.isfinite(direct_mean) and math.isfinite(direct_d) and direct_d >= 0
    if modest and (spread == 0.0 or max(abs(low), abs(high)) <= _CANCEL_RATIO * spread):
        return direct_mean, direct_d
    if not (math.isfinite(scaled_mean) and math.isfinite(scaled_d) and scaled_d >= 0):
        raise OverflowError("trimmed mean or variance is not finite")
    return scaled_mean, scaled_d


def _direct_moments(ordered, central, low, high, removed, effective):
    n = len(ordered)
    winsor = [low] * removed + central + [high] * removed
    trimmed = math.fsum(central) / effective
    center = math.fsum(winsor) / n
    component = math.fsum((item - center) ** 2 for item in winsor) / (effective * (effective - 1))
    return trimmed, component


def _scaled_moments(central, low, high, removed, effective, n):
    """The same moments after shifting by the lower retained value and scaling the deviations."""
    shifted = [item - low for item in central]
    span = high - low
    if not all(math.isfinite(item) for item in (*shifted, span)):
        raise OverflowError("trimmed mean or variance is not finite")
    trimmed = low + math.fsum(shifted) / effective
    center = (math.fsum(shifted) + removed * span) / n
    deviations = [item - center for item in shifted]
    low_dev, high_dev = -center, span - center
    if not all(math.isfinite(item) for item in (*deviations, trimmed, center, low_dev, high_dev)):
        raise OverflowError("trimmed mean or variance is not finite")
    spread = max([abs(low_dev), abs(high_dev), *(abs(item) for item in deviations)], default=0.0)
    if spread == 0.0:
        return trimmed, 0.0, 0.0
    squares = math.fsum((item / spread) ** 2 for item in deviations)
    squares += removed * ((low_dev / spread) ** 2 + (high_dev / spread) ** 2)
    component = squares * spread * spread / (effective * (effective - 1))
    return trimmed, component, spread


def _degrees(d_a, d_b, h_a, h_b):
    """Welch–Satterthwaite degrees of freedom. A zero component contributes the other sample's h − 1."""
    if d_a == 0.0:
        return float(h_b - 1)
    if d_b == 0.0:
        return float(h_a - 1)
    scale = max(d_a, d_b)
    left, right = d_a / scale, d_b / scale
    return (left + right) ** 2 / (left * left / (h_a - 1) + right * right / (h_b - 1))


# ----- worksheet -----------------------------------------------------------------------------------------------------

def _percent(options, field, default, key, *, low, high, exclusive_low):
    value = options.get(field, default)
    number = _fraction(value)
    inside = number is not None and (low < number < high if exclusive_low else low <= number < high)
    if not inside:
        raise FieldError(field, text(key))
    return number


def _flag(options):
    value = options.get(REVERSE, False)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise FieldError(REVERSE, text("yuen.error.reverse"))


def _column(frame, options, field):
    name = options.get(field)
    if not isinstance(name, str) or not name:
        raise FieldError(field, text("yuen.error.column", field=field))
    matches = [column for column in frame.columns if column == name]
    if not matches:
        raise FieldError(field, text("yuen.error.missing", field=field, name=name))
    if len(matches) > 1:
        raise FieldError(field, text("yuen.error.duplicate", name=name))
    return name


def _label(raw):
    if isinstance(raw, str):
        cleaned = raw.strip()
        return cleaned or None
    if isinstance(raw, (bool, np.bool_)):
        return bool(raw)
    if _blank(raw):
        return None
    if isinstance(raw, np.generic):
        raw = raw.item()
    return raw


def _finite(series, field):
    values = _numbers(series, field)
    return [float(item) for item in values[np.isfinite(values)]]


def _read(frame, options, layout):
    if layout == COLUMNS:
        first, second = _column(frame, options, FIRST), _column(frame, options, SECOND)
        if first == second:
            raise FieldError(SECOND, text("yuen.error.distinct"))
        return (
            _Sample(FIRST, first, len(frame[first]), _finite(frame[first], FIRST), False),
            _Sample(SECOND, second, len(frame[second]), _finite(frame[second], SECOND), False),
        )
    response, group = _column(frame, options, RESPONSE), _column(frame, options, GROUP)
    if response == group:
        raise FieldError(GROUP, text("yuen.error.distinct"))
    measured = _numbers(frame[response], RESPONSE)
    buckets, counts, labels = {}, {}, []
    for raw, value in zip(frame[group].tolist(), measured.tolist()):
        label = _label(raw)
        if label is None:
            continue
        known = next((item for item in labels if item == label), None)
        if known is None:
            labels.append(label)
            buckets[id(label)] = []
            counts[id(label)] = 0
            known = label
        buckets[id(known)].append(value)
        counts[id(known)] += 1
    if len(labels) != 2:
        raise FieldError(GROUP, text("yuen.error.groups", field=GROUP, count=len(labels)))
    order = _order(labels, options)
    options[GROUP_ORDER] = list(order)
    samples = []
    for label in order:
        column = buckets[id(label)]
        finite = [float(item) for item in column if math.isfinite(float(item))]
        samples.append(_Sample(RESPONSE, label, counts[id(label)], finite, True))
    return tuple(samples)


def _order(labels, options):
    saved = options.get(GROUP_ORDER)
    if not isinstance(saved, (list, tuple)) or len(saved) != len(labels):
        return list(labels)
    chosen, used = [], []
    for item in saved:
        match = next((label for label in labels if label == item and label not in used), None)
        if match is None:
            return list(labels)
        chosen.append(match)
        used.append(match)
    return chosen


def _checked(sample, fraction):
    if sample.n_after < 2:
        key = "yuen.error.short_group" if sample.grouped else "yuen.error.short"
        raise FieldError(sample.field, text(key, field=sample.field, sample=sample.label, count=sample.n_after))
    removed = removed_per_tail(sample.n_after, fraction)
    effective = sample.n_after - 2 * removed
    if effective < 2:
        raise FieldError(TRIM, text("yuen.error.trim_short", field=TRIM, kept=effective, sample=sample.label))
    try:
        mean, component = _moments(sorted(sample.values), removed, effective)
    except OverflowError as error:
        raise _overflow(sample) from error
    if not (math.isfinite(mean) and math.isfinite(component)):
        raise _overflow(sample)
    sample.removed, sample.effective = removed, effective
    sample.mean, sample.component = mean, component
    return sample


def _overflow(sample):
    key = "yuen.error.overflow_group" if sample.grouped else "yuen.error.overflow"
    return FieldError(sample.field, text(key, field=sample.field, sample=sample.label))
