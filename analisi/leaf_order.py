"""Optimal leaf ordering of a hierarchical clustering tree.

The only moves are swaps of the two children of a node, so every parent, merge height, cut and cluster
membership is preserved. The cost is the sum of the distances between adjacent leaves. The minimum is found
with the dynamic program of Bar-Joseph, Gifford and Jaakkola (2001): ``pair[u, w]`` holds the cheapest
ordering of the leaves under a node that has ``u`` at one end and ``w`` at the other. Two leaves have one
lowest common ancestor, and the two ends of an ordering always sit under different children of the node, so
one ``n x n`` matrix holds every node.

``scipy.cluster.hierarchy.optimal_leaf_ordering`` is not used. It can return an ordering that is not minimal,
a tree of four observations is enough (see ``tests/test_leaf_order.py``), and it keeps the interpreter lock
for the whole call, so the worker could be neither cancelled nor leave the window responsive. This version
works on blocks of numpy rows, checks the cancellation flag between blocks and lets numpy release the lock.
"""

import numpy as np
import pandas as pd
from scipy.spatial.distance import squareform

from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled

FIELD = "Leaf ordering"
DEFAULT, OPTIMAL = "Default", "Optimal"
CHOICES = (DEFAULT, OPTIMAL)
# Time grows with n³ and memory with n². At 2000 leaves one axis takes under 2 s and about 60 MB more
# than the tree itself on a desktop computer; docs/leaf-ordering.md reports the measurements.
MAX_LEAVES = 2000
_BLOCK = 1 << 20  # elements of the largest temporary array: 8 MB of doubles
_TIE = 1e-12


class LeafOrderCancelled(MonteCarloCancelled, InterruptedError):
    pass


def check_mode(options):
    mode = options.get(FIELD, DEFAULT)
    if mode not in CHOICES:
        raise FieldError(FIELD, "Choose Default or Optimal leaf ordering.")
    return mode


def check_size(count):
    """Refuse before any matrix is allocated."""
    if count > MAX_LEAVES:
        raise FieldError(FIELD, f"Optimal leaf ordering is limited to {MAX_LEAVES} leaves per axis. "
                                "Use fewer observations or variables, or choose Default.")


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise LeafOrderCancelled("Leaf ordering cancelled.")


def default_order(tree):
    """Leaves of a linkage from left to right, children in the stored order, without recursion."""
    n = len(tree) + 1
    children = np.asarray(tree)[:, :2].astype(int)
    leaves, pending = [], [2 * n - 2]
    while pending:
        node = pending.pop()
        if node < n:
            leaves.append(node)
        else:
            left, right = children[node - n]
            pending.extend((right, left))
    return np.asarray(leaves, dtype=int)


def order_cost(matrix, order):
    order = np.asarray(order)
    return float(matrix[order[:-1], order[1:]].sum())


def _minplus(left, right, cancel):
    """``out[i, j] = min over k of left[i, k] + right[k, j]``, a block of rows at a time."""
    rows, inner = left.shape
    out = np.empty((rows, right.shape[1]))
    step = max(1, _BLOCK // max(1, inner * right.shape[1]))
    for start in range(0, rows, step):
        check_cancel(cancel)
        out[start:start + step] = (left[start:start + step, :, None] + right[None, :, :]).min(axis=1)
    return out


def optimal_order(tree, distances, *, cancel=None):
    """Leaf order of minimal cost for a scipy linkage and its condensed distances: ``(order, cost)``.

    The first minimum in leaf order breaks ties, so one input always gives one answer. The original order
    is kept when it is already optimal.
    """
    tree = np.asarray(tree)
    n = len(tree) + 1
    matrix = squareform(np.asarray(distances, dtype=float))
    original = default_order(tree)
    original_cost = order_cost(matrix, original)
    if n < 3:
        return original, original_cost
    pair = np.full((n, n), np.inf)
    members = {leaf: np.array([leaf]) for leaf in range(n)}  # leaves under a node, left child first
    kids = {}

    def through(node, block):
        """``out[u] = min over m of pair[u, m] + block[m]`` for the leaves u, m of ``node``, in stored order."""
        if node < n:
            return block
        left, right = kids[node]
        first, second = members[left], members[right]
        inner = pair[np.ix_(first, second)]
        cut = len(first)
        return np.vstack([_minplus(inner, block[cut:], cancel), _minplus(inner.T, block[:cut], cancel)])

    for index, (left, right, _, _) in enumerate(tree):
        check_cancel(cancel)
        left, right = int(left), int(right)
        first, second = members[left], members[right]
        stage = through(left, matrix[np.ix_(first, second)])
        both = through(right, stage.T).T
        pair[np.ix_(first, second)] = both
        pair[np.ix_(second, first)] = both.T
        members[n + index] = np.concatenate([first, second])
        kids[n + index] = (left, right)

    root = 2 * n - 2
    left, right = kids[root]
    block = pair[np.ix_(members[left], members[right])]
    row, column = np.unravel_index(int(np.argmin(block)), block.shape)
    stack = [(root, int(members[left][row]), int(members[right][column]))]
    found = []
    while stack:
        check_cancel(cancel)
        node, start, end = stack.pop()
        if node < n:
            found.append(start)
            continue
        left, right = kids[node]
        near_id, far_id = (left, right) if start in members[left] else (right, left)
        near, far = members[near_id], members[far_id]
        total = (_ends(near_id, start, members, kids, pair, n)[:, None] + matrix[np.ix_(near, far)]
                 + _ends(far_id, end, members, kids, pair, n)[None, :])
        i, j = np.unravel_index(int(np.argmin(total)), total.shape)
        stack.append((far_id, int(far[j]), end))
        stack.append((near_id, start, int(near[i])))
    order = np.asarray(found, dtype=int)
    cost = order_cost(matrix, order)
    if original_cost <= cost + _TIE * max(abs(cost), abs(original_cost)):
        return original, original_cost
    return order, cost


def _ends(node, start, members, kids, pair, n):
    """Cost of ordering ``node`` with ``start`` at one end, for each possible other end."""
    if node < n:
        return np.zeros(1)
    left, right = kids[node]
    out = np.full(len(members[node]), np.inf)
    cut = len(members[left])
    other = slice(cut, None) if start in members[left] else slice(0, cut)
    out[other] = pair[start, members[node][other]]
    return out


def layout_tree(tree, order):
    """The linkage with children swapped where needed so that the left-to-right traversal gives ``order``."""
    tree = np.array(tree, dtype=float)
    n = len(tree) + 1
    first = np.empty(2 * n - 1, dtype=int)
    first[np.asarray(order)] = np.arange(n)
    for index, (left, right, _, _) in enumerate(tree):
        left, right = int(left), int(right)
        first[n + index] = min(first[left], first[right])
        if first[right] < first[left]:
            tree[index, 0], tree[index, 1] = right, left
    return tree


def leaf_order_report(order, names, matrix):
    """Position, label, input index and the distance from the previous leaf, for one axis."""
    order = np.asarray(order)
    previous = np.r_[np.nan, matrix[order[:-1], order[1:]]]
    return pd.DataFrame({"Position": np.arange(1, len(order) + 1), "Label": [names[i] for i in order],
                         "Input index": order + 1, "Distance from previous": previous})


def order_leaves(fit, names, *, cancel=None):
    """Optimal order of a fitted axis: ``(layout linkage, report, original cost, final cost)``."""
    check_size(len(names))
    order, cost = optimal_order(fit.tree, fit.distances, cancel=cancel)
    matrix = squareform(fit.distances)
    original = order_cost(matrix, default_order(fit.tree))
    return layout_tree(fit.tree, order), leaf_order_report(order, names, matrix), original, cost
