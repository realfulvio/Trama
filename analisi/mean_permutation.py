"""Permutation test for the difference between two means, independent or paired, exact or Monte Carlo.

The estimate is always mean(First) − mean(Second); First decides the direction of the test.

* **Independent**: the values of First and then of Second, each in worksheet order, form one pooled sequence of
  N = N₁ + N₂ positions. Under the null hypothesis the values are exchangeable between the samples, so every way of
  giving N₁ of the positions to First (and the others to Second) is equally likely. Equal values at different
  positions are different assignments.
* **Paired**: the differences First − Second of the complete rows, in worksheet order. Under the null hypothesis
  the two labels are exchangeable within each pair, so each difference keeps its size and takes the sign − or +
  with equal probability. A zero difference also counts in both configurations.

Tails, with ties included: Greater counts statistics ≥ the observed one, Less ≤, Two-sided |statistic| ≥ |observed|
(not twice the smaller one-sided p). Exact: p = tail count / assignments, the observed assignment included.
Monte Carlo: p = (tail count + 1) / (resamples + 1); Draws reports the resamples evaluated, without the + 1.

Numerical rule. The independent values are centred on the lower median of the pooled sample (a data value, so the
subtraction is exact for values of similar size) and the paired differences are used as they are. Statistics are
computed from these centred values, and two statistics are treated as equal when they differ by at most
τ = 2⁻³⁶ · S, where S is the largest absolute centred value (independent) or the largest absolute paired difference.
τ is about 10⁴ times the worst rounding error of a mean of up to 50,000 values, it does not depend on a common offset
of the data (values shifted by 2⁴⁰ give the same distribution and the same counts), and statistics that differ
by less than 1.5·10⁻¹¹ · S are not resolved. Values far larger than their spread (an offset beyond about 10⁶ times
the spread) carry decimal rounding that the test cannot recover: subtract a reference value first.

Monte Carlo draws come from one ``numpy.random.Generator(PCG64(seed))``: an independent assignment is
``choice(N, N₁, replace=False)`` (the positions given to First), a paired one ``integers(0, 2, size=pairs,
dtype="int64")`` (0 = minus, 1 = plus). Each resample makes one such call, so more resamples with the same seed keep
the earlier statistics exactly. Exact enumeration lists the positions of the smaller sample (First when the sizes
are equal) in lexicographic order, or the signs in binary order with the first pair as the most significant digit and
minus before plus.

Budgets are checked with integer arithmetic before any allocation: Exact up to 200,000 assignments and 10 million
operations (assignments × values or pairs), Monte Carlo up to 50 million operations (resamples × values or pairs),
and at most 50,000 valid values or 25,000 pairs. Auto enumerates when both exact limits hold and simulates otherwise.
Only the data and the series of statistics are kept in memory.
"""
from itertools import chain, combinations, islice
from math import fsum, ldexp
from numbers import Integral, Real

import numpy as np
import pandas as pd

from . import parallel
from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled
from .reporting import Result, _plot

METHOD = "Permutation test for mean difference"
FIRST, SECOND, DESIGN, ALTERNATIVE, MODE = "First", "Second", "Design", "Alternative", "Method"
RESAMPLES, SEED, KEEP_DRAWS, SHOW_GRAPH = "Resamples", "Seed", "Keep draws", "Show graph"
INDEPENDENT, PAIRED = DESIGNS = ("Independent", "Paired")
TWO_SIDED, GREATER, LESS = ALTERNATIVES = ("Two-sided", "Greater", "Less")
AUTO, EXACT, MONTE_CARLO = MODES = ("Auto", "Exact", "Monte Carlo")
DEFAULT_RESAMPLES, MIN_RESAMPLES, MAX_RESAMPLES = 9_999, 199, 100_000
SEED_LIMIT = 2**64

# The first entry of a choice is its default.
OPTIONS = {FIRST: None, SECOND: None, DESIGN: DESIGNS, ALTERNATIVE: ALTERNATIVES, MODE: MODES,
           RESAMPLES: DEFAULT_RESAMPLES, SEED: 0, KEEP_DRAWS: False, SHOW_GRAPH: True}
DATA_FIELDS = (FIRST, SECOND, DESIGN)
TEST_FIELDS = (ALTERNATIVE, MODE, RESAMPLES, SEED, KEEP_DRAWS, SHOW_GRAPH)
SIMULATION_FIELDS = (RESAMPLES, SEED)

MAX_EXACT_ASSIGNMENTS = 200_000
MAX_EXACT_WORK = 10_000_000
MAX_SIMULATION_WORK = 50_000_000
MAX_VALUES, MAX_PAIRS = 50_000, 25_000
MIN_VALUES = 2
TIE_EXPONENT = -36
EXACT_INTEGER = 2**53
BLOCK_WORK = 1 << 18

RESULTS_SHEET, SETTINGS_SHEET, DRAWS_SHEET = "Permutation results", "Settings", "Null distribution"
RESULT_COLUMNS = ["N first", "N second", "Mean first", "Mean second", "Mean difference", "Alternative", "p",
                  "Tail count", "Draws", "Mode used"]
DRAW_COLUMNS = ["Draw", "Statistic"]

# Vector ids of the figure, kept in SVG exports.
OBSERVED_GID, MIRROR_GID, SUMMARY_GID, BIN_GID = (
    "permutation-observed", "permutation-mirror", "permutation-summary", "permutation-null-bin")
NULL_LABEL, OBSERVED_LABEL, MIRROR_LABEL = "Null distribution", "Observed difference", "Mirror of observed (two-sided)"

# Interface captions and choices. Recipes, sheets and columns keep the English names and values.
TAB_KEYS = {"Data": "perm.tab.data", "Test": "perm.tab.test"}
LABEL_KEYS = {FIRST: "perm.field.first", SECOND: "perm.field.second", DESIGN: "perm.field.design",
              ALTERNATIVE: "perm.field.alternative", MODE: "perm.field.method", RESAMPLES: "perm.field.resamples",
              SEED: "perm.field.seed", KEEP_DRAWS: "perm.field.keep", SHOW_GRAPH: "perm.field.graph"}
CHOICE_KEYS = {INDEPENDENT: "perm.choice.independent", PAIRED: "perm.choice.paired",
               TWO_SIDED: "perm.choice.two_sided", GREATER: "perm.choice.greater", LESS: "perm.choice.less",
               AUTO: "perm.choice.auto", EXACT: "perm.choice.exact", MONTE_CARLO: "perm.choice.monte_carlo"}
DESIGN_NOTE_KEYS = {INDEPENDENT: "perm.note.independent", PAIRED: "perm.note.paired"}
ERROR_PREFIX = "perm.error."

_EPS = np.finfo(float).eps


class PermutationCancelled(MonteCarloCancelled):
    """The enumeration or the simulation stopped between two blocks; nothing is published."""


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise PermutationCancelled("Permutation test cancelled.")


def cancellable(method, options):
    """Both modes run in blocks on the worker and stop between two blocks when cancelled."""
    return method == METHOD


def visibility(mode):
    """Resamples and Seed are used by Monte Carlo and possibly by Auto, never by Exact."""
    shown = mode != EXACT
    return dict.fromkeys(SIMULATION_FIELDS, shown)


def shows_graph(options):
    return isinstance(options, dict) and options.get(SHOW_GRAPH, True) is not False


# ----- options -------------------------------------------------------------------------------------------------------

def _choice(options, name, choices):
    value = options.get(name, choices[0])
    if not isinstance(value, str) or value not in choices:
        raise FieldError(name, f"{name}: choose one of the listed options.")
    return value


def _flag(options, name):
    value = options.get(name, OPTIONS[name])
    if not isinstance(value, (bool, np.bool_)):
        raise FieldError(name, f"{name}: choose on or off.")
    return bool(value)


def _whole(value):
    """An exact Python int, or None. Integral floats are accepted only below 2**53, where they are exact."""
    if isinstance(value, (bool, np.bool_)):
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and float(value).is_integer() \
            and abs(value) <= EXACT_INTEGER:
        return int(value)
    return None


def _resamples(options):
    value = _whole(options.get(RESAMPLES, DEFAULT_RESAMPLES))
    if value is None or not MIN_RESAMPLES <= value <= MAX_RESAMPLES:
        raise FieldError(RESAMPLES, "Resamples must be a whole number from 199 to 100,000.")
    return value


def _seed(options):
    raw = options.get(SEED, 0)
    # Seeds are saved exactly: floats are refused, whatever their value.
    value = int(raw) if isinstance(raw, Integral) and not isinstance(raw, (bool, np.bool_)) else None
    if value is None or not 0 <= value < SEED_LIMIT:
        raise FieldError(SEED, "Seed must be a whole number from 0 to 18446744073709551615.")
    return value


def _column(frame, options, field):
    name = options.get(field)
    if name is None or (isinstance(name, str) and not name.strip()):
        raise FieldError(field, f"Choose a column for {field}.")
    try:
        present = name in frame.columns
    except TypeError:
        present = False
    if not present:
        raise FieldError(field, f'Choose an existing column for {field}: "{name}" is not in the worksheet.')
    if isinstance(frame[name], pd.DataFrame):
        raise FieldError(field, f'Worksheet column names must be unique: "{name}" appears more than once.')
    return name


def settings(frame, options):
    """Validated options as a plain dict; raises FieldError naming the field to correct.

    Resamples and Seed are read only when Monte Carlo may run (Monte Carlo or Auto): Exact ignores them.
    """
    if not isinstance(options, dict):
        raise FieldError(FIRST, "Choose a column for First.")
    design = _choice(options, DESIGN, DESIGNS)
    alternative = _choice(options, ALTERNATIVE, ALTERNATIVES)
    mode = _choice(options, MODE, MODES)
    flags = {name: _flag(options, name) for name in (KEEP_DRAWS, SHOW_GRAPH)}
    resamples = seed = None
    if mode != EXACT:
        resamples, seed = _resamples(options), _seed(options)
    first = _column(frame, options, FIRST)
    second = _column(frame, options, SECOND)
    if second == first:
        raise FieldError(SECOND, "Second: choose a column different from First.")
    return {"design": design, "alternative": alternative, "mode": mode, "resamples": resamples, "seed": seed,
            "keep": flags[KEEP_DRAWS], "graph": flags[SHOW_GRAPH], "first": first, "second": second}


# ----- reading the worksheet -----------------------------------------------------------------------------------------

def _blank(raw):
    if raw is None:
        return True
    if isinstance(raw, str):
        return not raw.strip()
    try:
        return bool(pd.isna(raw))
    except (TypeError, ValueError):
        return False


def _shown(raw):
    text = raw.strip() if isinstance(raw, str) else repr(raw)
    return text if len(text) <= 40 else text[:37] + "..."


def _not_number(field, row, raw):
    return FieldError(field, f"{field}: source row {row} is not a number ({_shown(raw)}).")


def _not_finite(field, row):
    return FieldError(field, f"{field}: source row {row} must be a finite number.")


def _not_exact(field, row, raw):
    return FieldError(field, f"{field}: source row {row} ({_shown(raw)}) cannot be represented exactly; "
                             "use values within ±9007199254740992.")


def _cell(raw, field, row):
    """A finite float, NaN for a blank or excluded cell, or a FieldError naming the sample and the row."""
    if _blank(raw):
        return np.nan
    if isinstance(raw, str):
        text = raw.strip()
        try:
            value = float(text.replace(",", ".") if text.count(",") == 1 and "." not in text else text)
        except ValueError:
            raise _not_number(field, row, raw) from None
    elif isinstance(raw, (bool, np.bool_)) or not isinstance(raw, Real):
        raise _not_number(field, row, raw)
    elif isinstance(raw, Integral):
        if abs(int(raw)) > EXACT_INTEGER:
            raise _not_exact(field, row, raw)
        value = float(raw)
    else:
        try:
            value = float(raw)
        except (OverflowError, ValueError):
            raise _not_finite(field, row) from None
    if not np.isfinite(value):
        raise _not_finite(field, row)
    return value


def _numbers(series, field):
    """Floats in worksheet order, NaN for blank or excluded cells. Anything else raises on its source row."""
    dtype = series.dtype
    if pd.api.types.is_integer_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype):
        present = series.notna().to_numpy()
        if present.any():
            low, high = int(series.min()), int(series.max())
            if low < -EXACT_INTEGER or high > EXACT_INTEGER:
                for position in np.flatnonzero(present):
                    raw = series.iloc[position]
                    if abs(int(raw)) > EXACT_INTEGER:
                        raise _not_exact(field, position + 1, raw)
        return series.to_numpy(dtype=float, na_value=np.nan)
    if pd.api.types.is_float_dtype(dtype):
        values = series.to_numpy(dtype=float, na_value=np.nan)
        infinite = np.isinf(values)
        if infinite.any():
            raise _not_finite(field, int(np.argmax(infinite)) + 1)
        return values
    return np.array([_cell(raw, field, position + 1) for position, raw in enumerate(series.tolist())], dtype=float)


def read_samples(frame, chosen):
    """The two samples (or the complete pairs) and the omitted counts, checked against the size limits."""
    a = _numbers(frame[chosen["first"]], FIRST)
    b = _numbers(frame[chosen["second"]], SECOND)
    has_a, has_b = ~np.isnan(a), ~np.isnan(b)
    used = has_a | has_b
    if chosen["design"] == PAIRED:
        complete = has_a & has_b
        count = int(complete.sum())
        if count < MIN_VALUES:
            raise FieldError(FIRST, f"Paired design needs at least 2 complete pairs; {count} found.")
        if count > MAX_PAIRS:
            raise FieldError(FIRST, f"Paired design accepts up to 25,000 complete pairs; {count:,} found.")
        return {"first": a[complete], "second": b[complete], "incomplete": int((used & ~complete).sum())}
    first, second = a[has_a], b[has_b]
    for field, values in ((FIRST, first), (SECOND, second)):
        if len(values) < MIN_VALUES:
            raise FieldError(field, f"{field}: at least 2 values are needed; {len(values)} found.")
    total = len(first) + len(second)
    if total > MAX_VALUES:
        raise FieldError(FIRST, f"Independent design accepts up to 50,000 values in total; {total:,} found.")
    return {"first": first, "second": second, "missing_first": int((used & ~has_a).sum()),
            "missing_second": int((used & ~has_b).sum())}


# ----- size of the reference set and the budgets ---------------------------------------------------------------------

def capped_comb(n, k, cap):
    """C(n, k) with integer arithmetic, or cap + 1 as soon as it is known to exceed cap."""
    k = min(k, n - k)
    if k < 0:
        return 0
    value = 1
    for step in range(1, k + 1):
        # Every intermediate value C(n − k + step, step) is an integer.
        value = value * (n - k + step) // step
        if value > cap:
            return cap + 1
    return value


def assignment_count(design, n_first, n_second):
    """Exact number of assignments, capped at MAX_EXACT_ASSIGNMENTS + 1."""
    cap = MAX_EXACT_ASSIGNMENTS
    if design == PAIRED:
        return (1 << n_first) if n_first < 18 else cap + 1
    return capped_comb(n_first + n_second, n_first, cap)


def plan(chosen, sizes):
    """Mode used, number of assignments (exact) and the work of the chosen mode. Raises on a budget field."""
    design, mode = chosen["design"], chosen["mode"]
    units = sizes[0] if design == PAIRED else sizes[0] + sizes[1]
    count = assignment_count(design, *sizes)
    exact_ok = count <= MAX_EXACT_ASSIGNMENTS and count * units <= MAX_EXACT_WORK
    if mode == EXACT and not exact_ok:
        if count > MAX_EXACT_ASSIGNMENTS:
            raise FieldError(MODE, "Method: exact enumeration allows at most 200,000 assignments and these data "
                                   "have more. Choose Auto or Monte Carlo.")
        raise FieldError(MODE, f"Method: exact enumeration allows at most 10,000,000 operations (assignments × "
                               f"values) and these data need {count * units:,}. Choose Auto or Monte Carlo.")
    if mode == EXACT or (mode == AUTO and exact_ok):
        return {"used": EXACT, "assignments": count, "work": count * units, "units": units}
    work = chosen["resamples"] * units
    if work > MAX_SIMULATION_WORK:
        limit = MAX_SIMULATION_WORK // units
        raise FieldError(RESAMPLES, f"Resamples: Monte Carlo allows at most 50,000,000 operations (resamples × "
                                    f"values) and {chosen['resamples']:,} × {units:,} = {work:,}. "
                                    f"Use {limit:,} resamples or fewer.")
    return {"used": MONTE_CARLO, "assignments": None, "work": work, "units": units}


def _prepare(frame, options):
    chosen = settings(frame, options)
    samples = read_samples(frame, chosen)
    sizes = len(samples["first"]), len(samples["second"])
    return chosen, samples, plan(chosen, sizes)


def check_options(frame, options):
    """Every field, value and budget check without enumerating or simulating anything.

    The dialog calls it so that field errors keep the dialog open; the worker repeats the checks and runs the test.
    """
    chosen, samples, steps = _prepare(frame, options)
    _centred(chosen, samples)
    return chosen, steps


def preview(frame, options):
    """What Auto (or the chosen method) would do with the current dialog values, or None when they are incomplete."""
    try:
        chosen, steps = check_options(frame, options)
    except (FieldError, ValueError, TypeError, KeyError):
        return None
    return {"mode": chosen["mode"], "used": steps["used"], "assignments": steps["assignments"],
            "units": steps["units"]}


# ----- arithmetic ----------------------------------------------------------------------------------------------------

def _too_large(field):
    return FieldError(field, f"{field}: the values are too large in magnitude to be compared reliably.")


def _centred(chosen, samples):
    """Centred values, their scale and the tie tolerance. Overflow names the sample holding the largest value."""
    first, second = samples["first"], samples["second"]
    largest = FIRST if np.max(np.abs(first)) >= np.max(np.abs(second)) else SECOND
    with np.errstate(over="ignore", invalid="ignore"):
        if chosen["design"] == PAIRED:
            values = first - second
            centre = 0.0
        else:
            pooled = np.concatenate((first, second))
            centre = float(np.sort(pooled)[(len(pooled) - 1) // 2])
            values = pooled - centre
        scale = float(np.max(np.abs(values))) if len(values) else 0.0
        reach = scale * len(values)
    if not (np.isfinite(values).all() and np.isfinite(reach)):
        raise _too_large(largest)
    return values, centre, scale, ldexp(scale, TIE_EXPONENT)


def _in_tail(statistics, observed, alternative, tolerance):
    if alternative == GREATER:
        return statistics >= observed - tolerance
    if alternative == LESS:
        return statistics <= observed + tolerance
    return np.abs(statistics) >= abs(observed) - tolerance


class _Independent:
    """Statistics of the independent design from the sum of the smaller sample's centred values."""

    def __init__(self, values, n_first, n_second):
        self.values, self.n_first, self.n_second = values, n_first, n_second
        self.total = fsum(values)
        self.first_is_small = n_first <= n_second
        self.small = n_first if self.first_is_small else n_second

    def statistic(self, small_sum):
        if self.first_is_small:
            first, second = small_sum, self.total - small_sum
        else:
            first, second = self.total - small_sum, small_sum
        return first / self.n_first - second / self.n_second

    def exact(self, count, cancel):
        out = np.empty(count)
        positions = combinations(range(len(self.values)), self.small)
        block = max(1, BLOCK_WORK // self.small)
        done = 0
        while done < count:
            check_cancel(cancel)
            rows = min(block, count - done)
            chosen = np.fromiter(chain.from_iterable(islice(positions, rows)), dtype=np.intp,
                                 count=rows * self.small).reshape(rows, self.small)
            out[done:done + rows] = self.statistic(self.values[chosen].sum(axis=1))
            done += rows
        return out

    def simulate(self, resamples, seed, cancel):
        generator = np.random.Generator(np.random.PCG64(seed))
        size = len(self.values)
        out = np.empty(resamples)
        block = max(1, BLOCK_WORK // size)
        mask = np.ones(size, dtype=bool)
        for draw in range(resamples):
            if draw % block == 0:
                check_cancel(cancel)
            first = generator.choice(size, self.n_first, replace=False)
            if self.first_is_small:
                small_sum = self.values[first].sum()
            else:
                # The second sample is the smaller one: sum its own positions, never total − (larger sum).
                mask[first] = False
                small_sum = self.values[mask].sum()
                mask[first] = True
            out[draw] = self.statistic(small_sum)
        return out


class _Paired:
    """Statistics of the paired design: the mean of the signed differences."""

    def __init__(self, differences):
        self.values = differences

    def exact(self, cancel):
        sums = np.zeros(1)
        # The last pair is the least significant binary digit; minus (0) comes before plus (1).
        for value in self.values[::-1]:
            check_cancel(cancel)
            sums = np.concatenate((sums - value, sums + value))
        return sums / len(self.values)

    def simulate(self, resamples, seed, cancel):
        generator = np.random.Generator(np.random.PCG64(seed))
        count = len(self.values)
        block = max(1, BLOCK_WORK // count)
        processes = parallel.warm_process_count()
        if processes > 1 and count * resamples >= 10_000_000:
            jobs = []
            chunk = (resamples + 2 * processes - 1) // (2 * processes)
            for start in range(0, resamples, chunk):
                check_cancel(cancel)
                size = min(chunk, resamples - start)
                jobs.append((self.values, generator.bit_generator.state, size))
                if start + size < resamples:
                    for draw in range(0, size, block):
                        check_cancel(cancel)
                        # PCG64 carries a buffered word for these draws. Save
                        # the entire state at each shard's first replicate.
                        generator.integers(0, 2, size=(min(block, size - draw), count), dtype="int64")
            return np.concatenate(parallel.run_tasks(_paired_permutation_task, jobs, cancel=cancel,
                                                     with_cancel=True))

        return _paired_statistics(self.values, generator, resamples, cancel)


def _paired_permutation_task(item, cancel):
    values, state, resamples = item
    bitgen = np.random.PCG64()
    bitgen.state = state
    return _paired_statistics(values, np.random.Generator(bitgen), resamples, cancel)


def _paired_statistics(values, generator, resamples, cancel):
    count, out = len(values), np.empty(resamples)
    block = max(1, BLOCK_WORK // count)
    negated = -values
    for start in range(0, resamples, block):
        check_cancel(cancel)
        stop = min(start + block, resamples)
        signs = generator.integers(0, 2, size=(stop - start, count), dtype="int64")
        out[start:stop] = np.where(signs == 1, values, negated).sum(axis=1) / count
    check_cancel(cancel)
    return out


# ----- analysis ------------------------------------------------------------------------------------------------------

def null_distribution(chosen, samples, steps, cancel=None):
    """Observed statistic, null statistics in evaluation order, the tie tolerance and the centre."""
    values, centre, scale, tolerance = _centred(chosen, samples)
    if chosen["design"] == PAIRED:
        observed = fsum(values) / len(values)
        engine = _Paired(values)
        statistics = (engine.exact(cancel) if steps["used"] == EXACT
                      else engine.simulate(chosen["resamples"], chosen["seed"], cancel))
    else:
        n_first, n_second = len(samples["first"]), len(samples["second"])
        observed = fsum(values[:n_first]) / n_first - fsum(values[n_first:]) / n_second
        engine = _Independent(values, n_first, n_second)
        statistics = (engine.exact(steps["assignments"], cancel) if steps["used"] == EXACT
                      else engine.simulate(chosen["resamples"], chosen["seed"], cancel))
    check_cancel(cancel)
    return observed, statistics, tolerance, scale


def permutation_test(frame, options, *, cancel=None):
    chosen, samples, steps = _prepare(frame, options)
    observed, statistics, tolerance, scale = null_distribution(chosen, samples, steps, cancel)
    tail = int(np.count_nonzero(_in_tail(statistics, observed, chosen["alternative"], tolerance)))
    draws = len(statistics)
    exact = steps["used"] == EXACT
    p = tail / draws if exact else (tail + 1) / (draws + 1)
    first, second = samples["first"], samples["second"]
    results = pd.DataFrame([{
        "N first": len(first), "N second": len(second), "Mean first": fsum(first) / len(first),
        "Mean second": fsum(second) / len(second), "Mean difference": observed,
        "Alternative": chosen["alternative"], "p": p, "Tail count": tail, "Draws": draws,
        "Mode used": steps["used"]}], columns=RESULT_COLUMNS)
    tables = {RESULTS_SHEET: results, SETTINGS_SHEET: _settings_table(chosen, samples, steps, tolerance)}
    if chosen["keep"]:
        tables[DRAWS_SHEET] = pd.DataFrame({"Draw": np.arange(1, draws + 1), "Statistic": statistics},
                                           columns=DRAW_COLUMNS)
    figure = _figure(statistics, observed, p, tail, chosen, steps, tolerance) if chosen["graph"] else None
    check_cancel(cancel)
    return Result(tables, figure)


def _settings_table(chosen, samples, steps, tolerance):
    first, second = chosen["first"], chosen["second"]
    exact = steps["used"] == EXACT
    rows = {"First column": first, "Second column": second, "Design": chosen["design"],
            "Alternative": chosen["alternative"], "Method requested": chosen["mode"], "Method used": steps["used"],
            "Statistic": f"mean({first}) − mean({second})"}
    if chosen["design"] == PAIRED:
        rows["Null hypothesis"] = ("Labels exchangeable within each pair: every difference First − Second is "
                                   "equally likely to have either sign.")
        rows["Incomplete or excluded pairs omitted"] = samples["incomplete"]
    else:
        rows["Null hypothesis"] = ("Values exchangeable between the samples: every split of the pooled values "
                                   "into groups of N first and N second is equally likely.")
        rows["Missing or excluded cells, First"] = samples["missing_first"]
        rows["Missing or excluded cells, Second"] = samples["missing_second"]
    if exact:
        rows["Assignments enumerated"] = steps["assignments"]
        rows["p value"] = "Tail count / assignments; the observed assignment is included."
    else:
        rows["Resamples"] = chosen["resamples"]
        rows["Seed"] = str(chosen["seed"])  # text: exports keep all 64 bits
        rows["Random generator"] = "numpy Generator(PCG64(seed)), one call per resample"
        rows["Monte Carlo correction"] = "p = (tail count + 1) / (resamples + 1)"
    rows["Tail rule"] = {GREATER: "Statistic ≥ observed", LESS: "Statistic ≤ observed",
                         TWO_SIDED: "|Statistic| ≥ |observed|"}[chosen["alternative"]] + ", ties included"
    rows["Tie tolerance"] = tolerance
    rows["Interval"] = "None: the analysis tests the mean difference and gives no confidence interval."
    index = pd.Index(list(rows), name="Setting")
    return pd.DataFrame({"Value": pd.Series(list(rows.values()), index=index, dtype=object)}, index=index)


# ----- figure --------------------------------------------------------------------------------------------------------

def bin_edges(statistics, tolerance):
    """Histogram edges with positive width. A discrete distribution on a regular grid gets one bin per value."""
    low, high = float(np.min(statistics)), float(np.max(statistics))
    if high - low <= tolerance:
        half = .5 * max(abs(low), 1.0) if low != 0 else .5
        return np.array([low - half, high + half])
    unique = np.unique(statistics)
    if len(unique) <= 80:
        gaps = np.diff(unique)
        gaps = gaps[gaps > tolerance]
        step = float(gaps.min()) if gaps.size else 0.0
        ratio = gaps / step if step > 0 else gaps
        span = (high - low) / step if step > 0 else np.inf
        if span <= 120 and np.all(np.abs(ratio - np.round(ratio)) < 1e-6):
            count = int(round(span)) + 1
            return low - step / 2 + step * np.arange(count + 1)
    edges = np.histogram_bin_edges(statistics, bins="auto")
    return edges if len(edges) <= 81 else np.linspace(low, high, 81)


def _figure(statistics, observed, p, tail, chosen, steps, tolerance):
    first, second = chosen["first"], chosen["second"]
    exact = steps["used"] == EXACT
    figure, axes = _plot("Permutation null distribution", f"Mean difference ({first} − {second})", "Frequency")
    _, _, bars = axes.hist(statistics, bins=bin_edges(statistics, tolerance), color="#7aa6c2",
                           edgecolor="#2d5c7a", linewidth=.6, label=NULL_LABEL)
    for number, patch in enumerate(bars.patches, 1):
        patch.set_gid(f"{BIN_GID}-{number}")
    line = axes.axvline(observed, color="#b0413e", linestyle="--", linewidth=1.8, zorder=3, label=OBSERVED_LABEL)
    line.set_gid(OBSERVED_GID)
    mirror = None
    if chosen["alternative"] == TWO_SIDED and abs(observed) > tolerance:
        mirror = axes.axvline(-observed, color="#b0413e", linestyle=":", linewidth=1.3, zorder=3, label=MIRROR_LABEL)
        mirror.set_gid(MIRROR_GID)
    method = (f"Exact · {steps['assignments']:,} assignments" if exact
              else f"Monte Carlo · {chosen['resamples']:,} resamples · seed {chosen['seed']}")
    side = {TWO_SIDED: "two-sided", GREATER: "greater", LESS: "less"}[chosen["alternative"]]
    summary = axes.text(.02, .98, f"Observed = {observed:.6g}\np = {p:.4g} ({side}, {tail:,} in tail)\n{method}",
                        transform=axes.transAxes, ha="left", va="top", fontsize=9, color="#33414e", zorder=4)
    summary.set_gid(SUMMARY_GID)
    legend = axes.legend(loc="upper right", frameon=False, fontsize=8.5)
    for text in (axes.title, axes.xaxis.label, axes.yaxis.label, summary, *legend.get_texts()):
        text.set_parse_math(False)
    axes._tramastat_permutation = {"observed": line, "mirror": mirror, "bars": bars, "summary": summary}
    axes._tramastat_numeric_axes = ("x", "y")
    return figure
