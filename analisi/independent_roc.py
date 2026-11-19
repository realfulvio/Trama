"""Compare independent ROC curves: full, partial and standardized partial area.

Two markers are measured on four independent samples (Control A, Patient A, Control B, Patient B). The method
compares the areas under the two empirical ROC curves.

Full area
    The area is the integral of the empirical ROC polygon, which equals the Mann–Whitney probability with half
    credit for ties. The variance of the difference is the sum of the two DeLong variances of independent
    cohorts: V = var(placement of the patients) / m + var(placement of the controls) / n, with the sample variance.
    Z, p and the interval use the normal approximation; with SE = 0 they stay empty and Status says why.
Partial area
    The polygon is integrated over 0 <= FPR <= q (trapezoids, linear interpolation where q cuts a segment; vertical
    steps have area zero). The standardized partial area maps the raw area to ``0.5 * (1 + (raw - C) / (P - C))``
    with C = q² / 2 (the diagonal) and P = q (a perfect curve); values below 0.5 are kept.
Percentile bootstrap
    One ``Generator(PCG64(seed))`` draws, replicate after replicate and in the order Control A, Patient A, Control B,
    Patient B, ``rng.integers(0, n, size=n)`` from the sorted oriented values of each sample. The first B replicates
    do not depend on the number requested or on the order of the worksheet rows. The interval of the difference uses
    the linear quantiles alpha / 2 and 1 - alpha / 2, the variance the sample variance (B - 1) of the replicates.
    The areas of a replicate come from per-value counts, never from a patient × control matrix.

Scores are oriented per marker (sign −1 for "Lower in patients") so that a larger oriented score always points to a
patient; the sheets report thresholds on the original scale. Every observation with the same value enters the same
step of the polygon.

Limits: 100 000 observations in total, and for the bootstrap 200–10 000 replicates with
``B × observations <= 5 000 000``, checked before any sample is drawn. The bootstrap is cancellable between blocks.
"""
from numbers import Real

import numpy as np
import pandas as pd
from scipy import stats

from . import parallel, roc as roc_module
from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled
from .processing import _column
from .reporting import Result, _plot

METHOD = "Compare independent ROC curves"
CONTROL_A, PATIENT_A, CONTROL_B, PATIENT_B = "Control A", "Patient A", "Control B", "Patient B"
DIRECTION_A, DIRECTION_B = "Direction A", "Direction B"
AREA, MAX_FPR, INFERENCE, LEVEL = "Area", "Maximum FPR", "Inference", "Confidence level (%)"
REPLICATES, SEED, SAVE = "Bootstrap replicates", "Bootstrap seed", "Save bootstrap"
FULL, PARTIAL, STANDARDIZED = AREAS = ("Full", "Partial", "Standardized partial")
DELONG, BOOTSTRAP = INFERENCES = ("DeLong", "Percentile bootstrap")
HIGHER, LOWER = DIRECTIONS = roc_module.PAIRED_DIRECTIONS

COLUMN_FIELDS = (CONTROL_A, PATIENT_A, CONTROL_B, PATIENT_B)
DEFAULT_FPR = 0.1
# The dialog builds its controls from these defaults: tuples are choices (the first one is the default), None is a
# column, bool, int and float are check boxes and entries. Column fields come first, in the order the data is read.
OPTIONS = {CONTROL_A: None, PATIENT_A: None, CONTROL_B: None, PATIENT_B: None,
           DIRECTION_A: DIRECTIONS, DIRECTION_B: DIRECTIONS, AREA: AREAS, MAX_FPR: DEFAULT_FPR,
           INFERENCE: INFERENCES, LEVEL: roc_module.DEFAULT_LEVEL, REPLICATES: 1000, SEED: 0, SAVE: False}
BOOTSTRAP_FIELDS = (REPLICATES, SEED, SAVE)
NUMBER_FIELDS = (MAX_FPR, REPLICATES, SEED)

MIN_PER_SAMPLE = 2
MAX_OBSERVATIONS = 100_000
MIN_REPLICATES, MAX_REPLICATES, MAX_SEED = 200, 10_000, 2**32 - 1
BUDGET = 5_000_000
BLOCK_VALUES, MAX_BLOCK = 50_000, 500

SUMMARY_SHEET, CURVE_A_SHEET, CURVE_B_SHEET, BOOTSTRAP_SHEET = (
    "ROC comparison", "ROC curve A", "ROC curve B", "ROC bootstrap")
SUMMARY_COLUMNS = ["Area A", "Area B", "Raw area A", "Raw area B", "Difference", "Variance of difference", "SE",
                   "Lower", "Upper", "Z", "p", "Status", "Control A N", "Patient A N", "Control B N", "Patient B N",
                   "Direction A", "Direction B", "Area type", "Maximum FPR", "Inference", "Confidence level (%)",
                   "Bootstrap replicates", "Bootstrap seed", "Note"]
CURVE_COLUMNS = ["Threshold", "False positive rate", "True positive rate"]
STATUS_DELONG, STATUS_ZERO = "DeLong test", "Zero variance"
STATUS_BOOTSTRAP, STATUS_CONSTANT = "Percentile bootstrap", "Constant bootstrap distribution"
GID = "independent-roc:"
COLORS = ("#1f6f8b", "#aa5440")


class IndependentRocCancelled(MonteCarloCancelled):
    """The calculation was cancelled before a partial comparison could be published."""


def visibility(area, inference):
    """Fields that apply to the area and the inference; the others are hidden, not validated and not saved."""
    bootstrap = inference == BOOTSTRAP
    return {MAX_FPR: area != FULL, REPLICATES: bootstrap, SEED: bootstrap, SAVE: bootstrap}


def proposed_inference(area, inference):
    """Percentile bootstrap is the only inference of a partial area, so the editor proposes it."""
    return BOOTSTRAP if area != FULL and inference == DELONG else inference


def cancellable(method, options):
    """True when a calculation can be long enough to need the Cancel calculation button."""
    return (method == METHOD and isinstance(options, dict) and options.get(INFERENCE) == BOOTSTRAP)


# ----- options -------------------------------------------------------------------------------------------------------

def _choice(options, name, choices, message):
    value = options.get(name, choices[0])
    if not isinstance(value, str) or value not in choices:
        raise FieldError(name, message)
    return value


def _real(options, name, low, high, message):
    """A finite number strictly between ``low`` and ``high``; text may use a decimal comma. Only the level has a
    default for a missing key, like the paired comparison."""
    value = options.get(name, OPTIONS[name] if name == LEVEL else None)
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", "."))
        except ValueError:
            raise FieldError(name, message) from None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise FieldError(name, message)
    value = float(value)
    if not np.isfinite(value) or not low < value < high:
        raise FieldError(name, message)
    return value


def _integer(options, name, low, high):
    """A whole number from ``low`` to ``high``; a missing key takes the default. Decimals, booleans and other
    text are refused, also from a recipe."""
    message = f"{name} must be a whole number from {low:,} to {high:,}."
    value = options.get(name, OPTIONS[name])
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        value = int(value)
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise FieldError(name, message)
    if not low <= int(value) <= high:
        raise FieldError(name, message)
    return int(value)


def _settings(options):
    """Validate everything that does not need the worksheet. Returns a dict of typed settings."""
    if not isinstance(options, dict):
        raise FieldError(AREA, "Independent ROC options must be a mapping.")
    direction_message = "Choose Higher in patients or Lower in patients."
    settings = {DIRECTION_A: _choice(options, DIRECTION_A, DIRECTIONS, direction_message),
                DIRECTION_B: _choice(options, DIRECTION_B, DIRECTIONS, direction_message)}
    area = settings[AREA] = _choice(options, AREA, AREAS, "Choose Full, Partial or Standardized partial.")
    if area == FULL:
        settings[MAX_FPR] = 1.0
    else:
        settings[MAX_FPR] = _real(options, MAX_FPR, 0.0, 1.0,
                                  "Maximum FPR must be a number greater than 0 and less than 1.")
    inference = settings[INFERENCE] = _choice(options, INFERENCE, INFERENCES, "Choose DeLong or Percentile bootstrap.")
    if area != FULL and inference == DELONG:
        raise FieldError(INFERENCE, "A partial area has no DeLong variance. Choose Percentile bootstrap.")
    settings[LEVEL] = _real(options, LEVEL, 0.0, 100.0, "Confidence level (%) must be greater than 0 and less than 100.")
    if inference == BOOTSTRAP:
        settings[REPLICATES] = _integer(options, REPLICATES, MIN_REPLICATES, MAX_REPLICATES)
        settings[SEED] = _integer(options, SEED, 0, MAX_SEED)
        save = options.get(SAVE, OPTIONS[SAVE])
        if not isinstance(save, (bool, np.bool_)):
            raise FieldError(SAVE, "Save bootstrap must be on or off.")
        settings[SAVE] = bool(save)
    return settings


def normalized_options(options, settings):
    """Typed values of the numeric entries, for the recipe the dialog saves."""
    typed = dict(options)
    for name in NUMBER_FIELDS:
        if name in typed and name in settings and (name != MAX_FPR or settings[AREA] != FULL):
            typed[name] = settings[name]
    return typed


# ----- data ----------------------------------------------------------------------------------------------------------

def _samples(frame, options):
    """The four samples, each column on its own: blank and excluded cells shrink only their own sample."""
    values, first_use = {}, {}
    for field in COLUMN_FIELDS:
        name = options.get(field)
        if not isinstance(name, str) or not name or name not in frame:
            raise FieldError(field, f"Choose a column for {field}.")
        if name in first_use:
            raise FieldError(field, f'Column "{name}" is already used for {first_use[name]}. '
                                    "Choose four distinct columns.")
        first_use[name] = field
        if isinstance(frame[name], pd.DataFrame):
            raise FieldError(field, "Worksheet column names must be unique.")
        try:
            column = _column(frame, name, field).dropna().to_numpy(dtype=float)
        except TypeError:
            # Complex numbers reach pandas' nullable parser as a TypeError before the shared parser can name them.
            raise FieldError(field, f'Column "{name}" contains complex or unsupported data.') from None
        if len(column) < MIN_PER_SAMPLE:
            raise FieldError(field, f'Column "{name}" needs at least {MIN_PER_SAMPLE} valid values; '
                                    f"{len(column)} found.")
        values[field] = column
    total = sum(len(column) for column in values.values())
    if total > MAX_OBSERVATIONS:
        largest = max(COLUMN_FIELDS, key=lambda field: len(values[field]))
        raise FieldError(largest, f"The four columns hold {total:,} values; at most {MAX_OBSERVATIONS:,} are allowed.")
    return values, total


def _check_budget(settings, total):
    if settings[INFERENCE] != BOOTSTRAP:
        return
    work = settings[REPLICATES] * total
    if work > BUDGET:
        raise FieldError(REPLICATES, f"{REPLICATES} × observations = {settings[REPLICATES]:,} × {total:,} = "
                                     f"{work:,} exceeds the limit of {BUDGET:,}. Use fewer replicates or smaller samples.")


def _prepare(frame, options):
    settings = _settings(options)
    values, total = _samples(frame, options)
    _check_budget(settings, total)
    return settings, values, total


def check_options(frame, options):
    """Everything the dialog can know without drawing a bootstrap sample. Errors name their field.

    Returns the typed settings and the number of observations of each sample.
    """
    settings, values, _ = _prepare(frame, options)
    return settings, {field: len(column) for field, column in values.items()}


# ----- areas ---------------------------------------------------------------------------------------------------------

def partial_area(fpr, tpr, cutoff):
    """Area of the polygon through the points (fpr, tpr) for 0 <= FPR <= cutoff.

    The points start at the origin and are ordered by threshold, so fpr never decreases. A vertical step adds
    nothing, and the height of the next segment starts at its upper end. A segment cut by the cutoff is
    interpolated linearly in TPR.
    """
    x0, x1, y0, y1 = fpr[:-1], fpr[1:], tpr[:-1], tpr[1:]
    run = x1 - x0
    width = np.maximum(np.minimum(x1, cutoff) - x0, 0.0)
    slope = np.divide(y1 - y0, run, out=np.zeros_like(run), where=run > 0)
    return float(np.sum(width * (2 * y0 + width * slope)) / 2)


def standardize(raw, cutoff):
    """McClish standardization: 0.5 at the diagonal, 1 for a perfect curve; values below 0.5 are kept."""
    chance = cutoff * cutoff / 2
    return float(0.5 * (1 + (raw - chance) / (cutoff - chance)))


def _scaled(raw, area, cutoff):
    return standardize(raw, cutoff) if area == STANDARDIZED else raw


def _oriented(values, direction):
    sign = 1 if direction == HIGHER else -1
    return np.sort(sign * values + 0.0), sign


def _delong_variance(controls, patients):
    """DeLong variance of one AUC; exactly zero when every placement value is equal."""
    n, m = len(controls), len(patients)
    case_counts, control_counts = roc_module._placements(controls, patients)

    def spread(counts, scale):
        return 0.0 if np.ptp(counts) == 0 else float(np.var(counts / scale, ddof=1))

    return spread(case_counts, 2 * n) / m + spread(control_counts, 2 * m) / n


class _Cohort:
    """Sorted oriented controls and patients of one marker, with the index of each value in the common value list."""

    def __init__(self, controls, patients):
        self.n, self.m = len(controls), len(patients)
        values = np.unique(np.r_[controls, patients])
        self.size = len(values)
        self.control_block = values.searchsorted(controls)
        self.patient_block = values.searchsorted(patients)

    def curve(self, control_counts, patient_counts):
        """Polygon points, origin first, of a sample given as counts per ascending value."""
        fpr = np.r_[0.0, np.cumsum(control_counts[::-1])] / self.n
        tpr = np.r_[0.0, np.cumsum(patient_counts[::-1])] / self.m
        return fpr, tpr

    def resample_area(self, control_draw, patient_draw, cutoff):
        control_counts = np.bincount(self.control_block[control_draw], minlength=self.size)
        patient_counts = np.bincount(self.patient_block[patient_draw], minlength=self.size)
        return partial_area(*self.curve(control_counts, patient_counts), cutoff)


# ----- bootstrap -----------------------------------------------------------------------------------------------------

def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise IndependentRocCancelled("Independent ROC calculation cancelled.")


def _draws(rng, sizes):
    return [rng.integers(0, size, size=size) for size in sizes]


def _bootstrap_block(cohorts, sizes, rng, area, cutoff, count, block, cancel):
    cohort_a, cohort_b = cohorts
    area_a, area_b = np.empty(count), np.empty(count)
    for start in range(0, count, block):
        _check_cancel(cancel)
        for index in range(start, min(start + block, count)):
            draws = _draws(rng, sizes)
            area_a[index] = _scaled(cohort_a.resample_area(draws[0], draws[1], cutoff), area, cutoff)
            area_b[index] = _scaled(cohort_b.resample_area(draws[2], draws[3], cutoff), area, cutoff)
    _check_cancel(cancel)
    return area_a, area_b


def _bootstrap_task(item, cancel):
    cohorts, sizes, state, area, cutoff, count, block = item
    bitgen = np.random.PCG64()
    bitgen.state = state
    return _bootstrap_block(cohorts, sizes, np.random.Generator(bitgen), area, cutoff, count, block, cancel)


def _bootstrap(cohorts, settings, total, cancel):
    """Calculate the original PCG64 sequence on the chosen area scale."""
    cohort_a, cohort_b = cohorts
    replicates, cutoff, area = settings[REPLICATES], settings[MAX_FPR], settings[AREA]
    rng = np.random.Generator(np.random.PCG64(settings[SEED]))
    sizes = (cohort_a.n, cohort_a.m, cohort_b.n, cohort_b.m)
    block = int(min(MAX_BLOCK, max(1, BLOCK_VALUES // total)))
    processes = parallel.warm_process_count()
    if processes <= 1 or replicates * total < 500_000:
        return _bootstrap_block(cohorts, sizes, rng, area, cutoff, replicates, block, cancel)

    # The full PCG64 state includes the buffered half word. Splitting on
    # complete draw boundaries keeps odd sample sizes reproducible too.
    jobs = []
    chunk = (replicates + 2 * processes - 1) // (2 * processes)
    for start in range(0, replicates, chunk):
        _check_cancel(cancel)
        count = min(chunk, replicates - start)
        jobs.append((cohorts, sizes, rng.bit_generator.state, area, cutoff, count, block))
        if start + count < replicates:
            for index in range(count):
                if index % block == 0:
                    _check_cancel(cancel)
                _draws(rng, sizes)
    parts = parallel.run_tasks(_bootstrap_task, jobs, with_cancel=True, cancel=cancel)
    _check_cancel(cancel)
    return tuple(np.concatenate(values) for values in zip(*parts, strict=True))


def _spread(values):
    """Sample variance; exactly zero for a constant distribution."""
    return 0.0 if np.ptp(values) == 0 else float(np.var(values, ddof=1))


# ----- analysis ------------------------------------------------------------------------------------------------------

def _curve_table(thresholds, fpr, tpr, sign):
    return pd.DataFrame({"Threshold": np.r_[np.nan, thresholds * sign + 0.0],
                         "False positive rate": fpr, "True positive rate": tpr}, columns=CURVE_COLUMNS)


def independent_roc(frame, options, *, cancel=None):
    """Return the Result of Compare independent ROC curves. ``cancel`` is an optional threading.Event."""

    _check_cancel(cancel)
    settings, values, total = _prepare(frame, options)
    sizes = {field: len(column) for field, column in values.items()}
    area, cutoff, inference = settings[AREA], settings[MAX_FPR], settings[INFERENCE]
    shown = f"{settings[LEVEL]:g}"
    alpha = 1 - settings[LEVEL] / 100

    oriented, signs = {}, {}
    for controls, patients, direction in ((CONTROL_A, PATIENT_A, DIRECTION_A), (CONTROL_B, PATIENT_B, DIRECTION_B)):
        for field in (controls, patients):
            oriented[field], signs[direction] = _oriented(values[field], settings[direction])
    curves, raw = [], []
    for controls, patients in ((CONTROL_A, PATIENT_A), (CONTROL_B, PATIENT_B)):
        # Distinct oriented scores, high to low; the false and true positive rates start at the origin.
        thresholds, fpr, tpr = roc_module._curve(oriented[controls], oriented[patients])
        curves.append((thresholds, fpr, tpr))
        raw.append(partial_area(fpr, tpr, cutoff))
    area_a, area_b = (_scaled(value, area, cutoff) for value in raw)
    delta = area_a - area_b

    row = dict.fromkeys(SUMMARY_COLUMNS)
    row.update({"Area A": area_a, "Area B": area_b, "Raw area A": raw[0], "Raw area B": raw[1], "Difference": delta,
                "Control A N": sizes[CONTROL_A], "Patient A N": sizes[PATIENT_A],
                "Control B N": sizes[CONTROL_B], "Patient B N": sizes[PATIENT_B],
                "Direction A": settings[DIRECTION_A], "Direction B": settings[DIRECTION_B], "Area type": area,
                "Maximum FPR": None if area == FULL else cutoff, "Inference": inference,
                "Confidence level (%)": settings[LEVEL]})
    undefined = dict.fromkeys(("Z", "p", "Lower", "Upper"), np.nan)
    replicate_table = None
    if inference == DELONG:
        variance = (_delong_variance(oriented[CONTROL_A], oriented[PATIENT_A])
                    + _delong_variance(oriented[CONTROL_B], oriented[PATIENT_B]))
        se = float(np.sqrt(variance))
        if se > 0:
            critical = float(stats.norm.isf(alpha / 2))
            z = delta / se
            undefined = {"Z": z, "p": min(1.0, float(2 * stats.norm.sf(abs(z)))),
                         "Lower": max(-1.0, delta - critical * se), "Upper": min(1.0, delta + critical * se)}
            status = STATUS_DELONG
            note = (f"Normal approximation with the DeLong variance of independent cohorts (variance of the "
                    f"difference = V(A) + V(B)). Null hypothesis: AUC A = AUC B. Interval: {shown}%.")
        else:
            status = STATUS_ZERO
            note = "Zero variance: the standard error is zero, so Z, p and the interval are not defined."
    else:
        cohorts = [_Cohort(oriented[CONTROL_A], oriented[PATIENT_A]), _Cohort(oriented[CONTROL_B], oriented[PATIENT_B])]
        replicates_a, replicates_b = _bootstrap(cohorts, settings, total, cancel)
        differences = replicates_a - replicates_b
        variance = _spread(differences)
        se = float(np.sqrt(variance))
        low, high = np.quantile(differences, [alpha / 2, 1 - alpha / 2], method="linear")
        undefined = {"Z": np.nan, "p": np.nan, "Lower": float(low), "Upper": float(high)}
        status = STATUS_BOOTSTRAP
        note = (f"Percentile bootstrap, stratified by sample (Control A, Patient A, Control B, Patient B), "
                f"{settings[REPLICATES]:,} replicates, seed {settings[SEED]}. Z and p are not defined; the "
                f"interval is the {shown}% percentile interval of the difference.")
        if variance == 0:
            status = STATUS_CONSTANT
            note += (" Every replicate gives the same difference, so the interval is a single point "
                     "and the bootstrap carries no information about the spread.")
        row.update({"Bootstrap replicates": settings[REPLICATES], "Bootstrap seed": settings[SEED]})
        if settings[SAVE]:
            replicate_table = pd.DataFrame({"Replicate": np.arange(1, settings[REPLICATES] + 1),
                                            "Area A": replicates_a, "Area B": replicates_b,
                                            "Difference": differences})
    _check_cancel(cancel)
    row.update({"Variance of difference": variance, "SE": se, **undefined, "Status": status, "Note": note})
    summary = pd.DataFrame([row], columns=SUMMARY_COLUMNS)
    for name in ("Maximum FPR", "Bootstrap replicates", "Bootstrap seed"):
        summary[name] = pd.Series([row[name]], dtype=object)

    tables = {SUMMARY_SHEET: summary,
              CURVE_A_SHEET: _curve_table(*curves[0], signs[DIRECTION_A]),
              CURVE_B_SHEET: _curve_table(*curves[1], signs[DIRECTION_B])}
    if replicate_table is not None:
        tables[BOOTSTRAP_SHEET] = replicate_table
    return Result(tables, _figure(options, settings, curves, (area_a, area_b)))


# ----- figure --------------------------------------------------------------------------------------------------------

def _plain(*texts):
    for text in texts:
        text.set_parse_math(False)


AREA_NAMES = {FULL: "AUC", PARTIAL: "pAUC", STANDARDIZED: "standardized pAUC"}


def area_label(area, cutoff):
    return AREA_NAMES[area] + ("" if area == FULL else f" (FPR ≤ {cutoff:g})")


def _figure(options, settings, curves, areas):
    area, cutoff = settings[AREA], settings[MAX_FPR]
    figure, axes = _plot(f"Independent ROC curves · {area_label(area, cutoff)}",
                         "False positive rate", "True positive rate")
    axes._tramastat_numeric_axes = ("x", "y")
    if area != FULL:
        band = axes.axvspan(0, cutoff, color="#2f7d6b", alpha=.12, zorder=0, linewidth=0,
                            label=f"FPR 0 to {cutoff:g}")
        band.set_gid(f"{GID}band")
    for letter, (_, fpr, tpr), estimate, (controls, patients), color in zip(
            "AB", curves, areas, ((options[CONTROL_A], options[PATIENT_A]), (options[CONTROL_B], options[PATIENT_B])),
            COLORS, strict=True):
        # The points are the corners of the polygon that is integrated, so a tie draws its diagonal segment.
        line, = axes.plot(fpr, tpr, color=color, linewidth=2, zorder=3,
                          label=f"{letter} ({patients} vs {controls}): {AREA_NAMES[area]} {estimate:.4g}")
        line.set_gid(f"{GID}curve-{letter.lower()}")
    diagonal, = axes.plot([0, 1], [0, 1], "--", color="#81919b", zorder=1, label="Chance")
    diagonal.set_gid(f"{GID}diagonal")
    if area != FULL:
        cut = axes.axvline(cutoff, color="#1f2933", linestyle=":", linewidth=1.5, zorder=2,
                           label=f"Maximum FPR = {cutoff:g}")
        cut.set_gid(f"{GID}cutoff")
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1)
    legend = axes.legend(loc="lower right", fontsize=8.5)
    _plain(axes.title, *legend.get_texts())
    return figure
