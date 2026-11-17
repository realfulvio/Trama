"""Ordinal linear trend and departure from linearity after ordinary one-way ANOVA.

Scores are the positions 1..k in the order the user declared. Group titles are
not doses. Unequal sizes weight each observation equally, which is the same as
weighting the group means by n_i. The two p values are planned tests and are
not adjusted again for multiplicity.
"""
import numpy as np
import pandas as pd
from scipy import stats

from .processing import FieldError
from .stats import complete

TREND = "Linear trend"
ORDER = "Trend group order"
ORDER_KIND = "Trend order"
SHEET = "Linear trend"
MEANS = "Trend group means"

_METRICS = (
    "N", "Groups", "Slope", "Intercept", "SS linear", "SS nonlinear", "SS between", "SS within",
    "SS total", "df linear", "df nonlinear", "df within", "F linear", "p linear", "F nonlinear",
    "p nonlinear", "R² effect", "R² alerting", "Convention", "Note",
)
_CONVENTION = ("ordinal scores 1, 2, …, k in the declared group order; "
               "unequal sizes weight the raw observations by n_i")


def _say(key, english):
    """English until the catalog has the key, then the active language."""
    from .i18n import tr
    translated = tr(key)
    return english if translated == key else translated


def _missing(value):
    return value is None or (isinstance(value, float) and np.isnan(value)) or pd.isna(value)


def _as_number(value):
    number = float(value)
    if not np.isfinite(number):
        raise ValueError
    if number.is_integer() and abs(number) < 2**53:
        return int(number)
    return number


def _identity(value):
    """Typed level, or None when the trend cannot represent the value."""
    if isinstance(value, (bool, np.bool_)):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        try:
            return ("number", _as_number(value))
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(value, str):
        return ("text", value)
    return None


def _entry(item):
    if not isinstance(item, dict):
        raise FieldError(ORDER, _say("analysis.trend.error.order_shape",
                                      "Trend group order must list each level as text or a finite number."))
    kind, value = item.get("kind"), item.get("value")
    if kind == "text" and isinstance(value, str):
        return {"kind": "text", "value": value}
    if kind == "number" and not isinstance(value, (bool, np.bool_)):
        try:
            return {"kind": "number", "value": _as_number(value)}
        except (TypeError, ValueError, OverflowError):
            pass
    raise FieldError(ORDER, _say("analysis.trend.error.order_shape",
                                  "Trend group order must list each level as text or a finite number."))


def _key(item):
    if item["kind"] == "number":
        return ("number", float(item["value"]))
    return ("text", item["value"])


def _label(item, ambiguous):
    shown = str(item["value"])
    if not ambiguous:
        return shown
    kind = _say("analysis.trend.kind.number", "number") if item["kind"] == "number" else _say(
        "analysis.trend.kind.text", "text")
    return f"{shown} [{kind}]"


def group_levels(frame, response, group):
    """Identities of the complete cases, in order of first appearance."""
    data = complete(frame, [response], [group])
    levels = []
    seen = set()
    for value in data[group]:
        identity = _identity(value)
        if identity is None:
            continue
        kind, stored = identity
        token = ("number", float(stored)) if kind == "number" else ("text", stored)
        if token in seen:
            continue
        seen.add(token)
        levels.append({"kind": kind, "value": stored})
    return levels


def _cases(frame, response, group):
    data = complete(frame, [response], [group])
    groups = []
    for label, part in data.groupby(group, sort=False, observed=True):
        identity = _identity(label)
        if identity is None:
            raise FieldError(TREND, _say(
                "analysis.trend.error.identity",
                "Linear trend cannot use this group level. Turn the trend off or remove the unsupported level."))
        values = part[response].to_numpy(dtype=float)
        groups.append(({"kind": identity[0], "value": identity[1]}, values))
    return groups


def _match_order(observed, order):
    parsed = [_entry(item) for item in order]
    wanted = [_key(item) for item in parsed]
    if len(wanted) != len(set(wanted)):
        raise FieldError(ORDER, _say("analysis.trend.error.duplicate",
                                      "Trend group order lists the same level more than once."))
    present = {_key(item): item for item, _ in observed}
    unknown = [item["value"] for item in parsed if _key(item) not in present]
    missing = [item["value"] for item, _ in observed if _key(item) not in set(wanted)]
    if unknown or missing or len(parsed) != len(observed):
        detail = unknown or missing
        raise FieldError(ORDER, _say(
            "analysis.trend.error.levels",
            "Trend group order must list each remaining level once. Review {levels}.").format(levels=", ".join(
                str(value) for value in detail)))
    return parsed


def _decomposition(ordered):
    sizes = np.array([len(values) for _, values in ordered], dtype=float)
    count = len(ordered)
    total_n = int(sizes.sum())
    if count < 2 or total_n - count <= 0:
        raise FieldError(TREND, _say(
            "analysis.trend.error.degrees",
            "Linear trend needs at least two groups and residual degrees of freedom."))
    origin = float(ordered[0][1][0])
    centered = [values - origin for _, values in ordered]
    means = np.array([sample.mean() for sample in centered], dtype=float)
    within = float(sum(np.square(sample - mean).sum() for sample, mean in zip(centered, means)))
    scores = np.arange(1, count + 1, dtype=float)
    weights = sizes
    xbar = float(np.sum(weights * scores) / total_n)
    ybar = float(np.sum(weights * means) / total_n)
    dx = scores - xbar
    dy = means - ybar
    sxx = float(np.sum(weights * dx * dx))
    sxy = float(np.sum(weights * dx * dy))
    between = float(np.sum(weights * dy * dy))
    if not np.isfinite([within, sxx, sxy, between]).all() or sxx <= 0:
        raise FieldError(TREND, _say(
            "analysis.trend.error.numeric",
            "Linear trend is outside the supported numeric range."))
    # Sxx is in score units, so it must not set the response tolerance.
    # A response scaled by 1e-12 keeps a real pooled variance far below Sxx.
    if within <= 0:
        raise FieldError(TREND, _say(
            "analysis.trend.error.variance",
            "Linear trend needs a positive pooled variance."))
    slope = sxy / sxx
    intercept = (ybar - slope * xbar) + origin
    linear = sxy * sxy / sxx
    nonlinear = between - linear
    scale = max(abs(between), abs(linear), abs(within))
    tau = 128 * np.finfo(float).eps * scale
    if between < -tau or nonlinear < -tau:
        raise FieldError(TREND, _say(
            "analysis.trend.error.numeric",
            "Linear trend is outside the supported numeric range."))
    if -tau <= nonlinear < 0:
        nonlinear = 0.0
    flat = between <= tau
    if flat:
        between = linear = nonlinear = 0.0
        slope = 0.0
        intercept = ybar + origin
    if not np.isfinite([slope, intercept, linear, nonlinear, between]).all():
        raise FieldError(TREND, _say(
            "analysis.trend.error.numeric",
            "Linear trend is outside the supported numeric range."))
    within_df = total_n - count
    mse = within / within_df
    total = between + within
    return {
        "sizes": sizes, "means": means + origin, "scores": scores, "slope": float(slope),
        "intercept": float(intercept), "linear": float(linear), "nonlinear": float(nonlinear),
        "between": float(between), "within": float(within), "total": float(total),
        "within_df": int(within_df), "mse": float(mse), "flat": flat,
    }


def reject_unless_one_way(method):
    """The trend belongs only to one-way ANOVA. Other methods stop before their own checks."""
    if method != "One-way ANOVA":
        raise FieldError(TREND, _say(
            "analysis.trend.error.method",
            "Linear trend requires an ordinary independent ANOVA."))


def check_options(frame, options):
    """Validate a requested trend. A false or absent trend ignores a dormant order."""
    if not options.get(TREND):
        return
    if options.get("Method", "Ordinary") != "Ordinary":
        raise FieldError(TREND, _say(
            "analysis.trend.error.method",
            "Linear trend requires an ordinary independent ANOVA."))
    observed = _cases(frame, options["Response"], options["Group"])
    order = options.get(ORDER)
    if not isinstance(order, (list, tuple)):
        raise FieldError(ORDER, _say("analysis.trend.error.order_shape",
                                      "Trend group order must list each level as text or a finite number."))
    _match_order(observed, order)
    _decomposition([(item, values) for item, values in _ordered(observed, order)])


def _ordered(observed, order):
    parsed = _match_order(observed, order)
    by_key = {_key(item): values for item, values in observed}
    return [(item, by_key[_key(item)]) for item in parsed]


def trend_tables(frame, response, group, order):
    """Linear contrast and, from four groups, departure from that line."""
    observed = _cases(frame, response, group)
    ordered = _ordered(observed, order)
    fit = _decomposition(ordered)
    count = len(ordered)
    total_n = int(fit["sizes"].sum())
    linear_f = fit["linear"] / fit["mse"]
    linear_p = float(stats.f.sf(linear_f, 1, fit["within_df"]))
    notes = [_say("analysis.trend.note.planned",
                  "The linear and nonlinear tests are planned contrasts and are not adjusted for multiplicity. "
                  "The slope is the change in the response for one group position, not for a dose written in the title.")]
    if fit["flat"]:
        alerting = np.nan
        notes.append(_say("analysis.trend.note.flat",
                          "The group means do not differ, so R² alerting is not available."))
        if count < 4:
            nonlinear_f = nonlinear_p = np.nan
            notes.append(_say("analysis.trend.note.few_groups",
                              "The nonlinear test is published from four groups upward."))
        else:
            nonlinear_f, nonlinear_p = 0.0, 1.0
    elif count < 4:
        nonlinear_f = nonlinear_p = np.nan
        alerting = fit["linear"] / fit["between"] if fit["between"] > 0 else np.nan
        notes.append(_say("analysis.trend.note.few_groups",
                          "The nonlinear test is published from four groups upward."))
    else:
        nonlinear_ms = fit["nonlinear"] / (count - 2)
        nonlinear_f = nonlinear_ms / fit["mse"]
        nonlinear_p = float(stats.f.sf(nonlinear_f, count - 2, fit["within_df"]))
        alerting = fit["linear"] / fit["between"] if fit["between"] > 0 else np.nan
    plain = [str(item["value"]) for item, _ in ordered]
    ambiguous = len(plain) != len(set(plain))
    metrics = {
        "N": total_n,
        "Groups": count,
        "Slope": fit["slope"],
        "Intercept": fit["intercept"],
        "SS linear": fit["linear"],
        "SS nonlinear": fit["nonlinear"],
        "SS between": fit["between"],
        "SS within": fit["within"],
        "SS total": fit["total"],
        "df linear": 1,
        "df nonlinear": count - 2,
        "df within": fit["within_df"],
        "F linear": 0.0 if fit["flat"] else float(linear_f),
        "p linear": 1.0 if fit["flat"] else linear_p,
        "F nonlinear": nonlinear_f,
        "p nonlinear": nonlinear_p,
        "R² effect": 0.0 if fit["flat"] else fit["linear"] / fit["total"],
        "R² alerting": alerting,
        "Convention": _CONVENTION,
        "Note": " ".join(notes),
    }
    sheet = pd.DataFrame({"Value": [metrics[name] for name in _METRICS]}, index=pd.Index(_METRICS, name="Metric"))
    rows = []
    for score, (item, values), mean in zip(fit["scores"], ordered, fit["means"], strict=True):
        variance = float(np.var(values, ddof=1)) if len(values) > 1 else np.nan
        rows.append({"Score": int(score), "Group kind": item["kind"], "Group value": item["value"],
                     "Group label": _label(item, ambiguous), "N": int(len(values)),
                     "Mean": float(mean), "Variance": variance})
    return {SHEET: sheet, MEANS: pd.DataFrame(rows)}
