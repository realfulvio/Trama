"""Whole analyses on several processes: the batches of the application (level 1 of the multicore plan).

A batch is any list of analyses that the application already computes one after the other on its worker
thread: the linked results recalculated after a table edit, the missing panels of a layout. Only the pure
part, ``workbench.analyse(method, frame, options)``, moves to a worker. The application keeps doing the rest
on its own thread, in the original order: Monte Carlo progress, styles, comparison brackets read from the
fresh results of other analyses, error handling.

Kept in the calling thread (never sent to a worker):
    * Monte Carlo studies, which report progress to the status bar while they run;
    * K-means stability, which reports progress too and spreads its own K-means fits over the pool (one
      granularity: its fits, never the whole analysis inside a worker);
    * results imported from other files (``Saved …`` methods), which render stored previews;
    * Join worksheets by key, which also reads a second worksheet (``join_data``) that a single-frame job
      does not carry;
    * XY series, which are cheaper than the transfer;
    * forest plots, before/after graphs and heat maps, whose figures keep local functions (axis converters,
      legend formatters) that cannot be pickled. Making those functions module-level lets them move to a
      worker too (see MAPPA.md in the delivery package).

Equivalence
    A worker receives copies of the frame and the options. ``tests/test_parallel_analyses.py`` checks that the
    analyses of the test suite do not change their options in place and that their results survive the
    transfer; ``strumenti/check_result_pickling.py`` in the delivery package runs the whole suite that way.
"""
from __future__ import annotations

from .forest_plot import FOREST_PLOT
from .heatmap import HEAT_MAP
from .kmeans_stability import METHOD as KMEANS_STABILITY
from .logistic_validation import METHOD as LOGISTIC_VALIDATION
from .monte_carlo import MONTE_CARLO
from .paired_graphs import BEFORE_AFTER
from .parallel import process_count, run_tasks
from .worksheet_join import METHOD as WORKSHEET_JOIN
from .workbench import SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT, SAVED_BINARY_RESULT, SAVED_EDITABLE_GRAPH, SAVED_XY
from .xy_series import XY_METHOD

LOCAL_METHODS = frozenset({MONTE_CARLO, KMEANS_STABILITY, LOGISTIC_VALIDATION, XY_METHOD, SAVED_XY, SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT,
                           SAVED_BINARY_RESULT, SAVED_EDITABLE_GRAPH, FOREST_PLOT, BEFORE_AFTER, HEAT_MAP,
                           WORKSHEET_JOIN})


def analysis_task(job, cancel=None):
    """Worker task: one ``analyse`` call. ``job`` is ``(method, frame, options)``."""
    from .workbench import analyse

    method, frame, options = job
    return analyse(method, frame, options, cancel=cancel)


def eligible(method, local_methods=LOCAL_METHODS):
    return method not in local_methods


def precompute(jobs, *, cancel=None, local_methods=LOCAL_METHODS):
    """Compute the eligible analyses of a batch on several processes.

    ``jobs`` is a list of ``(key, method, frame, options)``. The answer maps each computed key to an
    :class:`analisi.parallel.Outcome` (value or error). Keys that are missing were not computed: the caller
    computes them as before. With one process, or fewer than two eligible analyses, nothing is computed here.
    """
    chosen = [(key, method, frame, options) for key, method, frame, options in jobs
              if eligible(method, local_methods)]
    if len(chosen) < 2 or process_count() <= 1:
        return {}
    outcomes = run_tasks(analysis_task, [(method, frame, options) for _, method, frame, options in chosen],
                         cancel=cancel, with_cancel=True, outcomes=True, stop_queued=False)
    return {key: outcome for (key, *_), outcome in zip(chosen, outcomes, strict=True)}
