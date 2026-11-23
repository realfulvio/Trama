"""K-means stability under re-initialisation and subsampling: options, engine, sheets and figure.

For every k from Minimum k to Maximum k the analysis fits a reference partition on all effective rows, then
repeats the fit on subsamples drawn without replacement and, optionally, on the full data with other seeds. It
reports how often the same partition comes back. It does not choose k and it does not prove that a clustering is
valid: it describes stability under this perturbation only.

Rows and positions
    The worksheet row of an observation is its 1-based position in the frame the dispatcher receives (after the
    exclusions), counted before incomplete rows are dropped. Pandas labels are never used, so duplicate row labels
    are harmless. A row is complete when every selected variable is a finite number; NaN and infinite values make
    it incomplete.

Seeds (all streams independent and fixed by the recipe)
    Subsample of replicate r (r = 1, 2, …): ``Generator(PCG64(SeedSequence([seed, 0, r, 10]))).choice(n, m,
    replace=False)``, sorted; the same rows for every k. A fit seed is ``SeedSequence([seed, k, r, s])
    .generate_state(1, dtype=uint32)[0]`` with s = 20 for the reference (r = 0), 21 for a subsample fit and 22 for
    a seed run. Each fit is one call of ``analisi.stats.kmeans`` with its own internal starts, best-fit choice and
    convergence rule. Replicate r therefore gives the same numbers whatever the number of replicates, the list of k
    or the number of processes.

Projection and matching
    A subsample fit learns its own mean and SD (ddof=1) when Standardize is on. All effective rows are transformed
    with them and assigned to the nearest centre by squared Euclidean distance; an exact tie goes to the lower
    cluster number. An empty projected cluster makes the replicate invalid. The projected partition is compared
    with the reference by :func:`compare_partitions`: one-to-one matching of maximum total overlap (ties to the
    lexicographically smallest tuple of candidate labels, in reference order), per-cluster Jaccard on the aligned
    labels and the adjusted Rand index (Hubert and Arabie, 1985) of the whole partition. OOB ARI uses the rows the
    replicate never saw.

Every error the user can correct names its dialog field through ``FieldError``. ``prepare`` reads the data and
checks options and budgets without fitting anything (the dialog calls it before the worker starts). ``analysis``
runs the fits and polls ``cancel`` between them; reports are built only once every fit has finished. With more
than one process allowed (``analisi.parallel``), the fits go to the shared pool in blocks of ``BATCH``; the
numbers are the same as in the serial loop.
"""
from dataclasses import dataclass
from fractions import Fraction
from math import floor, isfinite
from numbers import Integral, Real
import re

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from scipy.optimize import linear_sum_assignment

from . import kmeans_options
from . import stats as engine
from .data import decimal_comma
from .field_error import FieldError
from .hartigan_wong import IterationLimitError
from .monte_carlo import MonteCarloCancelled
from .parallel import process_count, run_tasks
from .reporting import Result, _report

METHOD = "K-means stability"
VARIABLES, MIN_K, MAX_K, STANDARDIZE, SEED = "Variables", "Minimum k", "Maximum k", "Standardize", "Seed"
RESAMPLES, FRACTION, SEED_RUNS, REPORT_K = "Resamples", "Sample fraction (%)", "Seed runs", "Report k"
COASSIGNMENT = "Show co-assignment matrix"
ALGORITHM, MAX_ITERATIONS = kmeans_options.ALGORITHM, kmeans_options.MAX_ITERATIONS

# Dialog fields, in order: column roles, choices, flags and typed defaults (``analisi.workbench.METHODS``).
OPTIONS = {VARIABLES: "Multiple", MIN_K: 2, MAX_K: 4, STANDARDIZE: True,
           ALGORITHM: kmeans_options.ALGORITHMS, MAX_ITERATIONS: kmeans_options.DEFAULT_ITERATIONS,
           SEED: 42, RESAMPLES: 100, FRACTION: 80.0, SEED_RUNS: 0, REPORT_K: 2, COASSIGNMENT: False}
DEFAULTS = {MIN_K: 2, MAX_K: 4, STANDARDIZE: True, ALGORITHM: kmeans_options.LLOYD,
            MAX_ITERATIONS: kmeans_options.DEFAULT_ITERATIONS, SEED: 42, RESAMPLES: 100, FRACTION: 80.0,
            SEED_RUNS: 0, REPORT_K: 2, COASSIGNMENT: False}

SUMMARY, SCORES, CLUSTERS, ASSIGNMENTS = ("Stability summary", "Resample scores", "Cluster stability",
                                          "Assignment stability")
CENTERS, SEEDS, COASSIGN_SHEET, SETTINGS = "Reference centers", "Seed sensitivity", "Co-assignment", "Settings"
SHEETS = (SUMMARY, SCORES, CLUSTERS, ASSIGNMENTS, CENTERS, SEEDS, COASSIGN_SHEET, SETTINGS)
SUMMARY_COLUMNS = ["N", "Sample N", "Valid resamples", "Median ARI", "ARI p10", "ARI p90", "Median OOB ARI",
                   "Reference WSS", "Status"]
SEED_SUMMARY_COLUMNS = ["Valid seed runs", "Median seed-run ARI"]
SCORE_COLUMNS = ["k", "Replicate", "ARI", "OOB ARI", "Status"]
CLUSTER_COLUMNS = ["k", "Cluster", "N", "Median Jaccard", "Jaccard p10", "Jaccard p90", "Valid resamples"]
ASSIGNMENT_COLUMNS = ["Worksheet row", "Reference cluster", "Agreement", "Valid resamples"]
CENTER_COLUMNS = ["k", "Cluster", "Variable", "Center", "Fitting center"]
SEED_COLUMNS = ["k", "Replicate", "ARI", "Status"]
ROW = "Worksheet row"

OK = "OK"
CONSTANT_SAMPLE = "A selected variable is constant in this sample"
FEW_DISTINCT = "Fewer distinct sampled rows than k"
EMPTY_PROJECTION = "A cluster is empty after projection"
NO_VALID = "No valid resamples"
REFERENCE_FAILED = "Reference fit failed: {reason}"

MIN_CLUSTERS, MAX_CLUSTERS, MAX_VARIABLES = 2, 12, 32
MAX_SEED, MIN_RESAMPLES, MAX_RESAMPLES, MAX_SEED_RUNS = 2**32 - 1, 5, 2000, 100
MIN_FRACTION, MAX_FRACTION = 50, 95
MAX_ROWS, MAX_ROW_CLUSTERS, MAX_FITS, MAX_WORK = 20_000, 2_000_000, 6_000, 600_000_000
MAX_MATRIX_ROWS = 200
BATCH = 32  # fits handed to the process pool at once: bounds the results waiting in memory

SAMPLING = ("Without replacement: replicate r draws Generator(PCG64(SeedSequence([seed, 0, r, 10])))"
            ".choice(N, Sample N, replace=False), sorted; the same rows for every k")
FIT_SEEDS = ("SeedSequence([seed, k, r, s]).generate_state(1, uint32)[0]; s = 20 reference (r = 0), "
             "21 subsample fit, 22 seed run")
MATCHING = ("One-to-one matching of maximum total overlap; ties go to the lexicographically smallest candidate "
            "labels in reference order")
PERCENTILES = "Empirical 10th and 90th percentiles of the valid replicates (linear interpolation)"
INTERPRETATION = ("Describes stability under this perturbation only. The p10–p90 bands are empirical percentiles "
                  "of the valid replicates, not confidence intervals for k, and they do not prove that the "
                  "clustering is valid. The analysis does not choose k.")
LIMITS = "N ≤ 20,000; N × Maximum k ≤ 2,000,000; K-means fits ≤ 6,000; N × variables × Σk × fits per k ≤ 600 million"

# Engine messages are English; ``analisi.interface_catalog`` words them in Italian under this prefix. Captions of
# the fields come from the same catalog. Recipes keep the English names and the sheets keep English titles.
ERROR_PREFIX = "kstab.error."
_INTEGER = re.compile(r"\s*\+?[0-9]+\s*")
REFERENCE, SUBSAMPLE, SEED_RUN = "reference", "subsample", "seed run"
_STREAM = {REFERENCE: 20, SUBSAMPLE: 21, SEED_RUN: 22}


class KMeansStabilityCancelled(MonteCarloCancelled, InterruptedError):
    """The fits were cancelled before any report was built.

    ``InterruptedError`` for callers of the dispatcher; ``MonteCarloCancelled`` for the application, which keeps
    the last confirmed result of every cancellable job through that one path.
    """


def _cancelled(cancel):
    if cancel is None:
        return False
    if hasattr(cancel, "is_set"):
        return bool(cancel.is_set())
    return bool(cancel())


def check_cancel(cancel):
    if _cancelled(cancel):
        raise KMeansStabilityCancelled("K-means stability cancelled.")


def visibility(algorithm):
    """The iteration limit belongs to Hartigan–Wong only."""
    return {MAX_ITERATIONS: algorithm == kmeans_options.HARTIGAN}


# ----- options -----------------------------------------------------------------------------------------------------

def _get(options, name):
    return options.get(name, DEFAULTS[name])


def _whole(options, name, low, high):
    value = _get(options, name)
    if isinstance(value, str):
        value = value.strip()
        try:
            value = int(value) if _INTEGER.fullmatch(value) else None
        except ValueError:
            value = None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or not low <= value <= high:
        raise FieldError(name, f"{name}: enter a whole number from {low} to {high}.")
    return int(value)


def _flag(options, name):
    value = _get(options, name)
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name}: choose on or off.")
    return bool(value)


def _fraction(options):
    value = _get(options, FRACTION)
    if isinstance(value, str):
        try:
            value = float(decimal_comma(value.strip()))
        except ValueError:
            value = None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not isfinite(float(value)) \
            or not MIN_FRACTION <= float(value) <= MAX_FRACTION:
        raise FieldError(FRACTION, f"{FRACTION}: enter a number from {MIN_FRACTION} to {MAX_FRACTION}.")
    return float(value)


def sample_size(n, fraction):
    """floor(n × fraction / 100) on the decimal value of the fraction, so 80 % of 18 rows is 14."""
    return floor(n * Fraction(repr(float(fraction))) / 100)


def _variables(options):
    names = options.get(VARIABLES)
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, (list, tuple)) or not all(isinstance(name, str) for name in names) \
            or not 1 <= len(names) <= MAX_VARIABLES:
        raise FieldError(VARIABLES, f"Select from 1 to {MAX_VARIABLES} numeric columns.")
    if len(set(names)) != len(names):
        raise FieldError(VARIABLES, "Select each column only once.")
    return list(names)


def _numbers(frame, names):
    """The selected columns as floats by position, and the complete-row mask. Text is an error, not a gap."""
    titles = [str(title) for title in frame.columns]
    blocks = []
    for name in names:
        positions = [index for index, title in enumerate(titles) if title == name]
        if not positions:
            raise FieldError(VARIABLES, f'Column "{name}" is not in the table.')
        if len(positions) > 1:
            raise FieldError(VARIABLES, f'More than one column is called "{name}".')
        column = frame.iloc[:, positions[0]]
        numeric = pd.to_numeric(column, errors="coerce")
        if np.iscomplexobj(numeric.to_numpy()):
            raise FieldError(VARIABLES, f'Column "{name}" contains complex data.')
        values = numeric.to_numpy(dtype=float, na_value=np.nan)
        text = column.notna().to_numpy() & np.isnan(values)
        if text.any():
            raise FieldError(VARIABLES, f'Column "{name}" contains text.')
        blocks.append(values)
    values = np.column_stack(blocks) if blocks else np.empty((len(frame), 0))
    return values, np.isfinite(values).all(axis=1)


@dataclass
class Plan:
    """Everything a calculation needs, checked: no fit has run yet."""
    names: list
    values: np.ndarray          # complete rows only, in worksheet order (n × p)
    rows: np.ndarray            # their 1-based worksheet rows
    worksheet_rows: int
    ks: tuple
    standardize: bool
    fit_kwargs: dict
    seed: int
    resamples: int
    fraction: float
    sample: int                 # m
    seed_runs: int
    report_k: int
    coassignment: bool
    settings: dict              # canonical options, as stored in the recipe
    fits: int
    work: int

    @property
    def n(self):
        return len(self.values)


def _budget_field(fits_without_seed_runs, seed_runs):
    """A budget error points at the button that can fix it: Seed runs when dropping them would be enough."""
    return SEED_RUNS if seed_runs and fits_without_seed_runs else RESAMPLES


def prepare(frame, options):
    """Read and check the options, data and budgets; no allocation beyond the selected columns, no fit."""
    if not isinstance(options, dict):
        raise ValueError("K-means stability options must be a mapping.")
    names = _variables(options)
    low = _whole(options, MIN_K, MIN_CLUSTERS, MAX_CLUSTERS)
    high = _whole(options, MAX_K, low, MAX_CLUSTERS)
    standardize = _flag(options, STANDARDIZE)
    algorithm = _get(options, ALGORITHM)
    choice = {ALGORITHM: algorithm, MAX_ITERATIONS: _get(options, MAX_ITERATIONS)}
    fit_kwargs = kmeans_options.fit_options(kmeans_options.SELECTION, frame, choice)
    seed = _whole(options, SEED, 0, MAX_SEED)
    resamples = _whole(options, RESAMPLES, MIN_RESAMPLES, MAX_RESAMPLES)
    fraction = _fraction(options)
    seed_runs = _whole(options, SEED_RUNS, 0, MAX_SEED_RUNS)
    report_k = _whole(options, REPORT_K, low, high)
    coassignment = _flag(options, COASSIGNMENT)

    raw, complete = _numbers(frame, names)
    values = np.ascontiguousarray(raw[complete])
    rows = np.flatnonzero(complete) + 1
    n = len(values)
    if n == 0:
        raise FieldError(VARIABLES, "No row has a number in every selected column.")
    if n > MAX_ROWS:
        raise FieldError(VARIABLES, f"Use at most {MAX_ROWS} complete rows (this selection has {n}).")
    if standardize:
        for name, column in zip(names, values.T, strict=True):
            if n < 2 or np.all(column == column[0]):
                raise FieldError(VARIABLES, f'Column "{name}" is constant and cannot be standardized.')
    largest = sample_size(n, MAX_FRACTION)
    if largest < high + 1:
        if largest - 1 < MIN_CLUSTERS:
            raise FieldError(VARIABLES, f"There are only {n} complete rows: samples are too small for k = 2.")
        raise FieldError(MAX_K, f"With {n} complete rows a sample holds at most {largest} rows: "
                                f"choose Maximum k up to {largest - 1}.")
    sample = sample_size(n, fraction)
    if sample < high + 1:
        raise FieldError(FRACTION, f"Each sample has {sample} of {n} rows and needs at least {high + 1} "
                                   f"(Maximum k + 1): raise the sample fraction.")
    distinct = len(np.unique(values, axis=0))
    if distinct < high:
        raise FieldError(MAX_K, f"Maximum k cannot exceed the {distinct} distinct observations.")
    if n * high > MAX_ROW_CLUSTERS:
        raise FieldError(MAX_K, f"N × Maximum k must be at most {MAX_ROW_CLUSTERS} "
                                f"({n} rows × {high} = {n * high}).")
    ks = tuple(range(low, high + 1))
    per_k = 1 + resamples + seed_runs
    fits = len(ks) * per_k
    if fits > MAX_FITS:
        raise FieldError(_budget_field(len(ks) * (1 + resamples) <= MAX_FITS, seed_runs),
                         f"This request needs {fits} K-means fits; the limit is {MAX_FITS}. "
                         f"Lower Resamples, Seed runs or the range of k.")
    work = n * values.shape[1] * sum(ks) * per_k
    if work > MAX_WORK:
        field = _budget_field(n * values.shape[1] * sum(ks) * (1 + resamples) <= MAX_WORK, seed_runs)
        raise FieldError(field, f"This request needs {work} work units; the limit is {MAX_WORK}. "
                                f"Lower Resamples, Seed runs, the range of k or the number of variables.")
    if coassignment and n > MAX_MATRIX_ROWS:
        raise FieldError(COASSIGNMENT, f"The co-assignment matrix needs at most {MAX_MATRIX_ROWS} complete rows "
                                       f"(this selection has {n}).")
    settings = {VARIABLES: names, MIN_K: low, MAX_K: high, STANDARDIZE: standardize,
                ALGORITHM: algorithm, SEED: seed, RESAMPLES: resamples, FRACTION: fraction,
                SEED_RUNS: seed_runs, REPORT_K: report_k, COASSIGNMENT: coassignment}
    if algorithm == kmeans_options.HARTIGAN:
        settings[MAX_ITERATIONS] = fit_kwargs["max_iterations"]
    return Plan(names, values, rows, len(frame), ks, standardize, fit_kwargs, seed, resamples, fraction, sample,
                seed_runs, report_k, coassignment, settings, fits, work)


# ----- seeds -------------------------------------------------------------------------------------------------------

def sample_positions(seed, replicate, n, m):
    """Sorted positions (0-based, among the complete rows) of replicate ``replicate``; the same for every k."""
    generator = np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, 0, replicate, 10])))
    return np.sort(generator.choice(n, m, replace=False))


def fit_seed(seed, k, replicate, kind):
    """The integer seed handed to ``analisi.stats.kmeans`` for one fit."""
    state = np.random.SeedSequence([seed, k, replicate, _STREAM[kind]]).generate_state(1, dtype=np.uint32)
    return int(state[0])


# ----- partitions --------------------------------------------------------------------------------------------------

def _labels(values, name, length=None):
    array = np.asarray(values)
    if array.ndim != 1 or (length is not None and len(array) != length):
        raise ValueError(f"The {name} partition must be a vector of the same length as the reference.")
    if array.dtype.kind not in "iu":
        if array.dtype.kind != "f" or not np.all(np.isfinite(array)) or np.any(array != np.round(array)):
            raise ValueError(f"The {name} partition must contain whole-number labels.")
    return array.astype(np.int64)


def _table(reference, candidate, rows, columns):
    """Contingency counts of two 0-based label vectors."""
    return np.bincount(reference * columns + candidate, minlength=rows * columns).reshape(rows, columns)


def _pairs(counts):
    counts = np.asarray(counts, dtype=np.int64)
    return int((counts * (counts - 1) // 2).sum())


def _ari_table(table):
    """Hubert–Arabie ARI from integer counts; exact integers until the final division."""
    n = int(table.sum())
    a, b, c = _pairs(table), _pairs(table.sum(axis=1)), _pairs(table.sum(axis=0))
    t = n * (n - 1) // 2
    numerator = 2 * a * t - 2 * b * c
    denominator = (b + c) * t - 2 * b * c
    # The denominator is b(t − c) + c(t − b): zero only when both partitions are all singletons or both a single
    # group (or n < 2), that is when they are equal up to the labels.
    return 1.0 if denominator == 0 else numerator / denominator


def adjusted_rand(reference, candidate):
    """ARI of two label vectors of the same length; labels are arbitrary integers."""
    reference = _labels(reference, "reference")
    candidate = _labels(candidate, "candidate", len(reference))
    left, left_codes = np.unique(reference, return_inverse=True)
    right, right_codes = np.unique(candidate, return_inverse=True)
    return _ari_table(_table(left_codes, right_codes, len(left), len(right)))


def _best_total(table, rows, columns):
    if not rows:
        return 0
    block = table[np.ix_(rows, columns)]
    chosen_rows, chosen_columns = linear_sum_assignment(block, maximize=True)
    return int(block[chosen_rows, chosen_columns].sum())


def _matching(table):
    """0-based candidate column for each reference row: maximum total, then the lexicographically smallest tuple.

    The optimum comes from a polynomial assignment. Row by row, the smallest free column is kept as soon as fixing
    it still allows the optimum on the remaining rows; integer totals make the comparison exact.
    """
    k = table.shape[0]
    target = _best_total(table, list(range(k)), list(range(k)))
    mapping, total = [], 0
    for row in range(k):
        free = [column for column in range(k) if column not in mapping]
        for column in free:
            rest = [other for other in free if other != column]
            if total + int(table[row, column]) + _best_total(table, list(range(row + 1, k)), rest) == target:
                mapping.append(column)
                total += int(table[row, column])
                break
        else:  # pragma: no cover - the optimum always extends
            raise AssertionError("No assignment preserves the optimum.")
    return mapping


def compare_partitions(reference, candidate, k):
    """Compare two partitions of the same rows labelled 1…k, every group represented in both.

    Returns ``ari`` (Hubert–Arabie, label-free), ``mapping`` (the candidate label matched with each reference
    group, in reference order), ``jaccard`` (each reference group against its matched candidate group) and
    ``aligned`` (the candidate partition renumbered to the reference labels, in row order).
    """
    if isinstance(k, (bool, np.bool_)) or not isinstance(k, Integral) or k < 1:
        raise ValueError("k must be a positive whole number.")
    k = int(k)
    reference = _labels(reference, "reference")
    candidate = _labels(candidate, "candidate", len(reference))
    for name, labels in (("reference", reference), ("candidate", candidate)):
        if len(labels) == 0 or labels.min() < 1 or labels.max() > k or len(np.unique(labels)) != k:
            raise ValueError(f"The {name} partition must use every label from 1 to {k}.")
    table = _table(reference - 1, candidate - 1, k, k)
    mapping = _matching(table)
    rows, columns = table.sum(axis=1), table.sum(axis=0)
    jaccard = np.array([table[row, column] / (rows[row] + columns[column] - table[row, column])
                        for row, column in enumerate(mapping)], dtype=float)
    renumber = np.empty(k, dtype=np.int64)
    renumber[mapping] = np.arange(1, k + 1)
    return {"ari": _ari_table(table), "mapping": np.asarray(mapping, dtype=np.int64) + 1, "jaccard": jaccard,
            "aligned": renumber[candidate - 1]}


# ----- fits --------------------------------------------------------------------------------------------------------

def _fit(values, k, standardize, seed, fit_kwargs):
    """One complete ``analisi.stats.kmeans`` fit; ValueError for data it cannot fit."""
    frame = pd.DataFrame(values, columns=[f"v{index}" for index in range(values.shape[1])])
    fit = engine.kmeans(frame, list(frame.columns), k, standardize, seed, **fit_kwargs)
    return (fit.labels.to_numpy(dtype=np.int64), fit.centers.to_numpy(dtype=float), float(fit.inertia))


def project(values, centers, mean=None, sd=None):
    """Nearest centre (1-based) of every row; a row exactly between two centres goes to the lower number.

    ``mean`` and ``sd`` transform the rows to the scale of the centres. Memory and time are linear in the rows.
    """
    scaled = values if mean is None else (values - mean) / sd
    best = np.full(len(values), np.inf)
    labels = np.zeros(len(values), dtype=np.int64)
    for index, center in enumerate(centers, 1):
        distance = np.square(scaled - center).sum(axis=1)
        closer = distance < best  # strict: the first (lowest) centre keeps an exact tie
        labels[closer] = index
        best[closer] = distance[closer]
    return labels


def _reference_task(values, k, standardize, seed, fit_kwargs):
    try:
        labels, centers, inertia = _fit(values, k, standardize, fit_seed(seed, k, 0, REFERENCE), fit_kwargs)
    except ValueError as error:  # expected: the engine could not fit these data
        return {"status": REFERENCE_FAILED.format(reason=str(error)),
                "iterations": isinstance(error, IterationLimitError)}
    return {"status": OK, "labels": labels, "centers": centers, "inertia": inertia}


def _seed_task(values, k, replicate, standardize, seed, fit_kwargs, reference):
    try:
        labels, _, _ = _fit(values, k, standardize, fit_seed(seed, k, replicate, SEED_RUN), fit_kwargs)
    except ValueError as error:
        return {"status": str(error)}
    return {"status": OK, "ari": adjusted_rand(reference, labels)}


def _subsample_task(values, k, replicate, standardize, seed, fit_kwargs, sample, reference, keep):
    positions = sample_positions(seed, replicate, len(values), sample)
    part = values[positions]
    mean = sd = None
    if standardize:
        mean, sd = part.mean(axis=0), part.std(axis=0, ddof=1)
        if not np.all(sd > 0):
            return {"status": CONSTANT_SAMPLE}
    if len(np.unique(part, axis=0)) < k:
        return {"status": FEW_DISTINCT}
    try:
        _, centers, _ = _fit(part, k, standardize, fit_seed(seed, k, replicate, SUBSAMPLE), fit_kwargs)
    except ValueError as error:
        return {"status": str(error)}
    projected = project(values, centers, mean, sd)
    if len(np.unique(projected)) != k:
        return {"status": EMPTY_PROJECTION}
    compared = compare_partitions(reference, projected, k)
    unseen = np.ones(len(values), dtype=bool)
    unseen[positions] = False
    oob = np.nan
    if len(np.unique(reference[unseen])) >= 2 and len(np.unique(projected[unseen])) >= 2:
        oob = adjusted_rand(reference[unseen], projected[unseen])
    return {"status": OK, "ari": compared["ari"], "oob": oob, "jaccard": compared["jaccard"],
            "aligned": compared["aligned"].astype(np.int8) if keep else None}


def run_task(task, cancel=None):
    """One fit and its comparison, as a picklable top-level function (one fit is the unit of parallel work)."""
    if _cancelled(cancel):
        return None
    kind, arguments = task
    if kind == REFERENCE:
        return _reference_task(*arguments)
    if kind == SEED_RUN:
        return _seed_task(*arguments)
    return _subsample_task(*arguments)


def _execute(tasks, cancel, progress, state):
    """Results of ``tasks`` in order: on the shared process pool (``analisi.parallel``) when the preference allows
    more than one process, otherwise one after the other on this thread with a progress step per fit."""
    if process_count() > 1 and len(tasks) > 1:
        outcomes = run_tasks(run_task, tasks, cancel=cancel, with_cancel=True, outcomes=True)
        check_cancel(cancel)
        found = []
        for outcome in outcomes:
            if outcome.error is not None:  # a programming error: never a replicate status
                raise outcome.error
            if outcome.value is None:
                check_cancel(cancel)
            found.append(outcome.value)
        state[0] += len(tasks)
        if progress is not None:
            progress(state[0], state[1])
        return found
    found = []
    for task in tasks:
        check_cancel(cancel)
        found.append(run_task(task))
        state[0] += 1
        if progress is not None:
            progress(state[0], state[1])
    return found


def _batched(tasks, cancel, progress, state):
    for start in range(0, len(tasks), BATCH):
        yield from _execute(tasks[start:start + BATCH], cancel, progress, state)


class _Collector:
    """Per-k accumulators; rows of the report are added in replicate order and labels are never kept."""

    def __init__(self, plan, k, reference):
        self.k = k
        self.reference = reference
        self.scores, self.ari, self.oob, self.jaccard = [], [], [], []
        self.seeds, self.seed_ari = [], []
        keep = k == plan.report_k
        self.agree = np.zeros(plan.n, dtype=np.int64) if keep else None
        # Integer counts of shared groups; allocated only when the matrix was requested.
        self.shared = np.zeros((plan.n, plan.n), dtype=np.int64) if keep and plan.coassignment else None

    def add(self, replicate, outcome):
        status = outcome["status"]
        if status != OK:
            self.scores.append((self.k, replicate, np.nan, np.nan, status))
            return
        self.scores.append((self.k, replicate, outcome["ari"], outcome["oob"], OK))
        self.ari.append(outcome["ari"])
        if np.isfinite(outcome["oob"]):
            self.oob.append(outcome["oob"])
        self.jaccard.append(outcome["jaccard"])
        aligned = outcome["aligned"]
        if self.agree is not None:
            self.agree += aligned == self.reference["labels"]
        if self.shared is not None:
            members = np.eye(self.k, dtype=np.int64)[aligned.astype(np.int64) - 1]
            self.shared += members @ members.T

    def add_seed(self, replicate, outcome):
        if outcome["status"] == OK:
            self.seeds.append((self.k, replicate, outcome["ari"], OK))
            self.seed_ari.append(outcome["ari"])
        else:
            self.seeds.append((self.k, replicate, np.nan, outcome["status"]))


def _quantiles(values):
    if not len(values):
        return np.nan, np.nan, np.nan
    low, middle, high = np.percentile(np.asarray(values, dtype=float), [10, 50, 90])
    return float(middle), float(low), float(high)


# ----- calculation -------------------------------------------------------------------------------------------------

def calculate(plan, cancel=None, progress=None):
    """Run every fit of ``plan`` and build the result. A cancellation raises before any sheet exists."""
    values, ks = plan.values, plan.ks
    state = [0, plan.fits]
    references = list(_batched([(REFERENCE, (values, k, plan.standardize, plan.seed, plan.fit_kwargs))
                                for k in ks], cancel, progress, state))
    if not any(reference["status"] == OK for reference in references):
        if all(reference["iterations"] for reference in references):
            raise FieldError(MAX_ITERATIONS, "Hartigan–Wong reached the maximum number of iterations.")
        raise ValueError(f"No reference partition could be fitted for k = {ks[0]}–{ks[-1]}. "
                         f"{references[0]['status']}")
    collectors = {k: _Collector(plan, k, reference) for k, reference in zip(ks, references, strict=True)}
    available = [k for k in ks if references[ks.index(k)]["status"] == OK]
    state[1] = len(ks) + len(available) * (plan.resamples + plan.seed_runs)
    if progress is not None:
        progress(state[0], state[1])
    for k in available:
        collector = collectors[k]
        reference = collector.reference["labels"]
        tasks = [(SUBSAMPLE, (values, k, replicate, plan.standardize, plan.seed, plan.fit_kwargs, plan.sample,
                              reference, k == plan.report_k))
                 for replicate in range(1, plan.resamples + 1)]
        for replicate, outcome in enumerate(_batched(tasks, cancel, progress, state), 1):
            collector.add(replicate, outcome)
        tasks = [(SEED_RUN, (values, k, replicate, plan.standardize, plan.seed, plan.fit_kwargs, reference))
                 for replicate in range(1, plan.seed_runs + 1)]
        for replicate, outcome in enumerate(_batched(tasks, cancel, progress, state), 1):
            collector.add_seed(replicate, outcome)
    check_cancel(cancel)
    return _result(plan, collectors)


def analysis(frame, options, *, cancel=None, progress=None):
    """Dispatcher entry: check everything, then fit. The worker thread passes ``cancel`` and ``progress``."""
    return calculate(prepare(frame, options), cancel, progress)


# ----- sheets and figure -------------------------------------------------------------------------------------------

def _original_centers(plan, centers):
    if not plan.standardize:
        return centers
    return centers * plan.values.std(axis=0, ddof=1) + plan.values.mean(axis=0)


def _result(plan, collectors):
    summary, scores, clusters, centers, seeds = [], [], [], [], []
    for k, collector in collectors.items():
        reference = collector.reference
        median, low, high = _quantiles(collector.ari)
        oob = float(np.median(collector.oob)) if collector.oob else np.nan
        if reference["status"] != OK:
            status, wss = reference["status"], np.nan
        else:
            status, wss = (OK if collector.ari else NO_VALID), reference["inertia"]
        row = {"k": k, "N": plan.n, "Sample N": plan.sample, "Valid resamples": len(collector.ari),
               "Median ARI": median, "ARI p10": low, "ARI p90": high, "Median OOB ARI": oob,
               "Reference WSS": wss, "Status": status}
        if plan.seed_runs:
            row.update({"Valid seed runs": len(collector.seed_ari),
                        "Median seed-run ARI": float(np.median(collector.seed_ari)) if collector.seed_ari
                        else np.nan})
        summary.append(row)
        scores.extend(collector.scores)
        seeds.extend(collector.seeds)
        if reference["status"] != OK:
            continue
        sizes = np.bincount(reference["labels"], minlength=k + 1)[1:]
        jaccard = np.asarray(collector.jaccard, dtype=float).reshape(-1, k)
        for cluster in range(k):
            middle, lower, upper = _quantiles(jaccard[:, cluster])
            clusters.append((k, cluster + 1, int(sizes[cluster]), middle, lower, upper, len(jaccard)))
        original = _original_centers(plan, reference["centers"])
        for cluster in range(k):
            for variable, name in enumerate(plan.names):
                centers.append((k, cluster + 1, name, float(original[cluster, variable]),
                                float(reference["centers"][cluster, variable])))

    summary_columns = ["k", *SUMMARY_COLUMNS, *(SEED_SUMMARY_COLUMNS if plan.seed_runs else ())]
    tables = {SUMMARY: pd.DataFrame(summary, columns=summary_columns).set_index("k"),
              SCORES: pd.DataFrame(scores, columns=SCORE_COLUMNS).astype({"ARI": float, "OOB ARI": float}),
              CLUSTERS: pd.DataFrame(clusters, columns=CLUSTER_COLUMNS)}
    report = collectors[plan.report_k]
    matrix = None
    if report.reference["status"] == OK:
        valid = len(report.ari)
        agreement = report.agree / valid if valid else np.full(plan.n, np.nan)
        # Indexed by the worksheet row, like Co-assignment: the view and the CSV show no second row number.
        tables[ASSIGNMENTS] = pd.DataFrame({ROW: plan.rows, "Reference cluster": report.reference["labels"],
                                            "Agreement": agreement, "Valid resamples": valid},
                                           columns=ASSIGNMENT_COLUMNS).set_index(ROW)
        if report.shared is not None and valid:
            matrix = report.shared / valid  # one division of the integer counts
            labels = [str(row) for row in plan.rows]
            tables[COASSIGN_SHEET] = pd.DataFrame(matrix, index=pd.Index(plan.rows, name=ROW), columns=labels)
    tables[CENTERS] = pd.DataFrame(centers, columns=CENTER_COLUMNS)
    if plan.seed_runs:
        tables[SEEDS] = pd.DataFrame(seeds, columns=SEED_COLUMNS).astype({"ARI": float})
    tables[SETTINGS] = _settings(plan, report, matrix is not None)
    return Result(tables, _figure(plan, tables[SUMMARY], matrix))


def _settings(plan, report, matrix):
    values = {VARIABLES: ", ".join(plan.names), MIN_K: plan.ks[0], MAX_K: plan.ks[-1],
              STANDARDIZE: plan.standardize, ALGORITHM: plan.settings[ALGORITHM]}
    if MAX_ITERATIONS in plan.settings:
        values[MAX_ITERATIONS] = plan.settings[MAX_ITERATIONS]
    values.update({SEED: plan.seed, RESAMPLES: plan.resamples, FRACTION: plan.fraction, SEED_RUNS: plan.seed_runs,
                   REPORT_K: plan.report_k, COASSIGNMENT: plan.coassignment,
                   "Worksheet rows": plan.worksheet_rows, "Complete rows (N)": plan.n,
                   "Incomplete rows": plan.worksheet_rows - plan.n, "Sample N": plan.sample,
                   "Sampling": SAMPLING, "Fit seeds": FIT_SEEDS, "Matching": MATCHING, "Percentiles": PERCENTILES,
                   "K-means fits": plan.fits, "Work units": plan.work, "Limits": LIMITS,
                   "Interpretation": INTERPRETATION})
    if plan.coassignment and not matrix:
        reason = report.reference["status"] if report.reference["status"] != OK else NO_VALID
        values["Co-assignment"] = f"Not available for k = {plan.report_k}: {reason}"
    return _report(values)


BLUE, ORANGE, GRAY = "#2f6db5", "#c2672b", "#8a94a3"


def _figure(plan, summary, matrix):
    figure = Figure(figsize=(11.5, 5) if matrix is not None else (8, 5), dpi=100, layout="constrained")
    if matrix is None:
        axes = figure.add_subplot()
    else:
        grid = figure.add_gridspec(1, 2, width_ratios=(1.2, 1))
        axes = figure.add_subplot(grid[0, 0])
    axes.set(title="K-means stability", xlabel="Number of clusters (k)", ylabel="Adjusted Rand index (ARI)")
    axes.spines[["right", "top"]].set_visible(False)
    ks = summary.index.to_numpy(dtype=float)
    median = summary["Median ARI"].to_numpy(dtype=float)
    low, high = summary["ARI p10"].to_numpy(dtype=float), summary["ARI p90"].to_numpy(dtype=float)
    present = np.isfinite(median)
    handles = []
    if present.any():
        band = axes.fill_between(ks, low, high, where=present, color=BLUE, alpha=.2, linewidth=0,
                                 label="Resampling p10–p90", gid="kstab-band")
        line, = axes.plot(ks, median, "o-", color=BLUE, label="Resampling median ARI", gid="kstab-median")
        handles += [line, band]
    if plan.seed_runs:
        seed = summary["Median seed-run ARI"].to_numpy(dtype=float)
        if np.isfinite(seed).any():
            line, = axes.plot(ks, seed, "s--", color=ORANGE, label="Seed-run median ARI", gid="kstab-seeds")
            handles.append(line)
    gaps = ks[~present]
    for k in gaps:  # no valid replicate: a hatched gap instead of an invented value
        axes.axvspan(k - .35, k + .35, facecolor="none", edgecolor=GRAY, hatch="//", linewidth=0, gid="kstab-gap")
    if len(gaps):
        handles.append(Patch(facecolor="none", edgecolor=GRAY, hatch="//", label="No valid resamples"))
    axes.set_xticks(ks)
    axes.set_xticklabels([str(int(k)) for k in ks])
    axes.set_xlim(ks[0] - .5, ks[-1] + .5)
    finite = np.concatenate([values[np.isfinite(values)] for values in (low, median)]) if present.any() else []
    bottom = min(0.0, float(np.min(finite))) if len(finite) else 0.0
    axes.set_ylim(bottom - .05, 1.05)
    if handles:
        axes.legend(handles=handles, loc="best", frameon=False)
    if matrix is not None:
        heat = figure.add_subplot(grid[0, 1])
        image = heat.imshow(matrix, vmin=0, vmax=1, cmap="viridis", interpolation="nearest", gid="kstab-coassignment")
        heat.set(title=f"Co-assignment, k = {plan.report_k}", xlabel=ROW, ylabel=ROW)
        count = len(plan.rows)
        step = max(1, int(np.ceil(count / 12)))
        ticks = np.arange(0, count, step)
        heat.set_xticks(ticks, [str(plan.rows[index]) for index in ticks], rotation=90 if count > 9 else 0)
        heat.set_yticks(ticks, [str(plan.rows[index]) for index in ticks])
        heat._tramastat_categorical_axes = ("x", "y")
        figure.colorbar(image, ax=heat, label="Share of valid resamples in the same cluster", shrink=.85)
    return figure
