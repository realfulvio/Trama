"""One-way ANOVA for lognormal observations: one shared log offset, geometric summaries, ratios.

The legacy Normal path never enters this module. Lognormal reuses ``inference.one_way_anova``
on the natural logs of every used observation. Groups are not centered separately: that would
remove the effects. Geometric means put the common offset back. Ratios exponentiate the
existing contrasts. Overflow becomes a missing ratio with the log contrast kept, never 0 or
infinity.

Repeated measures and a lognormal linear trend are refused. Brown–Forsythe in the ANOVA table
is the original F* test of means (df1 = k − 1). The optional homogeneity sheet is the
median-centered Levene test, and both homogeneity checks run on the logs when requested.
"""
from math import sqrt

import numpy as np
import pandas as pd
from scipy import stats

from . import inference, unequal_anova, variance_assumptions
from .field_error import FieldError
from .lognormality import centered_logs
from .reporting import Result, _report
from .stats import complete
from .trend_anova import TREND

DISTRIBUTION = "Distribution"
NORMAL, LOGNORMAL = DISTRIBUTIONS = ("Normal", "Lognormal")
RATIO_DIRECTION = "Ratio direction"
FIRST_OVER_SECOND, SECOND_OVER_FIRST = DIRECTIONS = ("First / Second", "Second / First")
SUMMARY = "Geometric summary"
SETTINGS = "Lognormal settings"
AVAILABLE, UNREPRESENTABLE = "Available", "Unrepresentable"
INTERVAL_LABELS = frozenset({
    "Tukey", unequal_anova.DUNNETT, "Games–Howell", unequal_anova.TAMHANE, unequal_anova.DUNNETT_T3,
})
_POSTHOC = {
    "None": None, "Tukey": "tukey", unequal_anova.DUNNETT: "dunnett", "Games–Howell": "games-howell",
    **unequal_anova.UNEQUAL_POSTHOC_KEYS, "Holm": "holm", "Bonferroni": "bonferroni",
    "FDR (Benjamini–Hochberg)": "fdr_bh",
}
_RANGE = frozenset({"tukey", "games-howell"})
_P_ONLY = frozenset({"holm", "bonferroni", "fdr_bh"})

LABEL_KEYS = {
    DISTRIBUTION: "anova.lognormal.field.distribution",
    RATIO_DIRECTION: "anova.lognormal.field.direction",
}
CHOICE_KEYS = {
    NORMAL: "anova.lognormal.choice.normal",
    LOGNORMAL: "anova.lognormal.choice.lognormal",
    FIRST_OVER_SECOND: "anova.lognormal.choice.first_second",
    SECOND_OVER_FIRST: "anova.lognormal.choice.second_first",
}
_FIELDS = frozenset({DISTRIBUTION, RATIO_DIRECTION, TREND, "Response", unequal_anova.LEVEL})
_ERROR_KEYS = (
    "anova.lognormal.error.distribution", "anova.lognormal.error.repeated",
    "anova.lognormal.error.posthoc", "anova.lognormal.error.direction",
    "anova.lognormal.error.trend", "anova.lognormal.error.positive",
    "anova.lognormal.error.level",
)
# English sentences raised by this module. The catalog may translate them; a Normal-path
# sentence that merely shares Linear trend, Response, or the confidence level does not match.
_EN_ERRORS = (
    "Choose Normal or Lognormal.",
    "Repeated measures ANOVA does not support a lognormal distribution.",
    "Choose a post-hoc test offered for one-way ANOVA.",
    "Choose First / Second or Second / First.",
    "A lognormal linear trend is not available. Turn Linear trend off or choose Normal.",
    "Used observations in {response} must be finite and strictly positive.",
    "Confidence level (%) must be finite and strictly between 0 and 100.",
)


def _say(key, english, **values):
    """English until the catalog has the key, then the active language. Placeholders stay literal."""
    from .i18n import tr
    translated = tr(key)
    text = english if translated == key else translated
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def active(options):
    """True for a lognormal recipe. A missing key or Normal stays on the legacy path."""
    if DISTRIBUTION not in options or options[DISTRIBUTION] in (None, NORMAL):
        return False
    if options[DISTRIBUTION] == LOGNORMAL:
        return True
    raise FieldError(DISTRIBUTION, _say(
        "anova.lognormal.error.distribution", "Choose Normal or Lognormal."))


def reject_repeated(options):
    """Repeated measures are outside this analysis. Anything else is left untouched."""
    if options.get(DISTRIBUTION) == LOGNORMAL:
        raise FieldError(DISTRIBUTION, _say(
            "anova.lognormal.error.repeated",
            "Repeated measures ANOVA does not support a lognormal distribution."))


def _posthoc(options):
    label = options.get("Post-hoc", "None")
    if label not in _POSTHOC:
        raise FieldError("Post-hoc", _say(
            "anova.lognormal.error.posthoc", "Choose a post-hoc test offered for one-way ANOVA."))
    return label, _POSTHOC[label]


def _direction(options, requested):
    """Direction applies only when a lognormal post-hoc test is requested."""
    if not requested:
        return None
    direction = options.get(RATIO_DIRECTION, FIRST_OVER_SECOND)
    if direction not in DIRECTIONS:
        raise FieldError(RATIO_DIRECTION, _say(
            "anova.lognormal.error.direction", "Choose First / Second or Second / First."))
    return direction


def _level(options, label):
    """Intervals honor the chosen level. A post-hoc test without intervals ignores the field."""
    if label not in INTERVAL_LABELS:
        return unequal_anova.DEFAULT_LEVEL
    return unequal_anova.confidence_level(options.get(unequal_anova.LEVEL, unequal_anova.DEFAULT_LEVEL))


def validate_request(options):
    """Field errors for an unsupported or incomplete lognormal recipe. Normal recipes are not checked."""
    if not active(options):
        return None
    if options.get(TREND):
        raise FieldError(TREND, _say(
            "anova.lognormal.error.trend",
            "A lognormal linear trend is not available. Turn Linear trend off or choose Normal."))
    label, key = _posthoc(options)
    direction = _direction(options, key is not None)
    level = _level(options, label)
    unequal_anova.check_one_way_options(options)
    variance_assumptions.validate(options)
    return label, key, direction, level


def _identity(value):
    """Group identity that does not treat True, 1 and \"1\" as the same level."""
    if isinstance(value, (bool, np.bool_)):
        return ("bool", bool(value))
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, (np.integer, int)):
        return ("int", int(value))
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if np.isnan(number):
            return ("nan",)
        return ("float", number)
    return ("other", type(value).__name__, repr(value))


def _collides(labels):
    seen = []
    for label in labels:
        identity = _identity(label)
        for previous, previous_id in seen:
            if label == previous and identity != previous_id:
                return True
        seen.append((label, identity))
    return False


def _exp_finite(value):
    """Finite positive exponential, or NaN when the result would be 0 or infinity."""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return np.nan
    if not np.isfinite(value):
        return np.nan
    # finfo.tiny is the smallest *normal* number. Let the exponential round
    # naturally so positive subnormal means and ratio limits are retained.
    with np.errstate(over="ignore", under="ignore"):
        result = float(np.exp(value))
    if np.isfinite(result) and result > 0:
        return result
    return np.nan


def _prepare(frame, response, group):
    """Complete rows first, then refuse any used nonpositive value. The source frame is not written."""
    data = complete(frame, [response], [group])
    values = data[response].to_numpy(dtype=float, copy=True)
    if values.size and (not np.isfinite(values).all() or np.any(values <= 0)):
        raise FieldError("Response", _say(
            "anova.lognormal.error.positive",
            "Used observations in {response} must be finite and strictly positive.",
            response=response))
    logs, offset = centered_logs(values) if values.size else (np.array([], dtype=float), np.nan)
    logged = data.copy()
    logged[response] = logs
    labels, positions = [], {}
    for label in data[group].tolist():
        identity = _identity(label)
        if identity not in positions:
            positions[identity] = len(labels)
            labels.append(label)
    # Row order follows the completed frame, which is the source order of used rows.
    members = [[] for _ in labels]
    for index, label in enumerate(data[group].tolist()):
        members[positions[_identity(label)]].append(index)
    engine = logged
    restore = None
    if _collides(labels):
        tokens = [f"\x1e{index}" for index in range(len(labels))]
        restore = dict(zip(tokens, labels))
        mapped = []
        for label in data[group].tolist():
            mapped.append(tokens[positions[_identity(label)]])
        engine = logged.copy()
        engine[group] = mapped
    return {
        "logged": engine, "logs": logs, "offset": float(offset) if values.size else np.nan,
        "labels": labels, "members": members, "restore": restore, "omitted": len(frame) - len(data),
        "used": len(data),
    }


def _family(options, prepared):
    """Translate control and pairs only when pandas would merge typed labels. Otherwise pass them through."""
    if prepared["restore"] is None:
        return options
    labels = prepared["labels"]
    tokens = [f"\x1e{index}" for index in range(len(labels))]
    family = dict(options)
    control = options.get(unequal_anova.CONTROL)
    if control is not None:
        matches = [token for label, token in zip(labels, tokens) if str(label) == control]
        if len(matches) == 1:
            family[unequal_anova.CONTROL] = matches[0]
        else:
            raise FieldError(unequal_anova.CONTROL, "Choose an observed group with an unambiguous label.")
    selected = options.get(unequal_anova.PAIRS)
    if selected:
        by_text = {}
        for label, token in zip(labels, tokens):
            by_text.setdefault(str(label), []).append(token)
        rewritten = []
        for pair in selected:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                rewritten.append(pair)
                continue
            mapped = []
            usable = True
            for item in pair:
                hits = by_text.get(item, [])
                if len(hits) != 1:
                    usable = False
                    break
                mapped.append(hits[0])
            rewritten.append(tuple(mapped) if usable else pair)
        family[unequal_anova.PAIRS] = rewritten
    return family


def _restore_label(value, restore):
    if restore is None:
        return value
    return restore.get(value, value)


def _summary(prepared):
    rows = []
    for label, indexes in zip(prepared["labels"], prepared["members"]):
        centered = prepared["logs"][indexes]
        log_mean = float(centered.mean() + prepared["offset"]) if len(centered) else np.nan
        log_sd = float(centered.std(ddof=1)) if len(centered) >= 2 else np.nan
        geometric_mean = _exp_finite(log_mean)
        geometric_sd = _exp_finite(log_sd) if len(centered) >= 2 else np.nan
        notes = []
        if len(centered) < 2:
            notes.append("At least two observations are required for a geometric SD.")
        if len(centered) >= 2 and not np.isfinite(geometric_sd):
            notes.append("Geometric SD is outside the finite positive range. Log SD is retained.")
        if not np.isfinite(geometric_mean):
            notes.append("Geometric mean is outside the finite positive range. Log mean is retained.")
        rows.append({
            "Group": label, "N": len(centered), "Geometric mean": geometric_mean,
            "Geometric SD": geometric_sd, "Log mean": log_mean, "Log SD": log_sd,
            "Note": " ".join(notes),
        })
    summary = pd.DataFrame(rows, columns=["Group", "N", "Geometric mean", "Geometric SD", "Log mean", "Log SD", "Note"])
    summary["Group"] = pd.Series(prepared["labels"], dtype=object)
    return summary


def _retarget_range(comparisons, level, groups):
    """Tukey and Games–Howell in the shared engine fix the interval at 95%. Lognormal uses the chosen level."""
    if "CI 95% low" not in comparisons.columns:
        return comparisons
    differences = comparisons["Difference"].to_numpy(dtype=float)
    se = comparisons["SE"].to_numpy(dtype=float)
    degrees = comparisons["df"].to_numpy(dtype=float)
    critical = stats.studentized_range.ppf(level / 100, groups, degrees)
    half = critical * se / sqrt(2)
    comparisons = comparisons.copy()
    comparisons["CI 95% low"] = differences - half
    comparisons["CI 95% high"] = differences + half
    return comparisons


def _ratios(comparisons, direction, level, has_interval):
    frame = comparisons.reset_index()
    log_difference = frame["Difference"].to_numpy(dtype=float)
    low_name = "CI low" if "CI low" in frame.columns else "CI 95% low" if "CI 95% low" in frame.columns else None
    high_name = "CI high" if "CI high" in frame.columns else "CI 95% high" if "CI 95% high" in frame.columns else None
    log_low = frame[low_name].to_numpy(dtype=float) if low_name else None
    log_high = frame[high_name].to_numpy(dtype=float) if high_name else None
    if direction == SECOND_OVER_FIRST:
        numerator, denominator = frame["Second"].tolist(), frame["First"].tolist()
        log_ratio = -log_difference
        if log_low is not None:
            ratio_low_log, ratio_high_log = -log_high, -log_low
        else:
            ratio_low_log = ratio_high_log = None
    else:
        numerator, denominator = frame["First"].tolist(), frame["Second"].tolist()
        log_ratio = log_difference
        ratio_low_log, ratio_high_log = log_low, log_high
    ratio = np.array([_exp_finite(value) for value in log_ratio], dtype=float)
    if has_interval and ratio_low_log is not None:
        ratio_low = np.array([_exp_finite(value) for value in ratio_low_log], dtype=float)
        ratio_high = np.array([_exp_finite(value) for value in ratio_high_log], dtype=float)
    else:
        ratio_low = np.full(len(frame), np.nan)
        ratio_high = np.full(len(frame), np.nan)
    status, reason = [], []
    for index in range(len(frame)):
        missing = []
        if not np.isfinite(log_ratio[index]):
            missing.append("Log ratio")
        if not np.isfinite(ratio[index]):
            missing.append("Ratio")
        if has_interval:
            if not np.isfinite(ratio_low[index]):
                missing.append("Ratio CI low")
            if not np.isfinite(ratio_high[index]):
                missing.append("Ratio CI high")
        if missing:
            status.append(UNREPRESENTABLE)
            reason.append(
                f"{', '.join(missing)} is outside the finite positive range. "
                "Finite log contrasts are retained. No silent 0 or infinity is reported.")
        elif has_interval:
            status.append(AVAILABLE)
            reason.append("Simultaneous ratio interval.")
        else:
            status.append(AVAILABLE)
            reason.append("Point ratio only. This correction adjusts p values and does not produce an interval.")
    renamed = frame.rename(columns={"Difference": "Log difference", "SE": "Log SE"})
    drop = [name for name in ("CI low", "CI high", "CI 95% low", "CI 95% high") if name in renamed.columns]
    renamed = renamed.drop(columns=drop)
    if log_low is not None:
        renamed["Log CI low"] = log_low
        renamed["Log CI high"] = log_high
        renamed[unequal_anova.LEVEL] = level
    renamed["Numerator"] = pd.Series(numerator, dtype=object)
    renamed["Denominator"] = pd.Series(denominator, dtype=object)
    renamed["Log ratio"] = log_ratio
    renamed["Ratio"] = ratio
    renamed["Ratio CI low"] = ratio_low
    renamed["Ratio CI high"] = ratio_high
    renamed["Ratio status"] = status
    renamed["Ratio reason"] = reason
    renamed = renamed.drop(columns=["Comparison"], errors="ignore")
    return renamed


def _mark_scale(table):
    marked = table.copy()
    marked["Scale"] = "Natural logarithms"
    return marked


def _variance(frame, response, group, options, restore, offset):
    sheets = variance_assumptions.sheets(frame, response, group, options)
    if not sheets:
        return {}
    assumptions = sheets[variance_assumptions.SHEET].copy()
    assumptions["Scale"] = "Natural logarithms"
    assumptions["Note"] = (
        "Brown–Forsythe here is the median-centered Levene test on natural logarithms, "
        "not the Brown–Forsythe F* test of means. Bartlett also uses the natural logarithms. "
        "Equal variance means equal geometric SD.")
    groups = sheets[variance_assumptions.GROUPS].copy()
    if restore is not None:
        groups["Group"] = [_restore_label(value, restore) for value in groups["Group"]]
        groups["Group"] = pd.Series(groups["Group"].tolist(), dtype=object)
    # The engine sees centered logs. Put the common offset back so Log mean is ln of the geometric mean.
    if np.isfinite(offset):
        groups["Mean"] = groups["Mean"] + offset
        groups["Median"] = groups["Median"] + offset
    groups = groups.rename(columns={
        "Mean": "Log mean", "Median": "Log median", "SD": "Log SD",
        "Absolute deviation mean": "Log absolute deviation mean",
    })
    groups["Scale"] = "Natural logarithms"
    return {variance_assumptions.SHEET: assumptions, variance_assumptions.GROUPS: groups}


def _settings(offset, level, direction, label, omitted, used, variance_on):
    interval = label in INTERVAL_LABELS
    values = {
        "Distribution": LOGNORMAL,
        "Common log offset": offset,
        "Log base": "e (natural)",
        "Test units": "Natural logarithms",
        "Sum of squares units": "Squared natural logarithms",
        "Confidence level (%)": level if interval else "Not used",
        "Ratio direction": direction if direction else "Not used",
        "Observations used": used,
        "Observations omitted": omitted,
        "Variance checks": (
            "Brown–Forsythe homogeneity and Bartlett, when selected, use the natural logarithms. "
            "They are not the Brown–Forsythe F* test of means."
            if variance_on else "Not requested"),
        "Support": (
            "Independent groups and raw positive observations. "
            "A lognormal linear trend and repeated measures are not available. "
            "Holm, Bonferroni and FDR adjust p values only and do not create intervals."),
    }
    return _report(values)


def check_used(frame, options):
    """Raise when a used response is not strictly positive. Normal recipes are not inspected."""
    if active(options):
        _prepare(frame, options["Response"], options["Group"])


def analysis(frame, options):
    """Lognormal one-way ANOVA. ``frame`` is not modified."""
    checked = validate_request(options)
    if checked is None:
        raise FieldError(DISTRIBUTION, _say(
            "anova.lognormal.error.distribution", "Choose Normal or Lognormal."))
    label, key, direction, level = checked
    response, group = options["Response"], options["Group"]
    prepared = _prepare(frame, response, group)
    tables = inference.one_way_anova(
        prepared["logged"], response, group, method=unequal_anova.METHOD_KEYS[options["Method"]],
        posthoc=key, level=level, family=_family(options, prepared))
    tables["ANOVA"] = _mark_scale(tables["ANOVA"])
    tables[SUMMARY] = _summary(prepared)
    if "Multiple comparisons" in tables:
        comparisons = tables["Multiple comparisons"]
        if prepared["restore"] is not None:
            comparisons = comparisons.copy()
            for column in ("First", "Second"):
                comparisons[column] = [_restore_label(value, prepared["restore"]) for value in comparisons[column]]
        if key in _RANGE:
            comparisons = _retarget_range(comparisons, level, len(prepared["labels"]))
        tables["Multiple comparisons"] = _ratios(
            comparisons, direction, level, has_interval=key not in _P_ONLY and key is not None)
    variance = _variance(
        prepared["logged"], response, group, options, prepared["restore"], prepared["offset"])
    tables.update(variance)
    tables[SETTINGS] = _settings(
        prepared["offset"], level, direction, label, prepared["omitted"], prepared["used"], bool(variance))
    return Result(tables)


def _owns(text):
    """True when the sentence was raised for this analysis, in either catalog language."""
    from . import i18n
    templates = list(_EN_ERRORS)
    for key in _ERROR_KEYS:
        templates.extend(template for template in (i18n._EN.get(key, ""), i18n._IT.get(key, "")) if template)
    for template in templates:
        if not template:
            continue
        if "{response}" in template:
            head, tail = template.split("{response}", 1)
            if text.startswith(head) and text.endswith(tail):
                return True
        elif text == template:
            return True
    return False


def format_error(error):
    """Prefix a lognormal field error with its caption. None for other errors.

    Linear trend, Response and Confidence level are shared with the Normal path.
    Those historical sentences keep the dialog's existing wording.
    """
    field = getattr(error, "field", None)
    if field not in _FIELDS:
        return None
    from .i18n import tr, translate_message, ui
    original = str(error)
    text = translate_message(original, "anova.lognormal.error.")
    if text == original and not _owns(original):
        return None
    key = LABEL_KEYS.get(field)
    if field == TREND:
        key = "analysis.trend.heading.trend"
    elif field == "Response":
        key = None
    elif field == unequal_anova.LEVEL:
        key = "ratio_t.field.level"
    label = ui("Response") if field == "Response" else tr(key) if key else field
    if label and label not in text:
        return f"{label}: {text}"
    return text
