"""Exact conditional p value for Friedman's test, with ties, by compressed counting.

Under the null every subject's observations are exchangeable across treatments.
Each of the k! label assignments of a subject therefore has equal probability,
and a row with ties has the same set of assignments repeated: a distinct order
of a row with tie multiplicities m_g is hit by prod(m_g!) labelled assignments.

Midranks are doubled so they are integers. The sum of squared treatment rank
sums orders the permutations like the Friedman statistic, because the ranks of
each subject, and so the tie correction, are the same in every permutation.
The p value is the weighted share of assignments at or above the observed value.

Counting adds one subject at a time to a vector of partial rank sums. The
final statistic is symmetric in the treatments, and every row's set of weighted
orders is closed under relabeling the treatments. Hence the number of ways to
finish from a state depends only on the sorted partial sums. Sorting merges
every relabeled copy of a state and adds their path counts, so the multiplicity
of each sorted state equals the number of full assignments that reach any of
its relabelings. Tests check this against direct enumeration.
"""
from itertools import combinations
from math import factorial, prod

import numpy as np
from scipy import stats

_MAX_STATES = 200_000
_MAX_TRANSITIONS = 5_000_000
_MAX_ORDERS = 1_000_000
_MAX_VECTOR_CELLS = 2_000_000
_CHUNK = 100_000
_INT64_SAFE = 2**62


class ExactBudgetExceeded(Exception):
    """The exact count would need more states or transitions than the budget."""


def distinct_orders(row):
    """Return the distinct orderings of a row and the weight of each one.

    The weight is the number of labelled assignments that produce the ordering.
    """
    values, counts = np.unique(row, return_counts=True)
    weight = prod(factorial(int(c)) for c in counts)
    return values, counts, factorial(len(row)) // weight, weight


def _generate_orders(values, counts):
    """Build every distinct ordering by placing the values one group at a time."""
    size = int(counts.sum())
    orders = np.full((1, size), -1, dtype=np.int32)
    for value, group in zip(values, counts):
        free = np.argwhere(orders == -1)[:, 1].reshape(len(orders), -1)
        choices = np.array(list(combinations(range(free.shape[1]), int(group))), dtype=np.intp)
        chosen = free[:, choices]                         # rows × choices × group
        orders = np.repeat(orders, len(choices), axis=0).reshape(len(orders), len(choices), size)
        np.put_along_axis(orders, chosen, np.int32(value), axis=2)
        orders = orders.reshape(-1, size)
    return orders


def _merge(rows, weights):
    """Sum the weights of identical rows. Return sorted unique rows."""
    if len(rows) > 1:
        top = int(rows.max())
        bits = max(1, top.bit_length())
        if bits * rows.shape[1] <= 62:
            key = np.zeros(len(rows), dtype=np.int64)
            for column in range(rows.shape[1]):
                key = (key << bits) | rows[:, column].astype(np.int64)
            order = np.argsort(key, kind="stable")
            key = key[order]
            starts = np.flatnonzero(np.concatenate(([True], key[1:] != key[:-1])))
        else:
            order = np.lexsort(rows.T[::-1])
            ordered = rows[order]
            starts = np.flatnonzero(np.concatenate(([True], np.any(ordered[1:] != ordered[:-1], axis=1))))
        return rows[order][starts], np.add.reduceat(weights[order], starts)
    return rows, weights


def friedman_exact_tail(values, max_states=None, max_transitions=None):
    """Return (extreme, total): weighted count at or above the observed statistic and (k!)^n.

    Raise ExactBudgetExceeded before allocating more than the state or transition
    budget. Counts are Python integers whenever int64 could overflow.
    """
    max_states = _MAX_STATES if max_states is None else max_states
    max_transitions = _MAX_TRANSITIONS if max_transitions is None else max_transitions
    if np.size(values) > _MAX_VECTOR_CELLS:
        raise ExactBudgetExceeded(f"At most {_MAX_VECTOR_CELLS:,} rank cells fit in the exact calculation workspace.")
    ranks = (2 * stats.rankdata(values, axis=1)).astype(np.int64)
    n, k = ranks.shape
    vector_rows = _MAX_VECTOR_CELLS // k
    max_states = min(max_states, vector_rows)
    chunk = min(_CHUNK, vector_rows)
    total = factorial(k) ** n
    observed = int(np.square(ranks.sum(axis=0)).sum())
    dtype = np.int64 if total < _INT64_SAFE else object

    plans = []
    for row in ranks:
        distinct, counts, orders, weight = distinct_orders(row)
        plans.append((orders, distinct, counts, weight, row))
    # The first row is free after sorting, so start with the one with most orders.
    plans.sort(key=lambda plan: -plan[0])
    first = np.sort(plans[0][4])
    states = first[None, :]
    weights = np.array([factorial(k)], dtype=dtype)
    used = 0
    for index, (orders, distinct, counts, weight, _) in enumerate(plans[1:], start=1):
        last = index == n - 1
        needed = used + orders + len(states) * orders     # generating orders, then adding them
        if orders > _MAX_ORDERS:
            raise ExactBudgetExceeded(f"More than {_MAX_ORDERS:,} distinct orders for a subject.")
        if orders > vector_rows:
            raise ExactBudgetExceeded(f"The orders of a subject need more than {_MAX_VECTOR_CELLS:,} rank cells.")
        if needed > max_transitions:
            raise ExactBudgetExceeded(f"More than {max_transitions:,} transitions are needed.")
        used = needed
        table = _generate_orders(distinct, counts)
        step = np.array([weight], dtype=dtype)
        merged_rows = merged_weights = None
        extreme = 0
        for begin in range(0, orders, chunk):
            block = table[begin:begin + chunk]
            width = max(1, chunk // len(block))
            for start in range(0, len(states), width):
                part = states[start:start + width]
                sums = (part[:, None, :] + block[None, :, :]).reshape(-1, k)
                weighted = (weights[start:start + width][:, None] * step[0]).repeat(len(block), axis=1).reshape(-1)
                if last:
                    hit = np.square(sums.astype(np.int64)).sum(axis=1) >= observed
                    extreme += int(weighted[hit].sum()) if dtype is np.int64 else sum(weighted[hit].tolist())
                    continue
                sums.sort(axis=1)
                if merged_rows is None:
                    merged_rows, merged_weights = _merge(sums, weighted)
                else:
                    merged_rows, merged_weights = _merge(np.concatenate((merged_rows, sums)),
                                                         np.concatenate((merged_weights, weighted)))
                if len(merged_rows) > max_states:
                    raise ExactBudgetExceeded(f"More than {max_states:,} distinct partial-sum states.")
        if last:
            return extreme, total
        states, weights = merged_rows, merged_weights
    # Only reached with a single subject; Friedman's test requires at least two.
    hit = np.square(states.astype(np.int64)).sum(axis=1) >= observed
    return int(sum(weights[hit].tolist())), total
