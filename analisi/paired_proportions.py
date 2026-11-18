"""Paired proportions: McNemar's test and the conditional matched odds ratio for a binary outcome recorded twice.

Both ways of entering the data end in the 2 × 2 matrix ``[[a, b], [c, d]]`` of pairs:

* a  unchanged negative (negative before, negative after)
* b  gain (negative before, positive after)
* c  loss (positive before, negative after)
* d  unchanged positive

With N = a + b + c + d the report shows three separate things.

* The marginal difference (b − c) / N, the positive fraction after minus the positive fraction before.
  It has no interval here.
* McNemar's test on the D = b + c discordant pairs. Under H0 the gains B follow Binomial(D, 1/2) and the tail is
  taken at m = min(b, c): Exact p = min(1, 2·P(B ≤ m)), Mid-p = min(1, 2·P(B ≤ m) − P(B = m)), or the chi-square
  max(|b − c| − 1, 0)² / D with one degree of freedom (continuity correction).
* The conditional matched odds ratio b / c with the central Clopper–Pearson interval of b out of D, written
  q / (1 − q). It does not depend on the test chosen. No 0.5 correction is ever applied: with no losses the ratio
  is +∞ and with no gains it is 0.

Counts stay Python integers until the last step, so a total of 10 000 000 pairs is checked exactly. The module
never mutates the worksheet and keeps the position of every pair (``Source row``, 1-based, before any filter).
"""
from decimal import Decimal, InvalidOperation
from math import inf
from numbers import Integral, Real
import re

import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator
from scipy import stats

from .category_graphs import COLORS
from .contingency import COUNT_MATRIX, OBSERVATIONS, _whole_count, default_count_matrix
from .data import decimal_comma
from .field_error import FieldError
from .processing import TEXT
from .reporting import Result, _plot, _report

PAIRED_PROPORTIONS = "Paired proportions"
FORMAT, BEFORE, AFTER = "Input format", "Before", "After"
NEGATIVE, POSITIVE = "Negative value", "Positive value"
AFTER_NEGATIVE, AFTER_POSITIVE = "After negative counts", "After positive counts"
TEST, LEVEL, GRAPH = "Test", "Confidence level (%)", "Graph"
EXACT, MID_P, CHI_SQUARE = "Exact", "Mid-p", "Chi-square with continuity correction"
TESTS = (EXACT, MID_P, CHI_SQUARE)
FORMATS = (OBSERVATIONS, COUNT_MATRIX)

# The first entry of a choice is its default. Observations and Exact keep the recipe short.
OPTIONS = {FORMAT: FORMATS, BEFORE: None, AFTER: None, NEGATIVE: TEXT, POSITIVE: TEXT, AFTER_NEGATIVE: None,
           AFTER_POSITIVE: None, TEST: TESTS, LEVEL: 95.0, GRAPH: False}
DATA_FIELDS = (FORMAT, BEFORE, AFTER, NEGATIVE, POSITIVE, AFTER_NEGATIVE, AFTER_POSITIVE)
OBSERVATION_FIELDS = (BEFORE, AFTER, NEGATIVE, POSITIVE)
MATRIX_FIELDS = (AFTER_NEGATIVE, AFTER_POSITIVE)
DEFAULT_CODES = {NEGATIVE: "0", POSITIVE: "1"}

COUNTS_SHEET, REPORT_SHEET, PAIRS_SHEET = "Paired counts", "Paired proportions", "Pairs"
ROW_LABELS = ("Before negative", "Before positive")
COLUMN_LABELS = ("After negative", "After positive")
TRANSITIONS = ("Unchanged negative", "Gain", "Loss", "Unchanged positive")
TRANSITION_IDS = ("unchanged-negative", "gain", "loss", "unchanged-positive")
GID = "paired:"
MAX_TOTAL = 10_000_000
CI_METHOD = "Clopper–Pearson exact (conditional), central"

# Interface captions and choices; recipes keep the English names and values.
TAB_KEYS = {"Data": "paired.tab.data", "Test and graph": "paired.tab.test"}
LABEL_KEYS = {FORMAT: "paired.field.format", BEFORE: "paired.field.before", AFTER: "paired.field.after",
              NEGATIVE: "paired.field.negative", POSITIVE: "paired.field.positive",
              AFTER_NEGATIVE: "paired.field.after_negative", AFTER_POSITIVE: "paired.field.after_positive",
              TEST: "paired.field.test", LEVEL: "paired.field.level", GRAPH: "paired.field.graph"}
CHOICE_KEYS = {OBSERVATIONS: "paired.choice.observations", COUNT_MATRIX: "paired.choice.count_matrix",
               EXACT: "paired.choice.exact", MID_P: "paired.choice.mid_p", CHI_SQUARE: "paired.choice.chi_square"}
ERROR_PREFIX = "paired.error."


def visibility(input_format):
    """Fields that apply to the input format; the others are inactive, never validated and never saved."""
    observations = input_format != COUNT_MATRIX
    return {BEFORE: observations, AFTER: observations, NEGATIVE: observations, POSITIVE: observations,
            AFTER_NEGATIVE: not observations, AFTER_POSITIVE: not observations}


def defaults(frame):
    """Columns the dialog proposes for a worksheet: the first two columns, or the first two numeric ones for counts."""
    columns = [str(name) for name in frame.columns]
    numeric = [str(name) for name in frame.select_dtypes(include="number").columns]
    counts = (numeric if len(numeric) >= 2 else columns)[:2]
    proposal = {FORMAT: COUNT_MATRIX if default_count_matrix(frame) else OBSERVATIONS}
    if len(columns) >= 2:
        proposal.update({BEFORE: columns[0], AFTER: columns[1]})
    if len(counts) == 2:
        proposal.update({AFTER_NEGATIVE: counts[0], AFTER_POSITIVE: counts[1]})
    return proposal


# ----- statistics ----------------------------------------------------------------------------------------------------

def mcnemar_summary(a, b, c, d, test, level):
    """McNemar's test and the conditional odds ratio from the four counts of pairs.

    ``chi_square``, ``odds_ratio``, ``or_lower`` and ``or_upper`` are ``None`` when they do not exist; ``reason``
    then says why. The odds ratio is ``inf`` with no losses and ``0.0`` with no gains.
    """
    a, b, c, d = (int(value) for value in (a, b, c, d))
    n, discordant = a + b + c + d, b + c
    result = {"n": n, "before": (c + d) / n, "after": (b + d) / n, "difference": (b - c) / n,
              "discordant": discordant, "chi_square": None, "p": 1.0, "odds_ratio": None, "or_lower": None,
              "or_upper": None, "reason": ""}
    if discordant == 0:
        result["reason"] = "No discordant pairs."
        return result
    small = min(b, c)
    if test == CHI_SQUARE:
        statistic = max(abs(b - c) - 1, 0) ** 2 / discordant
        result["chi_square"] = statistic
        p = float(stats.chi2.sf(statistic, 1))
    elif b == c:
        p = 1.0
    elif test == EXACT:
        p = 2.0 * float(stats.binom.cdf(small, discordant, 0.5))
    else:
        # 2·P(B ≤ m) − P(B = m) written as P(B ≤ m) + P(B ≤ m − 1): no subtraction of nearly equal numbers.
        p = float(stats.binom.cdf(small, discordant, 0.5)) + float(stats.binom.cdf(small - 1, discordant, 0.5))
    result["p"] = min(1.0, max(0.0, p))
    tail = (100.0 - level) / 200.0
    # Clopper–Pearson limits of b out of b + c as odds q / (1 − q); 1 − q comes from the opposite tail of the
    # complementary beta law, so the limits stay exact next to 0 and 1 and swap reciprocally with Before and After.
    lower = stats.beta.ppf(tail, b, c + 1) / stats.beta.isf(tail, c + 1, b) if b else 0.0
    upper = stats.beta.isf(tail, b + 1, c) / stats.beta.ppf(tail, c, b + 1) if c else inf
    result.update(odds_ratio=inf if c == 0 else b / c, or_lower=float(lower), or_upper=float(upper))
    return result


# ----- options -------------------------------------------------------------------------------------------------------

def _choice(options, field, choices, message):
    value = options.get(field, choices[0])
    if not isinstance(value, str) or value not in choices:
        raise FieldError(field, message)
    return value


def _settings(options):
    input_format = _choice(options, FORMAT, FORMATS, "Input format: choose Observations or Count matrix.")
    test = _choice(options, TEST, TESTS, "Test: choose Exact, Mid-p or Chi-square with continuity correction.")
    level = options.get(LEVEL, 95.0)
    if (isinstance(level, (bool, np.bool_)) or not isinstance(level, Real) or not np.isfinite(float(level))
            or not 0 < float(level) < 100):
        raise FieldError(LEVEL, "Confidence level (%) must be a number greater than 0 and less than 100.")
    graph = options.get(GRAPH, False)
    if not isinstance(graph, (bool, np.bool_)):
        raise FieldError(GRAPH, "Graph must be on or off.")
    return input_format, test, float(level), bool(graph)


# ----- cells ---------------------------------------------------------------------------------------------------------

_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _missing(cell):
    if isinstance(cell, str):
        return not cell.strip()
    try:
        return bool(pd.isna(cell))
    except (TypeError, ValueError):
        return False


def _number(cell):
    """The finite Decimal a cell or a text stands for; ``None`` for text, Booleans and non-finite numbers."""
    if isinstance(cell, (bool, np.bool_)):
        return None
    if isinstance(cell, str):
        text = decimal_comma(cell.strip())
        if not _NUMBER.fullmatch(text):
            return None
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None
    elif isinstance(cell, Integral):
        number = Decimal(int(cell))
    elif isinstance(cell, Real):
        number = Decimal(repr(float(cell)))
    else:
        return None
    return number if number.is_finite() else None


def _code(options, field):
    """The literal code of the recipe and the number it stands for (``None`` for a text code)."""
    value = options.get(field, DEFAULT_CODES[field])
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (str, Real)):
        raise FieldError(POSITIVE, f"Enter {field} as text or as a number.")
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, Integral):
        text = str(int(value))
    else:
        text = repr(float(value))
    if not text:
        raise FieldError(POSITIVE, f"Enter a code for {field}.")
    return text, _number(text)


def _same_code(negative, positive):
    (text_n, number_n), (text_p, number_p) = negative, positive
    if number_n is not None and number_p is not None:
        return number_n == number_p
    return number_n is None and number_p is None and text_n == text_p


def _matches(cell, code):
    text, number = code
    if number is not None:
        value = _number(cell)
        return value is not None and value == number
    return isinstance(cell, str) and cell.strip() == text


def _column(frame, name, field):
    if not isinstance(name, str) or not name:
        raise FieldError(field, f"Choose a column for {field}.")
    if name not in frame:
        raise FieldError(field, f'Choose an existing column for {field}: "{name}" is not in the worksheet.')
    column = frame[name]
    if isinstance(column, pd.DataFrame):
        raise FieldError(field, "Worksheet column names must be unique.")
    return column.to_numpy(dtype=object)


def _shown(cell):
    text = str(cell)
    return text if len(text) <= 40 else text[:37] + "..."


# ----- data ----------------------------------------------------------------------------------------------------------

def _observations(frame, options):
    """Counts and the Pairs table from one pair per row; incomplete pairs are discarded as a whole."""
    before, after = options.get(BEFORE), options.get(AFTER)
    first = _column(frame, before, BEFORE)
    if isinstance(after, str) and after and after == before:
        raise FieldError(AFTER, "Choose different columns for Before and After.")
    second = _column(frame, after, AFTER)
    negative, positive = _code(options, NEGATIVE), _code(options, POSITIVE)
    if _same_code(negative, positive):
        raise FieldError(POSITIVE, f'{NEGATIVE} and {POSITIVE} must be different: "{negative[0]}" and '
                                   f'"{positive[0]}" are the same code.')
    complete = [i for i in range(len(first)) if not _missing(first[i]) and not _missing(second[i])]
    if not complete:
        raise FieldError(BEFORE, "No complete pair of Before and After values was found.")
    memo = {}

    def classify(cells, name, field):
        coded = []
        for row in complete:
            cell = cells[row]
            if isinstance(cell, (bool, np.bool_)):
                raise FieldError(field, f'Column "{name}" holds a Boolean value in source row {row + 1}; '
                                        "use text or numeric codes.")
            try:
                code = memo[type(cell), cell]
            except KeyError:
                code = memo[type(cell), cell] = _state(cell, negative, positive)
            except TypeError:  # an unhashable cell is never cached
                code = _state(cell, negative, positive)
            if code is None:
                raise FieldError(field, f'Column "{name}" holds "{_shown(cell)}" in source row {row + 1}, which is '
                                        f'neither the negative code "{negative[0]}" nor the positive code '
                                        f'"{positive[0]}".')
            coded.append(code)
        return coded

    codes_before = classify(first, before, BEFORE)
    codes_after = classify(second, after, AFTER)
    counts = [0, 0, 0, 0]
    transitions = []
    for was, now in zip(codes_before, codes_after):
        index = 2 * was + now
        # Index 0 unchanged negative, 1 gain, 2 loss, 3 unchanged positive: (was, now) is (0,0), (0,1), (1,0), (1,1).
        counts[index] += 1
        transitions.append(TRANSITIONS[index])
    pairs = pd.DataFrame({"Source row": [row + 1 for row in complete],
                          "Before": [first[row] for row in complete], "After": [second[row] for row in complete],
                          "Transition": transitions})
    return counts, pairs, len(first) - len(complete)


def _state(cell, negative, positive):
    if _matches(cell, negative):
        return 0
    if _matches(cell, positive):
        return 1
    return None


def _count_matrix(frame, options):
    """Counts from a summarised 2 × 2: two rows (Before negative, Before positive) and two After columns."""
    names = options.get(AFTER_NEGATIVE), options.get(AFTER_POSITIVE)
    first = _column(frame, names[0], AFTER_NEGATIVE)
    if isinstance(names[1], str) and names[1] and names[1] == names[0]:
        raise FieldError(AFTER_POSITIVE, "Choose different columns for After negative counts and After positive counts.")
    second = _column(frame, names[1], AFTER_POSITIVE)
    if len(first) < 2:
        raise FieldError(AFTER_NEGATIVE, "The count matrix needs two rows: Before negative and Before positive.")
    for field, name, cells in ((AFTER_NEGATIVE, names[0], first), (AFTER_POSITIVE, names[1], second)):
        for row in range(2, len(cells)):
            if not _missing(cells[row]):
                raise FieldError(field, "Only the first two rows (Before negative and Before positive) hold counts, "
                                        f'but row {row + 1} of "{name}" is not empty.')
    counts = []
    for row in (0, 1):
        for field, name, cells in ((AFTER_NEGATIVE, names[0], first), (AFTER_POSITIVE, names[1], second)):
            if _missing(cells[row]):
                raise FieldError(field, f'Enter a count for {ROW_LABELS[row]} in column "{name}".')
            counts.append(_whole_count(cells[row], name, field=field))
    total = sum(counts)
    if total == 0:
        raise FieldError(AFTER_NEGATIVE, "The total count is zero: enter at least one pair.")
    if total > MAX_TOTAL:
        raise FieldError(AFTER_NEGATIVE, "The total number of pairs cannot exceed 10,000,000.")
    return counts


# ----- analysis ------------------------------------------------------------------------------------------------------

def paired_proportions(frame, options):
    input_format, test, level, graph = _settings(options)
    discarded = None
    pairs = None
    if input_format == OBSERVATIONS:
        counts, pairs, discarded = _observations(frame, options)
    else:
        counts = _count_matrix(frame, options)
    a, b, c, d = counts
    summary = mcnemar_summary(a, b, c, d, test, level)
    empty = np.nan
    values = {"N pairs": summary["n"], "Before positive fraction": summary["before"],
              "After positive fraction": summary["after"], "Difference (after − before)": summary["difference"],
              "Discordant pairs": summary["discordant"],
              "Chi-square": empty if summary["chi_square"] is None else summary["chi_square"], "p": summary["p"],
              "Matched odds ratio": empty if summary["odds_ratio"] is None else summary["odds_ratio"],
              "OR CI lower": empty if summary["or_lower"] is None else summary["or_lower"],
              "OR CI upper": empty if summary["or_upper"] is None else summary["or_upper"],
              "Test": test, "Confidence level (%)": level, "OR CI method": CI_METHOD}
    if discarded is not None:
        values["Discarded pairs"] = discarded
    values["Note"] = _note(b, c)
    table = pd.DataFrame(np.array(counts, dtype=np.int64).reshape(2, 2), index=list(ROW_LABELS),
                         columns=list(COLUMN_LABELS))
    tables = {COUNTS_SHEET: table, REPORT_SHEET: _report(values)}
    if pairs is not None:
        tables[PAIRS_SHEET] = pairs
    return Result(tables, _figure(counts) if graph else None)


def _note(b, c):
    scope = ("The confidence interval belongs to the matched odds ratio b / c, which does not depend on the test; "
             "the marginal difference has no interval here.")
    if b + c == 0:
        return ("No discordant pairs: p = 1, and the chi-square statistic, the matched odds ratio and its interval "
                "cannot be estimated.")
    if c == 0:
        return "No losses (c = 0): the matched odds ratio and its upper limit are infinite. " + scope
    if b == 0:
        return "No gains (b = 0): the matched odds ratio and its lower limit are 0. " + scope
    return scope


# ----- figure --------------------------------------------------------------------------------------------------------

def _figure(counts):
    figure, axes = _plot(f"{PAIRED_PROPORTIONS} · {sum(counts)} pairs", "Transition (Before → After)", "Pairs")
    colors = ("#7b8794", COLORS[2], COLORS[1], COLORS[0])
    bars = axes.bar(range(4), counts, color=colors, width=0.62)
    for bar, name in zip(bars, TRANSITION_IDS):
        bar.set_gid(GID + name)
    axes.set_xticks(range(4), list(TRANSITIONS))
    axes.set_xlim(-0.6, 3.6)
    top = max(counts)
    axes.set_ylim(0, top * 1.14)
    axes.yaxis.set_major_locator(MaxNLocator(integer=True))
    for position, count in enumerate(counts):
        label = axes.text(position, count, str(count), ha="center", va="bottom", fontsize=10)
        label.set_parse_math(False)
    axes._tramastat_numeric_axes = ("y",)
    axes._tramastat_categorical_axes = ("x",)
    return figure
