"""Optional variance-homogeneity checks after ordinary one-way ANOVA.

Brown–Forsythe here is Levene's test centered on the group median. It is not
the Brown–Forsythe F* test of means in ``unequal_anova.py``, and a small p
value does not switch Method to Welch. Bartlett uses the classical correction.
A defined test keeps Reason empty; Bartlett's sensitivity to non-normal data
is stated on the dialog, because the sheet columns are fixed.

Undefined statistics stay missing. A zero Bartlett variance or a zero
Brown–Forsythe denominator is unavailable even when SciPy reports infinity.
The ANOVA result has no figure; these checks do not add one.
"""
import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .stats import complete

BROWN = "Brown–Forsythe variance test"
BARTLETT = "Bartlett variance test"
ALPHA = "Variance test alpha"
DEFAULT_ALPHA = 0.05
TAB = "Diagnostics/Assumptions"
SHEET = "Variance assumptions"
GROUPS = "Variance groups"
BROWN_NAME = "Brown–Forsythe (median Levene)"
BARTLETT_NAME = "Bartlett"
REJECT = "Reject"
KEEP = "Do not reject"
UNAVAILABLE = "NA"
COLUMNS = ("Test", "Statistic", "df1", "df2", "p", "Alpha", "Decision", "Reason")
GROUP_COLUMNS = ("Group", "N", "Mean", "Median", "SD", "Absolute deviation mean")

LABEL_KEYS = {
    TAB: "variance.assumptions.tab",
    BROWN: "variance.assumptions.brown",
    BARTLETT: "variance.assumptions.bartlett",
    ALPHA: "variance.assumptions.alpha",
}
_FIELDS = frozenset({BROWN, BARTLETT, ALPHA})


def _say(key, english):
    """English until the catalog has the key, then the active language."""
    from .i18n import tr
    translated = tr(key)
    return english if translated == key else translated


def _flag(options, key):
    if key not in options:
        return False
    value = options[key]
    if type(value) is not bool:
        raise FieldError(key, _say("variance.assumptions.error.bool", "Choose yes or no."))
    return value


def _alpha(options):
    if ALPHA not in options:
        return DEFAULT_ALPHA
    value = options[ALPHA]
    if isinstance(value, str):
        from .data import decimal_comma
        try:
            value = float(decimal_comma(value))
        except (TypeError, ValueError):
            raise FieldError(ALPHA, _say(
                "variance.assumptions.error.alpha_number",
                "Alpha must be a number between 0 and 1.")) from None
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise FieldError(ALPHA, _say(
            "variance.assumptions.error.alpha_number",
            "Alpha must be a number between 0 and 1."))
    if isinstance(options[ALPHA], bool) or not np.isfinite(value) or not 0 < value < 1:
        raise FieldError(ALPHA, _say(
            "variance.assumptions.error.alpha_range",
            "Alpha must be a finite number greater than 0 and less than 1."))
    return value


def validate(options):
    """Check flags and alpha. Welch and a fully off recipe ignore hidden text."""
    if options.get("Method", "Ordinary") != "Ordinary":
        return
    if not (_flag(options, BROWN) or _flag(options, BARTLETT)):
        return
    _alpha(options)


def _plain(label):
    if isinstance(label, np.generic):
        return label.item()
    return label


def _collect(frame, response, group):
    data = complete(frame, [response], [group])
    groups = []
    for label, part in data.groupby(group, sort=False, observed=True):
        groups.append((_plain(label), part[response].to_numpy(dtype=float).copy()))
    return groups


def _join(labels):
    return ", ".join(str(label) for label in labels)


def _few(labels):
    key = "variance.assumptions.reason.few" if len(labels) == 1 else "variance.assumptions.reason.few_many"
    english = ("Group {groups} has fewer than 2 complete observations." if len(labels) == 1
               else "Groups {groups} have fewer than 2 complete observations.")
    return _say(key, english).replace("{groups}", _join(labels))


def _zero(labels):
    key = "variance.assumptions.reason.zero" if len(labels) == 1 else "variance.assumptions.reason.zero_many"
    english = ("Group {groups} has zero variance." if len(labels) == 1
               else "Groups {groups} have zero variance.")
    return _say(key, english).replace("{groups}", _join(labels))


def _constant():
    return _say("variance.assumptions.reason.constant",
                "Brown–Forsythe is undefined because the absolute deviations are constant within every group.")


def _blank(name, alpha, reason, df1, df2):
    return {"Test": name, "Statistic": np.nan, "df1": df1, "df2": df2, "p": np.nan,
            "Alpha": alpha, "Decision": UNAVAILABLE, "Reason": reason}


def _decision(p, alpha):
    return REJECT if p < alpha else KEEP


def _brown(groups, alpha):
    sizes = np.array([len(values) for _, values in groups])
    k = len(groups)
    df1 = k - 1
    df2 = int(sizes.sum() - k)
    small = [label for label, values in groups if len(values) < 2]
    if small:
        return _blank(BROWN_NAME, alpha, _few(small), df1, df2)
    deviations = [np.abs(values - np.median(values)) for _, values in groups]
    peak = max((float(np.max(dev)) for dev in deviations), default=0.0)
    if not np.isfinite(peak) or peak == 0:
        return _blank(BROWN_NAME, alpha, _constant(), df1, df2)
    scaled = [dev / peak for dev in deviations]
    counts = sizes.astype(float)
    means = np.array([dev.mean() for dev in scaled])
    grand = np.average(means, weights=counts)
    numerator = float(np.sum(counts * np.square(means - grand)))
    denominator = float(sum(np.sum(np.square(dev - mean)) for dev, mean in zip(scaled, means)))
    if not np.isfinite(denominator) or not denominator > 0:
        return _blank(BROWN_NAME, alpha, _constant(), df1, df2)
    statistic = (counts.sum() - k) * numerator / (df1 * denominator)
    p = float(stats.f.sf(statistic, df1, df2))
    if not np.isfinite(statistic) or not np.isfinite(p):
        return _blank(BROWN_NAME, alpha, _constant(), df1, df2)
    return {"Test": BROWN_NAME, "Statistic": float(statistic), "df1": df1, "df2": df2,
            "p": p, "Alpha": alpha, "Decision": _decision(p, alpha), "Reason": ""}


def _bartlett(groups, alpha):
    sizes = np.array([len(values) for _, values in groups])
    k = len(groups)
    df1 = k - 1
    small = [label for label, values in groups if len(values) < 2]
    if small:
        return _blank(BARTLETT_NAME, alpha, _few(small), df1, np.nan)
    centered = [values - np.mean(values) for _, values in groups]
    peak = max((float(np.max(np.abs(dev))) for dev in centered), default=0.0)
    flat = [label for (label, _), dev in zip(groups, centered) if not np.max(np.abs(dev)) > 0]
    if flat or not np.isfinite(peak) or peak == 0:
        return _blank(BARTLETT_NAME, alpha, _zero(flat or [label for label, _ in groups]), df1, np.nan)
    degrees = sizes.astype(float) - 1
    variances = np.array([float(np.dot(dev / peak, dev / peak) / (len(dev) - 1)) for dev in centered])
    dead = [label for (label, _), variance in zip(groups, variances) if not variance > 0]
    if dead or not np.isfinite(variances).all():
        return _blank(BARTLETT_NAME, alpha, _zero(dead or [label for label, _ in groups]), df1, np.nan)
    total = float(degrees.sum())
    pooled = float(np.sum(degrees * variances) / total)
    if not pooled > 0:
        return _blank(BARTLETT_NAME, alpha, _zero([label for label, _ in groups]), df1, np.nan)
    numerator = total * np.log(pooled) - float(np.sum(degrees * np.log(variances)))
    correction = 1 + (float(np.sum(1 / degrees)) - 1 / total) / (3 * df1)
    statistic = float(numerator / correction)
    p = float(stats.chi2.sf(statistic, df1))
    if not np.isfinite(statistic) or not np.isfinite(p):
        return _blank(BARTLETT_NAME, alpha, _zero([label for label, _ in groups]), df1, np.nan)
    return {"Test": BARTLETT_NAME, "Statistic": statistic, "df1": df1, "df2": np.nan,
            "p": p, "Alpha": alpha, "Decision": _decision(p, alpha), "Reason": ""}


def _group_table(groups):
    rows = []
    for label, values in groups:
        count = len(values)
        deviation = np.abs(values - np.median(values))
        rows.append({
            "Group": label,
            "N": count,
            "Mean": float(np.mean(values)),
            "Median": float(np.median(values)),
            "SD": float(np.std(values, ddof=1)) if count >= 2 else np.nan,
            "Absolute deviation mean": float(np.mean(deviation)),
        })
    return pd.DataFrame(rows, columns=GROUP_COLUMNS)


def sheets(frame, response, group, options):
    """Return the two sheets, or nothing when the checks are off or not ordinary."""
    validate(options)
    if options.get("Method", "Ordinary") != "Ordinary":
        return {}
    brown, bartlett = _flag(options, BROWN), _flag(options, BARTLETT)
    if not brown and not bartlett:
        return {}
    alpha = _alpha(options)
    groups = _collect(frame, response, group)
    rows = []
    if brown:
        rows.append(_brown(groups, alpha))
    if bartlett:
        rows.append(_bartlett(groups, alpha))
    table = pd.DataFrame(rows, columns=COLUMNS)
    return {SHEET: table, GROUPS: _group_table(groups)}


def format_variance_error(error):
    """Prefix a variance-field error with the translated caption. None for other errors."""
    field = getattr(error, "field", None)
    if field not in _FIELDS:
        return None
    from .i18n import tr, translate_message
    text = translate_message(str(error), "variance.assumptions.error.")
    label = tr(LABEL_KEYS[field])
    if label and label not in text:
        return f"{label}: {text}"
    return text
