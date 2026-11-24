"""Mood's median test for two or more independent samples in separate columns.

The pooled median is computed once from all finite observations. Each sample then contributes
counts strictly above, strictly below, and equal to that median. The Ties rule places equals
Below (default), Above, or Ignore without recomputing the median. Pearson χ² on the resulting
2×k table uses k−1 degrees of freedom and an upper-tail p-value. Yates correction applies only
with exactly two samples and is off by default.

When a table margin is zero or Ignore empties a sample, the pooled median and the Mood counts
sheet are kept; Chi-square, df and P stay empty and Settings explains why. Expected frequencies
below 5 are noted. No exact or post-hoc follow-up is implied.
"""
from numbers import Integral, Real
import math

import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .reporting import Result
from .mood_median_text import text

METHOD = "Mood median test"
VARIABLES, TIES, YATES = "Variables", "Ties", "Yates correction"
BELOW, ABOVE, IGNORE = TIE_RULES = ("Below", "Above", "Ignore")
RESULT_SHEET, COUNTS_SHEET, SETTINGS_SHEET = "Mood median", "Mood counts", "Settings"
RESULT_COLUMNS = ("Pooled median", "Chi-square", "df", "P")
COUNT_COLUMNS = ("Sample", "Above", "Below", "Tied")
MULTIPLE = "Multiple"

OPTIONS = {VARIABLES: MULTIPLE, TIES: TIE_RULES, YATES: False}
DATA_FIELDS = (VARIABLES,)
TEST_FIELDS = (TIES, YATES)
NUMBER_FIELDS = ()
TAB_KEYS = {"Data": "mood.tab.data", "Test": "mood.tab.test"}
LABEL_KEYS = {
    VARIABLES: "mood.field.variables", TIES: "mood.field.ties", YATES: "mood.field.yates",
}
CHOICE_KEYS = {
    BELOW: "mood.choice.below", ABOVE: "mood.choice.above", IGNORE: "mood.choice.ignore",
}


def describe_error(error, field=None):
    """Dialog banner: the engine message in the active language, naming the field to correct."""
    from .i18n import tr, translate_message

    def caption(name):
        key = LABEL_KEYS.get(name)
        return tr(key) if key else name

    field = getattr(error, "field", field)
    raw = str(error)
    shown = translate_message(raw, "mood.error.", {"field": caption})
    label = caption(field) if field else ""
    if field and field.lower() not in shown.lower() and label.lower() not in shown.lower():
        shown = f"{label}: {shown}"
    return shown


def check_options(frame, options):
    """Validate the recipe and the worksheet. Field errors name the control to correct."""
    if not isinstance(options, dict):
        raise FieldError(VARIABLES, text("mood.error.variables"))
    names = _variables(frame, options)
    rule = _ties(options)
    yates = _yates(options)
    samples = [_sample(frame[name], name) for name in names]
    return {
        "names": names,
        "samples": [entry["values"] for entry in samples],
        "missing": [entry["missing"] for entry in samples],
        "ties": rule,
        "yates": yates,
    }


def mood_median(frame, options, *, cancel=None):
    """Mood median table, per-sample counts, and Settings. No figure."""
    chosen = check_options(frame, options)
    _check_cancel(cancel)
    summary = median_test(chosen["samples"], ties=chosen["ties"], correction=chosen["yates"],
                          cancel=cancel)
    result_row = {name: summary[name] for name in RESULT_COLUMNS}
    counts = pd.DataFrame({
        "Sample": chosen["names"],
        "Above": summary["Above"],
        "Below": summary["Below"],
        "Tied": summary["Tied"],
    }, columns=list(COUNT_COLUMNS))
    return Result({
        RESULT_SHEET: pd.DataFrame([result_row], columns=list(RESULT_COLUMNS)),
        COUNTS_SHEET: counts,
        SETTINGS_SHEET: _settings(chosen, summary),
    })


def median_test(samples, *, ties=BELOW, correction=False, cancel=None):
    """Pooled median, contingency counts and Pearson χ² for finite sample vectors."""
    groups = [_vector(group) for group in samples]
    if len(groups) < 2:
        raise ValueError("Mood's median test needs at least two samples")
    if ties not in TIE_RULES:
        raise ValueError("ties must be Below, Above or Ignore")
    if not isinstance(correction, (bool, np.bool_)):
        raise ValueError("correction must be a boolean")
    for group in groups:
        if len(group) < 2:
            raise ValueError("each sample needs at least 2 finite observations")
    _check_cancel(cancel)
    pooled = np.concatenate(groups)
    center = float(np.median(pooled))
    strict_above = [int(np.sum(group > center)) for group in groups]
    strict_below = [int(np.sum(group < center)) for group in groups]
    tied = [int(np.sum(group == center)) for group in groups]
    above = list(strict_above)
    below = list(strict_below)
    if ties == ABOVE:
        above = [a + t for a, t in zip(above, tied)]
    elif ties == BELOW:
        below = [b + t for b, t in zip(below, tied)]
    # Ignore leaves above/below as the strict counts.
    table = np.asarray([above, below], dtype=float)
    k = len(groups)
    apply_yates = bool(correction) and k == 2
    emptied = ties == IGNORE and any(a + b == 0 for a, b in zip(above, below))
    zero_margin = (table.sum(axis=0) == 0).any() or (table.sum(axis=1) == 0).any()
    summary = {
        "Pooled median": center,
        "Chi-square": np.nan,
        "df": np.nan,
        "P": np.nan,
        "Above": above,
        "Below": below,
        "Tied": tied,
        "table": table,
        "available": False,
        "reason": None,
        "min_expected": np.nan,
        "low_expected": False,
        "yates_applied": apply_yates,
        "yates_requested": bool(correction),
        "emptied": emptied,
        "zero_margin": bool(zero_margin),
    }
    if emptied or zero_margin:
        summary["reason"] = "ignore" if emptied else "margin"
        return summary
    try:
        result = stats.chi2_contingency(table, correction=apply_yates, lambda_=1)
    except ValueError:
        summary["reason"] = "margin"
        return summary
    statistic = float(result.statistic)
    pvalue = float(result.pvalue)
    expected = np.asarray(result.expected_freq, dtype=float)
    min_expected = float(np.min(expected)) if expected.size else np.nan
    if not (math.isfinite(statistic) and math.isfinite(pvalue)):
        summary["reason"] = "margin"
        return summary
    summary["Chi-square"] = statistic
    summary["df"] = float(k - 1)
    summary["P"] = pvalue
    summary["available"] = True
    summary["min_expected"] = min_expected
    summary["low_expected"] = bool(math.isfinite(min_expected) and min_expected < 5.0)
    return summary


# ----- worksheet -----------------------------------------------------------------------------------------------------

def _variables(frame, options):
    raw = options.get(VARIABLES)
    if isinstance(raw, str):
        names = [raw] if raw else []
    elif isinstance(raw, (list, tuple)):
        names = list(raw)
    else:
        raise FieldError(VARIABLES, text("mood.error.variables"))
    if len(names) < 2:
        raise FieldError(VARIABLES, text("mood.error.variables"))
    if len(set(names)) != len(names):
        raise FieldError(VARIABLES, text("mood.error.variables"))
    resolved = []
    for name in names:
        if not isinstance(name, str) or not name:
            raise FieldError(VARIABLES, text("mood.error.variables"))
        matches = [column for column in frame.columns if column == name]
        if not matches:
            raise FieldError(VARIABLES, text("mood.error.missing", name=name))
        if len(matches) > 1:
            raise FieldError(VARIABLES, text("mood.error.duplicate", name=name))
        resolved.append(name)
    return resolved


def _ties(options):
    value = options.get(TIES, BELOW)
    if not isinstance(value, str) or value not in TIE_RULES:
        raise FieldError(TIES, text("mood.error.ties"))
    return value


def _yates(options):
    value = options.get(YATES, False)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(YATES, text("mood.error.yates"))
    return bool(value)


def _shown(raw):
    text_value = raw.strip() if isinstance(raw, str) else repr(raw)
    return text_value if len(text_value) <= 40 else text_value[:37] + "..."


def _blank(raw):
    if raw is None:
        return True
    if isinstance(raw, str):
        return not raw.strip()
    try:
        return bool(pd.isna(raw))
    except (TypeError, ValueError):
        return False


def _cell(raw, name, row):
    if _blank(raw):
        return np.nan
    if isinstance(raw, (bool, np.bool_)):
        raise FieldError(VARIABLES, text("mood.error.boolean", name=name, row=row))
    if isinstance(raw, str):
        cleaned = raw.strip()
        try:
            value = float(cleaned.replace(",", ".") if cleaned.count(",") == 1 and "." not in cleaned
                          else cleaned)
        except ValueError:
            raise FieldError(VARIABLES, text("mood.error.not_number", name=name, row=row,
                                             shown=_shown(raw))) from None
    elif isinstance(raw, Integral):
        value = float(raw)
    elif isinstance(raw, Real):
        try:
            value = float(raw)
        except (OverflowError, ValueError):
            raise FieldError(VARIABLES, text("mood.error.not_finite", name=name, row=row)) from None
    else:
        raise FieldError(VARIABLES, text("mood.error.not_number", name=name, row=row,
                                         shown=_shown(raw)))
    if not math.isfinite(value):
        raise FieldError(VARIABLES, text("mood.error.not_finite", name=name, row=row))
    return value


def _sample(series, name):
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        raise FieldError(VARIABLES, text("mood.error.boolean", name=name, row=1))
    if pd.api.types.is_integer_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype):
        values = series.to_numpy(dtype=float, na_value=np.nan)
    elif pd.api.types.is_float_dtype(dtype):
        values = series.to_numpy(dtype=float, na_value=np.nan)
        infinite = np.isinf(values)
        if infinite.any():
            raise FieldError(VARIABLES, text("mood.error.not_finite", name=name,
                                             row=int(np.argmax(infinite)) + 1))
    else:
        values = np.array([_cell(raw, name, position + 1)
                           for position, raw in enumerate(series.tolist())], dtype=float)
    finite = values[np.isfinite(values)]
    missing = int(len(values) - len(finite))
    if len(finite) < 2:
        raise FieldError(VARIABLES, text("mood.error.short", name=name, count=len(finite)))
    return {"values": finite, "missing": missing}


def _vector(values):
    if isinstance(values, (str, bytes)):
        raise ValueError("a sample must be a finite vector")
    data = np.asarray(list(values), dtype=float)
    if data.ndim != 1 or not np.all(np.isfinite(data)):
        raise ValueError("a sample must be a finite vector")
    return data


def _settings(chosen, summary):
    rows = {
        "Variables": ", ".join(chosen["names"]),
        "Ties": chosen["ties"],
        "Yates correction": chosen["yates"],
        "Yates applied": summary["yates_applied"],
        "Approximation": text("mood.note.pearson"),
    }
    for name, missing in zip(chosen["names"], chosen["missing"]):
        rows[f"Missing or excluded cells, {name}"] = missing
    if summary["yates_requested"] and not summary["yates_applied"]:
        rows["Yates note"] = text("mood.note.yates_inactive")
    if summary["available"]:
        rows["Inference"] = "Available"
        rows["Minimum expected frequency"] = summary["min_expected"]
        if summary["low_expected"]:
            rows["Expected frequencies"] = text("mood.note.expected")
    else:
        rows["Inference"] = "Not available"
        reason = summary["reason"]
        rows["Reason"] = text("mood.reason.ignore" if reason == "ignore" else "mood.reason.margin")
    index = pd.Index(list(rows), name="Setting")
    return pd.DataFrame({"Value": pd.Series(list(rows.values()), index=index, dtype=object)},
                        index=index)


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        from .monte_carlo import MonteCarloCancelled
        raise MonteCarloCancelled("Mood median test cancelled.")
