"""Bland–Altman for repeated pairs: agreement of two methods measured on the same subject more than once.

Each worksheet row holds one pair (First, Second) already matched by the user; rows are never paired
automatically. The model is the one Bland and Altman (2007, "Agreement between methods of measurement with
multiple observations per individual", J Biopharm Stat 17:571–582) describe for a quantity that may vary between
occasions: the difference d of a pair is

    d_si = mu + b_s + e_si,   b_s ~ N(0, sigma_b²),   e_si ~ N(0, sigma_w²),

and the limits of agreement for one new pair on one new subject are mu ± z · sqrt(sigma_w² + sigma_b²), with
z = Phi⁻¹((1 + coverage / 100) / 2).

Estimator (one-way random-effects ANOVA of the differences, method of moments)
    For subject s with m_s pairs, d̄_s is the mean difference and SS_s the sum of squared deviations from it.
    N = Σ m_s pairs, g subjects.
        bias      = Σ m_s d̄_s / N                       (the mean of all pairs)
        MS within = Σ SS_s / (N − g)
        MS between= Σ m_s (d̄_s − bias)² / (g − 1)
        m0        = (N² − Σ m_s²) / ((g − 1) N)
        sigma_b²  = max(0, (MS between − MS within) / m0)      ("at the boundary" when the raw value is < 0)
        sigma_w²  = MS within
    In Log ratio mode d = log(First) − log(Second); bias and limits are reported as exp(·) on the ratio scale, the
    variance components stay on the log scale.

Subject bootstrap (optional percentile intervals for the bias and for each limit)
    ``Generator(PCG64(seed))``; for each replicate, in order, ``integers(0, g, size=g)`` over the subjects in the order
    of their first used pair. Every draw is a new subject carrying all its pairs, so a replicate is the estimator on
    the per-subject summaries (m_s, d̄_s, SS_s) of the drawn subjects; no row is copied. A replicate where every drawn
    subject has a single pair has no within-subject degree of freedom: it is counted as invalid and left out of the
    percentiles. With fewer than 90 % valid replicates the intervals stay empty. Quantiles use the linear rule
    (``numpy.quantile(method="linear")``). The replicates are split into contiguous blocks; each block starts from the
    exact generator state of its first replicate, so the result is the same with 1 or N processes.

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
from matplotlib.ticker import StrMethodFormatter
from scipy import stats

from . import parallel
from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled
from .processing import _check_integer_precision
from .reporting import Result, _plot

METHOD = "Bland–Altman for repeated pairs"
SUBJECT, OCCASION, FIRST, SECOND = "Subject", "Occasion", "First", "Second"
MODE, COVERAGE, INTERVALS, LEVEL, REPLICATES, SEED, GRAPH = (
    "Mode", "Coverage", "Confidence intervals", "Confidence level (%)", "Bootstrap replicates", "Seed", "Graph")
DIFFERENCE, LOG_RATIO = MODES = ("Difference", "Log ratio")
NO_INTERVAL, SUBJECT_BOOTSTRAP = INTERVAL_CHOICES = ("None", "Subject bootstrap")
PAIRS_VIEW, SUBJECT_VIEW = GRAPHS = ("Pairs", "Subject diagnostics")

# The dialog builds its controls from these defaults: None is a column, "Optional" an optional column, tuples are
# choices (the first is the default), floats and ints are entries.
OPTIONS = {SUBJECT: None, OCCASION: "Optional", FIRST: None, SECOND: None, MODE: MODES, COVERAGE: 95.0,
           INTERVALS: INTERVAL_CHOICES, LEVEL: 95.0, REPLICATES: 2000, SEED: 0, GRAPH: GRAPHS}
DEFAULTS = {MODE: DIFFERENCE, COVERAGE: 95.0, INTERVALS: NO_INTERVAL, LEVEL: 95.0, REPLICATES: 2000, SEED: 0,
            GRAPH: PAIRS_VIEW}
COLUMN_FIELDS = (SUBJECT, FIRST, SECOND)
BOOTSTRAP_FIELDS = (LEVEL, REPLICATES, SEED)
NUMBER_FIELDS = (COVERAGE, LEVEL, REPLICATES, SEED)

MIN_SUBJECTS = 3
MAX_PAIRS = 200_000
MIN_REPLICATES, MAX_REPLICATES, MAX_SEED = 199, 20_000, 2**32 - 1
MAX_WORK = 40_000_000           # replicates × subjects
MAGNITUDE = 1e100               # |First|, |Second| at most: differences, squares and ratios stay finite
VALID_SHARE = 0.9
PARALLEL_WORK = 200_000         # replicates × subjects below which the pool is not worth starting
CANCEL_BLOCK = 256              # replicates between two cancellation checks
QUANTILE_RULE = "Linear interpolation (numpy.quantile, method=\"linear\")"
SEQUENCE = "PCG64: Generator(PCG64(seed)); per replicate integers(0, g, size=g) over the subjects in order of first use"

AGREEMENT, SUBJECTS, PAIRS, EXCLUDED = "Agreement", "Subjects", "Pairs", "Excluded rows"
ESTIMATED, BOUNDARY = "Estimated", "At boundary (set to 0)"
NOT_REQUESTED, INTERVAL_OK, TOO_FEW_VALID = "Not requested", "Percentile interval", "Too few valid replicates"
GID = "ba-repeated:"
POINT_COLOR, LINE_COLOR, NEUTRAL_COLOR = "#2f6f8f", "#aa5440", "#9aa5ab"

LABEL_KEYS = {}  # the captions live in analisi.interface_catalog (one dedicated section)
ERROR_PREFIX = "barep.error."
_DIGITS = re.compile(r"\s*\+?[0-9]+\s*")


class BlandAltmanRepeatedCancelled(MonteCarloCancelled, InterruptedError):
    """The bootstrap was cancelled; the application keeps the last confirmed result."""


def cancellable(method, options):
    return (method == METHOD and isinstance(options, dict)
            and options.get(INTERVALS, DEFAULTS[INTERVALS]) == SUBJECT_BOOTSTRAP)


def visibility(intervals):
    """Level, replicates and seed only apply to the subject bootstrap."""
    return dict.fromkeys(BOOTSTRAP_FIELDS, intervals == SUBJECT_BOOTSTRAP)


def _cancelled(cancel):
    if cancel is None:
        return False
    return bool(cancel.is_set()) if hasattr(cancel, "is_set") else bool(cancel())


def check_cancel(cancel):
    if _cancelled(cancel):
        raise BlandAltmanRepeatedCancelled("Bland–Altman for repeated pairs cancelled.")


# ----- recipe --------------------------------------------------------------------------------------------------------

def _get(options, name):
    return options.get(name, DEFAULTS[name])


def _choice(options, name, choices):
    value = _get(options, name)
    if not isinstance(value, str) or value not in choices:
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
    subject: str
    occasion: str | None
    first: str
    second: str
    mode: str
    coverage: float
    intervals: str
    level: float | None
    replicates: int | None
    seed: int | None
    graph: str


def read_settings(options):
    """The recipe alone, checked before any worksheet value is read."""
    if not isinstance(options, dict):
        raise ValueError("Bland–Altman for repeated pairs options must be a mapping.")
    names = {}
    for field in COLUMN_FIELDS:
        name = options.get(field)
        if not isinstance(name, str) or not name:
            raise FieldError(field, f"Choose a column for {field}.")
        names[field] = name
    occasion = options.get(OCCASION)
    if occasion in (None, ""):
        occasion = None
    elif not isinstance(occasion, str):
        raise FieldError(OCCASION, f"Choose a column for {OCCASION}.")
    if names[SECOND] == names[FIRST]:
        raise FieldError(SECOND, "Choose two different columns for First and Second.")
    for field in (FIRST, SECOND):
        if names[field] == names[SUBJECT]:
            raise FieldError(field, "Subject, First and Second must be different columns.")
    if occasion is not None and occasion in names.values():
        raise FieldError(OCCASION, "Occasion must be a column other than Subject, First and Second.")
    mode = _choice(options, MODE, MODES)
    coverage = _percent(options, COVERAGE)
    intervals = _choice(options, INTERVALS, INTERVAL_CHOICES)
    graph = _choice(options, GRAPH, GRAPHS)
    level = replicates = seed = None
    if intervals == SUBJECT_BOOTSTRAP:
        level = _percent(options, LEVEL)
        replicates = _whole(options, REPLICATES, MIN_REPLICATES, MAX_REPLICATES)
        seed = _whole(options, SEED, 0, MAX_SEED)
    return Settings(names[SUBJECT], occasion, names[FIRST], names[SECOND], mode, coverage, intervals, level,
                    replicates, seed, graph)


def normalized_options(options):
    """The recipe with typed numbers, as the dialog saves it; hidden bootstrap fields are left out."""
    settings = read_settings(options)
    typed = {key: value for key, value in options.items()
             if key not in BOOTSTRAP_FIELDS or settings.intervals == SUBJECT_BOOTSTRAP}
    typed[COVERAGE] = settings.coverage
    if settings.intervals == SUBJECT_BOOTSTRAP:
        typed.update({LEVEL: settings.level, REPLICATES: settings.replicates, SEED: settings.seed})
    return typed


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


def _key(value):
    """Literal identity: text never equals a number, 1 equals 1.0, "S1" differs from "S1 "."""
    if isinstance(value, str):
        return "s", value
    if isinstance(value, (bool, np.bool_)):
        return "b", bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return "n", float(value) if isinstance(value, (float, np.floating)) else int(value)
    try:
        hash(value)
    except TypeError:
        return "r", type(value).__name__, repr(value)
    return "o", type(value).__name__, value


def label(value):
    """A subject or occasion as text: the literal string, or a number without a spurious ``.0``."""
    if isinstance(value, str):
        return value
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and float(value).is_integer() \
            and abs(value) < 1e15:
        return str(int(value))
    return str(value)


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
                values[position] = float(value.strip().replace(",", ".")) if isinstance(value, str) else float(value)
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
    return values


@dataclass
class Plan:
    settings: Settings
    rows: np.ndarray            # 0-based sheet positions of the used pairs, in sheet order
    first: np.ndarray
    second: np.ndarray
    working: np.ndarray         # d on the calculation scale (difference or log ratio)
    average: np.ndarray         # abscissa: half sum, or geometric mean in Log ratio mode
    code: np.ndarray            # subject number (0..g−1) of each used pair
    subjects: list              # literal subject of each code, in order of first use
    occasions: list             # literal occasion (or None) of each used pair
    excluded: list              # (row 0-based, subject literal or None, occasion literal or None, reason)
    sizes: np.ndarray           # m_s
    means: np.ndarray           # d̄_s
    squares: np.ndarray         # SS_s
    reference: float            # shift used for accurate sums

    @property
    def n(self):
        return int(len(self.rows))

    @property
    def g(self):
        return int(len(self.subjects))


def _summaries(values, code, count):
    """Accurate per-subject mean and sum of squared deviations (shifted by the subject's first value)."""
    first = np.full(count, np.nan)
    order = np.arange(len(code))[::-1]
    first[code[order]] = values[order]
    shifted = values - first[code]
    sizes = np.bincount(code, minlength=count)
    mean = np.bincount(code, shifted, minlength=count) / sizes
    centred = shifted - mean[code]
    correction = np.bincount(code, centred, minlength=count) / sizes
    centred -= correction[code]
    squares = np.bincount(code, centred * centred, minlength=count)
    return sizes, first + mean + correction, squares


def prepare(frame, options):
    """Read recipe and worksheet, exclude incomplete pairs, form the subject summaries. Nothing is resampled."""
    settings = read_settings(options)
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("Bland–Altman for repeated pairs needs a worksheet.")
    subject_column = _column(frame, settings.subject, SUBJECT)
    occasion_column = _column(frame, settings.occasion, OCCASION) if settings.occasion else None
    first = _numbers(_column(frame, settings.first, FIRST), settings.first, FIRST)
    second = _numbers(_column(frame, settings.second, SECOND), settings.second, SECOND)
    subjects_raw = subject_column.to_numpy(dtype=object)
    occasions_raw = occasion_column.to_numpy(dtype=object) if occasion_column is not None else None

    rows, excluded, codes, subjects, occasions, known = [], [], [], [], [], {}
    seen = {}
    for position in range(len(frame)):
        subject = subjects_raw[position]
        occasion = occasions_raw[position] if occasions_raw is not None else None
        no_subject = _missing(subject)
        occasion = None if occasion is None or _missing(occasion) else occasion
        no_first, no_second = np.isnan(first[position]), np.isnan(second[position])
        if no_subject and no_first and no_second:
            continue  # an empty row of the worksheet
        reasons = [text for missing, text in ((no_subject, "Subject is blank or excluded"),
                                              (no_first, "First is blank or excluded"),
                                              (no_second, "Second is blank or excluded")) if missing]
        if reasons:
            excluded.append((position, None if no_subject else subject, occasion, "; ".join(reasons)))
            continue
        if settings.mode == LOG_RATIO:
            for field, values, name in ((FIRST, first, settings.first), (SECOND, second, settings.second)):
                if values[position] <= 0:
                    raise FieldError(field, f'Log ratio needs positive values: column "{name}" has '
                                            f"{values[position]:g} in row {position + 1}.")
        key = _key(subject)
        code = known.setdefault(key, len(known))
        if code == len(subjects):
            subjects.append(subject)
        if occasion is not None:
            pair = (key, _key(occasion))
            if pair in seen:
                raise FieldError(OCCASION, f'Subject "{label(subject)}" has occasion "{label(occasion)}" in rows '
                                           f"{seen[pair] + 1} and {position + 1}. Each subject and occasion "
                                           "may hold one pair.")
            seen[pair] = position
        rows.append(position)
        codes.append(code)
        occasions.append(occasion)
    n, g = len(rows), len(subjects)
    if n > MAX_PAIRS:
        raise FieldError(SUBJECT, f"Use at most {MAX_PAIRS:,} pairs (this selection has {n:,}).")
    if g < MIN_SUBJECTS:
        raise FieldError(SUBJECT, f"At least {MIN_SUBJECTS} subjects with complete pairs are needed; {g} found.")
    if n - g < 1:
        raise FieldError(SUBJECT, "No subject has two complete pairs: the within-subject variance needs at least "
                                  "one repeated pair.")
    if settings.intervals == SUBJECT_BOOTSTRAP and settings.replicates * g > MAX_WORK:
        raise FieldError(REPLICATES, f"Bootstrap replicates × subjects = {settings.replicates:,} × {g:,} exceeds "
                                     f"the limit of {MAX_WORK:,}.")
    rows = np.asarray(rows, dtype=np.int64)
    code = np.asarray(codes, dtype=np.int64)
    a, b = first[rows], second[rows]
    if settings.mode == LOG_RATIO:
        log_a, log_b = np.log(a), np.log(b)
        working = log_a - log_b
        average = np.exp(log_a / 2 + log_b / 2)
    else:
        working = a - b
        average = a / 2 + b / 2
    sizes, means, squares = _summaries(working, code, g)
    reference = float(np.median(means))
    return Plan(settings, rows, a, b, working, average, code, subjects, occasions, excluded, sizes, means,
                squares, reference)


def check_options(frame, options):
    """Everything the dialog can check before the worker starts; raises FieldError."""
    prepare(frame, options)


# ----- estimator -----------------------------------------------------------------------------------------------------

def components(sizes, means, squares, reference=0.0):
    """Variance components of the subject summaries; arrays may carry leading replicate axes.

    Returns a dict of arrays: n, df_within, bias, ms_within, ms_between, m0, between_raw, between, total. The
    sums run over the last axis. A replicate without a within-subject degree of freedom gives NaN.
    """
    sizes = np.asarray(sizes, dtype=float)
    g = sizes.shape[-1]
    n = sizes.sum(axis=-1)
    df_within = n - g
    shifted = np.asarray(means, dtype=float) - reference
    with np.errstate(invalid="ignore", divide="ignore"):
        bias_shift = (sizes * shifted).sum(axis=-1) / n
        ms_within = np.asarray(squares, dtype=float).sum(axis=-1) / df_within
        deviation = shifted - bias_shift[..., None]
        ms_between = (sizes * deviation * deviation).sum(axis=-1) / (g - 1)
        m0 = (n * n - (sizes * sizes).sum(axis=-1)) / ((g - 1) * n)
        between_raw = (ms_between - ms_within) / m0
    ms_within = np.where(df_within >= 1, ms_within, np.nan)
    between_raw = np.where(df_within >= 1, between_raw, np.nan)
    between = np.where(np.isnan(between_raw), np.nan, np.maximum(between_raw, 0.0))
    return {"n": n, "df_within": df_within, "bias": bias_shift + reference, "ms_within": ms_within,
            "ms_between": ms_between, "m0": m0, "between_raw": between_raw, "between": between,
            "total": ms_within + between}


def critical(coverage):
    return float(stats.norm.ppf((1 + coverage / 100) / 2))


# ----- bootstrap -----------------------------------------------------------------------------------------------------

def _replicate_block(sizes, means, squares, reference, state, count, z, cancel):
    """Bias and limits of ``count`` replicates drawn from the generator ``state``, in order."""
    bitgen = np.random.PCG64()
    bitgen.state = state
    rng = np.random.Generator(bitgen)
    g = len(sizes)
    out = np.empty((count, 3))
    for start in range(0, count, CANCEL_BLOCK):
        check_cancel(cancel)
        stop = min(start + CANCEL_BLOCK, count)
        draws = np.stack([rng.integers(0, g, size=g) for _ in range(stop - start)])
        found = components(sizes[draws], means[draws], squares[draws], reference)
        spread = z * np.sqrt(found["total"])
        out[start:stop, 0] = found["bias"]
        out[start:stop, 1] = found["bias"] - spread
        out[start:stop, 2] = found["bias"] + spread
        out[start:stop][found["df_within"] < 1] = np.nan  # not identified: the whole replicate is left out
    check_cancel(cancel)
    return out


def _bootstrap_task(item, cancel):
    return _replicate_block(*item, cancel)


def bootstrap(plan, cancel=None, *, processes=None):
    """Replicate bias, lower and upper limit on the calculation scale (rows of NaN for invalid replicates)."""
    settings = plan.settings
    z = critical(settings.coverage)
    rng = np.random.Generator(np.random.PCG64(settings.seed))
    g, total = plan.g, settings.replicates
    arrays = (plan.sizes, plan.means, plan.squares, plan.reference)
    count = parallel.warm_process_count() if processes is None else processes
    if count <= 1 or total * g < PARALLEL_WORK:
        return _replicate_block(*arrays, rng.bit_generator.state, total, z, cancel)
    # Contiguous blocks, each starting from the exact generator state of its first replicate.
    jobs = []
    chunk = -(-total // (2 * count))
    for start in range(0, total, chunk):
        check_cancel(cancel)
        size = min(chunk, total - start)
        jobs.append((*arrays, rng.bit_generator.state, size, z))
        for _ in range(size):
            rng.integers(0, g, size=g)
    parts = parallel.run_tasks(_bootstrap_task, jobs, with_cancel=True, cancel=cancel)
    check_cancel(cancel)
    return np.concatenate(parts)


# ----- result --------------------------------------------------------------------------------------------------------

def _ratio(value):
    """exp of a log-scale value, NaN when the ratio overflows or underflows (never a clipped finite number)."""
    with np.errstate(over="ignore", under="ignore"):
        shown = np.exp(value)
    return float(shown) if np.isfinite(shown) and shown > 0 else np.nan


def _shown(value, mode):
    return _ratio(value) if mode == LOG_RATIO else float(value)


def _subject_table(plan):
    logs = plan.settings.mode == LOG_RATIO
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = np.where(plan.sizes > 1, np.sqrt(plan.squares / np.maximum(plan.sizes - 1, 1)), np.nan)
    magnitude = np.bincount(plan.code, plan.average, minlength=plan.g) / plan.sizes
    first_row = np.full(plan.g, -1)
    first_row[plan.code[::-1]] = plan.rows[::-1]
    table = {"Subject": [label(value) for value in plan.subjects], "Pairs": plan.sizes.astype(int),
             "First source row": first_row + 1}
    if logs:
        table.update({"Mean log ratio": plan.means, "Ratio (exp of mean)": [_ratio(v) for v in plan.means],
                      "Within-subject SD (log)": sd, "Mean of geometric means": magnitude})
    else:
        table.update({"Mean difference": plan.means, "Within-subject SD": sd, "Mean of pair averages": magnitude})
    return pd.DataFrame(table)


def _pair_table(plan):
    logs = plan.settings.mode == LOG_RATIO
    table = {"Source row": plan.rows + 1, "Subject": [label(plan.subjects[c]) for c in plan.code]}
    if plan.settings.occasion:
        table["Occasion"] = pd.Series([value if value is None else label(value) for value in plan.occasions],
                                      dtype=object)
    table.update({"First": plan.first, "Second": plan.second})
    if logs:
        table.update({"Geometric mean": plan.average, "Log ratio": plan.working,
                      "Ratio": [_ratio(v) for v in plan.working]})
    else:
        table.update({"Pair mean": plan.average, "Difference": plan.working})
    return pd.DataFrame(table)


def _excluded_table(plan):
    return pd.DataFrame({
        "Source row": [row + 1 for row, *_ in plan.excluded],
        "Subject": pd.Series([None if s is None else label(s) for _, s, _, _ in plan.excluded], dtype=object),
        "Occasion": pd.Series([None if o is None else label(o) for _, _, o, _ in plan.excluded], dtype=object),
        "Reason": [reason for *_, reason in plan.excluded]})


def calculate(plan, cancel=None):
    """Estimates, optional bootstrap intervals and the display geometry."""
    settings = plan.settings
    found = components(plan.sizes, plan.means, plan.squares, plan.reference)
    found = {key: float(value) for key, value in found.items()}
    z = critical(settings.coverage)
    spread = z * np.sqrt(found["total"])
    estimate = {"bias": found["bias"], "lower": found["bias"] - spread, "upper": found["bias"] + spread}
    interval = {key: (np.nan, np.nan) for key in estimate}
    boot = {"status": NOT_REQUESTED, "valid": None, "invalid": [], "message": ""}
    if settings.intervals == SUBJECT_BOOTSTRAP:
        replicates = bootstrap(plan, cancel)
        valid = np.isfinite(replicates).all(axis=1)
        boot["valid"] = int(valid.sum())
        boot["invalid"] = (np.flatnonzero(~valid) + 1).tolist()
        if boot["valid"] >= VALID_SHARE * settings.replicates:
            alpha = 1 - settings.level / 100
            limits = np.quantile(replicates[valid], [alpha / 2, 1 - alpha / 2], axis=0, method="linear")
            interval = {key: (float(limits[0, column]), float(limits[1, column]))
                        for column, key in enumerate(("bias", "lower", "upper"))}
            boot["status"] = INTERVAL_OK
        else:
            boot["status"] = TOO_FEW_VALID
            boot["message"] = (f"Only {boot['valid']:,} of {settings.replicates:,} replicates identify both variance "
                               f"components (at least {VALID_SHARE:.0%} are needed), so the intervals are left "
                               "empty. The estimates do not depend on the bootstrap.")
    check_cancel(cancel)
    return found, estimate, interval, boot


def _agreement_table(plan, found, estimate, interval, boot):
    settings, mode = plan.settings, plan.settings.mode
    shown = {key: _shown(value, mode) for key, value in estimate.items()}
    row = {"Mode": mode, "Pairs": plan.n, "Subjects": plan.g, "Bias": shown["bias"],
           "Within-subject variance": found["ms_within"], "Between-subject variance": found["between"],
           "Between-subject variance (unconstrained)": found["between_raw"],
           "Between-subject estimate": BOUNDARY if found["between_raw"] < 0 else ESTIMATED,
           "Total SD": float(np.sqrt(found["total"])), "Coverage (%)": settings.coverage,
           "z": critical(settings.coverage),
           "Lower agreement limit": shown["lower"], "Upper agreement limit": shown["upper"]}
    if mode == LOG_RATIO:
        row.update({"Bias (log)": estimate["bias"], "Lower limit (log)": estimate["lower"],
                    "Upper limit (log)": estimate["upper"]})
    row.update({"MS within": found["ms_within"], "MS between": found["ms_between"],
                "df within": int(found["df_within"]), "df between": plan.g - 1, "m0": found["m0"],
                "Confidence intervals": settings.intervals})
    for key, caption in (("bias", "Bias"), ("lower", "Lower limit"), ("upper", "Upper limit")):
        low, high = interval[key]
        row[f"{caption} CI low"] = _shown(low, mode) if np.isfinite(low) else np.nan
        row[f"{caption} CI high"] = _shown(high, mode) if np.isfinite(high) else np.nan
    if settings.intervals == SUBJECT_BOOTSTRAP:
        invalid = boot["invalid"]
        listed = ", ".join(str(number) for number in invalid[:20]) + (" …" if len(invalid) > 20 else "")
        row.update({"Confidence level (%)": settings.level, "Bootstrap replicates": settings.replicates,
                    "Bootstrap valid": boot["valid"], "Invalid replicates": listed, "Seed": settings.seed,
                    "Random sequence": SEQUENCE, "Quantile rule": QUANTILE_RULE})
    row["Interval status"] = boot["status"]
    row["Excluded rows"] = len(plan.excluded)
    row["Note"] = _note(plan, found, shown, boot)
    table = pd.DataFrame([row])
    for name in ("Invalid replicates", "Seed", "Bootstrap replicates", "Bootstrap valid"):
        if name in table:
            table[name] = pd.Series([row[name]], dtype=object)
    return table


def _note(plan, found, shown, boot):
    settings = plan.settings
    parts = [f"Limits of agreement for one new pair on one new subject, {settings.coverage:g}% coverage: "
             "bias ± z · sqrt(within-subject variance + between-subject variance), random-intercept model of the "
             "differences (Bland and Altman 2007, quantity that may vary)."]
    if found["between_raw"] < 0:
        parts.append("The between-subject variance estimate is negative and is set to 0 (boundary).")
    if settings.mode == LOG_RATIO:
        parts.append("Variances are on the log scale; bias and limits are ratios First / Second.")
        missing = [name for name, key in (("Bias", "bias"), ("Lower limit", "lower"), ("Upper limit", "upper"))
                   if not np.isfinite(shown[key])]
        if missing:
            parts.append(f"{', '.join(missing)} cannot be represented as a finite positive ratio and are left empty.")
    if boot["message"]:
        parts.append(boot["message"])
    elif boot["status"] == INTERVAL_OK:
        parts.append(f"{settings.level:g}% percentile intervals from {boot['valid']:,} valid subject-bootstrap "
                     "replicates; they describe the uncertainty of the estimates, not the agreement limits themselves.")
    parts.append("Wide or narrow limits alone do not show that two methods are interchangeable: compare them with a "
                 "clinically acceptable difference chosen beforehand.")
    return " ".join(parts)


# ----- figures -------------------------------------------------------------------------------------------------------

def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def _pairs_figure(plan, estimate, interval):
    settings = plan.settings
    logs = settings.mode == LOG_RATIO
    title = f"{METHOD} · {plan.n} pairs, {plan.g} subjects"
    figure, axes = _plot(title, "Geometric mean of First and Second" if logs else "Mean of First and Second",
                         "First / Second" if logs else "First − Second")
    axes._tramastat_numeric_axes = ("x", "y")
    values = np.exp(plan.working) if logs else plan.working
    points = axes.scatter(plan.average, values, s=28, color=POINT_COLOR, alpha=.85, zorder=3,
                          label=f"Pairs (n = {plan.n}, {plan.g} subjects)")
    points.set_gid(f"{GID}points")
    if logs:
        axes.set_yscale("log")
        # Plain ratios (0.9, 1, 1.2) instead of powers of ten; a module class, so the figure still pickles.
        axes.yaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
        axes.yaxis.set_minor_formatter(StrMethodFormatter("{x:g}"))
    neutral = axes.axhline(1.0 if logs else 0.0, color=NEUTRAL_COLOR, linewidth=.9, linestyle=":", zorder=1,
                           label="Equal values (1)" if logs else "Zero difference")
    neutral.set_gid(f"{GID}neutral")
    # Legend columns: pairs and reference, then bias, lower and upper limit, each above its interval.
    handles = [points, neutral]
    for key, caption, band_caption, style, color in (
            ("bias", "Bias", "Bias CI", "-", LINE_COLOR),
            ("lower", "Lower agreement limit", "Lower limit CI", "--", "#3b7ea1"),
            ("upper", "Upper agreement limit", "Upper limit CI", "--", "#c08a2e")):
        value = _shown(estimate[key], settings.mode)
        if np.isfinite(value):
            line = axes.axhline(value, color=LINE_COLOR, linestyle=style, linewidth=1.6 if key == "bias" else 1.3,
                                zorder=2, label=f"{caption} = {value:.4g}")
            line.set_gid(f"{GID}{key}")
            handles.append(line)
        low, high = (_shown(v, settings.mode) for v in interval[key])
        if np.isfinite(low) and np.isfinite(high):
            band = axes.axhspan(low, high, color=color, alpha=.15, linewidth=0, zorder=0,
                                label=band_caption)
            band.set_gid(f"{GID}{key}-band")
            handles.append(band)
    legend = figure.legend(handles=handles, loc="outside lower center", ncols=4, fontsize=8.5, frameon=False)
    _plain(axes.title, axes.xaxis.label, axes.yaxis.label, *legend.get_texts())
    return figure


def _subjects_figure(plan, found):
    logs = plan.settings.mode == LOG_RATIO
    figure, axes = _plot(f"Within-subject spread · {plan.g} subjects",
                         "Subject mean of geometric means" if logs else "Subject mean of pair averages",
                         "Within-subject SD of log ratio" if logs else "Within-subject SD of differences")
    axes._tramastat_numeric_axes = ("x", "y")
    table = _subject_table(plan)
    sd = table["Within-subject SD (log)" if logs else "Within-subject SD"].to_numpy(dtype=float)
    magnitude = table["Mean of geometric means" if logs else "Mean of pair averages"].to_numpy(dtype=float)
    shown = plan.sizes > 1
    sizes = 18 + 14 * np.minimum(plan.sizes[shown], 12)
    points = axes.scatter(magnitude[shown], sd[shown], s=sizes, color=POINT_COLOR, alpha=.8, zorder=3,
                          label=f"Subjects with repeated pairs ({int(shown.sum())}); marker area grows with pairs")
    points.set_gid(f"{GID}subject-points")
    if int(shown.sum()) <= 40:
        for x, y, m in zip(magnitude[shown], sd[shown], plan.sizes[shown], strict=True):
            text = axes.annotate(f"{int(m)}", (x, y), xytext=(4, 4), textcoords="offset points", fontsize=8,
                                 color="#33414a")
            text.set_gid(f"{GID}subject-count")
    pooled = axes.axhline(np.sqrt(found["ms_within"]), color=LINE_COLOR, linestyle="--", linewidth=1.3,
                          label=f"Pooled within-subject SD = {np.sqrt(found['ms_within']):.4g}")
    pooled.set_gid(f"{GID}pooled-sd")
    single = int((~shown).sum())
    if single:
        axes.plot([], [], " ", label=f"{single} subject(s) with one pair: no within-subject SD")
    top = np.nanmax(sd[shown]) if shown.any() else 0.0
    axes.set_ylim(0, max(top, np.sqrt(found["ms_within"])) * 1.15 or 1.0)
    legend = figure.legend(loc="outside lower center", ncols=1, fontsize=8.5, frameon=False)
    _plain(axes.title, axes.xaxis.label, axes.yaxis.label, *legend.get_texts())
    return figure


# ----- analysis ------------------------------------------------------------------------------------------------------

def analyse(frame, options, *, cancel=None):
    """Return the Result of Bland–Altman for repeated pairs; ``cancel`` is an optional threading.Event."""
    check_cancel(cancel)
    plan = prepare(frame, options)
    found, estimate, interval, boot = calculate(plan, cancel)
    tables = {AGREEMENT: _agreement_table(plan, found, estimate, interval, boot),
              SUBJECTS: _subject_table(plan), PAIRS: _pair_table(plan)}
    if plan.excluded:
        tables[EXCLUDED] = _excluded_table(plan)
    figure = (_subjects_figure(plan, found) if plan.settings.graph == SUBJECT_VIEW
              else _pairs_figure(plan, estimate, interval))
    return Result(tables, figure)
