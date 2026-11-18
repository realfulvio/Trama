"""Repeated-measures correlation (Bakdash and Marusich, 2017): options, engine, sheets and native figure.

The model gives every subject its own intercept and all subjects one common slope. X and Y are centred within each
subject that has at least two complete pairs; on those centred pairs

    r = Sxy / sqrt(Sxx · Syy),  b = Sxy / Sxx,  intercept_j = ȳ_j − b · x̄_j,
    df = N − S − 1,  t = r · sqrt(df / (1 − r²)),  p = 2 · P(T_df ≥ |t|),

where N counts the pairs in the fit and S the subjects in the fit. This is not Pearson's r of the pooled or averaged
data: the between-subject differences of X and Y are removed before anything is correlated.

The optional interval resamples whole subjects with their pairs. The used subjects, in the order of their first
complete pair, are drawn with ``Generator(PCG64(seed))``: for each replicate, in order, ``integers(0, S, size=S)``.
Every draw is an independent copy of that subject, so a replicate's coefficient is r on the pooled within-subject
sums of the drawn subjects; copies are never materialised and the generator belongs to this calculation only. The
interval is the two-sided linear-interpolation percentile of the valid replicates and is approximate.

A recipe uses the canonical English keys of ``OPTIONS``; missing keys take ``DEFAULTS``. Every error that the user
can correct names its dialog field through ``FieldError``. ``prepare`` reads and checks everything without
resampling (the dialog calls it); ``calculate`` runs the bootstrap on the worker and polls ``cancel`` before every
replicate.
"""
from dataclasses import dataclass
from math import isnan
from operator import index
import re

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from scipy import stats

from .category_graphs import COLORS
from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled
from .processing import _check_integer_precision
from .reporting import Result

RMCORR = "Repeated-measures correlation"
SUBJECT, X, Y = "Subject", "X", "Y"
INTERVAL, LEVEL, REPLICATES, SEED, GRAPH = (
    "Confidence interval", "Confidence level (%)", "Bootstrap replicates", "Seed", "Show graph")
NO_INTERVAL, SUBJECT_BOOTSTRAP = INTERVALS = ("None", "Subject bootstrap")
OPTIONS = {SUBJECT: None, X: None, Y: None, INTERVAL: INTERVALS, LEVEL: 95.0, REPLICATES: 2000, SEED: 0,
           GRAPH: True}
DEFAULTS = {INTERVAL: NO_INTERVAL, LEVEL: 95.0, REPLICATES: 2000, SEED: 0, GRAPH: True}
COLUMN_FIELDS = (SUBJECT, X, Y)
BOOTSTRAP_FIELDS = (LEVEL, REPLICATES, SEED)

SUMMARY, PARTICIPANTS, PAIRS, BOOTSTRAP = RMCORR, "Participants", "Pairs", "Bootstrap"
SUMMARY_COLUMNS = ["N", "Subjects", "df", "Coefficient", "Slope", "t", "p", "Lower", "Upper", "Bootstrap valid",
                   "Interval status"]
# Reproducibility metadata of a bootstrap interval, appended to the summary row (never a sheet of its own).
BOOTSTRAP_COLUMNS = [LEVEL, REPLICATES, SEED, "Random sequence"]
PARTICIPANT_COLUMNS = ["Subject", "Pairs used", "Intercept", "Status"]
PAIR_COLUMNS = ["Subject", "Source row", "X", "Y", "Fitted", "Status"]
REPLICATE_COLUMNS = ["Replicate", "Coefficient", "Status"]

USED, MISSING_PAIR, SINGLETON, NO_PAIRS = "Used", "Missing pair", "Singleton", "No complete pairs"
VALID, DEGENERATE = "Valid", "Degenerate"
NOT_REQUESTED = "Not requested"
APPROXIMATE = "Approximate percentile interval (subject bootstrap)"
SEQUENCE = "PCG64 v1: Generator(PCG64(seed)); per replicate integers(0, S, size=S) over the used subjects"

MAX_PAIRS, MAX_SUBJECTS, MAX_WORK = 50_000, 500, 2_000_000
MIN_REPLICATES, MAX_REPLICATES, MAX_SEED = 100, 10_000, 2**64 - 1
MAGNITUDE = 1e100
# Within-subject spread below this fraction of the magnitude is lost to rounding of the stored values.
PRECISION = 1e-12
# r is ±1 to double precision: 1 − r² (from the residual sum of squares) at most one unit in the last place.
PERFECT = 2.0 ** -52
LEGEND_LIMIT = 40
MARKERS = ("o", "s", "^", "D", "v")
SINGLETON_COLOR = "#7d8da1"
GID_FIT, GID_POINTS, GID_SINGLETONS = "rmcorr-fit-{}", "rmcorr-points-{}", "rmcorr-singletons"

# Interface captions; the recipe keeps the English field names and choices.
LABEL_KEYS = {SUBJECT: "rmcorr.field.subject", X: "rmcorr.field.x", Y: "rmcorr.field.y",
              INTERVAL: "rmcorr.field.interval", LEVEL: "rmcorr.field.level", REPLICATES: "rmcorr.field.replicates",
              SEED: "rmcorr.field.seed", GRAPH: "rmcorr.field.graph"}
CHOICE_KEYS = {NO_INTERVAL: "rmcorr.choice.none", SUBJECT_BOOTSTRAP: "rmcorr.choice.bootstrap"}
ERROR_PREFIX = "rmcorr.error."
_DIGITS = re.compile(r"\s*\+?[0-9]+\s*")


class RmcorrCancelled(MonteCarloCancelled, InterruptedError):
    """The bootstrap was cancelled before a result was published.

    ``InterruptedError`` for callers of the dispatcher; ``MonteCarloCancelled`` for the application, which keeps the
    last confirmed result of every cancellable job through that one path.
    """


def cancellable(method, options):
    """True when the run resamples subjects and deserves a Cancel button."""
    return (method == RMCORR and isinstance(options, dict)
            and options.get(INTERVAL, DEFAULTS[INTERVAL]) == SUBJECT_BOOTSTRAP)


def visibility(interval):
    """The level, replicates and seed are used only by the subject bootstrap."""
    active = interval == SUBJECT_BOOTSTRAP
    return dict.fromkeys(BOOTSTRAP_FIELDS, active)


def _cancelled(cancel):
    if cancel is None:
        return False
    if hasattr(cancel, "is_set"):
        return bool(cancel.is_set())
    return bool(cancel())


def check_cancel(cancel):
    if _cancelled(cancel):
        raise RmcorrCancelled("Repeated-measures correlation cancelled.")


# ----- options -----------------------------------------------------------------------------------------------------

def _get(options, name):
    return options.get(name, DEFAULTS[name])


def _choice(options, name, choices):
    value = _get(options, name)
    if not isinstance(value, str) or value not in choices:
        raise FieldError(name, f"Choose a valid {name}.")
    return value


def _flag(options, name):
    value = _get(options, name)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name} must be on or off.")
    return bool(value)


def _whole(options, name, low, high):
    """An exact integer: Python or NumPy integers, or digits typed as text. Never read through a float."""
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


def _level(options):
    value = _get(options, LEVEL)
    message = f"{LEVEL} must be a finite number strictly between 0 and 100."
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise FieldError(LEVEL, message)
    number = float(value)
    if not np.isfinite(number) or not 0 < number < 100:
        raise FieldError(LEVEL, message)
    return number


@dataclass
class Settings:
    subject: str
    x: str
    y: str
    interval: str
    level: float | None
    replicates: int | None
    seed: int | None
    graph: bool


def read_settings(options):
    """The recipe alone, checked before any worksheet value is read."""
    if not isinstance(options, dict):
        raise ValueError("Repeated-measures correlation options must be a mapping.")
    names = {}
    for field in COLUMN_FIELDS:
        name = options.get(field)
        if not isinstance(name, str) or not name:
            raise FieldError(field, f"Choose a column for {field}.")
        names[field] = name
    if names[X] == names[SUBJECT]:
        raise FieldError(X, "Choose three different columns for Subject, X and Y.")
    if names[Y] in (names[SUBJECT], names[X]):
        raise FieldError(Y, "Choose three different columns for Subject, X and Y.")
    interval = _choice(options, INTERVAL, INTERVALS)
    graph = _flag(options, GRAPH)
    level = replicates = seed = None
    if interval == SUBJECT_BOOTSTRAP:
        level = _level(options)
        replicates = _whole(options, REPLICATES, MIN_REPLICATES, MAX_REPLICATES)
        seed = _whole(options, SEED, 0, MAX_SEED)
    return Settings(names[SUBJECT], names[X], names[Y], interval, level, replicates, seed, graph)


# ----- worksheet -------------------------------------------------------------------------------------------------

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


def _key(value):
    """Typed identity of a subject: text never equals a number, 1 equals 1.0, True is not 1."""
    if isinstance(value, str):
        return "s", value
    if isinstance(value, (bool, np.bool_)):
        return "b", bool(value)
    if isinstance(value, np.integer):
        return "n", int(value)
    if isinstance(value, np.floating):
        return "n", float(value)
    if isinstance(value, (int, float)):
        return "n", value
    try:
        hash(value)
    except TypeError:
        return "r", type(value).__name__, repr(value)
    return "o", type(value).__name__, value


def label(value):
    """A subject as legend text: the literal string, or a number written without a spurious ``.0``."""
    if isinstance(value, str):
        return value
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and float(value).is_integer() \
            and abs(value) < 1e15:
        return str(int(value))
    return str(value)


def _column(frame, name, field):
    if name not in frame.columns:
        raise FieldError(field, f'Column "{name}" is not in the table.')
    return frame[name]


def _numbers(series, name, field):
    """Floats with NaN for empty cells. A filled cell that is not a finite number names its row."""
    if pd.api.types.is_bool_dtype(series):
        raise FieldError(field, f'Column "{name}" must contain numbers.')
    raw = series.to_numpy(dtype=object)
    present = np.fromiter((not _missing(value) for value in raw), dtype=bool, count=len(raw))
    if pd.api.types.is_integer_dtype(series):
        numbers = pd.to_numeric(series, errors="coerce", dtype_backend="numpy_nullable")
        values = numbers.to_numpy(dtype=float, na_value=np.nan)
        _check_integer_precision(numbers, values, field)
    elif pd.api.types.is_float_dtype(series):
        values = series.to_numpy(dtype=float, na_value=np.nan)
    else:
        values = np.full(len(raw), np.nan)
        for position in np.flatnonzero(present):
            value = raw[position]
            if isinstance(value, (bool, np.bool_, complex, np.complexfloating)):
                continue
            try:
                values[position] = float(value.strip()) if isinstance(value, str) else float(value)
            except (TypeError, ValueError, OverflowError):
                continue
    bad = present & ~np.isfinite(values)
    if bad.any():
        row = int(np.flatnonzero(bad)[0]) + 1
        raise FieldError(field, f'Column "{name}" has a value that is not a finite number in row {row}.')
    large = np.abs(np.where(present, values, 0.0)) > MAGNITUDE
    if large.any():
        row = int(np.flatnonzero(large)[0]) + 1
        raise FieldError(field, f'Column "{name}" has a value outside −1e100 to 1e100 in row {row}.')
    return values, present


@dataclass
class Plan:
    settings: Settings
    rows: np.ndarray            # source positions (0-based) of the listed rows, in sheet order
    subjects: list              # subject value of each listed row (first literal of its key)
    codes: np.ndarray           # participant index of each listed row
    x: np.ndarray
    y: np.ndarray
    status: list                # Used, Missing pair or Singleton per listed row
    participants: list          # [code, value, status, complete pairs] in report order
    first: list                 # literal subject value of each participant code (first occurrence)
    used: np.ndarray            # participant indices in the fit, in order of their first complete pair
    group: np.ndarray           # used-subject number (0..S−1) of each listed row, −1 when not in the fit
    u: np.ndarray               # centred and scaled X and Y of the fitted pairs, in sheet order
    w: np.ndarray
    sxx: np.ndarray             # scaled within-subject sums of each used subject
    syy: np.ndarray
    sxy: np.ndarray
    x_mean: np.ndarray          # subject means of X and Y in the original units
    y_mean: np.ndarray
    x_scale: float
    y_scale: float
    n: int


def _within(values, group, count):
    """Accurate subject means and centred values: shifted by the first value of the subject, then corrected."""
    first = np.full(count, np.nan)
    order = np.arange(len(group))[::-1]
    first[group[order]] = values[order]
    shifted = values - first[group]
    sizes = np.bincount(group, minlength=count)
    mean = np.bincount(group, shifted, minlength=count) / sizes
    centred = shifted - mean[group]
    correction = np.bincount(group, centred, minlength=count) / sizes
    centred -= correction[group]
    return first + mean + correction, centred


def prepare(frame, options):
    """Read the recipe and the worksheet and form the within-subject sums. No resampling happens here."""
    settings = read_settings(options)
    subject_series = _column(frame, settings.subject, SUBJECT)
    x_series = _column(frame, settings.x, X)
    y_series = _column(frame, settings.y, Y)
    xs, x_present = _numbers(x_series, settings.x, X)
    ys, y_present = _numbers(y_series, settings.y, Y)
    raw_subjects = subject_series.to_numpy(dtype=object)
    keys, first_seen, listed, values = {}, [], [], []
    codes, complete = [], []
    for position, value in enumerate(raw_subjects):
        absent = _missing(value)
        if absent:
            if x_present[position] or y_present[position]:
                raise FieldError(SUBJECT, f"Row {position + 1} has an X or Y value but no subject.")
            continue
        key = _key(value)
        code = keys.get(key)
        if code is None:
            code = keys[key] = len(first_seen)
            first_seen.append(value)
        listed.append(position)
        values.append(first_seen[code])
        codes.append(code)
        complete.append(bool(x_present[position] and y_present[position]))
    listed = np.asarray(listed, dtype=np.int64)
    codes = np.asarray(codes, dtype=np.int64)
    complete = np.asarray(complete, dtype=bool)
    count = len(first_seen)
    pairs = np.bincount(codes[complete], minlength=count) if count else np.zeros(0, dtype=np.int64)
    total = int(pairs.sum())
    if total > MAX_PAIRS:
        raise FieldError(Y, f"At most {MAX_PAIRS:,} complete pairs are supported; {total:,} were found.")
    # Report order: first complete pair in the sheet, then subjects without any, by first appearance.
    first_pair = np.full(count, len(raw_subjects), dtype=np.int64)
    for position, code in zip(listed[complete][::-1], codes[complete][::-1]):
        first_pair[code] = position
    with_pairs = [code for code in sorted(range(count), key=lambda code: first_pair[code]) if pairs[code] > 0]
    without = [code for code in range(count) if pairs[code] == 0]
    report = with_pairs + without
    used = np.asarray([code for code in with_pairs if pairs[code] >= 2], dtype=np.int64)
    subjects = len(used)
    if subjects > MAX_SUBJECTS:
        raise FieldError(SUBJECT, f"At most {MAX_SUBJECTS:,} subjects with two or more complete pairs are "
                                  f"supported; {subjects:,} were found.")
    if subjects < 2:
        raise FieldError(SUBJECT, "At least two subjects with two or more complete pairs are required; "
                                  f"{subjects} were found.")
    status_of = {code: USED if pairs[code] >= 2 else SINGLETON if pairs[code] == 1 else NO_PAIRS
                 for code in range(count)}
    participants = [[code, first_seen[code], status_of[code], int(pairs[code])] for code in report]
    number = np.full(count, -1, dtype=np.int64)
    number[used] = np.arange(subjects)
    group = np.where(complete, number[codes], -1)
    row_status = [MISSING_PAIR if not done else USED if status_of[code] == USED else SINGLETON
                  for code, done in zip(codes, complete)]
    in_fit = group >= 0
    fit_group = group[in_fit]
    x_fit, y_fit = xs[listed][in_fit], ys[listed][in_fit]
    n = int(in_fit.sum())
    df = n - subjects - 1
    if df <= 0:
        raise FieldError(SUBJECT, f"The fit needs N − S − 1 > 0; N = {n} and S = {subjects}.")
    x_mean, x_centred = _within(x_fit, fit_group, subjects)
    y_mean, y_centred = _within(y_fit, fit_group, subjects)
    x_scale, y_scale = _scale(x_centred, x_fit, X, settings.x), _scale(y_centred, y_fit, Y, settings.y)
    u, w = x_centred / x_scale, y_centred / y_scale
    sxx = np.bincount(fit_group, u * u, minlength=subjects)
    syy = np.bincount(fit_group, w * w, minlength=subjects)
    sxy = np.bincount(fit_group, u * w, minlength=subjects)
    if settings.interval == SUBJECT_BOOTSTRAP and subjects * settings.replicates > MAX_WORK:
        raise FieldError(REPLICATES, f"Subjects × replicates is {subjects * settings.replicates:,}; the limit is "
                                     f"{MAX_WORK:,}. Use fewer replicates.")
    return Plan(settings, listed, values, codes, xs[listed], ys[listed], row_status, participants, first_seen,
                used, group, u, w, sxx, syy, sxy, x_mean, y_mean, x_scale, y_scale, n)


def _scale(centred, values, field, name):
    spread = float(np.max(np.abs(centred))) if len(centred) else 0.0
    if spread == 0:
        raise FieldError(field, f'Column "{name}" does not vary within any subject with two or more complete pairs.')
    magnitude = float(np.max(np.abs(values)))
    if spread < PRECISION * magnitude:
        raise FieldError(field, f'Column "{name}" varies within subjects by less than the precision of its values. '
                                "Subtract a constant or change the unit.")
    return spread


# ----- calculation -----------------------------------------------------------------------------------------------

def coefficient(sxx, syy, sxy):
    """r of pooled within-subject sums; None when either variable has no within-subject variation."""
    if not sxx > 0 or not syy > 0:
        return None
    return float(np.clip(sxy / np.sqrt(sxx * syy), -1.0, 1.0))


@dataclass
class Estimate:
    n: int
    subjects: int
    df: int
    r: float
    slope: float
    t: float
    p: float
    intercepts: np.ndarray
    perfect: bool


def estimate(plan):
    sxx, syy, sxy = float(plan.sxx.sum()), float(plan.syy.sum()), float(plan.sxy.sum())
    subjects, n = len(plan.used), plan.n
    df = n - subjects - 1
    scaled_slope = sxy / sxx
    # 1 − r² from the residuals themselves: no cancellation of Syy − Sxy²/Sxx near a perfect fit.
    residual = plan.w - scaled_slope * plan.u
    loss = float(residual @ residual) / syy
    slope = scaled_slope * plan.y_scale / plan.x_scale
    intercepts = plan.y_mean - slope * plan.x_mean
    perfect = loss <= PERFECT
    if perfect:
        r = 1.0 if sxy > 0 else -1.0
        t, p = (np.inf if r > 0 else -np.inf), 0.0
    else:
        r = coefficient(sxx, syy, sxy)
        t = r * np.sqrt(df / loss)
        p = float(2 * stats.t.sf(abs(t), df))
    return Estimate(n, subjects, df, float(r), float(slope), float(t), float(p), intercepts, bool(perfect))


def bootstrap(plan, cancel=None):
    """Coefficients of the subject bootstrap, NaN for a degenerate replicate. Polls ``cancel`` before each one."""
    settings = plan.settings
    subjects = len(plan.used)
    stacked = np.column_stack((plan.sxx, plan.syy, plan.sxy))
    generator = np.random.Generator(np.random.PCG64(settings.seed))
    values = np.full(settings.replicates, np.nan)
    for replicate in range(settings.replicates):
        check_cancel(cancel)
        drawn = generator.integers(0, subjects, size=subjects)
        sxx, syy, sxy = np.bincount(drawn, minlength=subjects) @ stacked
        r = coefficient(sxx, syy, sxy)
        if r is not None:
            values[replicate] = r
    check_cancel(cancel)
    return values


def interval(values, level):
    """Percentile limits, the valid count and the status. Below 80 % valid replicates the limits stay empty."""
    valid = values[np.isfinite(values)]
    count, total = len(valid), len(values)
    if 5 * count < 4 * total or count == 0:
        return (None, None, count,
                f"Not available: {count:,} of {total:,} replicates are valid; at least 80% are required.")
    alpha = 1 - level / 100
    low, high = np.quantile(valid, [alpha / 2, 1 - alpha / 2], method="linear")
    return float(low), float(high), count, APPROXIMATE


def calculate(plan, cancel=None):
    """All sheets and the figure. A cancelled bootstrap raises ``RmcorrCancelled`` and returns nothing."""
    settings = plan.settings
    fit = estimate(plan)
    tables = {}
    summary = {"N": fit.n, "Subjects": fit.subjects, "df": fit.df, "Coefficient": fit.r, "Slope": fit.slope,
               "t": fit.t, "p": fit.p, "Lower": np.nan, "Upper": np.nan, "Bootstrap valid": np.nan,
               "Interval status": NOT_REQUESTED}
    replicates = None
    if settings.interval == SUBJECT_BOOTSTRAP:
        replicates = bootstrap(plan, cancel)
        low, high, count, status = interval(replicates, settings.level)
        summary.update({"Lower": np.nan if low is None else low, "Upper": np.nan if high is None else high,
                        "Bootstrap valid": count, "Interval status": status,
                        LEVEL: settings.level, REPLICATES: settings.replicates, SEED: str(settings.seed),
                        "Random sequence": SEQUENCE})
    columns = SUMMARY_COLUMNS + (BOOTSTRAP_COLUMNS if replicates is not None else [])
    tables[SUMMARY] = pd.DataFrame([summary], columns=columns)
    tables[PARTICIPANTS] = _participants(plan, fit)
    tables[PAIRS] = _pairs(plan, fit)
    if replicates is not None:
        tables[BOOTSTRAP] = pd.DataFrame({
            "Replicate": np.arange(1, len(replicates) + 1),
            "Coefficient": replicates,
            "Status": np.where(np.isfinite(replicates), VALID, DEGENERATE),
        }, columns=REPLICATE_COLUMNS)
    figure = figure_for(plan, fit) if settings.graph else None
    return Result(tables, figure)


def _participants(plan, fit):
    intercept_of = {int(code): float(value) for code, value in zip(plan.used, fit.intercepts)}
    rows = [{"Subject": value, "Pairs used": complete if status == USED else 0,
             "Intercept": intercept_of.get(int(code), np.nan), "Status": status}
            for code, value, status, complete in plan.participants]
    table = pd.DataFrame(rows, columns=PARTICIPANT_COLUMNS)
    table["Subject"] = pd.Series([row["Subject"] for row in rows], dtype=object)
    return table


def _pairs(plan, fit):
    fitted = np.full(len(plan.rows), np.nan)
    in_fit = plan.group >= 0
    fitted[in_fit] = fit.intercepts[plan.group[in_fit]] + fit.slope * plan.x[in_fit]
    table = pd.DataFrame({"Subject": pd.Series(plan.subjects, dtype=object), "Source row": plan.rows + 1,
                          "X": plan.x, "Y": plan.y, "Fitted": fitted, "Status": plan.status},
                         columns=PAIR_COLUMNS)
    return table


# ----- figure ------------------------------------------------------------------------------------------------------

def _literal(artist):
    if artist is not None and hasattr(artist, "set_parse_math"):
        artist.set_parse_math(False)
    return artist


def style_of(number):
    """Colour and marker of the used subject ``number`` (0-based): 40 distinct pairs, then they repeat."""
    return COLORS[number % len(COLORS)], MARKERS[(number // len(COLORS)) % len(MARKERS)]


def figure_for(plan, fit):
    figure = Figure(figsize=(8, 5), dpi=100, layout="constrained")
    axes = figure.add_subplot()
    axes.set(title=RMCORR, xlabel=plan.settings.x, ylabel=plan.settings.y)
    axes.spines[["right", "top"]].set_visible(False)
    handles, labels = [], []
    in_fit = plan.group >= 0
    for number, code in enumerate(plan.used):
        rows = in_fit & (plan.group == number)
        xs, ys = plan.x[rows], plan.y[rows]
        color, marker = style_of(number)
        axes.plot(xs, ys, linestyle="none", marker=marker, color=color, markersize=5,
                  gid=GID_POINTS.format(number + 1))
        low, high = float(xs.min()), float(xs.max())
        intercept = float(fit.intercepts[number])
        axes.plot([low, high], [intercept + fit.slope * low, intercept + fit.slope * high], color=color,
                  linewidth=1.5, gid=GID_FIT.format(number + 1))
        if len(plan.used) <= LEGEND_LIMIT:
            handles.append(Line2D([], [], color=color, marker=marker, markersize=5, linewidth=1.5))
            labels.append(label(plan.first[int(code)]))
    singles = np.asarray([status == SINGLETON for status in plan.status], dtype=bool)
    if singles.any():
        axes.plot(plan.x[singles], plan.y[singles], linestyle="none", marker="o", markerfacecolor="none",
                  color=SINGLETON_COLOR, markersize=5, gid=GID_SINGLETONS)
    if len(plan.used) > LEGEND_LIMIT:
        handles = [Line2D([], [], color="#4a5a6a", marker="o", linestyle="none", markersize=5),
                   Line2D([], [], color="#4a5a6a", linewidth=1.5)]
        labels = [f"Pairs of {len(plan.used)} subjects (one colour and marker per subject; they repeat after 40)",
                  "Subject fits: own intercept, common slope, over the subject's observed X"]
    if singles.any():
        handles.append(Line2D([], [], color=SINGLETON_COLOR, marker="o", markerfacecolor="none", linestyle="none",
                              markersize=5))
        labels.append("Single complete pair (not in the fit)")
    title = f"r rm = {fit.r:.3f}, slope = {fit.slope:.4g}\nN = {fit.n}, subjects = {fit.subjects}, df = {fit.df}"
    if len(plan.used) > LEGEND_LIMIT:
        title += "\nIntercepts: Participants sheet"
    legend = axes.legend(handles, labels, title=title, loc="upper left", bbox_to_anchor=(1.02, 1.0),
                         borderaxespad=0, fontsize="small", title_fontsize="small", frameon=False)
    _literal(legend.get_title())
    for text in legend.get_texts():
        _literal(text)
    for artist in (axes.title, axes.xaxis.label, axes.yaxis.label):
        _literal(artist)
    axes._tramastat_numeric_axes = ("x", "y")
    return figure


def analyse(frame, options, *, cancel=None):
    """The dispatcher entry point: validate, then calculate on the calling (worker) thread."""
    return calculate(prepare(frame, options), cancel=cancel)
