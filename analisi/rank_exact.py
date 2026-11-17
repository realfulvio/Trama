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
from math import comb

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
    if take is None:
        bound = 2**size
    else:
        bound = sum(comb(size, c) for c in range(take + 1))
    dtype = np.int64 if bound < _INT64_SAFE else object
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
    sums, counts = _distribution(_blocks(doubled), None, max_states, max_transitions)
    low, high = _tails(sums, counts, observed)
    return low, high, 2 ** len(doubled)
