"""Exact conditional counts for the Mann–Whitney and Wilcoxon signed-rank tests, ties included.

Ranks are doubled so that mid-ranks are integers. Equal ranks form a block of
``m`` observations. Taking ``j`` of them contributes ``comb(m, j)`` labelled
allocations, so ties are compressed instead of enumerated and every count is an
exact Python integer whenever int64 could overflow.

Mann–Whitney: under the null every choice of ``n1`` positions among the ``N``
pooled observations has probability ``1 / comb(N, n1)``. The distribution of the
rank sum of the chosen positions is built by dynamic programming over
(number chosen, doubled rank sum).

Wilcoxon: conditional on the moduli, each sign assignment of the ``m`` nonzero
differences has probability ``1 / 2**m``. The distribution of the doubled sum of
the ranks carrying a positive sign is built over blocks of equal ranks.

The work is counted before it is done: a block that would take the cumulative
transitions over the limit, or a merged table that holds too many states, raises
:class:`ExactBudgetExceeded`.
"""
from math import comb, lgamma, log, log2

import numpy as np

from .friedman_exact import ExactBudgetExceeded

MAX_STATES = 250_000
MAX_TRANSITIONS = 5_000_000
_INT64_SAFE = 2**62


def doubled_ranks(values):
    """Return 2 × the average rank of each value. Equal floats are ties."""
    values = np.asarray(values, dtype=float)
    if not len(values):
        return np.zeros(0, dtype=np.int64)
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    first = np.cumsum(counts) - counts                       # zero-based position of each block
    return (2 * first + counts + 1)[np.ravel(inverse)].astype(np.int64)


def _merge(keys, counts):
    """Sum the counts of equal keys. Return keys in increasing order."""
    if len(keys) < 2:
        return keys, counts
    order = np.argsort(keys, kind="stable")
    keys, counts = keys[order], counts[order]
    starts = np.flatnonzero(np.concatenate(([True], keys[1:] != keys[:-1])))
    if len(starts) == len(keys):
        return keys, counts
    if counts.dtype == object:
        edges = [*starts.tolist(), len(keys)]
        merged = np.empty(len(starts), dtype=object)
        for index, (begin, end) in enumerate(zip(edges[:-1], edges[1:])):
            merged[index] = sum(counts[begin:end].tolist())
        return keys[starts], merged
    return keys[starts], np.add.reduceat(counts, starts)


def _distribution(blocks, take, max_states, max_transitions):
    """Return (sums, counts) of the doubled rank sum over the allocations.

    ``blocks`` lists (doubled rank, multiplicity). ``take`` is the number of
    observations chosen, or None when any number may be chosen (signs).
    """
    size = sum(m for _, m in blocks)
    top = sum(value * m for value, m in blocks)
    stride = top + 1
    dtype = np.int64 if _count_bound_fits(size, take) else object
    keys = np.zeros(1, dtype=np.int64)
    counts = np.ones(1, dtype=dtype)
    remaining, transitions = size, 0
    for value, multiplicity in blocks:
        remaining -= multiplicity
        longest = multiplicity if take is None else min(multiplicity, take)
        transitions += len(keys) * (longest + 1)
        if transitions > max_transitions:
            raise ExactBudgetExceeded(f"More than {max_transitions:,} transitions are needed.")
        new_keys, new_counts = [], []
        for chosen in range(longest + 1):
            shifted = keys + chosen * (value if take is None else stride + value)
            weight = comb(multiplicity, chosen)
            weighted = counts * (np.int64(weight) if dtype is np.int64 else weight)
            if take is not None:
                level = shifted // stride
                keep = (level <= take) & (level >= take - remaining)
                shifted, weighted = shifted[keep], weighted[keep]
            new_keys.append(shifted)
            new_counts.append(weighted)
        keys, counts = _merge(np.concatenate(new_keys), np.concatenate(new_counts))
        if len(keys) > max_states:
            raise ExactBudgetExceeded(f"More than {max_states:,} distinct states.")
    if take is not None:
        keys = keys - take * stride
    return keys, counts


def _count_bound_fits(size, take):
    """True when every allocation count stays below 2**62, so int64 is exact.

    The bound is sum(comb(size, c) for c <= take) (2**size for signs). Summing those big
    integers costs O(take) multiplications of numbers with up to ``size`` bits, which takes
    minutes for size = 100,000. Above 61 observations an upper bound in logarithms decides:
    (take + 1) times the largest term, plus a margin. It can only choose the exact object
    path more often, never an int64 that could overflow.
    """
    if size <= 61:
        return True
    if take is None:
        return False
    k = min(take, size // 2)
    log2_term = (lgamma(size + 1) - lgamma(k + 1) - lgamma(size - k + 1)) / log(2)
    return log2(take + 1) + log2_term + 1 < 62


def mann_whitney_state_floor(doubled, take):
    """A lower bound on the distinct rank sums of ``take`` positions among the pooled ranks.

    Sort the doubled ranks. Start from the ``take`` smallest and move the chosen positions one
    step to the right at a time, the rightmost first, until they are the ``take`` largest. That
    is ``take * (size - take)`` moves; a move across two different ranks raises the sum, so the
    sums seen are distinct and the count of such moves plus one bounds the number of distinct
    sums. Position ``k`` (from the right) sweeps the gaps between sorted positions
    ``take - k`` and ``size - k``. Without ties this is exactly take * (size - take) + 1.
    """
    values = np.sort(np.asarray(doubled, dtype=np.int64))
    size = len(values)
    if take <= 0 or take >= size:
        return 1
    rises = np.concatenate(([0], np.cumsum(values[1:] > values[:-1])))   # rises[i]: steps before i
    starts = np.arange(take)                       # chosen position j starts at j ...
    ends = starts + (size - take)                  # ... and ends at j + size - take
    return int(1 + np.sum(rises[ends] - rises[starts]))


def _mann_whitney_budget_floor(doubled, take, max_states, max_transitions):
    """Return the budget message the dynamic programme would raise for certain, or None.

    The programme visits the blocks of equal doubled ranks in increasing order. Before block b
    it adds len(table) * (longest + 1) to its transition count, and after it the table holds
    one state per distinct (chosen, sum) pair with chosen in [take - remaining, min(take, m)],
    where m observations have been seen. For each such ``chosen`` the distinct sums of the
    first m sorted ranks are at least ``mann_whitney_state_floor`` of that prefix, which has
    the closed form 1 + CR[m] - CR[m - c] - CR[c] with CR the running sum of the rises. Both
    counts are therefore bounded from below block by block; reaching a limit with the bounds
    means the programme reaches it at the same block or earlier, with the same message kind.
    """
    values = np.sort(np.asarray(doubled, dtype=np.int64))
    size = len(values)
    if size > 2_000_000 or take <= 0:      # int64 sums below stay exact up to this size
        return None
    rises = np.concatenate(([0], np.cumsum(values[1:] > values[:-1], dtype=np.int64)))
    cr = np.concatenate(([0], np.cumsum(rises, dtype=np.int64)))            # cr[t] = sum(rises[:t])
    ccr = np.concatenate(([0], np.cumsum(cr, dtype=np.int64)))              # ccr[t] = sum(cr[:t])
    _, multiplicity = np.unique(values, return_counts=True)
    seen = np.cumsum(multiplicity)                                          # m after each block
    remaining = size - seen
    longest = np.minimum(multiplicity, take)
    low = np.maximum(0, take - remaining)
    high = np.minimum(take, seen)
    count = high - low + 1
    # sum over c in [low, high] of (1 + cr[m] - cr[m - c] - cr[c])
    states = (count * (1 + cr[seen]) - (ccr[seen - low + 1] - ccr[seen - high])
              - (ccr[high + 1] - ccr[low]))
    before = np.concatenate(([1.0], states[:-1].astype(float)))             # table size before each block
    transitions = np.cumsum(before * (longest + 1))
    over_transitions = np.flatnonzero(transitions > max_transitions)
    over_states = np.flatnonzero(states > max_states)
    first_t = over_transitions[0] if len(over_transitions) else size + 1
    first_s = over_states[0] if len(over_states) else size + 1
    if first_t <= first_s and first_t <= size:
        return f"More than {max_transitions:,} transitions are needed."
    if first_s <= size:
        return f"More than {max_states:,} distinct states."
    return None


def _signed_rank_budget_floor(doubled, max_states, max_transitions):
    """The signed-rank counterpart of :func:`_mann_whitney_budget_floor`.

    Without a fixed number chosen, the table after m observations holds every distinct subset
    sum of the first m sorted ranks. Those include the sums of exactly c = m // 2 of them, so
    the same closed form with c = m // 2 bounds the table size from below.
    """
    values = np.sort(np.asarray(doubled, dtype=np.int64))
    size = len(values)
    if size > 2_000_000:
        return None
    rises = np.concatenate(([0], np.cumsum(values[1:] > values[:-1], dtype=np.int64)))
    cr = np.concatenate(([0], np.cumsum(rises, dtype=np.int64)))
    _, multiplicity = np.unique(values, return_counts=True)
    seen = np.cumsum(multiplicity)
    half = seen // 2
    states = 1 + cr[seen] - cr[seen - half] - cr[half]
    before = np.concatenate(([1.0], states[:-1].astype(float)))
    transitions = np.cumsum(before * (multiplicity + 1))
    over_transitions = np.flatnonzero(transitions > max_transitions)
    over_states = np.flatnonzero(states > max_states)
    first_t = over_transitions[0] if len(over_transitions) else size + 1
    first_s = over_states[0] if len(over_states) else size + 1
    if first_t <= first_s and first_t <= size:
        return f"More than {max_transitions:,} transitions are needed."
    if first_s <= size:
        return f"More than {max_states:,} distinct states."
    return None


def _blocks(doubled):
    values, multiplicities = np.unique(np.asarray(doubled, dtype=np.int64), return_counts=True)
    return [(int(v), int(m)) for v, m in zip(values, multiplicities)]


def _tails(sums, counts, observed):
    """Return the counts of allocations with a sum at or below and at or above ``observed``."""
    def total(selected):
        return int(selected.sum()) if selected.dtype != object else sum(selected.tolist())
    return total(counts[sums <= observed]), total(counts[sums >= observed])


def mann_whitney_tails(doubled, first, *, max_states=None, max_transitions=None):
    """Return (less, greater, total) allocation counts for the first group's rank sum.

    ``doubled`` holds the doubled pooled ranks and ``first`` marks the first
    group. ``less`` counts the choices whose rank sum for the first group is at
    most the observed one, ``greater`` those at or above it, and ``total`` is
    comb(N, n1).
    """
    max_states = MAX_STATES if max_states is None else max_states
    max_transitions = MAX_TRANSITIONS if max_transitions is None else max_transitions
    doubled = np.asarray(doubled, dtype=np.int64)
    first = np.asarray(first, dtype=bool)
    size, n1 = len(doubled), int(first.sum())
    observed = int(doubled[first].sum())
    # Choosing the smaller group gives the same allocations with fewer states.
    take = min(n1, size - n1)
    # Lower bounds of the work the dynamic programme below would count: when one is over a
    # limit the programme would raise after doing that work, so raise before starting it.
    reason = _mann_whitney_budget_floor(doubled, take, max_states, max_transitions)
    if reason is not None:
        raise ExactBudgetExceeded(reason)
    sums, counts = _distribution(_blocks(doubled), take, max_states, max_transitions)
    low, high = _tails(sums, counts, observed if take == n1 else int(doubled.sum()) - observed)
    if take != n1:
        low, high = high, low
    return low, high, comb(size, n1)


def signed_rank_tails(doubled, positive, *, max_states=None, max_transitions=None):
    """Return (less, greater, total) sign-assignment counts for the positive rank sum.

    ``doubled`` holds the doubled ranks of the nonzero differences and
    ``positive`` marks those with a positive sign. ``total`` is 2**m.
    """
    max_states = MAX_STATES if max_states is None else max_states
    max_transitions = MAX_TRANSITIONS if max_transitions is None else max_transitions
    doubled = np.asarray(doubled, dtype=np.int64)
    if not len(doubled):
        return 1, 1, 1
    observed = int(doubled[np.asarray(positive, dtype=bool)].sum())
    reason = _signed_rank_budget_floor(doubled, max_states, max_transitions)
    if reason is not None:
        raise ExactBudgetExceeded(reason)
    sums, counts = _distribution(_blocks(doubled), None, max_states, max_transitions)
    low, high = _tails(sums, counts, observed)
    return low, high, 2 ** len(doubled)
