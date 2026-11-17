"""Mann–Whitney and Wilcoxon signed-rank tests with exact conditional or normal p values.

A recipe without the P value option keeps the original ``_nonparametric`` path.
Everything here runs only when the recipe carries P value.

Conventions stated by the contract (see tests/test_rank_tests.py):

* Ranks are mid-ranks, doubled internally so that the counts are integers.
  Ties are the equalities of the actual float values, with no rounding.
* Less means the first group (or the first column) tends to be smaller. Greater is
  the opposite. The exact two-sided p value is min(1, 2 × the smaller tail).
* Mann–Whitney Statistic is U of the first group, as in SciPy. Wilcoxon Statistic
  is min(W+, W−) for Two-sided and W+ for Less and Greater.
* The normal approximation uses the tie-corrected variance. Continuity moves the
  statistic by 0.5 rank units toward the mean.
* Automatic uses the exact distribution inside the work budget and otherwise the
  normal approximation, which it names in "p method reason". Exact conditional
  outside the budget is an error on the P value field.
"""
from fractions import Fraction

import numpy as np
import pandas as pd
from scipy import stats

from . import stats as engine
from .friedman_exact import ExactBudgetExceeded
from .processing import FieldError
from .rank_exact import doubled_ranks, mann_whitney_tails, signed_rank_tails
from .reporting import Result, _report

MANN_WHITNEY, WILCOXON = "Mann–Whitney", "Wilcoxon signed-rank"
P_VALUE = "P value"
AUTOMATIC, EXACT, NORMAL = P_METHODS = ("Automatic", "Exact conditional", "Normal approximation")
ALTERNATIVE = "Alternative"
TWO_SIDED, LESS, GREATER = ALTERNATIVES = ("Two-sided", "Less", "Greater")
CONTINUITY = "Continuity correction"
ZERO_DIFFERENCES = "Zero differences"
DISCARD, PRATT = ZERO_POLICIES = ("Discard", "Pratt")
NOT_APPLICABLE = "Not applicable"

# Interface captions and choice labels of the new controls. Recipes keep the English keys and values.
LABEL_KEYS = {P_VALUE: "rank.field.p_value", ALTERNATIVE: "rank.field.alternative",
              CONTINUITY: "rank.field.continuity", ZERO_DIFFERENCES: "rank.field.zero_differences"}
CHOICE_KEYS = {AUTOMATIC: "rank.choice.automatic", EXACT: "rank.choice.exact", NORMAL: "rank.choice.normal",
               TWO_SIDED: "rank.choice.two_sided", LESS: "rank.choice.less", GREATER: "rank.choice.greater",
               DISCARD: "rank.choice.discard", PRATT: "rank.choice.pratt"}

COMMON_OPTIONS = {P_VALUE: P_METHODS, ALTERNATIVE: ALTERNATIVES, CONTINUITY: True}
OPTIONS = {
    MANN_WHITNEY: {"Response": None, "Group": None, **COMMON_OPTIONS},
    WILCOXON: {"First": None, "Second": None, **COMMON_OPTIONS, ZERO_DIFFERENCES: ZERO_POLICIES},
}


def is_legacy(options):
    """Recipes saved before the exact tests carry no P value option."""
    return P_VALUE not in options


def check_options(method, options):
    """Return (P value, alternative, continuity, zero policy). Raises FieldError naming the field."""
    p_method = options.get(P_VALUE, AUTOMATIC)
    if not isinstance(p_method, str) or p_method not in P_METHODS:
        raise FieldError(P_VALUE, "Choose automatic, exact conditional or normal approximation.")
    alternative = options.get(ALTERNATIVE, TWO_SIDED)
    if not isinstance(alternative, str) or alternative not in ALTERNATIVES:
        raise FieldError(ALTERNATIVE, "Choose two-sided, less or greater.")
    continuity = options.get(CONTINUITY, True)
    if not isinstance(continuity, (bool, np.bool_)):
        raise FieldError(CONTINUITY, "Continuity correction must be on or off.")
    zero = options.get(ZERO_DIFFERENCES, DISCARD)
    if method == WILCOXON and (not isinstance(zero, str) or zero not in ZERO_POLICIES):
        raise FieldError(ZERO_DIFFERENCES, "Choose discard or Pratt.")
    return p_method, alternative, bool(continuity), zero


def _exact_p(low, high, total, alternative):
    if alternative == LESS:
        share = Fraction(low, total)
    elif alternative == GREATER:
        share = Fraction(high, total)
    else:
        share = min(Fraction(1), Fraction(2 * min(low, high), total))
    return float(share)


def _normal_p(statistic, mean, variance, alternative, continuity):
    """Return (p, note). A zero variance gives p = 1 and a note."""
    if not variance > 0:
        return 1.0, "The variance is zero, so the normal approximation reports p = 1."
    scale, shift = np.sqrt(variance), 0.5 if continuity else 0.0
    if alternative == LESS:
        p = stats.norm.cdf((statistic + shift - mean) / scale)
    elif alternative == GREATER:
        p = stats.norm.sf((statistic - shift - mean) / scale)
    else:
        p = 2 * stats.norm.sf(max(0.0, abs(statistic - mean) - shift) / scale)
    return float(min(1.0, p)), None


def _choose(p_method, exact, normal):
    """Return (p, method, reason, note) for the requested P value method.

    ``exact`` returns the p value or raises ExactBudgetExceeded. ``normal`` returns (p, note).
    """
    if p_method != NORMAL:
        try:
            return exact(), EXACT, "", None
        except ExactBudgetExceeded as error:
            if p_method == EXACT:
                raise FieldError(P_VALUE, f"Exact conditional exceeds the calculation limit ({error}) "
                                          "Choose Automatic or Normal approximation.") from None
            reason = f"Exact conditional exceeded the work limit ({error}) The normal approximation was used."
            p, note = normal()
            return p, NORMAL, reason, note
    p, note = normal()
    return p, NORMAL, "", note


def _summary(rows, note):
    if note:
        rows["Note"] = note
    return _report(rows)


def _mann_whitney(frame, options):
    p_method, alternative, continuity, _ = check_options(MANN_WHITNEY, options)
    response, group = options["Response"], options["Group"]
    if response == group:
        raise FieldError("Group", "Choose different columns for Response and Group.")
    data = engine.complete(frame.reset_index(drop=True), [response], [group])
    labels = pd.unique(data[group])
    if len(labels) != 2:
        raise FieldError("Group", "Mann–Whitney needs exactly two groups.")
    values = data[response].to_numpy(dtype=float)
    first = (data[group] == labels[0]).to_numpy()
    size, n1 = len(values), int(first.sum())
    n2 = size - n1
    doubled = doubled_ranks(values)
    u1 = doubled[first].sum() / 2 - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1

    def exact():
        low, high, total = mann_whitney_tails(doubled, first)
        return _exact_p(low, high, total, alternative)

    def normal():
        ties = np.unique(values, return_counts=True)[1].astype(float)
        variance = n1 * n2 / 12 * (size + 1 - (ties**3 - ties).sum() / (size * (size - 1)))
        return _normal_p(u1, n1 * n2 / 2, variance, alternative, continuity)

    p, used, reason, note = _choose(p_method, exact, normal)
    rows = {"Statistic": u1, "p": p, "N": size, "p method": used, "p method reason": reason,
            ALTERNATIVE: alternative, CONTINUITY: continuity if used == NORMAL else NOT_APPLICABLE,
            "Rank-biserial": 2 * u1 / (n1 * n2) - 1,
            "First group": labels[0], "Second group": labels[1], "N first": n1, "N second": n2,
            "U first": u1, "U second": u2}
    ranks = pd.DataFrame({"Source row": frame.index.take(data.index).to_numpy(), "Group": data[group].to_numpy(),
                          "Value": values, "Rank": doubled / 2})
    return Result({MANN_WHITNEY: _summary(rows, note), "Ranks": ranks})


def _wilcoxon(frame, options):
    p_method, alternative, continuity, zero = check_options(WILCOXON, options)
    first_name, second_name = options["First"], options["Second"]
    if first_name == second_name:
        raise FieldError("Second", "Choose different columns for First and Second.")
    data = engine.complete(frame.reset_index(drop=True), [first_name, second_name])
    if not len(data):
        raise ValueError("Wilcoxon needs at least one complete pair.")
    first, second = data[first_name].to_numpy(dtype=float), data[second_name].to_numpy(dtype=float)
    difference = first - second
    nonzero = difference != 0
    effective = int(nonzero.sum())
    if zero == PRATT:
        doubled = doubled_ranks(np.abs(difference))
    else:
        doubled = np.zeros(len(difference), dtype=np.int64)
        doubled[nonzero] = doubled_ranks(np.abs(difference[nonzero]))
    positive, negative = difference > 0, difference < 0
    w_plus, w_minus = doubled[positive].sum() / 2, doubled[negative].sum() / 2
    used = doubled[nonzero]

    def exact():
        low, high, total = signed_rank_tails(used, positive[nonzero])
        return _exact_p(low, high, total, alternative)

    def normal():
        if not effective:
            return 1.0, None
        return _normal_p(w_plus, used.sum() / 4, (used.astype(float) ** 2).sum() / 16, alternative, continuity)

    p, method, reason, note = _choose(p_method, exact, normal)
    if not effective:
        p = 1.0
        note = "Every complete pair has a zero difference, so there are no signed ranks to test."
    rows = {"Statistic": min(w_plus, w_minus) if alternative == TWO_SIDED else w_plus, "p": p, "N": len(data),
            "p method": method, "p method reason": reason, ALTERNATIVE: alternative,
            CONTINUITY: continuity if method == NORMAL else NOT_APPLICABLE,
            "Rank-biserial": (w_plus - w_minus) / (w_plus + w_minus) if effective else np.nan,
            "Complete pairs": len(data), "Zero pairs": len(data) - effective, "Effective N": effective,
            "W positive": w_plus, "W negative": w_minus, ZERO_DIFFERENCES: zero}
    ranked = np.where(nonzero | (zero == PRATT), doubled / 2, np.nan)
    ranks = pd.DataFrame({"Source row": frame.index.take(data.index).to_numpy(), "First": first, "Second": second,
                          "Difference": difference, "Absolute rank": ranked, "Included": nonzero})
    return Result({WILCOXON: _summary(rows, note), "Ranks": ranks})


def rank_test(method, frame, options):
    """Run the new path of Mann–Whitney or Wilcoxon signed-rank for a recipe that carries P value."""
    return (_mann_whitney if method == MANN_WHITNEY else _wilcoxon)(frame, options)
