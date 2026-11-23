"""Gap statistic across the merge sequence of a hierarchical fit."""

from itertools import batched
from numbers import Integral

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import pdist

from .field_error import FieldError
from .monte_carlo import MonteCarloCancelled
from .parallel import run_tasks


GAP_DATA = "Gap data"
GAP_PLOT = "Gap plot"
GAP_REPLICATES = "Gap reference datasets"
GAP_SEED = "Gap seed"
GAP_OPTIONS = {GAP_REPLICATES: 100, GAP_SEED: 42}
REFERENCE_WORKSPACE_BYTES = 512 * 1024**2


def check_gap_settings(options):
    replicates = options.get(GAP_REPLICATES, GAP_OPTIONS[GAP_REPLICATES])
    seed = options.get(GAP_SEED, GAP_OPTIONS[GAP_SEED])
    if not isinstance(replicates, Integral) or isinstance(replicates, bool) or not 5 <= replicates <= 100:
        raise FieldError(GAP_REPLICATES, "Choose between 5 and 100 Gap reference datasets.")
    if not isinstance(seed, Integral) or isinstance(seed, bool) or not 0 <= seed < 2**32:
        raise FieldError(GAP_SEED, "Gap seed must be an integer between 0 and 4294967295.")
    return int(replicates), int(seed)


def check_gap_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise MonteCarloCancelled("Hierarchical Gap calculation cancelled.")


def wcss_by_cut(tree, observations):
    """Accumulate within-cluster squared deviations along the merge sequence."""
    n, variables = observations.shape
    centers = np.empty((2 * n - 1, variables))
    sizes = np.ones(2 * n - 1, dtype=int)
    costs = np.empty(n - 1)
    total = 0.
    with np.errstate(over="ignore", invalid="ignore"):
        centers[:n] = observations - observations[0]
        for node, (left, right, _, _) in enumerate(tree, n):
            first, second = int(left), int(right)
            a, b = sizes[first], sizes[second]
            sizes[node] = a + b
            delta = centers[second] - centers[first]
            centers[node] = centers[first] + delta * (b / (a + b))
            # The joined cluster adds the squared separation of its centers,
            # weighted by their sample sizes, to the previous total.
            weighted_delta = delta * np.sqrt(a * b / (a + b))
            total += float(weighted_delta @ weighted_delta)
            costs[node - n] = total
    return costs[::-1]


def _reference_wcss(job, cancel=None):
    low, high, size, metric, method, seed, index = job
    check_gap_cancel(cancel)
    reference = np.random.default_rng([seed, index]).uniform(low, high, size)
    distances = pdist(reference, metric=metric)
    if not np.isfinite(distances).all() or np.any(distances < 0):
        raise ValueError("The chosen distance is undefined for the simulated Gap data.")
    check_gap_cancel(cancel)
    tree = linkage(distances, method=method)
    if not np.isfinite(tree).all():
        raise ValueError("The reference linkage produced non-finite merge distances.")
    check_gap_cancel(cancel)
    return wcss_by_cut(tree, reference)


def _log_wcss(costs):
    return np.log(costs, where=costs > 0, out=np.full_like(costs, np.nan))


def _reference_scores(points, metric, method, count, seed, cancel):
    low, high = points.min(axis=0), points.max(axis=0)
    jobs = ((low, high, points.shape, metric, method, seed, index) for index in range(count))
    # Bound simultaneous condensed distance matrices and SciPy's linkage workspace, even with a large pool.
    n, features = points.shape
    pairs = n * (n - 1) // 2
    working_bytes = 24 * pairs + 40 * n * features
    batch_size = max(1, REFERENCE_WORKSPACE_BYTES // working_bytes)
    references = []
    for batch in batched(jobs, batch_size):
        references.extend(run_tasks(_reference_wcss, batch, cancel=cancel, with_cancel=True))
    return _log_wcss(np.asarray(references))


def gap_data(tree, observations, metric, method, settings, cancel):
    check_gap_cancel(cancel)
    count, seed = settings
    # Keep both the reference distances and the squared deviations finite at extreme data scales.
    _, exponent = np.frexp(np.max(np.abs(observations)))
    exponent = int(exponent) if abs(exponent) > 400 else 0
    points = np.ldexp(observations, -exponent) if exponent else observations
    observed = _log_wcss(wcss_by_cut(tree, points))
    mean = np.full_like(observed, np.nan)
    se = np.full_like(observed, np.nan)
    if np.isfinite(observed).any():
        logs = _reference_scores(points, metric, method, count, seed, cancel)
        reference_defined = np.isfinite(logs).all(axis=0)
        mean[reference_defined] = logs[:, reference_defined].mean(axis=0)
        se[reference_defined] = logs[:, reference_defined].std(axis=0) * np.sqrt(1 + 1/count)
    check_gap_cancel(cancel)

    gap = mean - observed
    se[~np.isfinite(gap)] = np.nan
    defined = np.flatnonzero(np.isfinite(gap))
    recommended = np.zeros(len(gap), dtype=bool)
    if len(defined):
        within_one_se = np.flatnonzero(gap[:-1] >= gap[1:] - se[1:])
        recommended[within_one_se[0] if len(within_one_se) else defined[-1]] = True
    adjustment = 2 * exponent * np.log(2)
    return pd.DataFrame({"Number of clusters": np.arange(1, len(points)),
                         "Log W observed": observed + adjustment,
                         "Mean log W reference": mean + adjustment,
                         "Gap": gap, "Gap SE": se, "Recommended": recommended})
