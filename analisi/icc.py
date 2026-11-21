"""Intraclass correlation (ICC) of continuous measurements made by several raters or instruments.

Each worksheet row is one subject and each chosen column is one rater. The model is the balanced two-way layout
with one observation per cell (McGraw and Wong 1996, "Forming inferences about some intraclass correlation
coefficients", Psychological Methods 1:30–46). With n subjects and k raters the mean squares of the two-way ANOVA
are MSo (subjects), MSr (raters) and MSe (residual), and with D = MSo − MSe

    Absolute agreement, single measure   D / [MSo + (k−1) MSe + k (MSr − MSe) / n]      ICC(A,1)
    Absolute agreement, mean of raters   D / [MSo + (MSr − MSe) / n]                    ICC(A,k)
    Consistency,        single measure   D / [MSo + (k−1) MSe]                           ICC(C,1)
    Consistency,        mean of raters   D / MSo                                         ICC(C,k)

Negative coefficients are valid and are reported. A zero or non-finite denominator (for instance constant data)
leaves the estimate empty and says why in ``Status``.

Rows and identity
    The physical position of the row is the identity of the subject; the optional Subject column is only a label shown
    in the results and never changes the calculation. A row with a missing (or excluded) cell is left out as a whole.
    Text that is not a number and infinite values are rejected on the rater columns; negative values are valid.

Numerics
    The ICC does not change when every measurement is shifted by a constant or multiplied by a common factor. The
    calculation therefore works on the data shifted by their median and scaled by an exact power of two, so that
    very large or very small measurements neither overflow nor underflow; sums of squares are reported in the units
    of the data.

Subject bootstrap (optional percentile interval, off by default)
    ``Generator(PCG64(seed))``; for each replicate, in order, ``integers(0, n, size=n)`` draws rows with replacement
    and each drawn row carries its whole vector of ratings. The panel of raters is fixed, so the interval is
    conditional on the observed raters. Replicates whose coefficient is undefined are invalid and left out of the
    percentiles; with fewer than 80 % valid replicates the interval stays empty. Quantiles use the linear rule
    (``numpy.quantile(method="linear")``). The replicates are split into contiguous blocks, each starting from the exact
    generator state of its first replicate, so 1 and N processes give the same replicates. The work
    (replicates × rows × raters) is checked before any sample is drawn and the job can be cancelled between blocks.

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

from . import parallel
from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled
from .processing import _check_integer_precision
from .reporting import Result, _plot

METHOD = "Intraclass correlation"
RATERS, SUBJECT, DEFINITION, UNIT = "Raters", "Subject", "Definition", "Unit"
BOOTSTRAP, LEVEL, REPLICATES, SEED, GRAPH = (
    "Bootstrap CI", "Confidence level (%)", "Bootstrap replicates", "Seed", "Profile graph")
ABSOLUTE, CONSISTENCY = DEFINITIONS = ("Absolute agreement", "Consistency")
SINGLE, MEAN = UNITS = ("Single measure", "Mean of raters")

# The dialog builds its controls from these defaults: None is a column, "Optional" an optional column, tuples are
# choices (the first is the default), bools are check boxes, floats and ints are entries. ``Raters`` (a list of
# columns) is added by the workbench, which owns the "Multiple" kind.
OPTIONS = {SUBJECT: "Optional", DEFINITION: DEFINITIONS, UNIT: UNITS, BOOTSTRAP: False, LEVEL: 95.0,
           REPLICATES: 2000, SEED: 0, GRAPH: True}
DEFAULTS = {SUBJECT: None, DEFINITION: ABSOLUTE, UNIT: SINGLE, BOOTSTRAP: False, LEVEL: 95.0, REPLICATES: 2000,
            SEED: 0, GRAPH: True}
BOOTSTRAP_FIELDS = (LEVEL, REPLICATES, SEED)

MIN_ROWS = 3
MAX_ROWS = 100_000
MAX_RATERS = 64
MIN_REPLICATES, MAX_REPLICATES, MAX_SEED = 199, 5000, 2**64 - 1
MAX_WORK = 20_000_000           # resampled cells: replicates × rows × raters
MAGNITUDE = 1e100               # |value| at most
VALID_SHARE = 0.8
PARALLEL_WORK = 2_000_000       # resampled cells below which the pool is not worth starting
BLOCK_CELLS = 2_000_000         # cells held in memory by one batch of replicates
CANCEL_BLOCK = 256              # replicates at most per batch
MAX_LINES = 60                  # subject profiles drawn in the figure
QUANTILE_RULE = "Linear interpolation (numpy.quantile, method=\"linear\")"
SEQUENCE = "PCG64: Generator(PCG64(seed)); per replicate integers(0, n, size=n) over the complete rows in sheet order"

ICC, COMPONENTS, SUBJECTS, SETTINGS, EXCLUDED = (
    "ICC", "ANOVA components", "Subjects", "Settings", "Excluded rows")
ESTIMATED, NOT_ESTIMATED = "Estimated", "Not estimated"
NOT_REQUESTED, INTERVAL_OK, TOO_FEW_VALID = "Not requested", "Percentile interval", "Too few valid replicates"
GID = "icc:"
POINT_COLOR, LINE_COLOR = "#2f6f8f", "#aa5440"

LABEL_KEYS = {}  # the captions live in analisi.interface_catalog (one dedicated section)
ERROR_PREFIX = "icc.error."
_DIGITS = re.compile(r"\s*\+?[0-9]+\s*")

FORMS = {(ABSOLUTE, SINGLE): "ICC(A,1)", (ABSOLUTE, MEAN): "ICC(A,k)",
         (CONSISTENCY, SINGLE): "ICC(C,1)", (CONSISTENCY, MEAN): "ICC(C,k)"}


class IccCancelled(MonteCarloCancelled, InterruptedError):
    """The bootstrap was cancelled; the application keeps the last confirmed result."""


def cancellable(method, options):
    return method == METHOD and isinstance(options, dict) and options.get(BOOTSTRAP, DEFAULTS[BOOTSTRAP]) is True


def visibility(bootstrap):
    """Level, replicates and seed only apply when the subject bootstrap is requested."""
    return dict.fromkeys(BOOTSTRAP_FIELDS, bool(bootstrap))


def _cancelled(cancel):
    if cancel is None:
        return False
    return bool(cancel.is_set()) if hasattr(cancel, "is_set") else bool(cancel())


def check_cancel(cancel):
    if _cancelled(cancel):
        raise IccCancelled("Intraclass correlation cancelled.")


# ----- recipe --------------------------------------------------------------------------------------------------------

def _get(options, name):
    return options.get(name, DEFAULTS[name])


def _choice(options, name, choices):
    value = _get(options, name)
    if not isinstance(value, str) or value not in choices:
        raise FieldError(name, f"Choose a valid value for {name}.")
    return value


def _flag(options, name):
    value = _get(options, name)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"Choose a valid value for {name}.")
    return bool(value)


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
    raters: tuple
    subject: str | None
    definition: str
    unit: str
    bootstrap: bool
    level: float | None
    replicates: int | None
    seed: int | None
    graph: bool


def read_settings(options):
    """The recipe alone, checked before any worksheet value is read."""
    if not isinstance(options, dict):
        raise ValueError("Intraclass correlation options must be a mapping.")
    raters = options.get(RATERS)
    if not isinstance(raters, (list, tuple)) or not all(isinstance(name, str) and name for name in raters):
        raise FieldError(RATERS, f"Choose columns for {RATERS}.")
    if len(raters) < 2:
        raise FieldError(RATERS, f"Choose at least two columns for {RATERS}.")
    if len(set(raters)) != len(raters):
        raise FieldError(RATERS, f"Choose each column of {RATERS} only once.")
    if len(raters) > MAX_RATERS:
        raise FieldError(RATERS, f"Use at most {MAX_RATERS} raters (this selection has {len(raters)}).")
    subject = options.get(SUBJECT)
    if subject in (None, ""):
        subject = None
    elif not isinstance(subject, str):
        raise FieldError(SUBJECT, f"Choose a column for {SUBJECT}.")
    elif subject in raters:
        raise FieldError(SUBJECT, f"{SUBJECT} must be a column other than the {RATERS}.")
    definition = _choice(options, DEFINITION, DEFINITIONS)
    unit = _choice(options, UNIT, UNITS)
    bootstrap = _flag(options, BOOTSTRAP)
    graph = _flag(options, GRAPH)
    level = replicates = seed = None
    if bootstrap:
        level = _percent(options, LEVEL)
        replicates = _whole(options, REPLICATES, MIN_REPLICATES, MAX_REPLICATES)
        seed = _whole(options, SEED, 0, MAX_SEED)
    return Settings(tuple(raters), subject, definition, unit, bootstrap, level, replicates, seed, graph)


def normalized_options(options):
    """The recipe with typed numbers, as the dialog saves it; hidden bootstrap fields are left out."""
    settings = read_settings(options)
    typed = {key: value for key, value in options.items() if key not in BOOTSTRAP_FIELDS or settings.bootstrap}
    typed[RATERS] = list(settings.raters)
    if settings.bootstrap:
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


def label(value):
    """A subject label as text: the literal string, or a number without a spurious ``.0``."""
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
    rows: np.ndarray            # 0-based sheet positions of the complete rows, in sheet order
    labels: list | None         # literal subject label of each complete row (None without a Subject column)
    values: np.ndarray          # (n, k) measurements in the units of the data
    scaled: np.ndarray          # (n, k) the same, shifted by the median and multiplied by 2**-exponent
    exponent: int               # the data are scaled by 2**-exponent; 0 for constant data
    excluded: list              # (row 0-based, subject label or None, names of the raters without a value)

    @property
    def n(self):
        return int(len(self.rows))

    @property
    def k(self):
        return int(self.values.shape[1])


def _scale(values):
    """Shift by the median and scale by an exact power of two; the ICC is unchanged by both."""
    shifted = values - np.median(values)
    top = float(np.max(np.abs(shifted)))
    if top == 0.0:
        return shifted, 0
    exponent = int(np.frexp(top)[1])
    return np.ldexp(shifted, -exponent), exponent


def prepare(frame, options):
    """Read recipe and worksheet, leave out incomplete rows, scale the matrix. Nothing is resampled."""
    settings = read_settings(options)
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("Intraclass correlation needs a worksheet.")
    subject_column = _column(frame, settings.subject, SUBJECT) if settings.subject else None
    columns = [_numbers(_column(frame, name, RATERS), name, RATERS) for name in settings.raters]
    matrix = np.column_stack(columns) if len(frame) else np.empty((0, len(columns)))
    subjects_raw = subject_column.to_numpy(dtype=object) if subject_column is not None else None
    absent = np.isnan(matrix)
    complete = ~absent.any(axis=1)
    rows, labels, excluded = [], [], []
    for position in range(len(frame)):
        subject = subjects_raw[position] if subjects_raw is not None else None
        subject = None if subject is None or _missing(subject) else subject
        if complete[position]:
            rows.append(position)
            labels.append(subject)
        elif absent[position].all() and subject is None:
            continue  # an empty row of the worksheet
        else:
            names = [name for name, no_value in zip(settings.raters, absent[position], strict=True) if no_value]
            excluded.append((position, subject, names))
    n = len(rows)
    if n > MAX_ROWS:
        raise FieldError(RATERS, f"Use at most {MAX_ROWS:,} rows (this selection has {n:,}).")
    if n < MIN_ROWS:
        raise FieldError(RATERS, f"At least {MIN_ROWS} complete rows are needed; {n} found.")
    k = len(settings.raters)
    if settings.bootstrap and settings.replicates * n * k > MAX_WORK:
        raise FieldError(REPLICATES, f"Bootstrap would resample {settings.replicates * n * k:,} cells "
                                     f"(replicates × rows × raters); the limit is {MAX_WORK:,}.")
    rows = np.asarray(rows, dtype=np.int64)
    values = matrix[rows]
    scaled, exponent = _scale(values)
    return Plan(settings, rows, labels if subject_column is not None else None, values, scaled, exponent, excluded)


def check_options(frame, options):
    """Everything the dialog can check before the worker starts; raises FieldError."""
    prepare(frame, options)


def summary(frame, options):
    """Counts for the dialog, without raising for data problems: complete rows, left out rows, raters."""
    names = options.get(RATERS) if isinstance(options, dict) else None
    if not isinstance(names, (list, tuple)):
        return {"complete": 0, "excluded": 0, "raters": 0}
    present = [name for name in dict.fromkeys(names) if name in frame.columns
               and not isinstance(frame[name], pd.DataFrame)]
    if not present:
        return {"complete": 0, "excluded": 0, "raters": 0}
    blocks = []
    for name in present:
        series = frame[name]
        blocks.append(np.fromiter((not _missing(value) for value in series.to_numpy(dtype=object)),
                                  dtype=bool, count=len(series)))
    filled = np.column_stack(blocks)
    complete = int(filled.all(axis=1).sum())
    started = int((filled.any(axis=1)).sum())
    return {"complete": complete, "excluded": started - complete, "raters": len(present)}


# ----- estimator -----------------------------------------------------------------------------------------------------

def _mean(values, axis):
    """Mean with one correction pass (accurate sums for arrays of any leading shape)."""
    mean = values.mean(axis=axis)
    return mean + (values - np.expand_dims(mean, axis)).mean(axis=axis)


def sums_of_squares(matrix):
    """SS of subjects, raters and residual of ``(..., n, k)`` arrays, in the units of ``matrix``."""
    matrix = np.asarray(matrix, dtype=float)
    n, k = matrix.shape[-2:]
    rows = _mean(matrix, -1)                      # (..., n)
    columns = _mean(matrix, -2)                   # (..., k)
    grand = _mean(rows, -1)                       # (...)
    subjects = k * ((rows - grand[..., None]) ** 2).sum(axis=-1)
    raters = n * ((columns - grand[..., None]) ** 2).sum(axis=-1)
    residual = matrix - rows[..., :, None] - columns[..., None, :] + grand[..., None, None]
    return subjects, raters, (residual * residual).sum(axis=(-2, -1))


def mean_squares(subjects, raters, residual, n, k):
    return subjects / (n - 1), raters / (k - 1), residual / ((n - 1) * (k - 1))


def coefficient(ms_subjects, ms_raters, ms_residual, n, k, definition, unit):
    """The ICC, its denominator and whether that is zero; NaN estimate where the denominator is zero (up to rounding) or not finite.

    A denominator that is negative is not an error of the data: it can happen for the mean of raters under absolute
    agreement when the raters differ more than the subjects do, and the coefficient is then outside [−1, 1].
    """
    with np.errstate(all="ignore"):
        signal = ms_subjects - ms_residual
        if definition == ABSOLUTE:
            if unit == MEAN:
                denominator = ms_subjects + (ms_raters - ms_residual) / n
                size = np.abs(ms_subjects) + (np.abs(ms_raters) + np.abs(ms_residual)) / n
            else:
                denominator = ms_subjects + (k - 1) * ms_residual + k * (ms_raters - ms_residual) / n
                size = (np.abs(ms_subjects) + (k - 1) * np.abs(ms_residual)
                        + k * (np.abs(ms_raters) + np.abs(ms_residual)) / n)
        elif unit == MEAN:
            denominator, size = ms_subjects, np.abs(ms_subjects)
        else:
            denominator = ms_subjects + (k - 1) * ms_residual
            size = np.abs(ms_subjects) + (k - 1) * np.abs(ms_residual)
        estimate = signal / denominator
        zero = np.abs(denominator) <= 64 * np.finfo(float).eps * size
    usable = np.isfinite(denominator) & ~zero & np.isfinite(estimate)
    return np.where(usable, estimate, np.nan), denominator, zero


def estimate_of(matrix, definition, unit):
    """The ICC of ``(..., n, k)`` arrays (NaN where it is undefined)."""
    n, k = np.asarray(matrix).shape[-2:]
    parts = sums_of_squares(matrix)
    return coefficient(*mean_squares(*parts, n, k), n, k, definition, unit)[0]


# ----- bootstrap -----------------------------------------------------------------------------------------------------

def _replicate_block(scaled, definition, unit, state, count, cancel):
    """The ICC of ``count`` replicates drawn from the generator ``state``, in order."""
    bitgen = np.random.PCG64()
    bitgen.state = state
    rng = np.random.Generator(bitgen)
    n, k = scaled.shape
    batch = max(1, min(CANCEL_BLOCK, BLOCK_CELLS // (n * k)))
    out = np.empty(count)
    for start in range(0, count, batch):
        check_cancel(cancel)
        stop = min(start + batch, count)
        draws = np.stack([rng.integers(0, n, size=n) for _ in range(stop - start)])
        out[start:stop] = estimate_of(scaled[draws], definition, unit)
    check_cancel(cancel)
    return out


def _bootstrap_task(item, cancel):
    return _replicate_block(*item, cancel)


def bootstrap(plan, cancel=None, *, processes=None):
    """Replicate ICC values (NaN for invalid replicates), the same with 1 or N processes."""
    settings = plan.settings
    rng = np.random.Generator(np.random.PCG64(settings.seed))
    n, total = plan.n, settings.replicates
    arrays = (plan.scaled, settings.definition, settings.unit)
    count = parallel.warm_process_count() if processes is None else processes
    if count <= 1 or total * n * plan.k < PARALLEL_WORK:
        return _replicate_block(*arrays, rng.bit_generator.state, total, cancel)
    # Contiguous blocks, each starting from the exact generator state of its first replicate.
    jobs = []
    chunk = -(-total // (2 * count))
    for start in range(0, total, chunk):
        check_cancel(cancel)
        size = min(chunk, total - start)
        jobs.append((*arrays, rng.bit_generator.state, size))
        for _ in range(size):
            rng.integers(0, n, size=n)
    parts = parallel.run_tasks(_bootstrap_task, jobs, with_cancel=True, cancel=cancel)
    check_cancel(cancel)
    return np.concatenate(parts)


# ----- result --------------------------------------------------------------------------------------------------------

def calculate(plan, cancel=None):
    """Components, estimate (None when undefined), reason and the bootstrap summary."""
    settings = plan.settings
    n, k = plan.n, plan.k
    parts = sums_of_squares(plan.scaled)
    squares = mean_squares(*parts, n, k)
    estimate, denominator, zero = coefficient(*squares, n, k, settings.definition, settings.unit)
    estimate, denominator = float(estimate), float(denominator)
    reason = ""
    if not np.isfinite(estimate):
        if not np.isfinite(denominator):
            reason = "the denominator is not a finite number"
        elif bool(zero):
            reason = "the denominator is zero (the ratings carry no variation)"
        else:
            reason = "the result is not a finite number"
    boot = {"status": NOT_REQUESTED, "valid": None, "low": np.nan, "high": np.nan, "message": ""}
    if settings.bootstrap:
        replicates = bootstrap(plan, cancel)
        valid = np.isfinite(replicates)
        boot["valid"] = int(valid.sum())
        if boot["valid"] >= VALID_SHARE * settings.replicates:
            alpha = 1 - settings.level / 100
            low, high = np.quantile(replicates[valid], [alpha / 2, 1 - alpha / 2], method="linear")
            boot.update(status=INTERVAL_OK, low=float(low), high=float(high))
        else:
            boot["status"] = TOO_FEW_VALID
            boot["message"] = (f"Only {boot['valid']:,} of {settings.replicates:,} replicates have a defined "
                               f"coefficient (at least {VALID_SHARE:.0%} are needed), so the interval is left "
                               "empty. The estimate does not depend on the bootstrap.")
    check_cancel(cancel)
    return {"parts": parts, "squares": squares, "estimate": estimate, "denominator": denominator, "reason": reason,
            "boot": boot}


def _in_units(value, exponent):
    """A sum of squares or mean square of the scaled data back in the units of the data."""
    with np.errstate(over="ignore", under="ignore"):
        shown = float(np.ldexp(float(value), 2 * exponent))
    return shown


def _components_table(plan, found):
    n, k = plan.n, plan.k
    (ss_subjects, ss_raters, ss_residual), (ms_subjects, ms_raters, ms_residual) = found["parts"], found["squares"]
    rows = [("Subjects", ss_subjects, n - 1, ms_subjects), ("Raters", ss_raters, k - 1, ms_raters),
            ("Residual", ss_residual, (n - 1) * (k - 1), ms_residual)]
    return pd.DataFrame({
        "Source": [name for name, *_ in rows],
        "SS": [_in_units(ss, plan.exponent) for _, ss, _, _ in rows],
        "df": [df for _, _, df, _ in rows],
        "MS": [_in_units(ms, plan.exponent) for _, _, _, ms in rows]})


def _icc_table(plan, found):
    settings, boot = plan.settings, found["boot"]
    estimate = found["estimate"]
    status = ESTIMATED if np.isfinite(estimate) else f"{NOT_ESTIMATED}: {found['reason']}"
    row = {"Definition": settings.definition, "Unit": settings.unit, "Estimate": estimate if np.isfinite(estimate)
           else np.nan, "N": plan.n, "Raters": plan.k, "Status": status}
    if settings.bootstrap:
        row.update({"CI low": boot["low"], "CI high": boot["high"], "Confidence level (%)": settings.level,
                    "Interval status": boot["status"]})
    return pd.DataFrame([row])


def _subject_table(plan):
    values = plan.values
    first_row = plan.rows + 1
    table = {"Source row": first_row}
    if plan.labels is not None:
        table["Subject"] = pd.Series([None if value is None else label(value) for value in plan.labels], dtype=object)
    table.update({"Mean": values.mean(axis=1), "SD": values.std(axis=1, ddof=1), "Minimum": values.min(axis=1),
                  "Maximum": values.max(axis=1)})
    table["Range"] = table["Maximum"] - table["Minimum"]
    return pd.DataFrame(table)


def _excluded_table(plan):
    table = {"Source row": [row + 1 for row, *_ in plan.excluded]}
    if plan.labels is not None:
        table["Subject"] = pd.Series([None if subject is None else label(subject) for _, subject, _ in plan.excluded],
                                     dtype=object)
    table["Reason"] = ["No value for " + ", ".join(names) for *_, names in plan.excluded]
    return pd.DataFrame(table)


def _note(plan, found):
    settings = plan.settings
    form = FORMS[(settings.definition, settings.unit)]
    parts = [f"{form} of McGraw and Wong (1996): balanced two-way ANOVA with one observation per cell, "
             f"{plan.n} complete subjects and {plan.k} raters in the order of the Raters list."]
    if np.isfinite(found["estimate"]) and found["estimate"] < 0 and found["denominator"] > 0:
        parts.append("The coefficient is negative: the raters disagree more than the subjects differ.")
    if np.isfinite(found["estimate"]) and found["denominator"] < 0:
        parts.append("The denominator is negative (the raters differ more than the subjects do), so the coefficient "
                     "lies outside the usual range of −1 to 1 and should not be read as a correlation.")
    shown = [_in_units(value, plan.exponent) for value in (*found["parts"], *found["squares"])]
    if any(not np.isfinite(shown_value) or (shown_value == 0 and float(value) != 0)
           for shown_value, value in zip(shown, (*found["parts"], *found["squares"]), strict=True)):
        parts.append("Some sums of squares are outside the smallest representable or largest finite numbers in the "
                     "units of the data and are shown as 0 or empty; the coefficient does not depend on them.")
    if not np.isfinite(found["estimate"]):
        parts.append(f"The coefficient is not defined: {found['reason']}.")
    boot = found["boot"]
    if boot["message"]:
        parts.append(boot["message"])
    elif boot["status"] == INTERVAL_OK:
        parts.append(f"{settings.level:g}% percentile interval from {boot['valid']:,} valid subject-bootstrap "
                     "replicates. The bootstrap resamples subjects and keeps the observed panel of raters fixed, so "
                     "the inference is conditional on those raters.")
    parts.append("For categorical ratings use Cohen's kappa; to describe the size of the differences between two "
                 "methods in measurement units use Bland–Altman.")
    return " ".join(parts)


def _settings_table(plan, found):
    settings, boot = plan.settings, found["boot"]
    rows = [("Model", "Balanced two-way ANOVA, one observation per cell"),
            ("Coefficient", FORMS[(settings.definition, settings.unit)]),
            ("Definition", settings.definition), ("Unit", settings.unit),
            ("Complete subjects", str(plan.n)), ("Raters", str(plan.k)),
            ("Rater columns", "; ".join(settings.raters)),
            ("Subject column", settings.subject or "(none)"),
            ("Excluded rows", str(len(plan.excluded))),
            ("Bootstrap CI", "Yes" if settings.bootstrap else "No")]
    if settings.bootstrap:
        rows += [("Confidence level (%)", f"{settings.level:g}"), ("Bootstrap replicates", str(settings.replicates)),
                 ("Valid replicates", str(boot["valid"])), ("Seed", str(settings.seed)),
                 ("Random sequence", SEQUENCE), ("Quantile rule", QUANTILE_RULE),
                 ("Inference", "Conditional on the observed panel of raters")]
    rows.append(("Note", _note(plan, found)))
    return pd.DataFrame({"Setting": [name for name, _ in rows],
                         "Value": pd.Series([value for _, value in rows], dtype=object)})


# ----- figure --------------------------------------------------------------------------------------------------------

def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


def _profile_figure(plan):
    n, k = plan.n, plan.k
    figure, axes = _plot(f"{METHOD} · {n} subjects, {k} raters", "", "Measurement")
    axes._tramastat_numeric_axes = ("y",)
    shown = np.unique(np.linspace(0, n - 1, min(n, MAX_LINES)).round().astype(int))
    positions = np.arange(k)
    caption = f"Subjects (n = {n})" if len(shown) == n else (
        f"Subjects: {len(shown)} of {n} shown (evenly spaced rows); the results use all {n}")
    lines = axes.plot(positions, plan.values[shown].T, color=POINT_COLOR, alpha=.45, linewidth=1.0, marker="o",
                      markersize=3.5, zorder=2)
    for number, line in zip(shown, lines, strict=True):
        line.set_gid(f"{GID}subject")
    lines[0].set_label(caption)
    mean = axes.plot(positions, plan.values.mean(axis=0), color=LINE_COLOR, linewidth=2.4, marker="s", markersize=5,
                     zorder=3, label="Mean of the raters over all subjects")[0]
    mean.set_gid(f"{GID}mean")
    axes.set_xticks(positions, [str(name) for name in plan.settings.raters])
    axes.set_xlim(-.3, k - .7)
    if max(len(str(name)) for name in plan.settings.raters) * k > 60:
        axes.tick_params(axis="x", labelrotation=30)
    legend = figure.legend(loc="outside lower center", ncols=1, fontsize=8.5, frameon=False)
    _plain(axes.title, axes.yaxis.label, *legend.get_texts(), *axes.get_xticklabels())
    return figure


# ----- analysis ------------------------------------------------------------------------------------------------------

def analyse(frame, options, *, cancel=None):
    """Return the Result of Intraclass correlation; ``cancel`` is an optional threading.Event."""
    check_cancel(cancel)
    plan = prepare(frame, options)
    found = calculate(plan, cancel)
    tables = {ICC: _icc_table(plan, found), COMPONENTS: _components_table(plan, found),
              SUBJECTS: _subject_table(plan), SETTINGS: _settings_table(plan, found)}
    if plan.excluded:
        tables[EXCLUDED] = _excluded_table(plan)
    return Result(tables, _profile_figure(plan) if plan.settings.graph else None)
