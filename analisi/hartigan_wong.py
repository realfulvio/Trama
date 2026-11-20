"""Hartigan-Wong K-means with explicit initial observations.

The optimal stage considers the previous alternative and the live clusters. The quick stage revisits
the last alternative for each observation. A move must strictly reduce the within-cluster sum of squares.
"""
from dataclasses import dataclass
from numbers import Integral
import numpy as np
from scipy.spatial.distance import cdist


class IterationLimitError(ValueError):
    """No successful start converged within the selected iteration limit."""


@dataclass
class HartiganFit:
    labels: np.ndarray
    centers: np.ndarray
    within: np.ndarray
    converged: bool
    iterations: int


def _transfer(values, centers, counts, labels, alternative, row, target):
    origin = labels[row]
    point = values[row]
    counts[origin] -= 1
    counts[target] += 1
    centers[origin] += (centers[origin] - point) / counts[origin]
    centers[target] += (point - centers[target]) / counts[target]
    labels[row], alternative[row] = target, origin


def _quick(values, centers, counts, labels, alternative, changed_in_optimum):
    size = len(values)
    last_change = np.where(changed_in_optimum, 0, -size).tolist()
    touched = np.zeros(len(counts), dtype=bool)
    idle = 0
    for step in range(1, 50 * size + 1):
        row = (step - 1) % size
        origin, target = labels[row], alternative[row]
        idle += 1
        origin_count = counts[origin]
        cutoff = step - size
        if origin_count > 1 and (last_change[origin] > cutoff or last_change[target] > cutoff):
            x = values[row]
            delta = centers[[origin, target]] - x
            distance = np.einsum("ij,ij->i", delta, delta)
            target_count = counts[target]
            removed = distance[0] * origin_count / (origin_count - 1)
            added = distance[1] * target_count / (target_count + 1)
            if added < removed:
                _transfer(values, centers, counts, labels, alternative, row, target)
                last_change[origin] = last_change[target] = step
                touched[origin] = touched[target] = True
                idle = 0
        if idle == size:
            return touched
    raise ValueError("Hartigan-Wong quick transfers exceed their work budget.")


def fit_hartigan_wong(values, initial_rows, max_iterations=10):
    """Fit using zero-based positions of distinct initial rows in the complete numeric input."""
    values = np.asarray(values, dtype=float)
    positions = np.asarray(initial_rows)
    if values.ndim != 2 or values.shape[0] < 2 or not values.shape[1] or not np.isfinite(values).all():
        raise ValueError("Hartigan-Wong needs a finite numeric matrix with at least two rows.")
    n, width = values.shape
    if positions.ndim != 1 or positions.dtype.kind not in "iu" or not 1 <= len(positions) <= n:
        raise ValueError("Choose one distinct initial row per cluster.")
    if (positions >= n).any() or (positions < 0).any():
        raise ValueError("Initial row positions are outside the complete data.")
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, Integral) or not 1 <= max_iterations <= 1000:
        raise ValueError("Maximum iterations must be an integer from 1 to 1000.")
    k = len(positions)
    if n * k > 2_000_000:
        raise ValueError("The initial assignment exceeds the K-means work budget.")
    origin_point = values[0]
    with np.errstate(over="ignore", invalid="ignore"):
        values = values - origin_point
    limit = np.sqrt(np.finfo(float).max / (4 * n * width))
    if not np.isfinite(values).all() or np.abs(values).max() > limit:
        raise ValueError("Variable magnitudes are too large to compute squared distances.")
    initial = values[positions]
    if len(np.unique(initial, axis=0)) != k:
        raise ValueError("Initial observations must specify distinct centers.")
    if k == 1:
        center = values.mean(axis=0, keepdims=True)
        within = np.array([np.sum((values - center) ** 2)])
        return HartiganFit(np.zeros(n, dtype=int), center + origin_point, within, True, 1)
    if k == n:
        labels = np.empty(n, dtype=int)
        labels[positions] = np.arange(k)
        return HartiganFit(labels, initial + origin_point, np.zeros(k), True, 1)
    closest = np.argsort(cdist(values, initial, "sqeuclidean"), axis=1, kind="stable")[:, :2]
    labels, alternative = closest.T.copy()
    counts = np.bincount(labels, minlength=k)
    if (counts == 0).any():
        raise ValueError("An initial cluster has no observations.")
    centers = np.vstack([values[labels == i].mean(axis=0) for i in range(k)])
    quick_touched = np.ones(k, dtype=bool)
    opt_steps = 0
    # A transfer keeps both clusters eligible for the next cycle through the rows.
    live_through = np.zeros(k, dtype=int)
    idle = 0
    finished = False
    for iteration in range(1, max_iterations + 1):
        changed_in_optimum = np.zeros(k, dtype=bool)
        for row, point in enumerate(values):
            opt_steps += 1
            idle += 1
            origin = labels[row]
            if counts[origin] > 1:
                candidates = quick_touched | (live_through > opt_steps)
                if candidates[origin]:
                    candidates[:] = True
                candidates[alternative[row]] = True
                candidates[origin] = False
                ds = centers - point
                distances = np.einsum("ij,ij->i", ds, ds)
                cost = distances * counts / (counts + 1)
                cost[~candidates] = np.inf
                target = int(cost.argmin())
                alt = alternative[row]
                if cost[target] == cost[alt]:
                    target = alt
                removed = distances[origin] * counts[origin] / (counts[origin] - 1)
                if cost[target] < removed:
                    _transfer(values, centers, counts, labels, alternative, row, target)
                    live_through[origin] = live_through[target] = opt_steps + n
                    changed_in_optimum[origin] = changed_in_optimum[target] = True
                    idle = 0
                else:
                    alternative[row] = target
            if idle >= n:
                finished = True
                break
        if finished:
            break
        quick_touched = _quick(values, centers, counts, labels, alternative, changed_in_optimum)
        if quick_touched.any():
            idle = 0
        if k == 2:
            finished = True
            break
    centers = np.vstack([values[labels == i].mean(axis=0) for i in range(k)])
    ds = values - centers[labels]
    within = np.bincount(labels, weights=np.einsum("ij,ij->i", ds, ds))
    return HartiganFit(labels, centers + origin_point, within, finished, iteration)
