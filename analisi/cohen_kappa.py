"""Cohen's kappa for two raters: categories, the agreement matrix, the kappa statistic and its bootstrap.

``check_options`` reads the recipe and the worksheet and builds the matrix of the complete pairs without any heavy
work, so the dialog can call it to keep a field error on its field; ``run`` adds the bootstrap and the sheets.

Categories. A rating is a category when it is text (kept exactly as written), a finite number or a logical value.
A row whose rating is missing (an empty cell, an excluded cell or blank text) leaves out the whole pair, counted once
in ``Incomplete pairs``. The categories are the union of the values seen in the complete pairs. Each category has a
label that names it in the sheets, the order editor and the figure: text is its own label, a whole number is written
without decimals (1), any other number in the shortest exact form (2.5, 1e+20), a logical value as True or False.
Text and numbers stay different categories, so the text "01" and the number 1 are distinct; two categories of
different types with the same label (the text "1" and the number 1) are refused instead of being merged.

Order. With ``Unweighted`` an empty order is automatic: numbers ascending, then False and True, then text by
case-insensitive comparison (ties by code point). Any explicit order, and every order with ``Linear`` or
``Quadratic`` weights, must list each observed category exactly once.

Statistic. With N pairs, nᵢⱼ the matrix of counts and wᵢⱼ the disagreement costs (0 on the diagonal and 1 elsewhere,
|i − j| for linear weights, (i − j)² for quadratic ones), kappa = 1 − N·Σwᵢⱼnᵢⱼ / Σwᵢⱼrᵢcⱼ, where rᵢ and cⱼ are
the row and column totals. Both sums are exact integers, so the point value is the correctly rounded quotient. When
the expected cost is zero (a single category) kappa is undefined.

Bootstrap. Each resample draws one multinomial table of N pairs from the observed joint frequencies taken in
row-major order, with a single ``Generator(PCG64(seed))`` and one ``multinomial`` call per resample; categories absent
from a resample keep their row and column. The percentile interval interpolates linearly over the resamples whose
kappa is defined, in exact fractions rounded once, and is left empty when fewer than 90% of the requested resamples
are valid.
"""
from dataclasses import dataclass, field
from fractions import Fraction
from numbers import Real

import numpy as np
import pandas as pd

from .cohen_kappa_text import MESSAGES
from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled

METHOD = "Cohen's kappa"
FIRST, SECOND, WEIGHTING, ORDER = "First rating", "Second rating", "Weighting", "Category order"
INTERVAL, LEVEL, RESAMPLES, SEED, SHOW_GRAPH = (
    "Confidence interval", "Confidence level (%)", "Resamples", "Seed", "Show graph")
UNWEIGHTED, LINEAR, QUADRATIC = WEIGHTINGS = ("Unweighted", "Linear", "Quadratic")
NO_INTERVAL, BOOTSTRAP = INTERVALS = ("None", "Bootstrap percentile")
BOOTSTRAP_FIELDS = (LEVEL, RESAMPLES, SEED)
DEFAULTS = {WEIGHTING: UNWEIGHTED, ORDER: [], INTERVAL: NO_INTERVAL, LEVEL: 95.0, RESAMPLES: 1999, SEED: 0,
            SHOW_GRAPH: True}

MIN_PAIRS, MAX_PAIRS, MAX_LEVELS = 2, 50_000, 20
MIN_RESAMPLES, MAX_RESAMPLES = 199, 20_000
SEED_LIMIT = 2 ** 64
VALID_SHARE = (9, 10)  # at least 9/10 of the requested resamples need a defined kappa
BLOCK = 250  # resamples drawn between two checks of the cancel request

AGREEMENT, COUNTS, EXPECTED, TOTALS, SETTINGS = (
    "Agreement", "Counts", "Expected counts", "Category totals", "Settings")
AGREEMENT_COLUMNS = ["Complete pairs", "Incomplete pairs", "Observed agreement", "Kappa", "CI lower", "CI upper",
                     "Valid resamples", "Status"]
OK, UNDEFINED, TOO_FEW = "OK", "Undefined kappa", "Too few valid resamples"
NUMBER, LOGICAL, TEXT = "number", "logical", "text"
_RANK = {NUMBER: 0, LOGICAL: 1, TEXT: 2}


class KappaCancelled(MonteCarloCancelled):
    """The bootstrap was cancelled before a result was published."""


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise KappaCancelled("Cohen's kappa calculation cancelled.")


def _error(field_name, key, **values):
    return FieldError(field_name, MESSAGES[key].format(**values))


# ----- category labels -------------------------------------------------------------------------------------------------

def number_label(value):
    """The label of a finite number: whole numbers without decimals, others in the shortest exact form."""
    value = float(value) + 0.0
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def label_of(key):
    kind, value = key
    if kind == NUMBER:
        return number_label(value)
    if kind == LOGICAL:
        return "True" if value else "False"
    return value


def sort_key(key):
    kind, value = key
    return (_RANK[kind], (value.casefold(), value) if kind == TEXT else (float(value), ""))


def _shown(value):
    """A rejected worksheet value as a short piece of text."""
    if isinstance(value, float) or isinstance(value, np.floating):
        return repr(float(value))
    text = str(value)
    return text if len(text) <= 60 else text[:59] + "…"


def _is_number(value):
    return isinstance(value, (Real, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_))


def _cell_key(value, column, row, field_name):
    if isinstance(value, (bool, np.bool_)):
        return LOGICAL, bool(value)
    if _is_number(value):
        number = float(value)
        if not np.isfinite(number):
            raise _error(field_name, "value", row=row, value=_shown(value), column=column)
        return NUMBER, number + 0.0
    if isinstance(value, str):
        return TEXT, value
    raise _error(field_name, "value_type", row=row, value=_shown(value), column=column)


def _missing(series):
    """Missing ratings: empty and excluded cells, NaN, and text made only of spaces."""
    mask = np.array(series.isna(), dtype=bool)
    if not (pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype)):
        values = series.to_numpy(dtype=object)
        mask |= np.fromiter((isinstance(v, str) and not v.strip() for v in values), dtype=bool, count=len(values))
    return mask


def _keys(series, rows, field_name):
    """The category key of each complete row (positions ``rows``), as a list of level ids and the levels."""
    column = series.name
    if pd.api.types.is_bool_dtype(series.dtype):
        flags = np.array([bool(v) for v in series.to_numpy(dtype=object)[rows]], dtype=bool)
        present, inverse = np.unique(flags, return_inverse=True)
        return inverse.astype(np.int64), [(LOGICAL, bool(flag)) for flag in present]
    if pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_complex_dtype(series.dtype):
        values = series.to_numpy(dtype=float, na_value=np.nan)[rows]
        bad = ~np.isfinite(values)
        if bad.any():
            position = int(np.flatnonzero(bad)[0])
            raise _error(field_name, "value", row=int(rows[position]) + 1, value=_shown(values[position]),
                         column=column)
        unique, inverse = np.unique(values, return_inverse=True)
        return inverse.astype(np.int64), [(NUMBER, float(u) + 0.0) for u in unique]
    values = series.to_numpy(dtype=object)[rows]
    ids, levels, positions = np.empty(len(values), dtype=np.int64), [], {}
    for index, value in enumerate(values):
        key = _cell_key(value, column, int(rows[index]) + 1, field_name)
        position = positions.get(key)
        if position is None:
            position = positions[key] = len(levels)
            levels.append(key)
        ids[index] = position
    return ids, levels


# ----- recipe ----------------------------------------------------------------------------------------------------------

def _finite_real(value):
    if not _is_number(value):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if np.isfinite(number) else None


def _whole(value):
    """An exact integer, or None: Python and NumPy integers, never booleans, floats or text."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        return None
    return int(value)


def read_order(value):
    """The explicit order as a list of labels; numbers and logical values are written as their labels."""
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise _error(ORDER, "order_list", field=ORDER)
    labels = []
    for position, item in enumerate(value, 1):
        if isinstance(item, str):
            labels.append(item)
        elif isinstance(item, (bool, np.bool_)):
            labels.append(label_of((LOGICAL, bool(item))))
        elif _finite_real(item) is not None:
            labels.append(number_label(item))
        else:
            raise _error(ORDER, "order_item", field=ORDER, position=position)
    return labels


class Settings:
    """The recipe read and checked, before any worksheet value is looked at (columns aside)."""

    def __init__(self, options):
        get = lambda key: options.get(key, DEFAULTS[key])  # noqa: E731
        self.first, self.second = options.get(FIRST), options.get(SECOND)
        self.weighting = self._choice(WEIGHTING, get(WEIGHTING), WEIGHTINGS)
        self.order = read_order(get(ORDER))
        self.interval = self._choice(INTERVAL, get(INTERVAL), INTERVALS)
        self.bootstrap = self.interval == BOOTSTRAP
        self.level = self.resamples = self.seed = None
        if self.bootstrap:
            # Hidden while the interval is off: never read then, so the recipe may keep any value there.
            self.level = self._level(get(LEVEL))
            self.resamples = self._resamples(get(RESAMPLES))
            self.seed = self._seed(get(SEED))
        show = get(SHOW_GRAPH)
        if not isinstance(show, (bool, np.bool_)):
            raise _error(SHOW_GRAPH, "flag", field=SHOW_GRAPH)
        self.show_graph = bool(show)

    @staticmethod
    def _choice(name, value, choices):
        if not isinstance(value, str) or value not in choices:
            raise _error(name, "choice", field=name)
        return value

    @staticmethod
    def _level(value):
        number = _finite_real(value)
        if number is None or not 0 < number < 100:
            raise _error(LEVEL, "level", field=LEVEL)
        return number

    @staticmethod
    def _resamples(value):
        number = _whole(value)
        if number is None or not MIN_RESAMPLES <= number <= MAX_RESAMPLES:
            raise _error(RESAMPLES, "whole", field=RESAMPLES, low=MIN_RESAMPLES, high=f"{MAX_RESAMPLES:,}")
        return number

    @staticmethod
    def _seed(value):
        number = _whole(value)
        if number is None or not 0 <= number < SEED_LIMIT:
            raise _error(SEED, "whole", field=SEED, low=0, high=SEED_LIMIT - 1)
        return number


def _columns(frame, first, second):
    if not frame.columns.is_unique:
        raise _error(FIRST, "unique")
    for name, column in ((FIRST, first), (SECOND, second)):
        if not isinstance(column, str) or not column:
            raise _error(name, "choose", field=name)
        if column not in frame.columns:
            raise _error(name, "exists", field=name, name=column)
    if first == second:
        raise _error(SECOND, "same", first=FIRST, field=SECOND)


# ----- the matrix of the complete pairs --------------------------------------------------------------------------------

@dataclass
class Plan:
    settings: Settings
    labels: list
    explicit: bool
    counts: np.ndarray
    complete: int
    incomplete: int
    rows: np.ndarray = field(repr=False)

    @property
    def size(self):
        return len(self.labels)


def _names(labels, limit=6):
    shown = ", ".join(f'"{name}"' for name in labels[:limit])
    return shown + (f" and {len(labels) - limit} more" if len(labels) > limit else "")


def _collision(levels_by_label, key, field_name):
    other = levels_by_label[label_of(key)]
    text = key if key[0] == TEXT else other
    rest = other if key[0] == TEXT else key
    message = "collision_number" if rest[0] == NUMBER else "collision_logical"
    return _error(field_name, message, text=text[1])


def _union(first_levels, second_levels):
    """Merge the levels of both columns; refuse two keys of different types that share a label."""
    by_label, merged = {}, {}
    sources = {}
    for name, levels in ((FIRST, first_levels), (SECOND, second_levels)):
        for key in levels:
            sources.setdefault(key, set()).add(name)
    for key in sorted(sources, key=sort_key):
        text = label_of(key)
        if text in by_label and by_label[text] != key:
            other = by_label[text]
            # Both types inside the first column name it; otherwise the second column is the one to fix.
            raise _collision(by_label, key, FIRST if FIRST in sources[key] & sources[other] else SECOND)
        by_label[text] = key
        merged[key] = text
    return merged


def _resolve_order(settings, automatic):
    if not settings.order:
        if settings.weighting != UNWEIGHTED:
            raise _error(ORDER, "order_needed", field=ORDER, weighting=settings.weighting)
        return list(automatic), False
    seen = set()
    for name in settings.order:
        if name in seen:
            raise _error(ORDER, "order_repeat", field=ORDER, name=name)
        seen.add(name)
    observed = set(automatic)
    for name in settings.order:
        if name not in observed:
            raise _error(ORDER, "order_unknown", field=ORDER, name=name)
    missing = [name for name in automatic if name not in seen]
    if missing:
        raise _error(ORDER, "order_missing", field=ORDER, names=_names(missing))
    return list(settings.order), True


def observed_categories(frame, first, second):
    """Labels of the categories of the complete pairs in automatic order; raises FieldError like the analysis."""
    _columns(frame, first, second)
    rows, _ = _complete_rows(frame, first, second)
    if len(rows) > MAX_PAIRS:
        raise _error(FIRST, "pairs_many", limit=f"{MAX_PAIRS:,}", count=f"{len(rows):,}")
    _, first_levels = _keys(frame[first], rows, FIRST)
    _, second_levels = _keys(frame[second], rows, SECOND)
    return list(_union(first_levels, second_levels).values())


def _complete_rows(frame, first, second):
    missing = _missing(frame[first]) | _missing(frame[second])
    return np.flatnonzero(~missing), int(missing.sum())


def check_options(frame, options):
    """Every value, role, category and budget that can be checked without the bootstrap; raises FieldError."""
    if not isinstance(options, dict):
        options = {}
    first, second = options.get(FIRST), options.get(SECOND)
    _columns(frame, first, second)
    settings = Settings(options)
    rows, incomplete = _complete_rows(frame, first, second)
    complete = len(rows)
    if complete > MAX_PAIRS:
        raise _error(FIRST, "pairs_many", limit=f"{MAX_PAIRS:,}", count=f"{complete:,}")
    if complete < MIN_PAIRS:
        raise _error(FIRST, "pairs_few", minimum=MIN_PAIRS, count=complete)
    first_ids, first_levels = _keys(frame[first], rows, FIRST)
    second_ids, second_levels = _keys(frame[second], rows, SECOND)
    merged = _union(first_levels, second_levels)
    if len(merged) > MAX_LEVELS:
        raise _error(FIRST, "levels_many", limit=MAX_LEVELS, count=f"{len(merged):,}")
    labels, explicit = _resolve_order(settings, list(merged.values()))
    position = {name: index for index, name in enumerate(labels)}
    first_map = np.array([position[merged[key]] for key in first_levels], dtype=np.int64)
    second_map = np.array([position[merged[key]] for key in second_levels], dtype=np.int64)
    size = len(labels)
    counts = np.bincount(first_map[first_ids] * size + second_map[second_ids], minlength=size * size)
    return Plan(settings, labels, explicit, counts.reshape(size, size).astype(np.int64), complete, incomplete, rows)


# ----- statistic -------------------------------------------------------------------------------------------------------

def costs(size, weighting):
    """Integer disagreement costs: 0 on the diagonal, 1, |i − j| or (i − j)² elsewhere."""
    distance = np.abs(np.subtract.outer(np.arange(size), np.arange(size))).astype(np.int64)
    if weighting == UNWEIGHTED:
        return (distance > 0).astype(np.int64)
    return distance if weighting == LINEAR else distance * distance


def kappa(counts, weights):
    """Kappa of a matrix of counts, or NaN when the expected cost is zero. Exact integer sums, one rounding."""
    counts = np.asarray(counts, dtype=np.int64)
    n = int(counts.sum())
    observed = int((weights * counts).sum())
    expected = int(counts.sum(axis=1) @ weights @ counts.sum(axis=0))
    if expected == 0:
        return float("nan")
    return (expected - n * observed) / expected


def bootstrap(counts, weights, resamples, seed, cancel=None):
    """Kappa of ``resamples`` multinomial tables of N pairs as exact fractions, drawn in blocks.

    Returns the integer numerators and denominators: kappa = numerator / denominator, undefined where the
    denominator (the expected cost times N) is zero.
    """
    counts = np.asarray(counts, dtype=np.int64)
    size, n = counts.shape[0], int(counts.sum())
    probabilities = counts.ravel() / n
    generator = np.random.Generator(np.random.PCG64(seed))
    numerators = np.zeros(resamples, dtype=np.int64)
    denominators = np.zeros(resamples, dtype=np.int64)
    for start in range(0, resamples, BLOCK):
        check_cancel(cancel)
        stop = min(resamples, start + BLOCK)
        draws = np.empty((stop - start, size * size), dtype=np.int64)
        for row in range(stop - start):
            draws[row] = generator.multinomial(n, probabilities)
        tables = draws.reshape(-1, size, size)
        observed = np.einsum("bij,ij->b", tables, weights)
        expected = np.einsum("bi,ij,bj->b", tables.sum(axis=2), weights, tables.sum(axis=1))
        numerators[start:stop] = expected - n * observed
        denominators[start:stop] = expected
    check_cancel(cancel)
    return numerators, denominators


def _order_statistic(approx, order, numerators, denominators, rank):
    """The exact value of rank ``rank`` (from 0); the floats only decide between values that round alike."""
    start, stop = np.searchsorted(approx, approx[rank], "left"), np.searchsorted(approx, approx[rank], "right")
    tied = sorted(Fraction(int(numerators[i]), int(denominators[i])) for i in order[start:stop])
    return tied[rank - start]


def percentile_interval(numerators, denominators, level, requested):
    """Two-sided percentile interval with linear interpolation over the defined values; None when too few.

    The interpolation is exact (the kappas are fractions of integers) and each bound is rounded once, so the
    interval does not depend on the floating-point order of the sums.
    """
    numerators, denominators = np.asarray(numerators), np.asarray(denominators)
    defined = denominators > 0
    valid = int(defined.sum())
    if not valid or valid * VALID_SHARE[1] < requested * VALID_SHARE[0]:
        return None, valid
    numerators, denominators = numerators[defined], denominators[defined]
    approx = numerators / denominators  # correctly rounded: both integers are below 2**53
    order = np.argsort(approx, kind="stable")
    approx = approx[order]
    alpha = (100 - Fraction(level)) / 200
    bounds = []
    for share in (alpha, 1 - alpha):
        position = (valid - 1) * share
        low = int(position)
        high = min(low + 1, valid - 1)
        below = _order_statistic(approx, order, numerators, denominators, low)
        above = _order_statistic(approx, order, numerators, denominators, high) if high != low else below
        bounds.append(float(below + (position - low) * (above - below)))
    return (bounds[0], bounds[1]), valid


# ----- sheets ----------------------------------------------------------------------------------------------------------

COSTS_TEXT = {
    UNWEIGHTED: "0 on the diagonal, 1 elsewhere",
    LINEAR: "|i − j|, the distance between the positions of the two categories in the order",
    QUADRATIC: "(i − j)², the squared distance between the positions of the two categories in the order",
}


def settings_table(plan):
    s = plan.settings
    rows = [("First rating", s.first), ("Second rating", s.second), ("Matrix orientation",
            "Rows are the first rating, columns the second rating"), ("Weighting", s.weighting),
            ("Disagreement costs", COSTS_TEXT[s.weighting]),
            ("Category order", "Explicit" if plan.explicit else
             "Automatic: numbers ascending, then False and True, then text ignoring case")]
    rows += [(f"Category {index}", name) for index, name in enumerate(plan.labels, 1)]
    rows += [
        ("Complete pairs", plan.complete), ("Incomplete pairs", plan.incomplete),
        ("Missing ratings", "A row with an empty, excluded or blank rating is left out and counted once."),
        ("Category labels", "Text is kept as written. A whole number is written without decimals (1), any other "
                            "finite number in its shortest exact form (2.5, 1e+20), a logical value as True or "
                            "False. Text and numbers are different categories; two categories with the same label "
                            "are refused."),
        ("Kappa", "1 − observed cost / expected cost. Expected counts are row total × column total / N. Kappa is "
                  "undefined when the expected cost is zero."),
        ("Confidence interval", s.interval),
    ]
    if s.bootstrap:
        rows += [
            ("Confidence level (%)", s.level), ("Resamples", s.resamples), ("Seed", s.seed),
            ("Bootstrap method", "Whole pairs: one multinomial table of N pairs per resample from the observed "
                                 "joint frequencies in row-major order, drawn by Generator(PCG64(seed)). Two-sided "
                                 "percentile interval with linear interpolation over the resamples with a defined "
                                 "kappa; empty when fewer than 90% of the resamples are valid."),
        ]
    rows.append(("Not included", "Fleiss kappa and more than two raters, intraclass correlation, p values and "
                                 "arbitrary distances between categories."))
    values = np.empty(len(rows), dtype=object)
    values[:] = [value for _, value in rows]
    return pd.DataFrame({"Value": values}, index=pd.Index([name for name, _ in rows], name="Setting", dtype=object))


def tables(plan, point, interval, valid):
    s = plan.settings
    counts = plan.counts
    n = plan.complete
    index = pd.Index(plan.labels, name=s.first, dtype=object)
    columns = pd.Index(plan.labels, name=s.second, dtype=object)
    rows, cols = counts.sum(axis=1), counts.sum(axis=0)
    if np.isnan(point):
        status = UNDEFINED
    elif s.bootstrap and interval is None:
        status = TOO_FEW
    else:
        status = OK
    agreement = pd.DataFrame({
        "Complete pairs": [n], "Incomplete pairs": [plan.incomplete],
        "Observed agreement": [int(np.trace(counts)) / n], "Kappa": [point],
        "CI lower": [interval[0] if interval else np.nan], "CI upper": [interval[1] if interval else np.nan],
        "Valid resamples": [float(valid) if valid is not None else np.nan], "Status": np.array([status], dtype=object),
    }, index=pd.Index([f"{s.first} × {s.second}"], name="Ratings", dtype=object))[AGREEMENT_COLUMNS]
    return {
        AGREEMENT: agreement,
        COUNTS: pd.DataFrame(counts.copy(), index=index, columns=columns),
        EXPECTED: pd.DataFrame(np.outer(rows, cols) / n, index=index.copy(), columns=columns.copy()),
        TOTALS: pd.DataFrame({s.first: rows.astype(np.int64), s.second: cols.astype(np.int64)},
                             index=pd.Index(plan.labels, name="Category", dtype=object)),
        SETTINGS: settings_table(plan),
    }


def run(frame, options, cancel=None):
    """Check, calculate and report: the sheets and the plan (for the figure)."""
    plan = check_options(frame, options)
    weights = costs(plan.size, plan.settings.weighting)
    point = kappa(plan.counts, weights)
    interval = valid = None
    if plan.settings.bootstrap and not np.isnan(point):
        numerators, denominators = bootstrap(plan.counts, weights, plan.settings.resamples, plan.settings.seed,
                                             cancel)
        interval, valid = percentile_interval(numerators, denominators, plan.settings.level,
                                              plan.settings.resamples)
    check_cancel(cancel)
    return tables(plan, point, interval, valid), plan, point
