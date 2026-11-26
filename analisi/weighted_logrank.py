"""Tarone–Ware and Fleming–Harrington weights on the Kaplan–Meier risk sets.

The weight changes the test, not the survival curve. Each pairwise comparison builds
its own risk sets and its own weights. A factor raised to zero is 1, including at 0.
"""

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

from . import fdr_control
from .field_error import FieldError
from .i18n import tr
from .operations import adjust_p
from .stats import _global_statistic, _risk_sets
from .survival_input import (CONTROL_PAIRS, PAIRWISE_ADJUSTED, PAIRWISE_ALPHA, PAIRWISE_CONTROL,
                             PAIRWISE_CORRECTION, PAIRWISE_METHODS, PAIRWISE_PAIRS, PAIRWISE_SCOPE,
                             SELECTED_PAIRS, UNADJUSTED, pairwise_fields, pairwise_scope)

WEIGHTING = "Curve comparison"
DETAIL = "Weight detail"
RHO = "Fleming–Harrington rho"
GAMMA = "Fleming–Harrington gamma"
NONE = "None"
LOG_RANK = "Log-rank"
TARONE = "Tarone–Ware"
GEHAN = "Gehan–Breslow–Wilcoxon"
EARLY = "Fleming–Harrington early (1, 0)"
LATE = "Fleming–Harrington late (0, 1)"
INTERMEDIATE = "Fleming–Harrington intermediate (1, 1)"
CUSTOM = "Fleming–Harrington (custom)"
CHOICES = (NONE, LOG_RANK, TARONE, GEHAN, EARLY, LATE, INTERMEDIATE, CUSTOM)
FIELDS = (WEIGHTING, RHO, GAMMA, DETAIL)
PRESETS = {EARLY: (1.0, 0.0), LATE: (0.0, 1.0), INTERMEDIATE: (1.0, 1.0)}

GLOBAL = "Weighted log-rank"
PAIRS = "Weighted pairwise"
DETAIL_SHEET = "Weight detail"
FDR_SHEET = "Weighted pairwise FDR"
SHEETS = frozenset((GLOBAL, PAIRS, DETAIL_SHEET, FDR_SHEET))

ALL_GROUPS = "All groups"
CHI2 = "χ²"
NEED_GROUPS = "A comparison needs at least two groups."
NO_EVENTS = "There are no events to compare."
EMPTY_GROUP = "A group has no observations for this comparison."
LOW_RANK = "The covariance does not have enough rank for this comparison."
BAD_METHOD = "Choose a curve comparison."
BAD_EXPONENT = "{field} must be a finite number greater than or equal to zero."
TOO_MANY = "Pairwise survival tests support up to twelve groups."
ESTIMATED = "Estimated"
UNAVAILABLE = "Not available"
STEP_PREFIX = "weighted-logrank-step"
WEIGHT_AXES = "weighted-logrank-axes"
PAIR_LIMIT = 12

_PHRASES = {
    NEED_GROUPS: "weight.phrase.groups", NO_EVENTS: "weight.phrase.events", EMPTY_GROUP: "weight.phrase.empty",
    LOW_RANK: "weight.phrase.rank", UNAVAILABLE: "weight.phrase.unavailable", ESTIMATED: "weight.phrase.estimated",
    ALL_GROUPS: "weight.phrase.all", LOG_RANK: "weight.phrase.logrank", TARONE: "weight.phrase.tarone",
    GEHAN: "weight.phrase.gehan", EARLY: "weight.phrase.early", LATE: "weight.phrase.late",
    INTERMEDIATE: "weight.phrase.intermediate", CUSTOM: "weight.phrase.custom",
    "Method": "weight.column.method", "Rho": "weight.column.rho", "Gamma": "weight.column.gamma",
    "Status": "weight.column.status", "Reason": "weight.column.reason",
}

_SHEET_KEYS = {GLOBAL: "weight.sheet.global", PAIRS: "weight.sheet.pairs", DETAIL_SHEET: "weight.sheet.detail",
               FDR_SHEET: "weight.sheet.fdr"}
_HEADER_KEYS = {
    "Metric": "weight.column.metric", "Value": "weight.column.value", "Method": "weight.column.method",
    "Comparison": "weight.column.comparison", "First group": "weight.column.first",
    "Second group": "weight.column.second", "Time": "weight.column.time", "At risk": "weight.column.risk",
    "Events": "weight.column.events", "Survival before": "weight.column.survival", "Weight": "weight.column.weight",
    "Group": "weight.column.group", "Group at risk": "weight.column.group_risk",
    "Observed": "weight.column.observed", "Expected": "weight.column.expected", "Status": "weight.column.status",
    "Reason": "weight.column.reason", "Adjusted p": "weight.column.adjusted",
    "Significant": "weight.column.significant", "Response variable": "weight.column.response",
    "Rho": "weight.column.rho", "Gamma": "weight.column.gamma",
}


class WeightedComparisonCancelled(Exception):
    """The worker stopped between two comparisons. Nothing is published."""


def active(options):
    """True when the recipe asks for the weighted family."""
    return options.get(WEIGHTING, NONE) not in (None, "", NONE)


def phrase(value):
    """English sheet text in the active language. Numbers and unknown labels pass through."""
    key = _PHRASES.get(value)
    if key is None:
        return value
    shown = tr(key)
    return value if shown == key else shown


def method_text(choice):
    """The weighting as a reader sees it."""
    return phrase(choice)


def sheet_labels(title):
    """Translated tab title and column titles. The stored keys stay English."""
    headers = {}
    for name, key in _HEADER_KEYS.items():
        if key is None:
            continue
        shown = tr(key)
        if shown != key:
            headers[name] = shown
    return tr(_SHEET_KEYS[title]), headers


def field_visibility(correction, scope, adjusted, choice):
    """Pairwise fields, plus the exponents and the weight detail only when they apply."""
    fields = pairwise_fields(correction, scope, adjusted)
    chosen = choice not in (None, "", NONE)
    if chosen:
        fields[PAIRWISE_SCOPE] = True
        fields[PAIRWISE_CONTROL] = scope == CONTROL_PAIRS
        fields[PAIRWISE_PAIRS] = scope == SELECTED_PAIRS
    fields[RHO] = choice == CUSTOM
    fields[GAMMA] = choice == CUSTOM
    fields[DETAIL] = chosen
    return fields


def _exponent(value, field):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(field, BAD_EXPONENT.format(field=field))
    try:
        number = float(value)
    except OverflowError:
        raise FieldError(field, BAD_EXPONENT.format(field=field)) from None
    if not np.isfinite(number) or number < 0:
        raise FieldError(field, BAD_EXPONENT.format(field=field))
    return number


def validate(options):
    """Reject an unknown weighting or a custom exponent that is not finite and ≥ 0."""
    choice = options.get(WEIGHTING, NONE)
    if choice in (None, "", NONE):
        return
    if choice not in CHOICES:
        raise FieldError(WEIGHTING, BAD_METHOD)
    if choice == CUSTOM:
        _exponent(options.get(RHO), RHO)
        _exponent(options.get(GAMMA), GAMMA)


def canonical(options):
    """Store the weighting, and rho and gamma only for a custom Fleming–Harrington weight."""
    validate(options)
    choice = options.get(WEIGHTING, NONE)
    if choice in (None, "", NONE):
        for key in (WEIGHTING, RHO, GAMMA, DETAIL):
            options.pop(key, None)
        return options
    options[WEIGHTING] = choice
    if choice == CUSTOM:
        options[RHO] = _exponent(options.get(RHO), RHO)
        options[GAMMA] = _exponent(options.get(GAMMA), GAMMA)
    else:
        options.pop(RHO, None)
        options.pop(GAMMA, None)
    if options.get(DETAIL) is True:
        options[DETAIL] = True
    else:
        options.pop(DETAIL, None)
    return options


def _stopped(cancel):
    if cancel is None:
        return False
    flag = getattr(cancel, "is_set", None)
    return bool(flag() if flag is not None else cancel())


def _check(cancel):
    if _stopped(cancel):
        raise WeightedComparisonCancelled("The weighted comparison was cancelled.")


def _pow(base, exponent):
    """``base ** exponent`` with the convention that a zero exponent is 1, including 0 ** 0."""
    if float(exponent) == 0.0:
        return np.ones_like(base, dtype=float)
    return np.power(base, float(exponent))


def _spec(choice, rho, gamma):
    if choice == LOG_RANK:
        return "logrank", 0.0, 0.0
    if choice == TARONE:
        return "tarone", None, None
    if choice == GEHAN:
        return "gehan", None, None
    if choice in PRESETS:
        rho, gamma = PRESETS[choice]
        return "fh", rho, gamma
    return "fh", float(rho), float(gamma)


def _weights(code, total, survival, rho, gamma):
    if code == "logrank":
        return np.ones(len(total), dtype=float)
    if code == "gehan":
        return total.astype(float)
    if code == "tarone":
        return np.sqrt(total.astype(float))
    return _pow(survival, rho) * _pow(1.0 - survival, gamma)


def fit_arrays(time, event, labels, choice, rho=0.0, gamma=0.0):
    """One weighted log-rank on these rows.

    ``labels`` aligns with ``time`` and ``event``. Censorings at an event time stay in
    the risk set. Fleming–Harrington uses the pooled Kaplan–Meier value from just
    before the event. The result is either the statistic and the audit, or a note.
    """
    labels = np.asarray(labels, dtype=object)
    names = [str(label) for label in pd.unique(labels)]
    if len(names) < 2:
        return {"available": False, "note": NEED_GROUPS}
    names = sorted(names, key=str)
    codes = np.asarray(pd.Categorical(pd.Series(labels).astype(str), categories=names).codes)
    keep = codes >= 0
    times, at_risk, events = _risk_sets(np.asarray(time, float)[keep], np.asarray(event)[keep], codes[keep], len(names))
    if len(times) == 0:
        return {"available": False, "note": NO_EVENTS}
    total = at_risk.sum(axis=1)
    failed = events.sum(axis=1)
    code, rho, gamma = _spec(choice, rho, gamma)
    fraction = np.divide(failed, total, out=np.zeros(len(times)), where=total > 0)
    survival = np.cumprod(np.r_[1.0, 1.0 - fraction[:-1]])
    weights = _weights(code, total, survival, rho, gamma)
    share = np.divide(at_risk, total[:, None], out=np.zeros_like(at_risk), where=total[:, None] > 0)
    score = (weights[:, None] * (events - failed[:, None] * share)).sum(axis=0)
    factor = np.divide(failed * (total - failed), total - 1.0, out=np.zeros(len(times)), where=total > 1)
    coefficient = weights ** 2 * factor
    diagonal = (coefficient[:, None] * share).sum(axis=0)
    covariance = np.diag(diagonal) - (coefficient[:, None] * share).T @ share
    statistic = _global_statistic(score, covariance)
    if statistic is None:
        return {"available": False, "note": LOW_RANK}
    expected = failed[:, None] * share
    return {"available": True, "χ²": float(statistic), "df": len(names) - 1,
            "p": float(stats.chi2.sf(statistic, len(names) - 1)), "groups": names,
            "times": times, "at_risk": total, "events": failed, "survival": survival, "weight": weights,
            "group_at_risk": at_risk, "observed": events, "expected": expected,
            "rho": rho, "gamma": gamma, "code": code}


def _metric_sheet(rows):
    return pd.DataFrame({"Value": pd.Series(rows, dtype=object)}).rename_axis("Metric")


def _unavailable_sheet(note):
    return _metric_sheet({"Status": UNAVAILABLE, "Reason": note})


def _global_sheet(choice, found):
    if not found["available"]:
        return _unavailable_sheet(found["note"])
    rows = {"Method": choice}
    if found["code"] == "fh":
        rows["Rho"] = found["rho"]
        rows["Gamma"] = found["gamma"]
    rows[CHI2] = found["χ²"]
    rows["df"] = found["df"]
    rows["p"] = found["p"]
    return _metric_sheet(rows)


def _detail_frame(comparison, first, second, found):
    groups = found["groups"]
    count = len(groups)
    return pd.DataFrame({
        "Comparison": comparison, "First group": first, "Second group": second,
        "Time": np.repeat(found["times"], count), "At risk": np.repeat(found["at_risk"], count),
        "Events": np.repeat(found["events"], count), "Survival before": np.repeat(found["survival"], count),
        "Weight": np.repeat(found["weight"], count), "Group": np.tile(groups, len(found["times"])),
        "Group at risk": found["group_at_risk"].ravel(), "Observed": found["observed"].ravel(),
        "Expected": found["expected"].ravel(),
    })


def _pair_list(names, scope, options):
    ordered = sorted((str(name) for name in names), key=str)
    if scope == CONTROL_PAIRS:
        control = str(options.get(PAIRWISE_CONTROL, ""))
        return [(control, name) for name in ordered if name != control]
    if scope == SELECTED_PAIRS:
        pairs = options.get(PAIRWISE_PAIRS) or ()
        return [(str(pair[0]), str(pair[1])) for pair in pairs]
    return list(combinations(ordered, 2))


def _subset(time, event, labels, first, second):
    labels = np.asarray(labels).astype(str)
    chosen = (labels == first) | (labels == second)
    return time[chosen], event[chosen], labels[chosen]


def _pair_rows(time, event, labels, names, choice, rho, gamma, scope, options, cancel):
    rows, details = [], []
    for first, second in _pair_list(names, scope, options):
        _check(cancel)
        present = {str(name) for name in names}
        if first not in present or second not in present or first == second:
            rows.append({"Comparison": f"{first} / {second}", "First group": first, "Second group": second,
                         CHI2: np.nan, "df": np.nan, "p": np.nan, "Status": UNAVAILABLE, "Reason": EMPTY_GROUP})
            continue
        part_time, part_event, part_labels = _subset(time, event, labels, first, second)
        # Categories follow the requested pair so each comparison rebuilds its own sets.
        found = fit_arrays(part_time, part_event, part_labels, choice, rho, gamma)
        if not found["available"]:
            rows.append({"Comparison": f"{first} / {second}", "First group": first, "Second group": second,
                         CHI2: np.nan, "df": np.nan, "p": np.nan, "Status": UNAVAILABLE, "Reason": found["note"]})
            continue
        rows.append({"Comparison": f"{first} / {second}", "First group": first, "Second group": second,
                     CHI2: found["χ²"], "df": found["df"], "p": found["p"], "Status": ESTIMATED, "Reason": ""})
        if options.get(DETAIL) is True:
            left, right = sorted((first, second), key=str)
            details.append(_detail_frame(f"{left} / {right}", left, right, found))
    return rows, details


def _apply_correction(frame, options, correction):
    if correction in (None, "", NONE):
        return frame, None
    if correction in fdr_control.FDR_METHODS:
        from . import workbench
        family = workbench._pairwise_survival_fdr(frame, options, correction)
        return frame, family
    show_adjusted = options.get(PAIRWISE_ADJUSTED, True) and correction != UNADJUSTED
    p = frame["p"]
    if correction != UNADJUSTED and p.notna().any():
        p = adjust_p(frame, "p", PAIRWISE_METHODS[correction])["Adjusted p"]
        if show_adjusted:
            frame["Adjusted p"] = p
    if not show_adjusted:
        alpha = options.get(PAIRWISE_ALPHA, .05)
        frame["Significant"] = p.lt(alpha).astype("boolean").where(p.notna())
    return frame, None


def _bottom_panel(figure, xlabel, ylabel):
    found = next((ax for ax in figure.axes if ax.get_gid() == WEIGHT_AXES), None)
    if found is not None:
        return found
    hosts = list(figure.axes)
    grid = figure.add_gridspec(len(hosts) + 1, 1, height_ratios=[3] * len(hosts) + [1.15])
    for index, ax in enumerate(hosts):
        ax.set_subplotspec(grid[index, 0])
    axes = figure.add_subplot(grid[-1, 0])
    axes.set_gid(WEIGHT_AXES)
    axes.set_xlabel(xlabel, parse_math=False)
    axes.set_ylabel(ylabel)
    axes.spines[["right", "top"]].set_visible(False)
    figure.set_size_inches(figure.get_figwidth(), figure.get_figheight() + 1.8, forward=True)
    return axes


def _draw_weights(figure, km_axes, found, choice, xlabel, response, separate):
    ylabel = method_text(choice)
    legend = ylabel if response is None else f"{ylabel} — {response}"
    if separate:
        axes = _bottom_panel(figure, xlabel, ylabel)
    else:
        axes = km_axes.twinx()
        axes.set_ylabel(ylabel)
        axes.spines[["top"]].set_visible(False)
    count = sum(str(line.get_gid() or "").startswith(STEP_PREFIX) for ax in figure.axes for line in ax.lines)
    line, = axes.plot(found["times"], found["weight"], drawstyle="steps-post", label=legend,
                      gid=f"{STEP_PREFIX}-{count}")
    axes.legend(frameon=False)
    return line


def contribute(frame, options, curves, figure, *, response=None, km_axes=None, cancel=None):
    """Sheets for the selected weighting, and the weight step when detail is on.

    ``response`` is set when the figure has one panel per response, so the curve can name it.
    The Kaplan–Meier lines already on ``figure`` are left as they are.
    """
    _check(cancel)
    if not active(options):
        return {}
    choice = options[WEIGHTING]
    rho, gamma = options.get(RHO, 0.0), options.get(GAMMA, 0.0)
    time_name, event_name, group_name = options["Time"], options["Event"], options.get("Group")
    if not group_name or len(curves) < 2:
        return {GLOBAL: _unavailable_sheet(NEED_GROUPS)}
    from .stats import complete
    data = complete(frame, [time_name, event_name], [group_name])
    labels = data[group_name].map(str).to_numpy()
    names = [str(label) for label in curves]
    if len(names) > PAIR_LIMIT:
        raise FieldError(WEIGHTING, TOO_MANY)
    found = fit_arrays(data[time_name].to_numpy(), data[event_name].to_numpy(), labels, choice, rho, gamma)
    outputs = {GLOBAL: _global_sheet(choice, found)}
    scope = pairwise_scope(options)
    rows, details = _pair_rows(data[time_name].to_numpy(), data[event_name].to_numpy(), labels, names, choice,
                               rho, gamma, scope, options, cancel)
    pair_frame = pd.DataFrame(rows)
    correction = options.get(PAIRWISE_CORRECTION, NONE)
    pair_frame, family = _apply_correction(pair_frame, options, correction)
    outputs[PAIRS] = pair_frame.set_index("Comparison")
    if family is not None:
        outputs[FDR_SHEET] = family
    if options.get(DETAIL) is True:
        parts = []
        if found["available"]:
            parts.append(_detail_frame(ALL_GROUPS, "", "", found))
        parts.extend(details)
        outputs[DETAIL_SHEET] = pd.concat(parts, ignore_index=True) if parts else _unavailable_sheet(
            found.get("note", NO_EVENTS))
        if found["available"] and figure is not None:
            _draw_weights(figure, km_axes if km_axes is not None else figure.axes[0], found, choice,
                          time_name, response, separate=km_axes is None)
    return outputs


def cell_formatters(title):
    """Display text for the weighted sheets. Numeric cells keep the grid's own digits."""
    if title not in SHEETS:
        return None
    from trama_qt.models import display

    def show(value):
        if isinstance(value, str):
            return phrase(value)
        return display(value)

    if title == GLOBAL:
        return {"Value": show, "Metric": show}
    if title == PAIRS:
        return {"Status": show, "Reason": show}
    if title == DETAIL_SHEET:
        return {"Comparison": show}
    return None


def _whole(value):
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def _audit(detail, comparison):
    part = detail[detail["Comparison"] == comparison].drop_duplicates("Time")
    rows = []
    for _, row in part.iterrows():
        rows.append({"t": _whole(row["Time"]), "at_risk": _whole(row["At risk"]), "events": _whole(row["Events"]),
                     "s_before": float(row["Survival before"]), "weight": float(row["Weight"])})
    return rows


def artist_weights(figure):
    """Weights and times of the step curves actually drawn on the figure."""
    lines = [line for ax in figure.axes for line in ax.lines
             if str(line.get_gid() or "").startswith(STEP_PREFIX)]
    return [(np.asarray(line.get_xdata(), dtype=float), np.asarray(line.get_ydata(), dtype=float),
             line.get_label()) for line in lines]


def reference_record(result):
    """One ``atteso.json`` block from the recipe sheets, with weights taken from the drawn step."""
    detail = result.tables[DETAIL_SHEET]
    report = result.tables[GLOBAL]
    audit = _audit(detail, ALL_GROUPS)
    drawn = artist_weights(result.figure)
    if len(drawn) != 1:
        raise ValueError(f"expected one weight curve, found {len(drawn)}")
    times, weights, _label = drawn[0]
    sheet_weights = np.array([row["weight"] for row in audit], dtype=float)
    sheet_times = np.array([row["t"] for row in audit], dtype=float)
    if len(weights) != len(sheet_weights) or not np.allclose(weights, sheet_weights, rtol=0, atol=0):
        raise ValueError("The weight curve does not match the weight detail.")
    if not np.allclose(times, sheet_times, rtol=0, atol=0):
        raise ValueError("The weight curve times do not match the weight detail.")
    for row, weight in zip(audit, weights):
        row["weight"] = float(weight)
    pairs = {}
    for _comparison, row in result.tables[PAIRS].iterrows():
        first, second = str(row["First group"]), str(row["Second group"])
        key = "-".join(sorted((first, second)))
        left, right = sorted((first, second))
        pair_audit = _audit(detail, f"{left} / {right}")
        pairs[key] = {"chi2": float(row[CHI2]), "df": int(row["df"]), "p": float(row["p"]),
                      "audit": pair_audit, "p_holm": float(row["Adjusted p"])}
    return {"global_test": {"chi2": float(report.at[CHI2, "Value"]), "df": int(report.at["df", "Value"]),
                            "p": float(report.at["p", "Value"]), "audit": audit},
            "pairs": pairs}
