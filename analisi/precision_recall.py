"""Precision–recall curve for scores measured outside Trama (Group Comparison → Precision–recall curve).

A laboratory has the scores of one or two instruments on the same samples and wants to judge them when the
event is rare. The method takes the outcome column with explicit ``Positive`` and ``Negative`` labels, one score
(or two, for a paired comparison) and the direction of each score.

Thresholds
    Every distinct observed score is a threshold; scores that tie are counted together. With ``Higher is
    positive`` a sample is predicted positive when score >= threshold, with ``Lower is positive`` when
    score <= threshold. Each threshold gives TP, FP, TN, FN, Precision = TP / (TP + FP) and Recall = TP / P.
Average precision
    AP = Σ (R_k − R_{k−1}) · P_k over the thresholds from the strictest to the loosest, with R_0 = 0 and the
    precision at the new level (no interpolation; scikit-learn's ``average_precision_score`` definition). The
    point (recall 0, precision 1) is only the start of the drawn curve: it is not a threshold and is not in the
    sheet. The prevalence of the sample (P / N) is the reference line, and the AP of an uninformative (constant)
    score equals the prevalence. The thresholds and the AP come from the functions the logistic validation
    already uses (``analisi.logistic_validation``), so the two analyses agree on the same scores.
Rows
    A sample is used when its outcome and every chosen score are filled. A blank or excluded cell leaves the whole
    row out of every curve, so two scores are always compared on the same rows. Outcome labels are compared
    literally (``01`` is not ``1``); a label that is neither ``Positive`` nor ``Negative`` is an error that names
    its first row. A score must be a finite number.
Paired bootstrap (optional, also for one score)
    The percentile bootstrap stratifies by outcome: every replicate draws, with replacement, as many positive and
    as many negative samples as the data holds, and the same drawn samples give the AP of the first and of the
    second score, so the difference keeps the pairing. ``Generator(PCG64(seed))`` draws, replicate after
    replicate, ``integers(0, P, size=P)`` over the positive samples and then ``integers(0, N−P, size=N−P)`` over
    the negative ones. Inside each class the samples are first put in a canonical order (by the first score, then
    the second), so the replicates do not depend on the order of the worksheet rows. The interval uses the linear
    percentiles alpha / 2 and 1 − alpha / 2. The budget is replicates × samples <= 20 million drawn positions,
    checked before anything is drawn; the loop is cancellable between blocks.

``prepare`` reads and checks recipe and worksheet without resampling (the dialog calls it); ``analyse`` returns the
Result. Errors the user can correct name their dialog field through ``FieldError``; the text is English and the Qt
dialog translates it through ``ERROR_PREFIX``.
"""
from dataclasses import dataclass
from math import isnan
from operator import index
import re

import numpy as np
import pandas as pd

from .field_error import FieldError
from .logistic_validation import average_precision, curve_points, roc_auc
from .monte_carlo import MonteCarloCancelled
from .processing import OPTIONAL, TEXT
from .reporting import Result, _plot, _report

METHOD = "Precision–recall curve"
OUTCOME, POSITIVE, NEGATIVE, SCORE, SECOND_SCORE = "Outcome", "Positive", "Negative", "Score", "Second score"
DIRECTION, SECOND_DIRECTION = "Direction", "Second direction"
BOOTSTRAP, LEVEL, REPLICATES, SEED = "Bootstrap CI", "Confidence level (%)", "Bootstrap replicates", "Bootstrap seed"
HIGHER, LOWER = DIRECTIONS = ("Higher is positive", "Lower is positive")

# The dialog builds its controls from these defaults: None is a column, OPTIONAL an optional column, TEXT a text
# entry, tuples are choices (the first is the default), bool a check box, floats and ints are entries.
OPTIONS = {OUTCOME: None, POSITIVE: TEXT, NEGATIVE: TEXT, SCORE: None, SECOND_SCORE: OPTIONAL,
           DIRECTION: DIRECTIONS, SECOND_DIRECTION: DIRECTIONS, BOOTSTRAP: False, LEVEL: 95.0,
           REPLICATES: 1999, SEED: 0}
DEFAULTS = {DIRECTION: HIGHER, SECOND_DIRECTION: HIGHER, BOOTSTRAP: False, LEVEL: 95.0, REPLICATES: 1999, SEED: 0}
CODE_FIELDS = (POSITIVE, NEGATIVE)
BOOTSTRAP_FIELDS = (LEVEL, REPLICATES, SEED)
NUMBER_FIELDS = (LEVEL, REPLICATES, SEED)

MIN_REPLICATES, MAX_REPLICATES, MAX_SEED = 199, 10_000, 2**64 - 1
MAX_ROWS = 1_000_000
BUDGET = 20_000_000             # replicates × samples
BLOCK_VALUES = 2_000_000        # drawn positions per block between two cancellation checks

SUMMARY, COMPARISON, SETTINGS, EXCLUDED = "Summary", "Comparison", "Settings", "Excluded rows"
THRESHOLDS = "Thresholds: "
THRESHOLD_COLUMNS = ["Threshold", "TP", "FP", "TN", "FN", "Precision", "Recall"]
GID = "precision-recall:"
COLORS = ("#1f6f8b", "#aa5440")
REFERENCE_COLOR = "#81919b"
AP_DEFINITION = ("Σ (Recall − previous Recall) × Precision at each distinct threshold, from the strictest "
                 "threshold down; no interpolation; recall 0 before the first threshold")
SEQUENCE = ("PCG64: Generator(PCG64(seed)); per replicate integers(0, P, size=P) over the positives, then "
            "integers(0, N−P, size=N−P) over the negatives, each class in canonical score order")
QUANTILE_RULE = 'Linear interpolation (numpy.quantile, method="linear")'

ERROR_PREFIX = "prec.error."
_DIGITS = re.compile(r"\s*\+?[0-9]+\s*")


class PrecisionRecallCancelled(MonteCarloCancelled, InterruptedError):
    """The bootstrap was cancelled; the application keeps the last confirmed result."""


def cancellable(method, options):
    """True when the calculation can be long enough to need the Cancel calculation button."""
    return method == METHOD and isinstance(options, dict) and options.get(BOOTSTRAP) is True


def visibility(second, bootstrap):
    """The second direction needs a second score; level, replicates and seed need the bootstrap."""
    return {SECOND_DIRECTION: bool(second), **dict.fromkeys(BOOTSTRAP_FIELDS, bool(bootstrap))}


def _cancelled(cancel):
    if cancel is None:
        return False
    return bool(cancel.is_set()) if hasattr(cancel, "is_set") else bool(cancel())


def check_cancel(cancel):
    if _cancelled(cancel):
        raise PrecisionRecallCancelled("Precision–recall curve cancelled.")


# ----- recipe --------------------------------------------------------------------------------------------------------

def _get(options, name):
    return options.get(name, DEFAULTS[name])


def _choice(options, name):
    value = _get(options, name)
    if not isinstance(value, str) or value not in DIRECTIONS:
        raise FieldError(name, f"Choose a valid value for {name}.")
    return value


def _percent(options, name):
    value = _get(options, name)
    message = f"{name} must be a number greater than 0 and less than 100."
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", "."))
        except ValueError:
            raise FieldError(name, message) from None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(name, message)
    number = float(value)
    if not np.isfinite(number) or not 0 < number < 100:
        raise FieldError(name, message)
    return number


def _whole(options, name, low, high):
    """An exact integer (Python, NumPy or digits as text), never read through a float."""
    value = _get(options, name)
    message = f"{name} must be a whole number from {low:,} to {high:,}."
    if isinstance(value, (bool, np.bool_)):
        raise FieldError(name, message)
    if isinstance(value, str):
        if not _DIGITS.fullmatch(value):
            raise FieldError(name, message)
        value = int(value)
    else:
        try:
            value = index(value)
        except TypeError:
            raise FieldError(name, message) from None
    if not low <= value <= high:
        raise FieldError(name, message)
    return int(value)


@dataclass(frozen=True)
class Settings:
    outcome: str
    positive: str
    negative: str
    scores: tuple           # one or two column names
    directions: tuple       # one direction per score
    bootstrap: bool
    level: float | None
    replicates: int | None
    seed: int | None


def label(value):
    """A cell as the text the user types for it: the literal string, or a number without a spurious ``.0``."""
    if isinstance(value, str):
        return value
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and float(value).is_integer() \
            and abs(value) < 1e15:
        return str(int(value))
    return str(value)


def _code(options, field):
    value = options.get(field)
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_)):
        value = label(value)
    if not isinstance(value, str) or not value.strip():
        raise FieldError(field, f"Enter the exact label of the {field.lower()} rows.")
    return value


def read_settings(options):
    """The recipe alone, checked before any worksheet value is read."""
    if not isinstance(options, dict):
        raise ValueError("Precision–recall curve options must be a mapping.")
    names = {}
    for field in (OUTCOME, SCORE):
        name = options.get(field)
        if not isinstance(name, str) or not name:
            raise FieldError(field, f"Choose a column for {field}.")
        names[field] = name
    second = options.get(SECOND_SCORE)
    if second in (None, ""):
        second = None
    elif not isinstance(second, str):
        raise FieldError(SECOND_SCORE, f"Choose a column for {SECOND_SCORE}.")
    used = {names[OUTCOME]: OUTCOME}
    for field, name in ((SCORE, names[SCORE]), (SECOND_SCORE, second)):
        if name is None:
            continue
        if name in used:
            raise FieldError(field, f'Column "{name}" is already used for {used[name]}. '
                                    f"Choose a different column for {field}.")
        used[name] = field
    positive, negative = _code(options, POSITIVE), _code(options, NEGATIVE)
    if positive == negative:
        raise FieldError(NEGATIVE, "Positive and Negative must be different labels.")
    scores, directions = [names[SCORE]], [_choice(options, DIRECTION)]
    if second is not None:
        scores.append(second)
        directions.append(_choice(options, SECOND_DIRECTION))
    bootstrap = _get(options, BOOTSTRAP)
    if not isinstance(bootstrap, (bool, np.bool_)):
        raise FieldError(BOOTSTRAP, f"{BOOTSTRAP} must be on or off.")
    level = replicates = seed = None
    if bootstrap:
        level = _percent(options, LEVEL)
        replicates = _whole(options, REPLICATES, MIN_REPLICATES, MAX_REPLICATES)
        seed = _whole(options, SEED, 0, MAX_SEED)
    return Settings(names[OUTCOME], positive, negative, tuple(scores), tuple(directions), bool(bootstrap), level,
                    replicates, seed)


# ----- worksheet -----------------------------------------------------------------------------------------------------

def _missing(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, (float, np.floating)):
        return bool(isnan(float(value)))
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _column(frame, name, field):
    if name not in frame.columns:
        raise FieldError(field, f'Column "{name}" is not in the table.')
    column = frame[name]
    if isinstance(column, pd.DataFrame):
        raise FieldError(field, f'More than one column is called "{name}".')
    return column


def _numbers(series, name, field):
    """Floats with NaN for empty cells. A filled cell that is not a finite number names its row."""
    if pd.api.types.is_bool_dtype(series):
        raise FieldError(field, f'Column "{name}" must contain numbers.')
    raw = series.to_numpy(dtype=object)
    present = np.fromiter((not _missing(value) for value in raw), dtype=bool, count=len(raw))
    if pd.api.types.is_float_dtype(series) or pd.api.types.is_integer_dtype(series):
        values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    else:
        values = np.full(len(raw), np.nan)
        for position in np.flatnonzero(present):
            value = raw[position]
            if isinstance(value, (bool, np.bool_, complex, np.complexfloating)):
                continue
            try:
                values[position] = float(value.strip().replace(",", ".")) if isinstance(value, str) else float(value)
            except (TypeError, ValueError, OverflowError):
                continue
    bad = present & ~np.isfinite(values)
    if bad.any():
        row = int(np.flatnonzero(bad)[0]) + 1
        raise FieldError(field, f'Column "{name}" has a value that is not a finite number in row {row}.')
    return values


def _outcomes(series, settings):
    """1 for Positive, 0 for Negative, -1 for a blank cell; any other label is an error on its first row."""
    raw = series.to_numpy(dtype=object)
    status = np.full(len(raw), -1, dtype=np.int8)
    for position, value in enumerate(raw):
        if _missing(value):
            continue
        shown = label(value)
        if shown == settings.positive:
            status[position] = 1
        elif shown == settings.negative:
            status[position] = 0
        else:
            raise FieldError(OUTCOME, f'Outcome has the value "{shown}" in row {position + 1}, which is neither '
                                      f'Positive ("{settings.positive}") nor Negative ("{settings.negative}").')
    return status


@dataclass
class Plan:
    settings: Settings
    rows: np.ndarray            # 0-based sheet positions of the used samples, in sheet order
    y: np.ndarray               # 1 for Positive, 0 for Negative
    scores: list                # one float array per score, original scale
    excluded: list              # (row 0-based, outcome literal or None, reason)

    @property
    def n(self):
        return int(len(self.y))

    @property
    def positives(self):
        return int(self.y.sum())

    @property
    def negatives(self):
        return self.n - self.positives

    @property
    def prevalence(self):
        return self.positives / self.n

    def oriented(self, number):
        """Scores of the chosen column as a larger value always points to a positive (−0 is turned into 0)."""
        sign = 1 if self.settings.directions[number] == HIGHER else -1
        return sign * self.scores[number] + 0.0, sign


def prepare(frame, options):
    """Read recipe and worksheet, leave out incomplete rows and check the classes and the budget. Nothing is drawn."""
    settings = read_settings(options)
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("Precision–recall curve needs a worksheet.")
    status = _outcomes(_column(frame, settings.outcome, OUTCOME), settings)
    fields = (SCORE, SECOND_SCORE)
    values = [_numbers(_column(frame, name, field), name, field) for name, field in zip(settings.scores, fields)]
    complete = status >= 0
    for column in values:
        complete &= ~np.isnan(column)
    excluded = []
    raw = frame[settings.outcome].to_numpy(dtype=object)
    for position in np.flatnonzero(~complete):
        reasons = ([] if status[position] >= 0 else ["Outcome is blank or excluded"]) + [
            f"{field} is blank or excluded" for field, column in zip(fields, values) if np.isnan(column[position])]
        if len(reasons) == 1 + len(values):
            continue  # an empty row of the worksheet
        excluded.append((int(position), None if status[position] < 0 else label(raw[position]), "; ".join(reasons)))
    rows = np.flatnonzero(complete)
    y = status[rows].astype(np.int64)
    n, positives = len(rows), int(y.sum())
    if n == 0:
        raise FieldError(OUTCOME, "No row has an Outcome and a number in every score column.")
    if n > MAX_ROWS:
        raise FieldError(OUTCOME, f"Use at most {MAX_ROWS:,} rows (this selection has {n:,}).")
    if positives == 0:
        raise FieldError(OUTCOME, f"All {n:,} complete rows are Negative; at least one Positive row is needed.")
    if positives == n:
        raise FieldError(OUTCOME, f"All {n:,} complete rows are Positive; at least one Negative row is needed.")
    if settings.bootstrap and settings.replicates * n > BUDGET:
        raise FieldError(REPLICATES, f"Bootstrap replicates × samples = {settings.replicates:,} × {n:,} exceeds "
                                     f"the limit of {BUDGET:,}.")
    return Plan(settings, rows, y, [column[rows] for column in values], excluded)


def check_options(frame, options):
    """Everything the dialog can check before the worker starts; raises FieldError. Returns the Plan."""
    return prepare(frame, options)


# ----- curves --------------------------------------------------------------------------------------------------------

@dataclass
class Curve:
    name: str
    direction: str
    thresholds: np.ndarray      # original scale, strictest first
    tp: np.ndarray
    fp: np.ndarray
    precision: np.ndarray
    recall: np.ndarray
    ap: float
    auc: float


def build_curve(plan, number):
    oriented, sign = plan.oriented(number)
    thresholds, tp, fp = curve_points(plan.y, oriented)
    return Curve(plan.settings.scores[number], plan.settings.directions[number], sign * thresholds + 0.0,
                 tp, fp, tp / (tp + fp), tp / plan.positives, average_precision(plan.y, oriented),
                 roc_auc(plan.y, oriented))


# ----- bootstrap -----------------------------------------------------------------------------------------------------

def _groups(oriented):
    """Index of each sample's threshold among the distinct scores, strictest first."""
    distinct, inverse = np.unique(oriented, return_inverse=True)
    return len(distinct) - 1 - inverse.ravel(), len(distinct)


def _block_ap(group_of_positive, group_of_negative, groups, positives, draws_positive, draws_negative):
    """Average precision of each replicate of a block: per-threshold counts, cumulated, summed."""
    count = draws_positive.shape[0]
    offset = (np.arange(count, dtype=np.int64) * groups)[:, None]
    gained = np.bincount((group_of_positive[draws_positive] + offset).ravel(),
                         minlength=count * groups).reshape(count, groups)
    lost = np.bincount((group_of_negative[draws_negative] + offset).ravel(),
                       minlength=count * groups).reshape(count, groups)
    tp = np.cumsum(gained, axis=1)
    called = tp + np.cumsum(lost, axis=1)
    precision = np.divide(tp, called, out=np.zeros(tp.shape), where=called > 0)
    return (gained * precision).sum(axis=1) / positives


def bootstrap(plan, cancel=None):
    """Average precision of every score in every replicate, one row per score: shape (scores, replicates)."""
    settings = plan.settings
    positive, negative = np.flatnonzero(plan.y == 1), np.flatnonzero(plan.y == 0)
    oriented = [plan.oriented(number)[0] for number in range(len(settings.scores))]
    # Canonical order inside each class: by the first score, then by the second.
    keys = tuple(reversed(oriented))
    positive = positive[np.lexsort(tuple(key[positive] for key in keys))]
    negative = negative[np.lexsort(tuple(key[negative] for key in keys))]
    grouped = [_groups(values) for values in oriented]
    sides = [(groups[positive], groups[negative], size) for groups, size in grouped]
    rng = np.random.Generator(np.random.PCG64(settings.seed))
    total, size_p, size_n = settings.replicates, len(positive), len(negative)
    block = max(1, BLOCK_VALUES // plan.n)
    out = np.empty((len(oriented), total))
    for start in range(0, total, block):
        check_cancel(cancel)
        stop = min(start + block, total)
        draws_positive = np.empty((stop - start, size_p), dtype=np.int64)
        draws_negative = np.empty((stop - start, size_n), dtype=np.int64)
        for row in range(stop - start):
            draws_positive[row] = rng.integers(0, size_p, size=size_p)
            draws_negative[row] = rng.integers(0, size_n, size=size_n)
        for number, (group_p, group_n, groups) in enumerate(sides):
            out[number, start:stop] = _block_ap(group_p, group_n, groups, size_p, draws_positive, draws_negative)
    check_cancel(cancel)
    return out


def _interval(values, level):
    alpha = 1 - level / 100
    low, high = np.quantile(values, [alpha / 2, 1 - alpha / 2], method="linear")
    return float(low), float(high)


# ----- result --------------------------------------------------------------------------------------------------------

def _summary_table(plan, curves, intervals):
    rows = []
    for number, curve in enumerate(curves):
        row = {"Score": curve.name, "N": plan.n, "Positives": plan.positives, "Prevalence": plan.prevalence,
               "Average precision": curve.ap, "ROC AUC": curve.auc, "Direction": curve.direction}
        if intervals is not None:
            row["AP lower"], row["AP upper"] = intervals["scores"][number]
        rows.append(row)
    return pd.DataFrame(rows)


def _thresholds_table(plan, curve):
    return pd.DataFrame({"Threshold": curve.thresholds, "TP": curve.tp, "FP": curve.fp,
                         "TN": plan.negatives - curve.fp, "FN": plan.positives - curve.tp,
                         "Precision": curve.precision, "Recall": curve.recall}, columns=THRESHOLD_COLUMNS)


def _comparison_table(curves, intervals):
    first, second = curves
    row = {"First score": first.name, "Second score": second.name, "AP first": first.ap, "AP second": second.ap,
           "AP difference": second.ap - first.ap}
    if intervals is not None:
        row["Difference lower"], row["Difference upper"] = intervals["difference"]
    return pd.DataFrame([row])


def _excluded_table(plan):
    return pd.DataFrame({
        "Source row": [row + 1 for row, *_ in plan.excluded],
        "Outcome": pd.Series([outcome for _, outcome, _ in plan.excluded], dtype=object),
        "Reason": [reason for *_, reason in plan.excluded]})


def _settings_table(plan):
    settings = plan.settings
    values = {"Outcome column": settings.outcome, "Positive label": settings.positive,
              "Negative label": settings.negative, "Score": settings.scores[0],
              "Direction": settings.directions[0]}
    if len(settings.scores) == 2:
        values.update({"Second score": settings.scores[1], "Second direction": settings.directions[1]})
    values.update({"Common samples": plan.n, "Positives": plan.positives, "Negatives": plan.negatives,
                   "Prevalence": plan.prevalence, "Excluded rows": len(plan.excluded),
                   "Average precision": AP_DEFINITION,
                   "Tied scores": "Counted together at one threshold",
                   "Reference line": "Prevalence of the sample (positives / common samples)",
                   "Bootstrap CI": "On" if settings.bootstrap else "Off"})
    if settings.bootstrap:
        values.update({LEVEL: settings.level, REPLICATES: settings.replicates, SEED: settings.seed,
                       "Resampling": "Stratified by outcome; the same samples feed both scores",
                       "Random sequence": SEQUENCE, "Quantile rule": QUANTILE_RULE})
    return _report(values)


# ----- figure --------------------------------------------------------------------------------------------------------

def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def staircase(curve):
    """Vertices of the drawn curve: it starts at (0, 1) and holds the precision of each threshold over the recall
    it adds, so the area under it is the average precision."""
    previous = np.r_[0.0, curve.recall[:-1]]
    x = np.empty(2 * len(previous) + 1)
    y = np.empty_like(x)
    x[0], y[0] = 0.0, 1.0
    x[1::2], x[2::2] = previous, curve.recall
    y[1::2] = y[2::2] = curve.precision
    return x, y


def _figure(plan, curves, intervals):
    settings = plan.settings
    figure, axes = _plot(f"Precision–recall curve · {plan.n:,} samples, prevalence {plan.prevalence:.3g}",
                         "Recall", "Precision")
    axes._tramastat_numeric_axes = ("x", "y")
    for number, (curve, color) in enumerate(zip(curves, COLORS, strict=False)):
        text = f"{curve.name}: AP {curve.ap:.4g}"
        if intervals is not None:
            low, high = intervals["scores"][number]
            text += f" ({settings.level:g}% CI {low:.3g} to {high:.3g})"
        line, = axes.plot(*staircase(curve), color=color, linewidth=2, zorder=3, label=text)
        line.set_gid(f"{GID}curve-{'ab'[number]}")
    reference = axes.axhline(plan.prevalence, color=REFERENCE_COLOR, linestyle="--", linewidth=1.3, zorder=1,
                             label=f"Prevalence {plan.prevalence:.3g}")
    reference.set_gid(f"{GID}prevalence")
    if len(curves) == 2:
        text = f"AP difference ({curves[1].name} − {curves[0].name}): {curves[1].ap - curves[0].ap:.3g}"
        if intervals is not None:
            low, high = intervals["difference"]
            text += f" ({settings.level:g}% CI {low:.3g} to {high:.3g})"
        axes.plot([], [], " ", label=text)
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1.02)
    legend = axes.legend(loc="lower left", fontsize=8.5)
    _plain(axes.title, *legend.get_texts())
    return figure


# ----- analysis ------------------------------------------------------------------------------------------------------

def analyse(frame, options, *, cancel=None):
    """Return the Result of Precision–recall curve; ``cancel`` is an optional threading.Event."""
    check_cancel(cancel)
    plan = prepare(frame, options)
    curves = [build_curve(plan, number) for number in range(len(plan.scores))]
    intervals = None
    if plan.settings.bootstrap:
        replicates = bootstrap(plan, cancel)
        intervals = {"scores": [_interval(values, plan.settings.level) for values in replicates]}
        if len(curves) == 2:
            intervals["difference"] = _interval(replicates[1] - replicates[0], plan.settings.level)
    check_cancel(cancel)
    tables = {SUMMARY: _summary_table(plan, curves, intervals)}
    for curve in curves:
        tables[f"{THRESHOLDS}{curve.name}"] = _thresholds_table(plan, curve)
    if len(curves) == 2:
        tables[COMPARISON] = _comparison_table(curves, intervals)
    tables[SETTINGS] = _settings_table(plan)
    if plan.excluded:
        tables[EXCLUDED] = _excluded_table(plan)
    return Result(tables, _figure(plan, curves, intervals))
