"""Brunner–Munzel test for two independent samples.

Estimates the relative effect ``p = P(X > Y) + ½ P(X = Y)`` and tests whether it differs from ½.
The first sample is always X. Neither the estimate nor the test is a comparison of medians.

Placement scores are computed from sorted vectors in O(N log N) time and linear memory: for each
X value the share of Y strictly below it plus half the share equal to it, and symmetrically for Y.
Wins, ties and losses are the integer pair counts from the same passes. With ``a = var(scores X,
ddof=1)/Nx`` and ``b = var(scores Y, ddof=1)/Ny``, the standard error is ``√(a+b)``, the degrees of
freedom are Welch–Satterthwaite, and ``T = (p − ½) / SE`` is positive when X tends to be larger.
SciPy’s ``brunnermunzel`` statistic has the opposite sign for this orientation; p-values are
compared independently.

When SE is zero the observed probability and pair counts are kept; T, df, P and the interval stay
empty. A single zero variance component with the other positive still yields a valid inference.
"""
from numbers import Integral, Real
import math

import numpy as np
import pandas as pd
from scipy import stats

from .field_error import FieldError
from .reporting import Result
from .brunner_munzel_text import text

METHOD = "Brunner–Munzel test"
FIRST, SECOND = "First sample", "Second sample"
ALTERNATIVE, LEVEL = "Alternative", "Confidence level"
TWO_SIDED, GREATER, LESS = ALTERNATIVES = ("Two-sided", "Greater", "Less")
RESULT_SHEET, SETTINGS_SHEET = "Brunner–Munzel", "Settings"
RESULT_COLUMNS = ("Nx", "Ny", "Wins", "Ties", "Losses", "Probability", "SE", "T", "df", "P",
                  "Lower", "Upper")
SMALL_N = 10

OPTIONS = {FIRST: None, SECOND: None, ALTERNATIVE: ALTERNATIVES, LEVEL: 95.0}
DATA_FIELDS = (FIRST, SECOND)
NUMBER_FIELDS = (LEVEL,)
TAB_KEYS = {"Data": "bm.tab.data", "Test": "bm.tab.test"}
LABEL_KEYS = {
    FIRST: "bm.field.first", SECOND: "bm.field.second",
    ALTERNATIVE: "bm.field.alternative", LEVEL: "bm.field.level",
}
CHOICE_KEYS = {
    TWO_SIDED: "bm.choice.two_sided", GREATER: "bm.choice.greater", LESS: "bm.choice.less",
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
    shown = translate_message(raw, "bm.error.", {"field": caption})
    label = caption(field) if field else ""
    if field and field.lower() not in shown.lower() and label.lower() not in shown.lower():
        shown = f"{label}: {shown}"
    return shown


def check_options(frame, options):
    """Validate the recipe and the worksheet. Field errors name the control to correct."""
    if not isinstance(options, dict):
        raise FieldError(FIRST, text("bm.error.column", field=FIRST))
    alternative = _alternative(options)
    level = _level(options)
    first_name, second_name = _column(frame, options, FIRST), _column(frame, options, SECOND)
    if first_name == second_name:
        raise FieldError(SECOND, text("bm.error.distinct"))
    first = _sample(frame[first_name], FIRST)
    second = _sample(frame[second_name], SECOND)
    return {
        "first_name": first_name, "second_name": second_name,
        "first": first["values"], "second": second["values"],
        "missing_first": first["missing"], "missing_second": second["missing"],
        "alternative": alternative, "level": level,
    }


def brunner_munzel(frame, options, *, cancel=None):
    """One-row effect table and a Settings sheet. No figure."""
    chosen = check_options(frame, options)
    _check_cancel(cancel)
    summary = relative_effect(chosen["first"], chosen["second"], level=chosen["level"] / 100.0,
                              alternative=chosen["alternative"], cancel=cancel)
    row = {name: summary[name] for name in RESULT_COLUMNS}
    return Result({
        RESULT_SHEET: pd.DataFrame([row], columns=list(RESULT_COLUMNS)),
        SETTINGS_SHEET: _settings(chosen, summary),
    })


def relative_effect(x, y, *, level=0.95, alternative=TWO_SIDED, cancel=None):
    """Placement scores, pair counts and the Student approximation for finite vectors X and Y."""
    left, right = _vector(x), _vector(y)
    nx, ny = len(left), len(right)
    if nx < 2 or ny < 2:
        raise ValueError("each sample needs at least 2 finite observations")
    if not (isinstance(level, Real) and not isinstance(level, (bool, np.bool_))
            and math.isfinite(float(level)) and 0 < float(level) < 1):
        raise ValueError("level must be a fraction in (0, 1)")
    if alternative not in ALTERNATIVES:
        raise ValueError("alternative must be Two-sided, Greater or Less")
    _check_cancel(cancel)
    wins, ties, losses, scores_x, scores_y = _placements(left, right, cancel=cancel)
    probability = float(np.mean(scores_x))
    # Mean of the Y placements equals the same relative effect; keep the X mean as the estimate.
    a = float(np.var(scores_x, ddof=1) / nx)
    b = float(np.var(scores_y, ddof=1) / ny)
    if not (math.isfinite(a) and math.isfinite(b) and a >= 0 and b >= 0):
        raise ValueError("placement-score variances are not finite")
    se = math.sqrt(a + b)
    summary = {
        "Nx": nx, "Ny": ny, "Wins": wins, "Ties": ties, "Losses": losses,
        "Probability": probability, "SE": se, "T": np.nan, "df": np.nan, "P": np.nan,
        "Lower": np.nan, "Upper": np.nan, "a": a, "b": b, "available": False,
        "clipped": False, "small": min(nx, ny) < SMALL_N,
    }
    if se == 0.0:
        return summary
    df = _degrees(a, b, nx, ny)
    statistic = (probability - 0.5) / se
    if not (math.isfinite(df) and df > 0 and math.isfinite(statistic)):
        raise ValueError("the t statistic is not finite")
    pvalue = _pvalue(statistic, df, alternative)
    critical = float(stats.t.ppf((1.0 + float(level)) / 2.0, df))
    if not math.isfinite(critical):
        raise ValueError("the critical value is not finite")
    half = critical * se
    lower, upper = probability - half, probability + half
    clipped = lower < 0.0 or upper > 1.0
    summary.update(
        T=float(statistic), df=float(df), P=float(pvalue),
        Lower=float(max(0.0, lower)), Upper=float(min(1.0, upper)),
        available=True, clipped=clipped,
    )
    return summary


# ----- arithmetic ----------------------------------------------------------------------------------------------------

def _placements(x, y, *, cancel=None):
    """Integer pair counts and placement scores from two sorted passes."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    nx, ny = len(x), len(y)
    y_sorted = np.sort(y)
    _check_cancel(cancel)
    x_sorted = np.sort(x)
    _check_cancel(cancel)
    left_y = np.searchsorted(y_sorted, x, side="left")
    right_y = np.searchsorted(y_sorted, x, side="right")
    ties_x = right_y - left_y
    wins_x = left_y  # y < x ⇔ x > y
    scores_x = (wins_x + 0.5 * ties_x) / ny
    left_x = np.searchsorted(x_sorted, y, side="left")
    right_x = np.searchsorted(x_sorted, y, side="right")
    ties_y = right_x - left_x
    greater_x = nx - right_x  # x > y
    scores_y = (greater_x + 0.5 * ties_y) / nx
    wins = int(wins_x.sum())
    ties = int(ties_x.sum())
    losses = nx * ny - wins - ties
    return wins, ties, losses, scores_x, scores_y


def _degrees(a, b, nx, ny):
    """Welch–Satterthwaite df. A zero component contributes the other sample's n − 1."""
    if a == 0.0:
        return float(ny - 1)
    if b == 0.0:
        return float(nx - 1)
    scale = max(a, b)
    left, right = a / scale, b / scale
    return (left + right) ** 2 / (left * left / (nx - 1) + right * right / (ny - 1))


def _pvalue(statistic, df, alternative):
    if alternative == GREATER:
        return float(stats.t.sf(statistic, df))
    if alternative == LESS:
        return float(stats.t.cdf(statistic, df))
    return float(2.0 * stats.t.sf(abs(statistic), df))


def _vector(values):
    if isinstance(values, (str, bytes)):
        raise ValueError("a sample must be a finite vector")
    data = np.asarray(list(values), dtype=float)
    if data.ndim != 1 or not np.all(np.isfinite(data)):
        raise ValueError("a sample must be a finite vector")
    return data


# ----- worksheet -----------------------------------------------------------------------------------------------------

def _alternative(options):
    value = options.get(ALTERNATIVE, TWO_SIDED)
    if not isinstance(value, str) or value not in ALTERNATIVES:
        raise FieldError(ALTERNATIVE, text("bm.error.alternative"))
    return value


def _level(options):
    value = options.get(LEVEL, 95.0)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise FieldError(LEVEL, text("bm.error.level"))
    number = float(value)
    if not math.isfinite(number) or not 0 < number < 100:
        raise FieldError(LEVEL, text("bm.error.level"))
    return number


def _column(frame, options, field):
    name = options.get(field)
    if not isinstance(name, str) or not name:
        raise FieldError(field, text("bm.error.column", field=field))
    matches = [column for column in frame.columns if column == name]
    if not matches:
        raise FieldError(field, text("bm.error.missing", field=field, name=name))
    if len(matches) > 1:
        raise FieldError(field, text("bm.error.duplicate", name=name))
    return name


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


def _cell(raw, field, row):
    if _blank(raw):
        return np.nan
    if isinstance(raw, (bool, np.bool_)):
        raise FieldError(field, text("bm.error.boolean", field=field, row=row))
    if isinstance(raw, str):
        cleaned = raw.strip()
        try:
            value = float(cleaned.replace(",", ".") if cleaned.count(",") == 1 and "." not in cleaned
                          else cleaned)
        except ValueError:
            raise FieldError(field, text("bm.error.not_number", field=field, row=row,
                                         shown=_shown(raw))) from None
    elif isinstance(raw, Integral):
        value = float(raw)
    elif isinstance(raw, Real):
        try:
            value = float(raw)
        except (OverflowError, ValueError):
            raise FieldError(field, text("bm.error.not_finite", field=field, row=row)) from None
    else:
        raise FieldError(field, text("bm.error.not_number", field=field, row=row, shown=_shown(raw)))
    if not math.isfinite(value):
        raise FieldError(field, text("bm.error.not_finite", field=field, row=row))
    return value


def _sample(series, field):
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        raise FieldError(field, text("bm.error.boolean", field=field, row=1))
    if pd.api.types.is_integer_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype):
        values = series.to_numpy(dtype=float, na_value=np.nan)
    elif pd.api.types.is_float_dtype(dtype):
        values = series.to_numpy(dtype=float, na_value=np.nan)
        infinite = np.isinf(values)
        if infinite.any():
            raise FieldError(field, text("bm.error.not_finite", field=field,
                                         row=int(np.argmax(infinite)) + 1))
    else:
        values = np.array([_cell(raw, field, position + 1)
                           for position, raw in enumerate(series.tolist())], dtype=float)
    finite = values[np.isfinite(values)]
    missing = int(len(values) - len(finite))
    if len(finite) < 2:
        raise FieldError(field, text("bm.error.short", field=field, count=len(finite)))
    return {"values": finite, "missing": missing}


def _settings(chosen, summary):
    rows = {
        "First sample": chosen["first_name"],
        "Second sample": chosen["second_name"],
        "Orientation": text("bm.orientation"),
        "Alternative": chosen["alternative"],
        "Confidence level": chosen["level"],
        "Missing or excluded cells, First sample": chosen["missing_first"],
        "Missing or excluded cells, Second sample": chosen["missing_second"],
        "Approximation": text("bm.note.approx"),
    }
    if summary["small"]:
        rows["Small samples"] = text("bm.note.small")
    if not summary["available"]:
        rows["Inference"] = "Not available"
        rows["Reason"] = text("bm.reason.se")
    else:
        rows["Inference"] = "Available"
        if summary["clipped"]:
            rows["Interval"] = "Clipped to [0, 1]"
        else:
            rows["Interval"] = "Two-sided at the stated level; Alternative does not move it"
    index = pd.Index(list(rows), name="Setting")
    return pd.DataFrame({"Value": pd.Series(list(rows.values()), index=index, dtype=object)},
                        index=index)


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        from .monte_carlo import MonteCarloCancelled
        raise MonteCarloCancelled("Brunner–Munzel test cancelled.")
